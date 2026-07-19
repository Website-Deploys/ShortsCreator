"""Prove Olympus durable restart/resume with local synthetic media only."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_root in (ROOT, SRC):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tools import validate_real_rendering_e2e as real_e2e  # noqa: E402

from olympus.data.repositories import (  # noqa: E402
    StorageOptimizationRepository,
    StorageProjectRepository,
    StorageWorkflowRepository,
)
from olympus.data.storage.local import LocalStorage  # noqa: E402
from olympus.domain.contracts.workflow import EngineRunner, EngineRunResult  # noqa: E402
from olympus.domain.entities.project import Project  # noqa: E402
from olympus.domain.entities.workflow import EventType, Job, WorkflowEvent  # noqa: E402
from olympus.jobs import LocalDurableJobStore  # noqa: E402
from olympus.platform.config import get_settings  # noqa: E402
from olympus.rendering.artifacts import (  # noqa: E402
    canonical_render_manifest_path,
    resolve_render_manifest,
)
from olympus.validation.durable_resume import (  # noqa: E402
    DURABLE_RESUME_REPORT_SUBDIR,
    DurableOutputValidationV1,
    DurableRestartResumeResultV1,
    classify_stage_execution,
    detect_duplicate_outputs,
    detect_impossible_stage_transitions,
    durable_resume_self_check,
    interruption_plan,
    parse_checkpoint_snapshot,
    validate_rendered_output,
    validate_resume_final_payload,
    validate_resume_manifests,
    validated_durable_resume_report_dir,
    write_durable_resume_report,
)
from olympus.validation.real_video import as_dict, as_list, run_ffprobe  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / DURABLE_RESUME_REPORT_SUBDIR
DEFAULT_STORAGE_ROOT = ROOT / "storage_data"
DEFAULT_DURATION_SECONDS = 60.0
DEFAULT_TIMEOUT_SECONDS = 1800.0
DEFAULT_RENDER_PRESET = "veryfast"
DEFAULT_RENDER_THREADS = 1
DEFAULT_FILTER_THREADS = 1
WORKFLOW_KEY_TEMPLATE = "workflow/{project_id}/workflow.json"

JsonDict = dict[str, Any]


class DeterministicRenderingInterruptionRunner(EngineRunner):
    """Hold a claimed rendering job before FFmpeg so restart is deterministic."""

    engine = "rendering"

    def __init__(
        self,
        delegate: EngineRunner,
        storage: LocalStorage,
    ) -> None:
        self._delegate = delegate
        self._storage = storage
        self.entered = asyncio.Event()
        self._release = asyncio.Event()
        self.partial_storage_key: str | None = None

    async def run(self, project: Project, job: Job) -> EngineRunResult:
        self.partial_storage_key = (
            f"render/{project.id}/work/validator_interrupted_output.mp4.part"
        )
        await self._storage.put(
            self.partial_storage_key,
            b"",
            content_type="application/octet-stream",
        )
        job.log(
            "validator interruption gate entered after durable rendering claim "
            "and before FFmpeg launch"
        )
        self.entered.set()
        await self._release.wait()
        return await self._delegate.run(project, job)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def isolated_synthetic_storage_root(
    base_root: Path,
    mode: str,
    *,
    run_id: str | None = None,
) -> Path:
    """Give every synthetic restart proof an independent recovery namespace."""

    safe_mode = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in mode
    )
    return (
        base_root
        / "validation"
        / "durable_restart_resume"
        / safe_mode
        / (run_id or uuid4().hex)
    ).resolve()


def _runtime(
    storage: LocalStorage,
    *,
    duration_seconds: float,
    durable_root: Path,
    ffmpeg_binary: str,
    ffprobe_binary: str,
    timeout_seconds: float,
    render_preset: str,
    render_threads: int,
    filter_threads: int,
) -> real_e2e.RuntimeBundle:
    durable_store = LocalDurableJobStore(durable_root)
    return real_e2e._build_runtime(
        storage,
        duration_seconds=duration_seconds,
        ffmpeg_binary=ffmpeg_binary,
        ffprobe_binary=ffprobe_binary,
        timeout_seconds=timeout_seconds,
        render_preset=render_preset,
        render_threads=render_threads,
        render_filter_threads=filter_threads,
        durable_store=durable_store,
    )


def _force_local_only_settings() -> JsonDict:
    settings = get_settings().trend_research
    settings.enabled = True
    settings.provider = "evergreen"
    settings.allow_official_source_refresh = False
    settings.allow_configured_web_search = False
    settings.allow_live_web_provider = False
    settings.force_live_refresh = False
    settings.configured_search_endpoint = None
    settings.web_search_endpoint = None
    settings.web_search_api_key = None
    return {
        "external_access_allowed": False,
        "trend_provider": settings.provider,
        "official_refresh_allowed": settings.allow_official_source_refresh,
        "configured_web_search_allowed": settings.allow_configured_web_search,
        "live_web_provider_allowed": settings.allow_live_web_provider,
    }


def _source_fixture(
    report_dir: Path,
    *,
    ffmpeg_binary: str,
    duration_seconds: float,
) -> tuple[Path, JsonDict]:
    media_path = report_dir / "runtime" / "durable_resume_source.mp4"
    if media_path.is_file():
        probe = run_ffprobe(media_path)
        duration = float(probe.get("container_duration") or 0.0)
        if probe.get("passed") and probe.get("has_audio") and duration >= duration_seconds:
            return media_path, {
                "path": str(media_path.resolve()),
                "duration_seconds": duration,
                "reused": True,
                "ffprobe": probe,
            }
    generated = real_e2e.generate_synthetic_media(
        media_path,
        ffmpeg_binary=ffmpeg_binary,
        duration_seconds=duration_seconds,
    )
    return media_path, {**generated, "reused": False}


async def _persisted_snapshot(
    storage: LocalStorage,
    project_id: str,
    *,
    durable_root: Path,
    workflow_id: str | None = None,
) -> JsonDict:
    workflow_key = WORKFLOW_KEY_TEMPLATE.format(project_id=project_id)
    if not await storage.exists(workflow_key):
        snapshot = parse_checkpoint_snapshot(None)
        snapshot["errors"] = [f"Persisted workflow is missing: {workflow_key}"]
        return snapshot
    raw = await storage.get(workflow_key)
    snapshot = parse_checkpoint_snapshot(raw)
    snapshot["artifact_path"] = workflow_key
    snapshot["artifact_checksum"] = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    if workflow_id:
        try:
            durable = LocalDurableJobStore(durable_root).get(workflow_id)
        except Exception as exc:
            snapshot["durable_mirror"] = {
                "readable": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            snapshot["corrupted"] = True
            snapshot["errors"] = [
                *as_list(snapshot.get("errors")),
                "Durable job mirror is unreadable.",
            ]
        else:
            snapshot["durable_mirror"] = {
                "readable": isinstance(durable, dict),
                "status": durable.get("status") if isinstance(durable, dict) else None,
                "job_id": durable.get("job_id") if isinstance(durable, dict) else None,
            }
    return snapshot


async def _install_checkpoint_boundary_pause(
    runtime: real_e2e.RuntimeBundle,
    *,
    project_id: str,
    stage: str,
    interrupted: asyncio.Event,
) -> None:
    async def handler(event: WorkflowEvent) -> None:
        if (
            interrupted.is_set()
            or event.type is not EventType.JOB_COMPLETED
            or event.stage != stage
        ):
            return
        await runtime.workflow.pause(project_id)
        interrupted.set()

    runtime.workflow.subscribe(handler)


async def _wait_for_interruption(
    event: asyncio.Event,
    *,
    timeout_seconds: float,
) -> None:
    await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
    await asyncio.sleep(0)


async def _inspect_outputs(
    storage: LocalStorage,
    project_id: str,
) -> tuple[list[DurableOutputValidationV1], JsonDict, list[str]]:
    resolution = await resolve_render_manifest(storage, project_id)
    manifest = as_dict(resolution.manifest)
    outputs: list[DurableOutputValidationV1] = []
    warnings = [*resolution.warnings, *resolution.errors]
    referenced_keys: set[str] = set()
    for index, render in enumerate(as_list(manifest.get("renders"))):
        item = as_dict(render)
        clip_id = str(item.get("clip_id") or f"clip_{index + 1}")
        storage_key = str(item.get("storage_key") or "")
        referenced_keys.add(storage_key)
        local_value = storage.local_path(storage_key) if storage_key else None
        outputs.append(
            validate_rendered_output(
                clip_id=clip_id,
                storage_key=storage_key,
                path=Path(local_value) if local_value else None,
                probe_function=run_ffprobe,
            )
        )
    for key in await storage.list_keys(f"render/{project_id}/"):
        if key in referenced_keys or not key.lower().endswith((".part", ".tmp")):
            continue
        local_value = storage.local_path(key)
        outputs.append(
            validate_rendered_output(
                clip_id="validator_interrupted_partial",
                storage_key=key,
                path=Path(local_value) if local_value else None,
                probe_function=run_ffprobe,
            )
        )
    duplicate = detect_duplicate_outputs(outputs)
    duplicate_by_clip = {
        str(item.get("clip_id")): item.get("duplicate_of")
        for item in as_list(duplicate.get("outputs"))
        if isinstance(item, dict)
    }
    for output in outputs:
        output.duplicate_of = (
            str(duplicate_by_clip[output.clip_id])
            if duplicate_by_clip.get(output.clip_id)
            else None
        )
    return outputs, duplicate, warnings


async def _final_evidence(
    *,
    storage: LocalStorage,
    storage_root: Path,
    project_id: str,
    ffprobe_binary: str,
) -> JsonDict:
    inspection = await real_e2e.inspect_existing_project(
        project_id,
        storage_root=storage_root,
        ffprobe_binary=ffprobe_binary,
    )
    resolution = await resolve_render_manifest(storage, project_id)
    manifest = as_dict(resolution.manifest)
    render_path = canonical_render_manifest_path(project_id)
    render_present = bool(
        await storage.exists(render_path)
        and resolution.artifact_path == render_path
        and manifest.get("status") == "completed"
    )
    optimization_path = f"optimization/{project_id}/index.json"
    optimization = await StorageOptimizationRepository(storage).load(project_id)
    optimization_present = bool(
        await storage.exists(optimization_path)
        and optimization is not None
        and optimization.status.value == "completed"
    )
    outputs, duplicate, output_warnings = await _inspect_outputs(storage, project_id)
    accepted = [
        output
        for output in outputs
        if not output.partial_detected
        and output.duplicate_of is None
        and output.storage_key in {
            str(item.get("storage_key") or "")
            for item in as_list(manifest.get("renders"))
            if isinstance(item, dict)
        }
    ]
    payload = {
        "project_id": project_id,
        "manifest": manifest,
        "clips": [as_dict(item) for item in as_list(manifest.get("renders"))],
        "download_urls": [
            f"/api/v1/projects/{project_id}/rendering/clips/"
            f"{as_dict(item).get('clip_id')}/download"
            for item in as_list(manifest.get("renders"))
            if as_dict(item).get("clip_id")
        ],
    }
    payload_validation = validate_resume_final_payload(payload)
    return {
        "inspection": inspection,
        "render_manifest_present": render_present,
        "render_manifest_path": render_path,
        "optimization_manifest_present": optimization_present,
        "optimization_manifest_path": optimization_path,
        "outputs": outputs,
        "accepted_mp4_count": len(accepted),
        "duplicate": duplicate,
        "partial_outputs_detected": any(output.partial_detected for output in outputs),
        "final_payload": payload,
        "final_payload_valid": bool(
            payload_validation.get("passed")
            and inspection.get("api_payload_valid")
            and inspection.get("frontend_payload_valid")
        ),
        "warnings": output_warnings,
        "errors": [
            *as_list(payload_validation.get("errors")),
            *(
                []
                if inspection.get("passed")
                else ["Final persisted project inspection did not pass."]
            ),
        ],
    }


async def run_synthetic_resume_proof(args: argparse.Namespace) -> DurableRestartResumeResultV1:
    plan = interruption_plan(
        interrupt_after=args.interrupt_after,
        interrupt_during=args.interrupt_during,
    )
    if not plan.get("valid"):
        return DurableRestartResumeResultV1(
            project_id=None,
            mode="invalid",
            interruption_stage=None,
            interruption_method=None,
            errors=[str(item) for item in as_list(plan.get("errors"))],
        )

    started = time.perf_counter()
    mode = str(plan["mode"])
    result = DurableRestartResumeResultV1(
        project_id=None,
        mode=mode,
        interruption_stage=str(plan["stage"]),
        interruption_method=str(plan["method"]),
    )
    result.warnings.extend(
        [
            "Synthetic local media and a deterministic transcript fixture were used.",
            "This proves a new WorkflowService instance, not an operating-system process kill.",
            "Manual audiovisual playback was not performed.",
        ]
    )
    if plan["stage"] == "rendering":
        result.warnings.append(
            "The rendering interruption occurs after the durable rendering job is claimed "
            "and before FFmpeg starts; no live FFmpeg process is killed on Windows."
        )

    run_storage_root = isolated_synthetic_storage_root(args.storage_root, mode)
    storage = LocalStorage(root=str(run_storage_root))
    durable_root = run_storage_root / "durable_jobs"
    runtime_one: real_e2e.RuntimeBundle | None = None
    runtime_two: real_e2e.RuntimeBundle | None = None
    interrupted_partial: DurableOutputValidationV1 | None = None
    try:
        local_only = _force_local_only_settings()
        media_path, source = _source_fixture(
            args.report_dir,
            ffmpeg_binary=args.ffmpeg_binary,
            duration_seconds=args.duration_seconds,
        )
        probe = run_ffprobe(media_path)
        duration = float(probe.get("container_duration") or 0.0)
        project = await real_e2e.create_local_project(
            media_path,
            storage,
            probe,
            desired_clip_count=args.desired_clip_count,
        )
        result.project_id = project.id
        runtime_one = _runtime(
            storage,
            duration_seconds=duration,
            durable_root=durable_root,
            ffmpeg_binary=args.ffmpeg_binary,
            ffprobe_binary=args.ffprobe_binary,
            timeout_seconds=args.timeout_seconds,
            render_preset=args.render_preset,
            render_threads=args.render_threads,
            filter_threads=args.render_filter_threads,
        )
        interrupted = asyncio.Event()
        render_gate: DeterministicRenderingInterruptionRunner | None = None
        if plan["stage"] == "rendering":
            render_gate = DeterministicRenderingInterruptionRunner(
                runtime_one.runners["rendering"],
                storage,
            )
            runtime_one.runners["rendering"] = render_gate
            interrupted = render_gate.entered
        else:
            await _install_checkpoint_boundary_pause(
                runtime_one,
                project_id=project.id,
                stage=str(plan["stage"]),
                interrupted=interrupted,
            )

        workflow = await runtime_one.workflow.start(
            project,
            source=f"durable_restart_resume:{mode}",
            idempotency_key=f"durable_restart_resume:{mode}:{project.id}",
        )
        await _wait_for_interruption(interrupted, timeout_seconds=args.timeout_seconds)
        await runtime_one.workflow.stop_pool()
        runtime_one = None

        before = await _persisted_snapshot(
            storage,
            project.id,
            durable_root=durable_root,
            workflow_id=workflow.workflow_id,
        )
        result.checkpoint_before_restart = before
        result.stages_before_restart = [
            as_dict(item) for item in as_list(before.get("stages"))
        ]
        if render_gate is not None and render_gate.partial_storage_key:
            partial_key = render_gate.partial_storage_key
            partial_local = storage.local_path(partial_key)
            interrupted_partial = validate_rendered_output(
                clip_id="validator_interrupted_partial",
                storage_key=partial_key,
                path=Path(partial_local) if partial_local else None,
                probe_function=run_ffprobe,
            )
            result.checkpoint_before_restart["interrupted_partial_output"] = (
                interrupted_partial.to_dict()
            )
        if before.get("readable") is not True:
            result.errors.append("Checkpoint before restart is unreadable.")
        if before.get("corrupted") is True:
            result.errors.extend(str(item) for item in as_list(before.get("errors")))

        result.resume_started_at = utc_now_iso()
        runtime_two = _runtime(
            storage,
            duration_seconds=duration,
            durable_root=durable_root,
            ffmpeg_binary=args.ffmpeg_binary,
            ffprobe_binary=args.ffprobe_binary,
            timeout_seconds=args.timeout_seconds,
            render_preset=args.render_preset,
            render_threads=args.render_threads,
            filter_threads=args.render_filter_threads,
        )
        recovered_jobs = await runtime_two.workflow.recover()
        if plan["stage"] != "rendering":
            await runtime_two.workflow.resume(project.id)
        final_workflow = await runtime_two.workflow.wait_for(
            project.id,
            timeout=args.timeout_seconds,
        )
        await runtime_two.workflow.stop_pool()
        runtime_two = None
        result.resume_finished_at = utc_now_iso()

        after = await _persisted_snapshot(
            storage,
            project.id,
            durable_root=durable_root,
            workflow_id=workflow.workflow_id,
        )
        after["recovered_jobs"] = recovered_jobs
        result.checkpoint_after_restart = after
        result.stages_after_resume = [
            as_dict(item) for item in as_list(after.get("stages"))
        ]
        transition_errors = detect_impossible_stage_transitions(before, after)
        result.corrupted_checkpoints_detected = bool(
            before.get("corrupted") or after.get("corrupted") or transition_errors
        )
        result.errors.extend(transition_errors)

        accounting = classify_stage_execution(before, after)
        result.stage_execution_counts = {
            str(name): int(count)
            for name, count in as_dict(accounting.get("counts")).items()
        }
        result.stages_reused = [str(item) for item in as_list(accounting.get("reused"))]
        result.stages_rerun = [str(item) for item in as_list(accounting.get("rerun"))]
        result.stages_after_resume = [
            stage.to_dict() for stage in accounting.get("stages", [])
        ]
        completed_before = {
            str(stage.get("name"))
            for stage in result.stages_before_restart
            if stage.get("status") == "completed"
        }
        missing_reuse = sorted(completed_before.difference(result.stages_reused))
        if missing_reuse:
            result.errors.append(
                "Completed stages were not reused after restart: "
                + ", ".join(missing_reuse)
            )
        if plan["stage"] == "rendering" and "rendering" not in result.stages_rerun:
            result.errors.append("Interrupted rendering was not explicitly rerun.")

        evidence = await _final_evidence(
            storage=storage,
            storage_root=run_storage_root,
            project_id=project.id,
            ffprobe_binary=args.ffprobe_binary,
        )
        result.outputs = list(evidence["outputs"])
        if interrupted_partial is not None:
            result.outputs.append(interrupted_partial)
        result.render_manifest_present = bool(evidence["render_manifest_present"])
        result.optimization_manifest_present = bool(
            evidence["optimization_manifest_present"]
        )
        result.accepted_mp4_count = int(evidence["accepted_mp4_count"])
        result.final_payload_valid = bool(evidence["final_payload_valid"])
        result.duplicate_outputs_detected = bool(evidence["duplicate"].get("detected"))
        result.partial_outputs_detected = bool(
            evidence["partial_outputs_detected"]
            or (interrupted_partial and interrupted_partial.partial_detected)
        )
        result.warnings.extend(str(item) for item in evidence["warnings"])
        result.errors.extend(str(item) for item in evidence["errors"])

        manifest_validation = validate_resume_manifests(
            render_manifest_present=result.render_manifest_present,
            optimization_manifest_present=result.optimization_manifest_present,
        )
        result.errors.extend(str(item) for item in as_list(manifest_validation.get("errors")))
        accepted_partial = [
            output.storage_key
            for output in result.outputs
            if output.partial_detected
            and output.storage_key
            in {
                str(item.get("storage_key") or "")
                for item in as_list(
                    as_dict(evidence["final_payload"].get("manifest")).get("renders")
                )
                if isinstance(item, dict)
            }
        ]
        if accepted_partial:
            result.errors.append(
                "Render manifest accepted partial outputs: " + ", ".join(accepted_partial)
            )
        if result.duplicate_outputs_detected:
            result.errors.append("Duplicate accepted render outputs were detected.")
        if result.accepted_mp4_count < 1:
            result.errors.append("No real MP4 passed output validation.")
        if final_workflow.status.value != "completed":
            result.errors.append(
                f"Workflow finished with status {final_workflow.status.value!r}."
            )
        if plan["stage"] == "rendering" and recovered_jobs < 1:
            result.errors.append("Recovery did not requeue the interrupted rendering job.")
        expected_recovered_jobs = 1 if plan["stage"] == "rendering" else 0
        if recovered_jobs != expected_recovered_jobs:
            result.errors.append(
                "Recovery count does not match the isolated interrupted workflow: "
                f"expected {expected_recovered_jobs}, observed {recovered_jobs}."
            )
        result.checkpoint_after_restart["validation_context"] = {
            "source_fixture": source,
            "local_only_settings": local_only,
            "final_inspection_passed": evidence["inspection"].get("passed"),
            "render_manifest_path": evidence["render_manifest_path"],
            "optimization_manifest_path": evidence["optimization_manifest_path"],
            "first_run_after_restart": accounting.get("first_run_after_restart"),
            "isolated_storage_root": str(run_storage_root),
            "interrupted_partial_cleaned_before_final_validation": bool(
                interrupted_partial
                and not await storage.exists(interrupted_partial.storage_key)
            ),
        }
    except Exception as exc:
        result.errors.append(f"{type(exc).__name__}: {exc}")
        result.checkpoint_after_restart.setdefault(
            "runtime_exception",
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=30),
            },
        )
    finally:
        if runtime_one is not None:
            try:
                await runtime_one.workflow.stop_pool()
            except Exception as exc:
                result.errors.append(f"First worker-pool shutdown failed: {exc}")
        if runtime_two is not None:
            try:
                await runtime_two.workflow.stop_pool()
            except Exception as exc:
                result.errors.append(f"Second worker-pool shutdown failed: {exc}")

    result.total_runtime_seconds = round(time.perf_counter() - started, 3)
    result.warnings = list(dict.fromkeys(result.warnings))
    result.errors = list(dict.fromkeys(result.errors))
    result.resume_successful = bool(
        result.checkpoint_before_restart.get("readable")
        and result.checkpoint_after_restart.get("readable")
        and not result.corrupted_checkpoints_detected
        and result.render_manifest_present
        and result.optimization_manifest_present
        and result.accepted_mp4_count >= 1
        and result.final_payload_valid
        and not result.duplicate_outputs_detected
        and not result.errors
    )
    return result


async def inspect_existing_project(args: argparse.Namespace) -> DurableRestartResumeResultV1:
    project_id = str(args.project_id)
    storage = LocalStorage(root=str(args.storage_root))
    durable_root = args.storage_root / "durable_jobs"
    result = DurableRestartResumeResultV1(
        project_id=project_id,
        mode="project_id",
        interruption_stage=None,
        interruption_method="inspection_only_no_mutation_or_rerender",
        warnings=[
            "Project-id mode inspects persisted state only; it does not prove a new restart.",
            "Manual audiovisual playback was not performed.",
        ],
    )
    project = await StorageProjectRepository(storage).get(project_id)
    if project is None:
        result.errors.append("Project does not exist in configured storage.")
        return result
    workflow = await StorageWorkflowRepository(storage).load(project_id)
    workflow_id = workflow.workflow_id if workflow else None
    before = await _persisted_snapshot(
        storage,
        project_id,
        durable_root=durable_root,
        workflow_id=workflow_id,
    )
    evidence = await _final_evidence(
        storage=storage,
        storage_root=args.storage_root,
        project_id=project_id,
        ffprobe_binary=args.ffprobe_binary,
    )
    after = await _persisted_snapshot(
        storage,
        project_id,
        durable_root=durable_root,
        workflow_id=workflow_id,
    )
    if before.get("artifact_checksum") != after.get("artifact_checksum"):
        result.errors.append("Project-id inspection mutated the workflow checkpoint.")
    accounting = classify_stage_execution(before, after)
    result.checkpoint_before_restart = before
    result.checkpoint_after_restart = after
    result.stages_before_restart = [
        as_dict(item) for item in as_list(before.get("stages"))
    ]
    result.stages_after_resume = [stage.to_dict() for stage in accounting["stages"]]
    result.stage_execution_counts = accounting["counts"]
    result.stages_reused = accounting["reused"]
    result.stages_rerun = accounting["rerun"]
    result.corrupted_checkpoints_detected = bool(
        before.get("corrupted") or after.get("corrupted")
    )
    result.outputs = list(evidence["outputs"])
    result.render_manifest_present = bool(evidence["render_manifest_present"])
    result.optimization_manifest_present = bool(evidence["optimization_manifest_present"])
    result.accepted_mp4_count = int(evidence["accepted_mp4_count"])
    result.final_payload_valid = bool(evidence["final_payload_valid"])
    result.duplicate_outputs_detected = bool(evidence["duplicate"].get("detected"))
    result.partial_outputs_detected = bool(evidence["partial_outputs_detected"])
    result.warnings.extend(str(item) for item in evidence["warnings"])
    result.errors.extend(str(item) for item in evidence["errors"])
    result.errors = list(dict.fromkeys(result.errors))
    result.resume_successful = bool(
        before.get("readable")
        and after.get("readable")
        and not result.corrupted_checkpoints_detected
        and result.render_manifest_present
        and result.optimization_manifest_present
        and result.accepted_mp4_count >= 1
        and result.final_payload_valid
        and not result.duplicate_outputs_detected
        and not result.errors
    )
    return result


async def run_selected_mode(args: argparse.Namespace) -> DurableRestartResumeResultV1 | JsonDict:
    if args.self_check:
        return durable_resume_self_check(
            storage_root=args.storage_root,
            report_dir=args.report_dir,
            ffmpeg_binary=args.ffmpeg_binary,
            ffprobe_binary=args.ffprobe_binary,
        )
    if args.project_id:
        return await inspect_existing_project(args)
    return await run_synthetic_resume_proof(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--synthetic", action="store_true")
    modes.add_argument("--project-id")
    interruption = parser.add_mutually_exclusive_group()
    interruption.add_argument("--interrupt-after", choices=("analysis", "editing"))
    interruption.add_argument("--interrupt-during", choices=("rendering",))
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--ffmpeg-binary", default="ffmpeg")
    parser.add_argument("--ffprobe-binary", default="ffprobe")
    parser.add_argument("--duration-seconds", type=float, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--desired-clip-count", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--render-preset",
        choices=("ultrafast", "superfast", "veryfast", "faster", "fast", "medium"),
        default=DEFAULT_RENDER_PRESET,
    )
    parser.add_argument("--render-threads", type=int, default=DEFAULT_RENDER_THREADS)
    parser.add_argument("--render-filter-threads", type=int, default=DEFAULT_FILTER_THREADS)
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.synthetic and not (args.interrupt_after or args.interrupt_during):
        parser.error("--synthetic requires --interrupt-after or --interrupt-during")
    if not args.synthetic and (args.interrupt_after or args.interrupt_during):
        parser.error("interruption controls require --synthetic")
    if not 60.0 <= args.duration_seconds <= 120.0:
        parser.error("--duration-seconds must be between 60 and 120")
    if args.desired_clip_count < 1 or args.desired_clip_count > 3:
        parser.error("--desired-clip-count must be between 1 and 3")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    args.storage_root = args.storage_root.resolve()
    args.report_dir = validated_durable_resume_report_dir(
        args.report_dir,
        workspace_root=ROOT,
    )
    try:
        result = asyncio.run(run_selected_mode(args))
    except KeyboardInterrupt:
        print("Durable restart/resume validation interrupted by operator.", file=sys.stderr)
        return 130
    except Exception as exc:
        failure = {
            "mode": "validator_failure",
            "resume_successful": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "traceback": traceback.format_exc(limit=30),
        }
        paths = write_durable_resume_report(failure, args.report_dir, workspace_root=ROOT)
        print(json.dumps({**failure, "reports": paths}, indent=2))
        return 1
    payload = result.to_dict() if isinstance(result, DurableRestartResumeResultV1) else result
    if args.self_check:
        payload = {
            "mode": "self_check",
            "resume_successful": bool(payload.get("passed")),
            **payload,
        }
    paths = write_durable_resume_report(payload, args.report_dir, workspace_root=ROOT)
    print(json.dumps({**payload, "reports": paths}, indent=2))
    passed = bool(
        payload.get("passed")
        if args.self_check
        else payload.get("resume_successful")
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

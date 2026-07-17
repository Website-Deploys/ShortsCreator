"""Validate the Rendering -> durable checkpoint -> Optimization handoff."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.api.dependencies import build_workflow_service  # noqa: E402
from olympus.data.repositories import (  # noqa: E402
    StorageProjectRepository,
    StorageRenderManifestRepository,
    StorageWorkflowRepository,
)
from olympus.data.storage import build_storage  # noqa: E402
from olympus.data.storage.local import LocalStorage  # noqa: E402
from olympus.domain.entities.project import Project, ProjectStatus  # noqa: E402
from olympus.domain.entities.workflow import (  # noqa: E402
    WORKFLOW_STAGES,
    Job,
    JobStatus,
    Workflow,
    WorkflowStatus,
)
from olympus.jobs import CheckpointValidator  # noqa: E402
from olympus.platform.config import get_settings  # noqa: E402
from olympus.rendering.artifacts import (  # noqa: E402
    canonical_render_manifest_path,
    legacy_render_manifest_path,
    resolve_render_manifest,
)
from olympus.services.workflow import WorkflowService  # noqa: E402
from olympus.utils import new_id, utc_now  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "render_checkpoint_handoff"
SYNTHETIC_ROOT = ROOT / "work" / "rnd_validation" / "render_checkpoint"


class _SimulatedProbeValidator(CheckpointValidator):
    """Exercise checkpoint control flow without claiming fake bytes are real media."""

    def _ffprobe_passes(self, path: Path) -> bool | None:
        return path.is_file()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--simulate", action="store_true")
    modes.add_argument("--project-id")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Repair a validated project's stale rendering checkpoint path.",
    )
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parsed = parser.parse_args()
    if parsed.repair and not parsed.project_id:
        parser.error("--repair requires --project-id")
    return parsed


def _project(project_id: str) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="Render Checkpoint Handoff Validation",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=24,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=20.0,
        width=1920,
        height=1080,
        status=ProjectStatus.PROCESSING,
        created_at=now,
        updated_at=now,
    )


def _manifest(project_id: str, render_key: str, data: bytes) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "status": "completed",
        "rendering_version": "handoff-v2-validation",
        "renders": [
            {
                "clip_id": "validation_clip",
                "storage_key": render_key,
                "size_bytes": len(data),
                "checksum": f"sha256:{hashlib.sha256(data).hexdigest()}",
            }
        ],
    }


async def _write_canonical_fixture(storage: LocalStorage, project_id: str) -> None:
    render_key = f"render/{project_id}/clips/validation_clip.mp4"
    data = b"synthetic-checkpoint-bytes-not-real-media"
    await storage.put(render_key, data, content_type="video/mp4")
    run_index = {
        "project_id": project_id,
        "pipeline_version": "handoff-v2-validation",
        "status": "completed",
        "created_at": utc_now().isoformat(),
        "updated_at": utc_now().isoformat(),
        "stages": [],
        "render_manifest": _manifest(project_id, render_key, data),
    }
    await storage.put(
        canonical_render_manifest_path(project_id),
        json.dumps(run_index, indent=2).encode(),
        content_type="application/json",
    )


def _synthetic_storage(mode: str) -> tuple[LocalStorage, Path]:
    root = SYNTHETIC_ROOT / f"{mode}_{new_id('run')}"
    return LocalStorage(root=str(root / "storage")), root


def _base_report(mode: str, project_id: str | None) -> dict[str, Any]:
    return {
        "mode": mode,
        "project_id": project_id,
        "created_at": utc_now().isoformat(),
        "canonical_path": (
            canonical_render_manifest_path(project_id) if project_id else None
        ),
        "legacy_path": legacy_render_manifest_path(project_id) if project_id else None,
        "inspection": None,
        "repair": None,
        "warnings": [],
        "errors": [],
        "passed": False,
    }


async def _self_check() -> dict[str, Any]:
    project_id = "proj_render_checkpoint_self_check"
    report = _base_report("self-check", project_id)
    storage, root = _synthetic_storage("self_check")
    report["synthetic_root"] = str(root)
    report["media_validation"] = "simulated ffprobe result; no real media used"
    await _write_canonical_fixture(storage, project_id)
    validator = _SimulatedProbeValidator(storage)
    resolution = await resolve_render_manifest(storage, project_id)
    inspection = await validator.inspect_render(project_id)
    missing = await validator.inspect_render("proj_render_checkpoint_missing")
    report["inspection"] = inspection
    report["missing_manifest_rejected"] = missing.get("valid") is False
    report["resolver"] = {
        "artifact_path": resolution.artifact_path,
        "manifest_source_path": resolution.manifest_source_path,
        "searched_paths": resolution.searched_paths,
    }
    report["passed"] = bool(
        inspection.get("valid")
        and inspection.get("artifact_path") == canonical_render_manifest_path(project_id)
        and resolution.manifest_exists
        and missing.get("valid") is False
    )
    if not report["passed"]:
        report["errors"].append("Canonical self-check did not satisfy all assertions.")
    return report


def _failed_workflow(project: Project) -> Workflow:
    now = utc_now()
    workflow_id = new_id("wf")
    jobs: list[Job] = []
    for spec in WORKFLOW_STAGES:
        if spec.stage == "rendering":
            status = JobStatus.DEAD
        elif spec.stage == "optimization":
            status = JobStatus.BLOCKED
        else:
            status = JobStatus.COMPLETED
        job = Job(
            job_id=new_id("job"),
            workflow_id=workflow_id,
            project_id=project.id,
            engine=spec.engine,
            stage=spec.stage,
            depends_on=spec.depends_on,
            status=status,
            created_at=now,
            finished_at=now if status in {JobStatus.COMPLETED, JobStatus.DEAD} else None,
        )
        if spec.stage == "rendering":
            job.error = "stale legacy render checkpoint path"
            job.checkpoint = {
                "artifact_path": legacy_render_manifest_path(project.id),
                "artifact_version": "handoff-v2-validation",
            }
        jobs.append(job)
    return Workflow(
        workflow_id=workflow_id,
        project_id=project.id,
        status=WorkflowStatus.FAILED,
        created_at=now,
        updated_at=now,
        jobs=jobs,
    )


async def _simulate() -> dict[str, Any]:
    project_id = "proj_render_checkpoint_simulation"
    report = _base_report("simulate", project_id)
    storage, root = _synthetic_storage("simulate")
    report["synthetic_root"] = str(root)
    report["media_validation"] = "simulated ffprobe result; no real media used"
    project = _project(project_id)
    project_repo = StorageProjectRepository(storage)
    workflow_repo = StorageWorkflowRepository(storage)
    await project_repo.save(project)
    await storage.put(project.storage_key, b"synthetic-source", content_type="video/mp4")
    await workflow_repo.save(_failed_workflow(project))
    await _write_canonical_fixture(storage, project_id)
    validator = _SimulatedProbeValidator(storage)
    service = WorkflowService(
        repository=workflow_repo,
        project_repo=project_repo,
        runners={},
        run_in_process=False,
        checkpoint_validator=validator,
    )
    repair = await service.repair_render_checkpoint_artifact_path(project_id)
    repaired = await workflow_repo.load(project_id)
    manifest = await StorageRenderManifestRepository(storage).load(project_id)
    missing = await validator.inspect_render("proj_render_checkpoint_missing")
    rendering = repaired.job("rendering") if repaired else None
    optimization = repaired.job("optimization") if repaired else None
    report["inspection"] = await validator.inspect_render(project_id)
    report["repair"] = repair
    report["optimization_read_canonical_manifest"] = bool(manifest and manifest.renders)
    report["missing_manifest_rejected"] = missing.get("valid") is False
    report["passed"] = bool(
        repair.get("repaired")
        and rendering is not None
        and rendering.status is JobStatus.COMPLETED
        and rendering.checkpoint.get("artifact_path")
        == canonical_render_manifest_path(project_id)
        and optimization is not None
        and optimization.status is JobStatus.READY
        and manifest is not None
        and manifest.renders
        and missing.get("valid") is False
    )
    if not report["passed"]:
        report["errors"].append("Synthetic repair did not satisfy all handoff assertions.")
    return report


async def _inspect_project(project_id: str, *, repair: bool) -> dict[str, Any]:
    report = _base_report("project-repair" if repair else "project-inspect", project_id)
    settings = get_settings()
    storage = build_storage()
    workflow = await StorageWorkflowRepository(storage).load(project_id)
    rendering = workflow.job("rendering") if workflow else None
    stored_path = None
    if rendering is not None:
        value = rendering.checkpoint.get("artifact_path")
        stored_path = value if isinstance(value, str) else None
    validator = CheckpointValidator(
        storage,
        ffprobe_binary=settings.rendering.ffprobe_binary,
    )
    inspection = await validator.inspect_render(
        project_id,
        stored_artifact_path=stored_path,
    )
    report["workflow_exists"] = workflow is not None
    report["stored_rendering_status"] = rendering.status.value if rendering else None
    report["inspection"] = inspection
    if repair:
        if not inspection.get("valid"):
            report["warnings"].append(
                "Repair was not attempted because manifest and MP4 validation failed."
            )
        elif workflow is None:
            report["errors"].append("Repair requires a persisted workflow.")
        else:
            service = build_workflow_service(run_in_process=False)
            report["repair"] = await service.repair_render_checkpoint_artifact_path(project_id)
    report["passed"] = bool(
        inspection.get("valid")
        and (not repair or (report.get("repair") or {}).get("repaired"))
    )
    if not report["passed"] and not report["errors"]:
        report["errors"].append("Project render checkpoint is not valid.")
    return report


def _write_reports(report: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "render_checkpoint_handoff_report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    inspection = report.get("inspection") or {}
    repair = report.get("repair") or {}
    summary = [
        "# Render Checkpoint Artifact Handoff V2 Validation",
        "",
        f"- Mode: `{report.get('mode')}`",
        f"- Project: `{report.get('project_id') or 'synthetic'}`",
        f"- Passed: `{str(bool(report.get('passed'))).lower()}`",
        f"- Canonical path: `{report.get('canonical_path')}`",
        f"- Resolved path: `{inspection.get('artifact_path') or 'not found'}`",
        f"- Manifest exists: `{str(bool(inspection.get('manifest_exists'))).lower()}`",
        f"- MP4 files exist: `{str(bool(inspection.get('mp4_files_exist'))).lower()}`",
        f"- Repair applied: `{str(bool(repair.get('repaired'))).lower()}`",
    ]
    warnings = [*report.get("warnings", []), *inspection.get("warnings", [])]
    if warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in warnings]])
    if report.get("errors"):
        summary.extend(["", "## Errors", *[f"- {item}" for item in report["errors"]]])
    (report_dir / "render_checkpoint_handoff_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = _args()
    if args.self_check:
        report = asyncio.run(_self_check())
    elif args.simulate:
        report = asyncio.run(_simulate())
    else:
        report = asyncio.run(_inspect_project(str(args.project_id), repair=bool(args.repair)))
    _write_reports(report, args.report_dir)
    print(
        json.dumps(
            {
                "mode": report["mode"],
                "project_id": report.get("project_id"),
                "passed": report["passed"],
                "report_dir": str(args.report_dir),
                "errors": report["errors"],
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

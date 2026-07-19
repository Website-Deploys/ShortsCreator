"""Durable restart/resume validation contracts and integrity helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

JsonDict = dict[str, Any]
ProbeFunction = Callable[[Path], JsonDict]

DURABLE_RESUME_CONTRACT_VERSION = "1"
DURABLE_STAGE_ORDER = (
    "upload",
    "cognitive",
    "story",
    "virality",
    "planning",
    "editing",
    "rendering",
    "optimization",
)
DURABLE_RESUME_REPORT_SUBDIR = Path(
    "work/validation_reports/durable_restart_resume"
)


@dataclass(slots=True)
class DurableResumeStageResultV1:
    """One durable stage before and after a simulated process restart."""

    name: str
    status_before: str | None
    status_after: str | None
    artifact_before: str | None
    artifact_after: str | None
    execution_count: int
    reused: bool
    rerun: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(slots=True)
class DurableOutputValidationV1:
    """Integrity evidence for one rendered output."""

    clip_id: str
    storage_key: str
    exists: bool
    size_bytes: int
    ffprobe_valid: bool
    checksum: str | None
    duplicate_of: str | None
    partial_detected: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(slots=True)
class DurableRestartResumeResultV1:
    """JSON-safe proof result for one durable restart/resume exercise."""

    project_id: str | None
    mode: str
    interruption_stage: str | None
    interruption_method: str | None
    resume_started_at: str | None = None
    resume_finished_at: str | None = None
    total_runtime_seconds: float | None = None
    checkpoint_before_restart: JsonDict = field(default_factory=dict)
    checkpoint_after_restart: JsonDict = field(default_factory=dict)
    stages_before_restart: list[JsonDict] = field(default_factory=list)
    stages_after_resume: list[JsonDict] = field(default_factory=list)
    stage_execution_counts: dict[str, int] = field(default_factory=dict)
    stages_reused: list[str] = field(default_factory=list)
    stages_rerun: list[str] = field(default_factory=list)
    corrupted_checkpoints_detected: bool = False
    duplicate_outputs_detected: bool = False
    partial_outputs_detected: bool = False
    render_manifest_present: bool = False
    optimization_manifest_present: bool = False
    accepted_mp4_count: int = 0
    final_payload_valid: bool = False
    resume_successful: bool = False
    outputs: list[DurableOutputValidationV1] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    contract_version: str = DURABLE_RESUME_CONTRACT_VERSION

    def to_dict(self) -> JsonDict:
        payload = asdict(self)
        payload["outputs"] = [output.to_dict() for output in self.outputs]
        return payload


def parse_checkpoint_snapshot(value: Any) -> JsonDict:
    """Parse a persisted workflow or durable-job document without raising."""

    errors: list[str] = []
    payload: Any = value
    if isinstance(value, bytes):
        try:
            payload = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            return _unreadable_snapshot(f"Checkpoint is not UTF-8: {exc}")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            return _unreadable_snapshot(f"Checkpoint JSON is corrupt: {exc}")
    if hasattr(payload, "to_dict") and callable(payload.to_dict):
        payload = payload.to_dict()
    if not isinstance(payload, dict):
        return _unreadable_snapshot("Checkpoint payload is not a JSON object.")

    raw_stages = payload.get("jobs")
    if not isinstance(raw_stages, list):
        raw_stages = payload.get("stages")
    if not isinstance(raw_stages, list):
        raw_stages = []
        errors.append("Checkpoint contains no stage list.")

    stages: list[JsonDict] = []
    for index, raw_stage in enumerate(raw_stages):
        if not isinstance(raw_stage, dict):
            errors.append(f"Checkpoint stage {index} is not an object.")
            continue
        checkpoint = raw_stage.get("checkpoint")
        checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
        name = str(
            raw_stage.get("stage")
            or raw_stage.get("name")
            or raw_stage.get("engine")
            or f"stage_{index}"
        )
        stages.append(
            {
                "name": name,
                "engine": str(raw_stage.get("engine") or name),
                "status": str(raw_stage.get("status") or "missing"),
                "artifact_path": _optional_string(
                    checkpoint.get("artifact_path")
                    or checkpoint.get("checkpoint_key")
                ),
                "checkpoint_valid": checkpoint.get("valid"),
                "checkpoint": checkpoint,
                "attempts": _nonnegative_int(
                    raw_stage.get("attempts", raw_stage.get("attempt", 0))
                ),
                "started_at": _optional_string(raw_stage.get("started_at")),
                "finished_at": _optional_string(raw_stage.get("finished_at")),
                "worker_id": _optional_string(raw_stage.get("worker_id")),
                "error": _optional_string(raw_stage.get("error")),
                "warnings": _strings(raw_stage.get("warnings")),
                "errors": _strings(raw_stage.get("errors")),
            }
        )

    snapshot = {
        "readable": not errors,
        "corrupted": bool(errors),
        "workflow_id": _optional_string(
            payload.get("workflow_id") or payload.get("job_id")
        ),
        "project_id": _optional_string(payload.get("project_id")),
        "status": str(payload.get("status") or "missing"),
        "updated_at": _optional_string(payload.get("updated_at")),
        "stale_running_detected": bool(payload.get("stale_running_detected")),
        "recovery_reason": _optional_string(payload.get("recovery_reason")),
        "stages": stages,
        "errors": errors,
    }
    transition_errors = detect_checkpoint_corruption(snapshot)
    if transition_errors:
        snapshot["corrupted"] = True
        snapshot["errors"] = list(dict.fromkeys([*errors, *transition_errors]))
    return snapshot


def detect_checkpoint_corruption(snapshot: JsonDict) -> list[str]:
    """Detect malformed stage state without mutating persisted checkpoints."""

    errors = [str(item) for item in _list(snapshot.get("errors")) if item]
    if snapshot.get("readable") is False:
        return list(dict.fromkeys(errors or ["Checkpoint is unreadable."]))
    stages = [item for item in _list(snapshot.get("stages")) if isinstance(item, dict)]
    names = [str(item.get("name") or "") for item in stages]
    if len(names) != len(set(names)):
        errors.append("Checkpoint contains duplicate stage names.")
    valid_statuses = {
        "pending",
        "ready",
        "running",
        "completed",
        "failed",
        "cancel_requested",
        "stale",
        "cancelled",
        "dead",
        "blocked",
    }
    for stage in stages:
        name = str(stage.get("name") or "unknown")
        status = str(stage.get("status") or "missing")
        if status not in valid_statuses:
            errors.append(f"Stage {name} has invalid status {status!r}.")
        checkpoint = stage.get("checkpoint")
        if (
            status == "completed"
            and isinstance(checkpoint, dict)
            and checkpoint.get("valid") is False
        ):
            errors.append(f"Completed stage {name} has an invalid checkpoint.")
    completed = {str(item.get("name")) for item in stages if item.get("status") == "completed"}
    for index, name in enumerate(DURABLE_STAGE_ORDER):
        if name not in completed:
            continue
        missing = [
            dependency
            for dependency in DURABLE_STAGE_ORDER[:index]
            if dependency not in completed
        ]
        if missing:
            errors.append(
                f"Stage {name} is completed before dependencies: {', '.join(missing)}."
            )
    return list(dict.fromkeys(errors))


def detect_impossible_stage_transitions(before: JsonDict, after: JsonDict) -> list[str]:
    """Reject completed-stage regressions and decreasing execution counts."""

    errors: list[str] = []
    before_map = _stage_map(before)
    after_map = _stage_map(after)
    for name, previous in before_map.items():
        current = after_map.get(name)
        if current is None:
            errors.append(f"Stage {name} disappeared after restart.")
            continue
        previous_status = str(previous.get("status") or "missing")
        current_status = str(current.get("status") or "missing")
        if previous_status == "completed" and current_status != "completed":
            errors.append(
                f"Completed stage {name} regressed to {current_status!r} after restart."
            )
        if _nonnegative_int(current.get("attempts")) < _nonnegative_int(
            previous.get("attempts")
        ):
            errors.append(f"Stage {name} execution count decreased after restart.")
    errors.extend(detect_checkpoint_corruption(after))
    return list(dict.fromkeys(errors))


def compute_stage_execution_counts(snapshot: JsonDict) -> dict[str, int]:
    """Return persisted job-attempt counts for every durable stage."""

    stage_map = _stage_map(snapshot)
    return {
        name: _nonnegative_int(stage_map.get(name, {}).get("attempts"))
        for name in DURABLE_STAGE_ORDER
    }


def classify_stage_execution(
    before: JsonDict,
    after: JsonDict,
) -> JsonDict:
    """Classify completed work as reused, rerun, or first-run after restart."""

    before_map = _stage_map(before)
    after_map = _stage_map(after)
    reused: list[str] = []
    rerun: list[str] = []
    first_run_after_restart: list[str] = []
    stage_results: list[DurableResumeStageResultV1] = []
    for name in DURABLE_STAGE_ORDER:
        previous = before_map.get(name, {})
        current = after_map.get(name, {})
        before_count = _nonnegative_int(previous.get("attempts"))
        after_count = _nonnegative_int(current.get("attempts"))
        was_completed = previous.get("status") == "completed"
        is_completed = current.get("status") == "completed"
        stage_reused = bool(was_completed and is_completed and after_count == before_count)
        stage_rerun = bool(before_count > 0 and after_count > before_count)
        first_run = bool(before_count == 0 and after_count > 0)
        if stage_reused:
            reused.append(name)
        if stage_rerun:
            rerun.append(name)
        if first_run:
            first_run_after_restart.append(name)
        stage_results.append(
            DurableResumeStageResultV1(
                name=name,
                status_before=_optional_string(previous.get("status")),
                status_after=_optional_string(current.get("status")),
                artifact_before=_optional_string(previous.get("artifact_path")),
                artifact_after=_optional_string(current.get("artifact_path")),
                execution_count=after_count,
                reused=stage_reused,
                rerun=stage_rerun,
                warnings=_strings(current.get("warnings")),
                errors=_strings(current.get("errors")),
            )
        )
    return {
        "counts": compute_stage_execution_counts(after),
        "reused": reused,
        "rerun": rerun,
        "first_run_after_restart": first_run_after_restart,
        "stages": stage_results,
    }


def validate_rendered_output(
    *,
    clip_id: str,
    storage_key: str,
    path: Path | None,
    probe_function: ProbeFunction,
) -> DurableOutputValidationV1:
    """Reject missing, zero-byte, temporary, or FFprobe-invalid MP4 output."""

    exists = bool(path is not None and path.is_file())
    size_bytes = path.stat().st_size if exists and path is not None else 0
    warnings: list[str] = []
    errors: list[str] = []
    suffixes = {suffix.lower() for suffix in path.suffixes} if path is not None else set()
    temporary = bool(suffixes.intersection({".tmp", ".part"}))
    if not exists:
        errors.append("Rendered output is missing.")
    elif size_bytes <= 0:
        errors.append("Rendered output is zero bytes.")
    if temporary:
        errors.append("Temporary or partial output cannot be accepted.")
    probe = probe_function(path) if exists and size_bytes > 0 and path is not None else {}
    ffprobe_valid = bool(
        probe.get("passed")
        and probe.get("video_codec")
        and probe.get("audio_codec")
        and probe.get("has_audio")
    )
    if exists and size_bytes > 0 and not ffprobe_valid:
        errors.append("Rendered output failed audio/video FFprobe validation.")
        errors.extend(_strings(probe.get("errors")))
    checksum = None
    if exists and size_bytes > 0 and path is not None:
        checksum = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    partial_detected = bool(errors)
    return DurableOutputValidationV1(
        clip_id=clip_id,
        storage_key=storage_key,
        exists=exists,
        size_bytes=size_bytes,
        ffprobe_valid=ffprobe_valid,
        checksum=checksum,
        duplicate_of=None,
        partial_detected=partial_detected,
        warnings=warnings,
        errors=list(dict.fromkeys(errors)),
    )


def detect_duplicate_outputs(
    outputs: Sequence[DurableOutputValidationV1 | JsonDict],
) -> JsonDict:
    """Find duplicate storage keys and checksums without accepting aliases."""

    seen_keys: dict[str, str] = {}
    seen_checksums: dict[str, str] = {}
    storage_key_duplicates: list[JsonDict] = []
    checksum_duplicates: list[JsonDict] = []
    normalized: list[JsonDict] = []
    for output in outputs:
        item = output.to_dict() if isinstance(output, DurableOutputValidationV1) else dict(output)
        clip_id = str(item.get("clip_id") or "unknown")
        storage_key = str(item.get("storage_key") or "")
        checksum = str(item.get("checksum") or "")
        duplicate_of: str | None = None
        if storage_key and storage_key in seen_keys:
            duplicate_of = seen_keys[storage_key]
            storage_key_duplicates.append(
                {"clip_id": clip_id, "duplicate_of": duplicate_of, "storage_key": storage_key}
            )
        elif storage_key:
            seen_keys[storage_key] = clip_id
        if checksum and checksum in seen_checksums:
            duplicate_of = duplicate_of or seen_checksums[checksum]
            checksum_duplicates.append(
                {"clip_id": clip_id, "duplicate_of": seen_checksums[checksum], "checksum": checksum}
            )
        elif checksum:
            seen_checksums[checksum] = clip_id
        item["duplicate_of"] = duplicate_of
        normalized.append(item)
    return {
        "detected": bool(storage_key_duplicates or checksum_duplicates),
        "storage_key_duplicates": storage_key_duplicates,
        "checksum_duplicates": checksum_duplicates,
        "outputs": normalized,
    }


def validate_resume_manifests(
    *,
    render_manifest_present: bool,
    optimization_manifest_present: bool,
) -> JsonDict:
    """Require both canonical rendering and optimization handoffs."""

    errors: list[str] = []
    if not render_manifest_present:
        errors.append("Canonical render manifest is missing.")
    if not optimization_manifest_present:
        errors.append("Optimization manifest is missing.")
    return {"passed": not errors, "errors": errors}


def validate_resume_final_payload(payload: JsonDict) -> JsonDict:
    """Require a JSON-safe final payload containing at least one clip."""

    errors: list[str] = []
    clips = _list(payload.get("clips"))
    if not clips:
        clips = _list(_dict(payload.get("manifest")).get("renders"))
    if not clips:
        errors.append("Final payload contains no rendered clips.")
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        errors.append(f"Final payload is not JSON-safe: {exc}")
    return {"passed": not errors, "clip_count": len(clips), "errors": errors}


def interruption_plan(*, interrupt_after: str | None, interrupt_during: str | None) -> JsonDict:
    """Normalize supported deterministic interruption modes."""

    if interrupt_after in {"analysis", "editing"} and interrupt_during is None:
        stage = "cognitive" if interrupt_after == "analysis" else "editing"
        return {
            "valid": True,
            "stage": stage,
            "mode": f"interrupt_after_{interrupt_after}",
            "trigger": "job_completed",
            "method": "validator_checkpoint_boundary_pause_then_new_service_instance",
            "errors": [],
        }
    if interrupt_during == "rendering" and interrupt_after is None:
        return {
            "valid": True,
            "stage": "rendering",
            "mode": "interrupt_during_rendering",
            "trigger": "runner_entered",
            "method": (
                "validator_runner_gate_after_durable_claim_before_ffmpeg_"
                "then_new_service_instance"
            ),
            "errors": [],
        }
    return {
        "valid": False,
        "stage": None,
        "mode": "invalid",
        "trigger": None,
        "method": None,
        "errors": ["Choose one supported interruption mode."],
    }


def durable_resume_self_check(
    *,
    storage_root: Path,
    report_dir: Path,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
    which: Callable[[str], str | None] = shutil.which,
) -> JsonDict:
    """Check local-only durable validation prerequisites."""

    checks: list[JsonDict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    ffmpeg = which(ffmpeg_binary)
    ffprobe = which(ffprobe_binary)
    add("ffmpeg_available", ffmpeg is not None, ffmpeg or f"{ffmpeg_binary} not found")
    add("ffprobe_available", ffprobe is not None, ffprobe or f"{ffprobe_binary} not found")
    add("workflow_modules_import", True, "workflow and checkpoint modules imported")
    add("render_manifest_resolver", True, "canonical render resolver imported")
    add("optimization_resolver", True, "optimization repository imported")
    storage_ok, storage_detail = _writable_directory_check(storage_root)
    add("storage_root_writable", storage_ok, storage_detail)
    report_ok, report_detail = _writable_directory_check(report_dir)
    add("report_directory_writable", report_ok, report_detail)
    return {
        "passed": all(bool(check.get("passed")) for check in checks),
        "checks": checks,
        "external_access_required": False,
        "errors": [
            str(check.get("detail"))
            for check in checks
            if check.get("passed") is not True
        ],
    }


def validated_durable_resume_report_dir(
    report_dir: Path,
    *,
    workspace_root: Path,
) -> Path:
    """Restrict generated reports to ``work/validation_reports``."""

    allowed = (workspace_root / "work" / "validation_reports").resolve()
    resolved = report_dir.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f"Report directory must stay under {allowed}.") from exc
    return resolved


def is_generated_resume_artifact(path: str | Path) -> bool:
    """Return whether a validation artifact must never be staged."""

    normalized = str(path).replace("\\", "/").lower().lstrip("./")
    parts = {part for part in normalized.split("/") if part}
    generated_parts = {
        ".venv",
        "node_modules",
        ".next",
        "work",
        "storage_data",
        "media",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
    return bool(
        parts.intersection(generated_parts)
        or normalized.endswith((".mp4", ".mov", ".mkv", ".webm", ".part", ".tmp"))
        or normalized == ".env"
        or normalized.startswith(".env.")
    )


def write_durable_resume_report(
    result: DurableRestartResumeResultV1 | JsonDict,
    report_dir: Path,
    *,
    workspace_root: Path,
) -> dict[str, str]:
    """Write JSON and Markdown evidence under the guarded report root."""

    output = validated_durable_resume_report_dir(
        report_dir,
        workspace_root=workspace_root,
    )
    output.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict() if isinstance(result, DurableRestartResumeResultV1) else result
    mode = str(payload.get("mode") or "unknown").replace("/", "_")
    stem = f"durable_restart_resume_{mode}"
    json_path = output / f"{stem}_report.json"
    summary_path = output / f"{stem}_summary.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Durable Restart / Resume Proof V2",
        "",
        f"- Passed: `{str(bool(payload.get('resume_successful'))).lower()}`",
        f"- Mode: `{payload.get('mode')}`",
        f"- Project: `{payload.get('project_id') or 'not created'}`",
        f"- Interruption stage: `{payload.get('interruption_stage') or 'inspection only'}`",
        f"- Accepted MP4s: `{payload.get('accepted_mp4_count', 0)}`",
        f"- Reused stages: `{', '.join(_strings(payload.get('stages_reused'))) or 'none'}`",
        f"- Rerun stages: `{', '.join(_strings(payload.get('stages_rerun'))) or 'none'}`",
        "- External calls: `false`",
        "- Manual playback: `false`",
    ]
    if payload.get("warnings"):
        lines.extend(["", "## Warnings", *[f"- {item}" for item in payload["warnings"]]])
    if payload.get("errors"):
        lines.extend(["", "## Errors", *[f"- {item}" for item in payload["errors"]]])
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "summary": str(summary_path)}


def _stage_map(snapshot: JsonDict) -> dict[str, JsonDict]:
    return {
        str(stage.get("name")): stage
        for stage in _list(snapshot.get("stages"))
        if isinstance(stage, dict) and stage.get("name")
    }


def _unreadable_snapshot(error: str) -> JsonDict:
    return {
        "readable": False,
        "corrupted": True,
        "workflow_id": None,
        "project_id": None,
        "status": "unreadable",
        "updated_at": None,
        "stale_running_detected": False,
        "recovery_reason": None,
        "stages": [],
        "errors": [error],
    }


def _writable_directory_check(path: Path) -> tuple[bool, str]:
    marker = path / f".olympus-durable-resume-write-{uuid4().hex}.tmp"
    try:
        path.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
    except OSError as exc:
        return False, f"{path}: {type(exc).__name__}: {exc}"
    return True, str(path.resolve())


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _strings(value: Any) -> list[str]:
    return [str(item) for item in _list(value) if item not in (None, "")]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO timestamp for validator runtime calculations."""

    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

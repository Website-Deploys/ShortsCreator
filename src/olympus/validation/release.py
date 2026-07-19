"""Final internal release-candidate contracts and evidence helpers for Olympus V2."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FINAL_RELEASE_CONTRACT_VERSION = "1"
FINAL_VERDICT_PASS = "PASS_INTERNAL_RC"
FINAL_VERDICT_BLOCKED = "BLOCKED"
FINAL_VERDICT_INCOMPLETE = "INCOMPLETE"
READINESS_READY = "ready_for_internal_rc"
READINESS_BLOCKED = "blocked"
READINESS_INCOMPLETE = "validation_incomplete"

VALIDATOR_STATUS_PASSED = "passed"
VALIDATOR_STATUS_FAILED = "failed"
VALIDATOR_STATUS_SKIPPED = "skipped"
VALIDATOR_STATUS_NOT_RUN = "not_run"
VALIDATOR_STATUSES = frozenset(
    {
        VALIDATOR_STATUS_PASSED,
        VALIDATOR_STATUS_FAILED,
        VALIDATOR_STATUS_SKIPPED,
        VALIDATOR_STATUS_NOT_RUN,
    }
)

REPORT_SUBDIRECTORY = Path("work") / "validation_reports" / "final_release"
REPORT_NAME = "final_release_report.json"
SUMMARY_NAME = "final_release_summary.md"

_MEDIA_EXTENSIONS = frozenset(
    {".aac", ".avi", ".flac", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".ogg", ".wav", ".webm"}
)
_MEDIA_PATH_PATTERN = re.compile(
    r"(?i)(?:[a-z]:[\\/]|(?:^|\s))(?:[^\s\"'`]+[\\/])*[^\s\"'`]+"
    r"\.(?:aac|avi|flac|m4a|mkv|mov|mp3|mp4|ogg|wav|webm)"
)
_GENERATED_PREFIXES = (
    ".next/",
    ".venv/",
    "frontend/.next/",
    "frontend/node_modules/",
    "media/",
    "node_modules/",
    "storage_data/",
    "work/",
)


def utc_now_iso() -> str:
    """Return an ISO-formatted UTC timestamp."""

    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class ValidatorResultV1:
    """Normalized, JSON-safe evidence for one release validation command."""

    name: str
    command: list[str]
    status: str
    duration_seconds: float
    report_path: str | None
    required: bool
    blocker_on_failure: bool
    summary: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in VALIDATOR_STATUSES:
            raise ValueError(f"Unsupported validator status: {self.status}")
        if self.duration_seconds < 0:
            raise ValueError("Validator duration cannot be negative.")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary."""

        payload = asdict(self)
        json.dumps(payload)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ValidatorResultV1:
        """Restore a validator result from persisted JSON evidence."""

        return cls(
            name=str(value.get("name") or "unknown"),
            command=[str(item) for item in _as_list(value.get("command"))],
            status=str(value.get("status") or VALIDATOR_STATUS_NOT_RUN),
            duration_seconds=_as_float(value.get("duration_seconds")),
            report_path=_optional_string(value.get("report_path")),
            required=value.get("required") is True,
            blocker_on_failure=value.get("blocker_on_failure") is True,
            summary=str(value.get("summary") or ""),
            warnings=_strings(value.get("warnings")),
            errors=_strings(value.get("errors")),
        )


@dataclass(slots=True)
class FinalReleaseValidationResultV1:
    """Canonical truth report for the Olympus V2 internal release gate."""

    release_candidate_name: str = "Olympus V2 Internal Release Candidate"
    created_at: str = field(default_factory=utc_now_iso)
    git_commit: str = "unknown"
    git_branch: str = "unknown"
    environment: dict[str, Any] = field(default_factory=dict)
    backend_status: dict[str, Any] = field(default_factory=dict)
    frontend_status: dict[str, Any] = field(default_factory=dict)
    validators: list[ValidatorResultV1] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    release_readiness: str = READINESS_INCOMPLETE
    final_verdict: str = FINAL_VERDICT_INCOMPLETE
    contract_version: str = FINAL_RELEASE_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary without dataclass instances."""

        payload = asdict(self)
        payload["validators"] = [result.to_dict() for result in self.validators]
        json.dumps(payload)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FinalReleaseValidationResultV1:
        """Restore a final result from an existing report."""

        validators = [
            ValidatorResultV1.from_dict(item)
            for item in _as_list(value.get("validators"))
            if isinstance(item, Mapping)
        ]
        return cls(
            release_candidate_name=str(
                value.get("release_candidate_name")
                or "Olympus V2 Internal Release Candidate"
            ),
            created_at=str(value.get("created_at") or utc_now_iso()),
            git_commit=str(value.get("git_commit") or "unknown"),
            git_branch=str(value.get("git_branch") or "unknown"),
            environment=_dict(value.get("environment")),
            backend_status=_dict(value.get("backend_status")),
            frontend_status=_dict(value.get("frontend_status")),
            validators=validators,
            artifacts=_dict(value.get("artifacts")),
            blockers=_strings(value.get("blockers")),
            limitations=_strings(value.get("limitations")),
            warnings=_strings(value.get("warnings")),
            release_readiness=str(value.get("release_readiness") or READINESS_INCOMPLETE),
            final_verdict=str(value.get("final_verdict") or FINAL_VERDICT_INCOMPLETE),
            contract_version=str(
                value.get("contract_version") or FINAL_RELEASE_CONTRACT_VERSION
            ),
        )


def evaluate_final_release(
    result: FinalReleaseValidationResultV1,
    *,
    required_validator_names: Iterable[str] = (),
) -> FinalReleaseValidationResultV1:
    """Classify blockers, incomplete required proof, and the final internal-RC verdict."""

    blockers = list(result.blockers)
    warnings = list(result.warnings)
    validators_by_name = {validator.name: validator for validator in result.validators}
    incomplete: list[str] = []

    for name in required_validator_names:
        if name not in validators_by_name:
            _append_unique(blockers, f"Required validator command is missing: {name}.")

    for validator in result.validators:
        if validator.status == VALIDATOR_STATUS_PASSED and validator.errors:
            _append_unique(
                blockers,
                f"Validator {validator.name} reported success with errors present.",
            )
        if not validator.required:
            continue
        if validator.status == VALIDATOR_STATUS_FAILED and validator.blocker_on_failure:
            detail = validator.errors[0] if validator.errors else validator.summary
            _append_unique(blockers, f"Required validator {validator.name} failed: {detail}")
        elif validator.status in {VALIDATOR_STATUS_SKIPPED, VALIDATOR_STATUS_NOT_RUN}:
            incomplete.append(validator.name)

    if incomplete:
        _append_unique(
            warnings,
            "Required validation evidence was not run: " + ", ".join(sorted(incomplete)) + ".",
        )

    result.blockers = _unique(blockers)
    result.warnings = _unique(warnings)
    result.limitations = _unique(result.limitations)
    if result.blockers:
        result.final_verdict = FINAL_VERDICT_BLOCKED
        result.release_readiness = READINESS_BLOCKED
    elif incomplete:
        result.final_verdict = FINAL_VERDICT_INCOMPLETE
        result.release_readiness = READINESS_INCOMPLETE
    else:
        result.final_verdict = FINAL_VERDICT_PASS
        result.release_readiness = READINESS_READY
    return result


def missing_validator_result(
    name: str,
    command: Sequence[str],
    *,
    required: bool = True,
    blocker_on_failure: bool = True,
) -> ValidatorResultV1:
    """Return an explicit failure for a validator script or executable that is absent."""

    return ValidatorResultV1(
        name=name,
        command=[str(item) for item in command],
        status=VALIDATOR_STATUS_FAILED,
        duration_seconds=0.0,
        report_path=None,
        required=required,
        blocker_on_failure=blocker_on_failure,
        summary="Validator command is unavailable.",
        errors=[f"Validator command is missing: {' '.join(str(item) for item in command)}"],
    )


def skipped_validator_result(
    name: str,
    command: Sequence[str],
    reason: str,
    *,
    required: bool,
    blocker_on_failure: bool,
) -> ValidatorResultV1:
    """Return explicit skipped evidence without treating it as a passing validator."""

    return ValidatorResultV1(
        name=name,
        command=[str(item) for item in command],
        status=VALIDATOR_STATUS_SKIPPED,
        duration_seconds=0.0,
        report_path=None,
        required=required,
        blocker_on_failure=blocker_on_failure,
        summary=reason,
        warnings=[reason],
    )


def validator_result_from_command(
    *,
    name: str,
    command: Sequence[str],
    command_result: Mapping[str, Any],
    required: bool,
    blocker_on_failure: bool,
    summary: str,
    workspace_root: Path,
    report_path: Path | None = None,
) -> ValidatorResultV1:
    """Normalize subprocess evidence and verify an expected JSON report when supplied."""

    passed = command_result.get("passed") is True
    errors = _strings(command_result.get("errors"))
    warnings = _strings(command_result.get("warnings"))
    stored_report_path: str | None = None
    if report_path is not None:
        try:
            stored_report_path = relative_report_path(report_path, workspace_root)
        except ValueError as exc:
            errors.append(str(exc))
            passed = False
        if not report_path.is_file():
            errors.append("Expected validator report is missing.")
            passed = False
        else:
            payload, report_errors = load_json_report(report_path)
            errors.extend(report_errors)
            if report_errors:
                passed = False
            else:
                report_truth = extract_report_truth(payload)
                if report_truth is not True:
                    errors.append(
                        "Validator report did not contain an affirmative passing result."
                    )
                    passed = False
    if command_result.get("timed_out") is True:
        errors.append("Validator command timed out.")
    if not passed:
        diagnostic = str(
            command_result.get("stderr_tail")
            or command_result.get("stdout_tail")
            or ""
        ).strip()
        if diagnostic:
            errors.append(f"Diagnostic tail: {diagnostic[-2_000:]}")
    errors = [_redact_media_paths(item) for item in errors]
    warnings = [_redact_media_paths(item) for item in warnings]
    return ValidatorResultV1(
        name=name,
        command=[str(item) for item in command],
        status=VALIDATOR_STATUS_PASSED if passed else VALIDATOR_STATUS_FAILED,
        duration_seconds=max(0.0, _as_float(command_result.get("duration_seconds"))),
        report_path=stored_report_path,
        required=required,
        blocker_on_failure=blocker_on_failure,
        summary=summary if passed else f"{summary} Failed.",
        warnings=_unique(warnings),
        errors=_unique(errors or (["Validator command failed."] if not passed else [])),
    )


def extract_report_truth(payload: Mapping[str, Any]) -> bool | None:
    """Read the supported validators' explicit pass fields without inferring success."""

    if isinstance(payload.get("passed"), bool):
        return bool(payload["passed"])
    if isinstance(payload.get("resume_successful"), bool):
        return bool(payload["resume_successful"])
    for key in (
        "face_motion_validation_result_v1",
        "multi_speaker_layout_validation_result_v1",
    ):
        nested = payload.get(key)
        if isinstance(nested, Mapping) and isinstance(nested.get("passed"), bool):
            return bool(nested["passed"])
    legacy = payload.get("multi_speaker_validation_report")
    if isinstance(legacy, Mapping) and isinstance(legacy.get("pass_fail"), bool):
        return bool(legacy["pass_fail"])
    return None


def load_json_report(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Load one JSON object and return explicit parse errors instead of raising."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"Validator report is unreadable: {exc}"]
    if not isinstance(payload, dict):
        return {}, ["Validator report must contain a JSON object."]
    return payload, []


def frontend_script_status(package_json: Path, required_scripts: Sequence[str]) -> dict[str, Any]:
    """Return exact missing frontend scripts without invoking npm."""

    if not package_json.is_file():
        return {
            "passed": False,
            "available_scripts": [],
            "missing_scripts": list(required_scripts),
            "errors": ["Frontend package.json is missing."],
        }
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "available_scripts": [],
            "missing_scripts": list(required_scripts),
            "errors": [f"Frontend package.json is unreadable: {exc}"],
        }
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    available = sorted(str(item) for item in scripts) if isinstance(scripts, dict) else []
    missing = [item for item in required_scripts if item not in available]
    return {
        "passed": not missing,
        "available_scripts": available,
        "missing_scripts": missing,
        "errors": [f"Missing frontend npm script: {item}" for item in missing],
    }


def optional_provider_limitations(statuses: Mapping[str, Any]) -> list[str]:
    """Describe optional provider absence as limitations only when marked non-required."""

    limitations: list[str] = []
    for name, raw_status in sorted(statuses.items()):
        if not isinstance(raw_status, Mapping):
            continue
        if raw_status.get("available") is False and raw_status.get("required") is not True:
            feature = str(raw_status.get("feature") or "optional capability")
            limitations.append(
                f"Optional provider {name} is unavailable for {feature}; "
                "absence was reported honestly."
            )
    return limitations


def standard_proof_limitations() -> list[str]:
    """Return known proof boundaries that do not block an internal synthetic RC."""

    return [
        "No real face-tracking proof was run without a rights-cleared face sample.",
        "No real multi-speaker proof was run without a rights-cleared multi-speaker sample.",
        "Synthetic fixtures do not prove behavior on real creator footage.",
        "Peak RAM consumption was not measured.",
        "Durable recovery uses service reconstruction, not an operating-system process kill.",
        "Music quality and perceived speech/music balance were not manually verified.",
    ]


def duration_summary(validators: Sequence[ValidatorResultV1]) -> dict[str, Any]:
    """Summarize validator durations without retaining subprocess output."""

    total = round(sum(item.duration_seconds for item in validators), 3)
    completed_statuses = {VALIDATOR_STATUS_PASSED, VALIDATOR_STATUS_FAILED}
    completed = [item for item in validators if item.status in completed_statuses]
    longest = max(completed, key=lambda item: item.duration_seconds, default=None)
    return {
        "total_seconds": total,
        "completed_count": len(completed),
        "skipped_count": sum(item.status == VALIDATOR_STATUS_SKIPPED for item in validators),
        "longest_validator": longest.name if longest else None,
        "longest_duration_seconds": longest.duration_seconds if longest else 0.0,
    }


def generated_artifacts_staged(paths: Iterable[str]) -> list[str]:
    """Return staged generated/media paths prohibited by the release task."""

    return sorted(
        {
            normalized
            for item in paths
            if (normalized := _normalized_path(item))
            and _is_generated_path(normalized)
        }
    )


def relative_report_path(path: Path, workspace_root: Path) -> str:
    """Return a guarded workspace-relative path below work/validation_reports."""

    workspace = workspace_root.resolve()
    allowed = (workspace / "work" / "validation_reports").resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(allowed):
        raise ValueError(f"Report path must stay under {allowed}.")
    return resolved.relative_to(workspace).as_posix()


def validated_report_directory(path: Path, workspace_root: Path) -> Path:
    """Resolve and validate a final-release report directory."""

    workspace = workspace_root.resolve()
    allowed = (workspace / "work" / "validation_reports").resolve()
    selected = path if path.is_absolute() else workspace / path
    resolved = selected.resolve()
    if not resolved.is_relative_to(allowed):
        raise ValueError(f"Report directory must stay under {allowed}.")
    return resolved


def contains_raw_media_path(value: Any) -> bool:
    """Detect raw source/output media paths in the compact final report."""

    if isinstance(value, str):
        if _MEDIA_PATH_PATTERN.search(value):
            return True
        candidate = Path(value.replace("\\", "/"))
        return candidate.suffix.lower() in _MEDIA_EXTENSIONS and "/" in value.replace("\\", "/")
    if isinstance(value, Mapping):
        return any(contains_raw_media_path(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return any(contains_raw_media_path(item) for item in value)
    return False


def write_final_release_report(
    result: FinalReleaseValidationResultV1,
    report_dir: Path,
    *,
    workspace_root: Path,
) -> dict[str, str]:
    """Atomically write canonical JSON and Markdown reports under the ignored report root."""

    output = validated_report_directory(report_dir, workspace_root)
    payload = result.to_dict()
    if contains_raw_media_path(payload):
        raise ValueError("Final release report cannot contain raw media paths.")
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / REPORT_NAME
    markdown_path = output / SUMMARY_NAME
    _atomic_write(json_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    _atomic_write(markdown_path, final_release_markdown(result))
    return {
        "json": relative_report_path(json_path, workspace_root),
        "summary": relative_report_path(markdown_path, workspace_root),
    }


def final_release_markdown(result: FinalReleaseValidationResultV1) -> str:
    """Render the compact human-readable internal release-candidate summary."""

    lines = [
        "# Olympus V2 Final Release Validation",
        "",
        f"- Final verdict: **{result.final_verdict}**",
        f"- Release readiness: `{result.release_readiness}`",
        f"- Git commit: `{result.git_commit}`",
        f"- Branch: `{result.git_branch}`",
        f"- Created: `{result.created_at}`",
        "",
        "This verdict applies only to an internal release candidate, "
        "not public production readiness.",
        "",
        "## Environment",
        "",
        f"- Self-check passed: `{result.environment.get('passed')}`",
        f"- Python: `{result.environment.get('python_version') or 'unavailable'}`",
        f"- FFmpeg: `{result.environment.get('ffmpeg_available')}`",
        f"- FFprobe: `{result.environment.get('ffprobe_available')}`",
        f"- npm: `{result.environment.get('npm_available')}`",
        "",
        "## Backend",
        "",
        f"- Status: `{result.backend_status.get('status') or 'not_run'}`",
        f"- Passed: `{result.backend_status.get('passed')}`",
        "",
        "## Frontend",
        "",
        f"- Status: `{result.frontend_status.get('status') or 'not_run'}`",
        f"- Passed: `{result.frontend_status.get('passed')}`",
        "",
        "## Validators",
        "",
        "| Validator | Required | Status | Seconds | Report |",
        "| --- | --- | --- | ---: | --- |",
    ]
    lines.extend(
        "| "
        + " | ".join(
            (
                item.name,
                str(item.required).lower(),
                item.status,
                f"{item.duration_seconds:.3f}",
                item.report_path or "none",
            )
        )
        + " |"
        for item in result.validators
    )
    lines.extend(_artifact_markdown(result.artifacts))
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {item}" for item in result.blockers)
    if not result.blockers:
        lines.append("- None.")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in result.limitations)
    if not result.limitations:
        lines.append("- None recorded.")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {item}" for item in result.warnings)
    if not result.warnings:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Final Verdict",
            "",
            f"**{result.final_verdict}** — `{result.release_readiness}`",
            "",
        ]
    )
    return "\n".join(lines)


def _artifact_markdown(artifacts: Mapping[str, Any]) -> list[str]:
    return [
        "",
        "## MP4 / Render Proof",
        "",
        f"- Accepted MP4s: `{_nested(artifacts, 'real_rendering', 'accepted_mp4_count')}`",
        "- Render manifest valid: "
        f"`{_nested(artifacts, 'real_rendering', 'render_manifest_valid')}`",
        "- Optimization manifest valid: "
        f"`{_nested(artifacts, 'real_rendering', 'optimization_manifest_valid')}`",
        f"- Final payload valid: `{_nested(artifacts, 'real_rendering', 'final_payload_valid')}`",
        "",
        "## Long-Video Proof",
        "",
        f"- Source minutes: `{_nested(artifacts, 'long_video', 'source_duration_minutes')}`",
        f"- Accepted MP4s: `{_nested(artifacts, 'long_video', 'accepted_mp4_count')}`",
        f"- Planned clips: `{_nested(artifacts, 'long_video', 'planned_clip_count')}`",
        "",
        "## Durable Resume Proof",
        "",
        f"- Passing modes: `{_nested(artifacts, 'durable_resume', 'passing_modes')}`",
        f"- Accepted MP4s: `{_nested(artifacts, 'durable_resume', 'accepted_mp4_count')}`",
        "",
        "## Analysis Signals",
        "",
        f"- Synthetic passed: `{_nested(artifacts, 'analysis_signals', 'synthetic_passed')}`",
        "",
        "## Assets / Dependencies",
        "",
        f"- Self-check passed: `{_nested(artifacts, 'assets_dependencies', 'self_check_passed')}`",
        "- Repository check passed: "
        f"`{_nested(artifacts, 'assets_dependencies', 'repo_check_passed')}`",
    ]


def _nested(value: Mapping[str, Any], first: str, second: str) -> Any:
    nested = value.get(first)
    return nested.get(second) if isinstance(nested, Mapping) else None


def _redact_media_paths(value: str) -> str:
    return _MEDIA_PATH_PATTERN.sub(" <media-path-redacted>", value)


def _is_generated_path(path: str) -> bool:
    if path == ".env" or (path.startswith(".env.") and path != ".env.example"):
        return True
    if any(path.startswith(prefix) for prefix in _GENERATED_PREFIXES):
        return True
    return Path(path).suffix.lower() in _MEDIA_EXTENSIONS


def _normalized_path(value: str) -> str:
    return value.strip().replace("\\", "/").removeprefix("./")


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if item]


def _optional_string(value: Any) -> str | None:
    return str(value) if value not in {None, ""} else None


def _as_float(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0

"""Typed, persisted execution for fixed local Olympus and BOBA validators."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.workflow_controller import (
    BobaWorkflowStageDefinitionV1,
    validate_workflow_graph,
)
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.validation.face_motion import (
    FaceMotionValidationThresholdsV1,
    crop_motion_metrics,
    evaluate_face_crop_safety,
)
from olympus.validation.multi_speaker import (
    MultiSpeakerLayoutValidationThresholdsV1,
    evaluate_assigned_subject_regions,
    layout_motion_metrics,
)

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore


BobaValidatorCategoryV1 = Literal[
    "contract_schema",
    "artifact_integrity",
    "artifact_manifest",
    "project_identity",
    "workflow_state",
    "workflow_graph",
    "artifact_lineage",
    "checkpoint_integrity_read_only",
    "code_static",
    "code_types",
    "code_unit_tests",
    "code_regression_tests",
    "frontend_typecheck",
    "frontend_lint",
    "frontend_tests",
    "frontend_build",
    "tool_health",
    "media_probe",
    "media_decode",
    "media_streams",
    "media_duration",
    "source_window",
    "media_resolution",
    "media_aspect_ratio",
    "media_frame_rate",
    "audio_presence",
    "audio_format",
    "audio_video_sync",
    "caption_schema",
    "caption_presence",
    "caption_timing",
    "caption_bounds",
    "boundary_quality",
    "face_motion",
    "subject_visibility",
    "multi_speaker",
    "rendering_manifest",
    "recovery_output",
    "quality_evidence_support",
    "unknown",
]
BobaValidatorImplementationTypeV1 = Literal[
    "internal_python",
    "fixed_local_process",
    "fixed_media_probe",
    "fixed_media_decode",
    "unavailable_optional_provider",
    "future",
    "unknown",
]
BobaValidatorAvailabilityStatusV1 = Literal[
    "available",
    "degraded",
    "unavailable",
    "future",
    "blocked",
    "unknown",
]
BobaValidatorHealthStatusV1 = Literal[
    "healthy",
    "degraded",
    "unavailable",
    "incompatible",
    "unverified",
    "blocked",
    "unknown",
]
BobaValidationTargetTypeV1 = Literal[
    "project_artifact",
    "workflow_stage",
    "generated_output",
    "recovered_output",
    "checkpoint",
    "code_worktree",
    "code_patch_result",
    "tool_health",
    "validation_report",
    "unknown",
]
BobaValidationRunStatusV1 = Literal[
    "created",
    "validating_plan",
    "awaiting_safety_decision",
    "ready",
    "running",
    "cancelling",
    "cancelled",
    "completed",
    "failed",
    "blocked",
    "incomplete",
    "timed_out",
    "unknown",
]
BobaValidationCheckStatusV1 = Literal[
    "pending",
    "dependency_blocked",
    "ready",
    "running",
    "passed",
    "failed",
    "unavailable",
    "blocked",
    "errored",
    "timed_out",
    "cancelled",
    "skipped_not_required",
    "superseded",
    "unknown",
]
BobaValidationEvidenceSourceTypeV1 = Literal[
    "internal_validator",
    "fixed_process",
    "ffprobe",
    "ffmpeg_decode",
    "schema_check",
    "artifact_check",
    "workflow_check",
    "code_static_check",
    "test_runner",
    "frontend_runner",
    "media_validator",
    "existing_persisted_report",
    "unknown",
]
BobaValidationSuiteDecisionValueV1 = Literal[
    "passed",
    "passed_with_optional_warnings",
    "failed",
    "incomplete",
    "blocked",
    "errored",
    "timed_out",
    "cancelled",
    "invalid",
    "unknown",
]
BobaValidationIncidentTypeV1 = Literal[
    "invalid_plan",
    "unknown_validator",
    "unavailable_validator",
    "validator_version_mismatch",
    "input_mismatch",
    "stale_input",
    "malformed_input",
    "rights_block",
    "safety_block",
    "dependency_failure",
    "validator_failure",
    "validator_crash",
    "validator_timeout",
    "malformed_validator_output",
    "unexpected_file_modification",
    "budget_exhausted",
    "idempotency_conflict",
    "concurrency_conflict",
    "cancellation_failure",
    "uncertain_state",
    "unknown",
]
BobaValidationEventTypeV1 = Literal[
    "plan_created",
    "plan_validated",
    "run_created",
    "safety_review_required",
    "run_started",
    "check_started",
    "check_passed",
    "check_failed",
    "check_unavailable",
    "check_timed_out",
    "check_cancelled",
    "budget_warning",
    "run_cancel_requested",
    "run_cancelled",
    "suite_passed",
    "suite_failed",
    "suite_incomplete",
    "run_blocked",
    "unknown",
]
BobaValidationHandoffTargetV1 = Literal[
    "workflow_controller",
    "output_quality_reviewer",
    "autopilot_controller",
    "safety_gate",
    "repair_planner",
    "root_cause_analyzer",
    "code_surgeon",
    "tool_recovery_brain",
    "checkpoint_recovery_manager",
    "integration_layer",
    "final_decision_bus",
    "live_companion",
    "human_operator",
    "unknown",
]

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_URL = re.compile(r"(?i)^[a-z][a-z0-9+.-]*://")
_WINDOWS_ABSOLUTE = re.compile(r"(?i)^[a-z]:[\\/]")
_PRIVATE_WINDOWS_PATH = re.compile(r"(?i)\b[a-z]:[\\/][^\s\"']+")
_PRIVATE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users|root)/[^\s\"']+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SHELL_TOKEN = re.compile(r"(?:\|\||&&|[|><;`]|\$\()")
_SECRET_KEY = re.compile(
    r"(?i)(?:secret|password|passwd|token|credential|cookie|authorization|api[_-]?key)"
)
_OMITTED_EXPORT_KEYS = frozenset(
    {
        "bounded_stdout",
        "bounded_stderr",
        "complete_log",
        "complete_logs",
        "full_log",
        "full_logs",
        "media_bytes",
        "raw_audio",
        "raw_media",
        "raw_patch",
        "raw_video",
        "source_media_bytes",
    }
)
_RIGHTS_ALLOWED = frozenset(
    {
        "allowed",
        "eligible",
        "licensed",
        "owned",
        "permission_confirmed",
        "rights_confirmed",
    }
)
_TERMINAL_RUN_STATUSES = frozenset(
    {
        "cancelled",
        "completed",
        "failed",
        "blocked",
        "incomplete",
        "timed_out",
    }
)
_TERMINAL_CHECK_STATUSES = frozenset(
    {
        "passed",
        "failed",
        "unavailable",
        "blocked",
        "errored",
        "timed_out",
        "cancelled",
        "skipped_not_required",
        "superseded",
        "dependency_blocked",
    }
)
_PROCESS_MODULES = {
    "python.ruff": "ruff",
    "python.mypy": "mypy",
    "python.pytest_focused": "pytest",
    "python.pytest_regression": "pytest",
}
_FRONTEND_SCRIPTS = {
    "frontend.typecheck": "typecheck",
    "frontend.lint": "lint",
    "frontend.tests": "test",
    "frontend.build": "build",
}
_MEDIA_VALIDATORS = frozenset(
    {
        "media.ffprobe",
        "media.decode_to_null",
        "media.streams",
        "media.duration",
        "media.source_window",
        "media.resolution",
        "media.frame_rate",
        "media.audio_presence",
        "media.av_sync",
        "rendering.output_integrity",
        "recovery.output_integrity",
    }
)
_CODE_VALIDATORS = frozenset({*_PROCESS_MODULES, *_FRONTEND_SCRIPTS})
_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()
_DEFAULT_REGISTRY_CREATED_AT = "2026-07-30T00:00:00+00:00"
_DEFAULT_CAPTURE_BYTES = 131_072
_OWNED_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}
_OWNED_PROCESS_LOCK = threading.RLock()


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *values: Any) -> str:
    return f"{prefix}_{_digest(values)[:24]}"


def _runtime_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _bounded_text(value: Any, *, maximum: int = 900) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _unique(values: Sequence[Any], *, limit: int = 64, maximum: int = 256) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _bounded_text(value, maximum=maximum)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[depth-limited]"
    if isinstance(value, BobaContract):
        return _json_safe(value.model_dump(mode="json"), depth=depth + 1)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:512]:
            key = _bounded_text(raw_key, maximum=160)
            if not key:
                continue
            if _SECRET_KEY.search(key):
                result[key] = "[redacted]"
            else:
                result[key] = _json_safe(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:2_048]]
    if isinstance(value, str):
        return value[:4_000]
    if value is None or isinstance(value, bool | int | float):
        return value
    return _bounded_text(value, maximum=900)


def sanitize_validator_export(value: Any) -> Any:
    """Return bounded JSON evidence without private paths, secrets, or full logs."""

    if isinstance(value, BobaContract):
        return sanitize_validator_export(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:512]:
            key = _bounded_text(raw_key, maximum=160)
            if not key:
                continue
            if _SECRET_KEY.search(key):
                result[key] = "[redacted]"
            elif key.casefold() in _OMITTED_EXPORT_KEYS:
                result[key] = "[omitted]"
            else:
                result[key] = sanitize_validator_export(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [sanitize_validator_export(item) for item in list(value)[:2_048]]
    if isinstance(value, str):
        text = value[:4_000]
        text = _PRIVATE_WINDOWS_PATH.sub("[private-path-redacted]", text)
        text = _PRIVATE_POSIX_PATH.sub("[private-path-redacted]", text)
        return text
    if value is None or isinstance(value, bool | int | float):
        return value
    return _bounded_text(value, maximum=900)


def _validate_storage_reference(value: str) -> str:
    reference = value.strip().replace("\\", "/")
    if not reference:
        return reference
    if _URL.match(reference):
        raise ValueError("External validation target URLs are unavailable.")
    if reference.startswith("//") or _WINDOWS_ABSOLUTE.match(reference):
        raise ValueError("Absolute and UNC storage references are unavailable.")
    if reference.startswith("/"):
        raise ValueError("Absolute storage references are unavailable.")
    if any(part in {"", ".", ".."} for part in reference.split("/")):
        raise ValueError("Traversal and malformed storage references are unavailable.")
    return reference


def _validate_digest(value: str) -> str:
    normalized = value.strip().casefold()
    if not _DIGEST.fullmatch(normalized):
        raise ValueError("A lowercase SHA-256 digest is required.")
    return normalized


class BobaValidatorRegistrySnapshotV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = Field(default="1", min_length=1, max_length=80)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    validator_ids: list[str] = Field(default_factory=list, max_length=256)
    validator_versions: dict[str, str] = Field(default_factory=dict, max_length=256)
    available_validator_ids: list[str] = Field(default_factory=list, max_length=256)
    degraded_validator_ids: list[str] = Field(default_factory=list, max_length=256)
    unavailable_validator_ids: list[str] = Field(default_factory=list, max_length=256)
    future_validator_ids: list[str] = Field(default_factory=list, max_length=256)
    registry_sha256: str = Field(min_length=64, max_length=64)
    immutable: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    _digest_field = field_validator("registry_sha256")(_validate_digest)


class BobaValidatorDescriptorV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    validator_id: str = Field(min_length=1, max_length=180)
    display_name: str = Field(min_length=1, max_length=240)
    validator_version: str = Field(default="1", min_length=1, max_length=80)
    category: BobaValidatorCategoryV1
    implementation_type: BobaValidatorImplementationTypeV1
    adapter_id: str = Field(min_length=1, max_length=180)
    supported_target_types: list[BobaValidationTargetTypeV1] = Field(
        default_factory=list,
        max_length=32,
    )
    supported_artifact_types: list[str] = Field(default_factory=list, max_length=64)
    input_schema_ids: list[str] = Field(default_factory=list, max_length=64)
    output_schema_id: str = Field(min_length=1, max_length=180)
    required_tool_ids: list[str] = Field(default_factory=list, max_length=32)
    required_provider_ids: list[str] = Field(default_factory=list, max_length=32)
    availability_status: BobaValidatorAvailabilityStatusV1
    availability_reason: str = Field(default="", max_length=700)
    read_only: bool = True
    runner_owned_temp_writes: bool = False
    protected_state_mutation_allowed: Literal[False] = False
    rights_gate_required: bool = False
    safety_gate_required: bool = False
    target_approval_required: bool = False
    supported_platforms: list[str] = Field(default_factory=list, max_length=16)
    default_timeout_seconds: int = Field(default=60, ge=1, le=3_600)
    maximum_timeout_seconds: int = Field(default=900, ge=1, le=3_600)
    default_maximum_attempts: int = Field(default=1, ge=1, le=4)
    deterministic: bool = True
    idempotency_supported: bool = True
    health_status: BobaValidatorHealthStatusV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("validator_id", "adapter_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("Validator and adapter IDs use bounded safe characters only.")
        return value

    @model_validator(mode="after")
    def validate_availability(self) -> BobaValidatorDescriptorV1:
        if (
            self.availability_status == "available"
            and self.implementation_type
            in {"future", "unavailable_optional_provider", "unknown"}
        ):
            raise ValueError("Unavailable or future implementations cannot be available.")
        if self.default_timeout_seconds > self.maximum_timeout_seconds:
            raise ValueError("Default timeout cannot exceed the validator maximum.")
        return self


class BobaValidationPlanV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    validation_plan_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    workflow_run_id: str = Field(default="", max_length=180)
    stage_instance_id: str = Field(default="", max_length=180)
    autopilot_run_id: str = Field(default="", max_length=180)
    repair_plan_id: str = Field(default="", max_length=180)
    code_surgeon_run_id: str = Field(default="", max_length=180)
    tool_recovery_run_id: str = Field(default="", max_length=180)
    output_quality_review_id: str = Field(default="", max_length=180)
    plan_source_module: str = Field(min_length=1, max_length=160)
    plan_source_record_id: str = Field(default="", max_length=180)
    target_type: BobaValidationTargetTypeV1
    target_id: str = Field(min_length=1, max_length=180)
    target_digest: str = Field(min_length=64, max_length=64)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    check_ids: list[str] = Field(min_length=1, max_length=64)
    ordered_check_ids: list[str] = Field(min_length=1, max_length=64)
    required_check_ids: list[str] = Field(default_factory=list, max_length=64)
    optional_check_ids: list[str] = Field(default_factory=list, max_length=64)
    validation_objective: str = Field(min_length=1, max_length=900)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=64)
    rejection_criteria: list[str] = Field(min_length=1, max_length=64)
    execution_policy_id: str = Field(min_length=1, max_length=180)
    resource_budget_id: str = Field(min_length=1, max_length=180)
    approval_record_id: str = Field(default="", max_length=180)
    safety_decision_id: str = Field(default="", max_length=180)
    plan_digest: str = Field(min_length=64, max_length=64)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    expires_at: str = Field(min_length=1, max_length=80)
    immutable_after_run_start: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    _target_digest_field = field_validator(
        "target_digest",
        "project_snapshot_digest",
        "plan_digest",
    )(_validate_digest)

    @model_validator(mode="after")
    def validate_check_sets(self) -> BobaValidationPlanV1:
        checks = set(self.check_ids)
        if len(checks) != len(self.check_ids):
            raise ValueError("Validation plan check IDs must be unique.")
        if set(self.ordered_check_ids) != checks:
            raise ValueError("Ordered checks must contain every plan check exactly once.")
        if set(self.required_check_ids) & set(self.optional_check_ids):
            raise ValueError("Required and optional checks must be disjoint.")
        if set(self.required_check_ids) | set(self.optional_check_ids) != checks:
            raise ValueError("Every check must be required or optional.")
        return self


class BobaValidationPlanCheckV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_check_id: str = Field(min_length=1, max_length=180)
    validation_plan_id: str = Field(min_length=1, max_length=180)
    validator_id: str = Field(min_length=1, max_length=180)
    validator_version: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=240)
    category: BobaValidatorCategoryV1
    required: bool = True
    order: int = Field(ge=0, le=255)
    dependency_check_ids: list[str] = Field(default_factory=list, max_length=64)
    input_binding_ids: list[str] = Field(default_factory=list, max_length=64)
    expected_values: dict[str, Any] = Field(default_factory=dict, max_length=64)
    tolerance: dict[str, float] = Field(default_factory=dict, max_length=32)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=32)
    rejection_criteria: list[str] = Field(min_length=1, max_length=32)
    timeout_seconds: int = Field(ge=1, le=3_600)
    maximum_attempts: int = Field(default=1, ge=1, le=4)
    stop_suite_on_failure: bool = False
    safety_gate_required: bool = False
    approval_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="before")
    @classmethod
    def reject_execution_injection(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            prohibited = {
                "adapter",
                "adapter_id",
                "arguments",
                "callable",
                "callable_path",
                "command",
                "command_string",
                "executable",
                "flags",
                "import_path",
                "parser",
            }
            unexpected = sorted(prohibited & set(value))
            if unexpected:
                raise ValueError(
                    "Validation checks cannot provide adapters, commands, or callables."
                )
        return value


class BobaValidationInputBindingV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_binding_id: str = Field(min_length=1, max_length=180)
    validation_plan_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str = Field(default="", max_length=180)
    stage_instance_id: str = Field(default="", max_length=180)
    clip_id: str = Field(default="", max_length=180)
    output_id: str = Field(default="", max_length=180)
    artifact_type: str = Field(min_length=1, max_length=160)
    producer_module_id: str = Field(default="", max_length=160)
    producer_record_id: str = Field(default="", max_length=180)
    schema_id: str = Field(default="", max_length=180)
    schema_version: str = Field(default="1", max_length=80)
    artifact_digest: str = Field(min_length=64, max_length=64)
    sanitized_storage_reference: str = Field(default="", max_length=500)
    exact_local_target: str = Field(default="", max_length=1_024)
    immutable: bool = True
    source_media: bool = False
    source_media_read_only: bool = True
    accepted_output: bool = False
    required: bool = True
    available: bool = True
    stale: bool = False
    malformed: bool = False
    rights_status: str = Field(default="unknown", max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=32)

    _artifact_digest_field = field_validator("artifact_digest")(_validate_digest)

    @field_validator("sanitized_storage_reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        return _validate_storage_reference(value)

    @model_validator(mode="after")
    def validate_protection(self) -> BobaValidationInputBindingV1:
        if self.available and not (
            self.sanitized_storage_reference or self.exact_local_target
        ):
            raise ValueError("Available validation inputs require an exact target.")
        if self.source_media and not self.source_media_read_only:
            raise ValueError("Source media must remain read-only.")
        if self.source_media and self.accepted_output:
            raise ValueError("Source media cannot be an accepted generated output.")
        if self.accepted_output and not self.immutable:
            raise ValueError("Accepted outputs must remain immutable.")
        reference_parts = self.sanitized_storage_reference.split("/")
        if (
            len(reference_parts) >= 2
            and reference_parts[0] in {"projects", "render", "uploads"}
            and self.project_id not in reference_parts
        ):
            raise ValueError("Cross-project validation bindings are unavailable.")
        return self


class BobaValidationEnvironmentSnapshotV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    environment_snapshot_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    platform: str = Field(min_length=1, max_length=120)
    architecture: str = Field(min_length=1, max_length=120)
    normalized_runtime_version: str = Field(min_length=1, max_length=120)
    registered_tool_versions: dict[str, str] = Field(
        default_factory=dict,
        max_length=64,
    )
    registered_tool_digests: dict[str, str] = Field(
        default_factory=dict,
        max_length=64,
    )
    optional_provider_status: dict[str, str] = Field(
        default_factory=dict,
        max_length=64,
    )
    workspace_mode: str = Field(min_length=1, max_length=120)
    workspace_digest: str = Field(min_length=64, max_length=64)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    sanitized_environment_keys: list[str] = Field(default_factory=list, max_length=64)
    network_required: Literal[False] = False
    network_requested: Literal[False] = False
    runner_owned_temp_root: str = Field(min_length=1, max_length=500)
    environment_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    _digest_fields = field_validator(
        "workspace_digest",
        "project_snapshot_digest",
        "environment_digest",
    )(_validate_digest)


class BobaValidationExecutionPolicyV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_policy_id: str = Field(min_length=1, max_length=180)
    policy_version: str = Field(default="1", min_length=1, max_length=80)
    allowed_implementation_types: list[BobaValidatorImplementationTypeV1] = Field(
        default_factory=list,
        max_length=16,
    )
    allowed_adapter_ids: list[str] = Field(default_factory=list, max_length=128)
    allowed_executable_ids: list[str] = Field(default_factory=list, max_length=32)
    allowed_working_roots: list[str] = Field(default_factory=list, max_length=16)
    allowed_target_types: list[BobaValidationTargetTypeV1] = Field(
        default_factory=list,
        max_length=16,
    )
    shell_allowed: Literal[False] = False
    pipes_allowed: Literal[False] = False
    redirects_allowed: Literal[False] = False
    command_chaining_allowed: Literal[False] = False
    network_allowed: Literal[False] = False
    package_installation_allowed: Literal[False] = False
    external_service_allowed: Literal[False] = False
    source_media_modification_allowed: Literal[False] = False
    accepted_output_modification_allowed: Literal[False] = False
    tracked_source_modification_allowed: Literal[False] = False
    runner_owned_temp_writes_allowed: Literal[True] = True
    owned_child_termination_allowed: Literal[True] = True
    unrelated_process_termination_allowed: Literal[False] = False
    maximum_capture_bytes: int = Field(
        default=_DEFAULT_CAPTURE_BYTES,
        ge=1_024,
        le=1_048_576,
    )
    policy_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)

    _policy_digest_field = field_validator("policy_digest")(_validate_digest)


class BobaValidationResourceBudgetV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_budget_id: str = Field(min_length=1, max_length=180)
    validation_plan_id: str = Field(min_length=1, max_length=180)
    maximum_check_count: int = Field(default=64, ge=1, le=64)
    maximum_parallel_checks: int = Field(default=2, ge=1, le=2)
    maximum_total_duration_seconds: int = Field(default=1_800, ge=1, le=1_800)
    maximum_single_check_duration_seconds: int = Field(
        default=900,
        ge=1,
        le=900,
    )
    maximum_total_attempts: int = Field(default=128, ge=1, le=128)
    maximum_identical_retries: int = Field(default=1, ge=0, le=1)
    maximum_capture_bytes_per_stream: int = Field(
        default=_DEFAULT_CAPTURE_BYTES,
        ge=1_024,
        le=_DEFAULT_CAPTURE_BYTES,
    )
    maximum_temp_storage_bytes: int = Field(
        default=536_870_912,
        ge=1_048_576,
        le=536_870_912,
    )
    maximum_media_sample_seconds: int = Field(default=30, ge=1, le=30)
    maximum_sampled_frames: int = Field(default=12, ge=1, le=12)
    maximum_cpu_processes: int = Field(default=2, ge=1, le=2)
    budget_reset_requires_approval: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaValidationRunV1(BobaContract):
    validation_run_id: str = Field(min_length=1, max_length=180)
    validation_plan_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str = Field(default="", max_length=180)
    stage_instance_id: str = Field(default="", max_length=180)
    target_type: BobaValidationTargetTypeV1
    target_id: str = Field(min_length=1, max_length=180)
    target_digest: str = Field(min_length=64, max_length=64)
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    environment_snapshot_id: str = Field(min_length=1, max_length=180)
    execution_policy_id: str = Field(min_length=1, max_length=180)
    resource_budget_id: str = Field(min_length=1, max_length=180)
    correlation_id: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    started_at: str | None = Field(default=None, max_length=80)
    completed_at: str | None = Field(default=None, max_length=80)
    run_status: BobaValidationRunStatusV1 = "created"
    active_check_run_id: str = Field(default="", max_length=180)
    completed_check_run_ids: list[str] = Field(default_factory=list, max_length=256)
    failed_check_run_ids: list[str] = Field(default_factory=list, max_length=256)
    blocked_check_run_ids: list[str] = Field(default_factory=list, max_length=256)
    unavailable_check_run_ids: list[str] = Field(default_factory=list, max_length=256)
    timed_out_check_run_ids: list[str] = Field(default_factory=list, max_length=256)
    skipped_check_run_ids: list[str] = Field(default_factory=list, max_length=256)
    suite_decision_id: str = Field(default="", max_length=180)
    lease_id: str = Field(default="", max_length=180)
    idempotency_key: str = Field(min_length=1, max_length=180)
    cancellation_requested: bool = False
    stop_reason: str = Field(default="", max_length=900)
    project_state_uncertain: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    _target_digest_field = field_validator("target_digest")(_validate_digest)


class BobaValidationCheckRunV1(BobaContract):
    check_run_id: str = Field(min_length=1, max_length=180)
    validation_run_id: str = Field(min_length=1, max_length=180)
    plan_check_id: str = Field(min_length=1, max_length=180)
    validator_id: str = Field(min_length=1, max_length=180)
    validator_version: str = Field(min_length=1, max_length=80)
    category: BobaValidatorCategoryV1
    required: bool = True
    attempt_number: int = Field(default=1, ge=1, le=4)
    status: BobaValidationCheckStatusV1 = "pending"
    adapter_id: str = Field(min_length=1, max_length=180)
    input_binding_ids: list[str] = Field(default_factory=list, max_length=64)
    input_digest: str = Field(min_length=64, max_length=64)
    environment_digest: str = Field(min_length=64, max_length=64)
    started_at: str | None = Field(default=None, max_length=80)
    completed_at: str | None = Field(default=None, max_length=80)
    duration_seconds: float | None = Field(default=None, ge=0.0, le=3_600.0)
    timeout_seconds: int = Field(ge=1, le=3_600)
    exit_code: int | None = None
    result_id: str = Field(default="", max_length=180)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    bounded_stdout: str = Field(default="", max_length=8_192)
    bounded_stderr: str = Field(default="", max_length=8_192)
    output_truncated: bool = False
    owned_child_terminated: bool = False
    protected_state_unchanged: bool = True
    failure_summary: str = Field(default="", max_length=900)
    retryable: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)

    _digest_fields = field_validator("input_digest", "environment_digest")(
        _validate_digest
    )


class BobaValidationEvidenceV1(BobaContract):
    evidence_id: str = Field(min_length=1, max_length=180)
    validation_run_id: str = Field(min_length=1, max_length=180)
    check_run_id: str = Field(min_length=1, max_length=180)
    source_type: BobaValidationEvidenceSourceTypeV1
    validator_id: str = Field(min_length=1, max_length=180)
    category: BobaValidatorCategoryV1
    bounded_summary: str = Field(min_length=1, max_length=900)
    observed_value: Any = None
    expected_value: Any = None
    tolerance: dict[str, float] = Field(default_factory=dict, max_length=32)
    evidence_digest: str = Field(min_length=64, max_length=64)
    reliability: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    supports_pass: bool = False
    supports_failure: bool = False
    requires_human_interpretation: bool = False
    redacted: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)

    _evidence_digest_field = field_validator("evidence_digest")(_validate_digest)


class BobaValidationResultV1(BobaContract):
    result_id: str = Field(min_length=1, max_length=180)
    validation_run_id: str = Field(min_length=1, max_length=180)
    check_run_id: str = Field(min_length=1, max_length=180)
    validator_id: str = Field(min_length=1, max_length=180)
    status: BobaValidationCheckStatusV1
    assertion_results: dict[str, bool | None] = Field(
        default_factory=dict,
        max_length=128,
    )
    measured_values: dict[str, Any] = Field(default_factory=dict, max_length=128)
    expected_values: dict[str, Any] = Field(default_factory=dict, max_length=128)
    failed_assertions: list[str] = Field(default_factory=list, max_length=128)
    unavailable_assertions: list[str] = Field(default_factory=list, max_length=128)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    required_check: bool = True
    blocks_suite_pass: bool = True
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    result_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)

    _result_digest_field = field_validator("result_digest")(_validate_digest)


class BobaValidationSuiteDecisionV1(BobaContract):
    suite_decision_id: str = Field(min_length=1, max_length=180)
    validation_run_id: str = Field(min_length=1, max_length=180)
    validation_plan_id: str = Field(min_length=1, max_length=180)
    decision: BobaValidationSuiteDecisionValueV1
    decision_summary: str = Field(min_length=1, max_length=900)
    required_checks_complete: bool = False
    required_checks_passed: bool = False
    optional_checks_complete: bool = False
    failed_required_check_ids: list[str] = Field(default_factory=list, max_length=64)
    incomplete_required_check_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    unavailable_required_check_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    timed_out_required_check_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    failed_optional_check_ids: list[str] = Field(default_factory=list, max_length=64)
    warning_check_ids: list[str] = Field(default_factory=list, max_length=64)
    acceptance_criteria_met: bool = False
    rejection_criteria_triggered: bool = False
    evidence_complete: bool = False
    target_digest_unchanged: bool = False
    environment_digest_unchanged: bool = False
    project_snapshot_current: bool = False
    technical_validation_passed: bool = False
    output_quality_authorized: Literal[False] = False
    workflow_transition_authorized: Literal[False] = False
    upload_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    human_review_required: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaValidationIncidentV1(BobaContract):
    incident_id: str = Field(min_length=1, max_length=180)
    validation_run_id: str = Field(min_length=1, max_length=180)
    check_run_id: str = Field(default="", max_length=180)
    incident_type: BobaValidationIncidentTypeV1
    severity: Literal["info", "low", "medium", "high", "critical", "unknown"]
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(min_length=1, max_length=900)
    observed_at: str = Field(default_factory=now_iso, max_length=80)
    validator_id: str = Field(default="", max_length=180)
    target_id: str = Field(default="", max_length=180)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    repeated_fingerprint: str = Field(min_length=64, max_length=64)
    occurrence_count: int = Field(default=1, ge=1, le=10_000)
    project_state_uncertain: bool = False
    protected_state_risk: bool = False
    immediate_runner_action: str = Field(default="", max_length=700)
    recommended_target_module: str = Field(default="", max_length=160)
    human_review_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)

    _fingerprint_field = field_validator("repeated_fingerprint")(_validate_digest)


class BobaValidationEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    validation_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str = Field(default="", max_length=180)
    sequence: int = Field(ge=1)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    event_type: BobaValidationEventTypeV1
    severity: Literal["info", "warning", "error", "critical", "unknown"]
    check_run_id: str = Field(default="", max_length=180)
    validator_id: str = Field(default="", max_length=180)
    technical_message: str = Field(min_length=1, max_length=900)
    easy_message: str = Field(min_length=1, max_length=900)
    confirmed_fact: str = Field(default="", max_length=900)
    assessment: str = Field(default="", max_length=900)
    progress_current: int | None = Field(default=None, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    progress_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    requires_attention: bool = False
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaValidationHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=180)
    validation_run_id: str = Field(min_length=1, max_length=180)
    suite_decision_id: str = Field(min_length=1, max_length=180)
    source_module_id: Literal["validator_runner"] = "validator_runner"
    target_module_id: BobaValidationHandoffTargetV1
    reason: str = Field(min_length=1, max_length=900)
    target_id: str = Field(min_length=1, max_length=180)
    result_ids: list[str] = Field(default_factory=list, max_length=128)
    failed_required_check_ids: list[str] = Field(default_factory=list, max_length=64)
    incomplete_required_check_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    evidence_ids: list[str] = Field(default_factory=list, max_length=128)
    satisfied_conditions: list[str] = Field(default_factory=list, max_length=64)
    blocking_conditions: list[str] = Field(default_factory=list, max_length=64)
    allowed_actions: list[str] = Field(default_factory=list, max_length=64)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=64)
    apply_automatically: bool = False
    human_approval_required: bool = False
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    warnings: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def prevent_automatic_execution(self) -> BobaValidationHandoffV1:
        if self.apply_automatically and self.target_module_id in {
            "workflow_controller",
            "autopilot_controller",
            "repair_planner",
            "code_surgeon",
            "tool_recovery_brain",
            "checkpoint_recovery_manager",
            "integration_layer",
            "final_decision_bus",
        }:
            raise ValueError("Execution and workflow handoffs cannot apply automatically.")
        return self


class BobaValidationLeaseV1(BobaContract):
    lease_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    validation_run_id: str = Field(min_length=1, max_length=180)
    validation_plan_id: str = Field(min_length=1, max_length=180)
    target_id: str = Field(min_length=1, max_length=180)
    owner_id: str = Field(min_length=1, max_length=180)
    acquired_at: str = Field(default_factory=now_iso, max_length=80)
    refreshed_at: str = Field(default_factory=now_iso, max_length=80)
    expires_at: str = Field(min_length=1, max_length=80)
    lease_status: Literal[
        "active",
        "released",
        "expired",
        "conflicting",
        "unknown",
    ] = "active"
    stale: bool = False
    environment_digest: str = Field(min_length=64, max_length=64)
    workspace_reference: str = Field(min_length=1, max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=32)

    _environment_digest_field = field_validator("environment_digest")(
        _validate_digest
    )


class BobaValidatorRunnerSummaryV1(BobaContract):
    registry_snapshot_count: int = Field(default=0, ge=0)
    registered_validator_count: int = Field(default=0, ge=0)
    available_validator_count: int = Field(default=0, ge=0)
    degraded_validator_count: int = Field(default=0, ge=0)
    unavailable_validator_count: int = Field(default=0, ge=0)
    future_validator_count: int = Field(default=0, ge=0)
    total_plan_count: int = Field(default=0, ge=0)
    total_run_count: int = Field(default=0, ge=0)
    active_run_count: int = Field(default=0, ge=0)
    passed_suite_count: int = Field(default=0, ge=0)
    warning_suite_count: int = Field(default=0, ge=0)
    failed_suite_count: int = Field(default=0, ge=0)
    incomplete_suite_count: int = Field(default=0, ge=0)
    blocked_suite_count: int = Field(default=0, ge=0)
    timed_out_suite_count: int = Field(default=0, ge=0)
    cancelled_suite_count: int = Field(default=0, ge=0)
    total_check_count: int = Field(default=0, ge=0)
    passed_check_count: int = Field(default=0, ge=0)
    failed_check_count: int = Field(default=0, ge=0)
    unavailable_check_count: int = Field(default=0, ge=0)
    timed_out_check_count: int = Field(default=0, ge=0)
    idempotent_reuse_count: int = Field(default=0, ge=0)
    highest_priority_incident: str = Field(default="", max_length=160)
    current_validation_run_id: str = Field(default="", max_length=180)
    current_validator: str = Field(default="", max_length=180)
    safest_next_action: str = Field(default="", max_length=900)
    required_human_actions: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaValidatorRunnerSignalUsageV1(BobaContract):
    validator_registry_used: bool = False
    internal_python_validator_used: bool = False
    fixed_local_process_used: bool = False
    registered_ffprobe_used: bool = False
    registered_ffmpeg_decode_used: bool = False
    schema_validation_used: bool = False
    artifact_validation_used: bool = False
    workflow_validation_used: bool = False
    code_static_validation_used: bool = False
    code_test_validation_used: bool = False
    frontend_validation_used: bool = False
    media_validation_used: bool = False
    checkpoint_read_only_validation_used: bool = False
    integration_layer_used: bool = False
    safety_gate_used: bool = False
    workflow_controller_context_used: bool = False
    output_quality_context_used: bool = False
    target_module_approval_used: bool = False
    idempotency_used: bool = False
    execution_lease_used: bool = False
    runner_owned_temp_state_used: bool = False
    owned_child_process_termination_used: bool = False
    arbitrary_command_execution_used: Literal[False] = False
    arbitrary_dynamic_import_used: Literal[False] = False
    arbitrary_function_invocation_used: Literal[False] = False
    shell_execution_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_outputs_modified: Literal[False] = False
    protected_source_modified: Literal[False] = False
    checkpoint_restore_used: Literal[False] = False
    workflow_transition_used: Literal[False] = False
    output_quality_authorization_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_access_used: Literal[False] = False
    downloading_used: Literal[False] = False
    uploading_used: Literal[False] = False
    publication_used: Literal[False] = False
    push_used: Literal[False] = False
    merge_used: Literal[False] = False
    deployment_used: Literal[False] = False
    rights_bypass_used: Literal[False] = False
    safety_bypass_used: Literal[False] = False
    unrelated_process_termination_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=128)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaValidatorRunnerSetV1(BobaContract):
    schema_version: Literal[
        "boba_validator_runner_v1"
    ] = "boba_validator_runner_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    registry_snapshots: list[BobaValidatorRegistrySnapshotV1] = Field(
        default_factory=list,
        max_length=64,
    )
    validator_descriptors: list[BobaValidatorDescriptorV1] = Field(
        default_factory=list,
        max_length=256,
    )
    validation_plans: list[BobaValidationPlanV1] = Field(
        default_factory=list,
        max_length=256,
    )
    plan_checks: list[BobaValidationPlanCheckV1] = Field(
        default_factory=list,
        max_length=4_096,
    )
    validation_runs: list[BobaValidationRunV1] = Field(
        default_factory=list,
        max_length=512,
    )
    check_runs: list[BobaValidationCheckRunV1] = Field(
        default_factory=list,
        max_length=8_192,
    )
    input_bindings: list[BobaValidationInputBindingV1] = Field(
        default_factory=list,
        max_length=4_096,
    )
    environment_snapshots: list[BobaValidationEnvironmentSnapshotV1] = Field(
        default_factory=list,
        max_length=512,
    )
    execution_policies: list[BobaValidationExecutionPolicyV1] = Field(
        default_factory=list,
        max_length=512,
    )
    resource_budgets: list[BobaValidationResourceBudgetV1] = Field(
        default_factory=list,
        max_length=512,
    )
    evidence_records: list[BobaValidationEvidenceV1] = Field(
        default_factory=list,
        max_length=16_384,
    )
    validation_results: list[BobaValidationResultV1] = Field(
        default_factory=list,
        max_length=8_192,
    )
    suite_decisions: list[BobaValidationSuiteDecisionV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    incidents: list[BobaValidationIncidentV1] = Field(
        default_factory=list,
        max_length=4_096,
    )
    events: list[BobaValidationEventV1] = Field(
        default_factory=list,
        max_length=16_384,
    )
    handoffs: list[BobaValidationHandoffV1] = Field(
        default_factory=list,
        max_length=4_096,
    )
    runner_summary: BobaValidatorRunnerSummaryV1 = Field(
        default_factory=BobaValidatorRunnerSummaryV1
    )
    signal_usage: BobaValidatorRunnerSignalUsageV1 = Field(
        default_factory=BobaValidatorRunnerSignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=128)


@dataclass(frozen=True, slots=True)
class _ValidatorSpec:
    validator_id: str
    display_name: str
    category: BobaValidatorCategoryV1
    implementation_type: BobaValidatorImplementationTypeV1
    target_types: tuple[BobaValidationTargetTypeV1, ...]
    artifact_types: tuple[str, ...]
    tool_ids: tuple[str, ...] = ()
    provider_ids: tuple[str, ...] = ()
    rights: bool = False
    safety: bool = False
    approval: bool = False
    temp_writes: bool = False
    timeout: int = 60
    maximum_timeout: int = 900
    deterministic: bool = True
    limitations: tuple[str, ...] = ()


_FIXED_VALIDATOR_SPECS: tuple[_ValidatorSpec, ...] = (
    _ValidatorSpec(
        "artifact.schema",
        "Artifact schema",
        "contract_schema",
        "internal_python",
        ("project_artifact", "validation_report"),
        ("json", "manifest", "report"),
    ),
    _ValidatorSpec(
        "artifact.digest",
        "Artifact digest",
        "artifact_integrity",
        "internal_python",
        (
            "project_artifact",
            "generated_output",
            "recovered_output",
            "checkpoint",
            "validation_report",
        ),
        ("file", "json", "manifest", "media"),
    ),
    _ValidatorSpec(
        "artifact.manifest",
        "Artifact manifest",
        "artifact_manifest",
        "internal_python",
        ("project_artifact", "validation_report"),
        ("manifest", "json"),
    ),
    _ValidatorSpec(
        "workflow.graph",
        "Workflow graph",
        "workflow_graph",
        "internal_python",
        ("workflow_stage", "project_artifact"),
        ("workflow_definition", "json"),
    ),
    _ValidatorSpec(
        "workflow.transition",
        "Workflow transition",
        "workflow_state",
        "internal_python",
        ("workflow_stage",),
        ("workflow_controller", "json"),
    ),
    _ValidatorSpec(
        "workflow.artifact_lineage",
        "Workflow artifact lineage",
        "artifact_lineage",
        "internal_python",
        ("workflow_stage", "project_artifact"),
        ("artifact_binding", "json"),
    ),
    _ValidatorSpec(
        "checkpoint.integrity_read_only",
        "Checkpoint integrity read-only",
        "checkpoint_integrity_read_only",
        "internal_python",
        ("checkpoint",),
        ("checkpoint", "json"),
    ),
    _ValidatorSpec(
        "rendering.manifest",
        "Rendering manifest",
        "rendering_manifest",
        "internal_python",
        ("generated_output", "recovered_output", "project_artifact"),
        ("render_manifest", "manifest", "json"),
    ),
    _ValidatorSpec(
        "media.ffprobe",
        "Media FFprobe",
        "media_probe",
        "fixed_media_probe",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
        timeout=60,
    ),
    _ValidatorSpec(
        "media.decode_to_null",
        "Media decode to null",
        "media_decode",
        "fixed_media_decode",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        ("ffmpeg",),
        rights=True,
        safety=True,
        temp_writes=True,
        timeout=120,
    ),
    _ValidatorSpec(
        "media.streams",
        "Media streams",
        "media_streams",
        "fixed_media_probe",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
    ),
    _ValidatorSpec(
        "media.duration",
        "Media duration",
        "media_duration",
        "fixed_media_probe",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
    ),
    _ValidatorSpec(
        "media.source_window",
        "Media source window",
        "source_window",
        "fixed_media_probe",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
    ),
    _ValidatorSpec(
        "media.resolution",
        "Media resolution",
        "media_resolution",
        "fixed_media_probe",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
    ),
    _ValidatorSpec(
        "media.frame_rate",
        "Media frame rate",
        "media_frame_rate",
        "fixed_media_probe",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
    ),
    _ValidatorSpec(
        "media.audio_presence",
        "Media audio presence",
        "audio_presence",
        "fixed_media_probe",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
    ),
    _ValidatorSpec(
        "media.av_sync",
        "Media A/V synchronization",
        "audio_video_sync",
        "fixed_media_probe",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
    ),
    _ValidatorSpec(
        "captions.schema",
        "Caption schema",
        "caption_schema",
        "internal_python",
        ("project_artifact", "generated_output", "recovered_output"),
        ("captions", "timeline", "json"),
    ),
    _ValidatorSpec(
        "captions.timing",
        "Caption timing",
        "caption_timing",
        "internal_python",
        ("project_artifact", "generated_output", "recovered_output"),
        ("captions", "timeline", "json"),
    ),
    _ValidatorSpec(
        "captions.bounds",
        "Caption bounds",
        "caption_bounds",
        "internal_python",
        ("project_artifact", "generated_output", "recovered_output"),
        ("captions", "timeline", "json"),
    ),
    _ValidatorSpec(
        "validation.face_motion",
        "Face and motion artifact validation",
        "face_motion",
        "internal_python",
        ("project_artifact", "generated_output"),
        ("face_tracking_plan", "timeline", "json"),
    ),
    _ValidatorSpec(
        "validation.multi_speaker",
        "Multi-speaker artifact validation",
        "multi_speaker",
        "internal_python",
        ("project_artifact", "generated_output"),
        ("multi_speaker_layout", "timeline", "json"),
    ),
    _ValidatorSpec(
        "rendering.output_integrity",
        "Rendering output integrity",
        "recovery_output",
        "fixed_media_probe",
        ("generated_output",),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
    ),
    _ValidatorSpec(
        "recovery.output_integrity",
        "Recovery output integrity",
        "recovery_output",
        "fixed_media_probe",
        ("recovered_output",),
        ("mp4", "media"),
        ("ffprobe",),
        rights=True,
        safety=True,
        approval=True,
    ),
    _ValidatorSpec(
        "tool.health",
        "Registered tool health",
        "tool_health",
        "internal_python",
        ("tool_health",),
        ("tool",),
    ),
    _ValidatorSpec(
        "python.ruff",
        "Ruff",
        "code_static",
        "fixed_local_process",
        ("code_worktree", "code_patch_result"),
        ("code_workspace",),
        ("python", "ruff"),
        safety=True,
        approval=True,
        temp_writes=True,
        timeout=300,
    ),
    _ValidatorSpec(
        "python.mypy",
        "Mypy",
        "code_types",
        "fixed_local_process",
        ("code_worktree", "code_patch_result"),
        ("code_workspace",),
        ("python", "mypy"),
        safety=True,
        approval=True,
        temp_writes=True,
        timeout=600,
    ),
    _ValidatorSpec(
        "python.pytest_focused",
        "Focused pytest",
        "code_unit_tests",
        "fixed_local_process",
        ("code_worktree", "code_patch_result"),
        ("code_workspace",),
        ("python", "pytest"),
        safety=True,
        approval=True,
        temp_writes=True,
        timeout=900,
    ),
    _ValidatorSpec(
        "python.pytest_regression",
        "Regression pytest",
        "code_regression_tests",
        "fixed_local_process",
        ("code_worktree", "code_patch_result"),
        ("code_workspace",),
        ("python", "pytest"),
        safety=True,
        approval=True,
        temp_writes=True,
        timeout=900,
    ),
    _ValidatorSpec(
        "frontend.typecheck",
        "Frontend typecheck",
        "frontend_typecheck",
        "fixed_local_process",
        ("code_worktree", "code_patch_result"),
        ("code_workspace",),
        ("npm",),
        safety=True,
        approval=True,
        temp_writes=True,
        timeout=600,
    ),
    _ValidatorSpec(
        "frontend.lint",
        "Frontend lint",
        "frontend_lint",
        "fixed_local_process",
        ("code_worktree", "code_patch_result"),
        ("code_workspace",),
        ("npm",),
        safety=True,
        approval=True,
        temp_writes=True,
        timeout=600,
    ),
    _ValidatorSpec(
        "frontend.tests",
        "Frontend tests",
        "frontend_tests",
        "fixed_local_process",
        ("code_worktree", "code_patch_result"),
        ("code_workspace",),
        ("npm",),
        safety=True,
        approval=True,
        temp_writes=True,
        timeout=900,
    ),
    _ValidatorSpec(
        "frontend.build",
        "Frontend production build",
        "frontend_build",
        "fixed_local_process",
        ("code_worktree", "code_patch_result"),
        ("code_workspace",),
        ("npm",),
        safety=True,
        approval=True,
        temp_writes=True,
        timeout=900,
    ),
    _ValidatorSpec(
        "media.subject_visibility",
        "Frame-level subject visibility",
        "subject_visibility",
        "unavailable_optional_provider",
        ("generated_output", "recovered_output"),
        ("mp4", "media"),
        provider_ids=("opencv",),
        rights=True,
        safety=True,
        limitations=(
            "Frame-level CV validation is unavailable when the optional provider is absent.",
        ),
    ),
    _ValidatorSpec(
        "checkpoint.restore_validation",
        "Checkpoint restore validation",
        "checkpoint_integrity_read_only",
        "future",
        ("checkpoint",),
        ("checkpoint",),
        limitations=("Checkpoint restore remains owned by a future recovery manager.",),
    ),
)


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _tool_fingerprint(executable: str | None) -> tuple[str, str]:
    if not executable:
        return "unavailable", _EMPTY_DIGEST
    path = Path(executable)
    try:
        stat = path.stat()
    except OSError:
        return path.name, _digest({"path_name": path.name, "available": True})
    version = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}"
    return version, _digest(
        {
            "path_name": path.name,
            "size": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
        }
    )


def _availability_for_spec(
    spec: _ValidatorSpec,
    *,
    ffprobe_binary: str,
    ffmpeg_binary: str,
) -> tuple[BobaValidatorAvailabilityStatusV1, BobaValidatorHealthStatusV1, str]:
    if spec.implementation_type == "future":
        return "future", "unavailable", "The validator is explicitly future-gated."
    if spec.implementation_type == "unavailable_optional_provider":
        providers = {
            "opencv": _module_available("cv2"),
        }
        available = all(providers.get(item, False) for item in spec.provider_ids)
        if available:
            return (
                "degraded",
                "unverified",
                "The optional provider exists, but no fixed V1 frame adapter is registered.",
            )
        return (
            "unavailable",
            "unavailable",
            "The optional local provider is unavailable; no installation was attempted.",
        )
    if "ffprobe" in spec.tool_ids and shutil.which(ffprobe_binary) is None:
        return "unavailable", "unavailable", "Configured FFprobe is unavailable."
    if "ffmpeg" in spec.tool_ids and shutil.which(ffmpeg_binary) is None:
        return "unavailable", "unavailable", "Configured FFmpeg is unavailable."
    if spec.validator_id in _PROCESS_MODULES:
        module_name = _PROCESS_MODULES[spec.validator_id]
        if not _module_available(module_name):
            return (
                "unavailable",
                "unavailable",
                f"Python module {module_name!r} is unavailable; no installation was attempted.",
            )
    if spec.validator_id in _FRONTEND_SCRIPTS and shutil.which("npm") is None:
        return "unavailable", "unavailable", "npm is unavailable; no installation was attempted."
    return "available", "healthy", "The fixed local validator adapter is available."


def build_fixed_validator_adapter_registry() -> dict[str, str]:
    """Return fixed adapter IDs; no request or filesystem discovery is involved."""

    registry = {
        spec.validator_id: f"validator_adapter.{spec.validator_id}.v1"
        for spec in _FIXED_VALIDATOR_SPECS
    }
    if len(registry) != len(_FIXED_VALIDATOR_SPECS):
        raise ValidationError("Duplicate fixed validator IDs are unavailable.")
    adapter_ids = list(registry.values())
    if len(adapter_ids) != len(set(adapter_ids)):
        raise ValidationError("Duplicate fixed validator adapter IDs are unavailable.")
    return dict(sorted(registry.items()))


def build_fixed_validator_registry(
    *,
    ffprobe_binary: str = "ffprobe",
    ffmpeg_binary: str = "ffmpeg",
    descriptors: Sequence[BobaValidatorDescriptorV1] | None = None,
) -> tuple[BobaValidatorRegistrySnapshotV1, list[BobaValidatorDescriptorV1]]:
    """Build the deterministic, source-declared Validator Runner registry."""

    adapters = build_fixed_validator_adapter_registry()
    built: list[BobaValidatorDescriptorV1] = []
    if descriptors is not None:
        built = list(descriptors)
    else:
        for spec in _FIXED_VALIDATOR_SPECS:
            availability, health, reason = _availability_for_spec(
                spec,
                ffprobe_binary=ffprobe_binary,
                ffmpeg_binary=ffmpeg_binary,
            )
            built.append(
                BobaValidatorDescriptorV1(
                    validator_id=spec.validator_id,
                    display_name=spec.display_name,
                    validator_version="1",
                    category=spec.category,
                    implementation_type=spec.implementation_type,
                    adapter_id=adapters[spec.validator_id],
                    supported_target_types=list(spec.target_types),
                    supported_artifact_types=list(spec.artifact_types),
                    input_schema_ids=["boba.validation.input_binding:1"],
                    output_schema_id="boba.validation.result:1",
                    required_tool_ids=list(spec.tool_ids),
                    required_provider_ids=list(spec.provider_ids),
                    availability_status=availability,
                    availability_reason=reason,
                    read_only=True,
                    runner_owned_temp_writes=spec.temp_writes,
                    protected_state_mutation_allowed=False,
                    rights_gate_required=spec.rights,
                    safety_gate_required=spec.safety,
                    target_approval_required=spec.approval,
                    supported_platforms=["windows", "linux", "darwin"],
                    default_timeout_seconds=spec.timeout,
                    maximum_timeout_seconds=spec.maximum_timeout,
                    default_maximum_attempts=1,
                    deterministic=spec.deterministic,
                    idempotency_supported=True,
                    health_status=health,
                    warnings=[] if availability == "available" else [reason],
                    limitations=[
                        *spec.limitations,
                        "The adapter accepts no request-supplied command or callable.",
                    ],
                )
            )
    validator_ids = [item.validator_id for item in built]
    adapter_ids = [item.adapter_id for item in built]
    if len(validator_ids) != len(set(validator_ids)):
        raise ValidationError("Duplicate Validator Runner validator IDs are unavailable.")
    if len(adapter_ids) != len(set(adapter_ids)):
        raise ValidationError("Duplicate Validator Runner adapter IDs are unavailable.")
    ordered = sorted(built, key=lambda item: item.validator_id)
    digest = _digest(
        [
            {
                key: value
                for key, value in item.model_dump(mode="json").items()
                if key not in {"availability_reason", "warnings"}
            }
            for item in ordered
        ]
    )
    snapshot = BobaValidatorRegistrySnapshotV1(
        registry_snapshot_id=f"validator_registry_{digest[:24]}",
        registry_version="1",
        created_at=_DEFAULT_REGISTRY_CREATED_AT,
        validator_ids=[item.validator_id for item in ordered],
        validator_versions={
            item.validator_id: item.validator_version for item in ordered
        },
        available_validator_ids=[
            item.validator_id
            for item in ordered
            if item.availability_status == "available"
        ],
        degraded_validator_ids=[
            item.validator_id
            for item in ordered
            if item.availability_status == "degraded"
        ],
        unavailable_validator_ids=[
            item.validator_id
            for item in ordered
            if item.availability_status in {"unavailable", "blocked", "unknown"}
        ],
        future_validator_ids=[
            item.validator_id
            for item in ordered
            if item.availability_status == "future"
        ],
        registry_sha256=digest,
        immutable=True,
        limitations=[
            "Registry availability reflects local tools and fixed providers only.",
            "No tool was installed and no network service was queried.",
        ],
    )
    return snapshot, ordered


def calculate_validation_plan_digest(
    *,
    project_id: str,
    source_id: str,
    target_type: str,
    target_id: str,
    target_digest: str,
    project_snapshot_digest: str,
    registry_snapshot_id: str,
    checks: Sequence[Mapping[str, Any] | BobaValidationPlanCheckV1],
    input_bindings: Sequence[Mapping[str, Any] | BobaValidationInputBindingV1],
    acceptance_criteria: Sequence[str],
    rejection_criteria: Sequence[str],
    execution_policy_id: str,
    resource_budget_id: str,
) -> str:
    check_payloads = [
        item.model_dump(mode="json")
        if isinstance(item, BobaValidationPlanCheckV1)
        else dict(item)
        for item in checks
    ]
    binding_payloads = [
        item.model_dump(mode="json")
        if isinstance(item, BobaValidationInputBindingV1)
        else dict(item)
        for item in input_bindings
    ]
    for payload in check_payloads:
        for key in ("plan_check_id", "validation_plan_id", "warnings"):
            payload.pop(key, None)
    for payload in binding_payloads:
        for key in ("input_binding_id", "validation_plan_id", "exact_local_target"):
            payload.pop(key, None)
    return _digest(
        {
            "project_id": project_id,
            "source_id": source_id,
            "target_type": target_type,
            "target_id": target_id,
            "target_digest": target_digest,
            "project_snapshot_digest": project_snapshot_digest,
            "registry_snapshot_id": registry_snapshot_id,
            "checks": check_payloads,
            "input_bindings": binding_payloads,
            "acceptance_criteria": list(acceptance_criteria),
            "rejection_criteria": list(rejection_criteria),
            "execution_policy_id": execution_policy_id,
            "resource_budget_id": resource_budget_id,
        }
    )


def calculate_validation_idempotency_key(
    *,
    project_id: str,
    plan_digest: str,
    registry_digest: str,
    validator_versions: Mapping[str, str],
    target_digest: str,
    project_snapshot_digest: str,
    environment_digest: str,
    execution_policy_digest: str,
    approval_digest: str = "",
    safety_decision_digest: str = "",
) -> str:
    return _stable_id(
        "validation_idempotency",
        project_id,
        plan_digest,
        registry_digest,
        dict(sorted(validator_versions.items())),
        target_digest,
        project_snapshot_digest,
        environment_digest,
        execution_policy_digest,
        approval_digest,
        safety_decision_digest,
    )


def validate_validator_plan_dependencies(
    checks: Sequence[BobaValidationPlanCheckV1],
) -> list[str]:
    by_id: dict[str, BobaValidationPlanCheckV1] = {}
    for check in checks:
        if check.plan_check_id in by_id:
            raise ValidationError("Duplicate validation plan checks are unavailable.")
        by_id[check.plan_check_id] = check
    for check in checks:
        unknown = sorted(set(check.dependency_check_ids) - set(by_id))
        if unknown:
            raise ValidationError(
                "Validation check references an unknown dependency.",
                details={"plan_check_id": check.plan_check_id, "dependencies": unknown},
            )
        if check.plan_check_id in check.dependency_check_ids:
            raise ValidationError("Validation checks cannot depend on themselves.")
    incoming = dict.fromkeys(by_id, 0)
    successors: dict[str, list[str]] = {check_id: [] for check_id in by_id}
    for check in checks:
        for dependency in check.dependency_check_ids:
            incoming[check.plan_check_id] += 1
            successors[dependency].append(check.plan_check_id)
    queue = sorted(check_id for check_id, count in incoming.items() if count == 0)
    ordered: list[str] = []
    while queue:
        check_id = queue.pop(0)
        ordered.append(check_id)
        for successor in sorted(successors[check_id]):
            incoming[successor] -= 1
            if incoming[successor] == 0:
                queue.append(successor)
                queue.sort(
                    key=lambda item: (
                        by_id[item].order,
                        by_id[item].validator_id,
                        item,
                    )
                )
    if len(ordered) != len(checks):
        raise ValidationError("Validation plan check dependencies contain a cycle.")
    return ordered


def build_validation_execution_policy(
    *,
    policy_mode: Literal["artifact_only", "media_inspection", "isolated_code"],
    descriptors: Sequence[BobaValidatorDescriptorV1],
    allowed_working_roots: Sequence[str],
    maximum_capture_bytes: int = _DEFAULT_CAPTURE_BYTES,
) -> BobaValidationExecutionPolicyV1:
    allowed_types: dict[
        str,
        list[BobaValidatorImplementationTypeV1],
    ] = {
        "artifact_only": ["internal_python"],
        "media_inspection": [
            "internal_python",
            "fixed_media_probe",
            "fixed_media_decode",
        ],
        "isolated_code": ["internal_python", "fixed_local_process"],
    }
    executable_ids = {
        "artifact_only": [],
        "media_inspection": ["ffprobe", "ffmpeg"],
        "isolated_code": ["python", "npm"],
    }[policy_mode]
    target_types = sorted(
        {
            target
            for descriptor in descriptors
            for target in descriptor.supported_target_types
        }
    )
    payload = {
        "policy_version": "1",
        "policy_mode": policy_mode,
        "allowed_implementation_types": allowed_types[policy_mode],
        "allowed_adapter_ids": sorted(item.adapter_id for item in descriptors),
        "allowed_executable_ids": executable_ids,
        "allowed_working_roots": sorted(set(allowed_working_roots)),
        "allowed_target_types": target_types,
        "shell_allowed": False,
        "pipes_allowed": False,
        "redirects_allowed": False,
        "command_chaining_allowed": False,
        "network_allowed": False,
        "package_installation_allowed": False,
        "external_service_allowed": False,
        "source_media_modification_allowed": False,
        "accepted_output_modification_allowed": False,
        "tracked_source_modification_allowed": False,
        "runner_owned_temp_writes_allowed": True,
        "owned_child_termination_allowed": True,
        "unrelated_process_termination_allowed": False,
        "maximum_capture_bytes": min(
            _DEFAULT_CAPTURE_BYTES,
            max(1_024, maximum_capture_bytes),
        ),
    }
    digest = _digest(payload)
    return BobaValidationExecutionPolicyV1(
        execution_policy_id=f"validation_policy_{digest[:24]}",
        policy_digest=digest,
        limitations=[
            "The policy grants no network, package-install, shell, or protected-state mutation.",
            "Code checks require an approved isolated workspace.",
        ],
        **{key: value for key, value in payload.items() if key != "policy_mode"},
    )


def build_validation_resource_budget(
    validation_plan_id: str,
    *,
    overrides: Mapping[str, int] | None = None,
) -> BobaValidationResourceBudgetV1:
    defaults = {
        "maximum_check_count": 64,
        "maximum_parallel_checks": 2,
        "maximum_total_duration_seconds": 1_800,
        "maximum_single_check_duration_seconds": 900,
        "maximum_total_attempts": 128,
        "maximum_identical_retries": 1,
        "maximum_capture_bytes_per_stream": _DEFAULT_CAPTURE_BYTES,
        "maximum_temp_storage_bytes": 536_870_912,
        "maximum_media_sample_seconds": 30,
        "maximum_sampled_frames": 12,
        "maximum_cpu_processes": 2,
    }
    supplied = dict(overrides or {})
    unknown = sorted(set(supplied) - set(defaults))
    if unknown:
        raise ValidationError(
            "Unknown validation resource-budget fields are unavailable.",
            details={"fields": unknown},
        )
    values: dict[str, int] = {}
    for key, default in defaults.items():
        requested = int(supplied.get(key, default))
        if requested <= 0 or requested > default:
            raise ValidationError(
                "Validation resource budgets may only become stricter.",
                details={"field": key, "maximum": default},
            )
        values[key] = requested
    digest = _digest({"validation_plan_id": validation_plan_id, **values})
    return BobaValidationResourceBudgetV1(
        resource_budget_id=f"validation_budget_{digest[:24]}",
        validation_plan_id=validation_plan_id,
        **values,
    )


def capture_validation_environment_snapshot(
    *,
    project_id: str,
    project_snapshot_digest: str,
    workspace_mode: str,
    workspace_digest: str,
    runner_owned_temp_root: str,
    ffprobe_binary: str = "ffprobe",
    ffmpeg_binary: str = "ffmpeg",
) -> BobaValidationEnvironmentSnapshotV1:
    ffprobe = shutil.which(ffprobe_binary)
    ffmpeg = shutil.which(ffmpeg_binary)
    npm = shutil.which("npm")
    tool_paths = {
        "python": sys.executable,
        "ffprobe": ffprobe,
        "ffmpeg": ffmpeg,
        "npm": npm,
    }
    tool_versions: dict[str, str] = {}
    tool_digests: dict[str, str] = {}
    for tool_id, executable in tool_paths.items():
        version, digest = _tool_fingerprint(executable)
        tool_versions[tool_id] = version
        tool_digests[tool_id] = digest
    providers = {
        "opencv": "available" if _module_available("cv2") else "unavailable",
        "faster_whisper": (
            "available" if _module_available("faster_whisper") else "unavailable"
        ),
    }
    payload = {
        "project_id": project_id,
        "platform": platform.system().casefold() or "unknown",
        "architecture": platform.machine().casefold() or "unknown",
        "normalized_runtime_version": (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        "registered_tool_versions": tool_versions,
        "registered_tool_digests": tool_digests,
        "optional_provider_status": providers,
        "workspace_mode": workspace_mode,
        "workspace_digest": workspace_digest,
        "project_snapshot_digest": project_snapshot_digest,
        "sanitized_environment_keys": sorted(
            key
            for key in os.environ
            if key.upper() in {"LANG", "LC_ALL", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}
            and not _SECRET_KEY.search(key)
        ),
        "network_required": False,
        "network_requested": False,
        "runner_owned_temp_root": runner_owned_temp_root,
    }
    environment_digest = _digest(payload)
    return BobaValidationEnvironmentSnapshotV1(
        environment_snapshot_id=f"validation_environment_{environment_digest[:24]}",
        environment_digest=environment_digest,
        warnings=[
            item
            for item in (
                "FFprobe is unavailable." if ffprobe is None else "",
                "FFmpeg is unavailable." if ffmpeg is None else "",
                "npm is unavailable." if npm is None else "",
            )
            if item
        ],
        limitations=[
            "Environment values and secrets are not persisted.",
            "Binary fingerprints use local file metadata without executing version commands.",
        ],
        **payload,
    )


@dataclass(slots=True)
class _AdapterOutcome:
    status: BobaValidationCheckStatusV1
    summary: str
    assertion_results: dict[str, bool | None]
    measured_values: dict[str, Any]
    expected_values: dict[str, Any]
    failed_assertions: list[str]
    unavailable_assertions: list[str]
    source_type: BobaValidationEvidenceSourceTypeV1
    confidence: float
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    exit_code: int | None = None
    owned_child_terminated: bool = False
    warnings: list[str] | None = None
    limitations: list[str] | None = None


FixedAdapter = Callable[
    [
        BobaValidationPlanCheckV1,
        Sequence[BobaValidationInputBindingV1],
        Path,
        BobaValidationResourceBudgetV1,
        str,
    ],
    _AdapterOutcome,
]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValidationError(
            "The exact validation input is missing.",
            details={"name": path.name},
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "The exact validation input is not readable JSON.",
            details={"name": path.name},
        ) from exc


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _float_value(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _int_value(value: Any, default: int | None = None) -> int | None:
    try:
        return int(float(value)) if value is not None else default
    except (TypeError, ValueError):
        return default


def _path_is_within(path: Path, roots: Sequence[Path]) -> bool:
    resolved = path.resolve(strict=False)
    return any(
        resolved == root.resolve(strict=False)
        or root.resolve(strict=False) in resolved.parents
        for root in roots
    )


def _protected_tree_digest(root: Path) -> str:
    included_roots = (
        root / "src",
        root / "tests",
        root / "tools",
        root / "frontend" / "src",
    )
    included_files = (
        root / "pyproject.toml",
        root / "package.json",
        root / "frontend" / "package.json",
        root / "frontend" / "package-lock.json",
    )
    entries: list[tuple[str, str]] = []
    for included_root in included_roots:
        if not included_root.is_dir():
            continue
        for path in sorted(item for item in included_root.rglob("*") if item.is_file()):
            if any(
                part in {
                    ".git",
                    ".mypy_cache",
                    ".next",
                    ".pytest_cache",
                    ".ruff_cache",
                    "__pycache__",
                    "node_modules",
                }
                for part in path.parts
            ):
                continue
            entries.append((path.relative_to(root).as_posix(), _sha256_file(path)))
    for path in included_files:
        if path.is_file():
            entries.append((path.relative_to(root).as_posix(), _sha256_file(path)))
    return _digest(entries)


def _bounded_file_tail(handle: Any, maximum: int) -> tuple[str, bool]:
    handle.flush()
    handle.seek(0, 2)
    size = int(handle.tell())
    offset = max(0, size - maximum)
    handle.seek(offset)
    raw = handle.read(maximum)
    if offset and b"\n" in raw:
        raw = raw.split(b"\n", 1)[1]
    return _bounded_text(raw.decode("utf-8", "replace"), maximum=8_192), size > maximum


def _sanitized_process_environment(temp_root: Path) -> dict[str, str]:
    allowed = {"LANG", "LC_ALL", "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR"}
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed and not _SECRET_KEY.search(key)
    }
    environment.update(
        {
            "CI": "1",
            "HOME": str(temp_root),
            "NO_PROXY": "",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
            "http_proxy": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
        }
    )
    return environment


def _result_digest_payload(
    *,
    validator_id: str,
    status: BobaValidationCheckStatusV1,
    assertions: Mapping[str, bool | None],
    measured: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> str:
    return _digest(
        {
            "validator_id": validator_id,
            "status": status,
            "assertions": _json_safe(dict(assertions)),
            "measured": _json_safe(dict(measured)),
            "expected": _json_safe(dict(expected)),
        }
    )


def _status_event_type(status: BobaValidationCheckStatusV1) -> BobaValidationEventTypeV1:
    return cast(
        BobaValidationEventTypeV1,
        {
            "passed": "check_passed",
            "failed": "check_failed",
            "unavailable": "check_unavailable",
            "timed_out": "check_timed_out",
            "cancelled": "check_cancelled",
        }.get(status, "check_failed"),
    )


def _status_severity(
    status: BobaValidationCheckStatusV1,
) -> Literal["info", "warning", "error", "critical", "unknown"]:
    if status == "passed":
        return "info"
    if status in {"unavailable", "blocked", "cancelled", "dependency_blocked"}:
        return "warning"
    return "error"


class BobaValidatorRunnerV1:
    """Execute source-declared local validators and persist immutable evidence."""

    def __init__(
        self,
        store: BobaMemoryStore,
        *,
        repository_root: str | Path,
        storage_root: str | Path,
        ffprobe_binary: str = "ffprobe",
        ffmpeg_binary: str = "ffmpeg",
        lease_owner: str = "boba_validator_runner_v1",
        fixed_adapter_overrides: Mapping[str, FixedAdapter] | None = None,
        additional_allowed_input_roots: Sequence[str | Path] = (),
    ) -> None:
        self.store = store
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.storage_root = Path(storage_root).expanduser().resolve()
        self.ffprobe_binary = ffprobe_binary
        self.ffmpeg_binary = ffmpeg_binary
        self.lease_owner = _bounded_text(lease_owner, maximum=180)
        self.runner_workspace_root = (
            self.store.root / "validator_runner" / "workspaces"
        ).resolve()
        self.allowed_input_roots = tuple(
            dict.fromkeys(
                [
                    self.storage_root,
                    self.store.root.resolve(),
                    self.runner_workspace_root,
                    *(
                        Path(item).expanduser().resolve()
                        for item in additional_allowed_input_roots
                    ),
                ]
            )
        )
        known = set(build_fixed_validator_adapter_registry())
        supplied = dict(fixed_adapter_overrides or {})
        unknown = sorted(set(supplied) - known)
        if unknown:
            raise ValidationError(
                "Unknown Validator Runner adapter overrides are unavailable.",
                details={"validator_ids": unknown},
            )
        self.fixed_adapter_overrides = supplied

    def build_registry(
        self,
        project_id: str,
        *,
        source_id: str,
    ) -> BobaValidatorRegistrySnapshotV1:
        runner = self._runner(project_id, source_id=source_id)
        snapshot, descriptors = build_fixed_validator_registry(
            ffprobe_binary=self.ffprobe_binary,
            ffmpeg_binary=self.ffmpeg_binary,
        )
        existing = next(
            (
                item
                for item in runner.registry_snapshots
                if item.registry_snapshot_id == snapshot.registry_snapshot_id
            ),
            None,
        )
        if existing is not None:
            if existing.registry_sha256 != snapshot.registry_sha256:
                raise ValidationError(
                    "The immutable Validator Runner registry snapshot conflicts."
                )
            return existing
        runner.registry_snapshots.append(snapshot)
        known_descriptors = {
            (item.validator_id, item.validator_version)
            for item in runner.validator_descriptors
        }
        runner.validator_descriptors.extend(
            item
            for item in descriptors
            if (item.validator_id, item.validator_version) not in known_descriptors
        )
        runner.signal_usage.validator_registry_used = True
        self._refresh_summary(runner)
        self.store.save_boba_validator_runner(runner)
        return snapshot

    def inspect_registry(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        runner = self._runner(project_id, source_id=source_id)
        if not runner.registry_snapshots:
            self.build_registry(project_id, source_id=runner.source_id)
            runner = self._runner(project_id)
        snapshot = runner.registry_snapshots[-1]
        descriptors = [
            item
            for item in runner.validator_descriptors
            if item.validator_id in snapshot.validator_ids
            and snapshot.validator_versions.get(item.validator_id)
            == item.validator_version
        ]
        return {
            "schema_version": "boba_validator_registry_inspection_v1",
            "project_id": project_id,
            "registry_snapshot": snapshot.model_dump(mode="json"),
            "validators": [
                item.model_dump(mode="json")
                for item in sorted(descriptors, key=lambda value: value.validator_id)
            ],
            "fixed_registry": True,
            "dynamic_discovery_used": False,
            "network_used": False,
        }

    def inspect_availability(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        inspected = self.inspect_registry(project_id, source_id=source_id)
        validators = [
            _mapping(item) for item in _sequence(inspected.get("validators"))
        ]
        grouped: dict[str, list[dict[str, Any]]] = {
            "available": [],
            "degraded": [],
            "unavailable": [],
            "future": [],
            "blocked": [],
            "unknown": [],
        }
        for descriptor in validators:
            status = str(descriptor.get("availability_status") or "unknown")
            grouped.setdefault(status, []).append(descriptor)
        return {
            "schema_version": "boba_validator_availability_v1",
            "project_id": project_id,
            "registry_snapshot_id": _mapping(
                inspected.get("registry_snapshot")
            ).get("registry_snapshot_id"),
            "availability": grouped,
            "installation_attempted": False,
            "network_used": False,
            "warnings": [
                (
                    "Unavailable and future validators remain explicit and cannot "
                    "produce passing evidence."
                )
            ],
        }

    def create_validation_plan(
        self,
        project_id: str,
        *,
        source_id: str,
        target_type: BobaValidationTargetTypeV1,
        target_id: str,
        checks: Sequence[Mapping[str, Any]],
        input_bindings: Sequence[Mapping[str, Any]],
        validation_objective: str,
        acceptance_criteria: Sequence[str],
        rejection_criteria: Sequence[str],
        plan_source_module: str,
        plan_source_record_id: str = "",
        target_digest: str = "",
        project_snapshot_digest: str = "",
        workflow_run_id: str = "",
        stage_instance_id: str = "",
        autopilot_run_id: str = "",
        repair_plan_id: str = "",
        code_surgeon_run_id: str = "",
        tool_recovery_run_id: str = "",
        output_quality_review_id: str = "",
        workflow_revision: int = 0,
        approval_record_id: str = "",
        safety_decision_id: str = "",
        policy_mode: Literal[
            "artifact_only",
            "media_inspection",
            "isolated_code",
        ]
        | None = None,
        resource_budget_overrides: Mapping[str, int] | None = None,
        expires_in_seconds: int = 86_400,
        allow_unavailable_required: bool = False,
    ) -> BobaValidationPlanV1:
        if not checks:
            raise ValidationError("At least one fixed validation check is required.")
        if not input_bindings:
            raise ValidationError("At least one exact input binding is required.")
        runner = self._runner(project_id, source_id=source_id)
        snapshot = self.build_registry(project_id, source_id=source_id)
        runner = self._runner(project_id)
        descriptors = {
            item.validator_id: item
            for item in runner.validator_descriptors
            if snapshot.validator_versions.get(item.validator_id)
            == item.validator_version
        }
        requested_ids: list[str] = []
        for item in checks:
            validator_id = str(item.get("validator_id") or "").strip()
            if validator_id not in descriptors:
                raise ValidationError(
                    "Validation plan requested an unknown fixed validator.",
                    details={"validator_id": validator_id},
                )
            requested_ids.append(validator_id)
        selected = [descriptors[item] for item in requested_ids]
        if policy_mode is None:
            implementation_types = {
                item.implementation_type for item in selected
            }
            if "fixed_local_process" in implementation_types:
                if implementation_types & {
                    "fixed_media_probe",
                    "fixed_media_decode",
                }:
                    raise ValidationError(
                        "V1 does not mix isolated code and media process validators "
                        "in one validation plan."
                    )
                policy_mode = "isolated_code"
            elif implementation_types & {
                "fixed_media_probe",
                "fixed_media_decode",
            }:
                policy_mode = "media_inspection"
            else:
                policy_mode = "artifact_only"
        policy = build_validation_execution_policy(
            policy_mode=policy_mode,
            descriptors=selected,
            allowed_working_roots=(
                ["isolated_runner_workspace"]
                if policy_mode == "isolated_code"
                else ["configured_storage_root", "runner_owned_workspace"]
            ),
        )
        plan_seed = _digest(
            {
                "project_id": project_id,
                "source_id": source_id,
                "target_type": target_type,
                "target_id": target_id,
                "checks": [_json_safe(dict(item)) for item in checks],
                "inputs": [
                    {
                        key: _json_safe(value)
                        for key, value in dict(item).items()
                        if key != "exact_local_target"
                    }
                    for item in input_bindings
                ],
                "registry_snapshot_id": snapshot.registry_snapshot_id,
            }
        )
        validation_plan_id = f"validation_plan_{plan_seed[:24]}"
        bindings = self._build_input_bindings(
            validation_plan_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            stage_instance_id=stage_instance_id,
            supplied=input_bindings,
        )
        checks_built = self._build_plan_checks(
            validation_plan_id,
            supplied=checks,
            descriptors=descriptors,
            bindings=bindings,
            allow_unavailable_required=allow_unavailable_required,
        )
        ordered_check_ids = validate_validator_plan_dependencies(checks_built)
        budget = build_validation_resource_budget(
            validation_plan_id,
            overrides=resource_budget_overrides,
        )
        if len(checks_built) > budget.maximum_check_count:
            raise ValidationError("Validation plan exceeds the bounded check budget.")
        if not target_digest:
            target_digest = _digest(
                sorted(
                    (
                        item.artifact_type,
                        item.artifact_digest,
                        item.sanitized_storage_reference,
                    )
                    for item in bindings
                )
            )
        if not project_snapshot_digest:
            project_snapshot_digest = _digest(
                {
                    "project_id": project_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "target_digest": target_digest,
                    "workflow_revision": workflow_revision,
                }
            )
        plan_digest = calculate_validation_plan_digest(
            project_id=project_id,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            target_digest=target_digest,
            project_snapshot_digest=project_snapshot_digest,
            registry_snapshot_id=snapshot.registry_snapshot_id,
            checks=checks_built,
            input_bindings=bindings,
            acceptance_criteria=acceptance_criteria,
            rejection_criteria=rejection_criteria,
            execution_policy_id=policy.execution_policy_id,
            resource_budget_id=budget.resource_budget_id,
        )
        expires_at = (
            datetime.now(UTC)
            + timedelta(seconds=max(60, min(expires_in_seconds, 604_800)))
        ).isoformat()
        plan = BobaValidationPlanV1(
            validation_plan_id=validation_plan_id,
            project_id=project_id,
            source_id=source_id,
            workflow_run_id=workflow_run_id,
            stage_instance_id=stage_instance_id,
            autopilot_run_id=autopilot_run_id,
            repair_plan_id=repair_plan_id,
            code_surgeon_run_id=code_surgeon_run_id,
            tool_recovery_run_id=tool_recovery_run_id,
            output_quality_review_id=output_quality_review_id,
            plan_source_module=_bounded_text(
                plan_source_module,
                maximum=160,
            ),
            plan_source_record_id=_bounded_text(
                plan_source_record_id,
                maximum=180,
            ),
            target_type=target_type,
            target_id=_bounded_text(target_id, maximum=180),
            target_digest=target_digest,
            project_snapshot_digest=project_snapshot_digest,
            workflow_revision=workflow_revision,
            registry_snapshot_id=snapshot.registry_snapshot_id,
            check_ids=[item.plan_check_id for item in checks_built],
            ordered_check_ids=ordered_check_ids,
            required_check_ids=[
                item.plan_check_id for item in checks_built if item.required
            ],
            optional_check_ids=[
                item.plan_check_id for item in checks_built if not item.required
            ],
            validation_objective=_bounded_text(
                validation_objective,
                maximum=900,
            ),
            acceptance_criteria=_unique(
                acceptance_criteria,
                limit=64,
                maximum=500,
            ),
            rejection_criteria=_unique(
                rejection_criteria,
                limit=64,
                maximum=500,
            ),
            execution_policy_id=policy.execution_policy_id,
            resource_budget_id=budget.resource_budget_id,
            approval_record_id=_bounded_text(
                approval_record_id,
                maximum=180,
            ),
            safety_decision_id=_bounded_text(
                safety_decision_id,
                maximum=180,
            ),
            plan_digest=plan_digest,
            expires_at=expires_at,
            limitations=[
                "The plan can invoke only source-declared V1 validator adapters.",
                "The plan does not authorize workflow transitions or output acceptance.",
            ],
        )
        validation = self.validate_validation_plan(
            project_id,
            plan=plan,
            checks=checks_built,
            bindings=bindings,
            policy=policy,
            budget=budget,
            allow_unavailable_required=allow_unavailable_required,
        )
        if not validation["valid"]:
            raise ValidationError(
                "The Validator Runner plan is invalid.",
                details={
                    "errors": validation["errors"],
                    "warnings": validation["warnings"],
                },
            )
        existing = next(
            (
                item
                for item in runner.validation_plans
                if item.validation_plan_id == validation_plan_id
            ),
            None,
        )
        if existing is not None:
            if existing.plan_digest != plan.plan_digest:
                raise ValidationError(
                    "An immutable validation plan ID conflicts with existing content."
                )
            return existing
        runner.validation_plans.append(plan)
        runner.plan_checks.extend(checks_built)
        runner.input_bindings.extend(bindings)
        runner.execution_policies.append(policy)
        runner.resource_budgets.append(budget)
        runner.events.append(
            BobaValidationEventV1(
                event_id=_runtime_id("validation_event"),
                validation_run_id=f"planned:{validation_plan_id}",
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                sequence=1,
                event_type="plan_created",
                severity="info",
                technical_message=(
                    f"Immutable validation plan {validation_plan_id} was created "
                    f"against registry {snapshot.registry_snapshot_id}."
                ),
                easy_message=(
                    "BOBA prepared fixed local checks. No validator ran yet."
                ),
                confirmed_fact="The plan and exact input bindings were persisted.",
                progress_current=0,
                progress_total=len(checks_built),
                progress_percent=0.0,
            )
        )
        runner.events.append(
            BobaValidationEventV1(
                event_id=_runtime_id("validation_event"),
                validation_run_id=f"planned:{validation_plan_id}",
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                sequence=2,
                event_type="plan_validated",
                severity="info",
                technical_message="The fixed registry and dependency graph validated.",
                easy_message="The validation plan is ready to create a run.",
                confirmed_fact="No dynamic command, import, or callable was accepted.",
                progress_current=0,
                progress_total=len(checks_built),
                progress_percent=0.0,
            )
        )
        runner.signal_usage.validator_registry_used = True
        runner.signal_usage.safety_gate_used = bool(safety_decision_id)
        runner.signal_usage.target_module_approval_used = bool(approval_record_id)
        self._refresh_summary(runner)
        self.store.save_boba_validator_runner(runner)
        return plan

    def validate_validation_plan(
        self,
        project_id: str,
        *,
        validation_plan_id: str | None = None,
        plan: BobaValidationPlanV1 | None = None,
        checks: Sequence[BobaValidationPlanCheckV1] | None = None,
        bindings: Sequence[BobaValidationInputBindingV1] | None = None,
        policy: BobaValidationExecutionPolicyV1 | None = None,
        budget: BobaValidationResourceBudgetV1 | None = None,
        allow_unavailable_required: bool = False,
    ) -> dict[str, Any]:
        runner = self._runner(project_id)
        selected_plan = plan or self._plan(
            runner,
            str(validation_plan_id or ""),
        )
        selected_checks = list(checks or self._checks(runner, selected_plan))
        selected_bindings = list(bindings or self._bindings(runner, selected_plan))
        selected_policy = policy or self._policy(runner, selected_plan)
        selected_budget = budget or self._budget(runner, selected_plan)
        descriptor_map = self._descriptor_map(runner, selected_plan)
        errors: list[str] = []
        warnings: list[str] = []
        try:
            ordered = validate_validator_plan_dependencies(selected_checks)
        except ValidationError as exc:
            ordered = []
            errors.append(exc.message)
        if ordered and ordered != selected_plan.ordered_check_ids:
            errors.append("Persisted plan order does not match its dependency graph.")
        if len(selected_checks) > selected_budget.maximum_check_count:
            errors.append("Plan check count exceeds its immutable resource budget.")
        if selected_plan.target_type not in selected_policy.allowed_target_types:
            errors.append("The plan target type is outside its execution policy.")
        parsed_expiry = _parse_time(selected_plan.expires_at)
        if parsed_expiry is None:
            errors.append("The plan expiry timestamp is malformed.")
        elif parsed_expiry <= datetime.now(UTC):
            errors.append("The validation plan has expired.")
        binding_ids = {item.input_binding_id for item in selected_bindings}
        for check in selected_checks:
            descriptor = descriptor_map.get(check.validator_id)
            if descriptor is None:
                errors.append(f"Unknown validator: {check.validator_id}.")
                continue
            if descriptor.validator_version != check.validator_version:
                errors.append(
                    f"Validator version mismatch: {check.validator_id}."
                )
            if descriptor.adapter_id not in selected_policy.allowed_adapter_ids:
                errors.append(
                    f"Validator adapter is outside policy: {check.validator_id}."
                )
            if (
                descriptor.implementation_type
                not in selected_policy.allowed_implementation_types
            ):
                errors.append(
                    f"Validator implementation is outside policy: {check.validator_id}."
                )
            missing_bindings = sorted(set(check.input_binding_ids) - binding_ids)
            if missing_bindings:
                errors.append(
                    f"Check {check.plan_check_id} references unknown input bindings."
                )
            if descriptor.availability_status != "available":
                message = (
                    f"Validator {check.validator_id} is "
                    f"{descriptor.availability_status}: "
                    f"{descriptor.availability_reason}"
                )
                if check.required and not allow_unavailable_required:
                    errors.append(message)
                else:
                    warnings.append(message)
            if check.timeout_seconds > min(
                descriptor.maximum_timeout_seconds,
                selected_budget.maximum_single_check_duration_seconds,
            ):
                errors.append(
                    f"Check timeout exceeds policy: {check.plan_check_id}."
                )
            if check.maximum_attempts > descriptor.default_maximum_attempts + 1:
                errors.append(
                    f"Check attempts exceed fixed bounds: {check.plan_check_id}."
                )
            if descriptor.rights_gate_required:
                relevant = [
                    item
                    for item in selected_bindings
                    if item.input_binding_id in check.input_binding_ids
                ]
                if not relevant or any(
                    item.rights_status.casefold() not in _RIGHTS_ALLOWED
                    for item in relevant
                ):
                    errors.append(
                        f"Rights confirmation is missing for {check.validator_id}."
                    )
            if descriptor.safety_gate_required and not selected_plan.safety_decision_id:
                errors.append(
                    f"A safety decision is required for {check.validator_id}."
                )
            if (
                descriptor.target_approval_required
                and not selected_plan.approval_record_id
            ):
                errors.append(
                    f"Target approval is required for {check.validator_id}."
                )
        for binding in selected_bindings:
            if binding.project_id != project_id:
                errors.append("Cross-project validation input binding was rejected.")
            if binding.stale:
                errors.append(
                    f"Validation input {binding.input_binding_id} is stale."
                )
            if binding.malformed:
                errors.append(
                    f"Validation input {binding.input_binding_id} is malformed."
                )
            if binding.required and not binding.available:
                errors.append(
                    f"Required validation input {binding.input_binding_id} is unavailable."
                )
            try:
                self._resolve_binding_target(binding)
            except ValidationError as exc:
                errors.append(exc.message)
        recalculated = calculate_validation_plan_digest(
            project_id=selected_plan.project_id,
            source_id=selected_plan.source_id,
            target_type=selected_plan.target_type,
            target_id=selected_plan.target_id,
            target_digest=selected_plan.target_digest,
            project_snapshot_digest=selected_plan.project_snapshot_digest,
            registry_snapshot_id=selected_plan.registry_snapshot_id,
            checks=selected_checks,
            input_bindings=selected_bindings,
            acceptance_criteria=selected_plan.acceptance_criteria,
            rejection_criteria=selected_plan.rejection_criteria,
            execution_policy_id=selected_plan.execution_policy_id,
            resource_budget_id=selected_plan.resource_budget_id,
        )
        if recalculated != selected_plan.plan_digest:
            errors.append("Validation plan digest does not match its immutable inputs.")
        return {
            "schema_version": "boba_validation_plan_validation_v1",
            "project_id": project_id,
            "validation_plan_id": selected_plan.validation_plan_id,
            "valid": not errors,
            "errors": _unique(errors, limit=128, maximum=700),
            "warnings": _unique(warnings, limit=128, maximum=700),
            "ordered_check_ids": ordered,
            "arbitrary_command_accepted": False,
            "dynamic_import_accepted": False,
            "network_required": False,
        }

    def create_validation_run(
        self,
        project_id: str,
        validation_plan_id: str,
    ) -> BobaValidationRunV1:
        runner = self._runner(project_id)
        plan = self._plan(runner, validation_plan_id)
        validation = self.validate_validation_plan(
            project_id,
            plan=plan,
            allow_unavailable_required=True,
        )
        if not validation["valid"]:
            raise ValidationError(
                "A validation run cannot use an invalid or stale plan.",
                details={"errors": validation["errors"]},
            )
        checks = self._checks(runner, plan)
        descriptors = self._descriptor_map(runner, plan)
        policy = self._policy(runner, plan)
        budget = self._budget(runner, plan)
        bindings = self._bindings(runner, plan)
        code_plan = any(item.validator_id in _CODE_VALIDATORS for item in checks)
        workspace_mode = "isolated_code" if code_plan else "read_only_artifact"
        workspace_digest = (
            self._code_workspace_digest(bindings)
            if code_plan
            else self._actual_binding_set_digest(bindings)
        )
        environment = capture_validation_environment_snapshot(
            project_id=project_id,
            project_snapshot_digest=plan.project_snapshot_digest,
            workspace_mode=workspace_mode,
            workspace_digest=workspace_digest,
            runner_owned_temp_root="validator_runner/workspaces",
            ffprobe_binary=self.ffprobe_binary,
            ffmpeg_binary=self.ffmpeg_binary,
        )
        validator_versions = {
            check.validator_id: descriptors[check.validator_id].validator_version
            for check in checks
        }
        idempotency_key = calculate_validation_idempotency_key(
            project_id=project_id,
            plan_digest=plan.plan_digest,
            registry_digest=self._registry(runner, plan).registry_sha256,
            validator_versions=validator_versions,
            target_digest=plan.target_digest,
            project_snapshot_digest=plan.project_snapshot_digest,
            environment_digest=environment.environment_digest,
            execution_policy_digest=policy.policy_digest,
            approval_digest=(
                _digest(plan.approval_record_id)
                if plan.approval_record_id
                else _EMPTY_DIGEST
            ),
            safety_decision_digest=(
                _digest(plan.safety_decision_id)
                if plan.safety_decision_id
                else _EMPTY_DIGEST
            ),
        )
        matching = [
            item
            for item in runner.validation_runs
            if item.idempotency_key == idempotency_key
        ]
        if matching:
            existing = matching[-1]
            runner.signal_usage.idempotency_used = True
            if existing.run_status in _TERMINAL_RUN_STATUSES:
                runner.runner_summary.idempotent_reuse_count += 1
                self.store.save_boba_validator_runner(runner)
                return existing
            raise ValidationError(
                "An identical validation run is already active.",
                details={"validation_run_id": existing.validation_run_id},
            )
        if sum(
            item.run_status not in _TERMINAL_RUN_STATUSES
            for item in runner.validation_runs
        ) >= budget.maximum_parallel_checks:
            raise ValidationError(
                "The project validation concurrency budget is exhausted."
            )
        if not any(
            item.environment_snapshot_id == environment.environment_snapshot_id
            for item in runner.environment_snapshots
        ):
            runner.environment_snapshots.append(environment)
        validation_run_id = _runtime_id("validation_run")
        run = BobaValidationRunV1(
            validation_run_id=validation_run_id,
            validation_plan_id=validation_plan_id,
            project_id=project_id,
            workflow_run_id=plan.workflow_run_id,
            stage_instance_id=plan.stage_instance_id,
            target_type=plan.target_type,
            target_id=plan.target_id,
            target_digest=plan.target_digest,
            registry_snapshot_id=plan.registry_snapshot_id,
            environment_snapshot_id=environment.environment_snapshot_id,
            execution_policy_id=policy.execution_policy_id,
            resource_budget_id=budget.resource_budget_id,
            correlation_id=_runtime_id("validation_correlation"),
            run_status="ready",
            idempotency_key=idempotency_key,
            limitations=[
                "V1 runs checks sequentially within the bounded process budget.",
                "No suite result authorizes a workflow transition or output acceptance.",
            ],
        )
        runner.validation_runs.append(run)
        self._append_event(
            runner,
            run,
            event_type="run_created",
            severity="info",
            technical_message=(
                f"Validation run {validation_run_id} was created for immutable "
                f"plan {validation_plan_id}."
            ),
            easy_message="BOBA created the validation run. No check has started.",
            confirmed_fact="The environment and idempotency snapshot were persisted.",
            progress_current=0,
            progress_total=len(checks),
        )
        runner.signal_usage.idempotency_used = True
        self._refresh_summary(runner)
        self.store.save_boba_validator_runner(runner)
        return run

    def execute_validation_run(
        self,
        project_id: str,
        validation_run_id: str,
        *,
        confirm_stale_lease: bool = False,
    ) -> dict[str, Any]:
        runner = self._runner(project_id)
        run = self._run(runner, validation_run_id)
        if run.run_status in _TERMINAL_RUN_STATUSES:
            return self.inspect_validation_run(project_id, validation_run_id)
        if run.run_status not in {"ready", "created"}:
            raise ValidationError(
                "The validation run is not ready for exact execution.",
                details={"run_status": run.run_status},
            )
        plan = self._plan(runner, run.validation_plan_id)
        plan_validation = self.validate_validation_plan(
            project_id,
            plan=plan,
            allow_unavailable_required=True,
        )
        if not plan_validation["valid"]:
            run.run_status = "blocked"
            run.stop_reason = "The immutable validation plan is no longer valid."
            run.completed_at = now_iso()
            self._append_incident(
                runner,
                run,
                incident_type="invalid_plan",
                severity="high",
                title="Validation plan became invalid",
                summary="; ".join(plan_validation["errors"]),
                project_state_uncertain=True,
            )
            self._finalize_run(runner, run, plan)
            self.store.save_boba_validator_runner(runner)
            return self.inspect_validation_run(project_id, validation_run_id)
        environment = self._environment(runner, run)
        lease = self.store.acquire_boba_validation_lease(
            project_id,
            validation_run_id=validation_run_id,
            validation_plan_id=plan.validation_plan_id,
            target_id=plan.target_id,
            owner_id=self.lease_owner,
            environment_digest=environment.environment_digest,
            workspace_reference=(
                f"validator_runner/workspaces/{validation_run_id}"
            ),
            confirm_stale=confirm_stale_lease,
        )
        run.lease_id = lease.lease_id
        run.run_status = "running"
        run.started_at = now_iso()
        runner.signal_usage.execution_lease_used = True
        runner.signal_usage.runner_owned_temp_state_used = True
        workspace = self._run_workspace(validation_run_id)
        workspace.mkdir(parents=True, exist_ok=True)
        checks = self._checks(runner, plan)
        checks_by_id = {item.plan_check_id: item for item in checks}
        bindings = self._bindings(runner, plan)
        budget = self._budget(runner, plan)
        started = time.monotonic()
        total_attempts = 0
        self._append_event(
            runner,
            run,
            event_type="run_started",
            severity="info",
            technical_message=(
                f"Validation run {validation_run_id} acquired project lease "
                f"{lease.lease_id}."
            ),
            easy_message="BOBA started the fixed local validation checks.",
            confirmed_fact="Only runner-owned temporary state may be written.",
            progress_current=0,
            progress_total=len(checks),
        )
        self.store.save_boba_validator_runner(runner)
        terminal_by_plan_check: dict[str, BobaValidationCheckRunV1] = {}
        try:
            for index, plan_check_id in enumerate(plan.ordered_check_ids):
                runner = self._runner(project_id)
                run = self._run(runner, validation_run_id)
                if run.cancellation_requested:
                    run.run_status = "cancelled"
                    run.stop_reason = "Validation cancellation was requested."
                    break
                elapsed = time.monotonic() - started
                if elapsed >= budget.maximum_total_duration_seconds:
                    run.run_status = "timed_out"
                    run.stop_reason = "The total validation time budget expired."
                    break
                if total_attempts >= budget.maximum_total_attempts:
                    run.run_status = "incomplete"
                    run.stop_reason = "The total validation attempt budget expired."
                    break
                check = checks_by_id[plan_check_id]
                descriptor = self._descriptor_map(runner, plan)[check.validator_id]
                dependency_runs = [
                    terminal_by_plan_check.get(dependency_id)
                    for dependency_id in check.dependency_check_ids
                ]
                dependency_failed = [
                    item
                    for item in dependency_runs
                    if item is None or item.status != "passed"
                ]
                check_run = self._new_check_run(
                    run,
                    check,
                    descriptor,
                    environment,
                    bindings,
                    attempt_number=1,
                )
                runner.check_runs.append(check_run)
                run.active_check_run_id = check_run.check_run_id
                check_run.status = "running"
                check_run.started_at = now_iso()
                self._append_event(
                    runner,
                    run,
                    event_type="check_started",
                    severity="info",
                    check_run=check_run,
                    technical_message=(
                        f"Fixed adapter {descriptor.adapter_id} started "
                        f"{check.validator_id}."
                    ),
                    easy_message=f"Running {check.display_name}.",
                    confirmed_fact="No request-supplied command or callable was used.",
                    progress_current=index,
                    progress_total=len(checks),
                )
                self.store.save_boba_validator_runner(runner)
                total_attempts += 1
                before_digest = self._actual_binding_set_digest(
                    [
                        item
                        for item in bindings
                        if item.input_binding_id in check.input_binding_ids
                    ]
                )
                check_started = time.monotonic()
                if dependency_failed:
                    outcome = _AdapterOutcome(
                        status="dependency_blocked",
                        summary="A required validation dependency did not pass.",
                        assertion_results={"dependencies_passed": False},
                        measured_values={
                            "dependency_statuses": {
                                dependency_id: (
                                    terminal_by_plan_check[dependency_id].status
                                    if dependency_id in terminal_by_plan_check
                                    else "missing"
                                )
                                for dependency_id in check.dependency_check_ids
                            }
                        },
                        expected_values={"dependencies_passed": True},
                        failed_assertions=[],
                        unavailable_assertions=["dependencies_passed"],
                        source_type="internal_validator",
                        confidence=1.0,
                    )
                elif descriptor.availability_status != "available":
                    outcome = _AdapterOutcome(
                        status="unavailable",
                        summary=descriptor.availability_reason,
                        assertion_results={"validator_available": None},
                        measured_values={
                            "availability_status": descriptor.availability_status
                        },
                        expected_values={"availability_status": "available"},
                        failed_assertions=[],
                        unavailable_assertions=["validator_available"],
                        source_type="internal_validator",
                        confidence=1.0,
                        warnings=[descriptor.availability_reason],
                    )
                else:
                    try:
                        self._verify_binding_digests(
                            [
                                item
                                for item in bindings
                                if item.input_binding_id in check.input_binding_ids
                            ]
                        )
                        outcome = self._execute_adapter(
                            check,
                            descriptor,
                            bindings,
                            workspace,
                            budget,
                            f"{project_id}:{validation_run_id}:{check_run.check_run_id}",
                        )
                    except ValidationError as exc:
                        outcome = _AdapterOutcome(
                            status="blocked",
                            summary=exc.message,
                            assertion_results={"safe_execution_allowed": False},
                            measured_values={"error": sanitize_validator_export(exc.details)},
                            expected_values={"safe_execution_allowed": True},
                            failed_assertions=[],
                            unavailable_assertions=["safe_execution_allowed"],
                            source_type="internal_validator",
                            confidence=1.0,
                            warnings=[exc.message],
                        )
                    except Exception as exc:
                        outcome = _AdapterOutcome(
                            status="errored",
                            summary="The fixed validator adapter raised an unexpected error.",
                            assertion_results={"adapter_completed": False},
                            measured_values={
                                "error_type": type(exc).__name__,
                                "message": _bounded_text(exc, maximum=500),
                            },
                            expected_values={"adapter_completed": True},
                            failed_assertions=["adapter_completed"],
                            unavailable_assertions=[],
                            source_type="internal_validator",
                            confidence=0.0,
                            warnings=[
                                "The unexpected adapter error was retained as a failure."
                            ],
                        )
                after_digest = self._actual_binding_set_digest(
                    [
                        item
                        for item in bindings
                        if item.input_binding_id in check.input_binding_ids
                    ]
                )
                protected_unchanged = before_digest == after_digest
                if not protected_unchanged:
                    outcome = _AdapterOutcome(
                        status="errored",
                        summary=(
                            "The validator changed a protected input; the suite "
                            "was stopped as uncertain."
                        ),
                        assertion_results={"protected_state_unchanged": False},
                        measured_values={
                            "before_digest": before_digest,
                            "after_digest": after_digest,
                        },
                        expected_values={"protected_state_unchanged": True},
                        failed_assertions=["protected_state_unchanged"],
                        unavailable_assertions=[],
                        source_type=outcome.source_type,
                        confidence=1.0,
                        warnings=["Unexpected protected-state modification detected."],
                    )
                    run.project_state_uncertain = True
                duration = max(0.0, time.monotonic() - check_started)
                evidence, result = self._materialize_outcome(
                    run,
                    check,
                    check_run,
                    outcome,
                )
                check_run.status = outcome.status
                check_run.completed_at = now_iso()
                check_run.duration_seconds = round(min(duration, 3_600.0), 3)
                check_run.exit_code = outcome.exit_code
                check_run.result_id = result.result_id
                check_run.evidence_ids = [evidence.evidence_id]
                check_run.bounded_stdout = _bounded_text(
                    outcome.stdout,
                    maximum=8_192,
                )
                check_run.bounded_stderr = _bounded_text(
                    outcome.stderr,
                    maximum=8_192,
                )
                check_run.output_truncated = outcome.output_truncated
                check_run.owned_child_terminated = outcome.owned_child_terminated
                check_run.protected_state_unchanged = protected_unchanged
                check_run.failure_summary = (
                    "" if outcome.status == "passed" else outcome.summary
                )
                check_run.retryable = (
                    outcome.status
                    in {"failed", "errored", "timed_out", "unavailable"}
                    and check.maximum_attempts > 1
                )
                check_run.warnings = _unique(
                    outcome.warnings or [],
                    limit=32,
                    maximum=500,
                )
                check_run.limitations = _unique(
                    outcome.limitations or [],
                    limit=32,
                    maximum=500,
                )
                runner.evidence_records.append(evidence)
                runner.validation_results.append(result)
                terminal_by_plan_check[check.plan_check_id] = check_run
                run.active_check_run_id = ""
                run.completed_check_run_ids.append(check_run.check_run_id)
                if outcome.status in {"failed", "errored"}:
                    run.failed_check_run_ids.append(check_run.check_run_id)
                elif outcome.status in {"blocked", "dependency_blocked"}:
                    run.blocked_check_run_ids.append(check_run.check_run_id)
                elif outcome.status == "unavailable":
                    run.unavailable_check_run_ids.append(check_run.check_run_id)
                elif outcome.status == "timed_out":
                    run.timed_out_check_run_ids.append(check_run.check_run_id)
                elif outcome.status in {
                    "cancelled",
                    "skipped_not_required",
                    "superseded",
                }:
                    run.skipped_check_run_ids.append(check_run.check_run_id)
                if outcome.owned_child_terminated:
                    runner.signal_usage.owned_child_process_termination_used = True
                self._mark_signal_usage(runner, descriptor)
                self._append_event(
                    runner,
                    run,
                    event_type=_status_event_type(outcome.status),
                    severity=_status_severity(outcome.status),
                    check_run=check_run,
                    technical_message=outcome.summary,
                    easy_message=self._easy_check_message(check, outcome.status),
                    confirmed_fact=(
                        f"Result {result.result_id} and evidence "
                        f"{evidence.evidence_id} were persisted."
                    ),
                    progress_current=index + 1,
                    progress_total=len(checks),
                    evidence_reference_ids=[evidence.evidence_id],
                )
                if outcome.status != "passed":
                    self._append_incident_for_outcome(
                        runner,
                        run,
                        check,
                        check_run,
                        outcome,
                        evidence,
                    )
                self._refresh_summary(runner)
                self.store.save_boba_validator_runner(runner)
                if run.project_state_uncertain:
                    run.run_status = "failed"
                    run.stop_reason = "Protected state became uncertain."
                    break
                if (
                    check.stop_suite_on_failure
                    and outcome.status != "passed"
                ):
                    run.stop_reason = (
                        f"Check {check.plan_check_id} requested suite stop."
                    )
                    break
            runner = self._runner(project_id)
            run = self._run(runner, validation_run_id)
            if run.run_status == "running":
                run.run_status = "completed"
            run.completed_at = now_iso()
            self._finalize_run(runner, run, plan)
            self._refresh_summary(runner)
            self.store.save_boba_validator_runner(runner)
        except Exception as exc:
            runner = self._runner(project_id)
            run = self._run(runner, validation_run_id)
            if run.run_status not in _TERMINAL_RUN_STATUSES:
                run.run_status = "failed"
                run.completed_at = now_iso()
                run.stop_reason = (
                    "Validator Runner execution failed without a passing suite decision."
                )
                run.project_state_uncertain = True
                self._append_incident(
                    runner,
                    run,
                    incident_type="validator_crash",
                    severity="critical",
                    title="Validator Runner execution crashed",
                    summary=f"{type(exc).__name__}: {_bounded_text(exc, maximum=600)}",
                    project_state_uncertain=True,
                )
                self._finalize_run(runner, run, plan)
                self._refresh_summary(runner)
                self.store.save_boba_validator_runner(runner)
        finally:
            with suppress(ValidationError):
                self.store.release_boba_validation_lease(
                    project_id,
                    validation_run_id=validation_run_id,
                    owner_id=self.lease_owner,
                )
            self._cleanup_run_workspace(validation_run_id)
        return self.inspect_validation_run(project_id, validation_run_id)

    def cancel_validation_run(
        self,
        project_id: str,
        validation_run_id: str,
    ) -> BobaValidationRunV1:
        runner = self._runner(project_id)
        run = self._run(runner, validation_run_id)
        if run.run_status in _TERMINAL_RUN_STATUSES:
            return run
        run.cancellation_requested = True
        run.run_status = "cancelling"
        self._append_event(
            runner,
            run,
            event_type="run_cancel_requested",
            severity="warning",
            technical_message="Validation cancellation was requested.",
            easy_message="BOBA is stopping its own active validation process.",
            confirmed_fact="Unrelated processes were not targeted.",
        )
        terminated = False
        with _OWNED_PROCESS_LOCK:
            for process_key, process in list(_OWNED_PROCESSES.items()):
                if (
                    process_key.startswith(f"{project_id}:{validation_run_id}:")
                    and process.poll() is None
                ):
                        with suppress(OSError):
                            process.terminate()
                            terminated = True
        if terminated:
            runner.signal_usage.owned_child_process_termination_used = True
        self.store.save_boba_validator_runner(runner)
        return run

    def retry_validation_check(
        self,
        project_id: str,
        validation_run_id: str,
        plan_check_id: str,
    ) -> BobaValidationRunV1:
        runner = self._runner(project_id)
        original_run = self._run(runner, validation_run_id)
        original_plan = self._plan(runner, original_run.validation_plan_id)
        original_check = next(
            (
                item
                for item in self._checks(runner, original_plan)
                if item.plan_check_id == plan_check_id
            ),
            None,
        )
        if original_check is None:
            raise NotFoundError("The requested validation check was not found.")
        prior_attempts = [
            item
            for item in runner.check_runs
            if item.validation_run_id == validation_run_id
            and item.plan_check_id == plan_check_id
        ]
        if not prior_attempts:
            raise ValidationError("The validation check has not run yet.")
        latest = prior_attempts[-1]
        if latest.status == "passed":
            raise ValidationError("A passing validation check cannot be retried.")
        if len(prior_attempts) >= original_check.maximum_attempts:
            raise ValidationError("The fixed check retry budget is exhausted.")
        retry_plan = self.create_validation_plan(
            project_id,
            source_id=original_plan.source_id,
            target_type=original_plan.target_type,
            target_id=f"{original_plan.target_id}:retry:{plan_check_id}",
            checks=[
                {
                    "validator_id": original_check.validator_id,
                    "required": original_check.required,
                    "expected_values": original_check.expected_values,
                    "tolerance": original_check.tolerance,
                    "acceptance_criteria": original_check.acceptance_criteria,
                    "rejection_criteria": original_check.rejection_criteria,
                    "timeout_seconds": original_check.timeout_seconds,
                    "maximum_attempts": 1,
                    "input_binding_indexes": list(
                        range(len(original_check.input_binding_ids))
                    ),
                }
            ],
            input_bindings=[
                item.model_dump(mode="json")
                for item in self._bindings(runner, original_plan)
                if item.input_binding_id in original_check.input_binding_ids
            ],
            validation_objective=(
                f"Explicit bounded retry of {original_check.validator_id} from "
                f"run {validation_run_id}."
            ),
            acceptance_criteria=original_check.acceptance_criteria,
            rejection_criteria=original_check.rejection_criteria,
            plan_source_module="validator_runner",
            plan_source_record_id=validation_run_id,
            target_digest=original_plan.target_digest,
            project_snapshot_digest=original_plan.project_snapshot_digest,
            workflow_run_id=original_plan.workflow_run_id,
            stage_instance_id=original_plan.stage_instance_id,
            workflow_revision=original_plan.workflow_revision,
            approval_record_id=original_plan.approval_record_id,
            safety_decision_id=original_plan.safety_decision_id,
            allow_unavailable_required=True,
        )
        return self.create_validation_run(
            project_id,
            retry_plan.validation_plan_id,
        )

    def inspect_validation_run(
        self,
        project_id: str,
        validation_run_id: str,
    ) -> dict[str, Any]:
        runner = self._runner(project_id)
        run = self._run(runner, validation_run_id)
        check_runs = [
            item
            for item in runner.check_runs
            if item.validation_run_id == validation_run_id
        ]
        results = [
            item
            for item in runner.validation_results
            if item.validation_run_id == validation_run_id
        ]
        evidence = [
            item
            for item in runner.evidence_records
            if item.validation_run_id == validation_run_id
        ]
        decision = next(
            (
                item
                for item in runner.suite_decisions
                if item.validation_run_id == validation_run_id
            ),
            None,
        )
        return cast(
            dict[str, Any],
            sanitize_validator_export(
                {
                    "schema_version": "boba_validation_run_inspection_v1",
                "project_id": project_id,
                "run": run.model_dump(mode="json"),
                "check_runs": [
                    item.model_dump(mode="json") for item in check_runs
                ],
                "results": [item.model_dump(mode="json") for item in results],
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "suite_decision": (
                    decision.model_dump(mode="json") if decision else None
                ),
                "incidents": [
                    item.model_dump(mode="json")
                    for item in runner.incidents
                    if item.validation_run_id == validation_run_id
                ],
                "handoffs": [
                    item.model_dump(mode="json")
                    for item in runner.handoffs
                    if item.validation_run_id == validation_run_id
                ],
                "events": [
                    item.model_dump(mode="json")
                    for item in runner.events
                    if item.validation_run_id == validation_run_id
                ],
                }
            ),
        )

    def inspect_results(
        self,
        project_id: str,
        validation_run_id: str,
    ) -> dict[str, Any]:
        inspected = self.inspect_validation_run(project_id, validation_run_id)
        return {
            "schema_version": "boba_validation_results_v1",
            "project_id": project_id,
            "validation_run_id": validation_run_id,
            "results": inspected.get("results", []),
            "evidence": inspected.get("evidence", []),
            "suite_decision": inspected.get("suite_decision"),
            "warnings": [
                (
                    "Results are technical evidence only and do not authorize "
                    "workflow transition, output acceptance, upload, or publication."
                )
            ],
        }

    def inspect_events(
        self,
        project_id: str,
        validation_run_id: str,
    ) -> list[BobaValidationEventV1]:
        runner = self._runner(project_id)
        self._run(runner, validation_run_id)
        return sorted(
            (
                item
                for item in runner.events
                if item.validation_run_id == validation_run_id
            ),
            key=lambda item: item.sequence,
        )

    def export_validator_runner(self, project_id: str) -> dict[str, Any]:
        return self.store.export_boba_validator_runner(project_id)

    def reset_validator_runner(self, project_id: str) -> dict[str, Any]:
        return self.store.reset_boba_validator_runner(project_id)

    def _runner(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
    ) -> BobaValidatorRunnerSetV1:
        runner = self.store.load_boba_validator_runner(project_id)
        if runner is None:
            if not source_id:
                raise NotFoundError(
                    "The BOBA Validator Runner project record was not found."
                )
            return BobaValidatorRunnerSetV1(
                project_id=project_id,
                source_id=source_id,
                limitations=[
                    "V1 executes only fixed local validators.",
                    "Network, package installation, upload, publication, and "
                    "workflow mutation remain unavailable.",
                ],
            )
        if source_id and runner.source_id != source_id:
            raise ValidationError(
                "The Validator Runner source identity does not match the project."
            )
        return runner

    @staticmethod
    def _plan(
        runner: BobaValidatorRunnerSetV1,
        validation_plan_id: str,
    ) -> BobaValidationPlanV1:
        plan = next(
            (
                item
                for item in runner.validation_plans
                if item.validation_plan_id == validation_plan_id
            ),
            None,
        )
        if plan is None:
            raise NotFoundError("The validation plan was not found.")
        return plan

    @staticmethod
    def _run(
        runner: BobaValidatorRunnerSetV1,
        validation_run_id: str,
    ) -> BobaValidationRunV1:
        run = next(
            (
                item
                for item in runner.validation_runs
                if item.validation_run_id == validation_run_id
            ),
            None,
        )
        if run is None:
            raise NotFoundError("The validation run was not found.")
        return run

    @staticmethod
    def _checks(
        runner: BobaValidatorRunnerSetV1,
        plan: BobaValidationPlanV1,
    ) -> list[BobaValidationPlanCheckV1]:
        by_id = {
            item.plan_check_id: item
            for item in runner.plan_checks
            if item.validation_plan_id == plan.validation_plan_id
        }
        try:
            return [by_id[item] for item in plan.ordered_check_ids]
        except KeyError as exc:
            raise ValidationError(
                "The validation plan check records are incomplete."
            ) from exc

    @staticmethod
    def _bindings(
        runner: BobaValidatorRunnerSetV1,
        plan: BobaValidationPlanV1,
    ) -> list[BobaValidationInputBindingV1]:
        return [
            item
            for item in runner.input_bindings
            if item.validation_plan_id == plan.validation_plan_id
        ]

    @staticmethod
    def _policy(
        runner: BobaValidatorRunnerSetV1,
        plan: BobaValidationPlanV1,
    ) -> BobaValidationExecutionPolicyV1:
        policy = next(
            (
                item
                for item in runner.execution_policies
                if item.execution_policy_id == plan.execution_policy_id
            ),
            None,
        )
        if policy is None:
            raise ValidationError("The validation execution policy is missing.")
        return policy

    @staticmethod
    def _budget(
        runner: BobaValidatorRunnerSetV1,
        plan: BobaValidationPlanV1,
    ) -> BobaValidationResourceBudgetV1:
        budget = next(
            (
                item
                for item in runner.resource_budgets
                if item.resource_budget_id == plan.resource_budget_id
            ),
            None,
        )
        if budget is None:
            raise ValidationError("The validation resource budget is missing.")
        return budget

    @staticmethod
    def _registry(
        runner: BobaValidatorRunnerSetV1,
        plan: BobaValidationPlanV1,
    ) -> BobaValidatorRegistrySnapshotV1:
        snapshot = next(
            (
                item
                for item in runner.registry_snapshots
                if item.registry_snapshot_id == plan.registry_snapshot_id
            ),
            None,
        )
        if snapshot is None:
            raise ValidationError("The immutable validator registry is missing.")
        return snapshot

    @staticmethod
    def _descriptor_map(
        runner: BobaValidatorRunnerSetV1,
        plan: BobaValidationPlanV1,
    ) -> dict[str, BobaValidatorDescriptorV1]:
        snapshot = BobaValidatorRunnerV1._registry(runner, plan)
        return {
            item.validator_id: item
            for item in runner.validator_descriptors
            if snapshot.validator_versions.get(item.validator_id)
            == item.validator_version
        }

    @staticmethod
    def _environment(
        runner: BobaValidatorRunnerSetV1,
        run: BobaValidationRunV1,
    ) -> BobaValidationEnvironmentSnapshotV1:
        environment = next(
            (
                item
                for item in runner.environment_snapshots
                if item.environment_snapshot_id == run.environment_snapshot_id
            ),
            None,
        )
        if environment is None:
            raise ValidationError("The validation environment snapshot is missing.")
        return environment

    def _build_input_bindings(
        self,
        validation_plan_id: str,
        *,
        project_id: str,
        workflow_run_id: str,
        stage_instance_id: str,
        supplied: Sequence[Mapping[str, Any]],
    ) -> list[BobaValidationInputBindingV1]:
        allowed = {
            "clip_id",
            "output_id",
            "artifact_type",
            "producer_module_id",
            "producer_record_id",
            "schema_id",
            "schema_version",
            "artifact_digest",
            "sanitized_storage_reference",
            "exact_local_target",
            "immutable",
            "source_media",
            "source_media_read_only",
            "accepted_output",
            "required",
            "available",
            "stale",
            "malformed",
            "rights_status",
            "warnings",
        }
        bindings: list[BobaValidationInputBindingV1] = []
        for index, raw in enumerate(supplied):
            payload = dict(raw)
            unexpected = sorted(
                set(payload)
                - allowed
                - {
                    "input_binding_id",
                    "validation_plan_id",
                    "project_id",
                    "workflow_run_id",
                    "stage_instance_id",
                }
            )
            if unexpected:
                raise ValidationError(
                    "Validation input binding contains unsupported fields.",
                    details={"fields": unexpected},
                )
            reference = str(
                payload.get("sanitized_storage_reference") or ""
            ).strip()
            exact_target = str(payload.get("exact_local_target") or "").strip()
            artifact_type = _bounded_text(
                payload.get("artifact_type") or "unknown",
                maximum=160,
            )
            provisional = BobaValidationInputBindingV1(
                input_binding_id=_stable_id(
                    "validation_input",
                    validation_plan_id,
                    index,
                    artifact_type,
                    reference,
                    str(payload.get("artifact_digest") or ""),
                ),
                validation_plan_id=validation_plan_id,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                stage_instance_id=stage_instance_id,
                clip_id=_bounded_text(payload.get("clip_id"), maximum=180),
                output_id=_bounded_text(payload.get("output_id"), maximum=180),
                artifact_type=artifact_type,
                producer_module_id=_bounded_text(
                    payload.get("producer_module_id"),
                    maximum=160,
                ),
                producer_record_id=_bounded_text(
                    payload.get("producer_record_id"),
                    maximum=180,
                ),
                schema_id=_bounded_text(payload.get("schema_id"), maximum=180),
                schema_version=_bounded_text(
                    payload.get("schema_version") or "1",
                    maximum=80,
                ),
                artifact_digest=(
                    str(payload.get("artifact_digest") or _EMPTY_DIGEST)
                    .strip()
                    .casefold()
                ),
                sanitized_storage_reference=reference,
                exact_local_target=exact_target,
                immutable=bool(payload.get("immutable", True)),
                source_media=bool(payload.get("source_media", False)),
                source_media_read_only=bool(
                    payload.get("source_media_read_only", True)
                ),
                accepted_output=bool(payload.get("accepted_output", False)),
                required=bool(payload.get("required", True)),
                available=bool(payload.get("available", True)),
                stale=bool(payload.get("stale", False)),
                malformed=bool(payload.get("malformed", False)),
                rights_status=_bounded_text(
                    payload.get("rights_status") or "unknown",
                    maximum=80,
                ),
                warnings=_unique(
                    _sequence(payload.get("warnings")),
                    limit=32,
                    maximum=500,
                ),
            )
            if provisional.available:
                path = self._resolve_binding_target(provisional)
                actual_digest = self._path_digest(path)
                declared = str(payload.get("artifact_digest") or "").strip()
                if declared and declared.casefold() != actual_digest:
                    raise ValidationError(
                        "Validation input digest does not match the exact target.",
                        details={"input_index": index},
                    )
                provisional = provisional.model_copy(
                    update={
                        "artifact_digest": actual_digest,
                        "input_binding_id": _stable_id(
                            "validation_input",
                            validation_plan_id,
                            index,
                            artifact_type,
                            reference,
                            actual_digest,
                        ),
                    }
                )
            bindings.append(provisional)
        if len({item.input_binding_id for item in bindings}) != len(bindings):
            raise ValidationError("Validation input binding IDs must be unique.")
        return bindings

    def _build_plan_checks(
        self,
        validation_plan_id: str,
        *,
        supplied: Sequence[Mapping[str, Any]],
        descriptors: Mapping[str, BobaValidatorDescriptorV1],
        bindings: Sequence[BobaValidationInputBindingV1],
        allow_unavailable_required: bool,
    ) -> list[BobaValidationPlanCheckV1]:
        allowed = {
            "validator_id",
            "check_key",
            "required",
            "depends_on",
            "dependency_check_ids",
            "input_binding_indexes",
            "input_binding_ids",
            "expected_values",
            "tolerance",
            "acceptance_criteria",
            "rejection_criteria",
            "timeout_seconds",
            "maximum_attempts",
            "stop_suite_on_failure",
        }
        generated_ids: list[str] = []
        token_map: dict[str, str] = {}
        for index, raw in enumerate(supplied):
            unexpected = sorted(set(raw) - allowed)
            if unexpected:
                raise ValidationError(
                    "Validation checks cannot define commands, adapters, or "
                    "unsupported execution fields.",
                    details={"fields": unexpected},
                )
            validator_id = str(raw.get("validator_id") or "").strip()
            check_key = str(raw.get("check_key") or f"{validator_id}:{index}")
            check_id = _stable_id(
                "validation_check",
                validation_plan_id,
                index,
                validator_id,
                check_key,
            )
            generated_ids.append(check_id)
            for token in (check_id, check_key):
                if token in token_map:
                    raise ValidationError(
                        "Validation check keys must be unique."
                    )
                token_map[token] = check_id
            token_map.setdefault(validator_id, check_id)
        binding_ids = [item.input_binding_id for item in bindings]
        checks: list[BobaValidationPlanCheckV1] = []
        for index, raw in enumerate(supplied):
            validator_id = str(raw.get("validator_id") or "").strip()
            descriptor = descriptors[validator_id]
            required = bool(raw.get("required", True))
            if (
                required
                and descriptor.availability_status != "available"
                and not allow_unavailable_required
            ):
                raise ValidationError(
                    "A required validation check is unavailable.",
                    details={
                        "validator_id": validator_id,
                        "availability": descriptor.availability_status,
                    },
                )
            dependency_tokens = _sequence(
                raw.get("depends_on") or raw.get("dependency_check_ids")
            )
            dependencies: list[str] = []
            for token_value in dependency_tokens:
                token = str(token_value)
                if token not in token_map:
                    raise ValidationError(
                        "Validation check references an unknown dependency.",
                        details={"dependency": token},
                    )
                dependencies.append(token_map[token])
            selected_binding_ids: list[str] = []
            indexes = _sequence(raw.get("input_binding_indexes"))
            if indexes:
                for value in indexes:
                    binding_index = _int_value(value)
                    if (
                        binding_index is None
                        or binding_index < 0
                        or binding_index >= len(bindings)
                    ):
                        raise ValidationError(
                            "Validation check input index is out of bounds."
                        )
                    selected_binding_ids.append(binding_ids[binding_index])
            elif _sequence(raw.get("input_binding_ids")):
                requested = [str(item) for item in raw["input_binding_ids"]]
                unknown = sorted(set(requested) - set(binding_ids))
                if unknown:
                    raise ValidationError(
                        "Validation check references an unknown input binding."
                    )
                selected_binding_ids = requested
            else:
                selected_binding_ids = list(binding_ids)
            timeout = _int_value(
                raw.get("timeout_seconds"),
                descriptor.default_timeout_seconds,
            )
            timeout = max(
                1,
                min(
                    int(timeout or descriptor.default_timeout_seconds),
                    descriptor.maximum_timeout_seconds,
                    900,
                ),
            )
            attempts = max(
                1,
                min(
                    int(_int_value(raw.get("maximum_attempts"), 1) or 1),
                    2,
                ),
            )
            checks.append(
                BobaValidationPlanCheckV1(
                    plan_check_id=generated_ids[index],
                    validation_plan_id=validation_plan_id,
                    validator_id=validator_id,
                    validator_version=descriptor.validator_version,
                    display_name=descriptor.display_name,
                    category=descriptor.category,
                    required=required,
                    order=index,
                    dependency_check_ids=list(dict.fromkeys(dependencies)),
                    input_binding_ids=list(
                        dict.fromkeys(selected_binding_ids)
                    ),
                    expected_values=_json_safe(
                        _mapping(raw.get("expected_values"))
                    ),
                    tolerance={
                        str(key): float(value)
                        for key, value in _mapping(raw.get("tolerance")).items()
                    },
                    acceptance_criteria=_unique(
                        _sequence(raw.get("acceptance_criteria"))
                        or [f"{descriptor.display_name} passes."],
                        limit=32,
                        maximum=500,
                    ),
                    rejection_criteria=_unique(
                        _sequence(raw.get("rejection_criteria"))
                        or [f"{descriptor.display_name} fails or is unavailable."],
                        limit=32,
                        maximum=500,
                    ),
                    timeout_seconds=timeout,
                    maximum_attempts=attempts,
                    stop_suite_on_failure=bool(
                        raw.get("stop_suite_on_failure", False)
                    ),
                    safety_gate_required=descriptor.safety_gate_required,
                    approval_required=descriptor.target_approval_required,
                    warnings=(
                        [descriptor.availability_reason]
                        if descriptor.availability_status != "available"
                        else []
                    ),
                    limitations=[
                        "Execution details come only from the fixed registry adapter."
                    ],
                )
            )
        return checks

    def _resolve_binding_target(
        self,
        binding: BobaValidationInputBindingV1,
    ) -> Path:
        candidates: list[Path] = []
        if binding.sanitized_storage_reference:
            reference = PurePosixPath(binding.sanitized_storage_reference)
            candidates.append(
                (
                    self.storage_root
                    / Path(*reference.parts)
                ).resolve(strict=False)
            )
        if binding.exact_local_target:
            exact = Path(binding.exact_local_target).expanduser().resolve(
                strict=False
            )
            if not _path_is_within(exact, self.allowed_input_roots):
                raise ValidationError(
                    "The exact validation input is outside configured local roots."
                )
            candidates.append(exact)
        if not candidates:
            if binding.available:
                raise ValidationError("The exact validation input is missing.")
            return self.runner_workspace_root / "unavailable"
        if len(candidates) == 2 and candidates[0] != candidates[1]:
            raise ValidationError(
                "The sanitized reference and exact local target disagree."
            )
        target = candidates[-1]
        if binding.available and not target.exists():
            raise ValidationError("The exact validation input is unavailable.")
        if not _path_is_within(target, self.allowed_input_roots):
            raise ValidationError(
                "The resolved validation input escaped configured local roots."
            )
        return target

    def _path_digest(self, path: Path) -> str:
        if path.is_file():
            return _sha256_file(path)
        if path.is_dir():
            entries: list[tuple[str, str]] = []
            for item in sorted(value for value in path.rglob("*") if value.is_file()):
                if any(
                    part in {
                        ".git",
                        ".mypy_cache",
                        ".next",
                        ".pytest_cache",
                        ".ruff_cache",
                        "__pycache__",
                        "node_modules",
                    }
                    for part in item.parts
                ):
                    continue
                if len(entries) >= 20_000:
                    raise ValidationError(
                        "Validation input directory exceeds the bounded digest budget."
                    )
                entries.append(
                    (item.relative_to(path).as_posix(), _sha256_file(item))
                )
            return _digest(entries)
        raise ValidationError("The validation input target is not a file or directory.")

    def _verify_binding_digests(
        self,
        bindings: Sequence[BobaValidationInputBindingV1],
    ) -> None:
        for binding in bindings:
            if not binding.available:
                if binding.required:
                    raise ValidationError(
                        "A required validation input is unavailable."
                    )
                continue
            actual = self._path_digest(self._resolve_binding_target(binding))
            if actual != binding.artifact_digest:
                raise ValidationError(
                    "A validation input changed after plan creation.",
                    details={"input_binding_id": binding.input_binding_id},
                )

    def _actual_binding_set_digest(
        self,
        bindings: Sequence[BobaValidationInputBindingV1],
    ) -> str:
        observed: list[tuple[str, str]] = []
        for binding in bindings:
            if not binding.available:
                observed.append((binding.input_binding_id, "unavailable"))
                continue
            try:
                actual = self._path_digest(self._resolve_binding_target(binding))
            except ValidationError:
                actual = "missing"
            observed.append((binding.input_binding_id, actual))
        return _digest(sorted(observed))

    def _code_workspace_digest(
        self,
        bindings: Sequence[BobaValidationInputBindingV1],
    ) -> str:
        workspace = self._code_workspace(bindings)
        return _protected_tree_digest(workspace)

    def _code_workspace(
        self,
        bindings: Sequence[BobaValidationInputBindingV1],
    ) -> Path:
        candidates = [
            self._resolve_binding_target(item)
            for item in bindings
            if item.artifact_type == "code_workspace" and item.available
        ]
        if len(candidates) != 1:
            raise ValidationError(
                "Isolated code validation requires one exact code workspace."
            )
        workspace = candidates[0].resolve()
        if workspace == self.repository_root:
            raise ValidationError(
                "Code validation cannot execute in the protected repository root."
            )
        if not workspace.is_dir():
            raise ValidationError("The isolated code workspace is unavailable.")
        if not (
            (workspace / ".git").exists()
            or (workspace / ".boba_isolated_workspace").is_file()
        ):
            raise ValidationError(
                "The code target is not an explicit isolated worktree or copy."
            )
        return workspace

    def _run_workspace(self, validation_run_id: str) -> Path:
        if not _SAFE_ID.fullmatch(validation_run_id):
            raise ValidationError("Invalid validation run workspace identity.")
        workspace = (self.runner_workspace_root / validation_run_id).resolve()
        if self.runner_workspace_root not in workspace.parents:
            raise ValidationError("Validation run workspace escaped its root.")
        return workspace

    def _cleanup_run_workspace(self, validation_run_id: str) -> None:
        workspace = self._run_workspace(validation_run_id)
        if (
            workspace.exists()
            and workspace.parent == self.runner_workspace_root
            and workspace.name == validation_run_id
        ):
            shutil.rmtree(workspace, ignore_errors=True)

    def _new_check_run(
        self,
        run: BobaValidationRunV1,
        check: BobaValidationPlanCheckV1,
        descriptor: BobaValidatorDescriptorV1,
        environment: BobaValidationEnvironmentSnapshotV1,
        bindings: Sequence[BobaValidationInputBindingV1],
        *,
        attempt_number: int,
    ) -> BobaValidationCheckRunV1:
        relevant = [
            item
            for item in bindings
            if item.input_binding_id in check.input_binding_ids
        ]
        input_digest = _digest(
            [
                (
                    item.input_binding_id,
                    item.artifact_digest,
                    item.schema_id,
                    item.schema_version,
                )
                for item in relevant
            ]
        )
        return BobaValidationCheckRunV1(
            check_run_id=_runtime_id("validation_check_run"),
            validation_run_id=run.validation_run_id,
            plan_check_id=check.plan_check_id,
            validator_id=check.validator_id,
            validator_version=check.validator_version,
            category=check.category,
            required=check.required,
            attempt_number=attempt_number,
            adapter_id=descriptor.adapter_id,
            input_binding_ids=check.input_binding_ids,
            input_digest=input_digest,
            environment_digest=environment.environment_digest,
            timeout_seconds=check.timeout_seconds,
            limitations=[
                "The check can invoke only its source-declared fixed adapter."
            ],
        )

    def _append_event(
        self,
        runner: BobaValidatorRunnerSetV1,
        run: BobaValidationRunV1,
        *,
        event_type: BobaValidationEventTypeV1,
        severity: Literal["info", "warning", "error", "critical", "unknown"],
        technical_message: str,
        easy_message: str,
        confirmed_fact: str = "",
        assessment: str = "",
        check_run: BobaValidationCheckRunV1 | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        evidence_reference_ids: Sequence[str] = (),
    ) -> BobaValidationEventV1:
        existing = [
            item
            for item in runner.events
            if item.validation_run_id == run.validation_run_id
        ]
        total = progress_total
        current = progress_current
        percent = (
            round(current / total * 100.0, 2)
            if current is not None and total
            else None
        )
        event = BobaValidationEventV1(
            event_id=_runtime_id("validation_event"),
            validation_run_id=run.validation_run_id,
            project_id=run.project_id,
            workflow_run_id=run.workflow_run_id,
            sequence=max((item.sequence for item in existing), default=0) + 1,
            event_type=event_type,
            severity=severity,
            check_run_id=check_run.check_run_id if check_run else "",
            validator_id=check_run.validator_id if check_run else "",
            technical_message=_bounded_text(technical_message, maximum=900),
            easy_message=_bounded_text(easy_message, maximum=900),
            confirmed_fact=_bounded_text(confirmed_fact, maximum=900),
            assessment=_bounded_text(assessment, maximum=900),
            progress_current=current,
            progress_total=total,
            progress_percent=percent,
            requires_attention=severity in {"error", "critical"},
            evidence_reference_ids=_unique(
                evidence_reference_ids,
                limit=64,
                maximum=180,
            ),
        )
        runner.events.append(event)
        return event

    def _append_incident(
        self,
        runner: BobaValidatorRunnerSetV1,
        run: BobaValidationRunV1,
        *,
        incident_type: BobaValidationIncidentTypeV1,
        severity: Literal["info", "low", "medium", "high", "critical", "unknown"],
        title: str,
        summary: str,
        check_run_id: str = "",
        validator_id: str = "",
        evidence_ids: Sequence[str] = (),
        project_state_uncertain: bool = False,
    ) -> BobaValidationIncidentV1:
        fingerprint = _digest(
            {
                "project_id": run.project_id,
                "validation_run_id": run.validation_run_id,
                "incident_type": incident_type,
                "validator_id": validator_id,
                "summary": _bounded_text(summary, maximum=500),
            }
        )
        incident = BobaValidationIncidentV1(
            incident_id=_runtime_id("validation_incident"),
            validation_run_id=run.validation_run_id,
            check_run_id=check_run_id,
            incident_type=incident_type,
            severity=severity,
            title=_bounded_text(title, maximum=240),
            bounded_summary=_bounded_text(summary, maximum=900),
            validator_id=validator_id,
            target_id=run.target_id,
            evidence_ids=_unique(evidence_ids, limit=64, maximum=180),
            repeated_fingerprint=fingerprint,
            project_state_uncertain=project_state_uncertain,
            protected_state_risk=project_state_uncertain,
            immediate_runner_action=(
                "Stop the suite and require human inspection."
                if project_state_uncertain
                else "Retain the failed evidence and block a passing suite decision."
            ),
            recommended_target_module=(
                "human_operator"
                if project_state_uncertain
                else "root_cause_analyzer"
            ),
            human_review_required=project_state_uncertain,
        )
        runner.incidents.append(incident)
        return incident

    def _append_incident_for_outcome(
        self,
        runner: BobaValidatorRunnerSetV1,
        run: BobaValidationRunV1,
        check: BobaValidationPlanCheckV1,
        check_run: BobaValidationCheckRunV1,
        outcome: _AdapterOutcome,
        evidence: BobaValidationEvidenceV1,
    ) -> None:
        incident_type = cast(
            BobaValidationIncidentTypeV1,
            {
            "failed": "validator_failure",
            "unavailable": "unavailable_validator",
            "blocked": "safety_block",
            "dependency_blocked": "dependency_failure",
            "errored": "validator_crash",
            "timed_out": "validator_timeout",
            "cancelled": "cancellation_failure",
            }.get(outcome.status, "unknown"),
        )
        severity: Literal[
            "info",
            "low",
            "medium",
            "high",
            "critical",
            "unknown",
        ] = (
            "high"
            if check.required and outcome.status in {"failed", "errored"}
            else "medium"
        )
        self._append_incident(
            runner,
            run,
            incident_type=incident_type,
            severity=severity,
            title=f"{check.display_name} did not pass",
            summary=outcome.summary,
            check_run_id=check_run.check_run_id,
            validator_id=check.validator_id,
            evidence_ids=[evidence.evidence_id],
            project_state_uncertain=run.project_state_uncertain,
        )

    def _materialize_outcome(
        self,
        run: BobaValidationRunV1,
        check: BobaValidationPlanCheckV1,
        check_run: BobaValidationCheckRunV1,
        outcome: _AdapterOutcome,
    ) -> tuple[BobaValidationEvidenceV1, BobaValidationResultV1]:
        evidence_payload = {
            "validator_id": check.validator_id,
            "status": outcome.status,
            "summary": outcome.summary,
            "assertions": outcome.assertion_results,
            "measured_values": outcome.measured_values,
            "expected_values": outcome.expected_values,
        }
        evidence_digest = _digest(_json_safe(evidence_payload))
        evidence = BobaValidationEvidenceV1(
            evidence_id=_stable_id(
                "validation_evidence",
                run.validation_run_id,
                check_run.check_run_id,
                evidence_digest,
            ),
            validation_run_id=run.validation_run_id,
            check_run_id=check_run.check_run_id,
            source_type=outcome.source_type,
            validator_id=check.validator_id,
            category=check.category,
            bounded_summary=_bounded_text(outcome.summary, maximum=900),
            observed_value=_json_safe(outcome.measured_values),
            expected_value=_json_safe(outcome.expected_values),
            tolerance=check.tolerance,
            evidence_digest=evidence_digest,
            reliability=(
                "high"
                if outcome.confidence >= 0.85
                else "medium"
                if outcome.confidence >= 0.6
                else "low"
            ),
            confidence=outcome.confidence,
            supports_pass=outcome.status == "passed",
            supports_failure=outcome.status in {"failed", "errored", "timed_out"},
            requires_human_interpretation=outcome.status in {
                "blocked",
                "unavailable",
                "dependency_blocked",
            },
            redacted=True,
            warnings=_unique(
                outcome.warnings or [],
                limit=32,
                maximum=500,
            ),
        )
        result_digest = _result_digest_payload(
            validator_id=check.validator_id,
            status=outcome.status,
            assertions=outcome.assertion_results,
            measured=outcome.measured_values,
            expected=outcome.expected_values,
        )
        result = BobaValidationResultV1(
            result_id=_stable_id(
                "validation_result",
                run.validation_run_id,
                check_run.check_run_id,
                result_digest,
            ),
            validation_run_id=run.validation_run_id,
            check_run_id=check_run.check_run_id,
            validator_id=check.validator_id,
            status=outcome.status,
            assertion_results=outcome.assertion_results,
            measured_values=_json_safe(outcome.measured_values),
            expected_values=_json_safe(outcome.expected_values),
            failed_assertions=_unique(
                outcome.failed_assertions,
                limit=128,
                maximum=180,
            ),
            unavailable_assertions=_unique(
                outcome.unavailable_assertions,
                limit=128,
                maximum=180,
            ),
            evidence_ids=[evidence.evidence_id],
            required_check=check.required,
            blocks_suite_pass=check.required and outcome.status != "passed",
            confidence=outcome.confidence,
            result_digest=result_digest,
            warnings=_unique(
                outcome.warnings or [],
                limit=32,
                maximum=500,
            ),
            limitations=_unique(
                outcome.limitations or [],
                limit=32,
                maximum=500,
            ),
        )
        return evidence, result

    def _finalize_run(
        self,
        runner: BobaValidatorRunnerSetV1,
        run: BobaValidationRunV1,
        plan: BobaValidationPlanV1,
    ) -> BobaValidationSuiteDecisionV1:
        existing = next(
            (
                item
                for item in runner.suite_decisions
                if item.validation_run_id == run.validation_run_id
            ),
            None,
        )
        if existing is not None:
            return existing
        plan_checks = self._checks(runner, plan)
        check_runs = [
            item
            for item in runner.check_runs
            if item.validation_run_id == run.validation_run_id
        ]
        latest_by_plan_check: dict[str, BobaValidationCheckRunV1] = {}
        for check_run in check_runs:
            latest_by_plan_check[check_run.plan_check_id] = check_run
        required = [item for item in plan_checks if item.required]
        optional = [item for item in plan_checks if not item.required]
        missing_required = [
            item.plan_check_id
            for item in required
            if item.plan_check_id not in latest_by_plan_check
        ]
        failed_required = [
            item.plan_check_id
            for item in required
            if latest_by_plan_check.get(item.plan_check_id)
            and latest_by_plan_check[item.plan_check_id].status
            in {"failed", "errored"}
        ]
        unavailable_required = [
            item.plan_check_id
            for item in required
            if latest_by_plan_check.get(item.plan_check_id)
            and latest_by_plan_check[item.plan_check_id].status
            in {"unavailable", "dependency_blocked"}
        ]
        blocked_required = [
            item.plan_check_id
            for item in required
            if latest_by_plan_check.get(item.plan_check_id)
            and latest_by_plan_check[item.plan_check_id].status == "blocked"
        ]
        timed_out_required = [
            item.plan_check_id
            for item in required
            if latest_by_plan_check.get(item.plan_check_id)
            and latest_by_plan_check[item.plan_check_id].status == "timed_out"
        ]
        cancelled_required = [
            item.plan_check_id
            for item in required
            if latest_by_plan_check.get(item.plan_check_id)
            and latest_by_plan_check[item.plan_check_id].status == "cancelled"
        ]
        failed_optional = [
            item.plan_check_id
            for item in optional
            if latest_by_plan_check.get(item.plan_check_id)
            and latest_by_plan_check[item.plan_check_id].status != "passed"
        ]
        required_passed = bool(required) and all(
            latest_by_plan_check.get(item.plan_check_id)
            and latest_by_plan_check[item.plan_check_id].status == "passed"
            for item in required
        )
        required_complete = not missing_required and all(
            latest_by_plan_check[item.plan_check_id].status
            in _TERMINAL_CHECK_STATUSES
            for item in required
        )
        optional_complete = all(
            latest_by_plan_check.get(item.plan_check_id)
            and latest_by_plan_check[item.plan_check_id].status
            in _TERMINAL_CHECK_STATUSES
            for item in optional
        )
        decision: BobaValidationSuiteDecisionValueV1
        if run.cancellation_requested or cancelled_required or run.run_status == "cancelled":
            decision = "cancelled"
        elif run.project_state_uncertain:
            decision = "errored"
        elif blocked_required or run.run_status == "blocked":
            decision = "blocked"
        elif timed_out_required or run.run_status == "timed_out":
            decision = "timed_out"
        elif failed_required:
            decision = "failed"
        elif missing_required or unavailable_required or not required_complete:
            decision = "incomplete"
        elif required_passed and failed_optional:
            decision = "passed_with_optional_warnings"
        elif required_passed:
            decision = "passed"
        else:
            decision = "invalid"
        bindings = self._bindings(runner, plan)
        target_unchanged = True
        with suppress(ValidationError):
            self._verify_binding_digests(bindings)
        try:
            self._verify_binding_digests(bindings)
        except ValidationError:
            target_unchanged = False
        environment = self._environment(runner, run)
        code_plan = any(item.validator_id in _CODE_VALIDATORS for item in plan_checks)
        try:
            workspace_digest = (
                self._code_workspace_digest(bindings)
                if code_plan
                else self._actual_binding_set_digest(bindings)
            )
            current_environment = capture_validation_environment_snapshot(
                project_id=run.project_id,
                project_snapshot_digest=plan.project_snapshot_digest,
                workspace_mode=environment.workspace_mode,
                workspace_digest=workspace_digest,
                runner_owned_temp_root="validator_runner/workspaces",
                ffprobe_binary=self.ffprobe_binary,
                ffmpeg_binary=self.ffmpeg_binary,
            )
            environment_unchanged = (
                current_environment.environment_digest
                == environment.environment_digest
            )
        except ValidationError:
            environment_unchanged = False
        run_results = [
            item
            for item in runner.validation_results
            if item.validation_run_id == run.validation_run_id
        ]
        run_evidence = [
            item
            for item in runner.evidence_records
            if item.validation_run_id == run.validation_run_id
        ]
        evidence_ids = {item.evidence_id for item in run_evidence}
        evidence_complete = all(
            result.evidence_ids
            and set(result.evidence_ids).issubset(evidence_ids)
            for result in run_results
        ) and len(run_results) == len(check_runs)
        technical_passed = bool(
            decision in {"passed", "passed_with_optional_warnings"}
            and required_passed
            and target_unchanged
            and environment_unchanged
            and evidence_complete
        )
        if decision in {"passed", "passed_with_optional_warnings"} and not technical_passed:
            decision = "incomplete"
        decision_summary = {
            "passed": "Every required check passed with current exact evidence.",
            "passed_with_optional_warnings": (
                "Every required check passed; one or more optional checks did not pass."
            ),
            "failed": "At least one required validation check failed.",
            "incomplete": (
                "Required validation evidence is missing, unavailable, or stale."
            ),
            "blocked": "A required validation check was blocked.",
            "errored": "Validation ended with uncertain or errored protected state.",
            "timed_out": "A required validation time budget expired.",
            "cancelled": "Validation was cancelled before all required checks passed.",
            "invalid": "The suite could not derive a valid decision.",
            "unknown": "The suite decision is unknown.",
        }[decision]
        suite = BobaValidationSuiteDecisionV1(
            suite_decision_id=_stable_id(
                "validation_suite_decision",
                run.validation_run_id,
                decision,
                [item.result_digest for item in run_results],
            ),
            validation_run_id=run.validation_run_id,
            validation_plan_id=plan.validation_plan_id,
            decision=decision,
            decision_summary=decision_summary,
            required_checks_complete=required_complete,
            required_checks_passed=required_passed,
            optional_checks_complete=optional_complete,
            failed_required_check_ids=failed_required,
            incomplete_required_check_ids=list(
                dict.fromkeys(
                    [
                        *missing_required,
                        *unavailable_required,
                        *blocked_required,
                    ]
                )
            ),
            unavailable_required_check_ids=unavailable_required,
            timed_out_required_check_ids=timed_out_required,
            failed_optional_check_ids=failed_optional,
            warning_check_ids=failed_optional,
            acceptance_criteria_met=technical_passed,
            rejection_criteria_triggered=bool(
                failed_required
                or blocked_required
                or timed_out_required
                or run.project_state_uncertain
            ),
            evidence_complete=evidence_complete,
            target_digest_unchanged=target_unchanged,
            environment_digest_unchanged=environment_unchanged,
            project_snapshot_current=target_unchanged,
            technical_validation_passed=technical_passed,
            output_quality_authorized=False,
            workflow_transition_authorized=False,
            upload_authorized=False,
            publication_authorized=False,
            human_review_required=decision
            in {"blocked", "errored", "invalid"},
            confidence=(
                min((item.confidence for item in run_results), default=0.0)
                if technical_passed
                else 1.0
                if decision in {"failed", "blocked", "timed_out", "cancelled"}
                else 0.6
            ),
            warnings=(
                ["Optional checks did not pass."]
                if decision == "passed_with_optional_warnings"
                else []
            ),
            limitations=[
                "The suite decision is technical evidence, not output-quality approval.",
                "No workflow transition, upload, publication, push, or deployment was authorized.",
            ],
        )
        runner.suite_decisions.append(suite)
        run.suite_decision_id = suite.suite_decision_id
        run.completed_at = run.completed_at or now_iso()
        run.run_status = cast(
            BobaValidationRunStatusV1,
            {
            "passed": "completed",
            "passed_with_optional_warnings": "completed",
            "failed": "failed",
            "incomplete": "incomplete",
            "blocked": "blocked",
            "errored": "failed",
            "timed_out": "timed_out",
            "cancelled": "cancelled",
            "invalid": "failed",
            "unknown": "failed",
            }[decision],
        )
        runner.handoffs.extend(
            self._build_handoffs(
                run,
                suite,
                run_results,
                run_evidence,
            )
        )
        event_type: BobaValidationEventTypeV1 = (
            "suite_passed"
            if technical_passed
            else "run_cancelled"
            if decision == "cancelled"
            else "run_blocked"
            if decision == "blocked"
            else "suite_incomplete"
            if decision in {"incomplete", "timed_out"}
            else "suite_failed"
        )
        self._append_event(
            runner,
            run,
            event_type=event_type,
            severity="info" if technical_passed else "error",
            technical_message=decision_summary,
            easy_message=(
                "All required technical checks passed."
                if technical_passed
                else "Technical validation did not produce a complete pass."
            ),
            confirmed_fact=(
                f"Suite decision {suite.suite_decision_id} is persisted and "
                "does not authorize downstream execution."
            ),
            progress_current=len(check_runs),
            progress_total=len(plan_checks),
            evidence_reference_ids=[item.evidence_id for item in run_evidence],
        )
        return suite

    @staticmethod
    def _build_handoffs(
        run: BobaValidationRunV1,
        suite: BobaValidationSuiteDecisionV1,
        results: Sequence[BobaValidationResultV1],
        evidence: Sequence[BobaValidationEvidenceV1],
    ) -> list[BobaValidationHandoffV1]:
        targets: list[BobaValidationHandoffTargetV1] = [
            "workflow_controller",
            "output_quality_reviewer",
        ]
        if not suite.technical_validation_passed:
            targets.extend(["root_cause_analyzer", "repair_planner"])
        return [
            BobaValidationHandoffV1(
                handoff_id=_stable_id(
                    "validation_handoff",
                    run.validation_run_id,
                    target,
                    suite.suite_decision_id,
                ),
                validation_run_id=run.validation_run_id,
                suite_decision_id=suite.suite_decision_id,
                target_module_id=target,
                reason=(
                    "Consume persisted technical validation evidence."
                    if suite.technical_validation_passed
                    else "Inspect failed or incomplete technical validation evidence."
                ),
                target_id=run.target_id,
                result_ids=[item.result_id for item in results],
                failed_required_check_ids=suite.failed_required_check_ids,
                incomplete_required_check_ids=(
                    suite.incomplete_required_check_ids
                ),
                evidence_ids=[item.evidence_id for item in evidence],
                satisfied_conditions=(
                    ["technical_validation_passed"]
                    if suite.technical_validation_passed
                    else []
                ),
                blocking_conditions=(
                    []
                    if suite.technical_validation_passed
                    else [suite.decision_summary]
                ),
                allowed_actions=["inspect_evidence", "record_advisory_decision"],
                prohibited_actions=[
                    "automatic_workflow_transition",
                    "automatic_output_acceptance",
                    "upload",
                    "publication",
                    "push",
                    "merge",
                    "deployment",
                ],
                apply_automatically=False,
                human_approval_required=target
                in {"repair_planner", "workflow_controller"},
                priority=(
                    "high"
                    if not suite.technical_validation_passed
                    else "normal"
                ),
            )
            for target in targets
        ]

    @staticmethod
    def _easy_check_message(
        check: BobaValidationPlanCheckV1,
        status: BobaValidationCheckStatusV1,
    ) -> str:
        return {
            "passed": f"{check.display_name} passed.",
            "failed": f"{check.display_name} failed.",
            "unavailable": f"{check.display_name} is unavailable.",
            "blocked": f"{check.display_name} was blocked safely.",
            "dependency_blocked": (
                f"{check.display_name} could not run because a dependency did not pass."
            ),
            "errored": f"{check.display_name} ended with an error.",
            "timed_out": f"{check.display_name} timed out.",
            "cancelled": f"{check.display_name} was cancelled.",
        }.get(status, f"{check.display_name} did not pass.")

    @staticmethod
    def _mark_signal_usage(
        runner: BobaValidatorRunnerSetV1,
        descriptor: BobaValidatorDescriptorV1,
    ) -> None:
        runner.signal_usage.validator_registry_used = True
        if descriptor.implementation_type == "internal_python":
            runner.signal_usage.internal_python_validator_used = True
        if descriptor.implementation_type == "fixed_local_process":
            runner.signal_usage.fixed_local_process_used = True
        if descriptor.implementation_type == "fixed_media_probe":
            runner.signal_usage.registered_ffprobe_used = True
            runner.signal_usage.media_validation_used = True
        if descriptor.implementation_type == "fixed_media_decode":
            runner.signal_usage.registered_ffmpeg_decode_used = True
            runner.signal_usage.media_validation_used = True
        if descriptor.category in {"contract_schema", "caption_schema"}:
            runner.signal_usage.schema_validation_used = True
        if descriptor.category in {
            "artifact_integrity",
            "artifact_manifest",
            "artifact_lineage",
            "rendering_manifest",
        }:
            runner.signal_usage.artifact_validation_used = True
        if descriptor.category in {"workflow_state", "workflow_graph"}:
            runner.signal_usage.workflow_validation_used = True
        if descriptor.category in {"code_static", "code_types"}:
            runner.signal_usage.code_static_validation_used = True
        if descriptor.category in {"code_unit_tests", "code_regression_tests"}:
            runner.signal_usage.code_test_validation_used = True
        if descriptor.category.startswith("frontend_"):
            runner.signal_usage.frontend_validation_used = True
        if descriptor.category == "checkpoint_integrity_read_only":
            runner.signal_usage.checkpoint_read_only_validation_used = True

    @staticmethod
    def _refresh_summary(runner: BobaValidatorRunnerSetV1) -> None:
        decisions = [item.decision for item in runner.suite_decisions]
        statuses = [item.status for item in runner.check_runs]
        active = [
            item
            for item in runner.validation_runs
            if item.run_status not in _TERMINAL_RUN_STATUSES
        ]
        highest = next(
            (
                item.title
                for item in reversed(runner.incidents)
                if item.severity in {"critical", "high"}
            ),
            runner.incidents[-1].title if runner.incidents else "",
        )
        current = active[-1] if active else None
        runner.runner_summary = BobaValidatorRunnerSummaryV1(
            registry_snapshot_count=len(runner.registry_snapshots),
            registered_validator_count=len(runner.validator_descriptors),
            available_validator_count=sum(
                item.availability_status == "available"
                for item in runner.validator_descriptors
            ),
            degraded_validator_count=sum(
                item.availability_status == "degraded"
                for item in runner.validator_descriptors
            ),
            unavailable_validator_count=sum(
                item.availability_status == "unavailable"
                for item in runner.validator_descriptors
            ),
            future_validator_count=sum(
                item.availability_status == "future"
                for item in runner.validator_descriptors
            ),
            total_plan_count=len(runner.validation_plans),
            total_run_count=len(runner.validation_runs),
            active_run_count=len(active),
            passed_suite_count=decisions.count("passed"),
            warning_suite_count=decisions.count("passed_with_optional_warnings"),
            failed_suite_count=decisions.count("failed"),
            incomplete_suite_count=decisions.count("incomplete"),
            blocked_suite_count=decisions.count("blocked"),
            timed_out_suite_count=decisions.count("timed_out"),
            cancelled_suite_count=decisions.count("cancelled"),
            total_check_count=len(runner.check_runs),
            passed_check_count=statuses.count("passed"),
            failed_check_count=sum(
                item in {"failed", "errored"} for item in statuses
            ),
            unavailable_check_count=statuses.count("unavailable"),
            timed_out_check_count=statuses.count("timed_out"),
            idempotent_reuse_count=runner.runner_summary.idempotent_reuse_count,
            highest_priority_incident=highest,
            current_validation_run_id=(
                current.validation_run_id if current else ""
            ),
            current_validator=(
                next(
                    (
                        item.validator_id
                        for item in runner.check_runs
                        if current
                        and item.check_run_id == current.active_check_run_id
                    ),
                    "",
                )
            ),
            safest_next_action=(
                "Inspect the active fixed validation run."
                if current
                else "Create a digest-bound validation plan or inspect prior evidence."
            ),
            required_human_actions=(
                ["Inspect uncertain protected state."]
                if any(item.project_state_uncertain for item in runner.validation_runs)
                else []
            ),
            limitations=[
                "Suite pass is technical evidence only.",
                "No network or external validation provider is used.",
            ],
        )

    def _execute_adapter(
        self,
        check: BobaValidationPlanCheckV1,
        descriptor: BobaValidatorDescriptorV1,
        bindings: Sequence[BobaValidationInputBindingV1],
        workspace: Path,
        budget: BobaValidationResourceBudgetV1,
        process_key: str,
    ) -> _AdapterOutcome:
        override = self.fixed_adapter_overrides.get(check.validator_id)
        relevant = [
            item
            for item in bindings
            if item.input_binding_id in check.input_binding_ids
        ]
        if override is not None:
            return override(check, relevant, workspace, budget, process_key)
        if descriptor.implementation_type == "internal_python":
            return self._execute_internal_adapter(check, relevant)
        if descriptor.implementation_type in {
            "fixed_media_probe",
            "fixed_media_decode",
        }:
            media_adapter = cast(
                Callable[..., _AdapterOutcome],
                self.__getattribute__("_execute_media_adapter"),
            )
            return media_adapter(check, relevant, workspace)
        if descriptor.implementation_type == "fixed_local_process":
            code_adapter = cast(
                Callable[..., _AdapterOutcome],
                self.__getattribute__("_execute_code_adapter"),
            )
            return code_adapter(check, relevant, workspace, budget, process_key)
        return _AdapterOutcome(
            status="unavailable",
            summary="The fixed validator implementation is unavailable in V1.",
            assertion_results={"validator_implemented": None},
            measured_values={
                "implementation_type": descriptor.implementation_type
            },
            expected_values={"validator_implemented": True},
            failed_assertions=[],
            unavailable_assertions=["validator_implemented"],
            source_type="internal_validator",
            confidence=1.0,
            warnings=[descriptor.availability_reason],
        )

    def _execute_internal_adapter(
        self,
        check: BobaValidationPlanCheckV1,
        bindings: Sequence[BobaValidationInputBindingV1],
    ) -> _AdapterOutcome:
        if check.validator_id == "artifact.digest":
            assertions: dict[str, bool | None] = {}
            measured: dict[str, Any] = {}
            for binding in bindings:
                if not binding.available:
                    assertions[binding.input_binding_id] = None
                    measured[binding.input_binding_id] = "unavailable"
                    continue
                actual = self._path_digest(self._resolve_binding_target(binding))
                assertions[binding.input_binding_id] = (
                    actual == binding.artifact_digest
                )
                measured[binding.input_binding_id] = actual
            return self._assertion_outcome(
                summary_pass="Every exact artifact digest matches its immutable binding.",
                summary_fail="At least one artifact digest is missing or mismatched.",
                assertions=assertions,
                measured=measured,
                expected={
                    item.input_binding_id: item.artifact_digest
                    for item in bindings
                },
                source_type="artifact_check",
            )
        if check.validator_id == "workflow.artifact_lineage":
            assertions = {
                item.input_binding_id: bool(
                    item.producer_module_id
                    and item.producer_record_id
                    and item.artifact_digest != _EMPTY_DIGEST
                )
                for item in bindings
            }
            return self._assertion_outcome(
                summary_pass="Artifact producer lineage is complete and digest-bound.",
                summary_fail="Artifact producer lineage is incomplete.",
                assertions=assertions,
                measured={
                    item.input_binding_id: {
                        "producer_module_id": item.producer_module_id,
                        "producer_record_id": item.producer_record_id,
                        "schema_id": item.schema_id,
                    }
                    for item in bindings
                },
                expected={"complete_lineage": True},
                source_type="workflow_check",
            )
        if check.validator_id == "tool.health":
            return self._validate_tool_health(check)
        payloads = self._json_payloads(bindings)
        if check.validator_id == "artifact.schema":
            return self._validate_artifact_schema(check, payloads)
        if check.validator_id in {
            "artifact.manifest",
            "rendering.manifest",
        }:
            return self._validate_manifest(
                check,
                bindings,
                payloads,
                rendering=check.validator_id == "rendering.manifest",
            )
        if check.validator_id == "workflow.graph":
            return self._validate_workflow_graph_payload(payloads)
        if check.validator_id == "workflow.transition":
            return self._validate_workflow_transition(check, payloads)
        if check.validator_id == "checkpoint.integrity_read_only":
            return self._validate_checkpoint(check, payloads)
        if check.validator_id in {
            "captions.schema",
            "captions.timing",
            "captions.bounds",
        }:
            return self._validate_captions(check, payloads)
        if check.validator_id == "validation.face_motion":
            return self._validate_face_motion(check, payloads)
        if check.validator_id == "validation.multi_speaker":
            return self._validate_multi_speaker(check, payloads)
        return _AdapterOutcome(
            status="unavailable",
            summary="No fixed internal adapter is registered for this validator.",
            assertion_results={"fixed_adapter_registered": None},
            measured_values={"validator_id": check.validator_id},
            expected_values={"fixed_adapter_registered": True},
            failed_assertions=[],
            unavailable_assertions=["fixed_adapter_registered"],
            source_type="internal_validator",
            confidence=1.0,
        )

    def _json_payloads(
        self,
        bindings: Sequence[BobaValidationInputBindingV1],
    ) -> list[tuple[BobaValidationInputBindingV1, dict[str, Any]]]:
        payloads: list[tuple[BobaValidationInputBindingV1, dict[str, Any]]] = []
        for binding in bindings:
            if not binding.available:
                continue
            path = self._resolve_binding_target(binding)
            if not path.is_file():
                raise ValidationError(
                    "The internal JSON validator requires exact files."
                )
            raw = _load_json_file(path)
            if not isinstance(raw, Mapping):
                raise ValidationError("The validation JSON root must be an object.")
            payloads.append((binding, dict(raw)))
        if not payloads:
            raise ValidationError("No available JSON validation input was bound.")
        return payloads

    def _validate_artifact_schema(
        self,
        check: BobaValidationPlanCheckV1,
        payloads: Sequence[tuple[BobaValidationInputBindingV1, dict[str, Any]]],
    ) -> _AdapterOutcome:
        expected_schema = str(
            check.expected_values.get("schema_version")
            or check.expected_values.get("schema_id")
            or ""
        )
        assertions: dict[str, bool | None] = {}
        measured: dict[str, Any] = {}
        for binding, payload in payloads:
            schema_value = str(
                payload.get("schema_version")
                or payload.get("contract_version")
                or payload.get("version")
                or binding.schema_version
                or ""
            )
            root_valid = bool(payload)
            schema_matches = not expected_schema or schema_value == expected_schema
            assertions[f"{binding.input_binding_id}:json_object"] = root_valid
            assertions[f"{binding.input_binding_id}:schema"] = schema_matches
            measured[binding.input_binding_id] = {
                "schema_value": schema_value,
                "key_count": len(payload),
            }
        return self._assertion_outcome(
            summary_pass="Every bound artifact satisfies the requested JSON schema marker.",
            summary_fail="At least one bound artifact has a malformed or mismatched schema.",
            assertions=assertions,
            measured=measured,
            expected={"schema_version": expected_schema or "present"},
            source_type="schema_check",
        )

    def _validate_manifest(
        self,
        check: BobaValidationPlanCheckV1,
        bindings: Sequence[BobaValidationInputBindingV1],
        payloads: Sequence[tuple[BobaValidationInputBindingV1, dict[str, Any]]],
        *,
        rendering: bool,
    ) -> _AdapterOutcome:
        binding, payload = payloads[0]
        manifest = payload
        for key in ("render_manifest", "manifest"):
            nested = payload.get(key)
            if isinstance(nested, Mapping):
                manifest = dict(nested)
                break
        renders = [
            _mapping(item)
            for item in _sequence(
                manifest.get("renders")
                or manifest.get("outputs")
                or manifest.get("artifacts")
            )
            if isinstance(item, Mapping)
        ]
        references: list[str] = []
        for item in renders:
            reference = str(
                item.get("storage_key")
                or item.get("output_key")
                or item.get("artifact_path")
                or item.get("path")
                or ""
            ).strip()
            if reference:
                references.append(reference.replace("\\", "/"))
        assertions: dict[str, bool | None] = {
            "manifest_is_object": bool(manifest),
            "manifest_has_entries": bool(renders) if rendering else bool(renders or manifest),
        }
        existing = 0
        digest_matches = 0
        unsafe_references: list[str] = []
        for index, reference in enumerate(references[:128]):
            try:
                validated = _validate_storage_reference(reference)
                storage_candidate = (
                    self.storage_root
                    / Path(*PurePosixPath(validated).parts)
                ).resolve(strict=False)
                local_candidate = (
                    self._resolve_binding_target(binding).parent
                    / Path(*PurePosixPath(validated).parts)
                ).resolve(strict=False)
                candidate = (
                    storage_candidate
                    if storage_candidate.is_file()
                    else local_candidate
                )
                if _path_is_within(candidate, self.allowed_input_roots) and candidate.is_file():
                    existing += 1
                    declared = str(renders[index].get("checksum") or "")
                    if not declared:
                        digest_matches += 1
                    else:
                        digest_matches += int(
                            declared.removeprefix("sha256:").casefold()
                            == _sha256_file(candidate)
                        )
                else:
                    unsafe_references.append(reference)
            except (ValidationError, OSError):
                unsafe_references.append(reference)
        if references:
            assertions["referenced_artifacts_exist"] = existing == len(references)
            assertions["referenced_artifact_digests_match"] = (
                digest_matches == len(references)
            )
        if rendering:
            assertions["render_entries_have_mp4"] = bool(references) and all(
                Path(item).suffix.casefold() == ".mp4" for item in references
            )
        expected_count = _int_value(check.expected_values.get("minimum_entry_count"), 1)
        assertions["minimum_entry_count"] = len(renders) >= int(expected_count or 1)
        return self._assertion_outcome(
            summary_pass="Manifest structure and every referenced local artifact validate.",
            summary_fail="Manifest structure or referenced local artifacts do not validate.",
            assertions=assertions,
            measured={
                "entry_count": len(renders),
                "reference_count": len(references),
                "existing_reference_count": existing,
                "digest_match_count": digest_matches,
                "unsafe_or_missing_reference_count": len(unsafe_references),
            },
            expected={
                "minimum_entry_count": int(expected_count or 1),
                "all_references_exist": True,
                "all_digests_match": True,
            },
            source_type="artifact_check",
        )

    def _validate_workflow_graph_payload(
        self,
        payloads: Sequence[tuple[BobaValidationInputBindingV1, dict[str, Any]]],
    ) -> _AdapterOutcome:
        payload = payloads[0][1]
        raw_stages = _sequence(
            payload.get("stage_definitions")
            or _mapping(payload.get("workflow_controller")).get(
                "stage_definitions"
            )
        )
        if not raw_stages:
            return _AdapterOutcome(
                status="failed",
                summary="Workflow stage definitions are missing.",
                assertion_results={"stage_definitions_present": False},
                measured_values={"stage_count": 0},
                expected_values={"stage_definitions_present": True},
                failed_assertions=["stage_definitions_present"],
                unavailable_assertions=[],
                source_type="workflow_check",
                confidence=1.0,
            )
        try:
            stages = [
                BobaWorkflowStageDefinitionV1.model_validate(item)
                for item in raw_stages
            ]
            snapshot = _mapping(
                payload.get("workflow_definition")
                or payload.get("workflow_definition_snapshot")
            )
            start_stage_id = str(
                snapshot.get("start_stage_id")
                or payload.get("start_stage_id")
                or "workflow_created"
            )
            required_stage_ids = [
                str(item)
                for item in _sequence(
                    snapshot.get("required_stage_ids")
                    or payload.get("required_stage_ids")
                )
            ] or [item.stage_id for item in stages if not item.terminal]
            graph_digest = validate_workflow_graph(
                stages,
                start_stage_id=start_stage_id,
                required_stage_ids=required_stage_ids,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            return _AdapterOutcome(
                status="failed",
                summary=f"Workflow graph validation failed: {_bounded_text(exc)}",
                assertion_results={"workflow_graph_valid": False},
                measured_values={"stage_count": len(raw_stages)},
                expected_values={"workflow_graph_valid": True},
                failed_assertions=["workflow_graph_valid"],
                unavailable_assertions=[],
                source_type="workflow_check",
                confidence=1.0,
            )
        return _AdapterOutcome(
            status="passed",
            summary="Workflow graph is acyclic, reachable, and internally consistent.",
            assertion_results={"workflow_graph_valid": True},
            measured_values={
                "stage_count": len(stages),
                "workflow_graph_digest": graph_digest,
            },
            expected_values={"workflow_graph_valid": True},
            failed_assertions=[],
            unavailable_assertions=[],
            source_type="workflow_check",
            confidence=1.0,
        )

    def _validate_workflow_transition(
        self,
        check: BobaValidationPlanCheckV1,
        payloads: Sequence[tuple[BobaValidationInputBindingV1, dict[str, Any]]],
    ) -> _AdapterOutcome:
        payload = payloads[0][1]
        transition = _mapping(
            payload.get("transition")
            or payload.get("transition_decision")
            or payload
        )
        current = str(
            transition.get("current_status")
            or transition.get("from_status")
            or transition.get("status")
            or ""
        )
        next_status = str(
            transition.get("next_status")
            or transition.get("to_status")
            or transition.get("decision")
            or ""
        )
        expected_current = str(check.expected_values.get("current_status") or "")
        expected_next = str(check.expected_values.get("next_status") or "")
        assertions = {
            "transition_present": bool(current or next_status),
            "current_status_matches": (
                not expected_current or current == expected_current
            ),
            "next_status_matches": not expected_next or next_status == expected_next,
            "automatic_transition_not_authorized": transition.get(
                "apply_automatically"
            )
            is not True,
        }
        return self._assertion_outcome(
            summary_pass=(
                "Workflow transition evidence matches the expected state without "
                "applying it."
            ),
            summary_fail="Workflow transition evidence is missing, mismatched, or auto-applying.",
            assertions=assertions,
            measured={"current_status": current, "next_status": next_status},
            expected={
                "current_status": expected_current or "present",
                "next_status": expected_next or "present",
                "apply_automatically": False,
            },
            source_type="workflow_check",
        )

    def _validate_checkpoint(
        self,
        check: BobaValidationPlanCheckV1,
        payloads: Sequence[tuple[BobaValidationInputBindingV1, dict[str, Any]]],
    ) -> _AdapterOutcome:
        payload = payloads[0][1]
        checkpoint = _mapping(payload.get("checkpoint") or payload)
        expected_stage = str(check.expected_values.get("stage") or "")
        actual_stage = str(
            checkpoint.get("stage")
            or checkpoint.get("stage_id")
            or checkpoint.get("engine")
            or ""
        )
        digest_value = str(
            checkpoint.get("artifact_digest")
            or checkpoint.get("checksum")
            or checkpoint.get("digest")
            or ""
        ).removeprefix("sha256:")
        assertions = {
            "checkpoint_object_present": bool(checkpoint),
            "checkpoint_identity_present": bool(
                checkpoint.get("project_id")
                or checkpoint.get("checkpoint_id")
                or checkpoint.get("artifact_path")
            ),
            "checkpoint_stage_matches": not expected_stage
            or actual_stage == expected_stage,
            "checkpoint_digest_well_formed": not digest_value
            or bool(_DIGEST.fullmatch(digest_value.casefold())),
            "restore_not_performed": True,
        }
        return self._assertion_outcome(
            summary_pass="Checkpoint metadata is readable and internally consistent.",
            summary_fail="Checkpoint metadata is missing or inconsistent.",
            assertions=assertions,
            measured={
                "stage": actual_stage,
                "digest_present": bool(digest_value),
                "restore_performed": False,
            },
            expected={
                "stage": expected_stage or "present",
                "restore_performed": False,
            },
            source_type="artifact_check",
        )

    def _caption_events(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        candidates = (
            payload.get("captions"),
            payload.get("subtitles"),
            payload.get("segments"),
            payload.get("cues"),
            _mapping(payload.get("timeline")).get("captions"),
            _mapping(payload.get("metadata")).get("captions"),
        )
        for candidate in candidates:
            events = [
                _mapping(item)
                for item in _sequence(candidate)
                if isinstance(item, Mapping)
            ]
            if events:
                return events
        return []

    def _validate_captions(
        self,
        check: BobaValidationPlanCheckV1,
        payloads: Sequence[tuple[BobaValidationInputBindingV1, dict[str, Any]]],
    ) -> _AdapterOutcome:
        events = self._caption_events(payloads[0][1])
        expected_duration = _float_value(
            check.expected_values.get("duration_seconds"),
        )
        tolerance = float(check.tolerance.get("seconds", 0.15))
        normalized: list[tuple[float, float, str, dict[str, Any]]] = []
        malformed = 0
        for event in events:
            start = _float_value(
                event.get("start")
                or event.get("start_time")
                or event.get("start_seconds")
            )
            end = _float_value(
                event.get("end")
                or event.get("end_time")
                or event.get("end_seconds")
            )
            text_value = str(event.get("text") or event.get("content") or "").strip()
            if start is None or end is None or end <= start or not text_value:
                malformed += 1
                continue
            normalized.append((start, end, text_value, event))
        timing_valid = malformed == 0 and all(
            start >= 0
            and (
                expected_duration is None
                or end <= expected_duration + tolerance
            )
            for start, end, _text_value, _event in normalized
        )
        bounds_valid = all(
            self._caption_event_in_bounds(event)
            for _start, _end, _text_value, event in normalized
        )
        assertions: dict[str, bool | None] = {
            "captions_present": bool(events),
            "captions_well_formed": bool(normalized) and malformed == 0,
        }
        if check.validator_id == "captions.timing":
            assertions["caption_timing_valid"] = timing_valid
        if check.validator_id == "captions.bounds":
            assertions["caption_bounds_valid"] = bounds_valid
        return self._assertion_outcome(
            summary_pass="Caption events satisfy the requested schema, timing, and bounds checks.",
            summary_fail="Caption events are missing, malformed, mistimed, or outside bounds.",
            assertions=assertions,
            measured={
                "caption_count": len(events),
                "valid_caption_count": len(normalized),
                "malformed_caption_count": malformed,
                "maximum_end": max(
                    (item[1] for item in normalized),
                    default=0.0,
                ),
            },
            expected={
                "caption_count_minimum": 1,
                "duration_seconds": expected_duration,
                "bounds_normalized": True,
            },
            source_type="schema_check",
        )

    @staticmethod
    def _caption_event_in_bounds(event: Mapping[str, Any]) -> bool:
        position = _mapping(event.get("position") or event.get("bounds"))
        values = {
            key: _float_value(position.get(key) if position else event.get(key))
            for key in ("x", "y", "width", "height")
        }
        if all(value is None for value in values.values()):
            return True
        x_value = values["x"] if values["x"] is not None else 0.0
        y_value = values["y"] if values["y"] is not None else 0.0
        width = values["width"] if values["width"] is not None else 0.0
        height = values["height"] if values["height"] is not None else 0.0
        return bool(
            0.0 <= x_value <= 1.0
            and 0.0 <= y_value <= 1.0
            and 0.0 <= width <= 1.0
            and 0.0 <= height <= 1.0
            and x_value + width <= 1.0
            and y_value + height <= 1.0
        )

    def _validate_face_motion(
        self,
        check: BobaValidationPlanCheckV1,
        payloads: Sequence[tuple[BobaValidationInputBindingV1, dict[str, Any]]],
    ) -> _AdapterOutcome:
        payload = payloads[0][1]
        plan = _mapping(
            payload.get("face_tracking_plan")
            or _mapping(payload.get("editing_v2")).get("face_tracking_plan")
            or payload
        )
        detections = [
            _mapping(item)
            for item in _sequence(
                plan.get("detections")
                or plan.get("tracked_faces")
                or payload.get("face_detections")
            )
            if isinstance(item, Mapping)
        ]
        keyframes = [
            _mapping(item)
            for item in _sequence(plan.get("crop_keyframes"))
            if isinstance(item, Mapping)
        ]
        motion_effects = [
            _mapping(item)
            for item in _sequence(
                plan.get("motion_effects") or payload.get("motion_effects")
            )
            if isinstance(item, Mapping)
        ]
        source_width = _float_value(
            plan.get("source_width")
            or check.expected_values.get("source_width"),
            1920.0,
        )
        source_height = _float_value(
            plan.get("source_height")
            or check.expected_values.get("source_height"),
            1080.0,
        )
        thresholds = FaceMotionValidationThresholdsV1()
        metrics = crop_motion_metrics(keyframes)
        safety = evaluate_face_crop_safety(
            detections=detections,
            crop_keyframes=keyframes,
            source_width=float(source_width or 1920.0),
            source_height=float(source_height or 1080.0),
            safe_zone_margin_ratio=thresholds.safe_zone_margin_ratio,
            motion_effects=motion_effects,
        )
        mode = str(plan.get("mode") or "center_fallback")
        fallback_reason = str(plan.get("fallback_reason") or "")
        fallback_valid = (
            mode != "center_fallback"
            or bool(fallback_reason)
            or not detections
        )
        assertions = {
            "crop_keyframes_present": bool(keyframes)
            if mode != "center_fallback"
            else True,
            "face_safety_evaluated": bool(safety.get("evaluated"))
            if detections and keyframes
            else mode == "center_fallback",
            "face_inside_safe_zone": (
                float(safety.get("face_inside_safe_zone_ratio") or 0.0)
                >= thresholds.minimum_face_inside_safe_zone_ratio
                if safety.get("evaluated")
                else mode == "center_fallback"
            ),
            "face_cutoff_absent": safety.get("face_cutoff_detected") is not True,
            "jitter_within_limit": (
                metrics["jitter_score"] <= thresholds.maximum_jitter_score
            ),
            "crop_speed_within_limit": (
                metrics["max_crop_shift_per_second"]
                <= thresholds.maximum_crop_shift_per_second
            ),
            "fallback_honest": fallback_valid,
        }
        return self._assertion_outcome(
            summary_pass="Face/motion plan is stable, safe, and honest about fallback.",
            summary_fail="Face/motion plan is unsafe, unstable, or misleading.",
            assertions=assertions,
            measured={
                "mode": mode,
                "detection_count": len(detections),
                "keyframe_count": len(keyframes),
                **metrics,
                **safety,
            },
            expected={
                "maximum_jitter_score": thresholds.maximum_jitter_score,
                "maximum_crop_shift_per_second": (
                    thresholds.maximum_crop_shift_per_second
                ),
                "minimum_face_inside_safe_zone_ratio": (
                    thresholds.minimum_face_inside_safe_zone_ratio
                ),
            },
            source_type="media_validator",
        )

    def _validate_multi_speaker(
        self,
        check: BobaValidationPlanCheckV1,
        payloads: Sequence[tuple[BobaValidationInputBindingV1, dict[str, Any]]],
    ) -> _AdapterOutcome:
        payload = payloads[0][1]
        plan = _mapping(
            payload.get("multi_speaker_layout")
            or payload.get("face_tracking_plan")
            or payload
        )
        regions = [
            _mapping(item)
            for item in _sequence(plan.get("layout_regions"))
            if isinstance(item, Mapping)
        ]
        assignments = [
            _mapping(item)
            for item in _sequence(
                plan.get("subject_region_assignments")
                or plan.get("assignments")
            )
            if isinstance(item, Mapping)
        ]
        thresholds = MultiSpeakerLayoutValidationThresholdsV1()
        motion = layout_motion_metrics(regions)
        safety = evaluate_assigned_subject_regions(assignments)
        strategy = str(
            plan.get("mode") or plan.get("layout_strategy") or "center_fallback"
        )
        fallback_reason = str(plan.get("fallback_reason") or "")
        fallback_used = strategy in {
            "center_fallback",
            "multi_face_safe_frame",
        }
        assertions = {
            "layout_or_honest_fallback": bool(regions)
            or (fallback_used and bool(fallback_reason)),
            "subject_regions_safe": (
                float(safety.get("face_inside_region_ratio") or 0.0)
                >= thresholds.minimum_face_inside_region_ratio
                if safety.get("evaluated")
                else fallback_used
            ),
            "subject_cutoff_absent": safety.get("subject_cutoff_detected") is not True,
            "layout_jitter_within_limit": (
                motion["layout_jitter_score"]
                <= thresholds.maximum_layout_jitter_score
            ),
            "layout_speed_within_limit": (
                motion["max_region_shift_per_second"]
                <= thresholds.maximum_region_shift_per_second
            ),
            "active_speaker_evidence_honest": (
                strategy != "active_speaker_focus"
                or bool(plan.get("active_speaker_events"))
            ),
        }
        return self._assertion_outcome(
            summary_pass="Multi-speaker layout is stable, safe, and evidence-backed.",
            summary_fail="Multi-speaker layout is unsafe, unstable, or lacks claimed evidence.",
            assertions=assertions,
            measured={
                "strategy": strategy,
                "layout_region_count": len(regions),
                "assignment_count": len(assignments),
                **motion,
                **safety,
            },
            expected={
                "minimum_face_inside_region_ratio": (
                    thresholds.minimum_face_inside_region_ratio
                ),
                "maximum_layout_jitter_score": (
                    thresholds.maximum_layout_jitter_score
                ),
                "maximum_region_shift_per_second": (
                    thresholds.maximum_region_shift_per_second
                ),
            },
            source_type="media_validator",
        )

    def _validate_tool_health(
        self,
        check: BobaValidationPlanCheckV1,
    ) -> _AdapterOutcome:
        tool_id = str(check.expected_values.get("tool_id") or "").casefold()
        fixed_tools = {
            "python": sys.executable,
            "ffprobe": shutil.which(self.ffprobe_binary),
            "ffmpeg": shutil.which(self.ffmpeg_binary),
            "npm": shutil.which("npm"),
        }
        if tool_id not in fixed_tools:
            return _AdapterOutcome(
                status="unavailable",
                summary="The requested tool is not in the fixed health registry.",
                assertion_results={"registered_tool": None},
                measured_values={"tool_id": tool_id},
                expected_values={"registered_tool": True},
                failed_assertions=[],
                unavailable_assertions=["registered_tool"],
                source_type="internal_validator",
                confidence=1.0,
            )
        available = bool(fixed_tools[tool_id])
        return self._assertion_outcome(
            summary_pass=f"Registered local tool {tool_id} is available.",
            summary_fail=f"Registered local tool {tool_id} is unavailable.",
            assertions={"registered_tool_available": available},
            measured={"tool_id": tool_id, "available": available},
            expected={"available": True},
            source_type="internal_validator",
        )

    @staticmethod
    def _assertion_outcome(
        *,
        summary_pass: str,
        summary_fail: str,
        assertions: Mapping[str, bool | None],
        measured: Mapping[str, Any],
        expected: Mapping[str, Any],
        source_type: BobaValidationEvidenceSourceTypeV1,
    ) -> _AdapterOutcome:
        failed = [key for key, value in assertions.items() if value is False]
        unavailable = [key for key, value in assertions.items() if value is None]
        status: BobaValidationCheckStatusV1 = (
            "failed" if failed else "unavailable" if unavailable else "passed"
        )
        return _AdapterOutcome(
            status=status,
            summary=summary_pass if status == "passed" else summary_fail,
            assertion_results=dict(assertions),
            measured_values=_json_safe(dict(measured)),
            expected_values=_json_safe(dict(expected)),
            failed_assertions=failed,
            unavailable_assertions=unavailable,
            source_type=source_type,
            confidence=1.0,
        )


__all__ = [
    "BobaValidationCheckRunV1",
    "BobaValidationEnvironmentSnapshotV1",
    "BobaValidationEventV1",
    "BobaValidationEvidenceV1",
    "BobaValidationExecutionPolicyV1",
    "BobaValidationHandoffV1",
    "BobaValidationIncidentV1",
    "BobaValidationInputBindingV1",
    "BobaValidationLeaseV1",
    "BobaValidationPlanCheckV1",
    "BobaValidationPlanV1",
    "BobaValidationResourceBudgetV1",
    "BobaValidationResultV1",
    "BobaValidationRunV1",
    "BobaValidationSuiteDecisionV1",
    "BobaValidatorDescriptorV1",
    "BobaValidatorRegistrySnapshotV1",
    "BobaValidatorRunnerSetV1",
    "BobaValidatorRunnerSignalUsageV1",
    "BobaValidatorRunnerSummaryV1",
    "BobaValidatorRunnerV1",
    "build_fixed_validator_adapter_registry",
    "build_fixed_validator_registry",
    "build_validation_execution_policy",
    "build_validation_resource_budget",
    "calculate_validation_idempotency_key",
    "calculate_validation_plan_digest",
    "capture_validation_environment_snapshot",
    "sanitize_validator_export",
    "validate_validator_plan_dependencies",
]

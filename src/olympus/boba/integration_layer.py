"""Typed, bounded interoperability for registered BOBA module operations.

BOBA Integration Layer V1 validates and transports decisions made by other
modules. It never chooses an action, grants approval, changes Safety Gate
decisions, invokes arbitrary code, or directly executes commands, Git, FFmpeg,
workflow recovery, publication, deployment, or external access.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import ConfigDict, Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore

BobaIntegrationImplementationStatusV1 = Literal[
    "available",
    "degraded",
    "unavailable",
    "future",
    "blocked",
    "unknown",
]
BobaIntegrationHealthStatusV1 = Literal[
    "healthy",
    "degraded",
    "unavailable",
    "incompatible",
    "unverified",
    "blocked",
    "unknown",
]
BobaIntegrationOperationClassV1 = Literal[
    "read_only",
    "planning",
    "approved_execution",
    "approved_rollback",
    "metadata_reset",
    "export",
    "future_gated",
    "prohibited",
]
BobaIntegrationSideEffectClassV1 = Literal[
    "none",
    "BOBA_metadata_only",
    "isolated_generated_state",
    "isolated_code_worktree",
    "recovery_owned_state",
    "unknown",
]
BobaIntegrationEnvelopeTypeV1 = Literal[
    "request",
    "response",
    "event",
    "handoff",
    "failure",
    "approval_reference",
    "safety_reference",
    "unknown",
]
BobaIntegrationResponseStatusV1 = Literal[
    "succeeded",
    "failed",
    "blocked",
    "rejected",
    "timed_out",
    "unavailable",
    "incompatible",
    "duplicate_reused",
    "future_gated",
    "unknown",
]
BobaIntegrationCompatibilityStatusV1 = Literal[
    "compatible",
    "compatible_with_safe_normalization",
    "incompatible",
    "migration_required",
    "unavailable",
    "unknown",
]
BobaIntegrationDependencyStatusV1 = Literal[
    "ready",
    "degraded",
    "missing",
    "stale",
    "malformed",
    "incompatible",
    "blocked",
    "unknown",
]
BobaIntegrationTransactionStateV1 = Literal[
    "created",
    "validating",
    "blocked",
    "ready",
    "routing",
    "target_running",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "duplicate_reused",
    "future_gated",
    "unknown",
]
BobaIntegrationEventTypeV1 = Literal[
    "request_received",
    "request_validated",
    "compatibility_checked",
    "dependencies_checked",
    "approval_checked",
    "safety_checked",
    "idempotency_checked",
    "routing_started",
    "target_started",
    "target_completed",
    "target_failed",
    "transaction_blocked",
    "transaction_completed",
    "response_reused",
    "future_action_blocked",
    "unknown",
]
BobaIntegrationFailureClassV1 = Literal[
    "invalid_request",
    "unknown_module",
    "unknown_operation",
    "schema_incompatible",
    "missing_dependency",
    "stale_artifact",
    "malformed_artifact",
    "project_mismatch",
    "run_mismatch",
    "approval_missing",
    "approval_invalid",
    "approval_expired",
    "safety_decision_missing",
    "safety_decision_invalid",
    "safety_decision_expired",
    "rights_blocked",
    "idempotency_conflict",
    "target_unavailable",
    "target_rejected",
    "target_failed",
    "target_timed_out",
    "transaction_conflict",
    "future_gated",
    "prohibited",
    "internal_integration_error",
    "unknown",
]

IntegrationOperationResult: TypeAlias = Mapping[str, Any] | BobaContract
IntegrationOperationHandler: TypeAlias = Callable[
    ["BobaIntegrationRequestV1"],
    IntegrationOperationResult | Awaitable[IntegrationOperationResult],
]
IntegrationProjectExists: TypeAlias = Callable[[str], bool | Awaitable[bool]]
IntegrationContextProvider: TypeAlias = Callable[
    [str, "BobaIntegrationRequestV1"],
    Mapping[str, Any] | Awaitable[Mapping[str, Any]],
]

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
_DIGEST = re.compile(r"^[a-fA-F0-9]{64}$")
_EXTERNAL_URL = re.compile(r"(?i)\b(?:https?|ftp)://")
_WINDOWS_PATH = re.compile(r"(?i)(?:^|[\s\"'])?[A-Z]:[\\/][^\s\"']+")
_UNC_PATH = re.compile(r"^(?:\\\\|//)[^\\/]+[\\/]")
_PRIVATE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users|root)/[^\s\"']+")
_SECRET_KEY = re.compile(
    r"(?i)(?:secret|token|password|credential|cookie|authorization|api[_-]?key)"
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|"
    r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"
    r")"
)
_RAW_COMMAND = re.compile(
    r"(?i)(?:^|[\s;&|])(?:powershell(?:\.exe)?|cmd(?:\.exe)?|bash|sh|"
    r"git|ffmpeg|ffprobe|python(?:3|\.exe)?)\s+(?:-|/|[A-Za-z])"
)
_RAW_PATCH = re.compile(r"(?m)^(?:diff --git |--- [ab]/|\+\+\+ [ab]/|@@ .+ @@)")
_COMMAND_KEYS = frozenset(
    {
        "command",
        "commands",
        "shell_command",
        "git_command",
        "ffmpeg_command",
        "callable",
        "callable_path",
        "function",
        "function_name",
        "import_path",
        "module_path",
        "dynamic_import",
    }
)
_RAW_KEYS = frozenset(
    {
        "raw_patch",
        "patch_content",
        "unified_diff",
        "diff_content",
        "complete_patch",
        "raw_media",
        "source_media",
        "media_bytes",
        "stdout",
        "stderr",
        "command_log",
        "full_command_log",
        "full_command_logs",
        "full_log",
        "full_logs",
    }
)
_SAFETY_CRITICAL_FIELDS = frozenset(
    {
        "project_id",
        "run_id",
        "target_module_id",
        "target_operation_id",
        "approval_binding_id",
        "safety_binding_id",
        "project_snapshot_digest",
        "request_digest",
        "execution_scope",
        "authority",
    }
)
_MAX_PAYLOAD_BYTES = 24_000


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *values: Any) -> str:
    return f"{prefix}_{_digest(values)[:24]}"


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


def _text(value: Any, *, maximum: int = 900) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    text = _SECRET_VALUE.sub("[REDACTED]", text)
    text = _EXTERNAL_URL.sub("[external-url]", text)
    text = _WINDOWS_PATH.sub("[private-path]", text)
    text = _PRIVATE_POSIX_PATH.sub("[private-path]", text)
    if _RAW_COMMAND.search(text):
        text = "Unsafe command details were omitted."
    if _RAW_PATCH.search(text):
        text = "Raw patch details were omitted."
    return text[:maximum]


def _unique(values: Sequence[Any], *, limit: int = 64, maximum: int = 900) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value, maximum=maximum)
        if item and item not in seen:
            seen.add(item)
            result.append(item)
            if len(result) >= limit:
                break
    return result


def _json_value(value: Any) -> Any:
    if isinstance(value, BobaContract):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise ValidationError("Integration payload contains a non-JSON value.")


def sanitize_integration_export(value: Any) -> Any:
    """Return bounded JSON-safe integration metadata without sensitive material."""

    if isinstance(value, BobaContract):
        return sanitize_integration_export(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:256]:
            key = _text(raw_key, maximum=160)
            folded = key.casefold()
            if _SECRET_KEY.search(key):
                result[key] = "[REDACTED]"
            elif folded in _COMMAND_KEYS | _RAW_KEYS:
                result[key] = "[OMITTED]"
            else:
                result[key] = sanitize_integration_export(item)
        return result
    if isinstance(value, list | tuple | set):
        return [sanitize_integration_export(item) for item in list(value)[:512]]
    if isinstance(value, str):
        return _text(value, maximum=2_000)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _text(value)


def _validate_bounded_payload(value: Any, *, path: str = "payload") -> dict[str, Any]:
    payload = _json_value(value)
    if not isinstance(payload, dict):
        raise ValidationError("Integration bounded payload must be an object.")
    encoded = _canonical(payload).encode("utf-8")
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise ValidationError("Integration bounded payload exceeds the V1 size limit.")

    reject_request_authority = path.startswith(("payload", "request"))

    def inspect_value(item: Any, item_path: str) -> None:
        if isinstance(item, Mapping):
            for raw_key, nested in item.items():
                key = str(raw_key)
                folded = key.casefold()
                if reject_request_authority and _SECRET_KEY.search(key):
                    raise ValidationError(
                        f"Integration request rejects secret material at {item_path}."
                    )
                if reject_request_authority and folded in _COMMAND_KEYS:
                    raise ValidationError(
                        f"Integration request rejects arbitrary invocation at {item_path}."
                    )
                if reject_request_authority and folded in _RAW_KEYS:
                    raise ValidationError(
                        f"Integration request rejects raw unbounded material at {item_path}."
                    )
                if (
                    reject_request_authority
                    and folded in _SAFETY_CRITICAL_FIELDS
                ):
                    raise ValidationError(
                        f"Integration request rejects authority override at {item_path}."
                    )
                inspect_value(nested, f"{item_path}.{key}")
        elif isinstance(item, list):
            for index, nested in enumerate(item):
                inspect_value(nested, f"{item_path}[{index}]")
        elif isinstance(item, str):
            if reject_request_authority and _SECRET_VALUE.search(item):
                raise ValidationError("Integration request rejects secret material.")
            if reject_request_authority and _RAW_COMMAND.search(item):
                raise ValidationError("Integration request rejects raw commands.")
            if reject_request_authority and _RAW_PATCH.search(item):
                raise ValidationError("Integration request rejects raw patches.")
            if _EXTERNAL_URL.search(item):
                raise ValidationError("Integration request rejects external URLs.")
            if _WINDOWS_PATH.search(item) or _PRIVATE_POSIX_PATH.search(item):
                raise ValidationError("Integration request rejects private absolute paths.")
            if _UNC_PATH.search(item):
                raise ValidationError("Integration request rejects UNC paths.")
            normalized = item.replace("\\", "/")
            if any(part == ".." for part in normalized.split("/")):
                raise ValidationError("Integration request rejects path traversal.")

    inspect_value(payload, path)
    return payload


def _validate_storage_reference(reference: str) -> str:
    value = " ".join(reference.replace("\x00", " ").split())
    if not value:
        return ""
    if _EXTERNAL_URL.search(value):
        raise ValidationError("External artifact references are not allowed.")
    if _WINDOWS_PATH.search(value) or _PRIVATE_POSIX_PATH.search(value):
        raise ValidationError("Private absolute artifact paths are not allowed.")
    if _UNC_PATH.search(value):
        raise ValidationError("UNC artifact paths are not allowed.")
    normalized = value.replace("\\", "/").lstrip("/")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ValidationError("Artifact reference contains invalid path traversal.")
    return normalized[:500]


def calculate_integration_request_digest(value: Mapping[str, Any] | BobaContract) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BobaContract) else dict(value)
    payload.pop("request_digest", None)
    payload.pop("created_at", None)
    return _digest(sanitize_integration_export(payload))


class BobaIntegrationRegistrySnapshotV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = Field(default="boba_integration_registry_v1", max_length=80)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    module_ids: list[str] = Field(default_factory=list, max_length=96)
    operation_ids: list[str] = Field(default_factory=list, max_length=512)
    module_versions: dict[str, str] = Field(default_factory=dict, max_length=96)
    schema_versions: dict[str, list[str]] = Field(default_factory=dict, max_length=96)
    unavailable_module_ids: list[str] = Field(default_factory=list, max_length=96)
    future_module_ids: list[str] = Field(default_factory=list, max_length=96)
    registry_sha256: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationModuleDescriptorV1(BobaContract):
    module_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=240)
    module_version: str = Field(default="1", max_length=80)
    implementation_status: BobaIntegrationImplementationStatusV1
    supported_schema_versions: list[str] = Field(default_factory=list, max_length=32)
    operation_ids: list[str] = Field(default_factory=list, max_length=64)
    read_only: bool = False
    planning_capable: bool = False
    execution_capable: bool = False
    requires_rights_gate: bool = False
    requires_target_approval: bool = False
    requires_safety_gate: bool = False
    requires_checkpoint: bool = False
    implementation_import_path: str = Field(default="", max_length=240)
    artifact_path_pattern: str = Field(default="", max_length=500)
    dependency_module_ids: list[str] = Field(default_factory=list, max_length=32)
    health_status: BobaIntegrationHealthStatusV1 = "unverified"
    health_reason: str = Field(default="", max_length=700)
    known_limitations: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationOperationDescriptorV1(BobaContract):
    operation_id: str = Field(min_length=1, max_length=240)
    module_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=240)
    operation_class: BobaIntegrationOperationClassV1
    side_effect_class: BobaIntegrationSideEffectClassV1
    request_schema_id: str = Field(default="boba.integration.request", max_length=160)
    response_schema_id: str = Field(default="boba.integration.response", max_length=160)
    supported_schema_versions: list[str] = Field(
        default_factory=lambda: ["1.0"],
        max_length=16,
    )
    required_artifact_types: list[str] = Field(default_factory=list, max_length=64)
    optional_artifact_types: list[str] = Field(default_factory=list, max_length=64)
    dependency_operation_ids: list[str] = Field(default_factory=list, max_length=32)
    target_approval_required: bool = False
    required_approval_type: str = Field(default="", max_length=160)
    safety_gate_required: bool = False
    rights_gate_required: bool = False
    checkpoint_required: bool = False
    idempotency_required: bool = False
    future_gated: bool = False
    prohibited: bool = False
    timeout_seconds: int = Field(default=60, ge=1, le=3_600)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationArtifactReferenceV1(BobaContract):
    artifact_reference_id: str = Field(min_length=1, max_length=180)
    artifact_type: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    producer_module_id: str = Field(min_length=1, max_length=160)
    producer_record_id: str = Field(default="", max_length=180)
    schema_id: str = Field(min_length=1, max_length=160)
    schema_version: str = Field(min_length=1, max_length=80)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    sanitized_storage_reference: str = Field(default="", max_length=500)
    artifact_digest: str = Field(default="", max_length=64)
    immutable: bool = True
    required: bool = True
    available: bool = True
    stale: bool = False
    malformed: bool = False
    rights_relevant: bool = False
    safety_relevant: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationApprovalBindingV1(BobaContract):
    approval_binding_id: str = Field(min_length=1, max_length=180)
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=240)
    approval_record_id: str = Field(min_length=1, max_length=180)
    approval_type: str = Field(min_length=1, max_length=160)
    approval_digest: str = Field(min_length=64, max_length=64)
    approved_project_id: str = Field(min_length=1, max_length=128)
    approved_run_id: str = Field(default="", max_length=180)
    approved_plan_id: str = Field(default="", max_length=180)
    approved_strategy_id: str = Field(default="", max_length=180)
    approved_artifact_digest: str = Field(default="", max_length=64)
    approved_parameters_digest: str = Field(default="", max_length=64)
    approval_expires_at: str | None = Field(default=None, max_length=80)
    explicit_confirmation: bool = False
    exact_match_required: bool = True
    current_match_status: Literal[
        "matched",
        "mismatched",
        "expired",
        "missing",
        "unknown",
    ] = "unknown"
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationSafetyBindingV1(BobaContract):
    safety_binding_id: str = Field(min_length=1, max_length=180)
    safety_decision_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    decision: str = Field(min_length=1, max_length=120)
    request_digest: str = Field(min_length=64, max_length=64)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    policy_snapshot_digest: str = Field(min_length=64, max_length=64)
    decision_created_at: str = Field(min_length=1, max_length=80)
    decision_expires_at: str = Field(min_length=1, max_length=80)
    decision_valid: bool = False
    allowed_target_module: str = Field(default="", max_length=160)
    allowed_target_operation: str = Field(default="", max_length=160)
    allowed_scope: list[str] = Field(default_factory=list, max_length=64)
    target_revalidation_required: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationEnvelopeV1(BobaContract):
    envelope_id: str = Field(min_length=1, max_length=180)
    envelope_type: BobaIntegrationEnvelopeTypeV1
    schema_id: str = Field(min_length=1, max_length=160)
    schema_version: str = Field(min_length=1, max_length=80)
    producer_module_id: str = Field(min_length=1, max_length=160)
    producer_module_version: str = Field(default="1", max_length=80)
    consumer_module_id: str = Field(min_length=1, max_length=160)
    consumer_operation_id: str = Field(min_length=1, max_length=240)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    run_id: str = Field(default="", max_length=180)
    correlation_id: str = Field(min_length=1, max_length=180)
    transaction_id: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    expires_at: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=180)
    project_snapshot_digest: str = Field(default="", max_length=64)
    payload_digest: str = Field(min_length=64, max_length=64)
    artifact_references: list[BobaIntegrationArtifactReferenceV1] = Field(
        default_factory=list,
        max_length=64,
    )
    approval_binding: BobaIntegrationApprovalBindingV1 | None = None
    safety_binding: BobaIntegrationSafetyBindingV1 | None = None
    bounded_payload: dict[str, Any] = Field(default_factory=dict, max_length=128)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationRequestV1(BobaContract):
    request_id: str = Field(min_length=1, max_length=180)
    envelope_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(default="", max_length=180)
    requesting_module_id: str = Field(min_length=1, max_length=160)
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=240)
    request_schema_id: str = Field(min_length=1, max_length=160)
    request_schema_version: str = Field(min_length=1, max_length=80)
    request_parameters: dict[str, Any] = Field(default_factory=dict, max_length=128)
    artifact_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    approval_binding_id: str = Field(default="", max_length=180)
    safety_binding_id: str = Field(default="", max_length=180)
    idempotency_key: str = Field(min_length=1, max_length=180)
    expected_response_schema_id: str = Field(min_length=1, max_length=160)
    timeout_seconds: int = Field(default=60, ge=1, le=3_600)
    request_digest: str = Field(min_length=64, max_length=64)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationResponseV1(BobaContract):
    response_id: str = Field(min_length=1, max_length=180)
    request_id: str = Field(min_length=1, max_length=180)
    envelope_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(default="", max_length=180)
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=240)
    status: BobaIntegrationResponseStatusV1
    response_schema_id: str = Field(min_length=1, max_length=160)
    response_schema_version: str = Field(min_length=1, max_length=80)
    output_artifact_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    bounded_result: dict[str, Any] = Field(default_factory=dict, max_length=128)
    result_digest: str = Field(min_length=64, max_length=64)
    idempotency_reused: bool = False
    started_at: str = Field(default_factory=now_iso, max_length=80)
    completed_at: str = Field(default_factory=now_iso, max_length=80)
    failure_id: str = Field(default="", max_length=180)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationCompatibilityCheckV1(BobaContract):
    compatibility_check_id: str = Field(min_length=1, max_length=180)
    transaction_id: str = Field(min_length=1, max_length=180)
    producer_module_id: str = Field(min_length=1, max_length=160)
    consumer_module_id: str = Field(min_length=1, max_length=160)
    schema_id: str = Field(min_length=1, max_length=160)
    producer_schema_version: str = Field(min_length=1, max_length=80)
    supported_consumer_versions: list[str] = Field(default_factory=list, max_length=32)
    compatibility_status: BobaIntegrationCompatibilityStatusV1
    backward_compatible: bool = False
    migration_required: bool = False
    safe_normalization_available: bool = False
    safety_critical_difference: bool = False
    failure_reason: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationDependencyCheckV1(BobaContract):
    dependency_check_id: str = Field(min_length=1, max_length=180)
    transaction_id: str = Field(min_length=1, max_length=180)
    module_id: str = Field(min_length=1, max_length=160)
    operation_id: str = Field(min_length=1, max_length=240)
    required_module_ids: list[str] = Field(default_factory=list, max_length=64)
    available_module_ids: list[str] = Field(default_factory=list, max_length=96)
    unavailable_module_ids: list[str] = Field(default_factory=list, max_length=96)
    required_artifact_ids: list[str] = Field(default_factory=list, max_length=64)
    available_artifact_ids: list[str] = Field(default_factory=list, max_length=64)
    missing_artifact_ids: list[str] = Field(default_factory=list, max_length=64)
    stale_artifact_ids: list[str] = Field(default_factory=list, max_length=64)
    malformed_artifact_ids: list[str] = Field(default_factory=list, max_length=64)
    dependency_status: BobaIntegrationDependencyStatusV1
    blocks_routing: bool = False
    failure_reason: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationIdempotencyRecordV1(BobaContract):
    idempotency_record_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(default="", max_length=180)
    idempotency_key: str = Field(min_length=1, max_length=180)
    operation_id: str = Field(min_length=1, max_length=240)
    request_digest: str = Field(min_length=64, max_length=64)
    first_transaction_id: str = Field(min_length=1, max_length=180)
    latest_transaction_id: str = Field(min_length=1, max_length=180)
    first_seen_at: str = Field(default_factory=now_iso, max_length=80)
    latest_seen_at: str = Field(default_factory=now_iso, max_length=80)
    attempt_count: int = Field(default=1, ge=1, le=100)
    completed: bool = False
    reusable_response_id: str = Field(default="", max_length=180)
    conflicting_request_detected: bool = False
    expires_at: str = Field(min_length=1, max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationTransactionV1(BobaContract):
    transaction_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(default="", max_length=180)
    correlation_id: str = Field(min_length=1, max_length=180)
    request_id: str = Field(min_length=1, max_length=180)
    response_id: str = Field(default="", max_length=180)
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=240)
    operation_class: BobaIntegrationOperationClassV1
    state: BobaIntegrationTransactionStateV1 = "created"
    created_at: str = Field(default_factory=now_iso, max_length=80)
    validated_at: str | None = Field(default=None, max_length=80)
    routed_at: str | None = Field(default=None, max_length=80)
    completed_at: str | None = Field(default=None, max_length=80)
    request_digest: str = Field(min_length=64, max_length=64)
    snapshot_digest: str = Field(default="", max_length=64)
    approval_binding_valid: bool = False
    safety_binding_valid: bool = False
    compatibility_check_ids: list[str] = Field(default_factory=list, max_length=64)
    dependency_check_ids: list[str] = Field(default_factory=list, max_length=64)
    idempotency_record_id: str = Field(default="", max_length=180)
    target_invocation_started: bool = False
    target_invocation_completed: bool = False
    target_independent_revalidation_confirmed: bool = False
    side_effects_reported: list[str] = Field(default_factory=list, max_length=64)
    failure_id: str = Field(default="", max_length=180)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    transaction_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(default="", max_length=180)
    correlation_id: str = Field(min_length=1, max_length=180)
    sequence: int = Field(ge=1)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    event_type: BobaIntegrationEventTypeV1
    severity: Literal["info", "warning", "error", "critical"] = "info"
    module_id: str = Field(min_length=1, max_length=160)
    operation_id: str = Field(min_length=1, max_length=240)
    technical_message: str = Field(min_length=1, max_length=1_200)
    easy_message: str = Field(min_length=1, max_length=1_200)
    confirmed_fact: str = Field(default="", max_length=900)
    assessment: str = Field(default="", max_length=900)
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    requires_attention: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationFailureV1(BobaContract):
    failure_id: str = Field(min_length=1, max_length=180)
    transaction_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(default="", max_length=180)
    failure_class: BobaIntegrationFailureClassV1
    failure_code: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(min_length=1, max_length=1_200)
    source_layer: Literal[
        "integration_layer",
        "autopilot_controller",
        "safety_gate",
        "target_module",
        "rights_permission_gate",
        "unknown",
    ] = "integration_layer"
    source_module_id: str = Field(default="", max_length=160)
    source_operation_id: str = Field(default="", max_length=240)
    retryable: bool = False
    safe_to_retry: bool = False
    requires_reapproval: bool = False
    requires_new_safety_decision: bool = False
    project_state_uncertain: bool = False
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    recommended_target_module: str = Field(default="", max_length=160)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=180)
    transaction_id: str = Field(min_length=1, max_length=180)
    source_module_id: str = Field(min_length=1, max_length=160)
    target_module_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=900)
    required_inputs: list[str] = Field(default_factory=list, max_length=64)
    artifact_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    unresolved_dependencies: list[str] = Field(default_factory=list, max_length=64)
    approval_required: bool = False
    safety_decision_required: bool = False
    human_review_required: bool = False
    allowed_actions: list[str] = Field(default_factory=list, max_length=64)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=64)
    apply_automatically: bool = False
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationSummaryV1(BobaContract):
    registered_module_count: int = Field(default=0, ge=0)
    available_module_count: int = Field(default=0, ge=0)
    degraded_module_count: int = Field(default=0, ge=0)
    unavailable_module_count: int = Field(default=0, ge=0)
    registered_operation_count: int = Field(default=0, ge=0)
    read_only_operation_count: int = Field(default=0, ge=0)
    approved_execution_operation_count: int = Field(default=0, ge=0)
    future_gated_operation_count: int = Field(default=0, ge=0)
    prohibited_operation_count: int = Field(default=0, ge=0)
    total_transaction_count: int = Field(default=0, ge=0)
    succeeded_transaction_count: int = Field(default=0, ge=0)
    blocked_transaction_count: int = Field(default=0, ge=0)
    failed_transaction_count: int = Field(default=0, ge=0)
    incompatible_transaction_count: int = Field(default=0, ge=0)
    idempotent_reuse_count: int = Field(default=0, ge=0)
    idempotency_conflict_count: int = Field(default=0, ge=0)
    approval_block_count: int = Field(default=0, ge=0)
    safety_block_count: int = Field(default=0, ge=0)
    dependency_block_count: int = Field(default=0, ge=0)
    current_registry_snapshot_id: str = Field(default="", max_length=180)
    highest_priority_failure: str = Field(default="", max_length=900)
    required_human_actions: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationSignalUsageV1(BobaContract):
    module_registry_used: bool = False
    operation_registry_used: bool = False
    schema_validation_used: bool = False
    compatibility_validation_used: bool = False
    dependency_validation_used: bool = False
    artifact_reference_validation_used: bool = False
    approval_binding_used: bool = False
    safety_binding_used: bool = False
    idempotency_used: bool = False
    typed_target_invocation_used: bool = False
    event_stream_used: bool = False
    direct_command_execution_used: Literal[False] = False
    direct_git_execution_used: Literal[False] = False
    direct_ffmpeg_execution_used: Literal[False] = False
    arbitrary_dynamic_import_used: Literal[False] = False
    arbitrary_function_invocation_used: Literal[False] = False
    code_modified_directly: Literal[False] = False
    artifact_modified_directly: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_outputs_modified: Literal[False] = False
    checkpoint_restore_used: Literal[False] = False
    workflow_resume_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    service_restart_used: Literal[False] = False
    process_kill_used: Literal[False] = False
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
    destructive_action_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaIntegrationLayerSetV1(BobaContract):
    schema_version: Literal["boba_integration_layer_v1"] = "boba_integration_layer_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    registry_snapshot: BobaIntegrationRegistrySnapshotV1
    module_descriptors: list[BobaIntegrationModuleDescriptorV1] = Field(
        default_factory=list,
        max_length=96,
    )
    operation_descriptors: list[BobaIntegrationOperationDescriptorV1] = Field(
        default_factory=list,
        max_length=512,
    )
    request_envelopes: list[BobaIntegrationEnvelopeV1] = Field(
        default_factory=list,
        max_length=256,
    )
    integration_requests: list[BobaIntegrationRequestV1] = Field(
        default_factory=list,
        max_length=256,
    )
    response_envelopes: list[BobaIntegrationEnvelopeV1] = Field(
        default_factory=list,
        max_length=256,
    )
    integration_responses: list[BobaIntegrationResponseV1] = Field(
        default_factory=list,
        max_length=256,
    )
    artifact_references: list[BobaIntegrationArtifactReferenceV1] = Field(
        default_factory=list,
        max_length=256,
    )
    integration_transactions: list[BobaIntegrationTransactionV1] = Field(
        default_factory=list,
        max_length=512,
    )
    compatibility_checks: list[BobaIntegrationCompatibilityCheckV1] = Field(
        default_factory=list,
        max_length=512,
    )
    dependency_checks: list[BobaIntegrationDependencyCheckV1] = Field(
        default_factory=list,
        max_length=512,
    )
    idempotency_records: list[BobaIntegrationIdempotencyRecordV1] = Field(
        default_factory=list,
        max_length=512,
    )
    integration_events: list[BobaIntegrationEventV1] = Field(
        default_factory=list,
        max_length=2_048,
    )
    integration_failures: list[BobaIntegrationFailureV1] = Field(
        default_factory=list,
        max_length=512,
    )
    integration_handoffs: list[BobaIntegrationHandoffV1] = Field(
        default_factory=list,
        max_length=512,
    )
    integration_summary: BobaIntegrationSummaryV1 = Field(
        default_factory=BobaIntegrationSummaryV1
    )
    signal_usage: BobaIntegrationSignalUsageV1 = Field(
        default_factory=BobaIntegrationSignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=128)


_MODULE_SPECS: dict[str, dict[str, Any]] = {
    "core_brain": {"name": "BOBA Core Brain", "path": "olympus.boba.brain"},
    "memory_system": {
        "name": "BOBA Memory System",
        "path": "olympus.boba.memory_contracts",
    },
    "whole_video_understanding": {
        "name": "Whole Video Understanding",
        "path": "olympus.boba.whole_video",
    },
    "candidate_clip_discovery": {
        "name": "Candidate Clip Discovery",
        "path": "olympus.boba.clip_discovery",
        "deps": ["whole_video_understanding"],
    },
    "clip_ranking": {
        "name": "Clip Ranking Brain",
        "path": "olympus.boba.clip_ranking",
        "deps": ["candidate_clip_discovery"],
    },
    "editorial_decision": {
        "name": "Editorial Decision Engine",
        "path": "olympus.boba.editorial_decision",
        "deps": ["clip_ranking"],
    },
    "explanation_engine": {
        "name": "Explanation Engine",
        "path": "olympus.boba.explanation",
        "deps": ["editorial_decision"],
    },
    "creative_director": {
        "name": "Creative Director",
        "path": "olympus.boba.creative_director",
        "deps": ["editorial_decision"],
    },
    "clip_brief": {
        "name": "Clip Brief Generator",
        "path": "olympus.boba.clip_brief",
        "deps": ["creative_director"],
    },
    "hook_retention": {
        "name": "Hook + Retention Brain",
        "path": "olympus.boba.hook_retention",
        "deps": ["clip_brief"],
    },
    "caption_motion": {
        "name": "Caption + Motion Brain",
        "path": "olympus.boba.caption_motion",
        "deps": ["clip_brief"],
    },
    "music_mood": {
        "name": "Music Mood Brain",
        "path": "olympus.boba.music_mood",
        "deps": ["clip_brief"],
    },
    "creator_learning": {
        "name": "Creator Learning Loop",
        "path": "olympus.boba.creator_learning",
    },
    "approval_rejection_learning": {
        "name": "Approval / Rejection Learning",
        "path": "olympus.boba.approval_rejection_learning",
    },
    "experimentation": {
        "name": "Experimentation System",
        "path": "olympus.boba.experimentation",
    },
    "performance_feedback": {
        "name": "Performance Feedback Brain",
        "path": "olympus.boba.performance_feedback",
    },
    "content_scout": {
        "name": "Content Scout",
        "path": "olympus.boba.content_scout",
    },
    "research_brain": {
        "name": "Research Brain",
        "path": "olympus.boba.research_brain",
    },
    "trend_topic_watcher": {
        "name": "Trend / Topic Watcher",
        "path": "olympus.boba.trend_topic_watcher",
    },
    "candidate_video_scorer": {
        "name": "Candidate Video Scorer",
        "path": "olympus.boba.candidate_video_scorer",
    },
    "rights_permission_gate": {
        "name": "Rights + Permission Gate",
        "path": "olympus.boba.rights_permission_gate",
    },
    "observer": {"name": "Observer", "path": "olympus.boba.observer", "rights": True},
    "error_doctor": {
        "name": "Error Doctor",
        "path": "olympus.boba.error_doctor",
        "deps": ["observer"],
    },
    "root_cause_analyzer": {
        "name": "Root Cause Analyzer",
        "path": "olympus.boba.root_cause_analyzer",
        "deps": ["error_doctor"],
    },
    "repair_planner": {
        "name": "Repair Planner",
        "path": "olympus.boba.repair_planner",
        "deps": ["root_cause_analyzer"],
        "planning": True,
    },
    "code_surgeon": {
        "name": "Code Surgeon",
        "path": "olympus.boba.code_surgeon",
        "deps": ["repair_planner"],
        "execution": True,
        "approval": True,
        "safety": True,
        "checkpoint": True,
    },
    "tool_recovery_brain": {
        "name": "Tool Recovery Brain",
        "path": "olympus.boba.tool_recovery",
        "deps": ["repair_planner"],
        "execution": True,
        "approval": True,
        "safety": True,
        "checkpoint": True,
    },
    "output_quality_reviewer": {
        "name": "Output Quality Reviewer",
        "path": "olympus.boba.output_quality_reviewer",
        "deps": ["tool_recovery_brain"],
    },
    "autopilot_controller": {
        "name": "Autopilot Controller",
        "path": "olympus.boba.autopilot_controller",
        "deps": ["safety_gate"],
        "planning": True,
    },
    "safety_gate": {
        "name": "Safety Gate",
        "path": "olympus.boba.safety_gate",
        "deps": ["rights_permission_gate"],
        "planning": True,
    },
    "integration_layer": {
        "name": "Integration Layer",
        "path": "olympus.boba.integration_layer",
    },
    "workflow_controller": {
        "name": "Workflow Controller",
        "path": "olympus.boba.workflow_controller",
        "deps": ["integration_layer", "safety_gate"],
        "planning": True,
        "execution": True,
        "approval": True,
        "safety": True,
        "checkpoint": True,
    },
    "olympus_editing": {
        "name": "Olympus Editing",
        "path": "olympus.editing",
        "execution": True,
        "approval": True,
        "safety": True,
        "checkpoint": True,
    },
    "olympus_rendering": {
        "name": "Olympus Rendering",
        "path": "olympus.rendering",
        "execution": True,
        "approval": True,
        "safety": True,
        "checkpoint": True,
    },
    "olympus_optimization": {
        "name": "Olympus Optimization",
        "path": "olympus.optimization",
    },
    "tool_registry_fallback_router": {
        "name": "Tool Registry / Fallback Router",
        "future": True,
    },
    "checkpoint_recovery_manager": {
        "name": "Checkpoint Recovery Manager",
        "future": True,
    },
    "validator_runner": {
        "name": "Validator Runner",
        "path": "olympus.boba.validator_runner_execution",
        "deps": ["integration_layer", "safety_gate"],
        "planning": True,
        "execution": True,
        "approval": True,
        "safety": True,
    },
    "artifact_inspector": {
        "name": "Artifact Inspector",
        "path": "olympus.boba.artifact_inspector",
        "deps": ["integration_layer", "safety_gate"],
    },
    "report_reader": {
        "name": "Report Reader",
        "path": "olympus.boba.report_reader",
        "deps": ["integration_layer", "safety_gate"],
    },
    "final_decision_bus": {
        "name": "Final Decision Bus",
        "path": "olympus.boba.final_decision_bus",
        "deps": ["integration_layer", "safety_gate", "workflow_controller"],
    },
    "error_doctor_review": {
        "name": "Error Doctor Panel",
        "path": "olympus.boba.error_doctor_review",
        "deps": [
            "integration_layer",
            "safety_gate",
            "review_ui",
            "observer",
            "error_doctor",
            "root_cause_analyzer",
            "repair_planner",
            "tool_recovery_brain",
            "validator_runner",
            "artifact_inspector",
            "workflow_controller",
        ],
    },
    "approval_controls": {
        "name": "Approval Reject Buttons",
        "path": "olympus.boba.approval_controls",
        "deps": [
            "integration_layer",
            "safety_gate",
            "review_ui",
            "workflow_controller",
            "final_decision_bus",
            "autopilot_controller",
            "output_quality_reviewer",
        ],
    },
    "repair_plan_review": {
        "name": "Repair Plan Panel",
        "path": "olympus.boba.repair_plan_review",
        "deps": [
            "integration_layer",
            "safety_gate",
            "review_ui",
            "error_doctor_review",
            "repair_planner",
            "root_cause_analyzer",
            "error_doctor",
            "code_surgeon",
            "tool_recovery_brain",
            "validator_runner",
            "artifact_inspector",
            "output_quality_reviewer",
            "workflow_controller",
        ],
    },
    "clip_brief_review": {
        "name": "Clip Brief Panel",
        "path": "olympus.boba.clip_brief_review",
        "deps": [
            "integration_layer",
            "safety_gate",
            "review_ui",
            "candidate_review",
            "clip_brief",
            "editorial_decision",
        ],
    },
    "candidate_review": {
        "name": "Candidate Review Panel",
        "path": "olympus.boba.candidate_review",
        "deps": [
            "integration_layer",
            "safety_gate",
            "review_ui",
            "candidate_clip_discovery",
            "clip_ranking",
            "editorial_decision",
        ],
    },
    "review_ui": {
        "name": "Review UI",
        "path": "olympus.boba.review_ui",
        "deps": [
            "integration_layer",
            "safety_gate",
            "workflow_controller",
            "final_decision_bus",
        ],
    },
    "live_companion": {"name": "Live Companion", "future": True},
}

_PRIMARY_OPERATIONS: dict[str, tuple[str, BobaIntegrationOperationClassV1]] = {
    "core_brain": ("generate", "planning"),
    "memory_system": ("build", "planning"),
    "whole_video_understanding": ("generate", "planning"),
    "candidate_clip_discovery": ("discover", "planning"),
    "clip_ranking": ("rank", "planning"),
    "editorial_decision": ("generate", "planning"),
    "explanation_engine": ("generate", "planning"),
    "creative_director": ("generate", "planning"),
    "clip_brief": ("generate", "planning"),
    "hook_retention": ("generate", "planning"),
    "caption_motion": ("generate", "planning"),
    "music_mood": ("generate", "planning"),
    "creator_learning": ("generate", "planning"),
    "approval_rejection_learning": ("generate", "planning"),
    "experimentation": ("generate", "planning"),
    "performance_feedback": ("generate", "planning"),
    "content_scout": ("generate", "planning"),
    "research_brain": ("generate", "planning"),
    "trend_topic_watcher": ("generate", "planning"),
    "candidate_video_scorer": ("generate", "planning"),
    "rights_permission_gate": ("generate", "read_only"),
    "observer": ("generate", "read_only"),
    "error_doctor": ("generate", "read_only"),
    "root_cause_analyzer": ("generate", "read_only"),
    "repair_planner": ("generate", "planning"),
}


def _operation(
    module_id: str,
    name: str,
    operation_class: BobaIntegrationOperationClassV1,
    *,
    side_effect_class: BobaIntegrationSideEffectClassV1 = "BOBA_metadata_only",
    approval: bool = False,
    approval_type: str = "",
    safety: bool = False,
    rights: bool = False,
    checkpoint: bool = False,
    idempotency: bool = True,
    required_artifacts: Sequence[str] = (),
    optional_artifacts: Sequence[str] = (),
    timeout: int = 60,
) -> BobaIntegrationOperationDescriptorV1:
    operation_id = f"{module_id}.{name}"
    return BobaIntegrationOperationDescriptorV1(
        operation_id=operation_id,
        module_id=module_id,
        display_name=f"{_MODULE_SPECS[module_id]['name']} {name.replace('_', ' ')}",
        operation_class=operation_class,
        side_effect_class=side_effect_class,
        required_artifact_types=list(required_artifacts),
        optional_artifact_types=list(optional_artifacts),
        target_approval_required=approval,
        required_approval_type=approval_type,
        safety_gate_required=safety,
        rights_gate_required=rights,
        checkpoint_required=checkpoint,
        idempotency_required=idempotency,
        future_gated=operation_class == "future_gated",
        prohibited=operation_class == "prohibited",
        timeout_seconds=timeout,
        limitations=[
            "The operation uses only its fixed typed facade adapter.",
            "Integration Layer does not replace target-module validation.",
        ],
    )


def build_boba_operation_registry() -> dict[str, BobaIntegrationOperationDescriptorV1]:
    """Build the deterministic fixed V1 operation registry."""

    operations: list[BobaIntegrationOperationDescriptorV1] = []
    for module_id, (name, operation_class) in _PRIMARY_OPERATIONS.items():
        operations.append(
            _operation(
                module_id,
                name,
                operation_class,
                rights=False,
            )
        )
    for module_id, spec in _MODULE_SPECS.items():
        if spec.get("future"):
            continue
        operations.extend(
            [
                _operation(
                    module_id,
                    "load",
                    "read_only",
                    side_effect_class="none",
                    idempotency=False,
                ),
                _operation(
                    module_id,
                    "export",
                    "export",
                    side_effect_class="none",
                    idempotency=False,
                ),
                _operation(module_id, "reset", "metadata_reset"),
            ]
        )
    operations.extend(
        [
            _operation("code_surgeon", "propose", "planning"),
            _operation(
                "code_surgeon",
                "validate_patch",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "code_surgeon",
                "execute_approved",
                "approved_execution",
                side_effect_class="isolated_code_worktree",
                approval=True,
                approval_type="isolated_patch_execution",
                safety=True,
                checkpoint=True,
                timeout=900,
            ),
            _operation(
                "code_surgeon",
                "prepare_local_commit",
                "approved_execution",
                side_effect_class="isolated_code_worktree",
                approval=True,
                approval_type="local_commit_creation",
                safety=True,
                checkpoint=True,
                timeout=300,
            ),
            _operation("tool_recovery_brain", "plan", "planning"),
            _operation(
                "tool_recovery_brain",
                "health_check",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "tool_recovery_brain",
                "execute_approved",
                "approved_execution",
                side_effect_class="recovery_owned_state",
                approval=True,
                approval_type="tool_recovery_exact",
                safety=True,
                checkpoint=True,
                timeout=1_800,
            ),
            _operation(
                "tool_recovery_brain",
                "validate_output",
                "read_only",
                side_effect_class="BOBA_metadata_only",
            ),
            _operation(
                "tool_recovery_brain",
                "rollback",
                "approved_rollback",
                side_effect_class="recovery_owned_state",
                approval=True,
                approval_type="tool_recovery_rollback",
                safety=True,
                checkpoint=True,
                timeout=900,
            ),
            _operation("output_quality_reviewer", "review", "read_only"),
            _operation("output_quality_reviewer", "compare", "read_only"),
            _operation(
                "output_quality_reviewer",
                "record_human_review",
                "metadata_reset",
            ),
            _operation("autopilot_controller", "create_run", "planning"),
            _operation("autopilot_controller", "plan_next", "planning"),
            _operation("autopilot_controller", "advance_safe", "read_only"),
            _operation(
                "autopilot_controller",
                "coordinate_approved",
                "approved_execution",
                side_effect_class="isolated_generated_state",
                approval=True,
                approval_type="target_module_exact",
                safety=True,
                checkpoint=True,
                timeout=1_800,
            ),
            _operation("autopilot_controller", "pause", "metadata_reset"),
            _operation("autopilot_controller", "continue_controller", "metadata_reset"),
            _operation("autopilot_controller", "cancel", "metadata_reset"),
            _operation("autopilot_controller", "record_human_decision", "metadata_reset"),
            _operation("safety_gate", "create_policy", "planning"),
            _operation("safety_gate", "create_request", "planning"),
            _operation("safety_gate", "evaluate", "planning"),
            _operation("safety_gate", "revalidate", "read_only"),
            _operation("safety_gate", "invalidate", "metadata_reset"),
            _operation("safety_gate", "record_human_review", "metadata_reset"),
            _operation("validator_runner", "build_registry", "planning"),
            _operation(
                "validator_runner",
                "inspect_registry",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "validator_runner",
                "inspect_availability",
                "read_only",
                side_effect_class="none",
            ),
            _operation("validator_runner", "create_plan", "planning"),
            _operation(
                "validator_runner",
                "validate_plan",
                "read_only",
                side_effect_class="none",
            ),
            _operation("validator_runner", "create_run", "planning"),
            _operation(
                "validator_runner",
                "execute_run",
                "approved_execution",
                side_effect_class="BOBA_metadata_only",
                approval=True,
                approval_type="target_module_exact",
                safety=True,
                timeout=1_800,
            ),
            _operation("validator_runner", "cancel_run", "metadata_reset"),
            _operation(
                "validator_runner",
                "retry_check",
                "approved_execution",
                side_effect_class="BOBA_metadata_only",
                approval=True,
                approval_type="target_module_exact",
                safety=True,
                timeout=1_800,
            ),
            _operation(
                "validator_runner",
                "inspect_results",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "report_reader",
                "inspect_registry",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "report_reader",
                "create_read_request",
                "read_only",
            ),
            _operation(
                "report_reader",
                "validate_references",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "report_reader",
                "read_reports",
                "read_only",
            ),
            _operation(
                "report_reader",
                "inspect_read_run",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "report_reader",
                "compare_reports",
                "read_only",
            ),
            _operation(
                "report_reader",
                "build_bundle",
                "read_only",
            ),
            _operation(
                "report_reader",
                "inspect_bundle",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "report_reader",
                "inspect_events",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "artifact_inspector",
                "inspect_registry",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "artifact_inspector",
                "create_inspection_request",
                "read_only",
            ),
            _operation(
                "artifact_inspector",
                "validate_references",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "artifact_inspector",
                "inspect_artifacts",
                "read_only",
            ),
            _operation(
                "artifact_inspector",
                "inspect_run",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "artifact_inspector",
                "build_inventory",
                "read_only",
            ),
            _operation(
                "artifact_inspector",
                "inspect_lineage",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "artifact_inspector",
                "compare_artifacts",
                "read_only",
            ),
            _operation(
                "artifact_inspector",
                "inspect_events",
                "read_only",
                side_effect_class="none",
            ),
            _operation("final_decision_bus", "build_registries", "read_only"),
            _operation(
                "final_decision_bus", "inspect_registries", "read_only", side_effect_class="none"
            ),
            _operation("final_decision_bus", "create_request", "read_only"),
            _operation(
                "final_decision_bus", "validate_request", "read_only", side_effect_class="none"
            ),
            _operation("final_decision_bus", "collect_source_bindings", "read_only"),
            _operation(
                "final_decision_bus",
                "validate_source_bindings",
                "read_only",
                side_effect_class="none",
            ),
            _operation("final_decision_bus", "build_evidence_requirements", "read_only"),
            _operation("final_decision_bus", "bind_evidence", "read_only"),
            _operation("final_decision_bus", "detect_conflicts", "read_only"),
            _operation("final_decision_bus", "evaluate_policy", "read_only"),
            _operation("final_decision_bus", "finalize_decision", "read_only"),
            _operation("final_decision_bus", "build_dispatch_envelope", "read_only"),
            _operation(
                "final_decision_bus", "inspect_decision", "read_only", side_effect_class="none"
            ),
            _operation(
                "final_decision_bus",
                "inspect_dispatch_envelope",
                "read_only",
                side_effect_class="none",
            ),
            _operation("final_decision_bus", "consume_dispatch_envelope", "read_only"),
            _operation("final_decision_bus", "invalidate_decision", "read_only"),
            _operation(
                "final_decision_bus", "inspect_events", "read_only", side_effect_class="none"
            ),
            _operation("review_ui", "inspect_registry", "read_only", side_effect_class="none"),
            _operation("review_ui", "create_session", "metadata_reset"),
            _operation("review_ui", "update_session", "metadata_reset"),
            _operation("review_ui", "build_queue", "read_only", side_effect_class="none"),
            _operation("review_ui", "inspect_queue", "read_only", side_effect_class="none"),
            _operation("review_ui", "build_snapshot", "read_only"),
            _operation("review_ui", "refresh_snapshot", "read_only"),
            _operation("review_ui", "inspect_target", "read_only", side_effect_class="none"),
            _operation("review_ui", "create_action", "read_only"),
            _operation("review_ui", "validate_action", "read_only", side_effect_class="none"),
            _operation(
                "review_ui",
                "submit_action",
                "read_only",
                approval=True,
                approval_type="exact_human_review_action",
                safety=True,
            ),
            _operation("review_ui", "inspect_receipt", "read_only", side_effect_class="none"),
            _operation("review_ui", "inspect_timeline", "read_only", side_effect_class="none"),
            _operation("review_ui", "inspect_events", "read_only", side_effect_class="none"),
            _operation("review_ui", "acknowledge_notification", "metadata_reset"),
            _operation(
                "candidate_review", "inspect_registry", "read_only", side_effect_class="none"
            ),
            _operation("candidate_review", "create_session", "metadata_reset"),
            _operation("candidate_review", "update_session", "metadata_reset"),
            _operation(
                "candidate_review", "build_queue", "read_only", side_effect_class="none"
            ),
            _operation(
                "candidate_review", "inspect_queue", "read_only", side_effect_class="none"
            ),
            _operation("candidate_review", "build_snapshot", "read_only"),
            _operation("candidate_review", "refresh_snapshot", "read_only"),
            _operation(
                "candidate_review", "inspect_candidate", "read_only", side_effect_class="none"
            ),
            _operation(
                "candidate_review", "compare_candidates", "read_only", side_effect_class="none"
            ),
            _operation(
                "candidate_review", "calculate_overlaps", "read_only", side_effect_class="none"
            ),
            _operation("candidate_review", "create_action", "read_only"),
            _operation(
                "candidate_review", "validate_action", "read_only", side_effect_class="none"
            ),
            _operation(
                "candidate_review",
                "submit_action",
                "read_only",
                approval=True,
                approval_type="exact_candidate_review_action",
                safety=True,
            ),
            _operation(
                "candidate_review", "inspect_receipt", "read_only", side_effect_class="none"
            ),
            _operation(
                "candidate_review", "inspect_timeline", "read_only", side_effect_class="none"
            ),
            _operation(
                "candidate_review", "inspect_events", "read_only", side_effect_class="none"
            ),
            _operation(
                "error_doctor_review", "inspect_registry", "read_only", side_effect_class="none"
            ),
            _operation("error_doctor_review", "create_session", "metadata_reset"),
            _operation("error_doctor_review", "update_session", "metadata_reset"),
            _operation(
                "error_doctor_review", "build_queue", "read_only", side_effect_class="none"
            ),
            _operation(
                "error_doctor_review", "inspect_queue", "read_only", side_effect_class="none"
            ),
            _operation("error_doctor_review", "build_snapshot", "read_only"),
            _operation("error_doctor_review", "refresh_snapshot", "read_only"),
            _operation(
                "error_doctor_review", "inspect_incident", "read_only", side_effect_class="none"
            ),
            _operation(
                "error_doctor_review", "inspect_diagnosis", "read_only", side_effect_class="none"
            ),
            _operation(
                "error_doctor_review", "inspect_root_cause", "read_only", side_effect_class="none"
            ),
            _operation(
                "error_doctor_review",
                "inspect_repair_plan",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "error_doctor_review",
                "inspect_recovery_history",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "error_doctor_review",
                "inspect_validation_evidence",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "error_doctor_review",
                "inspect_artifact_evidence",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "error_doctor_review", "detect_conflicts", "read_only", side_effect_class="none"
            ),
            _operation(
                "error_doctor_review",
                "compare_incidents",
                "read_only",
                side_effect_class="none",
            ),
            _operation("error_doctor_review", "create_action", "read_only"),
            _operation(
                "error_doctor_review", "validate_action", "read_only", side_effect_class="none"
            ),
            _operation(
                "error_doctor_review",
                "submit_action",
                "read_only",
                approval=True,
                approval_type="exact_error_doctor_review_action",
                safety=True,
            ),
            _operation(
                "error_doctor_review", "inspect_receipt", "read_only", side_effect_class="none"
            ),
            _operation(
                "error_doctor_review", "inspect_timeline", "read_only", side_effect_class="none"
            ),
            _operation(
                "error_doctor_review", "inspect_events", "read_only", side_effect_class="none"
            ),
            _operation(
                "approval_controls", "inspect_registry", "read_only", side_effect_class="none"
            ),
            _operation(
                "approval_controls", "inspect_eligibility", "read_only", side_effect_class="none"
            ),
            _operation("approval_controls", "build_snapshot", "read_only"),
            _operation(
                "approval_controls", "revalidate_snapshot", "read_only", side_effect_class="none"
            ),
            _operation("approval_controls", "create_decision", "read_only"),
            _operation(
                "approval_controls",
                "submit_decision",
                "read_only",
                approval=True,
                approval_type="exact_human_review_action",
                safety=True,
            ),
            _operation(
                "approval_controls",
                "inspect_decision_status",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "approval_controls",
                "inspect_decision_history",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "approval_controls", "inspect_events", "read_only", side_effect_class="none"
            ),
            _operation(
                "approval_controls", "inspect_timeline", "read_only", side_effect_class="none"
            ),
            _operation(
                "approval_controls", "compare_decisions", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_registry", "read_only", side_effect_class="none"
            ),
            _operation("repair_plan_review", "create_session", "metadata_reset"),
            _operation("repair_plan_review", "update_session", "metadata_reset"),
            _operation(
                "repair_plan_review", "build_queue", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_queue", "read_only", side_effect_class="none"
            ),
            _operation("repair_plan_review", "build_snapshot", "read_only"),
            _operation("repair_plan_review", "refresh_snapshot", "read_only"),
            _operation(
                "repair_plan_review", "inspect_plan", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_steps", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_risks", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_approvals", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_verification", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_evidence", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review",
                "inspect_recovery_history",
                "read_only",
                side_effect_class="none",
            ),
            _operation(
                "repair_plan_review", "detect_conflicts", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_conflicts", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "compare_plans", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "describe_confirmation", "read_only", side_effect_class="none"
            ),
            _operation("repair_plan_review", "create_action", "read_only"),
            _operation(
                "repair_plan_review", "validate_action", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review",
                "submit_action",
                "read_only",
                approval=True,
                approval_type="exact_repair_plan_review_action",
                safety=True,
            ),
            _operation(
                "repair_plan_review", "inspect_receipt", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_timeline", "read_only", side_effect_class="none"
            ),
            _operation(
                "repair_plan_review", "inspect_events", "read_only", side_effect_class="none"
            ),
            _operation(
                "clip_brief_review", "inspect_registry", "read_only", side_effect_class="none"
            ),
            _operation("clip_brief_review", "create_session", "metadata_reset"),
            _operation("clip_brief_review", "update_session", "metadata_reset"),
            _operation(
                "clip_brief_review", "build_queue", "read_only", side_effect_class="none"
            ),
            _operation(
                "clip_brief_review", "inspect_queue", "read_only", side_effect_class="none"
            ),
            _operation("clip_brief_review", "build_snapshot", "read_only"),
            _operation("clip_brief_review", "refresh_snapshot", "read_only"),
            _operation(
                "clip_brief_review", "inspect_brief", "read_only", side_effect_class="none"
            ),
            _operation(
                "clip_brief_review", "compare_briefs", "read_only", side_effect_class="none"
            ),
            _operation(
                "clip_brief_review", "inspect_completeness", "read_only", side_effect_class="none"
            ),
            _operation(
                "clip_brief_review", "inspect_evidence", "read_only", side_effect_class="none"
            ),
            _operation(
                "clip_brief_review", "detect_conflicts", "read_only", side_effect_class="none"
            ),
            _operation("clip_brief_review", "create_action", "read_only"),
            _operation(
                "clip_brief_review", "validate_action", "read_only", side_effect_class="none"
            ),
            _operation(
                "clip_brief_review",
                "submit_action",
                "read_only",
                approval=True,
                approval_type="exact_clip_brief_review_action",
                safety=True,
            ),
            _operation(
                "clip_brief_review", "inspect_receipt", "read_only", side_effect_class="none"
            ),
            _operation(
                "clip_brief_review", "inspect_timeline", "read_only", side_effect_class="none"
            ),
            _operation(
                "clip_brief_review", "inspect_events", "read_only", side_effect_class="none"
            ),
            _operation("workflow_controller", "build_definition", "planning"),
            _operation("workflow_controller", "create_run", "planning"),
            _operation(
                "workflow_controller",
                "inspect",
                "read_only",
                side_effect_class="none",
            ),
            _operation("workflow_controller", "plan_next", "planning"),
            _operation(
                "workflow_controller",
                "create_transition_request",
                "planning",
            ),
            _operation(
                "workflow_controller",
                "evaluate_transition",
                "planning",
            ),
            _operation(
                "workflow_controller",
                "advance_safe_read_only",
                "read_only",
            ),
            _operation(
                "workflow_controller",
                "coordinate_approved_internal_transition",
                "approved_execution",
                side_effect_class="isolated_generated_state",
                approval=True,
                approval_type="target_module_exact",
                safety=True,
                checkpoint=True,
                timeout=1_800,
            ),
            _operation("workflow_controller", "pause", "metadata_reset"),
            _operation(
                "workflow_controller",
                "continue_controller",
                "metadata_reset",
            ),
            _operation("workflow_controller", "cancel", "metadata_reset"),
            _operation(
                "workflow_controller",
                "create_recovery_hold",
                "planning",
            ),
            _operation(
                "workflow_controller",
                "receive_recovery_result",
                "planning",
            ),
            _operation(
                "workflow_controller",
                "evaluate_resume_eligibility",
                "planning",
            ),
            _operation(
                "workflow_controller",
                "record_human_decision",
                "metadata_reset",
            ),
            _operation(
                "workflow_controller",
                "complete_internal_output",
                "approved_execution",
                approval=True,
                approval_type="target_module_exact",
                safety=True,
                checkpoint=True,
            ),
            _operation(
                "olympus_editing",
                "prepare_render",
                "approved_execution",
                side_effect_class="isolated_generated_state",
                approval=True,
                approval_type="target_module_exact",
                safety=True,
                checkpoint=True,
                required_artifacts=[
                    "hook_retention_plan",
                    "caption_motion_plan",
                    "music_mood_plan",
                ],
                timeout=1_800,
            ),
            _operation(
                "olympus_rendering",
                "render",
                "approved_execution",
                side_effect_class="isolated_generated_state",
                approval=True,
                approval_type="target_module_exact",
                safety=True,
                checkpoint=True,
                required_artifacts=["render_timeline"],
                timeout=3_600,
            ),
            _operation(
                "olympus_optimization",
                "validate_render",
                "read_only",
                required_artifacts=["rendered_mp4", "render_manifest"],
                timeout=900,
            ),
            _operation("workflow_controller", "resume", "future_gated"),
            _operation("checkpoint_recovery_manager", "restore_checkpoint", "future_gated"),
            _operation("integration_layer", "upload", "future_gated"),
            _operation("integration_layer", "publication", "future_gated"),
            _operation("integration_layer", "push", "future_gated"),
            _operation("integration_layer", "merge", "future_gated"),
            _operation("integration_layer", "deployment", "future_gated"),
            _operation("integration_layer", "package_installation", "prohibited"),
            _operation("integration_layer", "service_restart", "prohibited"),
        ]
    )
    registry: dict[str, BobaIntegrationOperationDescriptorV1] = {}
    for descriptor in operations:
        if descriptor.operation_id in registry:
            raise ValidationError(
                f"Duplicate BOBA integration operation: {descriptor.operation_id}"
            )
        registry[descriptor.operation_id] = descriptor
    return dict(sorted(registry.items()))


def build_boba_module_registry() -> dict[str, BobaIntegrationModuleDescriptorV1]:
    """Build the deterministic fixed V1 module registry."""

    operation_registry = build_boba_operation_registry()
    registry: dict[str, BobaIntegrationModuleDescriptorV1] = {}
    for module_id, spec in _MODULE_SPECS.items():
        if module_id in registry:
            raise ValidationError(f"Duplicate BOBA integration module: {module_id}")
        operation_ids = [
            operation_id
            for operation_id, descriptor in operation_registry.items()
            if descriptor.module_id == module_id
        ]
        future = bool(spec.get("future"))
        registry[module_id] = BobaIntegrationModuleDescriptorV1(
            module_id=module_id,
            display_name=str(spec["name"]),
            module_version="1",
            implementation_status="future" if future else "available",
            supported_schema_versions=[
                f"boba_{module_id}_v1",
                "boba.integration.request:1.0",
                "boba.integration.response:1.0",
            ],
            operation_ids=operation_ids,
            read_only=not bool(spec.get("execution")),
            planning_capable=bool(spec.get("planning")) or any(
                operation_registry[item].operation_class == "planning"
                for item in operation_ids
            ),
            execution_capable=bool(spec.get("execution")),
            requires_rights_gate=bool(spec.get("rights")),
            requires_target_approval=bool(spec.get("approval")),
            requires_safety_gate=bool(spec.get("safety")),
            requires_checkpoint=bool(spec.get("checkpoint")),
            implementation_import_path=str(spec.get("path") or ""),
            artifact_path_pattern=(
                f"projects/{{project_id}}/{module_id}/index.json"
                if not future
                else ""
            ),
            dependency_module_ids=list(spec.get("deps") or []),
            health_status="unavailable" if future else "unverified",
            health_reason=(
                "The module is explicitly future-gated."
                if future
                else "Availability is declared; handler readiness is checked per route."
            ),
            known_limitations=(
                ["No V1 target handler exists."]
                if future
                else ["The Integration Layer does not own module decisions."]
            ),
        )
    known_ids = set(registry)
    for descriptor in registry.values():
        unknown = set(descriptor.dependency_module_ids) - known_ids
        if unknown:
            raise ValidationError(
                f"Unknown module dependencies for {descriptor.module_id}: {sorted(unknown)}"
            )
    return dict(sorted(registry.items()))


def validate_boba_registry_descriptors(
    modules: Sequence[BobaIntegrationModuleDescriptorV1],
    operations: Sequence[BobaIntegrationOperationDescriptorV1],
) -> None:
    """Reject duplicate or cross-linked descriptors before routing is possible."""

    module_ids = [item.module_id for item in modules]
    operation_ids = [item.operation_id for item in operations]
    duplicate_modules = sorted(
        item for item, count in Counter(module_ids).items() if count > 1
    )
    duplicate_operations = sorted(
        item for item, count in Counter(operation_ids).items() if count > 1
    )
    if duplicate_modules:
        raise ValidationError(
            "Duplicate BOBA integration module descriptors.",
            details={"module_ids": duplicate_modules},
        )
    if duplicate_operations:
        raise ValidationError(
            "Duplicate BOBA integration operation descriptors.",
            details={"operation_ids": duplicate_operations},
        )
    known_modules = set(module_ids)
    for operation in operations:
        if operation.module_id not in known_modules:
            raise ValidationError(
                "BOBA integration operation references an unknown module.",
                details={"operation_id": operation.operation_id},
            )
    known_operations = set(operation_ids)
    for module in modules:
        missing = sorted(set(module.operation_ids) - known_operations)
        if missing:
            raise ValidationError(
                "BOBA integration module references unknown operations.",
                details={"module_id": module.module_id, "operation_ids": missing},
            )


_TERMINAL_TRANSACTION_STATES = frozenset(
    {
        "blocked",
        "succeeded",
        "failed",
        "timed_out",
        "cancelled",
        "duplicate_reused",
        "future_gated",
    }
)
_EXECUTION_OPERATION_CLASSES = frozenset(
    {"approved_execution", "approved_rollback"}
)
_ALLOWED_EXECUTION_SAFETY_DECISION = "allowed_for_exact_internal_execution"
_ALLOWED_READ_ONLY_SAFETY_DECISION = "allowed_for_internal_read_only"


async def _resolve_awaitable(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _new_runtime_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _request_digest_payload(
    *,
    project_id: str,
    run_id: str,
    requesting_module_id: str,
    target_module_id: str,
    target_operation_id: str,
    request_schema_id: str,
    request_schema_version: str,
    request_parameters: Mapping[str, Any],
    artifact_reference_ids: Sequence[str],
    approval_binding: BobaIntegrationApprovalBindingV1 | None,
    safety_binding: BobaIntegrationSafetyBindingV1 | None,
    project_snapshot_digest: str,
) -> dict[str, Any]:
    safety_payload = safety_binding.model_dump(mode="json") if safety_binding else None
    if safety_payload is not None:
        safety_payload.pop("request_digest", None)
    return {
        "project_id": project_id,
        "run_id": run_id,
        "requesting_module_id": requesting_module_id,
        "target_module_id": target_module_id,
        "target_operation_id": target_operation_id,
        "request_schema_id": request_schema_id,
        "request_schema_version": request_schema_version,
        "request_parameters": request_parameters,
        "artifact_reference_ids": sorted(artifact_reference_ids),
        "approval_binding": (
            approval_binding.model_dump(mode="json") if approval_binding else None
        ),
        "safety_binding": safety_payload,
        "project_snapshot_digest": project_snapshot_digest,
    }


class BobaIntegrationLayerV1:
    """Closed typed router for registered BOBA operations.

    Handlers are supplied only by the trusted application composition root.
    Requests can select a registered operation ID, but they cannot add or
    replace a handler.
    """

    def __init__(
        self,
        store: BobaMemoryStore,
        *,
        project_id: str,
        source_id: str,
        handlers: Mapping[str, IntegrationOperationHandler] | None = None,
        project_exists: IntegrationProjectExists | None = None,
        context_provider: IntegrationContextProvider | None = None,
    ) -> None:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError(
                "Invalid BOBA Integration Layer project id.",
                details={"project_id": project_id},
            )
        self.store = store
        self.project_id = project_id
        self.source_id = _text(source_id or project_id, maximum=512)
        self.module_registry = build_boba_module_registry()
        self.operation_registry = build_boba_operation_registry()
        validate_boba_registry_descriptors(
            list(self.module_registry.values()),
            list(self.operation_registry.values()),
        )
        supplied_handlers = dict(handlers or {})
        unknown_handlers = sorted(set(supplied_handlers) - set(self.operation_registry))
        if unknown_handlers:
            raise ValidationError(
                "BOBA Integration Layer rejected unregistered handlers.",
                details={"operation_ids": unknown_handlers},
            )
        self._handlers = supplied_handlers
        self._project_exists = project_exists
        self._context_provider = context_provider

    def build_registry_snapshot(self) -> BobaIntegrationRegistrySnapshotV1:
        """Build and persist an immutable deterministic registry snapshot."""

        modules = list(self.module_registry.values())
        operations = list(self.operation_registry.values())
        digest_payload = {
            "registry_version": "boba_integration_registry_v1",
            "modules": [item.model_dump(mode="json") for item in modules],
            "operations": [item.model_dump(mode="json") for item in operations],
        }
        registry_digest = _digest(digest_payload)
        snapshot = BobaIntegrationRegistrySnapshotV1(
            registry_snapshot_id=f"boba_registry_{registry_digest[:24]}",
            module_ids=[item.module_id for item in modules],
            operation_ids=[item.operation_id for item in operations],
            module_versions={
                item.module_id: item.module_version for item in modules
            },
            schema_versions={
                item.module_id: list(item.supported_schema_versions)
                for item in modules
            },
            unavailable_module_ids=[
                item.module_id
                for item in modules
                if item.implementation_status in {"unavailable", "blocked"}
            ],
            future_module_ids=[
                item.module_id
                for item in modules
                if item.implementation_status == "future"
            ],
            registry_sha256=registry_digest,
            limitations=[
                "Registry declarations are static for Integration Layer V1.",
                "Handler health is checked again when a request is routed.",
            ],
        )
        return self.store.save_boba_integration_registry_snapshot(
            self.project_id,
            snapshot,
        )

    def inspect_module_registry(
        self,
    ) -> list[BobaIntegrationModuleDescriptorV1]:
        return [
            item.model_copy(deep=True) for item in self.module_registry.values()
        ]

    def inspect_operation_registry(
        self,
    ) -> list[BobaIntegrationOperationDescriptorV1]:
        return [
            item.model_copy(deep=True) for item in self.operation_registry.values()
        ]

    def _new_layer(
        self,
        snapshot: BobaIntegrationRegistrySnapshotV1 | None = None,
    ) -> BobaIntegrationLayerSetV1:
        current_snapshot = snapshot or self.build_registry_snapshot()
        layer = BobaIntegrationLayerSetV1(
            project_id=self.project_id,
            source_id=self.source_id,
            registry_snapshot=current_snapshot,
            module_descriptors=self.inspect_module_registry(),
            operation_descriptors=self.inspect_operation_registry(),
            signal_usage=BobaIntegrationSignalUsageV1(
                module_registry_used=True,
                operation_registry_used=True,
            ),
            limitations=[
                "The layer transports decisions but never chooses an action.",
                "Idempotency does not guarantee global exactly-once execution.",
            ],
        )
        layer.integration_summary = self._summarize(layer)
        return self.store.save_boba_integration_layer(layer)

    def _load_layer(self) -> BobaIntegrationLayerSetV1:
        return (
            self.store.load_boba_integration_layer(self.project_id)
            or self._new_layer()
        )

    def _save_layer(
        self,
        layer: BobaIntegrationLayerSetV1,
    ) -> BobaIntegrationLayerSetV1:
        layer.integration_summary = self._summarize(layer)
        return self.store.save_boba_integration_layer(layer)

    def _summarize(
        self,
        layer: BobaIntegrationLayerSetV1,
    ) -> BobaIntegrationSummaryV1:
        module_status = Counter(
            item.implementation_status for item in layer.module_descriptors
        )
        operation_classes = Counter(
            item.operation_class for item in layer.operation_descriptors
        )
        transaction_states = Counter(
            item.state for item in layer.integration_transactions
        )
        failure_classes = Counter(
            item.failure_class for item in layer.integration_failures
        )
        highest_failure = (
            layer.integration_failures[-1].bounded_summary
            if layer.integration_failures
            else ""
        )
        human_actions = _unique(
            [
                item.reason
                for item in layer.integration_handoffs
                if item.human_review_required
            ],
            limit=32,
        )
        return BobaIntegrationSummaryV1(
            registered_module_count=len(layer.module_descriptors),
            available_module_count=module_status["available"],
            degraded_module_count=module_status["degraded"],
            unavailable_module_count=(
                module_status["unavailable"]
                + module_status["blocked"]
                + module_status["future"]
            ),
            registered_operation_count=len(layer.operation_descriptors),
            read_only_operation_count=operation_classes["read_only"],
            approved_execution_operation_count=(
                operation_classes["approved_execution"]
                + operation_classes["approved_rollback"]
            ),
            future_gated_operation_count=operation_classes["future_gated"],
            prohibited_operation_count=operation_classes["prohibited"],
            total_transaction_count=len(layer.integration_transactions),
            succeeded_transaction_count=transaction_states["succeeded"],
            blocked_transaction_count=(
                transaction_states["blocked"]
                + transaction_states["future_gated"]
            ),
            failed_transaction_count=(
                transaction_states["failed"] + transaction_states["timed_out"]
            ),
            incompatible_transaction_count=failure_classes["schema_incompatible"],
            idempotent_reuse_count=transaction_states["duplicate_reused"],
            idempotency_conflict_count=failure_classes["idempotency_conflict"],
            approval_block_count=(
                failure_classes["approval_missing"]
                + failure_classes["approval_invalid"]
                + failure_classes["approval_expired"]
            ),
            safety_block_count=(
                failure_classes["safety_decision_missing"]
                + failure_classes["safety_decision_invalid"]
                + failure_classes["safety_decision_expired"]
            ),
            dependency_block_count=(
                failure_classes["missing_dependency"]
                + failure_classes["stale_artifact"]
                + failure_classes["malformed_artifact"]
            ),
            current_registry_snapshot_id=layer.registry_snapshot.registry_snapshot_id,
            highest_priority_failure=highest_failure,
            required_human_actions=human_actions,
            limitations=[
                "Integration Layer does not create approvals or Safety decisions.",
                "Target modules independently revalidate execution requests.",
            ],
        )

    def create_request_envelope(
        self,
        *,
        requesting_module_id: str,
        target_module_id: str,
        target_operation_id: str,
        request_parameters: Mapping[str, Any] | None = None,
        run_id: str = "",
        source_id: str | None = None,
        request_schema_id: str = "boba.integration.request",
        request_schema_version: str = "1.0",
        artifact_references: Sequence[
            BobaIntegrationArtifactReferenceV1
        ] = (),
        approval_binding: BobaIntegrationApprovalBindingV1 | None = None,
        safety_binding: BobaIntegrationSafetyBindingV1 | None = None,
        project_snapshot_digest: str = "",
        expires_in_seconds: int = 300,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> BobaIntegrationEnvelopeV1:
        """Create a bounded request envelope without invoking a target."""

        if not 1 <= expires_in_seconds <= 3_600:
            raise ValidationError(
                "Integration request expiry must be between 1 and 3600 seconds."
            )
        for label, value in {
            "requesting_module_id": requesting_module_id,
            "target_module_id": target_module_id,
            "target_operation_id": target_operation_id,
            "run_id": run_id or "no-run",
        }.items():
            if not _SAFE_ID.fullmatch(value):
                raise ValidationError(
                    f"Invalid Integration Layer {label}.",
                    details={label: value},
                )
        parameters = _validate_bounded_payload(request_parameters or {})
        references = [item.model_copy(deep=True) for item in artifact_references]
        for reference in references:
            if reference.sanitized_storage_reference:
                reference.sanitized_storage_reference = _validate_storage_reference(
                    reference.sanitized_storage_reference
                )
        transaction_id = _new_runtime_id("boba_integration_tx")
        envelope_id = _new_runtime_id("boba_integration_envelope")
        correlation = correlation_id or _new_runtime_id("boba_integration_correlation")
        created = datetime.now(UTC)
        request_digest = _digest(
            _request_digest_payload(
                project_id=self.project_id,
                run_id=run_id,
                requesting_module_id=requesting_module_id,
                target_module_id=target_module_id,
                target_operation_id=target_operation_id,
                request_schema_id=request_schema_id,
                request_schema_version=request_schema_version,
                request_parameters=parameters,
                artifact_reference_ids=[
                    item.artifact_reference_id for item in references
                ],
                approval_binding=approval_binding,
                safety_binding=safety_binding,
                project_snapshot_digest=project_snapshot_digest,
            )
        )
        key = idempotency_key or _stable_id(
            "boba_integration_idempotency",
            self.project_id,
            run_id,
            target_operation_id,
            request_digest,
        )
        if not _SAFE_ID.fullmatch(key):
            raise ValidationError("Invalid Integration Layer idempotency key.")
        return BobaIntegrationEnvelopeV1(
            envelope_id=envelope_id,
            envelope_type="request",
            schema_id=request_schema_id,
            schema_version=request_schema_version,
            producer_module_id=requesting_module_id,
            producer_module_version=self.module_registry.get(
                requesting_module_id,
                BobaIntegrationModuleDescriptorV1(
                    module_id="unknown",
                    display_name="Unknown",
                    implementation_status="unknown",
                ),
            ).module_version,
            consumer_module_id=target_module_id,
            consumer_operation_id=target_operation_id,
            project_id=self.project_id,
            source_id=_text(source_id or self.source_id, maximum=512),
            run_id=run_id,
            correlation_id=correlation,
            transaction_id=transaction_id,
            created_at=created.isoformat(),
            expires_at=(created + timedelta(seconds=expires_in_seconds)).isoformat(),
            idempotency_key=key,
            project_snapshot_digest=project_snapshot_digest,
            payload_digest=_digest(parameters),
            artifact_references=references,
            approval_binding=(
                approval_binding.model_copy(deep=True) if approval_binding else None
            ),
            safety_binding=(
                safety_binding.model_copy(deep=True) if safety_binding else None
            ),
            bounded_payload=parameters,
        )

    def _request_from_envelope(
        self,
        envelope: BobaIntegrationEnvelopeV1,
    ) -> BobaIntegrationRequestV1:
        operation = self.operation_registry.get(envelope.consumer_operation_id)
        timeout = operation.timeout_seconds if operation else 60
        request = BobaIntegrationRequestV1(
            request_id=_stable_id("boba_integration_request", envelope.envelope_id),
            envelope_id=envelope.envelope_id,
            project_id=envelope.project_id,
            run_id=envelope.run_id,
            requesting_module_id=envelope.producer_module_id,
            target_module_id=envelope.consumer_module_id,
            target_operation_id=envelope.consumer_operation_id,
            request_schema_id=envelope.schema_id,
            request_schema_version=envelope.schema_version,
            request_parameters=dict(envelope.bounded_payload),
            artifact_reference_ids=[
                item.artifact_reference_id
                for item in envelope.artifact_references
            ],
            approval_binding_id=(
                envelope.approval_binding.approval_binding_id
                if envelope.approval_binding
                else ""
            ),
            safety_binding_id=(
                envelope.safety_binding.safety_binding_id
                if envelope.safety_binding
                else ""
            ),
            idempotency_key=envelope.idempotency_key,
            expected_response_schema_id=(
                operation.response_schema_id
                if operation
                else "boba.integration.response"
            ),
            timeout_seconds=timeout,
            request_digest="0" * 64,
            created_at=envelope.created_at,
        )
        request.request_digest = _digest(
            _request_digest_payload(
                project_id=request.project_id,
                run_id=request.run_id,
                requesting_module_id=request.requesting_module_id,
                target_module_id=request.target_module_id,
                target_operation_id=request.target_operation_id,
                request_schema_id=request.request_schema_id,
                request_schema_version=request.request_schema_version,
                request_parameters=request.request_parameters,
                artifact_reference_ids=request.artifact_reference_ids,
                approval_binding=envelope.approval_binding,
                safety_binding=envelope.safety_binding,
                project_snapshot_digest=envelope.project_snapshot_digest,
            )
        )
        return request

    def create_transaction(
        self,
        request: BobaIntegrationRequestV1,
        envelope: BobaIntegrationEnvelopeV1,
    ) -> BobaIntegrationTransactionV1:
        operation = self.operation_registry.get(request.target_operation_id)
        operation_class: BobaIntegrationOperationClassV1 = (
            operation.operation_class if operation else "prohibited"
        )
        transaction = BobaIntegrationTransactionV1(
            transaction_id=envelope.transaction_id,
            project_id=request.project_id,
            run_id=request.run_id,
            correlation_id=envelope.correlation_id,
            request_id=request.request_id,
            registry_snapshot_id=self.build_registry_snapshot().registry_snapshot_id,
            target_module_id=request.target_module_id,
            target_operation_id=request.target_operation_id,
            operation_class=operation_class,
            request_digest=request.request_digest,
            snapshot_digest=envelope.project_snapshot_digest,
            limitations=[
                "This transaction records integration routing only.",
                "Execution ownership remains with the target module.",
            ],
        )
        self.store.save_boba_integration_transaction(transaction)
        return transaction

    def _remember_request(
        self,
        envelope: BobaIntegrationEnvelopeV1,
        request: BobaIntegrationRequestV1,
        transaction: BobaIntegrationTransactionV1,
    ) -> None:
        layer = self._load_layer()
        layer.request_envelopes = (
            [
                item
                for item in layer.request_envelopes
                if item.envelope_id != envelope.envelope_id
            ]
            + [envelope]
        )[-256:]
        layer.integration_requests = (
            [
                item
                for item in layer.integration_requests
                if item.request_id != request.request_id
            ]
            + [request]
        )[-256:]
        existing_artifact_ids = {
            item.artifact_reference_id for item in envelope.artifact_references
        }
        layer.artifact_references = (
            [
                item
                for item in layer.artifact_references
                if item.artifact_reference_id not in existing_artifact_ids
            ]
            + list(envelope.artifact_references)
        )[-256:]
        layer.integration_transactions = (
            [
                item
                for item in layer.integration_transactions
                if item.transaction_id != transaction.transaction_id
            ]
            + [transaction]
        )[-512:]
        layer.signal_usage.schema_validation_used = True
        self._save_layer(layer)

    def _remember_transaction(
        self,
        transaction: BobaIntegrationTransactionV1,
    ) -> None:
        self.store.save_boba_integration_transaction(transaction)
        layer = self._load_layer()
        layer.integration_transactions = (
            [
                item
                for item in layer.integration_transactions
                if item.transaction_id != transaction.transaction_id
            ]
            + [transaction]
        )[-512:]
        self._save_layer(layer)

    def _append_event(
        self,
        transaction: BobaIntegrationTransactionV1,
        event_type: BobaIntegrationEventTypeV1,
        *,
        technical_message: str,
        easy_message: str,
        severity: Literal["info", "warning", "error", "critical"] = "info",
        confirmed_fact: str = "",
        assessment: str = "",
        requires_attention: bool = False,
    ) -> BobaIntegrationEventV1:
        previous = self.store.load_boba_integration_events(
            transaction.project_id,
            transaction.transaction_id,
        )
        event = BobaIntegrationEventV1(
            event_id=_new_runtime_id("boba_integration_event"),
            transaction_id=transaction.transaction_id,
            project_id=transaction.project_id,
            run_id=transaction.run_id,
            correlation_id=transaction.correlation_id,
            sequence=(previous[-1].sequence + 1 if previous else 1),
            event_type=event_type,
            severity=severity,
            module_id=transaction.target_module_id,
            operation_id=transaction.target_operation_id,
            technical_message=_text(technical_message, maximum=1_200),
            easy_message=_text(easy_message, maximum=1_200),
            confirmed_fact=_text(confirmed_fact, maximum=900),
            assessment=_text(assessment, maximum=900),
            requires_attention=requires_attention,
        )
        self.store.append_boba_integration_event(event)
        layer = self._load_layer()
        layer.integration_events = [*layer.integration_events, event][-2_048:]
        layer.signal_usage.event_stream_used = True
        self._save_layer(layer)
        return event

    async def _request_context(
        self,
        request: BobaIntegrationRequestV1,
    ) -> dict[str, Any]:
        if self._context_provider is None:
            return {}
        value = await _resolve_awaitable(
            self._context_provider(self.project_id, request)
        )
        return dict(value) if isinstance(value, Mapping) else {}

    async def _project_is_available(self) -> bool:
        if self._project_exists is None:
            return True
        return bool(
            await _resolve_awaitable(self._project_exists(self.project_id))
        )

    @staticmethod
    def _schema_parts(version: str) -> tuple[int, int] | None:
        match = re.fullmatch(r"(\d+)(?:\.(\d+))?", version.strip())
        if not match:
            return None
        return int(match.group(1)), int(match.group(2) or 0)

    def validate_schema_compatibility(
        self,
        request: BobaIntegrationRequestV1,
        transaction: BobaIntegrationTransactionV1,
        operation: BobaIntegrationOperationDescriptorV1,
    ) -> BobaIntegrationCompatibilityCheckV1:
        supported = list(operation.supported_schema_versions)
        status: BobaIntegrationCompatibilityStatusV1 = "compatible"
        backward_compatible = False
        normalized = False
        migration_required = False
        safety_critical = False
        failure_reason = ""
        producer_version = self._schema_parts(request.request_schema_version)
        supported_parts = [
            item
            for item in (self._schema_parts(value) for value in supported)
            if item is not None
        ]
        if request.request_schema_id != operation.request_schema_id:
            status = "incompatible"
            safety_critical = operation.operation_class in _EXECUTION_OPERATION_CLASSES
            failure_reason = "The request schema ID does not match the operation."
        elif request.request_schema_version in supported:
            status = "compatible"
        elif producer_version is None or not supported_parts:
            status = "incompatible"
            failure_reason = "The request schema version is malformed."
        elif producer_version[0] not in {item[0] for item in supported_parts}:
            status = "migration_required"
            migration_required = True
            safety_critical = operation.operation_class in _EXECUTION_OPERATION_CLASSES
            failure_reason = "The request uses an unsupported major schema version."
        elif any(
            item[0] == producer_version[0] and item[1] >= producer_version[1]
            for item in supported_parts
        ):
            status = "compatible_with_safe_normalization"
            backward_compatible = True
            normalized = request.request_schema_version not in supported
        else:
            status = "incompatible"
            failure_reason = "No declared backward-compatible schema version exists."
        check = BobaIntegrationCompatibilityCheckV1(
            compatibility_check_id=_stable_id(
                "boba_integration_compatibility",
                transaction.transaction_id,
                request.request_schema_id,
                request.request_schema_version,
            ),
            transaction_id=transaction.transaction_id,
            producer_module_id=request.requesting_module_id,
            consumer_module_id=request.target_module_id,
            schema_id=request.request_schema_id,
            producer_schema_version=request.request_schema_version,
            supported_consumer_versions=supported,
            compatibility_status=status,
            backward_compatible=backward_compatible,
            migration_required=migration_required,
            safe_normalization_available=normalized,
            safety_critical_difference=safety_critical,
            failure_reason=failure_reason,
        )
        layer = self._load_layer()
        layer.compatibility_checks = (
            [
                item
                for item in layer.compatibility_checks
                if item.compatibility_check_id != check.compatibility_check_id
            ]
            + [check]
        )[-512:]
        layer.signal_usage.compatibility_validation_used = True
        self._save_layer(layer)
        return check

    def validate_artifact_references(
        self,
        request: BobaIntegrationRequestV1,
        envelope: BobaIntegrationEnvelopeV1,
    ) -> list[str]:
        warnings: list[str] = []
        seen: set[str] = set()
        for reference in envelope.artifact_references:
            if reference.artifact_reference_id in seen:
                raise ValidationError("Duplicate integration artifact reference.")
            seen.add(reference.artifact_reference_id)
            if reference.project_id != request.project_id:
                raise ValidationError(
                    "Integration artifact belongs to a different project."
                )
            if reference.producer_module_id not in self.module_registry:
                raise ValidationError(
                    "Integration artifact producer is not registered."
                )
            if reference.artifact_type.casefold() in {
                "raw_media",
                "source_media",
                "media_bytes",
            }:
                raise ValidationError(
                    "Raw or source media cannot be transported by the Integration Layer."
                )
            storage_reference = reference.sanitized_storage_reference
            if storage_reference:
                normalized = _validate_storage_reference(storage_reference)
                project_marker = f"projects/{request.project_id}/"
                if "projects/" in normalized and project_marker not in normalized:
                    raise ValidationError(
                        "Integration artifact storage scope is cross-project."
                    )
            if reference.available and not _DIGEST.fullmatch(
                reference.artifact_digest
            ):
                raise ValidationError("Integration artifact digest is malformed.")
            if reference.malformed:
                raise ValidationError("Integration artifact is marked malformed.")
            if reference.required and not reference.available:
                raise ValidationError("Required integration artifact is missing.")
            if reference.required and reference.stale:
                raise ValidationError("Required integration artifact is stale.")
            if not reference.required and not reference.available:
                warnings.append(
                    f"Optional artifact unavailable: {reference.artifact_reference_id}"
                )
            if not reference.required and reference.stale:
                warnings.append(
                    f"Optional artifact stale: {reference.artifact_reference_id}"
                )
        if set(request.artifact_reference_ids) != seen:
            raise ValidationError(
                "Integration request artifact identities do not match the envelope."
            )
        layer = self._load_layer()
        layer.signal_usage.artifact_reference_validation_used = True
        self._save_layer(layer)
        return warnings

    def validate_dependencies(
        self,
        request: BobaIntegrationRequestV1,
        transaction: BobaIntegrationTransactionV1,
        operation: BobaIntegrationOperationDescriptorV1,
        envelope: BobaIntegrationEnvelopeV1,
        context: Mapping[str, Any],
    ) -> BobaIntegrationDependencyCheckV1:
        module = self.module_registry[operation.module_id]
        required_modules = list(module.dependency_module_ids)
        context_unavailable = {
            str(item) for item in context.get("unavailable_module_ids", [])
        }
        unavailable_modules = [
            module_id
            for module_id in required_modules
            if (
                module_id not in self.module_registry
                or self.module_registry[module_id].implementation_status
                in {"unavailable", "future", "blocked"}
                or module_id in context_unavailable
            )
        ]
        available_modules = [
            module_id
            for module_id in required_modules
            if module_id not in unavailable_modules
        ]
        artifacts_by_id = {
            item.artifact_reference_id: item for item in envelope.artifact_references
        }
        required_artifact_ids: list[str] = []
        missing_artifact_ids: list[str] = []
        stale_artifact_ids: list[str] = []
        malformed_artifact_ids: list[str] = []
        for artifact_type in operation.required_artifact_types:
            matches = [
                item
                for item in envelope.artifact_references
                if item.artifact_type == artifact_type
            ]
            if not matches:
                missing_artifact_ids.append(artifact_type)
                continue
            required_artifact_ids.extend(
                item.artifact_reference_id for item in matches
            )
        for artifact_id in request.artifact_reference_ids:
            reference = artifacts_by_id.get(artifact_id)
            if reference is None or not reference.available:
                missing_artifact_ids.append(artifact_id)
            elif reference.stale:
                stale_artifact_ids.append(artifact_id)
            elif reference.malformed:
                malformed_artifact_ids.append(artifact_id)
        active_operations = {
            str(item) for item in context.get("active_target_operation_ids", [])
        }
        conflicting_run = request.target_operation_id in active_operations
        project_uncertain = bool(context.get("project_state_uncertain"))
        workflow_transition_missing = (
            operation.operation_class in _EXECUTION_OPERATION_CLASSES
            and request.requesting_module_id == "workflow_controller"
            and not bool(context.get("workflow_transition_valid"))
        )
        autopilot_missing = (
            operation.operation_class in _EXECUTION_OPERATION_CLASSES
            and request.requesting_module_id != "workflow_controller"
            and (
                request.requesting_module_id != "autopilot_controller"
                or not bool(context.get("autopilot_action_valid"))
            )
        )
        status: BobaIntegrationDependencyStatusV1 = "ready"
        reason = ""
        if malformed_artifact_ids:
            status = "malformed"
            reason = "A required artifact is malformed."
        elif stale_artifact_ids:
            status = "stale"
            reason = "A required artifact is stale."
        elif missing_artifact_ids or unavailable_modules:
            status = "missing"
            reason = "A required module or artifact is unavailable."
        elif conflicting_run:
            status = "blocked"
            reason = "The target operation already has a conflicting active run."
        elif project_uncertain:
            status = "blocked"
            reason = "The project state is uncertain."
        elif workflow_transition_missing:
            status = "blocked"
            reason = (
                "Execution requires an exact validated Workflow Controller "
                "transition."
            )
        elif autopilot_missing:
            status = "blocked"
            reason = "Execution requires an exact validated Autopilot action."
        check = BobaIntegrationDependencyCheckV1(
            dependency_check_id=_stable_id(
                "boba_integration_dependency",
                transaction.transaction_id,
                request.target_operation_id,
            ),
            transaction_id=transaction.transaction_id,
            module_id=request.target_module_id,
            operation_id=request.target_operation_id,
            required_module_ids=required_modules,
            available_module_ids=available_modules,
            unavailable_module_ids=unavailable_modules,
            required_artifact_ids=_unique(required_artifact_ids),
            available_artifact_ids=[
                item.artifact_reference_id
                for item in envelope.artifact_references
                if item.available and not item.stale and not item.malformed
            ],
            missing_artifact_ids=_unique(missing_artifact_ids),
            stale_artifact_ids=_unique(stale_artifact_ids),
            malformed_artifact_ids=_unique(malformed_artifact_ids),
            dependency_status=status,
            blocks_routing=status != "ready",
            failure_reason=reason,
            warnings=(
                [
                    (
                        "Execution Workflow Controller binding was not "
                        "independently confirmed."
                    )
                ]
                if workflow_transition_missing
                else ["Execution Autopilot binding was not independently confirmed."]
                if autopilot_missing
                else []
            ),
        )
        layer = self._load_layer()
        layer.dependency_checks = (
            [
                item
                for item in layer.dependency_checks
                if item.dependency_check_id != check.dependency_check_id
            ]
            + [check]
        )[-512:]
        layer.signal_usage.dependency_validation_used = True
        self._save_layer(layer)
        return check

    @staticmethod
    def _context_record(
        context: Mapping[str, Any],
        collection_name: str,
        record_id: str,
    ) -> dict[str, Any] | None:
        collection = context.get(collection_name)
        if not isinstance(collection, Mapping):
            return None
        value = collection.get(record_id)
        if isinstance(value, BobaContract):
            return value.model_dump(mode="json")
        return dict(value) if isinstance(value, Mapping) else None

    def verify_approval_binding(
        self,
        request: BobaIntegrationRequestV1,
        envelope: BobaIntegrationEnvelopeV1,
        operation: BobaIntegrationOperationDescriptorV1,
        context: Mapping[str, Any],
    ) -> bool:
        binding = envelope.approval_binding
        if not operation.target_approval_required and binding is None:
            return True
        if binding is None:
            raise ValidationError("Target-module approval binding is missing.")
        if binding.approval_binding_id != request.approval_binding_id:
            raise ValidationError("Approval binding identity does not match.")
        if binding.target_module_id != request.target_module_id:
            raise ValidationError("Approval target module does not match.")
        if binding.target_operation_id != request.target_operation_id:
            raise ValidationError("Approval target operation does not match.")
        if binding.approved_project_id != request.project_id:
            raise ValidationError("Approval project does not match.")
        if binding.approved_run_id and binding.approved_run_id != request.run_id:
            raise ValidationError("Approval run does not match.")
        if operation.required_approval_type and (
            binding.approval_type != operation.required_approval_type
        ):
            raise ValidationError("Approval type does not match the operation.")
        if not binding.exact_match_required or not binding.explicit_confirmation:
            raise ValidationError("Approval lacks exact explicit confirmation.")
        if binding.current_match_status != "matched":
            raise ValidationError("Approval binding is not currently matched.")
        expires_at = _parse_time(binding.approval_expires_at)
        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise ValidationError("Target-module approval has expired.")
        actual = self._context_record(
            context,
            "approval_records",
            binding.approval_record_id,
        )
        if actual is None:
            raise ValidationError("Referenced target-module approval is unavailable.")
        actual_id = str(
            actual.get("approval_id")
            or actual.get("approval_record_id")
            or ""
        )
        if actual_id != binding.approval_record_id:
            raise ValidationError("Referenced target-module approval identity changed.")
        if actual.get("approved") is False:
            raise ValidationError("Referenced target-module approval is not approved.")
        actual_confirmation = actual.get("explicit_confirmation")
        if not bool(actual_confirmation):
            raise ValidationError(
                "Referenced target-module approval lacks confirmation."
            )
        actual_digest = str(actual.get("approval_digest") or "")
        if not _DIGEST.fullmatch(actual_digest):
            actual_digest = _digest(sanitize_integration_export(actual))
        if actual_digest != binding.approval_digest:
            raise ValidationError("Referenced target-module approval digest changed.")
        actual_expiry = _parse_time(
            str(actual.get("approval_expires_at") or "") or None
        )
        if actual_expiry is not None and actual_expiry <= datetime.now(UTC):
            raise ValidationError("Referenced target-module approval has expired.")
        plan_id = str(
            request.request_parameters.get("recovery_plan_id")
            or request.request_parameters.get("approved_plan_id")
            or ""
        )
        if binding.approved_plan_id and binding.approved_plan_id != plan_id:
            raise ValidationError("Approval plan does not match.")
        strategy_id = str(
            request.request_parameters.get("recovery_strategy_id")
            or request.request_parameters.get("repair_strategy_id")
            or ""
        )
        if (
            binding.approved_strategy_id
            and binding.approved_strategy_id != strategy_id
        ):
            raise ValidationError("Approval strategy does not match.")
        artifact_digest = str(
            request.request_parameters.get("patch_digest")
            or request.request_parameters.get("artifact_digest")
            or ""
        )
        if (
            binding.approved_artifact_digest
            and binding.approved_artifact_digest != artifact_digest
        ):
            raise ValidationError("Approval patch or artifact digest does not match.")
        parameters_digest = _digest(
            sanitize_integration_export(request.request_parameters)
        )
        if (
            binding.approved_parameters_digest
            and binding.approved_parameters_digest != parameters_digest
        ):
            raise ValidationError("Approval parameters do not match.")
        layer = self._load_layer()
        layer.signal_usage.approval_binding_used = True
        self._save_layer(layer)
        return True

    def verify_safety_binding(
        self,
        request: BobaIntegrationRequestV1,
        envelope: BobaIntegrationEnvelopeV1,
        operation: BobaIntegrationOperationDescriptorV1,
        context: Mapping[str, Any],
    ) -> bool:
        binding = envelope.safety_binding
        if not operation.safety_gate_required and binding is None:
            return True
        if binding is None:
            raise ValidationError("Safety Gate decision binding is missing.")
        if binding.safety_binding_id != request.safety_binding_id:
            raise ValidationError("Safety binding identity does not match.")
        allowed_decision = (
            _ALLOWED_EXECUTION_SAFETY_DECISION
            if operation.operation_class in _EXECUTION_OPERATION_CLASSES
            else _ALLOWED_READ_ONLY_SAFETY_DECISION
        )
        if binding.decision != allowed_decision:
            raise ValidationError("Safety Gate decision does not allow this route.")
        if not binding.decision_valid:
            raise ValidationError("Safety Gate decision is not valid.")
        expires_at = _parse_time(binding.decision_expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            raise ValidationError("Safety Gate decision has expired.")
        if binding.request_digest != request.request_digest:
            raise ValidationError("Safety Gate request digest does not match.")
        if binding.project_snapshot_digest != envelope.project_snapshot_digest:
            raise ValidationError("Safety Gate project snapshot does not match.")
        if not _DIGEST.fullmatch(binding.policy_snapshot_digest):
            raise ValidationError("Safety Gate policy digest is malformed.")
        if binding.allowed_target_module != request.target_module_id:
            raise ValidationError("Safety Gate target module does not match.")
        if binding.allowed_target_operation != request.target_operation_id:
            raise ValidationError("Safety Gate target operation does not match.")
        actual = self._context_record(
            context,
            "safety_decisions",
            binding.safety_decision_id,
        )
        if actual is None:
            raise ValidationError("Referenced Safety Gate decision is unavailable.")
        comparisons = {
            "safety_case_id": binding.safety_case_id,
            "decision": binding.decision,
            "request_digest": binding.request_digest,
            "project_snapshot_digest": binding.project_snapshot_digest,
            "policy_snapshot_digest": binding.policy_snapshot_digest,
            "allowed_target_module": binding.allowed_target_module,
            "allowed_target_operation": binding.allowed_target_operation,
        }
        for field, expected in comparisons.items():
            if str(actual.get(field) or "") != expected:
                raise ValidationError(
                    f"Referenced Safety Gate {field} changed."
                )
        actual_scope = [str(item) for item in actual.get("allowed_scope", [])]
        if actual_scope != list(binding.allowed_scope):
            raise ValidationError("Safety Gate allowed scope changed.")
        if actual.get("decision_valid") is not True:
            raise ValidationError("Referenced Safety Gate decision is invalid.")
        actual_expiry = _parse_time(str(actual.get("decision_expires_at") or ""))
        if actual_expiry is None or actual_expiry <= datetime.now(UTC):
            raise ValidationError("Referenced Safety Gate decision has expired.")
        if actual.get("decision_expired") is True:
            raise ValidationError("Referenced Safety Gate decision is expired.")
        layer = self._load_layer()
        layer.signal_usage.safety_binding_used = True
        self._save_layer(layer)
        return True

    def resolve_idempotency(
        self,
        request: BobaIntegrationRequestV1,
        transaction: BobaIntegrationTransactionV1,
        operation: BobaIntegrationOperationDescriptorV1,
        context: Mapping[str, Any],
    ) -> tuple[
        BobaIntegrationIdempotencyRecordV1,
        BobaIntegrationResponseV1 | None,
    ]:
        records = self.store.load_boba_integration_idempotency_records(
            self.project_id
        )
        existing = next(
            (
                item
                for item in records
                if item.idempotency_key == request.idempotency_key
            ),
            None,
        )
        now = datetime.now(UTC)
        reusable: BobaIntegrationResponseV1 | None = None
        if existing is None:
            record = BobaIntegrationIdempotencyRecordV1(
                idempotency_record_id=_stable_id(
                    "boba_integration_idempotency_record",
                    self.project_id,
                    request.idempotency_key,
                ),
                project_id=self.project_id,
                run_id=request.run_id,
                idempotency_key=request.idempotency_key,
                operation_id=request.target_operation_id,
                request_digest=request.request_digest,
                first_transaction_id=transaction.transaction_id,
                latest_transaction_id=transaction.transaction_id,
                expires_at=(now + timedelta(days=7)).isoformat(),
                warnings=[
                    "Idempotency is local metadata, not a global exactly-once guarantee."
                ],
            )
            records.append(record)
        else:
            record = existing.model_copy(deep=True)
            if (
                record.project_id != request.project_id
                or record.run_id != request.run_id
                or record.operation_id != request.target_operation_id
                or record.request_digest != request.request_digest
            ):
                record.conflicting_request_detected = True
                record.latest_seen_at = now.isoformat()
                record.latest_transaction_id = transaction.transaction_id
                self.store.save_boba_integration_idempotency_records(
                    self.project_id,
                    [
                        record if item.idempotency_record_id == record.idempotency_record_id
                        else item
                        for item in records
                    ],
                )
                raise ValidationError(
                    "Idempotency key was reused for a changed request."
                )
            if record.completed and record.reusable_response_id:
                layer = self._load_layer()
                reusable = next(
                    (
                        item
                        for item in layer.integration_responses
                        if item.response_id == record.reusable_response_id
                    ),
                    None,
                )
                if reusable is None:
                    raise ValidationError(
                        "Idempotency response metadata is unavailable."
                    )
            elif (
                record.latest_transaction_id != transaction.transaction_id
                and operation.operation_class in _EXECUTION_OPERATION_CLASSES
                and not bool(context.get("retry_allowed"))
            ):
                raise ValidationError(
                    "Execution retry requires a new idempotency key or target policy."
                )
            if record.latest_transaction_id != transaction.transaction_id:
                record.attempt_count = min(record.attempt_count + 1, 100)
            record.latest_seen_at = now.isoformat()
            record.latest_transaction_id = transaction.transaction_id
            records = [
                record if item.idempotency_record_id == record.idempotency_record_id
                else item
                for item in records
            ]
        self.store.save_boba_integration_idempotency_records(
            self.project_id,
            records,
        )
        layer = self._load_layer()
        layer.idempotency_records = records[-512:]
        layer.signal_usage.idempotency_used = operation.idempotency_required
        self._save_layer(layer)
        return record, reusable

    @staticmethod
    def _classify_validation_failure(
        message: str,
    ) -> BobaIntegrationFailureClassV1:
        folded = message.casefold()
        if "idempotency" in folded:
            return "idempotency_conflict"
        if "approval" in folded:
            if "expired" in folded:
                return "approval_expired"
            if "missing" in folded or "unavailable" in folded:
                return "approval_missing"
            return "approval_invalid"
        if "safety gate" in folded or "safety binding" in folded:
            if "expired" in folded:
                return "safety_decision_expired"
            if "missing" in folded or "unavailable" in folded:
                return "safety_decision_missing"
            return "safety_decision_invalid"
        if "rights" in folded:
            return "rights_blocked"
        if "schema" in folded:
            return "schema_incompatible"
        if "stale" in folded:
            return "stale_artifact"
        if "malformed" in folded and "artifact" in folded:
            return "malformed_artifact"
        if "artifact" in folded or "dependency" in folded or "autopilot" in folded:
            return "missing_dependency"
        if "project" in folded:
            return "project_mismatch"
        if "run" in folded:
            return "run_mismatch"
        if "operation" in folded:
            return "unknown_operation"
        if "module" in folded:
            return "unknown_module"
        return "invalid_request"

    async def validate_request_envelope(
        self,
        envelope: BobaIntegrationEnvelopeV1,
    ) -> BobaIntegrationTransactionV1:
        """Validate a request fully and persist a ready or blocked transaction."""

        request = self._request_from_envelope(envelope)
        transaction = self.store.load_boba_integration_transaction(
            request.project_id,
            envelope.transaction_id,
        )
        if transaction is None:
            transaction = self.create_transaction(request, envelope)
            self._remember_request(envelope, request, transaction)
            self._append_event(
                transaction,
                "request_received",
                technical_message="Typed integration request received.",
                easy_message="BOBA received a request for a registered module.",
                confirmed_fact=(
                    f"Requested operation: {request.target_operation_id}."
                ),
            )
        elif transaction.state in _TERMINAL_TRANSACTION_STATES:
            return transaction

        transaction = transaction.model_copy(deep=True)
        transaction.state = "validating"
        self._remember_transaction(transaction)
        try:
            if envelope.envelope_type != "request":
                raise ValidationError("Integration envelope is not a request.")
            if envelope.project_id != self.project_id:
                raise ValidationError("Integration request project does not match.")
            if not await self._project_is_available():
                raise ValidationError("Integration request project is missing.")
            if envelope.producer_module_id not in self.module_registry:
                raise ValidationError("Unknown requesting BOBA module.")
            if envelope.consumer_module_id not in self.module_registry:
                raise ValidationError("Unknown target BOBA module.")
            operation = self.operation_registry.get(
                envelope.consumer_operation_id
            )
            if operation is None:
                raise ValidationError("Unknown BOBA integration operation.")
            if operation.module_id != envelope.consumer_module_id:
                raise ValidationError(
                    "Integration operation does not belong to the target module."
                )
            module = self.module_registry[operation.module_id]
            if module.implementation_status == "future" or operation.future_gated:
                return self.record_integration_failure(
                    transaction,
                    failure_class="future_gated",
                    failure_code="integration_future_gated",
                    title="Future action is not available",
                    summary=(
                        "This registered operation has no V1 target handler and "
                        "remains future-gated."
                    ),
                    state="future_gated",
                )
            if operation.prohibited:
                return self.record_integration_failure(
                    transaction,
                    failure_class="prohibited",
                    failure_code="integration_operation_prohibited",
                    title="Operation is prohibited",
                    summary=(
                        "Integration Layer V1 refuses this operation and did not "
                        "invoke a target."
                    ),
                    state="blocked",
                )
            if module.implementation_status in {"unavailable", "blocked"}:
                raise ValidationError("Target module is unavailable.")
            if _parse_time(envelope.expires_at) is None:
                raise ValidationError("Integration request expiry is malformed.")
            if _parse_time(envelope.expires_at) <= datetime.now(UTC):  # type: ignore[operator]
                raise ValidationError("Integration request has expired.")
            parameters = _validate_bounded_payload(envelope.bounded_payload)
            if parameters != request.request_parameters:
                raise ValidationError("Integration request payload changed.")
            if envelope.payload_digest != _digest(parameters):
                raise ValidationError("Integration payload digest does not match.")
            expected_digest = _digest(
                _request_digest_payload(
                    project_id=request.project_id,
                    run_id=request.run_id,
                    requesting_module_id=request.requesting_module_id,
                    target_module_id=request.target_module_id,
                    target_operation_id=request.target_operation_id,
                    request_schema_id=request.request_schema_id,
                    request_schema_version=request.request_schema_version,
                    request_parameters=request.request_parameters,
                    artifact_reference_ids=request.artifact_reference_ids,
                    approval_binding=envelope.approval_binding,
                    safety_binding=envelope.safety_binding,
                    project_snapshot_digest=envelope.project_snapshot_digest,
                )
            )
            if request.request_digest != expected_digest:
                raise ValidationError("Integration request digest does not match.")
            context = await self._request_context(request)
            expected_run_id = str(context.get("expected_run_id") or "")
            if expected_run_id and expected_run_id != request.run_id:
                raise ValidationError("Integration request run does not match.")
            if (
                operation.operation_class in _EXECUTION_OPERATION_CLASSES
                and not _DIGEST.fullmatch(envelope.project_snapshot_digest)
            ):
                raise ValidationError(
                    "Execution request project snapshot digest is missing."
                )
            compatibility = self.validate_schema_compatibility(
                request,
                transaction,
                operation,
            )
            transaction.compatibility_check_ids = [
                compatibility.compatibility_check_id
            ]
            self._append_event(
                transaction,
                "compatibility_checked",
                technical_message=(
                    f"Schema compatibility status: "
                    f"{compatibility.compatibility_status}."
                ),
                easy_message=(
                    "BOBA checked that the sending and receiving modules "
                    "understand the same request format."
                ),
                confirmed_fact=compatibility.compatibility_status,
                assessment=compatibility.failure_reason,
                requires_attention=(
                    compatibility.compatibility_status
                    not in {
                        "compatible",
                        "compatible_with_safe_normalization",
                    }
                ),
            )
            if compatibility.compatibility_status not in {
                "compatible",
                "compatible_with_safe_normalization",
            }:
                raise ValidationError(
                    compatibility.failure_reason
                    or "Integration request schema is incompatible."
                )
            artifact_warnings = self.validate_artifact_references(
                request,
                envelope,
            )
            dependency = self.validate_dependencies(
                request,
                transaction,
                operation,
                envelope,
                context,
            )
            transaction.dependency_check_ids = [dependency.dependency_check_id]
            transaction.warnings = _unique(
                [*transaction.warnings, *artifact_warnings]
            )
            self._append_event(
                transaction,
                "dependencies_checked",
                technical_message=(
                    f"Dependency status: {dependency.dependency_status}."
                ),
                easy_message=(
                    "BOBA checked the required modules and saved artifacts."
                ),
                confirmed_fact=dependency.dependency_status,
                assessment=dependency.failure_reason,
                requires_attention=dependency.blocks_routing,
            )
            if dependency.blocks_routing:
                raise ValidationError(
                    dependency.failure_reason
                    or "Integration request dependency validation failed."
                )
            if operation.rights_gate_required and not bool(
                context.get("rights_allowed")
            ):
                raise ValidationError("Rights Gate did not allow this route.")
            transaction.approval_binding_valid = self.verify_approval_binding(
                request,
                envelope,
                operation,
                context,
            )
            self._append_event(
                transaction,
                "approval_checked",
                technical_message="Target approval binding checked.",
                easy_message=(
                    "BOBA checked the exact target approval when one was required."
                ),
                confirmed_fact=(
                    "Approval binding valid."
                    if transaction.approval_binding_valid
                    else "Approval binding not required."
                ),
            )
            transaction.safety_binding_valid = self.verify_safety_binding(
                request,
                envelope,
                operation,
                context,
            )
            self._append_event(
                transaction,
                "safety_checked",
                technical_message="Safety Gate binding checked.",
                easy_message=(
                    "BOBA checked the current Safety Gate decision when required."
                ),
                confirmed_fact=(
                    "Safety binding valid."
                    if transaction.safety_binding_valid
                    else "Safety binding not required."
                ),
            )
            record, reusable = self.resolve_idempotency(
                request,
                transaction,
                operation,
                context,
            )
            transaction.idempotency_record_id = record.idempotency_record_id
            self._append_event(
                transaction,
                "idempotency_checked",
                technical_message="Local integration idempotency metadata checked.",
                easy_message=(
                    "BOBA checked whether this exact request already completed."
                ),
                confirmed_fact=(
                    "Reusable response found."
                    if reusable
                    else "No reusable response found."
                ),
            )
            if reusable is not None:
                transaction.state = "duplicate_reused"
                transaction.response_id = reusable.response_id
                transaction.completed_at = now_iso()
                self._remember_transaction(transaction)
                self._append_event(
                    transaction,
                    "response_reused",
                    technical_message="Saved typed response reused.",
                    easy_message=(
                        "This exact request already succeeded, so BOBA returned "
                        "the saved result instead of running it again."
                    ),
                    confirmed_fact=f"Response {reusable.response_id} reused.",
                )
                return transaction
            transaction.state = "ready"
            transaction.validated_at = now_iso()
            self._remember_transaction(transaction)
            self._append_event(
                transaction,
                "request_validated",
                technical_message="Typed integration request is ready to route.",
                easy_message=(
                    "BOBA validated this request. No target action has run yet."
                ),
                confirmed_fact="Transaction state is ready.",
            )
            return transaction
        except ValidationError as exc:
            failure_class = self._classify_validation_failure(str(exc))
            self.record_integration_failure(
                transaction,
                failure_class=failure_class,
                failure_code=f"integration_{failure_class}",
                title="Integration request validation failed",
                summary=str(exc),
                state="blocked",
            )
            raise

    async def create_validated_request(
        self,
        **kwargs: Any,
    ) -> tuple[
        BobaIntegrationEnvelopeV1,
        BobaIntegrationRequestV1,
        BobaIntegrationTransactionV1,
    ]:
        envelope = self.create_request_envelope(**kwargs)
        transaction = await self.validate_request_envelope(envelope)
        return envelope, self._request_from_envelope(envelope), transaction

    def _request_records(
        self,
        transaction: BobaIntegrationTransactionV1,
    ) -> tuple[BobaIntegrationEnvelopeV1, BobaIntegrationRequestV1]:
        layer = self._load_layer()
        request = next(
            (
                item
                for item in layer.integration_requests
                if item.request_id == transaction.request_id
            ),
            None,
        )
        envelope = next(
            (
                item
                for item in layer.request_envelopes
                if request is not None and item.envelope_id == request.envelope_id
            ),
            None,
        )
        if request is None or envelope is None:
            raise ValidationError(
                "Integration transaction request metadata is unavailable."
            )
        return envelope, request

    @staticmethod
    def _response_status_for_failure(
        failure_class: BobaIntegrationFailureClassV1,
    ) -> BobaIntegrationResponseStatusV1:
        if failure_class == "future_gated":
            return "future_gated"
        if failure_class == "schema_incompatible":
            return "incompatible"
        if failure_class == "target_unavailable":
            return "unavailable"
        if failure_class == "target_rejected":
            return "rejected"
        if failure_class == "target_timed_out":
            return "timed_out"
        if failure_class in {"target_failed", "internal_integration_error"}:
            return "failed"
        return "blocked"

    def _persist_response(
        self,
        envelope: BobaIntegrationEnvelopeV1,
        response: BobaIntegrationResponseV1,
    ) -> None:
        layer = self._load_layer()
        layer.response_envelopes = (
            [
                item
                for item in layer.response_envelopes
                if item.envelope_id != envelope.envelope_id
            ]
            + [envelope]
        )[-256:]
        layer.integration_responses = (
            [
                item
                for item in layer.integration_responses
                if item.response_id != response.response_id
            ]
            + [response]
        )[-256:]
        self._save_layer(layer)

    def _build_response_records(
        self,
        transaction: BobaIntegrationTransactionV1,
        request_envelope: BobaIntegrationEnvelopeV1,
        request: BobaIntegrationRequestV1,
        *,
        status: BobaIntegrationResponseStatusV1,
        result: Mapping[str, Any],
        failure_id: str = "",
        idempotency_reused: bool = False,
        warnings: Sequence[str] = (),
        limitations: Sequence[str] = (),
    ) -> tuple[BobaIntegrationEnvelopeV1, BobaIntegrationResponseV1]:
        bounded_result = _validate_bounded_payload(
            sanitize_integration_export(result),
            path="response",
        )
        response_id = _stable_id(
            "boba_integration_response",
            transaction.transaction_id,
            status,
            failure_id,
        )
        target_module = self.module_registry.get(request.target_module_id)
        response_envelope = BobaIntegrationEnvelopeV1(
            envelope_id=_stable_id(
                "boba_integration_response_envelope",
                response_id,
            ),
            envelope_type="response",
            schema_id=request.expected_response_schema_id,
            schema_version="1.0",
            producer_module_id=request.target_module_id,
            producer_module_version=(
                target_module.module_version if target_module else "unknown"
            ),
            consumer_module_id=request.requesting_module_id,
            consumer_operation_id=request.target_operation_id,
            project_id=request.project_id,
            source_id=request_envelope.source_id,
            run_id=request.run_id,
            correlation_id=transaction.correlation_id,
            transaction_id=transaction.transaction_id,
            expires_at=(datetime.now(UTC) + timedelta(days=7)).isoformat(),
            idempotency_key=request.idempotency_key,
            project_snapshot_digest=request_envelope.project_snapshot_digest,
            payload_digest=_digest(bounded_result),
            artifact_references=[],
            bounded_payload=bounded_result,
            warnings=_unique(warnings),
        )
        response = BobaIntegrationResponseV1(
            response_id=response_id,
            request_id=request.request_id,
            envelope_id=response_envelope.envelope_id,
            project_id=request.project_id,
            run_id=request.run_id,
            target_module_id=request.target_module_id,
            target_operation_id=request.target_operation_id,
            status=status,
            response_schema_id=request.expected_response_schema_id,
            response_schema_version="1.0",
            bounded_result=bounded_result,
            result_digest=_digest(bounded_result),
            idempotency_reused=idempotency_reused,
            failure_id=failure_id,
            warnings=_unique(warnings),
            limitations=_unique(limitations),
        )
        return response_envelope, response

    def _build_handoff(
        self,
        failure: BobaIntegrationFailureV1,
        transaction: BobaIntegrationTransactionV1,
    ) -> BobaIntegrationHandoffV1:
        target_module = "autopilot_controller"
        if failure.failure_class.startswith("safety_decision"):
            target_module = "safety_gate"
        elif failure.failure_class in {
            "schema_incompatible",
            "missing_dependency",
            "stale_artifact",
            "malformed_artifact",
        }:
            target_module = "repair_planner"
        elif failure.failure_class in {
            "target_failed",
            "target_timed_out",
            "internal_integration_error",
        }:
            target_module = "root_cause_analyzer"
        elif failure.failure_class == "rights_blocked":
            target_module = "rights_permission_gate"
        elif failure.failure_class == "future_gated":
            target_module = (
                "checkpoint_recovery_manager"
                if "checkpoint" in transaction.target_operation_id
                else "workflow_controller"
            )
        human_review = failure.failure_class in {
            "approval_missing",
            "approval_invalid",
            "approval_expired",
            "safety_decision_missing",
            "safety_decision_invalid",
            "safety_decision_expired",
            "rights_blocked",
            "project_mismatch",
            "run_mismatch",
            "future_gated",
            "prohibited",
        }
        return BobaIntegrationHandoffV1(
            handoff_id=_stable_id(
                "boba_integration_handoff",
                failure.failure_id,
                target_module,
            ),
            transaction_id=transaction.transaction_id,
            source_module_id="integration_layer",
            target_module_id=target_module,
            reason=failure.bounded_summary,
            unresolved_dependencies=[failure.failure_code],
            approval_required=failure.failure_class.startswith("approval_"),
            safety_decision_required=failure.failure_class.startswith(
                "safety_decision"
            ),
            human_review_required=human_review,
            allowed_actions=["inspect", "provide_missing_evidence", "retry_with_new_key"],
            prohibited_actions=[
                "bypass_approval",
                "bypass_safety",
                "invoke_unregistered_operation",
            ],
            apply_automatically=False,
            priority=(
                "high"
                if failure.failure_class
                in {
                    "target_failed",
                    "target_timed_out",
                    "safety_decision_invalid",
                }
                else "medium"
            ),
        )

    def record_integration_failure(
        self,
        transaction: BobaIntegrationTransactionV1,
        *,
        failure_class: BobaIntegrationFailureClassV1,
        failure_code: str,
        title: str,
        summary: str,
        state: BobaIntegrationTransactionStateV1,
        source_layer: Literal[
            "integration_layer",
            "autopilot_controller",
            "safety_gate",
            "target_module",
            "rights_permission_gate",
            "unknown",
        ] = "integration_layer",
        retryable: bool = False,
        safe_to_retry: bool = False,
        project_state_uncertain: bool = False,
    ) -> BobaIntegrationTransactionV1:
        """Persist a bounded typed failure without converting it to success."""

        current = transaction.model_copy(deep=True)
        envelope, request = self._request_records(current)
        failure = BobaIntegrationFailureV1(
            failure_id=_new_runtime_id("boba_integration_failure"),
            transaction_id=current.transaction_id,
            project_id=current.project_id,
            run_id=current.run_id,
            failure_class=failure_class,
            failure_code=_text(failure_code, maximum=160),
            title=_text(title, maximum=240),
            bounded_summary=_text(summary, maximum=1_200),
            source_layer=source_layer,
            source_module_id=(
                current.target_module_id
                if source_layer == "target_module"
                else source_layer
            ),
            source_operation_id=current.target_operation_id,
            retryable=retryable,
            safe_to_retry=safe_to_retry,
            requires_reapproval=failure_class.startswith("approval_"),
            requires_new_safety_decision=failure_class.startswith(
                "safety_decision"
            ),
            project_state_uncertain=project_state_uncertain,
            recommended_target_module=(
                "root_cause_analyzer"
                if source_layer == "target_module"
                else "autopilot_controller"
            ),
        )
        response_envelope, response = self._build_response_records(
            current,
            envelope,
            request,
            status=self._response_status_for_failure(failure_class),
            result={
                "failure_id": failure.failure_id,
                "failure_code": failure.failure_code,
                "summary": failure.bounded_summary,
                "source_layer": failure.source_layer,
                "nothing_executed": not current.target_invocation_started,
            },
            failure_id=failure.failure_id,
            warnings=["The failure remains visible and was not reclassified."],
            limitations=["No automatic alternative target was selected."],
        )
        current.failure_id = failure.failure_id
        current.response_id = response.response_id
        current.state = state
        current.completed_at = now_iso()
        current.target_invocation_completed = (
            current.target_invocation_started
            and failure_class
            in {"target_rejected", "target_failed", "target_timed_out"}
        )
        handoff = self._build_handoff(failure, current)
        layer = self._load_layer()
        layer.integration_failures = [
            *layer.integration_failures,
            failure,
        ][-512:]
        layer.integration_handoffs = [
            *layer.integration_handoffs,
            handoff,
        ][-512:]
        self._save_layer(layer)
        self._persist_response(response_envelope, response)
        self._remember_transaction(current)
        event_type: BobaIntegrationEventTypeV1 = (
            "future_action_blocked"
            if failure_class in {"future_gated", "prohibited"}
            else (
                "target_failed"
                if source_layer == "target_module"
                else "transaction_blocked"
            )
        )
        self._append_event(
            current,
            event_type,
            technical_message=failure.bounded_summary,
            easy_message=(
                "BOBA stopped this request safely. Nothing was reported as "
                "successful."
            ),
            severity="error",
            confirmed_fact=f"Failure class: {failure.failure_class}.",
            assessment=failure.title,
            requires_attention=True,
        )
        return current

    def record_typed_response(
        self,
        transaction: BobaIntegrationTransactionV1,
        request_envelope: BobaIntegrationEnvelopeV1,
        request: BobaIntegrationRequestV1,
        *,
        result: Mapping[str, Any],
        target_revalidated: bool,
        side_effects: Sequence[Any],
    ) -> BobaIntegrationResponseV1:
        response_envelope, response = self._build_response_records(
            transaction,
            request_envelope,
            request,
            status="succeeded",
            result=result,
            limitations=[
                "The response reports only target-module returned metadata."
            ],
        )
        current = transaction.model_copy(deep=True)
        current.response_id = response.response_id
        current.state = "succeeded"
        current.completed_at = now_iso()
        current.target_invocation_completed = True
        current.target_independent_revalidation_confirmed = target_revalidated
        current.side_effects_reported = _unique(side_effects)
        self._persist_response(response_envelope, response)
        self._remember_transaction(current)
        records = self.store.load_boba_integration_idempotency_records(
            request.project_id
        )
        updated_records: list[BobaIntegrationIdempotencyRecordV1] = []
        for record in records:
            if record.idempotency_key != request.idempotency_key:
                updated_records.append(record)
                continue
            updated = record.model_copy(deep=True)
            updated.completed = True
            updated.reusable_response_id = response.response_id
            updated.latest_transaction_id = current.transaction_id
            updated.latest_seen_at = now_iso()
            updated_records.append(updated)
        self.store.save_boba_integration_idempotency_records(
            request.project_id,
            updated_records,
        )
        layer = self._load_layer()
        layer.idempotency_records = updated_records[-512:]
        self._save_layer(layer)
        self._append_event(
            current,
            "target_completed",
            technical_message="Registered typed target operation completed.",
            easy_message="The registered BOBA module returned a result.",
            confirmed_fact=f"Response {response.response_id} was recorded.",
            assessment=(
                "Target independent revalidation confirmed."
                if target_revalidated
                else "Target revalidation was not required for this route."
            ),
        )
        self._append_event(
            current,
            "transaction_completed",
            technical_message="Integration transaction succeeded.",
            easy_message="BOBA finished routing this typed request.",
            confirmed_fact="Transaction state is succeeded.",
        )
        return response

    async def route_typed_request(
        self,
        transaction_id: str,
    ) -> BobaIntegrationResponseV1:
        """Revalidate and invoke one fixed registered handler."""

        transaction = self.inspect_transaction(transaction_id)
        layer = self._load_layer()
        if transaction.state in _TERMINAL_TRANSACTION_STATES:
            response = next(
                (
                    item
                    for item in layer.integration_responses
                    if item.response_id == transaction.response_id
                ),
                None,
            )
            if response is None:
                raise ValidationError(
                    "Terminal integration transaction response is unavailable."
                )
            if transaction.state == "duplicate_reused":
                reused = response.model_copy(deep=True)
                reused.status = "duplicate_reused"
                reused.idempotency_reused = True
                return reused
            return response
        request_envelope, request = self._request_records(transaction)
        transaction = await self.validate_request_envelope(request_envelope)
        if transaction.state == "duplicate_reused":
            return await self.route_typed_request(transaction.transaction_id)
        if transaction.state != "ready":
            return await self.route_typed_request(transaction.transaction_id)
        operation = self.operation_registry[request.target_operation_id]
        handler = self._handlers.get(request.target_operation_id)
        if handler is None:
            blocked = self.record_integration_failure(
                transaction,
                failure_class="target_unavailable",
                failure_code="integration_target_handler_unavailable",
                title="Registered target handler is unavailable",
                summary=(
                    "The operation is registered, but this application instance "
                    "has no fixed typed handler for it."
                ),
                state="blocked",
            )
            return await self.route_typed_request(blocked.transaction_id)
        transaction = transaction.model_copy(deep=True)
        transaction.state = "routing"
        transaction.routed_at = now_iso()
        self._remember_transaction(transaction)
        self._append_event(
            transaction,
            "routing_started",
            technical_message="Fixed registered operation handler selected.",
            easy_message=(
                "BOBA selected the built-in typed route for this operation."
            ),
            confirmed_fact=request.target_operation_id,
        )
        transaction.state = "target_running"
        transaction.target_invocation_started = True
        self._remember_transaction(transaction)
        self._append_event(
            transaction,
            "target_started",
            technical_message="Typed target invocation started.",
            easy_message="The registered target module started its own operation.",
            confirmed_fact=f"Target module: {request.target_module_id}.",
        )
        try:
            target_result = handler(request)
            if inspect.isawaitable(target_result):
                target_result = await asyncio.wait_for(
                    target_result,
                    timeout=request.timeout_seconds,
                )
            result_payload = _json_value(target_result)
            if not isinstance(result_payload, Mapping):
                raise ValidationError("Target handler returned a non-object result.")
            internal = dict(result_payload)
            target_revalidated = bool(
                internal.pop("_integration_target_revalidated", False)
            )
            side_effects = internal.pop("_integration_side_effects", [])
            target_status = str(
                internal.pop("_integration_target_status", "succeeded")
            )
            if target_status in {"rejected", "blocked"}:
                rejected = self.record_integration_failure(
                    transaction,
                    failure_class="target_rejected",
                    failure_code="integration_target_rejected",
                    title="Target module rejected the request",
                    summary=str(
                        internal.get("reason")
                        or internal.get("message")
                        or "The target module rejected the typed request."
                    ),
                    state="failed",
                    source_layer="target_module",
                )
                return await self.route_typed_request(rejected.transaction_id)
            if (
                operation.operation_class in _EXECUTION_OPERATION_CLASSES
                and not target_revalidated
            ):
                rejected = self.record_integration_failure(
                    transaction,
                    failure_class="target_rejected",
                    failure_code="integration_target_revalidation_missing",
                    title="Target revalidation was not confirmed",
                    summary=(
                        "The execution-capable target did not independently "
                        "confirm approval and Safety bindings."
                    ),
                    state="failed",
                    source_layer="target_module",
                )
                return await self.route_typed_request(rejected.transaction_id)
            bounded = _validate_bounded_payload(
                sanitize_integration_export(internal),
                path="target_result",
            )
            layer = self._load_layer()
            layer.signal_usage.typed_target_invocation_used = True
            self._save_layer(layer)
            return self.record_typed_response(
                transaction,
                request_envelope,
                request,
                result=bounded,
                target_revalidated=target_revalidated,
                side_effects=(
                    list(side_effects)
                    if isinstance(side_effects, list | tuple | set)
                    else []
                ),
            )
        except TimeoutError:
            timed_out = self.record_integration_failure(
                transaction,
                failure_class="target_timed_out",
                failure_code="integration_target_timeout",
                title="Target module timed out",
                summary=(
                    "The registered target did not return before the declared "
                    "timeout."
                ),
                state="timed_out",
                source_layer="target_module",
                retryable=True,
            )
            return await self.route_typed_request(timed_out.transaction_id)
        except ValidationError as exc:
            rejected = self.record_integration_failure(
                transaction,
                failure_class="target_rejected",
                failure_code="integration_target_validation_rejected",
                title="Target module rejected the typed request",
                summary=str(exc),
                state="failed",
                source_layer="target_module",
            )
            return await self.route_typed_request(rejected.transaction_id)
        except Exception as exc:
            failed = self.record_integration_failure(
                transaction,
                failure_class="target_failed",
                failure_code="integration_target_failure",
                title="Target module failed",
                summary=_text(exc, maximum=1_200),
                state="failed",
                source_layer="target_module",
                retryable=False,
                project_state_uncertain=(
                    operation.operation_class in _EXECUTION_OPERATION_CLASSES
                ),
            )
            return await self.route_typed_request(failed.transaction_id)

    def inspect_transaction(
        self,
        transaction_id: str,
    ) -> BobaIntegrationTransactionV1:
        if not _SAFE_ID.fullmatch(transaction_id):
            raise ValidationError("Invalid Integration Layer transaction id.")
        transaction = self.store.load_boba_integration_transaction(
            self.project_id,
            transaction_id,
        )
        if transaction is None:
            raise ValidationError("Integration transaction was not found.")
        return transaction

    def inspect_transaction_events(
        self,
        transaction_id: str,
    ) -> list[BobaIntegrationEventV1]:
        self.inspect_transaction(transaction_id)
        return self.store.load_boba_integration_events(
            self.project_id,
            transaction_id,
        )

    def export_integration_layer(self) -> dict[str, Any]:
        return self.store.export_boba_integration_layer(self.project_id)

    def reset_integration_metadata(self) -> dict[str, Any]:
        return self.store.reset_boba_integration_layer(self.project_id)


__all__ = [
    "BobaIntegrationApprovalBindingV1",
    "BobaIntegrationArtifactReferenceV1",
    "BobaIntegrationCompatibilityCheckV1",
    "BobaIntegrationDependencyCheckV1",
    "BobaIntegrationEnvelopeV1",
    "BobaIntegrationEventV1",
    "BobaIntegrationFailureV1",
    "BobaIntegrationHandoffV1",
    "BobaIntegrationIdempotencyRecordV1",
    "BobaIntegrationLayerSetV1",
    "BobaIntegrationLayerV1",
    "BobaIntegrationModuleDescriptorV1",
    "BobaIntegrationOperationDescriptorV1",
    "BobaIntegrationRegistrySnapshotV1",
    "BobaIntegrationRequestV1",
    "BobaIntegrationResponseV1",
    "BobaIntegrationSafetyBindingV1",
    "BobaIntegrationSignalUsageV1",
    "BobaIntegrationSummaryV1",
    "BobaIntegrationTransactionV1",
    "build_boba_module_registry",
    "build_boba_operation_registry",
    "calculate_integration_request_digest",
    "sanitize_integration_export",
    "validate_boba_registry_descriptors",
]

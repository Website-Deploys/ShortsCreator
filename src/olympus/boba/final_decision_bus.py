"""Deterministic, source-authority-preserving final dispatch decisions for BOBA.

Final Decision Bus V1 accepts only fixed action policies and exact persisted
source records. It evaluates policy readiness, records an immutable final
disposition, and may create a bounded single-use dispatch envelope. It never
executes, repairs, changes source decisions, advances workflow state, or
modifies media, artifacts, code, approvals, Safety, Rights, validation, or
quality records.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ConfigDict, Field, field_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.integration_layer import build_boba_operation_registry
from olympus.platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore


BobaFinalAuthorityDomainV1 = Literal[
    "rights",
    "safety",
    "approval",
    "workflow",
    "technical_validation",
    "output_quality",
    "artifact_integrity",
    "recovery",
    "checkpoint",
    "human_decision",
    "report_context",
    "integration",
    "unknown",
]
BobaFinalAvailabilityV1 = Literal["available", "degraded", "unavailable", "future", "unknown"]
BobaFinalActionClassV1 = Literal[
    "exact_internal_workflow_transition",
    "exact_internal_stage_continuation",
    "exact_internal_recovery_execution",
    "exact_internal_code_repair_execution",
    "exact_registered_validation_execution",
    "exact_internal_output_acceptance_handoff",
    "exact_internal_completion_handoff",
    "exact_internal_dispatch",
    "unknown",
]
BobaFinalDispositionV1 = Literal[
    "ready_for_exact_internal_dispatch",
    "hold_missing_evidence",
    "hold_stale_evidence",
    "hold_conflicting_evidence",
    "hold_human_review",
    "blocked_by_rights",
    "blocked_by_safety",
    "blocked_by_target_approval",
    "blocked_by_validation",
    "blocked_by_quality",
    "blocked_by_artifact_integrity",
    "blocked_by_workflow_state",
    "blocked_by_recovery_state",
    "blocked_by_policy",
    "blocked_by_budget",
    "rejected",
    "expired",
    "invalid",
    "cancelled",
    "unknown",
]
BobaFinalConflictTypeV1 = Literal[
    "project_identity_conflict",
    "workflow_identity_conflict",
    "stage_identity_conflict",
    "clip_identity_conflict",
    "output_identity_conflict",
    "artifact_identity_conflict",
    "digest_conflict",
    "action_conflict",
    "decision_conflict",
    "status_conflict",
    "approval_conflict",
    "rights_conflict",
    "safety_conflict",
    "validation_conflict",
    "quality_conflict",
    "artifact_integrity_conflict",
    "workflow_state_conflict",
    "recovery_state_conflict",
    "lifecycle_conflict",
    "supersession_conflict",
    "unknown",
]
BobaFinalIncidentTypeV1 = Literal[
    "invalid_request",
    "unknown_action",
    "unavailable_action",
    "wrong_source_owner",
    "unsupported_schema",
    "digest_mismatch",
    "identity_mismatch",
    "missing_required_evidence",
    "stale_required_evidence",
    "expired_required_decision",
    "invalidated_required_decision",
    "superseded_required_decision",
    "conflicting_authority",
    "rights_block",
    "safety_block",
    "approval_block",
    "validation_block",
    "quality_block",
    "artifact_block",
    "workflow_block",
    "recovery_block",
    "policy_mismatch",
    "registry_mismatch",
    "idempotency_conflict",
    "concurrency_conflict",
    "dispatch_expired",
    "uncertain_state",
    "unknown",
]
BobaFinalEventTypeV1 = Literal[
    "request_created",
    "request_validated",
    "source_binding_validated",
    "evidence_requirement_satisfied",
    "evidence_requirement_missing",
    "stale_evidence_detected",
    "conflict_detected",
    "policy_evaluation_started",
    "policy_evaluation_completed",
    "final_decision_ready",
    "final_decision_held",
    "final_decision_blocked",
    "human_review_required",
    "dispatch_envelope_created",
    "dispatch_envelope_expired",
    "dispatch_envelope_consumed",
    "decision_invalidated",
    "unknown",
]

_MAX_SOURCE_BINDINGS = 64
_MAX_EVIDENCE_BINDINGS = 128
_MAX_REQUIREMENTS = 128
_MAX_CONFLICTS = 256
_MAX_INCIDENTS = 256
_MAX_ACTIVE_ENVELOPES = 8
_MAX_EVENTS = 2_000
_MAX_REQUEST_BYTES = 1_000_000
_MAX_DISPATCH_TTL_SECONDS = 900
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,180}$")
_DIGEST = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$", re.IGNORECASE)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *values: object) -> str:
    return f"{prefix}_{_digest(list(values))[:24]}"


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


def _expired(value: str | None) -> bool:
    parsed = _parse_time(value)
    return parsed is not None and parsed <= datetime.now(UTC)


def _safe_text(value: object, maximum: int = 1_200) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    text = re.sub(r"[A-Za-z]:\\[^\s\"']+", "[private-path-redacted]", text)
    text = re.sub(r"/(?:home|Users|root|var|tmp)/[^\s\"']+", "[private-path-redacted]", text)
    text = re.sub(r"(?i)(?:token|secret|password|credential)=[^\s,;]+", "[redacted]", text)
    return text[:maximum]


def _safe_id(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not _ID.fullmatch(normalized):
        raise ValidationError(f"{label} must be a fixed typed identifier.")
    return normalized


def _validate_digest(value: str, label: str) -> str:
    normalized = str(value or "").strip().casefold()
    if not normalized or not _DIGEST.fullmatch(normalized):
        raise ValidationError(f"{label} must be a SHA-256 digest.")
    return normalized.removeprefix("sha256:")


def sanitize_final_decision_export(value: Any) -> Any:
    """Return bounded metadata without raw reports, logs, media, paths, or secrets."""

    blocked = {
        "raw_body",
        "content",
        "data",
        "path",
        "absolute_path",
        "resolved_path",
        "stdout",
        "stderr",
        "traceback",
        "token",
        "secret",
        "password",
        "credential",
        "authorization",
        "cookie",
        "media_bytes",
        "source_code",
        "raw_patch",
        "command",
        "shell_command",
        "callable",
        "callable_path",
    }
    if isinstance(value, BobaContract):
        return sanitize_final_decision_export(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:512]:
            key = _safe_text(raw_key, 120)
            if not key:
                continue
            if key.casefold() in blocked or re.search(
                r"token|secret|password|credential", key, re.I
            ):
                result[key] = "[redacted]"
            else:
                result[key] = sanitize_final_decision_export(raw_value)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_final_decision_export(item) for item in list(value)[:2048]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value, 4_000)


def _sanitized_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_final_decision_export(value)
    if not isinstance(sanitized, dict):
        raise ValidationError("Final Decision Bus export must remain a JSON object.")
    return {str(key): item for key, item in sanitized.items()}


class BobaFinalDecisionRegistrySnapshotV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = Field(default="1", min_length=1, max_length=80)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    decision_source_ids: list[str] = Field(default_factory=list, max_length=64)
    action_policy_ids: list[str] = Field(default_factory=list, max_length=64)
    available_source_ids: list[str] = Field(default_factory=list, max_length=64)
    unavailable_source_ids: list[str] = Field(default_factory=list, max_length=64)
    future_source_ids: list[str] = Field(default_factory=list, max_length=64)
    available_action_ids: list[str] = Field(default_factory=list, max_length=64)
    unavailable_action_ids: list[str] = Field(default_factory=list, max_length=64)
    source_registry_digest: str = Field(min_length=64, max_length=64)
    action_policy_registry_digest: str = Field(min_length=64, max_length=64)
    combined_registry_digest: str = Field(min_length=64, max_length=64)
    immutable: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaDecisionSourceDescriptorV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_source_id: str = Field(min_length=1, max_length=160)
    producer_module_id: str = Field(min_length=1, max_length=160)
    authority_domain: BobaFinalAuthorityDomainV1
    decision_record_type: str = Field(min_length=1, max_length=160)
    schema_id: str = Field(min_length=1, max_length=160)
    supported_schema_versions: list[str] = Field(default_factory=lambda: ["1"], max_length=16)
    decision_field: str = Field(default="decision", max_length=120)
    status_field: str = Field(default="decision", max_length=120)
    identity_fields: list[str] = Field(default_factory=list, max_length=32)
    digest_fields: list[str] = Field(default_factory=list, max_length=32)
    freshness_fields: list[str] = Field(default_factory=list, max_length=32)
    expiration_supported: bool = False
    invalidation_supported: bool = False
    supersession_supported: bool = False
    blocking_statuses: list[str] = Field(default_factory=list, max_length=32)
    ready_statuses: list[str] = Field(default_factory=list, max_length=32)
    advisory_only: bool = False
    current_state_capable: bool = True
    historical_capable: bool = True
    required_original_record: bool = True
    availability: BobaFinalAvailabilityV1 = "available"
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaFinalActionPolicyV1(BobaContract):
    """A fixed, source-owned authorization policy for one registered action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_policy_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=240)
    action_class: BobaFinalActionClassV1
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=180)
    exact_target_required: Literal[True] = True
    internal_only: Literal[True] = True
    executable_target: bool = True
    availability: BobaFinalAvailabilityV1 = "available"
    required_decision_source_ids: list[str] = Field(default_factory=list, max_length=32)
    optional_decision_source_ids: list[str] = Field(default_factory=list, max_length=32)
    required_authority_domains: list[BobaFinalAuthorityDomainV1] = Field(
        default_factory=list, max_length=16
    )
    required_identity_fields: list[str] = Field(default_factory=list, max_length=24)
    required_evidence_kinds: list[str] = Field(default_factory=list, max_length=32)
    required_current_state: bool = True
    requires_target_independent_revalidation: Literal[True] = True
    requires_explicit_human_confirmation: bool = False
    requires_valid_lease: bool = True
    dispatch_ttl_seconds: int = Field(default=300, ge=30, le=_MAX_DISPATCH_TTL_SECONDS)
    max_concurrent_envelopes: int = Field(default=1, ge=1, le=_MAX_ACTIVE_ENVELOPES)
    allowed_decision_values: list[str] = Field(default_factory=list, max_length=24)
    forbidden_decision_values: list[str] = Field(default_factory=list, max_length=32)
    policy_digest: str = Field(min_length=64, max_length=64)
    immutable: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaFinalDecisionSourceSelectorV1(BobaContract):
    """An exact request reference to an existing, owner-controlled record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_source_id: str = Field(min_length=1, max_length=160)
    producer_record_id: str = Field(min_length=1, max_length=180)
    expected_record_digest: str = Field(default="", max_length=72)
    required: bool = True

    @field_validator("expected_record_digest")
    @classmethod
    def validate_expected_digest(cls, value: str) -> str:
        return _validate_digest(value, "Expected source record digest") if value else ""


class BobaFinalDecisionRequestV1(BobaContract):
    """A bounded request to adjudicate one exact registered internal action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    final_decision_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    source_id: str = Field(min_length=1, max_length=512)
    requested_by_module: str = Field(min_length=1, max_length=160)
    action_policy_id: str = Field(min_length=1, max_length=160)
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(default="", max_length=180)
    stage_instance_id: str = Field(default="", max_length=180)
    clip_id: str = Field(default="", max_length=180)
    output_id: str = Field(default="", max_length=180)
    artifact_reference_id: str = Field(default="", max_length=180)
    project_snapshot_digest: str = Field(default="", max_length=72)
    workflow_snapshot_digest: str = Field(default="", max_length=72)
    target_parameters_digest: str = Field(default="", max_length=72)
    source_selectors: list[BobaFinalDecisionSourceSelectorV1] = Field(
        default_factory=list, max_length=_MAX_SOURCE_BINDINGS
    )
    source_decision_binding_ids: list[str] = Field(default_factory=list, max_length=64)
    requested_at: str = Field(default_factory=now_iso, max_length=80)
    expires_at: str = Field(
        default_factory=lambda: (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        max_length=80,
    )
    request_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=180)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    @field_validator(
        "project_snapshot_digest", "workflow_snapshot_digest", "target_parameters_digest"
    )
    @classmethod
    def validate_optional_digest(cls, value: str) -> str:
        return _validate_digest(value, "Decision request digest") if value else ""


class BobaFinalDecisionSourceBindingV1(BobaContract):
    """A sanitized, immutable binding to a source-owned decision record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_binding_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    decision_source_id: str = Field(min_length=1, max_length=160)
    authority_domain: BobaFinalAuthorityDomainV1
    producer_module_id: str = Field(min_length=1, max_length=160)
    producer_record_id: str = Field(min_length=1, max_length=180)
    producer_record_type: str = Field(min_length=1, max_length=160)
    producer_schema_id: str = Field(default="", max_length=160)
    producer_schema_version: str = Field(default="1", max_length=80)
    canonical_record_digest: str = Field(min_length=64, max_length=64)
    expected_record_digest: str = Field(default="", max_length=64)
    observed_decision: str = Field(default="unknown", max_length=160)
    observed_status: str = Field(default="unknown", max_length=160)
    project_identity_match: bool = False
    workflow_identity_match: bool | None = None
    stage_identity_match: bool | None = None
    clip_identity_match: bool | None = None
    output_identity_match: bool | None = None
    artifact_identity_match: bool | None = None
    target_identity_match: bool | None = None
    digest_match: bool = False
    current_state: bool | None = None
    expired: bool = False
    invalidated: bool = False
    superseded: bool = False
    valid: bool = False
    authoritative: bool = True
    advisory_only: bool = False
    collected_at: str = Field(default_factory=now_iso, max_length=80)
    expires_at: str = Field(default="", max_length=80)
    sanitized_record: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaFinalDecisionEvidenceRequirementV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_requirement_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    action_policy_id: str = Field(min_length=1, max_length=160)
    decision_source_id: str = Field(default="", max_length=160)
    authority_domain: BobaFinalAuthorityDomainV1 = "unknown"
    evidence_kind: str = Field(min_length=1, max_length=160)
    required: bool = True
    requires_current_state: bool = True
    requires_exact_identity: bool = True
    acceptable_decision_values: list[str] = Field(default_factory=list, max_length=24)
    blocking_decision_values: list[str] = Field(default_factory=list, max_length=32)
    bounded_reason: str = Field(default="", max_length=1200)


class BobaFinalDecisionEvidenceBindingV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_binding_id: str = Field(min_length=1, max_length=180)
    evidence_requirement_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    source_binding_id: str = Field(default="", max_length=180)
    status: Literal["satisfied", "missing", "stale", "invalid", "blocked", "unknown"] = "unknown"
    satisfied: bool = False
    bounded_reason: str = Field(default="", max_length=1200)
    created_at: str = Field(default_factory=now_iso, max_length=80)


class BobaFinalDecisionConflictV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conflict_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    conflict_type: BobaFinalConflictTypeV1
    severity: Literal["info", "warning", "error", "critical", "unknown"] = "warning"
    source_binding_ids: list[str] = Field(default_factory=list, max_length=32)
    unresolved: bool = True
    bounded_summary: str = Field(default="", max_length=1200)
    created_at: str = Field(default_factory=now_iso, max_length=80)


class BobaFinalDecisionPolicyEvaluationV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_evaluation_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    action_policy_id: str = Field(min_length=1, max_length=160)
    policy_digest: str = Field(min_length=64, max_length=64)
    registry_digest: str = Field(min_length=64, max_length=64)
    disposition: BobaFinalDispositionV1 = "unknown"
    request_valid: bool = False
    source_bindings_valid: bool = False
    evidence_complete: bool = False
    evidence_current: bool = False
    conflicts_resolved: bool = False
    lease_available: bool = False
    required_revalidation: bool = True
    ordered_checks: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    evidence_binding_ids: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_BINDINGS)
    conflict_ids: list[str] = Field(default_factory=list, max_length=_MAX_CONFLICTS)
    incident_ids: list[str] = Field(default_factory=list, max_length=_MAX_INCIDENTS)
    decision_reasons: list[str] = Field(default_factory=list, max_length=128)
    warnings: list[str] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=128)
    evaluated_at: str = Field(default_factory=now_iso, max_length=80)


class BobaFinalDecisionV1(BobaContract):
    """Immutable adjudication result; it never represents target execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    final_decision_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    policy_evaluation_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    action_policy_id: str = Field(min_length=1, max_length=160)
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=180)
    registry_digest: str = Field(min_length=64, max_length=64)
    policy_digest: str = Field(min_length=64, max_length=64)
    request_digest: str = Field(min_length=64, max_length=64)
    source_binding_digests: list[str] = Field(default_factory=list, max_length=_MAX_SOURCE_BINDINGS)
    evidence_binding_ids: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_BINDINGS)
    conflict_ids: list[str] = Field(default_factory=list, max_length=_MAX_CONFLICTS)
    disposition: BobaFinalDispositionV1
    ready_for_dispatch: bool = False
    target_execution_authorized: Literal[False] = False
    source_decision_ownership_preserved: Literal[True] = True
    required_target_revalidation: Literal[True] = True
    invalidated: bool = False
    invalidated_at: str = Field(default="", max_length=80)
    invalidation_reason: str = Field(default="", max_length=1200)
    expires_at: str = Field(default="", max_length=80)
    decision_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=128)


class BobaFinalDispatchEnvelopeV1(BobaContract):
    """A single-use route authorization, not an instruction to execute."""

    model_config = ConfigDict(extra="forbid")

    dispatch_envelope_id: str = Field(min_length=1, max_length=180)
    final_decision_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    action_policy_id: str = Field(min_length=1, max_length=160)
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=180)
    request_digest: str = Field(min_length=64, max_length=64)
    decision_digest: str = Field(min_length=64, max_length=64)
    dispatch_digest: str = Field(min_length=64, max_length=64)
    issued_at: str = Field(default_factory=now_iso, max_length=80)
    expires_at: str = Field(min_length=1, max_length=80)
    single_use: Literal[True] = True
    consumed: bool = False
    consumed_at: str = Field(default="", max_length=80)
    consumption_transaction_id: str = Field(default="", max_length=180)
    target_independent_revalidation_required: Literal[True] = True
    target_execution_authorized: Literal[False] = False
    valid: bool = True
    invalidated: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaFinalDecisionLeaseV1(BobaContract):
    model_config = ConfigDict(extra="forbid")

    final_decision_lease_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    action_policy_id: str = Field(min_length=1, max_length=160)
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    final_decision_id: str = Field(default="", max_length=180)
    lease_key: str = Field(min_length=1, max_length=180)
    acquired_at: str = Field(default_factory=now_iso, max_length=80)
    expires_at: str = Field(min_length=1, max_length=80)
    state: Literal["active", "released", "expired", "invalidated"] = "active"
    release_reason: str = Field(default="", max_length=1200)


class BobaFinalDecisionIncidentV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(default="", max_length=180)
    final_decision_id: str = Field(default="", max_length=180)
    incident_type: BobaFinalIncidentTypeV1
    severity: Literal["info", "warning", "error", "critical", "unknown"] = "warning"
    bounded_summary: str = Field(default="", max_length=1600)
    fingerprint: str = Field(min_length=1, max_length=180)
    occurrence_count: int = Field(default=1, ge=1)
    created_at: str = Field(default_factory=now_iso, max_length=80)


class BobaFinalDecisionEventV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(default="", max_length=180)
    final_decision_id: str = Field(default="", max_length=180)
    dispatch_envelope_id: str = Field(default="", max_length=180)
    sequence: int = Field(ge=1)
    event_type: BobaFinalEventTypeV1
    technical_message: str = Field(default="", max_length=1600)
    easy_message: str = Field(default="", max_length=1600)
    confirmed_fact: str = Field(default="", max_length=1600)
    severity: Literal["info", "warning", "error", "critical", "unknown"] = "info"
    requires_attention: bool = False
    created_at: str = Field(default_factory=now_iso, max_length=80)


class BobaFinalDecisionHandoffV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    handoff_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    final_decision_id: str = Field(default="", max_length=180)
    dispatch_envelope_id: str = Field(default="", max_length=180)
    target_module_id: str = Field(default="", max_length=160)
    target_operation_id: str = Field(default="", max_length=180)
    handoff_state: Literal["informational", "ready_for_revalidation", "blocked", "invalidated"] = (
        "informational"
    )
    exact_revalidation_required: Literal[True] = True
    execution_performed: Literal[False] = False
    bounded_reason: str = Field(default="", max_length=1600)
    created_at: str = Field(default_factory=now_iso, max_length=80)


class BobaFinalDecisionSummaryV1(BobaContract):
    model_config = ConfigDict(extra="forbid")

    registry_snapshot_count: int = 0
    request_count: int = 0
    source_binding_count: int = 0
    policy_evaluation_count: int = 0
    final_decision_count: int = 0
    ready_decision_count: int = 0
    active_envelope_count: int = 0
    consumed_envelope_count: int = 0
    incident_count: int = 0
    safest_next_action: str = Field(
        default="Inspect authoritative source records; do not execute targets.", max_length=1200
    )
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaFinalDecisionSignalUsageV1(BobaContract):
    model_config = ConfigDict(extra="forbid")

    fixed_source_registry_used: bool = False
    fixed_action_policy_registry_used: bool = False
    persisted_owner_records_read: bool = False
    dynamic_source_discovery_used: Literal[False] = False
    arbitrary_file_read_used: Literal[False] = False
    source_decision_modified: Literal[False] = False
    rights_bypass_used: Literal[False] = False
    safety_bypass_used: Literal[False] = False
    approval_creation_used: Literal[False] = False
    validation_execution_used: Literal[False] = False
    workflow_transition_used: Literal[False] = False
    target_execution_used: Literal[False] = False
    repair_execution_used: Literal[False] = False
    code_execution_used: Literal[False] = False
    shell_execution_used: Literal[False] = False
    git_execution_used: Literal[False] = False
    ffmpeg_execution_used: Literal[False] = False
    media_modification_used: Literal[False] = False
    artifact_modification_used: Literal[False] = False
    checkpoint_restore_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_used: Literal[False] = False
    upload_used: Literal[False] = False
    publication_used: Literal[False] = False
    push_used: Literal[False] = False
    merge_used: Literal[False] = False
    deployment_used: Literal[False] = False


class BobaFinalDecisionInvalidationV1(BobaContract):
    """Append-only invalidation record; immutable decisions are never rewritten."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    final_decision_invalidation_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    final_decision_id: str = Field(min_length=1, max_length=180)
    final_decision_request_id: str = Field(min_length=1, max_length=180)
    reason: str = Field(min_length=1, max_length=1200)
    invalidated_by_module: str = Field(min_length=1, max_length=160)
    invalidated_at: str = Field(default_factory=now_iso, max_length=80)
    invalidation_digest: str = Field(min_length=64, max_length=64)


class BobaFinalDecisionBusSetV1(BobaContract):
    """The project-scoped persisted state for Final Decision Bus V1."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["boba_final_decision_bus_v1"] = "boba_final_decision_bus_v1"
    project_id: str = Field(min_length=1, max_length=180)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    registry_snapshots: list[BobaFinalDecisionRegistrySnapshotV1] = Field(
        default_factory=list, max_length=32
    )
    decision_source_descriptors: list[BobaDecisionSourceDescriptorV1] = Field(
        default_factory=list, max_length=64
    )
    action_policies: list[BobaFinalActionPolicyV1] = Field(default_factory=list, max_length=64)
    decision_requests: list[BobaFinalDecisionRequestV1] = Field(
        default_factory=list, max_length=512
    )
    source_bindings: list[BobaFinalDecisionSourceBindingV1] = Field(
        default_factory=list, max_length=4096
    )
    evidence_requirements: list[BobaFinalDecisionEvidenceRequirementV1] = Field(
        default_factory=list, max_length=4096
    )
    evidence_bindings: list[BobaFinalDecisionEvidenceBindingV1] = Field(
        default_factory=list, max_length=8192
    )
    conflicts: list[BobaFinalDecisionConflictV1] = Field(default_factory=list, max_length=8192)
    policy_evaluations: list[BobaFinalDecisionPolicyEvaluationV1] = Field(
        default_factory=list, max_length=2048
    )
    final_decisions: list[BobaFinalDecisionV1] = Field(default_factory=list, max_length=2048)
    dispatch_envelopes: list[BobaFinalDispatchEnvelopeV1] = Field(
        default_factory=list, max_length=2048
    )
    leases: list[BobaFinalDecisionLeaseV1] = Field(default_factory=list, max_length=2048)
    invalidations: list[BobaFinalDecisionInvalidationV1] = Field(
        default_factory=list, max_length=2048
    )
    incidents: list[BobaFinalDecisionIncidentV1] = Field(default_factory=list, max_length=4096)
    events: list[BobaFinalDecisionEventV1] = Field(default_factory=list, max_length=_MAX_EVENTS)
    handoffs: list[BobaFinalDecisionHandoffV1] = Field(default_factory=list, max_length=4096)
    summary: BobaFinalDecisionSummaryV1 = Field(default_factory=BobaFinalDecisionSummaryV1)
    signal_usage: BobaFinalDecisionSignalUsageV1 = Field(
        default_factory=BobaFinalDecisionSignalUsageV1
    )
    limitations: list[str] = Field(default_factory=list, max_length=128)


def _final_source_descriptor(
    decision_source_id: str,
    producer_module_id: str,
    authority_domain: BobaFinalAuthorityDomainV1,
    decision_record_type: str,
    *,
    decision_field: str = "decision",
    status_field: str = "decision",
    identity_fields: Sequence[str] = (),
    digest_fields: Sequence[str] = (),
    freshness_fields: Sequence[str] = (),
    expiration_supported: bool = False,
    invalidation_supported: bool = False,
    supersession_supported: bool = False,
    blocking_statuses: Sequence[str] = (),
    ready_statuses: Sequence[str] = (),
    advisory_only: bool = False,
    availability: BobaFinalAvailabilityV1 = "available",
    limitations: Sequence[str] = (),
) -> BobaDecisionSourceDescriptorV1:
    return BobaDecisionSourceDescriptorV1(
        decision_source_id=decision_source_id,
        producer_module_id=producer_module_id,
        authority_domain=authority_domain,
        decision_record_type=decision_record_type,
        schema_id=f"boba.{decision_source_id}",
        decision_field=decision_field,
        status_field=status_field,
        identity_fields=list(identity_fields),
        digest_fields=list(digest_fields),
        freshness_fields=list(freshness_fields),
        expiration_supported=expiration_supported,
        invalidation_supported=invalidation_supported,
        supersession_supported=supersession_supported,
        blocking_statuses=list(blocking_statuses),
        ready_statuses=list(ready_statuses),
        advisory_only=advisory_only,
        availability=availability,
        limitations=list(limitations),
    )


def build_fixed_final_decision_source_registry() -> dict[str, BobaDecisionSourceDescriptorV1]:
    """Return the V1 source list; requests cannot add or replace descriptors."""

    descriptors = [
        _final_source_descriptor(
            "rights_permission_gate",
            "rights_permission_gate",
            "rights",
            "BobaRightsGateDecisionV1",
            status_field="gate_status",
            identity_fields=("project_id", "source_id"),
            blocking_statuses=("blocked", "needs_permission", "needs_rights_review"),
            ready_statuses=("ready_for_human_review",),
            limitations=(
                "Rights Gate does not grant arbitrary execution authority.",
                "A bound blocking Rights record blocks this bus decision.",
            ),
        ),
        _final_source_descriptor(
            "safety_gate",
            "safety_gate",
            "safety",
            "BobaSafetyDecisionV1",
            identity_fields=("project_id", "target_module_id", "target_operation_id"),
            digest_fields=("request_digest", "snapshot_digest", "policy_digest"),
            freshness_fields=("valid", "expires_at"),
            expiration_supported=True,
            invalidation_supported=True,
            blocking_statuses=(
                "denied",
                "blocked",
                "needs_human_review",
                "needs_more_evidence",
            ),
            ready_statuses=("allowed_for_exact_internal_execution",),
        ),
        _final_source_descriptor(
            "target_approval",
            "integration_layer",
            "approval",
            "BobaIntegrationApprovalBindingV1",
            decision_field="approval_type",
            status_field="approval_type",
            identity_fields=(
                "approved_project_id",
                "target_module_id",
                "target_operation_id",
            ),
            digest_fields=("approval_digest", "approved_parameters_digest"),
            freshness_fields=("current_match", "expires_at"),
            expiration_supported=True,
            invalidation_supported=True,
            blocking_statuses=("revoked", "rejected", "expired"),
            ready_statuses=("target_module_exact",),
        ),
        _final_source_descriptor(
            "workflow_controller",
            "workflow_controller",
            "workflow",
            "BobaWorkflowTransitionDecisionV1",
            identity_fields=("project_id", "workflow_run_id", "stage_instance_id"),
            digest_fields=("workflow_snapshot_digest",),
            freshness_fields=("valid", "expires_at"),
            expiration_supported=True,
            invalidation_supported=True,
            blocking_statuses=("blocked", "denied", "cancelled", "paused"),
            ready_statuses=("allowed", "ready"),
        ),
        _final_source_descriptor(
            "human_decision",
            "workflow_controller",
            "human_decision",
            "BobaWorkflowHumanDecisionV1",
            decision_field="decision",
            identity_fields=("project_id", "workflow_run_id", "stage_instance_id"),
            digest_fields=("snapshot_digest",),
            freshness_fields=("current_snapshot", "expires_at"),
            expiration_supported=True,
            invalidation_supported=True,
            blocking_statuses=("rejected", "denied", "cancelled"),
            ready_statuses=("approved", "confirmed"),
        ),
        _final_source_descriptor(
            "validator_runner",
            "validator_runner",
            "technical_validation",
            "BobaValidationSuiteDecisionV1",
            identity_fields=("project_id", "workflow_run_id", "stage_instance_id"),
            freshness_fields=("target_current", "snapshot_current"),
            blocking_statuses=("failed", "incomplete", "blocked"),
            ready_statuses=("passed", "passed_with_warnings"),
        ),
        _final_source_descriptor(
            "output_quality_reviewer",
            "output_quality_reviewer",
            "output_quality",
            "BobaOutputAcceptanceDecisionV1",
            identity_fields=("project_id", "clip_id", "output_id"),
            freshness_fields=("current",),
            blocking_statuses=("rejected", "blocked", "needs_human_review"),
            ready_statuses=("accepted",),
        ),
        _final_source_descriptor(
            "artifact_inspector",
            "artifact_inspector",
            "artifact_integrity",
            "BobaArtifactIntegrityAssessmentV1",
            status_field="status",
            identity_fields=("project_id", "artifact_reference_id"),
            freshness_fields=("status",),
            blocking_statuses=(
                "missing",
                "inaccessible",
                "digest_mismatch",
                "partial",
                "malformed",
            ),
            ready_statuses=("verified",),
        ),
        _final_source_descriptor(
            "autopilot_controller",
            "autopilot_controller",
            "checkpoint",
            "BobaAutopilotDecisionV1",
            identity_fields=("project_id", "workflow_run_id", "stage_instance_id"),
            freshness_fields=("valid", "expires_at"),
            expiration_supported=True,
            invalidation_supported=True,
            blocking_statuses=("blocked", "paused", "cancelled"),
            ready_statuses=("ready", "approved"),
            limitations=(
                "Autopilot is advisory to Final Decision Bus and cannot override owners.",
            ),
        ),
        _final_source_descriptor(
            "repair_planner",
            "repair_planner",
            "recovery",
            "BobaRepairPlanV1",
            identity_fields=("project_id",),
            blocking_statuses=("blocked", "rejected"),
            ready_statuses=("ready", "approved"),
            limitations=(
                "Repair plans do not authorize execution; an owner approval is required.",
            ),
        ),
        _final_source_descriptor(
            "code_surgeon",
            "code_surgeon",
            "recovery",
            "BobaCodeApprovalRecordV1",
            identity_fields=("project_id", "case_id"),
            digest_fields=("patch_digest", "base_digest"),
            freshness_fields=("current_match", "expires_at"),
            expiration_supported=True,
            invalidation_supported=True,
            blocking_statuses=("rejected", "revoked", "expired"),
            ready_statuses=("approved",),
        ),
        _final_source_descriptor(
            "tool_recovery_brain",
            "tool_recovery_brain",
            "recovery",
            "BobaToolRecoveryPlanV1",
            identity_fields=("project_id", "case_id", "plan_id"),
            digest_fields=("strategy_digest",),
            freshness_fields=("current_match", "expires_at"),
            expiration_supported=True,
            invalidation_supported=True,
            blocking_statuses=("rejected", "revoked", "expired"),
            ready_statuses=("approved",),
        ),
        _final_source_descriptor(
            "report_reader",
            "report_reader",
            "report_context",
            "BobaReportEvidenceBundleV1",
            identity_fields=("project_id",),
            advisory_only=True,
            blocking_statuses=(),
            ready_statuses=(),
            limitations=(
                "Report Reader is advisory only and cannot satisfy an authoritative requirement.",
            ),
        ),
    ]
    return {item.decision_source_id: item for item in descriptors}


def _final_action_policy(
    action_policy_id: str,
    display_name: str,
    action_class: BobaFinalActionClassV1,
    target_module_id: str,
    target_operation_id: str,
    *,
    required_sources: Sequence[str],
    optional_sources: Sequence[str] = (),
    required_domains: Sequence[BobaFinalAuthorityDomainV1] = (),
    required_evidence_kinds: Sequence[str] = (),
    requires_human: bool = False,
    ttl_seconds: int = 300,
    limitations: Sequence[str] = (),
) -> BobaFinalActionPolicyV1:
    operation = build_boba_operation_registry().get(f"{target_module_id}.{target_operation_id}")
    availability: BobaFinalAvailabilityV1 = "available"
    warnings: list[str] = []
    if operation is None:
        availability = "unavailable"
        warnings.append("Integration Layer does not register this exact operation.")
    elif operation.prohibited:
        availability = "unavailable"
        warnings.append("The registered operation is prohibited.")
    elif operation.future_gated:
        availability = "future"
        warnings.append("The registered operation remains future-gated.")
    payload = {
        "action_policy_id": action_policy_id,
        "action_class": action_class,
        "target_module_id": target_module_id,
        "target_operation_id": target_operation_id,
        "required_sources": list(required_sources),
        "optional_sources": list(optional_sources),
        "required_domains": list(required_domains),
        "required_evidence_kinds": list(required_evidence_kinds),
        "requires_human": requires_human,
        "ttl_seconds": ttl_seconds,
        "registry_version": "1",
    }
    return BobaFinalActionPolicyV1(
        action_policy_id=action_policy_id,
        display_name=display_name,
        action_class=action_class,
        target_module_id=target_module_id,
        target_operation_id=target_operation_id,
        executable_target=operation is not None
        and not operation.prohibited
        and not operation.future_gated,
        availability=availability,
        required_decision_source_ids=list(required_sources),
        optional_decision_source_ids=list(optional_sources),
        required_authority_domains=list(required_domains),
        required_identity_fields=(
            ["project_id", "target_module_id", "target_operation_id"]
            + (
                ["workflow_run_id", "stage_instance_id"]
                if "workflow_controller" in required_sources
                else []
            )
        ),
        required_evidence_kinds=list(required_evidence_kinds or required_sources),
        requires_explicit_human_confirmation=requires_human,
        dispatch_ttl_seconds=ttl_seconds,
        allowed_decision_values=(
            [
                "allowed_for_exact_internal_execution",
                "approved",
                "accepted",
                "passed",
                "verified",
                "allowed",
            ]
        ),
        forbidden_decision_values=(
            ["denied", "blocked", "rejected", "failed", "invalid", "expired", "cancelled"]
        ),
        policy_digest=_digest(payload),
        warnings=warnings,
        limitations=[
            *limitations,
            "The bus only creates a dispatch envelope; it does not execute this target.",
            "Integration Layer and the target must independently revalidate every envelope.",
        ],
    )


def build_fixed_final_action_policy_registry() -> dict[str, BobaFinalActionPolicyV1]:
    """Return static policies bound only to known Integration Layer operations."""

    policies = [
        _final_action_policy(
            "exact_registered_validation_execution",
            "Exact registered validation execution",
            "exact_registered_validation_execution",
            "validator_runner",
            "execute_run",
            required_sources=("safety_gate", "target_approval"),
            optional_sources=(
                "rights_permission_gate",
                "workflow_controller",
                "artifact_inspector",
            ),
            required_domains=("safety", "approval"),
            ttl_seconds=180,
            limitations=("Validation Runner owns validation execution and result determination.",),
        ),
        _final_action_policy(
            "exact_internal_workflow_transition",
            "Exact internal workflow transition",
            "exact_internal_workflow_transition",
            "workflow_controller",
            "coordinate_approved_internal_transition",
            required_sources=(
                "safety_gate",
                "target_approval",
                "workflow_controller",
                "artifact_inspector",
            ),
            optional_sources=("rights_permission_gate", "human_decision", "validator_runner"),
            required_domains=("safety", "approval", "workflow", "artifact_integrity"),
            ttl_seconds=180,
        ),
        _final_action_policy(
            "exact_internal_completion_handoff",
            "Exact internal completion handoff",
            "exact_internal_completion_handoff",
            "workflow_controller",
            "complete_internal_output",
            required_sources=(
                "safety_gate",
                "target_approval",
                "workflow_controller",
                "validator_runner",
                "output_quality_reviewer",
                "artifact_inspector",
            ),
            optional_sources=("rights_permission_gate", "human_decision", "autopilot_controller"),
            required_domains=(
                "safety",
                "approval",
                "workflow",
                "technical_validation",
                "output_quality",
                "artifact_integrity",
            ),
            ttl_seconds=180,
        ),
        _final_action_policy(
            "exact_internal_recovery_execution",
            "Exact internal recovery execution",
            "exact_internal_recovery_execution",
            "tool_recovery_brain",
            "execute_approved",
            required_sources=(
                "safety_gate",
                "target_approval",
                "workflow_controller",
                "artifact_inspector",
                "tool_recovery_brain",
            ),
            optional_sources=("rights_permission_gate", "human_decision", "validator_runner"),
            required_domains=("safety", "approval", "workflow", "artifact_integrity", "recovery"),
            requires_human=True,
            ttl_seconds=120,
        ),
        _final_action_policy(
            "exact_internal_code_repair_execution",
            "Exact internal code repair execution",
            "exact_internal_code_repair_execution",
            "code_surgeon",
            "execute_approved",
            required_sources=(
                "safety_gate",
                "target_approval",
                "workflow_controller",
                "artifact_inspector",
                "code_surgeon",
            ),
            optional_sources=("rights_permission_gate", "human_decision", "validator_runner"),
            required_domains=("safety", "approval", "workflow", "artifact_integrity", "recovery"),
            requires_human=True,
            ttl_seconds=120,
        ),
        _final_action_policy(
            "exact_internal_editing_preparation",
            "Exact internal editing preparation",
            "exact_internal_stage_continuation",
            "olympus_editing",
            "prepare_render",
            required_sources=(
                "safety_gate",
                "target_approval",
                "workflow_controller",
                "artifact_inspector",
            ),
            optional_sources=("rights_permission_gate", "validator_runner", "autopilot_controller"),
            required_domains=("safety", "approval", "workflow", "artifact_integrity"),
            ttl_seconds=180,
        ),
        _final_action_policy(
            "exact_internal_render",
            "Exact internal rendering",
            "exact_internal_stage_continuation",
            "olympus_rendering",
            "render",
            required_sources=(
                "safety_gate",
                "target_approval",
                "workflow_controller",
                "artifact_inspector",
            ),
            optional_sources=("rights_permission_gate", "validator_runner", "autopilot_controller"),
            required_domains=("safety", "approval", "workflow", "artifact_integrity"),
            ttl_seconds=180,
            limitations=(
                "Rendering independently verifies its timeline and artifact prerequisites.",
            ),
        ),
    ]
    return {item.action_policy_id: item for item in policies}


def build_final_decision_registries() -> tuple[
    BobaFinalDecisionRegistrySnapshotV1,
    list[BobaDecisionSourceDescriptorV1],
    list[BobaFinalActionPolicyV1],
]:
    """Build deterministic, immutable source and action policy registry metadata."""

    source_registry = build_fixed_final_decision_source_registry()
    action_registry = build_fixed_final_action_policy_registry()
    descriptors = list(source_registry.values())
    policies = list(action_registry.values())
    source_digest = _digest([item.model_dump(mode="json") for item in descriptors])
    action_digest = _digest([item.model_dump(mode="json") for item in policies])
    combined_digest = _digest(
        {"source_registry_digest": source_digest, "action_policy_registry_digest": action_digest}
    )
    created_at = now_iso()
    snapshot = BobaFinalDecisionRegistrySnapshotV1(
        registry_snapshot_id=_stable_id("final_decision_registry", combined_digest, created_at),
        created_at=created_at,
        decision_source_ids=sorted(source_registry),
        action_policy_ids=sorted(action_registry),
        available_source_ids=sorted(
            key for key, item in source_registry.items() if item.availability == "available"
        ),
        unavailable_source_ids=sorted(
            key for key, item in source_registry.items() if item.availability == "unavailable"
        ),
        future_source_ids=sorted(
            key for key, item in source_registry.items() if item.availability == "future"
        ),
        available_action_ids=sorted(
            key for key, item in action_registry.items() if item.availability == "available"
        ),
        unavailable_action_ids=sorted(
            key for key, item in action_registry.items() if item.availability != "available"
        ),
        source_registry_digest=source_digest,
        action_policy_registry_digest=action_digest,
        combined_registry_digest=combined_digest,
        limitations=[
            "Registries are code-defined and cannot be changed by API request data.",
            "Report Reader remains advisory only.",
        ],
    )
    return snapshot, descriptors, policies


def _record_payload(record: Any) -> dict[str, Any]:
    if isinstance(record, BobaContract):
        return record.model_dump(mode="json")
    if isinstance(record, Mapping):
        return dict(record)
    raise ValidationError("Final Decision Bus source records must be typed JSON objects.")


def _record_identifier(payload: Mapping[str, Any]) -> str:
    for field_name in (
        "decision_id",
        "safety_decision_id",
        "transition_decision_id",
        "human_decision_id",
        "suite_decision_id",
        "acceptance_decision_id",
        "integrity_assessment_id",
        "approval_binding_id",
        "approval_id",
        "approval_record_id",
        "approval_gate_id",
        "recovery_plan_id",
        "bundle_id",
        "report_bundle_id",
    ):
        value = str(payload.get(field_name) or "").strip()
        if value:
            return value
    return ""


def _value(payload: Mapping[str, Any], *field_names: str) -> str:
    for field_name in field_names:
        value = payload.get(field_name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _optional_match(expected: str, actual: str) -> bool | None:
    if not expected:
        return None
    if not actual:
        return None
    return expected == actual


def _normal_status(value: str) -> str:
    return str(value or "").strip().casefold()


def _status_from_record(payload: Mapping[str, Any]) -> str:
    return (
        _value(
            payload,
            "decision",
            "gate_status",
            "status",
            "approval_status",
            "approval_type",
            "integrity_status",
        )
        or "unknown"
    )


def _source_expiration(payload: Mapping[str, Any]) -> str:
    return _value(
        payload,
        "decision_expires_at",
        "approval_expires_at",
        "expires_at",
    )


def _source_current_state(payload: Mapping[str, Any]) -> bool | None:
    values: list[bool] = []
    for field_name in (
        "decision_valid",
        "current_match",
        "project_snapshot_current",
        "workflow_revision_current",
        "target_current",
        "snapshot_current",
        "technical_validation_passed",
        "quality_clear",
        "checkpoint_clear",
    ):
        field_value = payload.get(field_name)
        if isinstance(field_value, bool):
            values.append(field_value)
    current_match_status = _normal_status(str(payload.get("current_match_status") or ""))
    if current_match_status:
        values.append(current_match_status in {"match", "current", "exact_match"})
    if not values:
        return None
    return all(values)


class BobaFinalDecisionBusV1:
    """Read-only final adjudication and exact dispatch-envelope producer."""

    def __init__(self, store: BobaMemoryStore) -> None:
        self.store = store

    def _bus(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
    ) -> BobaFinalDecisionBusSetV1:
        existing = self.store.load_boba_final_decision_bus(project_id)
        if existing is not None:
            return existing
        if not source_id:
            raise NotFoundError("BOBA Final Decision Bus is unavailable for this project.")
        created = BobaFinalDecisionBusSetV1(project_id=project_id, source_id=source_id)
        self.store.save_boba_final_decision_bus(created)
        return created

    def build_final_decision_registries(
        self,
        project_id: str,
        *,
        source_id: str,
    ) -> BobaFinalDecisionRegistrySnapshotV1:
        bus = self._bus(project_id, source_id=source_id)
        snapshot, descriptors, policies = build_final_decision_registries()
        existing = next(
            (
                item
                for item in bus.registry_snapshots
                if item.combined_registry_digest == snapshot.combined_registry_digest
            ),
            None,
        )
        if existing is None:
            bus.registry_snapshots.append(snapshot)
            bus.decision_source_descriptors = descriptors
            bus.action_policies = policies
        bus.signal_usage.fixed_source_registry_used = True
        bus.signal_usage.fixed_action_policy_registry_used = True
        self._refresh_summary(bus)
        self.store.save_boba_final_decision_bus(bus)
        return existing or snapshot

    def inspect_final_decision_registries(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        bus = self._bus(project_id, source_id=source_id)
        if not bus.registry_snapshots:
            self.build_final_decision_registries(project_id, source_id=bus.source_id)
            bus = self._bus(project_id)
        snapshot = bus.registry_snapshots[-1]
        return {
            "schema_version": "boba_final_decision_bus_registry_v1",
            "project_id": project_id,
            "registry_snapshot": snapshot.model_dump(mode="json"),
            "decision_sources": [
                item.model_dump(mode="json") for item in bus.decision_source_descriptors
            ],
            "action_policies": [item.model_dump(mode="json") for item in bus.action_policies],
            "fixed_registry": True,
            "dynamic_source_discovery_used": False,
            "target_execution_used": False,
        }

    def create_final_decision_request(
        self,
        project_id: str,
        *,
        source_id: str,
        requested_by_module: str,
        action_policy_id: str,
        target_module_id: str,
        target_operation_id: str,
        source_selectors: Sequence[Mapping[str, Any] | BobaFinalDecisionSourceSelectorV1],
        workflow_run_id: str = "",
        stage_instance_id: str = "",
        clip_id: str = "",
        output_id: str = "",
        artifact_reference_id: str = "",
        project_snapshot_digest: str = "",
        workflow_snapshot_digest: str = "",
        target_parameters_digest: str = "",
        expires_at: str | None = None,
    ) -> BobaFinalDecisionRequestV1:
        bus = self._bus(project_id, source_id=source_id)
        if not bus.registry_snapshots:
            self.build_final_decision_registries(project_id, source_id=source_id)
            bus = self._bus(project_id)
        policy = self._policy(bus, action_policy_id)
        if (
            target_module_id != policy.target_module_id
            or target_operation_id != policy.target_operation_id
        ):
            raise ValidationError(
                "Final Decision Bus requests must use the policy's exact registered target."
            )
        if len(source_selectors) > _MAX_SOURCE_BINDINGS:
            raise ValidationError("Final Decision Bus permits at most 64 source selectors.")
        selectors = [
            selector
            if isinstance(selector, BobaFinalDecisionSourceSelectorV1)
            else BobaFinalDecisionSourceSelectorV1.model_validate(selector)
            for selector in source_selectors
        ]
        source_ids = {item.decision_source_id for item in bus.decision_source_descriptors}
        unknown = sorted({item.decision_source_id for item in selectors} - source_ids)
        if unknown:
            raise ValidationError(f"Unknown fixed decision source selectors: {unknown}")
        if len({(item.decision_source_id, item.producer_record_id) for item in selectors}) != len(
            selectors
        ):
            raise ValidationError("Final Decision Bus source selectors must be unique.")
        effective_expiry = expires_at or (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
        expiry = _parse_time(effective_expiry)
        if expiry is None or expiry <= datetime.now(UTC):
            raise ValidationError("Final Decision Bus request expiry must be in the future.")
        if expiry > datetime.now(UTC) + timedelta(minutes=15):
            raise ValidationError(
                "Final Decision Bus request expiry cannot exceed fifteen minutes."
            )
        request_payload = {
            "project_id": project_id,
            "source_id": source_id,
            "requested_by_module": requested_by_module,
            "action_policy_id": action_policy_id,
            "target_module_id": target_module_id,
            "target_operation_id": target_operation_id,
            "workflow_run_id": workflow_run_id,
            "stage_instance_id": stage_instance_id,
            "clip_id": clip_id,
            "output_id": output_id,
            "artifact_reference_id": artifact_reference_id,
            "project_snapshot_digest": project_snapshot_digest,
            "workflow_snapshot_digest": workflow_snapshot_digest,
            "target_parameters_digest": target_parameters_digest,
            "source_selectors": [item.model_dump(mode="json") for item in selectors],
        }
        request_digest = _digest(request_payload)
        existing = next(
            (
                item
                for item in bus.decision_requests
                if item.request_digest == request_digest and not _expired(item.expires_at)
            ),
            None,
        )
        if existing is not None:
            return existing
        request = BobaFinalDecisionRequestV1(
            final_decision_request_id=_stable_id(
                "final_decision_request", project_id, request_digest
            ),
            project_id=project_id,
            source_id=source_id,
            requested_by_module=_safe_id(requested_by_module, "Requesting module"),
            action_policy_id=action_policy_id,
            target_module_id=target_module_id,
            target_operation_id=target_operation_id,
            workflow_run_id=workflow_run_id,
            stage_instance_id=stage_instance_id,
            clip_id=clip_id,
            output_id=output_id,
            artifact_reference_id=artifact_reference_id,
            project_snapshot_digest=project_snapshot_digest,
            workflow_snapshot_digest=workflow_snapshot_digest,
            target_parameters_digest=target_parameters_digest,
            source_selectors=selectors,
            expires_at=effective_expiry,
            request_digest=request_digest,
            idempotency_key=_stable_id("final_decision_idempotency", project_id, request_digest),
        )
        bus.decision_requests.append(request)
        self._event(
            bus,
            "request_created",
            request.final_decision_request_id,
            "Exact Final Decision Bus request created.",
            "BOBA will combine only the selected authoritative records.",
        )
        self._refresh_summary(bus)
        self.store.save_boba_final_decision_bus(bus)
        return request

    def _policy(
        self,
        bus: BobaFinalDecisionBusSetV1,
        action_policy_id: str,
    ) -> BobaFinalActionPolicyV1:
        for policy in bus.action_policies:
            if policy.action_policy_id == action_policy_id:
                return policy
        raise NotFoundError("Final Decision Bus action policy was not found.")

    @staticmethod
    def _request(
        bus: BobaFinalDecisionBusSetV1,
        final_decision_request_id: str,
    ) -> BobaFinalDecisionRequestV1:
        for request in bus.decision_requests:
            if request.final_decision_request_id == final_decision_request_id:
                return request
        raise NotFoundError("Final Decision Bus request was not found.")

    @staticmethod
    def _descriptor(
        bus: BobaFinalDecisionBusSetV1,
        decision_source_id: str,
    ) -> BobaDecisionSourceDescriptorV1:
        for descriptor in bus.decision_source_descriptors:
            if descriptor.decision_source_id == decision_source_id:
                return descriptor
        raise ValidationError("Final Decision Bus source is not in the fixed registry.")

    def _source_records(
        self,
        project_id: str,
        decision_source_id: str,
    ) -> list[dict[str, Any]]:
        """Read exactly one hard-coded owner collection; never discover sources dynamically."""

        def scoped(records: Sequence[Any]) -> list[dict[str, Any]]:
            return [
                {"source_project_id": project_id, **_record_payload(record)} for record in records
            ]

        owner: Any
        if decision_source_id == "rights_permission_gate":
            owner = self.store.load_rights_permission_gate(project_id)
            return scoped(owner.gate_decisions) if owner is not None else []
        if decision_source_id == "safety_gate":
            owner = self.store.load_boba_safety_gate(project_id)
            return scoped(owner.safety_decisions) if owner is not None else []
        if decision_source_id == "workflow_controller":
            owner = self.store.load_boba_workflow_controller(project_id)
            return scoped(owner.transition_decisions) if owner is not None else []
        if decision_source_id == "human_decision":
            owner = self.store.load_boba_workflow_controller(project_id)
            return scoped(owner.human_decisions) if owner is not None else []
        if decision_source_id == "validator_runner":
            owner = self.store.load_boba_validator_runner(project_id)
            return scoped(owner.suite_decisions) if owner is not None else []
        if decision_source_id == "output_quality_reviewer":
            owner = self.store.load_boba_output_quality_reviewer(project_id)
            return scoped(owner.acceptance_decisions) if owner is not None else []
        if decision_source_id == "artifact_inspector":
            owner = self.store.load_boba_artifact_inspector(project_id)
            return scoped(owner.integrity_assessments) if owner is not None else []
        if decision_source_id == "autopilot_controller":
            owner = self.store.load_boba_autopilot_controller(project_id)
            return scoped(owner.decisions) if owner is not None else []
        if decision_source_id == "repair_planner":
            owner = self.store.load_boba_repair_planner(project_id)
            return scoped(owner.approval_gates) if owner is not None else []
        if decision_source_id == "code_surgeon":
            owner = self.store.load_boba_code_surgeon(project_id)
            return scoped(owner.approval_records) if owner is not None else []
        if decision_source_id == "tool_recovery_brain":
            owner = self.store.load_boba_tool_recovery(project_id)
            return scoped(owner.recovery_plans) if owner is not None else []
        if decision_source_id == "report_reader":
            owner = self.store.load_boba_report_reader(project_id)
            return scoped(owner.report_bundles) if owner is not None else []
        if decision_source_id == "target_approval":
            owner = self.store.load_boba_integration_layer(project_id)
            if owner is None:
                return []
            records: list[dict[str, Any]] = []
            for envelope in owner.request_envelopes:
                if envelope.approval_binding is not None:
                    records.append(
                        {
                            "source_project_id": project_id,
                            **_record_payload(envelope.approval_binding),
                        }
                    )
            return records
        raise ValidationError("Final Decision Bus source resolver is not registered.")

    def _source_record_invalidated(
        self,
        project_id: str,
        decision_source_id: str,
        producer_record_id: str,
    ) -> bool:
        if decision_source_id != "safety_gate":
            return False
        owner = self.store.load_boba_safety_gate(project_id)
        if owner is None:
            return False
        return any(
            item.safety_decision_id == producer_record_id for item in owner.decision_invalidations
        )

    def _build_source_binding(
        self,
        request: BobaFinalDecisionRequestV1,
        descriptor: BobaDecisionSourceDescriptorV1,
        selector: BobaFinalDecisionSourceSelectorV1,
    ) -> BobaFinalDecisionSourceBindingV1:
        records = self._source_records(request.project_id, descriptor.decision_source_id)
        record = next(
            (item for item in records if _record_identifier(item) == selector.producer_record_id),
            None,
        )
        if record is None:
            missing_digest = _digest(
                {
                    "source": descriptor.decision_source_id,
                    "record_id": selector.producer_record_id,
                    "missing": True,
                }
            )
            return BobaFinalDecisionSourceBindingV1(
                source_binding_id=_stable_id(
                    "final_source_binding",
                    request.final_decision_request_id,
                    descriptor.decision_source_id,
                    selector.producer_record_id,
                    missing_digest,
                ),
                final_decision_request_id=request.final_decision_request_id,
                project_id=request.project_id,
                decision_source_id=descriptor.decision_source_id,
                authority_domain=descriptor.authority_domain,
                producer_module_id=descriptor.producer_module_id,
                producer_record_id=selector.producer_record_id,
                producer_record_type=descriptor.decision_record_type,
                canonical_record_digest=missing_digest,
                expected_record_digest=selector.expected_record_digest,
                digest_match=False,
                valid=False,
                authoritative=not descriptor.advisory_only,
                advisory_only=descriptor.advisory_only,
                sanitized_record={"record_found": False},
                warnings=["Selected source record was not found in its owner collection."],
            )
        canonical_digest = _digest(record)
        expected_matches = (
            not selector.expected_record_digest
            or selector.expected_record_digest == canonical_digest
        )
        project_match = (
            _value(record, "project_id", "approved_project_id", "source_project_id")
            == request.project_id
        )
        workflow_match = _optional_match(
            request.workflow_run_id,
            _value(record, "workflow_run_id", "approved_run_id", "run_id", "autopilot_run_id"),
        )
        stage_match = _optional_match(
            request.stage_instance_id,
            _value(record, "stage_instance_id", "source_stage_instance_id"),
        )
        clip_match = _optional_match(request.clip_id, _value(record, "clip_id"))
        output_match = _optional_match(request.output_id, _value(record, "output_id"))
        artifact_match = _optional_match(
            request.artifact_reference_id,
            _value(record, "artifact_reference_id"),
        )
        target_module = _value(record, "allowed_target_module", "target_module_id", "target_module")
        target_operation = _value(
            record, "allowed_target_operation", "target_operation_id", "target_operation"
        )
        target_match: bool | None = None
        if target_module or target_operation:
            target_match = (
                target_module == request.target_module_id
                and target_operation == request.target_operation_id
            )
        expires_at = _source_expiration(record)
        invalidated = self._source_record_invalidated(
            request.project_id,
            descriptor.decision_source_id,
            selector.producer_record_id,
        )
        current_state = _source_current_state(record)
        status = _status_from_record(record)
        valid = (
            descriptor.availability == "available"
            and project_match
            and expected_matches
            and not _expired(expires_at)
            and not invalidated
            and current_state is not False
            and target_match is not False
        )
        warnings: list[str] = []
        if selector.expected_record_digest:
            warnings.append(
                "Source digest was compared to a canonical typed-record digest at collection."
            )
        else:
            warnings.append(
                "No source-provided expected digest was supplied; canonical record "
                "binding was computed."
            )
        if target_match is None and descriptor.decision_source_id in {
            "safety_gate",
            "target_approval",
        }:
            valid = False
            warnings.append("Exact target identity is absent from a required target-bound record.")
        if current_state is None:
            warnings.append("Owner record does not expose a current-state flag.")
        return BobaFinalDecisionSourceBindingV1(
            source_binding_id=_stable_id(
                "final_source_binding",
                request.final_decision_request_id,
                descriptor.decision_source_id,
                selector.producer_record_id,
                canonical_digest,
            ),
            final_decision_request_id=request.final_decision_request_id,
            project_id=request.project_id,
            decision_source_id=descriptor.decision_source_id,
            authority_domain=descriptor.authority_domain,
            producer_module_id=descriptor.producer_module_id,
            producer_record_id=selector.producer_record_id,
            producer_record_type=descriptor.decision_record_type,
            producer_schema_id=str(record.get("schema_version") or descriptor.schema_id),
            canonical_record_digest=canonical_digest,
            expected_record_digest=selector.expected_record_digest,
            observed_decision=status,
            observed_status=status,
            project_identity_match=project_match,
            workflow_identity_match=workflow_match,
            stage_identity_match=stage_match,
            clip_identity_match=clip_match,
            output_identity_match=output_match,
            artifact_identity_match=artifact_match,
            target_identity_match=target_match,
            digest_match=expected_matches,
            current_state=current_state,
            expired=_expired(expires_at),
            invalidated=invalidated,
            valid=valid,
            authoritative=not descriptor.advisory_only,
            advisory_only=descriptor.advisory_only,
            expires_at=expires_at,
            sanitized_record=_sanitized_mapping(record),
            warnings=warnings,
        )

    def collect_source_decision_bindings(
        self,
        project_id: str,
        final_decision_request_id: str,
    ) -> list[BobaFinalDecisionSourceBindingV1]:
        bus = self._bus(project_id)
        request = self._request(bus, final_decision_request_id)
        collected: list[BobaFinalDecisionSourceBindingV1] = []
        for selector in request.source_selectors:
            descriptor = self._descriptor(bus, selector.decision_source_id)
            binding = self._build_source_binding(request, descriptor, selector)
            existing = next(
                (
                    item
                    for item in bus.source_bindings
                    if item.source_binding_id == binding.source_binding_id
                ),
                None,
            )
            if existing is None:
                bus.source_bindings.append(binding)
                collected.append(binding)
            else:
                collected.append(existing)
        bus.signal_usage.persisted_owner_records_read = True
        self._event(
            bus,
            "source_binding_validated",
            request.final_decision_request_id,
            "Selected authoritative source records were bound.",
            "BOBA read only the exact owner records selected for this request.",
        )
        self._refresh_summary(bus)
        self.store.save_boba_final_decision_bus(bus)
        return collected

    def validate_final_decision_request(
        self,
        project_id: str,
        final_decision_request_id: str,
    ) -> dict[str, Any]:
        bus = self._bus(project_id)
        request = self._request(bus, final_decision_request_id)
        valid, reasons = self._request_is_valid(bus, request)
        self._event(
            bus,
            "request_validated",
            request.final_decision_request_id,
            "Final Decision Bus request was validated.",
            "BOBA checked that one exact registered internal action was requested.",
            severity="info" if valid else "warning",
            requires_attention=not valid,
        )
        self.store.save_boba_final_decision_bus(bus)
        return {
            "project_id": project_id,
            "final_decision_request_id": final_decision_request_id,
            "valid": valid,
            "reasons": reasons,
        }

    def validate_source_decision_bindings(
        self,
        project_id: str,
        final_decision_request_id: str,
    ) -> dict[str, Any]:
        bus = self._bus(project_id)
        request = self._request(bus, final_decision_request_id)
        bindings = self._latest_bindings(bus, request.final_decision_request_id)
        results = [
            {
                "source_binding_id": item.source_binding_id,
                "decision_source_id": item.decision_source_id,
                "valid": item.valid,
                "expired": item.expired,
                "invalidated": item.invalidated,
                "project_identity_match": item.project_identity_match,
                "target_identity_match": item.target_identity_match,
                "warnings": item.warnings,
            }
            for item in bindings
        ]
        return {
            "project_id": project_id,
            "final_decision_request_id": final_decision_request_id,
            "bindings": results,
            "all_valid": bool(results) and all(item["valid"] for item in results),
        }

    def build_evidence_requirements(
        self,
        project_id: str,
        final_decision_request_id: str,
    ) -> list[BobaFinalDecisionEvidenceRequirementV1]:
        bus = self._bus(project_id)
        request = self._request(bus, final_decision_request_id)
        policy = self._policy(bus, request.action_policy_id)
        requirements: list[BobaFinalDecisionEvidenceRequirementV1] = []
        for source_id in policy.required_decision_source_ids:
            descriptor = self._descriptor(bus, source_id)
            requirement = BobaFinalDecisionEvidenceRequirementV1(
                evidence_requirement_id=_stable_id(
                    "final_evidence_requirement",
                    request.final_decision_request_id,
                    policy.action_policy_id,
                    source_id,
                ),
                final_decision_request_id=request.final_decision_request_id,
                action_policy_id=policy.action_policy_id,
                decision_source_id=source_id,
                authority_domain=descriptor.authority_domain,
                evidence_kind=source_id,
                required=True,
                requires_current_state=policy.required_current_state,
                requires_exact_identity=True,
                acceptable_decision_values=descriptor.ready_statuses,
                blocking_decision_values=descriptor.blocking_statuses,
                bounded_reason=(
                    f"{descriptor.decision_source_id} remains owned by "
                    f"{descriptor.producer_module_id} and is required by the fixed policy."
                ),
            )
            existing = next(
                (
                    item
                    for item in bus.evidence_requirements
                    if item.evidence_requirement_id == requirement.evidence_requirement_id
                ),
                None,
            )
            if existing is None:
                bus.evidence_requirements.append(requirement)
                requirements.append(requirement)
            else:
                requirements.append(existing)
        self.store.save_boba_final_decision_bus(bus)
        return requirements

    def bind_final_decision_evidence(
        self,
        project_id: str,
        final_decision_request_id: str,
    ) -> list[BobaFinalDecisionEvidenceBindingV1]:
        bus = self._bus(project_id)
        request = self._request(bus, final_decision_request_id)
        requirements = self.build_evidence_requirements(project_id, final_decision_request_id)
        bus = self._bus(project_id)
        bindings = self._bindings_for_request(bus, request.final_decision_request_id)
        evidence_bindings: list[BobaFinalDecisionEvidenceBindingV1] = []
        for requirement in requirements:
            descriptor = self._descriptor(bus, requirement.decision_source_id)
            candidates = [
                item
                for item in bindings
                if item.decision_source_id == requirement.decision_source_id
            ]
            source_binding = candidates[-1] if candidates else None
            status: Literal["satisfied", "missing", "stale", "invalid", "blocked", "unknown"]
            reason: str
            if source_binding is None:
                status = "missing"
                reason = "No selected source record was bound for this required authority."
            elif source_binding.expired or source_binding.invalidated or source_binding.superseded:
                status = "stale"
                reason = "The required source decision is expired, invalidated, or superseded."
            elif _normal_status(source_binding.observed_decision) in {
                _normal_status(item) for item in descriptor.blocking_statuses
            }:
                status = "blocked"
                reason = "The source owner recorded a blocking decision."
            elif not source_binding.valid:
                status = "invalid"
                reason = "The selected source record does not match the required current identity."
            elif not self._source_binding_ready(descriptor, source_binding):
                status = "unknown"
                reason = "The source record is not a current readiness decision for this policy."
            else:
                status = "satisfied"
                reason = "The source-owned readiness decision is current and exact."
            evidence = BobaFinalDecisionEvidenceBindingV1(
                evidence_binding_id=_stable_id(
                    "final_evidence_binding",
                    requirement.evidence_requirement_id,
                    source_binding.source_binding_id if source_binding is not None else "missing",
                    status,
                ),
                evidence_requirement_id=requirement.evidence_requirement_id,
                final_decision_request_id=request.final_decision_request_id,
                source_binding_id=(
                    source_binding.source_binding_id if source_binding is not None else ""
                ),
                status=status,
                satisfied=status == "satisfied",
                bounded_reason=reason,
            )
            existing = next(
                (
                    item
                    for item in bus.evidence_bindings
                    if item.evidence_binding_id == evidence.evidence_binding_id
                ),
                None,
            )
            if existing is None:
                bus.evidence_bindings.append(evidence)
                evidence_bindings.append(evidence)
                self._event(
                    bus,
                    (
                        "evidence_requirement_satisfied"
                        if evidence.satisfied
                        else "evidence_requirement_missing"
                    ),
                    request.final_decision_request_id,
                    "Final Decision Bus evidence requirement evaluated.",
                    "BOBA checked whether the required owner decision is present and current.",
                    severity="info" if evidence.satisfied else "warning",
                    requires_attention=not evidence.satisfied,
                )
            else:
                evidence_bindings.append(existing)
        self._refresh_summary(bus)
        self.store.save_boba_final_decision_bus(bus)
        return evidence_bindings

    def detect_final_decision_conflicts(
        self,
        project_id: str,
        final_decision_request_id: str,
    ) -> list[BobaFinalDecisionConflictV1]:
        bus = self._bus(project_id)
        request = self._request(bus, final_decision_request_id)
        conflicts: list[BobaFinalDecisionConflictV1] = []
        bindings = self._bindings_for_request(bus, request.final_decision_request_id)
        by_domain: dict[str, list[BobaFinalDecisionSourceBindingV1]] = {}
        for binding in bindings:
            if binding.advisory_only or binding.expired or binding.invalidated:
                continue
            by_domain.setdefault(binding.authority_domain, []).append(binding)
            if not binding.project_identity_match:
                conflicts.append(
                    self._conflict(
                        request,
                        "project_identity_conflict",
                        [binding.source_binding_id],
                        "A selected source record does not belong to this project.",
                    )
                )
            if binding.target_identity_match is False:
                conflicts.append(
                    self._conflict(
                        request,
                        "action_conflict",
                        [binding.source_binding_id],
                        "A selected source record does not authorize this exact target.",
                    )
                )
        for domain, domain_bindings in by_domain.items():
            statuses = {_normal_status(item.observed_decision) for item in domain_bindings}
            if len(statuses) > 1:
                conflicts.append(
                    self._conflict(
                        request,
                        "decision_conflict",
                        [item.source_binding_id for item in domain_bindings],
                        f"Active {domain} records disagree for the selected request.",
                    )
                )
        persisted: list[BobaFinalDecisionConflictV1] = []
        for conflict in conflicts[:_MAX_CONFLICTS]:
            existing = (
                next(item for item in bus.conflicts if item.conflict_id == conflict.conflict_id)
                if any(item.conflict_id == conflict.conflict_id for item in bus.conflicts)
                else None
            )
            if existing is None:
                bus.conflicts.append(conflict)
                persisted.append(conflict)
                self._event(
                    bus,
                    "conflict_detected",
                    request.final_decision_request_id,
                    "Final Decision Bus detected conflicting source evidence.",
                    "BOBA cannot authorize an exact action while authoritative records conflict.",
                    severity="error",
                    requires_attention=True,
                )
            else:
                persisted.append(existing)
        self.store.save_boba_final_decision_bus(bus)
        return persisted

    def evaluate_final_action_policy(
        self,
        project_id: str,
        final_decision_request_id: str,
    ) -> BobaFinalDecisionPolicyEvaluationV1:
        """Evaluate only the fixed policy, in the documented fail-closed order."""

        bus = self._bus(project_id)
        request = self._request(bus, final_decision_request_id)
        policy = self._policy(bus, request.action_policy_id)
        self.build_evidence_requirements(project_id, final_decision_request_id)
        bus = self._bus(project_id)
        evidence_bindings = self.bind_final_decision_evidence(project_id, final_decision_request_id)
        bus = self._bus(project_id)
        conflicts = self.detect_final_decision_conflicts(project_id, final_decision_request_id)
        bus = self._bus(project_id)
        valid_request, request_reasons = self._request_is_valid(bus, request)
        required_bindings = self._bindings_for_request(bus, request.final_decision_request_id)
        required_source_ids = set(policy.required_decision_source_ids)
        required_source_bindings = [
            item for item in required_bindings if item.decision_source_id in required_source_ids
        ]
        bindings_valid = len({item.decision_source_id for item in required_source_bindings}) == len(
            required_source_ids
        ) and all(item.valid for item in required_source_bindings)
        evidence_complete = bool(evidence_bindings) and all(
            item.satisfied for item in evidence_bindings
        )
        evidence_current = all(
            item.status not in {"stale", "invalid"} for item in evidence_bindings
        )
        unresolved_conflicts = [item for item in conflicts if item.unresolved]
        lease_available = self._lease_available(bus, request, policy)
        optional_rights_blocks = [
            item
            for item in required_bindings
            if item.authority_domain == "rights"
            and self._source_is_blocking(self._descriptor(bus, item.decision_source_id), item)
        ]
        blocked_bindings = [
            item
            for item in required_bindings
            if self._source_is_blocking(self._descriptor(bus, item.decision_source_id), item)
        ]
        human_ready = any(
            item.decision_source_id == "human_decision"
            and self._source_binding_ready(self._descriptor(bus, "human_decision"), item)
            for item in required_bindings
        )
        ordered_checks = [
            self._ordered_check(1, "request_validity", valid_request, request_reasons),
            self._ordered_check(
                2,
                "registry_and_policy",
                policy.availability == "available" and policy.executable_target,
                policy.warnings,
            ),
            self._ordered_check(
                3,
                "project_and_target_identity",
                all(
                    item.project_identity_match and item.target_identity_match is not False
                    for item in required_source_bindings
                ),
                [],
            ),
            self._ordered_check(
                4,
                "rights",
                not optional_rights_blocks,
                ["A bound Rights record blocks this action."] if optional_rights_blocks else [],
            ),
            self._ordered_check(
                5,
                "safety",
                not any(item.authority_domain == "safety" for item in blocked_bindings),
                [],
            ),
            self._ordered_check(
                6,
                "target_approval",
                not any(item.decision_source_id == "target_approval" for item in blocked_bindings),
                [],
            ),
            self._ordered_check(
                7,
                "human_decision",
                not policy.requires_explicit_human_confirmation or human_ready,
                ["The fixed policy requires a current explicit human decision."]
                if policy.requires_explicit_human_confirmation and not human_ready
                else [],
            ),
            self._ordered_check(
                8,
                "workflow",
                not any(item.authority_domain == "workflow" for item in blocked_bindings),
                [],
            ),
            self._ordered_check(
                9,
                "artifact_integrity",
                not any(item.authority_domain == "artifact_integrity" for item in blocked_bindings),
                [],
            ),
            self._ordered_check(
                10,
                "technical_validation",
                not any(
                    item.authority_domain == "technical_validation" for item in blocked_bindings
                ),
                [],
            ),
            self._ordered_check(
                11,
                "output_quality",
                not any(item.authority_domain == "output_quality" for item in blocked_bindings),
                [],
            ),
            self._ordered_check(
                12,
                "recovery_and_checkpoint",
                not any(
                    item.authority_domain in {"recovery", "checkpoint"} for item in blocked_bindings
                ),
                [],
            ),
            self._ordered_check(13, "freshness", evidence_current, []),
            self._ordered_check(
                14,
                "conflicts",
                not unresolved_conflicts,
                ["Authoritative records conflict."] if unresolved_conflicts else [],
            ),
            self._ordered_check(
                15,
                "resources_and_lease",
                lease_available,
                ["An active exact-action lease exists."] if not lease_available else [],
            ),
            self._ordered_check(16, "evidence_completeness", evidence_complete, []),
        ]
        disposition: BobaFinalDispositionV1
        decision_reasons: list[str] = []
        if not valid_request:
            disposition = "invalid"
            decision_reasons.extend(request_reasons)
        elif policy.availability != "available" or not policy.executable_target:
            disposition = "blocked_by_policy"
            decision_reasons.extend(policy.warnings or ["Policy target is unavailable."])
        elif optional_rights_blocks:
            disposition = "blocked_by_rights"
            decision_reasons.append("A selected Rights + Permission Gate record blocks the action.")
        elif blocked_bindings:
            disposition = self._blocking_disposition(blocked_bindings[0])
            decision_reasons.append("A selected authoritative source owner blocks the action.")
        elif unresolved_conflicts:
            disposition = "hold_conflicting_evidence"
            decision_reasons.append("Conflicting authoritative source records require resolution.")
        elif any(item.status == "stale" for item in evidence_bindings):
            disposition = "hold_stale_evidence"
            decision_reasons.append("Required source evidence is stale, expired, or invalidated.")
        elif policy.requires_explicit_human_confirmation and not human_ready:
            disposition = "hold_human_review"
            decision_reasons.append(
                "The fixed action policy requires an explicit current human decision."
            )
        elif not evidence_complete or not bindings_valid:
            disposition = "hold_missing_evidence"
            decision_reasons.append(
                "One or more required current source decisions are missing or invalid."
            )
        elif not lease_available:
            disposition = "blocked_by_policy"
            decision_reasons.append(
                "Another active exact-action lease prevents duplicate dispatch."
            )
        else:
            disposition = "ready_for_exact_internal_dispatch"
            decision_reasons.append(
                "All fixed required source-owner decisions are current, exact, and non-conflicting."
            )
        snapshot = bus.registry_snapshots[-1]
        evaluation_payload = {
            "request_digest": request.request_digest,
            "policy_digest": policy.policy_digest,
            "registry_digest": snapshot.combined_registry_digest,
            "source_bindings": [
                (item.source_binding_id, item.canonical_record_digest, item.valid)
                for item in required_bindings
            ],
            "evidence": [(item.evidence_binding_id, item.status) for item in evidence_bindings],
            "conflicts": [item.conflict_id for item in unresolved_conflicts],
            "disposition": disposition,
        }
        evaluation_id = _stable_id("final_policy_evaluation", _digest(evaluation_payload))
        existing = next(
            (item for item in bus.policy_evaluations if item.policy_evaluation_id == evaluation_id),
            None,
        )
        if existing is not None:
            return existing
        incident_ids: list[str] = []
        if disposition != "ready_for_exact_internal_dispatch":
            incident = self._incident_for_disposition(
                bus, request, disposition, decision_reasons[0] if decision_reasons else ""
            )
            incident_ids.append(incident.incident_id)
        evaluation = BobaFinalDecisionPolicyEvaluationV1(
            policy_evaluation_id=evaluation_id,
            final_decision_request_id=request.final_decision_request_id,
            project_id=project_id,
            action_policy_id=policy.action_policy_id,
            policy_digest=policy.policy_digest,
            registry_digest=snapshot.combined_registry_digest,
            disposition=disposition,
            request_valid=valid_request,
            source_bindings_valid=bindings_valid,
            evidence_complete=evidence_complete,
            evidence_current=evidence_current,
            conflicts_resolved=not unresolved_conflicts,
            lease_available=lease_available,
            ordered_checks=ordered_checks,
            evidence_binding_ids=[item.evidence_binding_id for item in evidence_bindings],
            conflict_ids=[item.conflict_id for item in unresolved_conflicts],
            incident_ids=incident_ids,
            decision_reasons=decision_reasons,
        )
        bus.policy_evaluations.append(evaluation)
        self._event(
            bus,
            "policy_evaluation_completed",
            request.final_decision_request_id,
            "Final Decision Bus policy evaluation completed.",
            (
                "BOBA found every required source ready for one exact internal dispatch."
                if disposition == "ready_for_exact_internal_dispatch"
                else "BOBA will not authorize dispatch until the listed blockers are resolved."
            ),
            severity="info" if disposition == "ready_for_exact_internal_dispatch" else "warning",
            requires_attention=disposition != "ready_for_exact_internal_dispatch",
        )
        self._refresh_summary(bus)
        self.store.save_boba_final_decision_bus(bus)
        return evaluation

    def finalize_exact_internal_decision(
        self,
        project_id: str,
        final_decision_request_id: str,
    ) -> BobaFinalDecisionV1:
        bus = self._bus(project_id)
        request = self._request(bus, final_decision_request_id)
        evaluation = self.evaluate_final_action_policy(project_id, final_decision_request_id)
        bus = self._bus(project_id)
        existing = next(
            (
                item
                for item in bus.final_decisions
                if item.policy_evaluation_id == evaluation.policy_evaluation_id
            ),
            None,
        )
        if existing is not None:
            return existing
        policy = self._policy(bus, request.action_policy_id)
        expiry = min(
            (
                value
                for value in (
                    _parse_time(request.expires_at),
                    datetime.now(UTC) + timedelta(seconds=policy.dispatch_ttl_seconds),
                )
                if value is not None
            ),
            default=datetime.now(UTC),
        ).isoformat()
        decision_payload = {
            "request_digest": request.request_digest,
            "evaluation_id": evaluation.policy_evaluation_id,
            "policy_digest": policy.policy_digest,
            "registry_digest": evaluation.registry_digest,
            "disposition": evaluation.disposition,
            "expiry": expiry,
        }
        decision_digest = _digest(decision_payload)
        decision_id = _stable_id("final_decision", project_id, decision_digest)
        ready = evaluation.disposition == "ready_for_exact_internal_dispatch"
        if ready and not self._lease_available(bus, request, policy):
            # A concurrent finalization changed the state after evaluation.
            evaluation = self.evaluate_final_action_policy(project_id, final_decision_request_id)
            ready = False
        if ready:
            self._acquire_lease(bus, request, policy, decision_id, expiry)
        decision = BobaFinalDecisionV1(
            final_decision_id=decision_id,
            final_decision_request_id=request.final_decision_request_id,
            policy_evaluation_id=evaluation.policy_evaluation_id,
            project_id=project_id,
            action_policy_id=policy.action_policy_id,
            target_module_id=request.target_module_id,
            target_operation_id=request.target_operation_id,
            registry_digest=evaluation.registry_digest,
            policy_digest=policy.policy_digest,
            request_digest=request.request_digest,
            source_binding_digests=[
                item.canonical_record_digest
                for item in self._bindings_for_request(bus, request.final_decision_request_id)
            ],
            evidence_binding_ids=evaluation.evidence_binding_ids,
            conflict_ids=evaluation.conflict_ids,
            disposition=evaluation.disposition,
            ready_for_dispatch=ready,
            expires_at=expiry if ready else request.expires_at,
            decision_digest=decision_digest,
            idempotency_key=request.idempotency_key,
            warnings=(
                []
                if ready
                else ["No dispatch envelope may be created for a non-ready final disposition."]
            ),
        )
        bus.final_decisions.append(decision)
        handoff = BobaFinalDecisionHandoffV1(
            handoff_id=_stable_id("final_decision_handoff", decision.final_decision_id),
            project_id=project_id,
            final_decision_request_id=request.final_decision_request_id,
            final_decision_id=decision.final_decision_id,
            target_module_id=request.target_module_id,
            target_operation_id=request.target_operation_id,
            handoff_state="ready_for_revalidation" if ready else "blocked",
            bounded_reason=(
                "A ready decision permits only a single-use dispatch envelope and independent "
                "target revalidation."
                if ready
                else "Final Decision Bus preserved the source-owner blocker and did not dispatch."
            ),
        )
        bus.handoffs.append(handoff)
        self._event(
            bus,
            "final_decision_ready" if ready else "final_decision_blocked",
            request.final_decision_request_id,
            "Immutable Final Decision Bus disposition recorded.",
            (
                "BOBA recorded readiness for a single-use internal dispatch envelope."
                if ready
                else "BOBA recorded a blocker; no target action was executed."
            ),
            final_decision_id=decision.final_decision_id,
            severity="info" if ready else "warning",
            requires_attention=not ready,
        )
        self._refresh_summary(bus)
        self.store.save_boba_final_decision_bus(bus)
        return decision

    def build_exact_dispatch_envelope(
        self,
        project_id: str,
        final_decision_id: str,
    ) -> BobaFinalDispatchEnvelopeV1:
        bus = self._bus(project_id)
        decision = self._decision(bus, final_decision_id)

        policy = self._policy(bus, decision.action_policy_id)
        if (
            not decision.ready_for_dispatch
            or decision.disposition != "ready_for_exact_internal_dispatch"
            or self._decision_invalidated(bus, decision.final_decision_id)
            or _expired(decision.expires_at)
        ):
            raise ValidationError("A dispatch envelope requires a current ready final decision.")
        existing = next(
            (
                item
                for item in bus.dispatch_envelopes
                if item.final_decision_id == decision.final_decision_id
                and not item.consumed
                and not item.invalidated
                and not _expired(item.expires_at)
            ),
            None,
        )
        if existing is not None:
            return existing
        issued_at = now_iso()
        expiry_limit = datetime.now(UTC) + timedelta(seconds=policy.dispatch_ttl_seconds)
        decision_expiry = _parse_time(decision.expires_at) or expiry_limit
        expires_at = min(expiry_limit, decision_expiry).isoformat()
        envelope_payload = {
            "decision_id": decision.final_decision_id,
            "request_digest": decision.request_digest,
            "decision_digest": decision.decision_digest,
            "target_module_id": decision.target_module_id,
            "target_operation_id": decision.target_operation_id,
            "expires_at": expires_at,
        }
        dispatch_digest = _digest(envelope_payload)
        envelope = BobaFinalDispatchEnvelopeV1(
            dispatch_envelope_id=_stable_id("final_dispatch_envelope", project_id, dispatch_digest),
            final_decision_id=decision.final_decision_id,
            final_decision_request_id=decision.final_decision_request_id,
            project_id=project_id,
            action_policy_id=decision.action_policy_id,
            target_module_id=decision.target_module_id,
            target_operation_id=decision.target_operation_id,
            request_digest=decision.request_digest,
            decision_digest=decision.decision_digest,
            dispatch_digest=dispatch_digest,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        bus.dispatch_envelopes.append(envelope)
        bus.handoffs.append(
            BobaFinalDecisionHandoffV1(
                handoff_id=_stable_id("final_dispatch_handoff", envelope.dispatch_envelope_id),
                project_id=project_id,
                final_decision_request_id=decision.final_decision_request_id,
                final_decision_id=decision.final_decision_id,
                dispatch_envelope_id=envelope.dispatch_envelope_id,
                target_module_id=envelope.target_module_id,
                target_operation_id=envelope.target_operation_id,
                handoff_state="ready_for_revalidation",
                bounded_reason=(
                    "Dispatch envelope was created. Integration Layer and the exact target "
                    "must independently revalidate it before any action."
                ),
            )
        )
        self._event(
            bus,
            "dispatch_envelope_created",
            decision.final_decision_request_id,
            "Single-use Final Decision Bus dispatch envelope created.",
            "BOBA created routing metadata only; it did not execute the requested action.",
            final_decision_id=decision.final_decision_id,
            dispatch_envelope_id=envelope.dispatch_envelope_id,
        )
        self._refresh_summary(bus)
        self.store.save_boba_final_decision_bus(bus)
        return envelope

    def inspect_final_decision(
        self,
        project_id: str,
        final_decision_id: str,
    ) -> dict[str, Any]:
        bus = self._bus(project_id)
        decision = self._decision(bus, final_decision_id)
        request = self._request(bus, decision.final_decision_request_id)

        evaluation = next(
            item
            for item in bus.policy_evaluations
            if item.policy_evaluation_id == decision.policy_evaluation_id
        )
        invalidated = self._decision_invalidated(bus, decision.final_decision_id)
        return _sanitized_mapping(
            {
                "schema_version": "boba_final_decision_inspection_v1",
                "decision": decision.model_dump(mode="json"),
                "request": request.model_dump(mode="json"),
                "evaluation": evaluation.model_dump(mode="json"),
                "source_bindings": [
                    item.model_dump(mode="json")
                    for item in self._bindings_for_request(bus, request.final_decision_request_id)
                ],
                "evidence_bindings": [
                    item.model_dump(mode="json")
                    for item in bus.evidence_bindings
                    if item.evidence_binding_id in evaluation.evidence_binding_ids
                ],
                "conflicts": [
                    item.model_dump(mode="json")
                    for item in bus.conflicts
                    if item.conflict_id in evaluation.conflict_ids
                ],
                "invalidated": invalidated,
                "expired": _expired(decision.expires_at),
                "target_execution_performed": False,
            }
        )

    def inspect_dispatch_envelope(
        self,
        project_id: str,
        dispatch_envelope_id: str,
    ) -> dict[str, Any]:
        bus = self._bus(project_id)
        envelope = self._envelope(bus, dispatch_envelope_id)
        valid = (
            envelope.valid
            and not envelope.consumed
            and not envelope.invalidated
            and not _expired(envelope.expires_at)
            and not self._decision_invalidated(bus, envelope.final_decision_id)
        )
        return {
            "schema_version": "boba_final_dispatch_envelope_inspection_v1",
            "dispatch_envelope": envelope.model_dump(mode="json"),
            "currently_valid_for_independent_revalidation": valid,
            "target_execution_performed": False,
            "limitations": [
                "Envelope inspection does not route or execute the target.",
                "Integration Layer and the target must independently revalidate the envelope.",
            ],
        }

    def mark_dispatch_envelope_consumed(
        self,
        project_id: str,
        dispatch_envelope_id: str,
        *,
        integration_transaction_id: str,
    ) -> BobaFinalDispatchEnvelopeV1:
        bus = self._bus(project_id)
        envelope = self._envelope(bus, dispatch_envelope_id)
        if envelope.consumed or envelope.invalidated or _expired(envelope.expires_at):
            raise ValidationError("Dispatch envelope is no longer available for consumption.")
        if self._decision_invalidated(bus, envelope.final_decision_id):
            raise ValidationError("The final decision was invalidated before dispatch consumption.")
        transaction = self.store.load_boba_integration_transaction(
            project_id, integration_transaction_id
        )
        if transaction is None:
            raise NotFoundError("Matching Integration Layer transaction was not found.")
        if (
            transaction.project_id != project_id
            or transaction.target_module_id != envelope.target_module_id
            or transaction.target_operation_id != envelope.target_operation_id
            or not transaction.target_independent_revalidation_confirmed
        ):
            raise ValidationError(
                "Integration transaction did not independently revalidate this exact "
                "envelope target."
            )
        consumed = envelope.model_copy(
            update={
                "consumed": True,
                "consumed_at": now_iso(),
                "consumption_transaction_id": integration_transaction_id,
                "valid": False,
            }
        )
        bus.dispatch_envelopes = [
            consumed if item.dispatch_envelope_id == dispatch_envelope_id else item
            for item in bus.dispatch_envelopes
        ]
        self._event(
            bus,
            "dispatch_envelope_consumed",
            envelope.final_decision_request_id,
            "Final Decision Bus dispatch envelope was consumed once.",
            "BOBA recorded only independent target revalidation; it does not claim "
            "execution success.",
            final_decision_id=envelope.final_decision_id,
            dispatch_envelope_id=envelope.dispatch_envelope_id,
        )
        self._refresh_summary(bus)
        self.store.save_boba_final_decision_bus(bus)
        return consumed

    def invalidate_final_decision(
        self,
        project_id: str,
        final_decision_id: str,
        *,
        reason: str,
        invalidated_by_module: str,
    ) -> BobaFinalDecisionInvalidationV1:
        bus = self._bus(project_id)
        decision = self._decision(bus, final_decision_id)
        cleaned_reason = _safe_text(reason, 1_200)
        if not cleaned_reason:
            raise ValidationError("Final Decision Bus invalidation requires a bounded reason.")
        existing = next(
            (
                item
                for item in bus.invalidations
                if item.final_decision_id == final_decision_id and item.reason == cleaned_reason
            ),
            None,
        )
        if existing is not None:
            return existing
        invalidation_digest = _digest(
            {
                "decision_id": final_decision_id,
                "reason": cleaned_reason,
                "invalidated_by_module": invalidated_by_module,
            }
        )
        invalidation = BobaFinalDecisionInvalidationV1(
            final_decision_invalidation_id=_stable_id(
                "final_decision_invalidation", project_id, invalidation_digest
            ),
            project_id=project_id,
            final_decision_id=decision.final_decision_id,
            final_decision_request_id=decision.final_decision_request_id,
            reason=cleaned_reason,
            invalidated_by_module=_safe_id(invalidated_by_module, "Invalidating module"),
            invalidation_digest=invalidation_digest,
        )
        bus.invalidations.append(invalidation)
        bus.dispatch_envelopes = [
            item.model_copy(update={"invalidated": True, "valid": False})
            if item.final_decision_id == final_decision_id and not item.consumed
            else item
            for item in bus.dispatch_envelopes
        ]
        bus.leases = [
            item.model_copy(update={"state": "invalidated", "release_reason": cleaned_reason})
            if item.final_decision_id == final_decision_id and item.state == "active"
            else item
            for item in bus.leases
        ]
        bus.handoffs.append(
            BobaFinalDecisionHandoffV1(
                handoff_id=_stable_id(
                    "final_invalidation_handoff", invalidation.invalidation_digest
                ),
                project_id=project_id,
                final_decision_request_id=decision.final_decision_request_id,
                final_decision_id=decision.final_decision_id,
                target_module_id=decision.target_module_id,
                target_operation_id=decision.target_operation_id,
                handoff_state="invalidated",
                bounded_reason=cleaned_reason,
            )
        )
        self._event(
            bus,
            "decision_invalidated",
            decision.final_decision_request_id,
            "Final Decision Bus decision invalidated.",
            "BOBA invalidated the dispatch authorization because meaningful state changed.",
            final_decision_id=decision.final_decision_id,
            severity="warning",
            requires_attention=True,
        )
        self._refresh_summary(bus)
        self.store.save_boba_final_decision_bus(bus)
        return invalidation

    def inspect_final_decision_events(
        self,
        project_id: str,
        *,
        final_decision_request_id: str = "",
    ) -> list[dict[str, Any]]:
        bus = self._bus(project_id)
        events = [
            item
            for item in bus.events
            if not final_decision_request_id
            or item.final_decision_request_id == final_decision_request_id
        ]
        return [_sanitized_mapping(item.model_dump(mode="json")) for item in events]

    def export_final_decision_bus(self, project_id: str) -> dict[str, Any]:
        bus = self._bus(project_id)
        return _sanitized_mapping(
            {
                "schema_version": "boba_final_decision_bus_export_v1",
                "final_decision_bus": bus.model_dump(mode="json"),
                "target_execution_performed": False,
                "external_access_used": False,
            }
        )

    def reset_final_decision_bus_metadata(self, project_id: str) -> dict[str, Any]:
        return self.store.reset_boba_final_decision_bus(project_id)

    def _request_is_valid(
        self,
        bus: BobaFinalDecisionBusSetV1,
        request: BobaFinalDecisionRequestV1,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        try:
            policy = self._policy(bus, request.action_policy_id)
        except NotFoundError:
            return False, ["Requested action policy is absent from the fixed registry."]
        if _expired(request.expires_at):
            reasons.append("Final Decision Bus request has expired.")
        if (
            request.target_module_id != policy.target_module_id
            or request.target_operation_id != policy.target_operation_id
        ):
            reasons.append("Request target differs from the fixed action policy target.")
        known_sources = {item.decision_source_id for item in bus.decision_source_descriptors}
        selected_sources = {item.decision_source_id for item in request.source_selectors}
        unknown_sources = selected_sources - known_sources
        if unknown_sources:
            reasons.append("Request includes an unregistered decision source.")
        if len(request.source_selectors) > _MAX_SOURCE_BINDINGS:
            reasons.append("Request exceeds the source-binding limit.")
        if len(_canonical(request.model_dump(mode="json")).encode("utf-8")) > _MAX_REQUEST_BYTES:
            reasons.append("Request exceeds the bounded Final Decision Bus payload size.")
        return not reasons, reasons

    @staticmethod
    def _bindings_for_request(
        bus: BobaFinalDecisionBusSetV1,
        final_decision_request_id: str,
    ) -> list[BobaFinalDecisionSourceBindingV1]:
        return [
            item
            for item in bus.source_bindings
            if item.final_decision_request_id == final_decision_request_id
        ]

    def _latest_bindings(
        self,
        bus: BobaFinalDecisionBusSetV1,
        final_decision_request_id: str,
    ) -> list[BobaFinalDecisionSourceBindingV1]:
        latest: dict[tuple[str, str], BobaFinalDecisionSourceBindingV1] = {}
        for binding in self._bindings_for_request(bus, final_decision_request_id):
            latest[(binding.decision_source_id, binding.producer_record_id)] = binding
        return list(latest.values())

    @staticmethod
    def _source_binding_ready(
        descriptor: BobaDecisionSourceDescriptorV1,
        binding: BobaFinalDecisionSourceBindingV1,
    ) -> bool:
        if not binding.valid or binding.advisory_only:
            return False
        record = binding.sanitized_record
        status = _normal_status(binding.observed_decision)
        ready_statuses = {_normal_status(item) for item in descriptor.ready_statuses}
        if descriptor.decision_source_id == "target_approval":
            return (
                status == "target_module_exact"
                and bool(record.get("explicit_confirmation"))
                and _normal_status(str(record.get("current_match_status") or ""))
                in {"match", "current", "exact_match"}
            )
        if descriptor.decision_source_id == "safety_gate":
            return (
                status == "allowed_for_exact_internal_execution"
                and bool(record.get("decision_valid"))
                and binding.target_identity_match is True
            )
        if descriptor.decision_source_id == "workflow_controller":
            return status in ready_statuses or (
                bool(record.get("decision_valid"))
                and bool(record.get("integration_ready"))
                and bool(record.get("target_approval_valid"))
                and bool(record.get("safety_decision_valid"))
                and bool(record.get("artifact_bindings_valid"))
            )
        if descriptor.decision_source_id == "human_decision":
            return status in ready_statuses or (
                bool(record.get("explicit_confirmation"))
                and not _expired(_source_expiration(record))
            )
        if descriptor.decision_source_id == "validator_runner":
            return status in ready_statuses and bool(
                record.get("technical_validation_passed", True)
            )
        if descriptor.decision_source_id == "output_quality_reviewer":
            return status in ready_statuses
        if descriptor.decision_source_id == "artifact_inspector":
            return status in ready_statuses
        if descriptor.decision_source_id in {"code_surgeon", "tool_recovery_brain"}:
            return (
                bool(record.get("approved"))
                or _normal_status(str(record.get("approval_status") or "")) == "approved"
            ) and not _expired(_source_expiration(record))
        if descriptor.decision_source_id == "repair_planner":
            return bool(record.get("approved")) and not bool(record.get("blocked"))
        return status in ready_statuses

    @staticmethod
    def _source_is_blocking(
        descriptor: BobaDecisionSourceDescriptorV1,
        binding: BobaFinalDecisionSourceBindingV1,
    ) -> bool:
        record = binding.sanitized_record
        if descriptor.decision_source_id == "rights_permission_gate":
            return (
                bool(record.get("blocked"))
                or bool(record.get("requires_permission"))
                or bool(record.get("requires_rights_review"))
            )
        if descriptor.decision_source_id in {"code_surgeon", "tool_recovery_brain"}:
            return record.get("approved") is False and (
                "approved" in record or "approval_status" in record
            )
        status = _normal_status(binding.observed_decision)
        return status in {_normal_status(item) for item in descriptor.blocking_statuses}

    @staticmethod
    def _blocking_disposition(
        binding: BobaFinalDecisionSourceBindingV1,
    ) -> BobaFinalDispositionV1:
        by_domain: dict[str, BobaFinalDispositionV1] = {
            "rights": "blocked_by_rights",
            "safety": "blocked_by_safety",
            "approval": "blocked_by_target_approval",
            "workflow": "blocked_by_workflow_state",
            "technical_validation": "blocked_by_validation",
            "output_quality": "blocked_by_quality",
            "artifact_integrity": "blocked_by_artifact_integrity",
            "recovery": "blocked_by_recovery_state",
            "checkpoint": "blocked_by_recovery_state",
        }
        return by_domain.get(binding.authority_domain, "blocked_by_policy")

    @staticmethod
    def _ordered_check(
        order: int,
        name: str,
        passed: bool,
        reasons: Sequence[str],
    ) -> dict[str, Any]:
        return {
            "order": order,
            "name": name,
            "passed": passed,
            "reasons": [_safe_text(item, 300) for item in reasons[:8]],
        }

    def _lease_available(
        self,
        bus: BobaFinalDecisionBusSetV1,
        request: BobaFinalDecisionRequestV1,
        policy: BobaFinalActionPolicyV1,
    ) -> bool:
        return not any(
            item.state == "active"
            and not _expired(item.expires_at)
            and item.action_policy_id == policy.action_policy_id
            and item.target_module_id == request.target_module_id
            and item.target_operation_id == request.target_operation_id
            and item.final_decision_request_id != request.final_decision_request_id
            for item in bus.leases
        )

    def _acquire_lease(
        self,
        bus: BobaFinalDecisionBusSetV1,
        request: BobaFinalDecisionRequestV1,
        policy: BobaFinalActionPolicyV1,
        final_decision_id: str,
        expires_at: str,
    ) -> BobaFinalDecisionLeaseV1:
        if not self._lease_available(bus, request, policy):
            raise ValidationError("An active Final Decision Bus lease already exists.")
        lease_key = _stable_id(
            "final_decision_lease_key",
            request.project_id,
            policy.action_policy_id,
            request.target_module_id,
            request.target_operation_id,
        )
        lease = BobaFinalDecisionLeaseV1(
            final_decision_lease_id=_stable_id(
                "final_decision_lease", request.final_decision_request_id, final_decision_id
            ),
            project_id=request.project_id,
            action_policy_id=policy.action_policy_id,
            target_module_id=request.target_module_id,
            target_operation_id=request.target_operation_id,
            final_decision_request_id=request.final_decision_request_id,
            final_decision_id=final_decision_id,
            lease_key=lease_key,
            expires_at=expires_at,
        )
        bus.leases.append(lease)
        return lease

    @staticmethod
    def _decision(
        bus: BobaFinalDecisionBusSetV1,
        final_decision_id: str,
    ) -> BobaFinalDecisionV1:
        for decision in bus.final_decisions:
            if decision.final_decision_id == final_decision_id:
                return decision
        raise NotFoundError("Final Decision Bus decision was not found.")

    @staticmethod
    def _envelope(
        bus: BobaFinalDecisionBusSetV1,
        dispatch_envelope_id: str,
    ) -> BobaFinalDispatchEnvelopeV1:
        for envelope in bus.dispatch_envelopes:
            if envelope.dispatch_envelope_id == dispatch_envelope_id:
                return envelope
        raise NotFoundError("Final Decision Bus dispatch envelope was not found.")

    @staticmethod
    def _decision_invalidated(
        bus: BobaFinalDecisionBusSetV1,
        final_decision_id: str,
    ) -> bool:
        return any(item.final_decision_id == final_decision_id for item in bus.invalidations)

    @staticmethod
    def _conflict(
        request: BobaFinalDecisionRequestV1,
        conflict_type: BobaFinalConflictTypeV1,
        source_binding_ids: Sequence[str],
        summary: str,
    ) -> BobaFinalDecisionConflictV1:
        conflict_id = _stable_id(
            "final_decision_conflict",
            request.final_decision_request_id,
            conflict_type,
            sorted(source_binding_ids),
            summary,
        )
        return BobaFinalDecisionConflictV1(
            conflict_id=conflict_id,
            final_decision_request_id=request.final_decision_request_id,
            conflict_type=conflict_type,
            severity="error",
            source_binding_ids=list(source_binding_ids),
            bounded_summary=_safe_text(summary, 1_200),
        )

    def _incident_for_disposition(
        self,
        bus: BobaFinalDecisionBusSetV1,
        request: BobaFinalDecisionRequestV1,
        disposition: BobaFinalDispositionV1,
        summary: str,
    ) -> BobaFinalDecisionIncidentV1:
        incident_type_map: dict[str, BobaFinalIncidentTypeV1] = {
            "invalid": "invalid_request",
            "hold_missing_evidence": "missing_required_evidence",
            "hold_stale_evidence": "stale_required_evidence",
            "hold_conflicting_evidence": "conflicting_authority",
            "hold_human_review": "uncertain_state",
            "blocked_by_rights": "rights_block",
            "blocked_by_safety": "safety_block",
            "blocked_by_target_approval": "approval_block",
            "blocked_by_validation": "validation_block",
            "blocked_by_quality": "quality_block",
            "blocked_by_artifact_integrity": "artifact_block",
            "blocked_by_workflow_state": "workflow_block",
            "blocked_by_recovery_state": "recovery_block",
            "blocked_by_policy": "policy_mismatch",
        }
        incident_type = incident_type_map.get(disposition, "uncertain_state")
        fingerprint = _stable_id(
            "final_decision_incident",
            request.final_decision_request_id,
            incident_type,
            _safe_text(summary, 400),
        )
        existing = next(
            (item for item in bus.incidents if item.fingerprint == fingerprint),
            None,
        )
        if existing is not None:
            replacement = existing.model_copy(
                update={"occurrence_count": existing.occurrence_count + 1}
            )
            bus.incidents = [
                replacement if item.incident_id == existing.incident_id else item
                for item in bus.incidents
            ]
            return replacement
        incident = BobaFinalDecisionIncidentV1(
            incident_id=fingerprint,
            final_decision_request_id=request.final_decision_request_id,
            incident_type=incident_type,
            severity="warning",
            bounded_summary=_safe_text(summary or disposition, 1_200),
            fingerprint=fingerprint,
        )
        bus.incidents.append(incident)
        return incident

    def _event(
        self,
        bus: BobaFinalDecisionBusSetV1,
        event_type: BobaFinalEventTypeV1,
        final_decision_request_id: str,
        technical_message: str,
        easy_message: str,
        *,
        final_decision_id: str = "",
        dispatch_envelope_id: str = "",
        severity: Literal["info", "warning", "error", "critical", "unknown"] = "info",
        requires_attention: bool = False,
    ) -> BobaFinalDecisionEventV1:
        sequence = (
            max(
                len(bus.events),
                self.store.boba_final_decision_last_event_sequence(bus.project_id),
            )
            + 1
        )
        event = BobaFinalDecisionEventV1(
            event_id=_stable_id(
                "final_decision_event",
                bus.project_id,
                sequence,
                event_type,
                final_decision_request_id,
                final_decision_id,
                dispatch_envelope_id,
            ),
            project_id=bus.project_id,
            final_decision_request_id=final_decision_request_id,
            final_decision_id=final_decision_id,
            dispatch_envelope_id=dispatch_envelope_id,
            sequence=sequence,
            event_type=event_type,
            technical_message=_safe_text(technical_message, 1_600),
            easy_message=_safe_text(easy_message, 1_600),
            confirmed_fact="Final Decision Bus did not execute a target operation.",
            severity=severity,
            requires_attention=requires_attention,
        )
        bus.events.append(event)
        if len(bus.events) > _MAX_EVENTS:
            bus.events = bus.events[-_MAX_EVENTS:]
        return event

    @staticmethod
    def _refresh_summary(bus: BobaFinalDecisionBusSetV1) -> None:
        bus.summary = BobaFinalDecisionSummaryV1(
            registry_snapshot_count=len(bus.registry_snapshots),
            request_count=len(bus.decision_requests),
            source_binding_count=len(bus.source_bindings),
            policy_evaluation_count=len(bus.policy_evaluations),
            final_decision_count=len(bus.final_decisions),
            ready_decision_count=sum(item.ready_for_dispatch for item in bus.final_decisions),
            active_envelope_count=sum(
                not item.consumed and not item.invalidated and not _expired(item.expires_at)
                for item in bus.dispatch_envelopes
            ),
            consumed_envelope_count=sum(item.consumed for item in bus.dispatch_envelopes),
            incident_count=len(bus.incidents),
            limitations=[
                "The summary reports dispatch authorization state, never target execution state.",
            ],
        )

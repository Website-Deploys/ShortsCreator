"""Persisted, exact-stage control for the internal Olympus workflow."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.integration_layer import (
    BobaIntegrationApprovalBindingV1,
    BobaIntegrationArtifactReferenceV1,
    BobaIntegrationLayerV1,
    BobaIntegrationOperationClassV1,
    BobaIntegrationResponseV1,
    BobaIntegrationSafetyBindingV1,
    BobaIntegrationSideEffectClassV1,
)
from olympus.boba.output_quality_reviewer import BobaOutputAcceptanceDecisionV1
from olympus.boba.safety_gate import BobaSafetyDecisionV1
from olympus.platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore


BobaWorkflowStageScopeV1 = Literal[
    "project",
    "clip",
    "output",
    "recovery",
    "unknown",
]
BobaWorkflowProjectStateV1 = Literal[
    "uninitialized",
    "created",
    "inspecting",
    "rights_review_required",
    "ready",
    "stage_ready",
    "stage_running",
    "stage_completed",
    "awaiting_approval",
    "awaiting_safety_decision",
    "awaiting_human_review",
    "recovery_required",
    "recovery_in_progress",
    "recovery_review_required",
    "resume_eligibility_review",
    "transition_ready",
    "transition_running",
    "internal_output_complete",
    "paused",
    "blocked",
    "cancelled",
    "failed",
    "unknown",
]
BobaWorkflowRunStatusV1 = Literal[
    "created",
    "active",
    "paused",
    "blocked",
    "recovery",
    "completed",
    "cancelled",
    "failed",
    "unknown",
]
BobaWorkflowStageStateV1 = Literal[
    "pending",
    "dependency_blocked",
    "ready",
    "awaiting_approval",
    "awaiting_safety_decision",
    "running",
    "completed",
    "completed_with_limitations",
    "failed",
    "timed_out",
    "cancelled",
    "recovery_required",
    "superseded",
    "skipped_not_required",
    "blocked",
    "unknown",
]
BobaWorkflowDependencyStatusV1 = Literal[
    "ready",
    "incomplete",
    "missing",
    "stale",
    "malformed",
    "conflicting",
    "blocked",
    "unknown",
]
BobaWorkflowTransitionTypeV1 = Literal[
    "create_initial_stage",
    "advance_read_only",
    "advance_exact_internal_stage",
    "retry_stage",
    "supersede_failed_stage",
    "enter_recovery",
    "return_from_recovery",
    "complete_internal_output",
    "pause",
    "cancel",
    "unknown",
]
BobaWorkflowTransitionDecisionValueV1 = Literal[
    "allowed_read_only_transition",
    "allowed_exact_internal_transition",
    "awaiting_approval",
    "awaiting_safety_decision",
    "awaiting_human_review",
    "more_evidence_required",
    "recovery_required",
    "blocked_rights",
    "blocked_stale_state",
    "blocked_dependency",
    "blocked_checkpoint",
    "blocked_validation",
    "blocked_quality",
    "blocked_concurrency",
    "blocked_idempotency",
    "invalid_transition",
    "expired",
    "denied",
    "unknown",
]
BobaWorkflowPauseCategoryV1 = Literal[
    "manual",
    "stage_failure",
    "validation_failure",
    "quality_rejection",
    "rights_block",
    "safety_block",
    "approval_required",
    "checkpoint_issue",
    "stale_state",
    "concurrency_conflict",
    "budget_exhausted",
    "recovery_required",
    "uncertain_state",
    "unknown",
]
BobaWorkflowRecoveryHoldStatusV1 = Literal[
    "created",
    "awaiting_autopilot",
    "recovery_in_progress",
    "awaiting_quality_review",
    "awaiting_safety_review",
    "awaiting_human_review",
    "resolved_pending_resume_review",
    "unresolved",
    "blocked",
    "released",
    "unknown",
]
BobaWorkflowLeaseModeV1 = Literal[
    "advisory_read",
    "read_only_transition",
    "exact_internal_transition",
    "unknown",
]
BobaWorkflowLeaseStatusV1 = Literal[
    "active",
    "released",
    "expired",
    "conflicting",
    "unknown",
]
BobaWorkflowIncidentTypeV1 = Literal[
    "invalid_transition",
    "stage_failure",
    "stage_timeout",
    "missing_artifact",
    "stale_artifact",
    "malformed_artifact",
    "rights_block",
    "approval_block",
    "safety_block",
    "checkpoint_block",
    "validation_failure",
    "quality_rejection",
    "integration_failure",
    "concurrency_conflict",
    "idempotency_conflict",
    "revision_conflict",
    "recovery_failure",
    "uncertain_state",
    "unknown",
]
BobaWorkflowEventTypeV1 = Literal[
    "workflow_created",
    "stage_created",
    "stage_ready",
    "stage_started",
    "stage_completed",
    "stage_failed",
    "stage_blocked",
    "transition_requested",
    "transition_allowed",
    "transition_blocked",
    "workflow_paused",
    "recovery_requested",
    "recovery_started",
    "recovery_completed",
    "quality_review_required",
    "human_review_required",
    "safety_review_required",
    "resume_eligibility_started",
    "resume_eligible",
    "resume_blocked",
    "exact_internal_transition_started",
    "exact_internal_transition_completed",
    "internal_output_completed",
    "workflow_cancelled",
    "unknown",
]
BobaWorkflowHandoffTargetV1 = Literal[
    "autopilot_controller",
    "observer",
    "error_doctor",
    "root_cause_analyzer",
    "repair_planner",
    "code_surgeon",
    "tool_recovery_brain",
    "output_quality_reviewer",
    "safety_gate",
    "integration_layer",
    "checkpoint_recovery_manager",
    "validator_runner",
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
_SECRET_KEY = re.compile(
    r"(?i)(?:secret|password|passwd|token|credential|cookie|authorization|api[_-]?key)"
)
_OMITTED_EXPORT_KEYS = frozenset(
    {
        "complete_log",
        "complete_logs",
        "full_log",
        "full_logs",
        "media_bytes",
        "raw_audio",
        "raw_media",
        "raw_video",
        "source_media_bytes",
    }
)
_TERMINAL_STAGE_STATES = frozenset(
    {
        "completed",
        "completed_with_limitations",
        "failed",
        "timed_out",
        "cancelled",
        "superseded",
        "skipped_not_required",
        "blocked",
    }
)
_TERMINAL_RUN_STATUSES = frozenset({"completed", "cancelled", "failed"})
_ALLOWED_QUALITY_DECISIONS = frozenset(
    {
        "accepted_for_next_internal_stage",
        "accepted_with_disclosed_limitations",
    }
)
_SAFE_AUTOMATIC_CLASSES = frozenset({"read_only", "planning"})
_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


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


def _bounded_text(value: Any, *, maximum: int = 900) -> str:
    text = " ".join(str(value or "").split())
    return text[:maximum]


def _unique(values: Sequence[Any], *, limit: int = 64, maximum: int = 256) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _bounded_text(value, maximum=maximum)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def sanitize_workflow_export(value: Any) -> Any:
    if isinstance(value, BobaContract):
        return sanitize_workflow_export(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:512]:
            safe_key = _bounded_text(key, maximum=160)
            if not safe_key:
                continue
            if safe_key.casefold() in _OMITTED_EXPORT_KEYS:
                result[safe_key] = "[omitted]"
            elif _SECRET_KEY.search(safe_key):
                result[safe_key] = "[redacted]"
            else:
                result[safe_key] = sanitize_workflow_export(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [sanitize_workflow_export(item) for item in list(value)[:2_048]]
    if isinstance(value, str):
        text = _bounded_text(value, maximum=2_000)
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
        raise ValueError("External artifact URLs are unavailable.")
    if reference.startswith("//") or _WINDOWS_ABSOLUTE.match(reference):
        raise ValueError("Absolute and UNC artifact paths are unavailable.")
    if reference.startswith("/"):
        raise ValueError("Absolute artifact paths are unavailable.")
    if any(part in {"", ".", ".."} for part in reference.split("/")):
        raise ValueError("Artifact traversal and malformed path segments are unavailable.")
    return reference


class BobaWorkflowStageDefinitionV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_definition_id: str = Field(min_length=1, max_length=180)
    workflow_definition_id: str = Field(min_length=1, max_length=180)
    stage_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=240)
    stage_version: str = Field(default="1", min_length=1, max_length=80)
    stage_scope: BobaWorkflowStageScopeV1
    operation_module_id: str = Field(min_length=1, max_length=160)
    operation_id: str = Field(min_length=1, max_length=240)
    operation_class: BobaIntegrationOperationClassV1
    side_effect_class: BobaIntegrationSideEffectClassV1
    required_predecessor_stage_ids: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    allowed_next_stage_ids: list[str] = Field(default_factory=list, max_length=32)
    required_artifact_types: list[str] = Field(default_factory=list, max_length=64)
    optional_artifact_types: list[str] = Field(default_factory=list, max_length=64)
    produced_artifact_types: list[str] = Field(default_factory=list, max_length=64)
    rights_gate_required: bool = False
    target_approval_required: bool = False
    safety_gate_required: bool = False
    checkpoint_required: bool = False
    technical_validation_required: bool = False
    output_quality_review_required: bool = False
    human_review_required: bool = False
    idempotency_required: bool = True
    maximum_attempts: int = Field(default=1, ge=1, le=12)
    timeout_seconds: int = Field(default=300, ge=1, le=3_600)
    terminal: bool = False
    recovery_route: str = Field(default="autopilot_controller", max_length=160)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowDefinitionSnapshotV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_definition_id: str = Field(min_length=1, max_length=180)
    workflow_name: str = Field(min_length=1, max_length=240)
    workflow_version: str = Field(default="1", min_length=1, max_length=80)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    stage_definition_ids: list[str] = Field(default_factory=list, max_length=64)
    start_stage_id: str = Field(min_length=1, max_length=160)
    terminal_stage_ids: list[str] = Field(default_factory=list, max_length=16)
    required_stage_ids: list[str] = Field(default_factory=list, max_length=64)
    optional_stage_ids: list[str] = Field(default_factory=list, max_length=64)
    workflow_graph_digest: str = Field(min_length=64, max_length=64)
    immutable: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowRunV1(BobaContract):
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    correlation_id: str = Field(min_length=1, max_length=180)
    workflow_definition_id: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    started_at: str | None = Field(default=None, max_length=80)
    updated_at: str = Field(default_factory=now_iso, max_length=80)
    completed_at: str | None = Field(default=None, max_length=80)
    run_status: BobaWorkflowRunStatusV1 = "created"
    current_project_state: BobaWorkflowProjectStateV1 = "created"
    current_stage_instance_ids: list[str] = Field(default_factory=list, max_length=256)
    completed_stage_instance_ids: list[str] = Field(
        default_factory=list,
        max_length=2_048,
    )
    failed_stage_instance_ids: list[str] = Field(default_factory=list, max_length=512)
    blocked_stage_instance_ids: list[str] = Field(default_factory=list, max_length=512)
    active_transition_request_id: str | None = Field(default=None, max_length=180)
    active_transition_decision_id: str | None = Field(default=None, max_length=180)
    active_integration_transaction_id: str | None = Field(default=None, max_length=180)
    active_safety_decision_id: str | None = Field(default=None, max_length=180)
    active_autopilot_run_id: str | None = Field(default=None, max_length=180)
    active_recovery_hold_id: str | None = Field(default=None, max_length=180)
    pause_record_ids: list[str] = Field(default_factory=list, max_length=256)
    incident_ids: list[str] = Field(default_factory=list, max_length=512)
    human_decision_ids: list[str] = Field(default_factory=list, max_length=512)
    event_ids: list[str] = Field(default_factory=list, max_length=4_096)
    execution_lease_id: str | None = Field(default=None, max_length=180)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    revision: int = Field(default=1, ge=1)
    internal_output_complete: bool = False
    upload_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    stop_reason: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=128)


class BobaWorkflowStageInstanceV1(BobaContract):
    stage_instance_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str | None = Field(default=None, max_length=160)
    output_id: str | None = Field(default=None, max_length=160)
    stage_definition_id: str = Field(min_length=1, max_length=180)
    stage_id: str = Field(min_length=1, max_length=160)
    attempt_number: int = Field(default=1, ge=1, le=12)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    started_at: str | None = Field(default=None, max_length=80)
    completed_at: str | None = Field(default=None, max_length=80)
    status: BobaWorkflowStageStateV1 = "pending"
    predecessor_stage_instance_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    successor_stage_instance_ids: list[str] = Field(default_factory=list, max_length=64)
    input_artifact_binding_ids: list[str] = Field(default_factory=list, max_length=128)
    output_artifact_binding_ids: list[str] = Field(default_factory=list, max_length=128)
    dependency_check_id: str | None = Field(default=None, max_length=180)
    transition_request_id: str | None = Field(default=None, max_length=180)
    transition_decision_id: str | None = Field(default=None, max_length=180)
    integration_transaction_id: str | None = Field(default=None, max_length=180)
    safety_decision_id: str | None = Field(default=None, max_length=180)
    approval_record_id: str | None = Field(default=None, max_length=180)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    input_digest: str = Field(default=_EMPTY_DIGEST, min_length=64, max_length=64)
    idempotency_key: str = Field(default="", max_length=180)
    result_digest: str = Field(default="", max_length=64)
    failure_summary: str = Field(default="", max_length=900)
    recovery_required: bool = False
    human_review_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowArtifactBindingV1(BobaContract):
    artifact_binding_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    stage_instance_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str | None = Field(default=None, max_length=160)
    output_id: str | None = Field(default=None, max_length=160)
    artifact_type: str = Field(min_length=1, max_length=160)
    producer_module_id: str = Field(min_length=1, max_length=160)
    producer_record_id: str = Field(default="", max_length=180)
    schema_id: str = Field(min_length=1, max_length=160)
    schema_version: str = Field(min_length=1, max_length=80)
    artifact_digest: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    sanitized_storage_reference: str = Field(default="", max_length=500)
    immutable: bool = True
    accepted_output: bool = False
    source_media: bool = False
    source_media_read_only: bool = True
    required: bool = True
    available: bool = True
    stale: bool = False
    malformed: bool = False
    rights_relevant: bool = False
    safety_relevant: bool = False
    quality_relevant: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("sanitized_storage_reference")
    @classmethod
    def validate_storage_reference(cls, value: str) -> str:
        return _validate_storage_reference(value)

    @model_validator(mode="after")
    def validate_binding(self) -> BobaWorkflowArtifactBindingV1:
        if self.available and not self.sanitized_storage_reference:
            raise ValueError("Available artifacts require a sanitized storage reference.")
        if self.source_media and self.artifact_type not in {
            "source_media",
            "source_asset",
            "registered_source",
        }:
            raise ValueError("Source media cannot be presented as generated output.")
        if self.source_media and self.accepted_output:
            raise ValueError("Source media cannot also be an accepted generated output.")
        if self.accepted_output and not self.immutable:
            raise ValueError("Accepted outputs must be immutable.")
        if self.source_media and not self.source_media_read_only:
            raise ValueError("Source media must remain read-only.")
        parts = self.sanitized_storage_reference.split("/")
        if len(parts) >= 2 and parts[0] == "projects" and parts[1] != self.project_id:
            raise ValueError("Cross-project artifact references are unavailable.")
        return self


class BobaWorkflowDependencyCheckV1(BobaContract):
    dependency_check_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    stage_instance_id: str = Field(min_length=1, max_length=180)
    required_predecessor_stage_ids: list[str] = Field(default_factory=list, max_length=64)
    completed_predecessor_stage_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    missing_predecessor_stage_ids: list[str] = Field(default_factory=list, max_length=64)
    failed_predecessor_stage_ids: list[str] = Field(default_factory=list, max_length=64)
    required_artifact_binding_ids: list[str] = Field(default_factory=list, max_length=128)
    available_artifact_binding_ids: list[str] = Field(default_factory=list, max_length=128)
    stale_artifact_binding_ids: list[str] = Field(default_factory=list, max_length=128)
    malformed_artifact_binding_ids: list[str] = Field(default_factory=list, max_length=128)
    rights_ready: bool = False
    approval_ready: bool = False
    safety_ready: bool = False
    checkpoint_ready: bool = False
    validation_ready: bool = False
    quality_ready: bool = False
    human_review_ready: bool = False
    active_conflict_present: bool = False
    dependency_status: BobaWorkflowDependencyStatusV1 = "unknown"
    blocks_transition: bool = True
    failure_reasons: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowTransitionRequestV1(BobaContract):
    transition_request_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str | None = Field(default=None, max_length=160)
    output_id: str | None = Field(default=None, max_length=160)
    source_stage_instance_id: str = Field(min_length=1, max_length=180)
    target_stage_definition_id: str = Field(min_length=1, max_length=180)
    transition_type: BobaWorkflowTransitionTypeV1
    requested_operation_id: str = Field(min_length=1, max_length=240)
    requested_at: str = Field(default_factory=now_iso, max_length=80)
    requested_by_module: str = Field(default="workflow_controller", max_length=160)
    request_reason: str = Field(min_length=1, max_length=900)
    current_revision: int = Field(ge=1)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    input_artifact_digest: str = Field(min_length=64, max_length=64)
    approval_record_id: str | None = Field(default=None, max_length=180)
    safety_decision_id: str | None = Field(default=None, max_length=180)
    integration_request_id: str | None = Field(default=None, max_length=180)
    checkpoint_reference: str | None = Field(default=None, max_length=500)
    checkpoint_digest: str | None = Field(default=None, max_length=128)
    quality_decision_id: str | None = Field(default=None, max_length=180)
    human_decision_id: str | None = Field(default=None, max_length=180)
    request_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=180)
    expires_at: str = Field(min_length=1, max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("checkpoint_reference")
    @classmethod
    def validate_checkpoint_reference(cls, value: str | None) -> str | None:
        return _validate_storage_reference(value) if value else value


class BobaWorkflowTransitionDecisionV1(BobaContract):
    transition_decision_id: str = Field(min_length=1, max_length=180)
    transition_request_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    decision: BobaWorkflowTransitionDecisionValueV1
    decision_summary: str = Field(min_length=1, max_length=900)
    source_stage_valid: bool = False
    target_stage_valid: bool = False
    graph_transition_valid: bool = False
    dependency_check_id: str | None = Field(default=None, max_length=180)
    artifact_bindings_valid: bool = False
    project_snapshot_current: bool = False
    workflow_revision_current: bool = False
    rights_clear: bool = False
    target_approval_valid: bool = False
    safety_decision_valid: bool = False
    integration_ready: bool = False
    checkpoint_ready: bool = False
    validation_ready: bool = False
    quality_ready: bool = False
    human_review_complete: bool = False
    lease_available: bool = False
    idempotency_clear: bool = False
    conditions: list[str] = Field(default_factory=list, max_length=64)
    unmet_conditions: list[str] = Field(default_factory=list, max_length=64)
    blocking_reasons: list[str] = Field(default_factory=list, max_length=64)
    next_project_state: BobaWorkflowProjectStateV1 = "unknown"
    decision_created_at: str = Field(default_factory=now_iso, max_length=80)
    decision_expires_at: str = Field(min_length=1, max_length=80)
    decision_valid: bool = False
    target_revalidation_required: bool = True
    workflow_resume_authorized: Literal[False] = False
    upload_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowPauseRecordV1(BobaContract):
    pause_record_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    stage_instance_id: str | None = Field(default=None, max_length=180)
    paused_at: str = Field(default_factory=now_iso, max_length=80)
    pause_reason: str = Field(min_length=1, max_length=900)
    pause_category: BobaWorkflowPauseCategoryV1
    requested_by: str = Field(default="workflow_controller", max_length=160)
    automatic_pause: bool = False
    project_state_at_pause: BobaWorkflowProjectStateV1
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    active_operation_status: str = Field(default="none", max_length=160)
    source_media_protected: bool = True
    accepted_outputs_protected: bool = True
    recovery_required: bool = False
    human_review_required: bool = False
    resume_conditions: list[str] = Field(default_factory=list, max_length=64)
    released_at: str | None = Field(default=None, max_length=80)
    released_by_decision_id: str | None = Field(default=None, max_length=180)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowRecoveryHoldV1(BobaContract):
    recovery_hold_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    failed_stage_instance_id: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    recovery_reason: str = Field(min_length=1, max_length=900)
    observer_record_id: str | None = Field(default=None, max_length=180)
    error_doctor_case_id: str | None = Field(default=None, max_length=180)
    root_cause_case_id: str | None = Field(default=None, max_length=180)
    repair_plan_id: str | None = Field(default=None, max_length=180)
    autopilot_run_id: str | None = Field(default=None, max_length=180)
    code_surgeon_run_id: str | None = Field(default=None, max_length=180)
    tool_recovery_run_id: str | None = Field(default=None, max_length=180)
    output_quality_decision_id: str | None = Field(default=None, max_length=180)
    safety_decision_id: str | None = Field(default=None, max_length=180)
    hold_status: BobaWorkflowRecoveryHoldStatusV1 = "created"
    recovery_artifact_ids: list[str] = Field(default_factory=list, max_length=128)
    original_project_snapshot_digest: str = Field(min_length=64, max_length=64)
    current_project_snapshot_digest: str = Field(min_length=64, max_length=64)
    resolution_summary: str = Field(default="", max_length=900)
    human_review_required: bool = False
    released: bool = False
    released_at: str | None = Field(default=None, max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowResumeEligibilityReviewV1(BobaContract):
    resume_eligibility_review_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    recovery_hold_id: str = Field(min_length=1, max_length=180)
    paused_stage_instance_id: str = Field(min_length=1, max_length=180)
    proposed_target_stage_definition_id: str = Field(min_length=1, max_length=180)
    reviewed_at: str = Field(default_factory=now_iso, max_length=80)
    project_snapshot_match: bool = False
    workflow_revision_match: bool = False
    recovery_resolved: bool = False
    output_quality_accepted: bool = False
    technical_validation_passed: bool = False
    rights_clear: bool = False
    safety_decision_valid: bool = False
    target_approval_valid: bool = False
    checkpoint_valid: bool = False
    rollback_state_clear: bool = False
    no_active_recovery: bool = False
    no_active_conflicting_transition: bool = False
    artifacts_current: bool = False
    dependencies_ready: bool = False
    human_review_complete: bool = False
    retry_budget_clear: bool = False
    resume_eligible: bool = False
    missing_conditions: list[str] = Field(default_factory=list, max_length=64)
    blocking_conditions: list[str] = Field(default_factory=list, max_length=64)
    safest_next_action: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowExecutionLeaseV1(BobaContract):
    execution_lease_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    transition_request_id: str | None = Field(default=None, max_length=180)
    stage_instance_id: str | None = Field(default=None, max_length=180)
    lease_mode: BobaWorkflowLeaseModeV1
    owner_id: str = Field(min_length=1, max_length=180)
    acquired_at: str = Field(default_factory=now_iso, max_length=80)
    refreshed_at: str = Field(default_factory=now_iso, max_length=80)
    expires_at: str = Field(min_length=1, max_length=80)
    lease_status: BobaWorkflowLeaseStatusV1 = "active"
    revision_at_acquisition: int = Field(ge=1)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    stale: bool = False
    conflicting_lease_ids: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowIncidentV1(BobaContract):
    incident_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    stage_instance_id: str | None = Field(default=None, max_length=180)
    transition_request_id: str | None = Field(default=None, max_length=180)
    integration_transaction_id: str | None = Field(default=None, max_length=180)
    incident_type: BobaWorkflowIncidentTypeV1
    severity: Literal["info", "warning", "error", "critical", "unknown"] = "unknown"
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(min_length=1, max_length=900)
    observed_at: str = Field(default_factory=now_iso, max_length=80)
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    repeated_fingerprint: str = Field(min_length=64, max_length=64)
    occurrence_count: int = Field(default=1, ge=1)
    project_state_uncertain: bool = False
    source_media_risk: bool = False
    accepted_output_risk: bool = False
    immediate_controller_action: str = Field(default="pause", max_length=160)
    recovery_handoff_required: bool = False
    human_review_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowHumanDecisionV1(BobaContract):
    human_decision_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    stage_instance_id: str | None = Field(default=None, max_length=180)
    transition_request_id: str | None = Field(default=None, max_length=180)
    decision_type: str = Field(min_length=1, max_length=160)
    decision: str = Field(min_length=1, max_length=160)
    bounded_reason: str = Field(min_length=1, max_length=900)
    reviewer_reference: str = Field(min_length=1, max_length=160)
    decided_at: str = Field(default_factory=now_iso, max_length=80)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(ge=1)
    explicit_confirmation: bool = False
    conditions: list[str] = Field(default_factory=list, max_length=64)
    expires_at: str | None = Field(default=None, max_length=80)
    upload_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str | None = Field(default=None, max_length=160)
    sequence: int = Field(ge=1)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    event_type: BobaWorkflowEventTypeV1
    severity: Literal["info", "warning", "error", "critical", "unknown"] = "info"
    project_state: BobaWorkflowProjectStateV1
    stage_instance_id: str | None = Field(default=None, max_length=180)
    transition_request_id: str | None = Field(default=None, max_length=180)
    module_id: str = Field(default="workflow_controller", max_length=160)
    operation_id: str = Field(default="", max_length=240)
    technical_message: str = Field(min_length=1, max_length=1_200)
    easy_message: str = Field(min_length=1, max_length=700)
    confirmed_fact: str = Field(default="", max_length=700)
    assessment: str = Field(default="", max_length=700)
    progress_current: int | None = Field(default=None, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    progress_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    requires_attention: bool = False
    available_user_actions: list[str] = Field(default_factory=list, max_length=16)
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    stage_instance_id: str | None = Field(default=None, max_length=180)
    transition_request_id: str | None = Field(default=None, max_length=180)
    source_module_id: str = Field(default="workflow_controller", max_length=160)
    target_module_id: BobaWorkflowHandoffTargetV1
    reason: str = Field(min_length=1, max_length=900)
    current_project_state: BobaWorkflowProjectStateV1
    required_inputs: list[str] = Field(default_factory=list, max_length=64)
    artifact_binding_ids: list[str] = Field(default_factory=list, max_length=128)
    satisfied_conditions: list[str] = Field(default_factory=list, max_length=64)
    blocking_conditions: list[str] = Field(default_factory=list, max_length=64)
    allowed_actions: list[str] = Field(default_factory=list, max_length=64)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=64)
    apply_automatically: bool = False
    human_approval_required: bool = True
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowControllerSummaryV1(BobaContract):
    workflow_definition_count: int = Field(default=0, ge=0)
    total_workflow_runs: int = Field(default=0, ge=0)
    active_workflow_run_count: int = Field(default=0, ge=0)
    paused_workflow_run_count: int = Field(default=0, ge=0)
    recovery_hold_count: int = Field(default=0, ge=0)
    blocked_workflow_run_count: int = Field(default=0, ge=0)
    completed_internal_output_count: int = Field(default=0, ge=0)
    total_stage_instance_count: int = Field(default=0, ge=0)
    completed_stage_count: int = Field(default=0, ge=0)
    failed_stage_count: int = Field(default=0, ge=0)
    blocked_stage_count: int = Field(default=0, ge=0)
    total_transition_request_count: int = Field(default=0, ge=0)
    allowed_transition_count: int = Field(default=0, ge=0)
    denied_transition_count: int = Field(default=0, ge=0)
    stale_transition_count: int = Field(default=0, ge=0)
    recovery_transition_count: int = Field(default=0, ge=0)
    quality_block_count: int = Field(default=0, ge=0)
    safety_block_count: int = Field(default=0, ge=0)
    rights_block_count: int = Field(default=0, ge=0)
    concurrency_block_count: int = Field(default=0, ge=0)
    current_workflow_run_id: str | None = Field(default=None, max_length=180)
    current_project_state: BobaWorkflowProjectStateV1 = "uninitialized"
    current_stage: str = Field(default="", max_length=160)
    next_valid_stage: str = Field(default="", max_length=160)
    current_pause_reason: str = Field(default="", max_length=900)
    next_required_human_action: str = Field(default="", max_length=900)
    safest_next_action: str = Field(default="", max_length=900)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowControllerSignalUsageV1(BobaContract):
    built_in_workflow_definition_used: bool = False
    project_workflow_run_used: bool = False
    stage_dependency_validation_used: bool = False
    artifact_binding_validation_used: bool = False
    rights_gate_used: bool = False
    autopilot_handoff_used: bool = False
    output_quality_reviewer_used: bool = False
    safety_gate_used: bool = False
    integration_layer_used: bool = False
    target_module_approval_used: bool = False
    checkpoint_reference_used: bool = False
    execution_lease_used: bool = False
    idempotency_used: bool = False
    human_decision_used: bool = False
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
    unrestricted_workflow_resume_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    service_restart_used: Literal[False] = False
    process_kill_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_access_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    uploading_used: Literal[False] = False
    publication_used: Literal[False] = False
    push_used: Literal[False] = False
    merge_used: Literal[False] = False
    deployment_used: Literal[False] = False
    rights_bypass_used: Literal[False] = False
    safety_bypass_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaWorkflowControllerSetV1(BobaContract):
    schema_version: Literal["boba_workflow_controller_v1"] = (
        "boba_workflow_controller_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    workflow_definition_snapshots: list[BobaWorkflowDefinitionSnapshotV1] = Field(
        default_factory=list,
        max_length=16,
    )
    stage_definitions: list[BobaWorkflowStageDefinitionV1] = Field(
        default_factory=list,
        max_length=128,
    )
    workflow_runs: list[BobaWorkflowRunV1] = Field(default_factory=list, max_length=128)
    stage_instances: list[BobaWorkflowStageInstanceV1] = Field(
        default_factory=list,
        max_length=8_192,
    )
    transition_requests: list[BobaWorkflowTransitionRequestV1] = Field(
        default_factory=list,
        max_length=8_192,
    )
    transition_decisions: list[BobaWorkflowTransitionDecisionV1] = Field(
        default_factory=list,
        max_length=8_192,
    )
    artifact_bindings: list[BobaWorkflowArtifactBindingV1] = Field(
        default_factory=list,
        max_length=16_384,
    )
    dependency_checks: list[BobaWorkflowDependencyCheckV1] = Field(
        default_factory=list,
        max_length=8_192,
    )
    pause_records: list[BobaWorkflowPauseRecordV1] = Field(
        default_factory=list,
        max_length=2_048,
    )
    recovery_holds: list[BobaWorkflowRecoveryHoldV1] = Field(
        default_factory=list,
        max_length=2_048,
    )
    resume_eligibility_reviews: list[BobaWorkflowResumeEligibilityReviewV1] = Field(
        default_factory=list,
        max_length=2_048,
    )
    execution_leases: list[BobaWorkflowExecutionLeaseV1] = Field(
        default_factory=list,
        max_length=2_048,
    )
    incidents: list[BobaWorkflowIncidentV1] = Field(default_factory=list, max_length=4_096)
    human_decisions: list[BobaWorkflowHumanDecisionV1] = Field(
        default_factory=list,
        max_length=4_096,
    )
    workflow_events: list[BobaWorkflowEventV1] = Field(
        default_factory=list,
        max_length=16_384,
    )
    handoffs: list[BobaWorkflowHandoffV1] = Field(default_factory=list, max_length=4_096)
    controller_summary: BobaWorkflowControllerSummaryV1 = Field(
        default_factory=BobaWorkflowControllerSummaryV1
    )
    signal_usage: BobaWorkflowControllerSignalUsageV1 = Field(
        default_factory=BobaWorkflowControllerSignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=128)


_BUILTIN_STAGE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "stage_id": "workflow_created",
        "display_name": "Workflow Created",
        "scope": "project",
        "module": "workflow_controller",
        "operation": "workflow_controller.create_run",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": (),
        "next": ("source_registration",),
        "produces": ("workflow_run",),
    },
    {
        "stage_id": "source_registration",
        "display_name": "Source Registration",
        "scope": "project",
        "module": "workflow_controller",
        "operation": "workflow_controller.inspect",
        "class": "read_only",
        "side_effect": "none",
        "predecessors": ("workflow_created",),
        "next": ("rights_review",),
        "required": ("source_media",),
        "produces": ("source_registration",),
    },
    {
        "stage_id": "rights_review",
        "display_name": "Rights Review",
        "scope": "project",
        "module": "rights_permission_gate",
        "operation": "rights_permission_gate.generate",
        "class": "read_only",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("source_registration",),
        "next": ("source_ready",),
        "required": ("source_media",),
        "produces": ("rights_decision",),
        "rights": True,
    },
    {
        "stage_id": "source_ready",
        "display_name": "Source Ready",
        "scope": "project",
        "module": "workflow_controller",
        "operation": "workflow_controller.plan_next",
        "class": "read_only",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("rights_review",),
        "next": ("whole_video_analysis",),
        "required": ("rights_decision",),
        "produces": ("source_ready",),
        "rights": True,
    },
    {
        "stage_id": "whole_video_analysis",
        "display_name": "Whole Video Analysis",
        "scope": "project",
        "module": "whole_video_understanding",
        "operation": "whole_video_understanding.generate",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("source_ready",),
        "next": ("candidate_discovery",),
        "required": ("source_media", "source_ready"),
        "produces": ("whole_video_understanding",),
        "rights": True,
    },
    {
        "stage_id": "candidate_discovery",
        "display_name": "Candidate Discovery",
        "scope": "project",
        "module": "candidate_clip_discovery",
        "operation": "candidate_clip_discovery.discover",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("whole_video_analysis",),
        "next": ("clip_ranking",),
        "required": ("whole_video_understanding",),
        "produces": ("candidate_clips",),
    },
    {
        "stage_id": "clip_ranking",
        "display_name": "Clip Ranking",
        "scope": "project",
        "module": "clip_ranking",
        "operation": "clip_ranking.rank",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("candidate_discovery",),
        "next": ("editorial_selection",),
        "required": ("candidate_clips",),
        "produces": ("clip_ranking",),
    },
    {
        "stage_id": "editorial_selection",
        "display_name": "Editorial Selection",
        "scope": "project",
        "module": "editorial_decision",
        "operation": "editorial_decision.generate",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("clip_ranking",),
        "next": ("creative_direction",),
        "required": ("clip_ranking",),
        "produces": ("editorial_selection",),
    },
    {
        "stage_id": "creative_direction",
        "display_name": "Creative Direction",
        "scope": "project",
        "module": "creative_director",
        "operation": "creative_director.generate",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("editorial_selection",),
        "next": ("clip_brief_generation",),
        "required": ("editorial_selection",),
        "produces": ("creative_direction",),
    },
    {
        "stage_id": "clip_brief_generation",
        "display_name": "Clip Brief Generation",
        "scope": "clip",
        "module": "clip_brief",
        "operation": "clip_brief.generate",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("creative_direction",),
        "next": (
            "hook_retention_planning",
            "caption_motion_planning",
            "music_mood_planning",
        ),
        "required": ("creative_direction",),
        "produces": ("clip_brief",),
    },
    {
        "stage_id": "hook_retention_planning",
        "display_name": "Hook and Retention Planning",
        "scope": "clip",
        "module": "hook_retention",
        "operation": "hook_retention.generate",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("clip_brief_generation",),
        "next": ("render_preparation",),
        "required": ("clip_brief",),
        "produces": ("hook_retention_plan",),
    },
    {
        "stage_id": "caption_motion_planning",
        "display_name": "Caption and Motion Planning",
        "scope": "clip",
        "module": "caption_motion",
        "operation": "caption_motion.generate",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("clip_brief_generation",),
        "next": ("render_preparation",),
        "required": ("clip_brief",),
        "produces": ("caption_motion_plan",),
    },
    {
        "stage_id": "music_mood_planning",
        "display_name": "Music Mood Planning",
        "scope": "clip",
        "module": "music_mood",
        "operation": "music_mood.generate",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("clip_brief_generation",),
        "next": ("render_preparation",),
        "required": ("clip_brief",),
        "produces": ("music_mood_plan",),
    },
    {
        "stage_id": "render_preparation",
        "display_name": "Render Preparation",
        "scope": "clip",
        "module": "olympus_editing",
        "operation": "olympus_editing.prepare_render",
        "class": "approved_execution",
        "side_effect": "isolated_generated_state",
        "predecessors": (
            "hook_retention_planning",
            "caption_motion_planning",
            "music_mood_planning",
        ),
        "next": ("rendering",),
        "required": (
            "hook_retention_plan",
            "caption_motion_plan",
            "music_mood_plan",
        ),
        "produces": ("render_timeline",),
        "approval": True,
        "safety": True,
        "checkpoint": True,
        "maximum_attempts": 2,
        "timeout": 1_800,
    },
    {
        "stage_id": "rendering",
        "display_name": "Rendering",
        "scope": "output",
        "module": "olympus_rendering",
        "operation": "olympus_rendering.render",
        "class": "approved_execution",
        "side_effect": "isolated_generated_state",
        "predecessors": ("render_preparation",),
        "next": ("technical_validation",),
        "required": ("render_timeline",),
        "produces": ("rendered_mp4", "render_manifest"),
        "approval": True,
        "safety": True,
        "checkpoint": True,
        "maximum_attempts": 2,
        "timeout": 3_600,
    },
    {
        "stage_id": "technical_validation",
        "display_name": "Technical Validation",
        "scope": "output",
        "module": "olympus_optimization",
        "operation": "olympus_optimization.validate_render",
        "class": "read_only",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("rendering",),
        "next": ("output_quality_review",),
        "required": ("rendered_mp4", "render_manifest"),
        "produces": ("technical_validation",),
        "validation": True,
    },
    {
        "stage_id": "output_quality_review",
        "display_name": "Output Quality Review",
        "scope": "output",
        "module": "output_quality_reviewer",
        "operation": "output_quality_reviewer.review",
        "class": "read_only",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("technical_validation",),
        "next": ("human_review", "internal_output_completion"),
        "required": ("technical_validation", "rendered_mp4"),
        "produces": ("output_quality_decision",),
        "quality": True,
    },
    {
        "stage_id": "human_review",
        "display_name": "Human Review",
        "scope": "output",
        "module": "workflow_controller",
        "operation": "workflow_controller.record_human_decision",
        "class": "planning",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("output_quality_review",),
        "next": ("internal_output_completion",),
        "required": ("output_quality_decision",),
        "produces": ("human_workflow_decision",),
        "human": True,
        "optional": True,
    },
    {
        "stage_id": "internal_output_completion",
        "display_name": "Internal Output Completion",
        "scope": "project",
        "module": "workflow_controller",
        "operation": "workflow_controller.complete_internal_output",
        "class": "approved_execution",
        "side_effect": "BOBA_metadata_only",
        "predecessors": ("output_quality_review",),
        "next": (),
        "required": ("output_quality_decision", "technical_validation"),
        "produces": ("internal_output_completion",),
        "rights": True,
        "approval": True,
        "safety": True,
        "validation": True,
        "quality": True,
        "terminal": True,
    },
)


def calculate_workflow_request_digest(value: Mapping[str, Any] | BobaContract) -> str:
    payload = (
        value.model_dump(mode="json")
        if isinstance(value, BobaContract)
        else dict(value)
    )
    excluded = {
        "transition_request_id",
        "request_digest",
        "requested_at",
        "expires_at",
        "warnings",
    }
    return _digest(
        {
            key: sanitize_workflow_export(item)
            for key, item in payload.items()
            if key not in excluded
        }
    )


def calculate_workflow_idempotency_key(
    *,
    project_id: str,
    workflow_run_id: str,
    stage_instance_id: str,
    transition_type: str,
    operation_id: str,
    project_snapshot_digest: str,
    workflow_revision: int,
    input_artifact_digest: str,
    approval_digest: str = "",
    safety_decision_digest: str = "",
) -> str:
    return _stable_id(
        "workflow_idempotency",
        project_id,
        workflow_run_id,
        stage_instance_id,
        transition_type,
        operation_id,
        project_snapshot_digest,
        workflow_revision,
        input_artifact_digest,
        approval_digest,
        safety_decision_digest,
    )


def validate_workflow_graph(
    stage_definitions: Sequence[BobaWorkflowStageDefinitionV1],
    *,
    start_stage_id: str,
    required_stage_ids: Sequence[str],
) -> str:
    by_id: dict[str, BobaWorkflowStageDefinitionV1] = {}
    for stage in stage_definitions:
        if stage.stage_id in by_id:
            raise ValidationError(
                "BOBA Workflow Controller rejected a duplicate stage ID.",
                details={"stage_id": stage.stage_id},
            )
        by_id[stage.stage_id] = stage
    if start_stage_id not in by_id:
        raise ValidationError("BOBA workflow start stage is missing.")
    for stage in stage_definitions:
        unknown_predecessors = sorted(
            set(stage.required_predecessor_stage_ids) - set(by_id)
        )
        unknown_successors = sorted(set(stage.allowed_next_stage_ids) - set(by_id))
        if unknown_predecessors:
            raise ValidationError(
                "BOBA workflow contains an unknown predecessor.",
                details={
                    "stage_id": stage.stage_id,
                    "unknown_predecessors": unknown_predecessors,
                },
            )
        if unknown_successors:
            raise ValidationError(
                "BOBA workflow contains an unknown successor.",
                details={
                    "stage_id": stage.stage_id,
                    "unknown_successors": unknown_successors,
                },
            )
        if stage.terminal and stage.allowed_next_stage_ids:
            raise ValidationError(
                "Terminal BOBA workflow stages cannot have successors.",
                details={"stage_id": stage.stage_id},
            )
    incoming: dict[str, int] = dict.fromkeys(by_id, 0)
    for stage in stage_definitions:
        for successor in stage.allowed_next_stage_ids:
            incoming[successor] += 1
    queue = sorted(stage_id for stage_id, count in incoming.items() if count == 0)
    visited: list[str] = []
    while queue:
        stage_id = queue.pop(0)
        visited.append(stage_id)
        for successor in by_id[stage_id].allowed_next_stage_ids:
            incoming[successor] -= 1
            if incoming[successor] == 0:
                queue.append(successor)
                queue.sort()
    if len(visited) != len(by_id):
        raise ValidationError("BOBA workflow stage graph contains a cycle.")
    reachable: set[str] = set()
    stack = [start_stage_id]
    while stack:
        stage_id = stack.pop()
        if stage_id in reachable:
            continue
        reachable.add(stage_id)
        stack.extend(by_id[stage_id].allowed_next_stage_ids)
    unreachable = sorted(set(required_stage_ids) - reachable)
    if unreachable:
        raise ValidationError(
            "BOBA workflow contains unreachable required stages.",
            details={"stage_ids": unreachable},
        )
    graph_payload = [
        {
            "stage_id": stage.stage_id,
            "stage_version": stage.stage_version,
            "scope": stage.stage_scope,
            "operation": stage.operation_id,
            "operation_class": stage.operation_class,
            "side_effect_class": stage.side_effect_class,
            "predecessors": sorted(stage.required_predecessor_stage_ids),
            "successors": sorted(stage.allowed_next_stage_ids),
            "required_artifacts": sorted(stage.required_artifact_types),
            "optional_artifacts": sorted(stage.optional_artifact_types),
            "produced_artifacts": sorted(stage.produced_artifact_types),
            "terminal": stage.terminal,
        }
        for stage in sorted(stage_definitions, key=lambda item: item.stage_id)
    ]
    return _digest(graph_payload)


def build_workflow_stage_registry(
    *,
    workflow_definition_id: str = "olympus_internal_workflow_v1",
) -> tuple[BobaWorkflowDefinitionSnapshotV1, list[BobaWorkflowStageDefinitionV1]]:
    stage_definitions: list[BobaWorkflowStageDefinitionV1] = []
    optional_stage_ids: list[str] = []
    for spec in _BUILTIN_STAGE_SPECS:
        stage_id = str(spec["stage_id"])
        optional = bool(spec.get("optional"))
        if optional:
            optional_stage_ids.append(stage_id)
        stage_definitions.append(
            BobaWorkflowStageDefinitionV1(
                stage_definition_id=f"{workflow_definition_id}:{stage_id}:v1",
                workflow_definition_id=workflow_definition_id,
                stage_id=stage_id,
                display_name=str(spec["display_name"]),
                stage_scope=spec["scope"],
                operation_module_id=str(spec["module"]),
                operation_id=str(spec["operation"]),
                operation_class=spec["class"],
                side_effect_class=spec["side_effect"],
                required_predecessor_stage_ids=list(spec.get("predecessors", ())),
                allowed_next_stage_ids=list(spec.get("next", ())),
                required_artifact_types=list(spec.get("required", ())),
                optional_artifact_types=list(spec.get("optional_artifacts", ())),
                produced_artifact_types=list(spec.get("produces", ())),
                rights_gate_required=bool(spec.get("rights")),
                target_approval_required=bool(spec.get("approval")),
                safety_gate_required=bool(spec.get("safety")),
                checkpoint_required=bool(spec.get("checkpoint")),
                technical_validation_required=bool(spec.get("validation")),
                output_quality_review_required=bool(spec.get("quality")),
                human_review_required=bool(spec.get("human")),
                idempotency_required=True,
                maximum_attempts=int(spec.get("maximum_attempts", 1)),
                timeout_seconds=int(spec.get("timeout", 300)),
                terminal=bool(spec.get("terminal")),
                recovery_route="autopilot_controller",
                limitations=[
                    "The stage may use only its fixed Integration Layer operation.",
                    (
                        "Completion requires persisted evidence; target exit status "
                        "alone is insufficient."
                    ),
                ],
            )
        )
    required_stage_ids = [
        stage.stage_id
        for stage in stage_definitions
        if stage.stage_id not in optional_stage_ids
    ]
    graph_digest = validate_workflow_graph(
        stage_definitions,
        start_stage_id="workflow_created",
        required_stage_ids=required_stage_ids,
    )
    snapshot = BobaWorkflowDefinitionSnapshotV1(
        workflow_definition_id=workflow_definition_id,
        workflow_name="Olympus Internal Production Workflow",
        workflow_version="1",
        created_at="2026-07-30T00:00:00+00:00",
        stage_definition_ids=[
            stage.stage_definition_id for stage in stage_definitions
        ],
        start_stage_id="workflow_created",
        terminal_stage_ids=[
            stage.stage_id for stage in stage_definitions if stage.terminal
        ],
        required_stage_ids=required_stage_ids,
        optional_stage_ids=optional_stage_ids,
        workflow_graph_digest=graph_digest,
        immutable=True,
        limitations=[
            "The built-in graph cannot be replaced by request payloads.",
            "Rendering requires a fixed target adapter and independently validated MP4 evidence.",
        ],
    )
    return snapshot, stage_definitions


def capture_workflow_project_snapshot(
    *,
    project_id: str,
    source_id: str,
    project_state: Mapping[str, Any] | None = None,
) -> str:
    safe_state = sanitize_workflow_export(dict(project_state or {}))
    return _digest(
        {
            "project_id": project_id,
            "source_id": source_id,
            "project_state": safe_state,
        }
    )


class BobaWorkflowControllerV1:
    """Own BOBA's exact-stage workflow ledger without replacing Olympus runners."""

    def __init__(
        self,
        store: BobaMemoryStore,
        *,
        integration_layer_factory: (
            Any
        ) = None,
        lease_owner: str = "boba_workflow_controller_v1",
    ) -> None:
        self.store = store
        self.integration_layer_factory = integration_layer_factory
        self.lease_owner = _bounded_text(lease_owner, maximum=180)

    def build_workflow_definition(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
    ) -> BobaWorkflowDefinitionSnapshotV1:
        snapshot, stages = build_workflow_stage_registry()
        controller = self.store.load_boba_workflow_controller(project_id)
        if controller is None:
            if not source_id:
                raise ValidationError(
                    "A source ID is required for the first Workflow Controller record."
                )
            controller = BobaWorkflowControllerSetV1(
                project_id=project_id,
                source_id=source_id,
                limitations=[
                    (
                        "V1 coordinates exact internal stages but does not replace "
                        "the durable Olympus worker pool."
                    ),
                    "Upload and publication are unavailable.",
                ],
            )
        existing = next(
            (
                item
                for item in controller.workflow_definition_snapshots
                if item.workflow_definition_id == snapshot.workflow_definition_id
            ),
            None,
        )
        if existing is not None:
            if existing.workflow_graph_digest != snapshot.workflow_graph_digest:
                raise ValidationError(
                    "Stored BOBA workflow definition conflicts with the immutable built-in graph."
                )
            return existing
        controller.workflow_definition_snapshots.append(snapshot)
        controller.stage_definitions.extend(stages)
        controller.signal_usage.built_in_workflow_definition_used = True
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        self.store.save_boba_workflow_definition(
            project_id,
            snapshot,
            stages,
        )
        return snapshot

    def create_workflow_run(
        self,
        project_id: str,
        *,
        source_id: str,
        project_snapshot: Mapping[str, Any] | None = None,
        source_storage_reference: str,
        source_artifact_digest: str,
        clip_ids: Sequence[str] = (),
        output_ids_by_clip: Mapping[str, str] | None = None,
        rights_status: str = "unknown",
    ) -> BobaWorkflowControllerSetV1:
        source_reference = _validate_storage_reference(source_storage_reference)
        if not _DIGEST.fullmatch(source_artifact_digest):
            raise ValidationError("Source artifact digest must be a SHA-256 digest.")
        snapshot = self.build_workflow_definition(
            project_id,
            source_id=source_id,
        )
        controller = self._controller(project_id)
        active = [
            run
            for run in controller.workflow_runs
            if run.run_status not in _TERMINAL_RUN_STATUSES
        ]
        if active:
            raise ValidationError(
                "A mutating BOBA workflow run is already active for this project.",
                details={"workflow_run_id": active[-1].workflow_run_id},
            )
        project_snapshot_digest = capture_workflow_project_snapshot(
            project_id=project_id,
            source_id=source_id,
            project_state=project_snapshot,
        )
        workflow_run_id = _runtime_id("workflow_run")
        correlation_id = _runtime_id("workflow_correlation")
        run = BobaWorkflowRunV1(
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            source_id=source_id,
            correlation_id=correlation_id,
            workflow_definition_id=snapshot.workflow_definition_id,
            started_at=now_iso(),
            run_status="active",
            current_project_state=(
                "ready"
                if rights_status
                in {
                    "owned",
                    "licensed",
                    "permission_granted",
                    "ready_for_internal_processing",
                }
                else "rights_review_required"
            ),
            project_snapshot_digest=project_snapshot_digest,
            revision=1,
            limitations=[
                "The controller does not start rendering during run creation.",
                "The controller does not authorize upload or publication.",
            ],
        )
        controller.workflow_runs.append(run)
        instances = self._create_stage_instances(
            controller,
            run,
            clip_ids=_unique(clip_ids, limit=256, maximum=160),
            output_ids_by_clip=dict(output_ids_by_clip or {}),
        )
        controller.stage_instances.extend(instances)
        created_stage = self._stage_for_identity(
            controller,
            run,
            stage_id="workflow_created",
        )
        source_stage = self._stage_for_identity(
            controller,
            run,
            stage_id="source_registration",
        )
        source_binding = BobaWorkflowArtifactBindingV1(
            artifact_binding_id=_stable_id(
                "workflow_artifact",
                workflow_run_id,
                "source_media",
                source_artifact_digest,
            ),
            workflow_run_id=workflow_run_id,
            stage_instance_id=created_stage.stage_instance_id,
            project_id=project_id,
            artifact_type="source_media",
            producer_module_id="workflow_controller",
            producer_record_id=source_id,
            schema_id="olympus.source.asset",
            schema_version="1",
            artifact_digest=source_artifact_digest,
            sanitized_storage_reference=source_reference,
            immutable=True,
            source_media=True,
            source_media_read_only=True,
            required=True,
            available=True,
            rights_relevant=True,
            safety_relevant=True,
        )
        controller.artifact_bindings.append(source_binding)
        created_stage.output_artifact_binding_ids.append(
            source_binding.artifact_binding_id
        )
        source_stage.input_artifact_binding_ids.append(
            source_binding.artifact_binding_id
        )
        source_stage.status = "ready"
        run.current_stage_instance_ids = [source_stage.stage_instance_id]
        run.completed_stage_instance_ids = [created_stage.stage_instance_id]
        advisory_lease = BobaWorkflowExecutionLeaseV1(
            execution_lease_id=_runtime_id("workflow_lease"),
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            lease_mode="advisory_read",
            owner_id=self.lease_owner,
            acquired_at=now_iso(),
            refreshed_at=now_iso(),
            expires_at=now_iso(),
            lease_status="released",
            revision_at_acquisition=run.revision,
            project_snapshot_digest=project_snapshot_digest,
            stale=False,
        )
        controller.execution_leases.append(advisory_lease)
        run.execution_lease_id = advisory_lease.execution_lease_id
        self._append_event(
            controller,
            run,
            event_type="workflow_created",
            technical_message=(
                f"Workflow run {workflow_run_id} was created from immutable "
                f"definition {snapshot.workflow_definition_id}."
            ),
            easy_message=(
                "BOBA created the internal workflow record. No rendering, upload, "
                "or publication started."
            ),
            confirmed_fact="A persisted workflow run and initial stage records exist.",
            evidence_reference_ids=[
                snapshot.workflow_definition_id,
                source_binding.artifact_binding_id,
            ],
        )
        self._append_event(
            controller,
            run,
            event_type="stage_ready",
            stage=source_stage,
            technical_message="Source registration is ready for exact inspection.",
            easy_message="BOBA can inspect the registered source as the next stage.",
            confirmed_fact="The source asset is bound read-only.",
        )
        controller.signal_usage.project_workflow_run_used = True
        controller.signal_usage.execution_lease_used = True
        controller.signal_usage.artifact_binding_validation_used = True
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return controller

    def inspect_workflow_run(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> dict[str, Any]:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        return self._run_snapshot(controller, run)

    def plan_next_stage(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> dict[str, Any]:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        if run.run_status in _TERMINAL_RUN_STATUSES:
            return {
                "schema_version": "boba_workflow_next_stage_plan_v1",
                "project_id": project_id,
                "workflow_run_id": workflow_run_id,
                "available": False,
                "reason": "The workflow run is terminal.",
                "stage_instance": None,
                "stage_definition": None,
            }
        if run.run_status in {"paused", "blocked", "recovery"}:
            return {
                "schema_version": "boba_workflow_next_stage_plan_v1",
                "project_id": project_id,
                "workflow_run_id": workflow_run_id,
                "available": False,
                "reason": "The workflow is paused or blocked; no transition was scheduled.",
                "stage_instance": None,
                "stage_definition": None,
            }
        candidates: list[tuple[int, BobaWorkflowStageInstanceV1]] = []
        definition_order = {
            stage.stage_id: index
            for index, stage in enumerate(self._definitions(controller, run))
        }
        for stage in self._stages(controller, run):
            if stage.status in _TERMINAL_STAGE_STATES | {"running"}:
                continue
            predecessor_states = [
                self._stage(controller, predecessor_id).status
                for predecessor_id in stage.predecessor_stage_instance_ids
            ]
            if all(
                state in {"completed", "completed_with_limitations"}
                for state in predecessor_states
            ):
                candidates.append((definition_order.get(stage.stage_id, 999), stage))
        if not candidates:
            return {
                "schema_version": "boba_workflow_next_stage_plan_v1",
                "project_id": project_id,
                "workflow_run_id": workflow_run_id,
                "available": False,
                "reason": "No dependency-ready stage is currently available.",
                "stage_instance": None,
                "stage_definition": None,
            }
        candidates.sort(
            key=lambda item: (
                item[0],
                item[1].clip_id or "",
                item[1].output_id or "",
            )
        )
        stage = candidates[0][1]
        definition = self._definition(controller, stage.stage_definition_id)
        return {
            "schema_version": "boba_workflow_next_stage_plan_v1",
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "available": True,
            "reason": "Required predecessor stages are complete.",
            "stage_instance": stage.model_dump(mode="json"),
            "stage_definition": definition.model_dump(mode="json"),
            "transition_type": (
                "advance_read_only"
                if definition.operation_class in _SAFE_AUTOMATIC_CLASSES
                else "advance_exact_internal_stage"
            ),
            "execution_started": False,
        }

    def add_artifact_binding(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        stage_instance_id: str,
        artifact_type: str,
        producer_module_id: str,
        producer_record_id: str,
        schema_id: str,
        schema_version: str,
        artifact_digest: str,
        sanitized_storage_reference: str,
        clip_id: str | None = None,
        output_id: str | None = None,
        required: bool = True,
        available: bool = True,
        stale: bool = False,
        malformed: bool = False,
        source_media: bool = False,
        accepted_output: bool = False,
        rights_relevant: bool = False,
        safety_relevant: bool = False,
        quality_relevant: bool = False,
    ) -> BobaWorkflowArtifactBindingV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        stage = self._stage(controller, stage_instance_id)
        if stage.workflow_run_id != run.workflow_run_id:
            raise ValidationError("Artifact stage belongs to another workflow run.")
        if clip_id and stage.clip_id and clip_id != stage.clip_id:
            raise ValidationError("Artifact clip does not match its stage instance.")
        if output_id and stage.output_id and output_id != stage.output_id:
            raise ValidationError("Artifact output does not match its stage instance.")
        reference = _validate_storage_reference(sanitized_storage_reference)
        if accepted_output:
            conflicting = [
                item
                for item in controller.artifact_bindings
                if item.accepted_output
                and item.sanitized_storage_reference == reference
                and item.artifact_digest != artifact_digest
            ]
            if conflicting:
                raise ValidationError(
                    "An accepted output cannot be selected as an overwrite target."
                )
        binding = BobaWorkflowArtifactBindingV1(
            artifact_binding_id=_stable_id(
                "workflow_artifact",
                workflow_run_id,
                stage_instance_id,
                artifact_type,
                artifact_digest,
            ),
            workflow_run_id=workflow_run_id,
            stage_instance_id=stage_instance_id,
            project_id=project_id,
            clip_id=clip_id or stage.clip_id,
            output_id=output_id or stage.output_id,
            artifact_type=artifact_type,
            producer_module_id=producer_module_id,
            producer_record_id=producer_record_id,
            schema_id=schema_id,
            schema_version=schema_version,
            artifact_digest=artifact_digest,
            sanitized_storage_reference=reference,
            immutable=True,
            accepted_output=accepted_output,
            source_media=source_media,
            source_media_read_only=True,
            required=required,
            available=available,
            stale=stale,
            malformed=malformed,
            rights_relevant=rights_relevant,
            safety_relevant=safety_relevant,
            quality_relevant=quality_relevant,
        )
        existing = next(
            (
                item
                for item in controller.artifact_bindings
                if item.artifact_binding_id == binding.artifact_binding_id
            ),
            None,
        )
        if existing is not None:
            if existing.model_dump(mode="json") != binding.model_dump(mode="json"):
                raise ValidationError("Immutable workflow artifact binding changed.")
            return existing
        controller.artifact_bindings.append(binding)
        stage.output_artifact_binding_ids = _unique(
            [*stage.output_artifact_binding_ids, binding.artifact_binding_id],
            limit=128,
            maximum=180,
        )
        controller.signal_usage.artifact_binding_validation_used = True
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return binding

    def validate_workflow_dependencies(
        self,
        project_id: str,
        workflow_run_id: str,
        stage_instance_id: str,
        *,
        rights_ready: bool | None = None,
        approval_ready: bool | None = None,
        safety_ready: bool | None = None,
        checkpoint_ready: bool | None = None,
        validation_ready: bool | None = None,
        quality_ready: bool | None = None,
        human_review_ready: bool | None = None,
        persist: bool = True,
    ) -> BobaWorkflowDependencyCheckV1:
        controller = self._controller(project_id)
        self._run(controller, workflow_run_id)
        stage = self._stage(controller, stage_instance_id)
        definition = self._definition(controller, stage.stage_definition_id)
        predecessors = [
            self._stage(controller, item)
            for item in stage.predecessor_stage_instance_ids
        ]
        completed_predecessors = [
            item.stage_id
            for item in predecessors
            if item.status in {"completed", "completed_with_limitations"}
        ]
        failed_predecessors = [
            item.stage_id
            for item in predecessors
            if item.status
            in {
                "failed",
                "timed_out",
                "cancelled",
                "recovery_required",
                "blocked",
                "unknown",
            }
        ]
        present_stage_ids = {item.stage_id for item in predecessors}
        missing_predecessors = [
            item
            for item in definition.required_predecessor_stage_ids
            if item not in present_stage_ids or item not in completed_predecessors
        ]
        candidate_artifacts = [
            item
            for item in controller.artifact_bindings
            if self._artifact_matches_stage(item, stage)
        ]
        required_bindings: list[BobaWorkflowArtifactBindingV1] = []
        missing_artifact_types: list[str] = []
        for artifact_type in definition.required_artifact_types:
            matches = [
                item for item in candidate_artifacts if item.artifact_type == artifact_type
            ]
            if matches:
                required_bindings.extend(matches)
            else:
                missing_artifact_types.append(artifact_type)
        stale = [item for item in required_bindings if item.stale]
        malformed = [item for item in required_bindings if item.malformed]
        unavailable = [item for item in required_bindings if not item.available]
        active_lease = self.store.load_boba_workflow_execution_lease(project_id)
        active_conflict = bool(
            active_lease
            and not active_lease.stale
            and active_lease.workflow_run_id != workflow_run_id
        )
        rights_value = (
            not definition.rights_gate_required
            if rights_ready is None
            else rights_ready
        )
        approval_value = (
            not definition.target_approval_required
            if approval_ready is None
            else approval_ready
        )
        safety_value = (
            not definition.safety_gate_required
            if safety_ready is None
            else safety_ready
        )
        checkpoint_value = (
            not definition.checkpoint_required
            if checkpoint_ready is None
            else checkpoint_ready
        )
        validation_value = (
            not definition.technical_validation_required
            if validation_ready is None
            else validation_ready
        )
        quality_value = (
            not definition.output_quality_review_required
            if quality_ready is None
            else quality_ready
        )
        human_value = (
            not definition.human_review_required
            if human_review_ready is None
            else human_review_ready
        )
        failure_reasons: list[str] = []
        if missing_predecessors:
            failure_reasons.append(
                "Required predecessor stages are incomplete: "
                + ", ".join(sorted(set(missing_predecessors)))
            )
        if failed_predecessors:
            failure_reasons.append(
                "A required predecessor failed: "
                + ", ".join(sorted(set(failed_predecessors)))
            )
        if missing_artifact_types:
            failure_reasons.append(
                "Required artifact types are missing: "
                + ", ".join(sorted(missing_artifact_types))
            )
        if stale:
            failure_reasons.append("Required artifacts are stale.")
        if malformed:
            failure_reasons.append("Required artifacts are malformed.")
        if unavailable:
            failure_reasons.append("Required artifacts are unavailable.")
        if not rights_value:
            failure_reasons.append("Rights readiness is not established.")
        if not approval_value:
            failure_reasons.append("Exact target approval is not ready.")
        if not safety_value:
            failure_reasons.append("Exact Safety Gate allowance is not ready.")
        if not checkpoint_value:
            failure_reasons.append("Checkpoint or state-preservation evidence is not ready.")
        if not validation_value:
            failure_reasons.append("Required technical validation is not ready.")
        if not quality_value:
            failure_reasons.append("Required output-quality acceptance is not ready.")
        if not human_value:
            failure_reasons.append("Required human review is not complete.")
        if active_conflict:
            failure_reasons.append("A conflicting workflow execution lease is active.")
        if active_conflict:
            status: BobaWorkflowDependencyStatusV1 = "conflicting"
        elif malformed:
            status = "malformed"
        elif stale:
            status = "stale"
        elif missing_artifact_types or unavailable:
            status = "missing"
        elif missing_predecessors or failed_predecessors:
            status = "incomplete"
        elif failure_reasons:
            status = "blocked"
        else:
            status = "ready"
        check = BobaWorkflowDependencyCheckV1(
            dependency_check_id=_runtime_id("workflow_dependency"),
            workflow_run_id=workflow_run_id,
            stage_instance_id=stage_instance_id,
            required_predecessor_stage_ids=list(
                definition.required_predecessor_stage_ids
            ),
            completed_predecessor_stage_ids=_unique(completed_predecessors),
            missing_predecessor_stage_ids=_unique(missing_predecessors),
            failed_predecessor_stage_ids=_unique(failed_predecessors),
            required_artifact_binding_ids=[
                item.artifact_binding_id for item in required_bindings
            ],
            available_artifact_binding_ids=[
                item.artifact_binding_id
                for item in required_bindings
                if item.available and not item.stale and not item.malformed
            ],
            stale_artifact_binding_ids=[
                item.artifact_binding_id for item in stale
            ],
            malformed_artifact_binding_ids=[
                item.artifact_binding_id for item in malformed
            ],
            rights_ready=rights_value,
            approval_ready=approval_value,
            safety_ready=safety_value,
            checkpoint_ready=checkpoint_value,
            validation_ready=validation_value,
            quality_ready=quality_value,
            human_review_ready=human_value,
            active_conflict_present=active_conflict,
            dependency_status=status,
            blocks_transition=status != "ready",
            failure_reasons=_unique(failure_reasons, maximum=900),
        )
        if persist:
            controller.dependency_checks.append(check)
            stage.dependency_check_id = check.dependency_check_id
            stage.input_artifact_binding_ids = _unique(
                [
                    *stage.input_artifact_binding_ids,
                    *check.available_artifact_binding_ids,
                ],
                limit=128,
                maximum=180,
            )
            controller.signal_usage.stage_dependency_validation_used = True
            controller.signal_usage.artifact_binding_validation_used = True
            self.store.save_boba_workflow_controller(controller)
        return check

    def create_transition_request(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        source_stage_instance_id: str,
        target_stage_id: str,
        expected_revision: int,
        transition_type: BobaWorkflowTransitionTypeV1,
        reason: str,
        clip_id: str | None = None,
        output_id: str | None = None,
        approval_record_id: str | None = None,
        safety_decision_id: str | None = None,
        integration_request_id: str | None = None,
        checkpoint_reference: str | None = None,
        checkpoint_digest: str | None = None,
        quality_decision_id: str | None = None,
        human_decision_id: str | None = None,
        expires_in_seconds: int = 300,
        idempotency_key: str | None = None,
    ) -> BobaWorkflowTransitionRequestV1:
        if transition_type == "unknown":
            raise ValidationError("Unknown workflow transition types cannot be requested.")
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        if run.run_status in _TERMINAL_RUN_STATUSES:
            raise ValidationError("Terminal workflow runs cannot be reopened.")
        if run.run_status in {"paused", "blocked", "recovery"} and transition_type not in {
            "return_from_recovery",
            "cancel",
        }:
            raise ValidationError(
                "Paused or blocked workflows require a separate eligibility review."
            )
        source = self._stage(controller, source_stage_instance_id)
        if source.workflow_run_id != workflow_run_id:
            raise ValidationError("Source stage belongs to another workflow run.")
        target = self._stage_for_identity(
            controller,
            run,
            stage_id=target_stage_id,
            clip_id=clip_id,
            output_id=output_id,
        )
        target_definition = self._definition(
            controller,
            target.stage_definition_id,
        )
        source_definition = self._definition(
            controller,
            source.stage_definition_id,
        )
        if (
            target_stage_id not in source_definition.allowed_next_stage_ids
            and transition_type not in {"return_from_recovery", "retry_stage"}
        ):
            raise ValidationError(
                "Requested stages do not form an allowed workflow graph edge.",
                details={
                    "source_stage": source.stage_id,
                    "target_stage": target_stage_id,
                },
            )
        if target.status in {"completed", "completed_with_limitations"}:
            raise ValidationError("A completed stage cannot be reopened.")
        if target.attempt_number > target_definition.maximum_attempts:
            raise ValidationError("The workflow stage retry limit is exhausted.")
        input_artifacts = [
            item
            for item in controller.artifact_bindings
            if self._artifact_matches_stage(item, target)
            and item.artifact_type in target_definition.required_artifact_types
        ]
        input_artifact_digest = _digest(
            sorted(
                (
                    item.artifact_binding_id,
                    item.artifact_digest,
                    item.available,
                    item.stale,
                    item.malformed,
                )
                for item in input_artifacts
            )
        )
        next_revision = run.revision + 1
        computed_key = calculate_workflow_idempotency_key(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            stage_instance_id=target.stage_instance_id,
            transition_type=transition_type,
            operation_id=target_definition.operation_id,
            project_snapshot_digest=run.project_snapshot_digest,
            workflow_revision=next_revision,
            input_artifact_digest=input_artifact_digest,
            approval_digest=approval_record_id or "",
            safety_decision_digest=safety_decision_id or "",
        )
        effective_key = idempotency_key or computed_key
        request_data: dict[str, Any] = {
            "transition_request_id": _runtime_id("workflow_transition"),
            "workflow_run_id": workflow_run_id,
            "project_id": project_id,
            "clip_id": target.clip_id,
            "output_id": target.output_id,
            "source_stage_instance_id": source_stage_instance_id,
            "target_stage_definition_id": target.stage_definition_id,
            "transition_type": transition_type,
            "requested_operation_id": target_definition.operation_id,
            "requested_at": now_iso(),
            "requested_by_module": "workflow_controller",
            "request_reason": _bounded_text(reason, maximum=900),
            "current_revision": next_revision,
            "project_snapshot_digest": run.project_snapshot_digest,
            "input_artifact_digest": input_artifact_digest,
            "approval_record_id": approval_record_id,
            "safety_decision_id": safety_decision_id,
            "integration_request_id": integration_request_id,
            "checkpoint_reference": checkpoint_reference,
            "checkpoint_digest": checkpoint_digest,
            "quality_decision_id": quality_decision_id,
            "human_decision_id": human_decision_id,
            "idempotency_key": effective_key,
            "expires_at": (
                datetime.now(UTC)
                + timedelta(seconds=max(1, min(expires_in_seconds, 3_600)))
            ).isoformat(),
        }
        request_data["request_digest"] = calculate_workflow_request_digest(
            request_data
        )
        request = BobaWorkflowTransitionRequestV1.model_validate(request_data)
        existing = next(
            (
                item
                for item in controller.transition_requests
                if item.idempotency_key == effective_key
            ),
            None,
        )
        if existing is not None:
            if existing.request_digest != request.request_digest:
                self._record_incident(
                    controller,
                    run,
                    incident_type="idempotency_conflict",
                    title="Workflow transition idempotency conflict",
                    summary=(
                        "A repeated idempotency key was supplied with changed transition "
                        "content."
                    ),
                    stage=target,
                    transition_request_id=existing.transition_request_id,
                )
                self._refresh_summary(controller)
                self.store.save_boba_workflow_controller(controller)
                raise ValidationError(
                    "Workflow transition idempotency key conflicts with an existing request."
                )
            return existing
        run.revision = next_revision
        run.updated_at = now_iso()
        run.active_transition_request_id = request.transition_request_id
        run.active_transition_decision_id = None
        run.current_project_state = "inspecting"
        target.transition_request_id = request.transition_request_id
        controller.transition_requests.append(request)
        controller.signal_usage.idempotency_used = True
        controller.signal_usage.checkpoint_reference_used = bool(
            checkpoint_reference or checkpoint_digest
        )
        self._append_event(
            controller,
            run,
            event_type="transition_requested",
            stage=target,
            transition_request=request,
            operation_id=target_definition.operation_id,
            technical_message=(
                f"Exact transition {request.transition_request_id} requested from "
                f"{source.stage_id} to {target.stage_id} at revision {run.revision}."
            ),
            easy_message=(
                f"BOBA prepared one exact transition to {target_definition.display_name}. "
                "Nothing has run yet."
            ),
            confirmed_fact="A persisted transition request exists.",
        )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return request

    def evaluate_transition_request(
        self,
        project_id: str,
        workflow_run_id: str,
        transition_request_id: str,
        *,
        expected_revision: int,
        current_project_snapshot_digest: str,
        rights_clear: bool | None = None,
        approval_record: Mapping[str, Any] | BobaContract | None = None,
        safety_decision: BobaSafetyDecisionV1 | Mapping[str, Any] | None = None,
        checkpoint_valid: bool | None = None,
        technical_validation: Mapping[str, Any] | BobaContract | None = None,
        quality_decision: (
            BobaOutputAcceptanceDecisionV1 | Mapping[str, Any] | None
        ) = None,
        human_decision: BobaWorkflowHumanDecisionV1 | Mapping[str, Any] | None = None,
    ) -> BobaWorkflowTransitionDecisionV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        request = self._transition_request(controller, transition_request_id)
        if request.workflow_run_id != workflow_run_id or request.project_id != project_id:
            raise ValidationError("Transition request belongs to another workflow run.")
        existing = next(
            (
                item
                for item in controller.transition_decisions
                if item.transition_request_id == transition_request_id
                and item.decision_valid
            ),
            None,
        )
        if existing is not None:
            return existing
        source = self._stage(controller, request.source_stage_instance_id)
        target = self._stage_for_definition(
            controller,
            run,
            request.target_stage_definition_id,
            clip_id=request.clip_id,
            output_id=request.output_id,
        )
        source_definition = self._definition(
            controller,
            source.stage_definition_id,
        )
        target_definition = self._definition(
            controller,
            target.stage_definition_id,
        )
        source_valid = (
            source.workflow_run_id == workflow_run_id
            and source.project_id == project_id
            and source.status
            in {
                "completed",
                "completed_with_limitations",
                "failed",
                "recovery_required",
            }
        )
        target_valid = (
            target.workflow_run_id == workflow_run_id
            and target.project_id == project_id
            and target.status
            not in {
                "completed",
                "completed_with_limitations",
                "cancelled",
                "superseded",
            }
        )
        graph_valid = (
            target.stage_id in source_definition.allowed_next_stage_ids
            or request.transition_type in {"return_from_recovery", "retry_stage"}
        )
        project_snapshot_current = (
            bool(current_project_snapshot_digest)
            and current_project_snapshot_digest == run.project_snapshot_digest
            and current_project_snapshot_digest == request.project_snapshot_digest
        )
        workflow_revision_current = request.current_revision == run.revision
        request_expiry = _parse_time(request.expires_at)
        expired = (
            request_expiry is None
            or request_expiry <= datetime.now(UTC)
        )
        rights_value = self._rights_clear(project_id, rights_clear)
        approval_valid = self._approval_valid(
            approval_record,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            stage=target,
            operation_id=target_definition.operation_id,
        )
        if not target_definition.target_approval_required:
            approval_valid = True
        safety_valid = self._safety_valid(
            safety_decision,
            project_id=project_id,
            request=request,
        )
        if not target_definition.safety_gate_required:
            safety_valid = True
        checkpoint_value = (
            not target_definition.checkpoint_required
            if checkpoint_valid is None
            else checkpoint_valid
        )
        if (
            target_definition.checkpoint_required
            and checkpoint_valid is None
            and request.checkpoint_reference
            and request.checkpoint_digest
        ):
            checkpoint_value = True
        validation_value = self._technical_validation_passed(
            technical_validation,
            required=target_definition.technical_validation_required,
        )
        quality_value, quality_human_required = self._quality_ready(
            quality_decision,
            required=target_definition.output_quality_review_required,
        )
        human_value = self._human_decision_valid(
            human_decision,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            stage=target,
            request=request,
        )
        if not target_definition.human_review_required and not quality_human_required:
            human_value = True
        integration_ready = self._integration_operation_ready(
            project_id,
            target_definition.operation_id,
        )
        active_lease = self.store.load_boba_workflow_execution_lease(project_id)
        lease_available = active_lease is None or active_lease.stale
        idempotency_conflict = any(
            item.idempotency_key == request.idempotency_key
            and item.transition_request_id != request.transition_request_id
            and item.request_digest != request.request_digest
            for item in controller.transition_requests
        )
        dependency = self.validate_workflow_dependencies(
            project_id,
            workflow_run_id,
            target.stage_instance_id,
            rights_ready=rights_value,
            approval_ready=approval_valid,
            safety_ready=safety_valid,
            checkpoint_ready=checkpoint_value,
            validation_ready=validation_value,
            quality_ready=quality_value,
            human_review_ready=human_value,
            persist=False,
        )
        artifacts_valid = not (
            dependency.stale_artifact_binding_ids
            or dependency.malformed_artifact_binding_ids
            or any(
                reason.startswith("Required artifact types are missing")
                or reason.startswith("Required artifacts are unavailable")
                for reason in dependency.failure_reasons
            )
        )
        unmet: list[str] = []
        conditions: list[str] = []
        checks = {
            "source stage is valid": source_valid,
            "target stage is valid": target_valid,
            "workflow graph edge is valid": graph_valid,
            "artifact bindings are current": artifacts_valid,
            "project snapshot is current": project_snapshot_current,
            "workflow revision is current": workflow_revision_current,
            "rights permit this internal stage": (
                rights_value or not target_definition.rights_gate_required
            ),
            "target approval is exact and current": approval_valid,
            "Safety Gate decision is exact and current": safety_valid,
            "Integration Layer target is registered": integration_ready,
            "checkpoint evidence is ready": checkpoint_value,
            "technical validation is ready": validation_value,
            "output quality is ready": quality_value,
            "required human review is complete": human_value,
            "execution lease is available": lease_available,
            "idempotency has no conflict": not idempotency_conflict,
            "stage dependencies are ready": not dependency.blocks_transition,
            "transition request is unexpired": not expired,
        }
        for label, passed in checks.items():
            (conditions if passed else unmet).append(label)
        hard_reasons = _unique([*unmet, *dependency.failure_reasons], maximum=900)
        if expired:
            decision_value: BobaWorkflowTransitionDecisionValueV1 = "expired"
        elif not workflow_revision_current or not project_snapshot_current:
            decision_value = "blocked_stale_state"
        elif not source_valid or not target_valid or not graph_valid:
            decision_value = "invalid_transition"
        elif idempotency_conflict:
            decision_value = "blocked_idempotency"
        elif not lease_available:
            decision_value = "blocked_concurrency"
        elif target_definition.rights_gate_required and not rights_value:
            decision_value = "blocked_rights"
        elif target_definition.target_approval_required and not approval_valid:
            decision_value = "awaiting_approval"
        elif target_definition.safety_gate_required and not safety_valid:
            decision_value = "awaiting_safety_decision"
        elif not checkpoint_value:
            decision_value = "blocked_checkpoint"
        elif not validation_value:
            decision_value = "blocked_validation"
        elif not quality_value:
            decision_value = (
                "awaiting_human_review"
                if quality_human_required
                else "blocked_quality"
            )
        elif not human_value:
            decision_value = "awaiting_human_review"
        elif dependency.blocks_transition or not artifacts_valid:
            decision_value = "blocked_dependency"
        elif not integration_ready:
            decision_value = "more_evidence_required"
        elif target_definition.operation_class in _SAFE_AUTOMATIC_CLASSES:
            decision_value = "allowed_read_only_transition"
        else:
            decision_value = "allowed_exact_internal_transition"
        allowed = decision_value in {
            "allowed_read_only_transition",
            "allowed_exact_internal_transition",
        }
        next_state: BobaWorkflowProjectStateV1
        if allowed:
            next_state = "transition_ready"
        elif decision_value == "awaiting_approval":
            next_state = "awaiting_approval"
        elif decision_value == "awaiting_safety_decision":
            next_state = "awaiting_safety_decision"
        elif decision_value == "awaiting_human_review":
            next_state = "awaiting_human_review"
        elif decision_value in {
            "blocked_rights",
            "blocked_stale_state",
            "blocked_dependency",
            "blocked_checkpoint",
            "blocked_validation",
            "blocked_quality",
            "blocked_concurrency",
            "blocked_idempotency",
            "invalid_transition",
            "expired",
            "denied",
        }:
            next_state = "paused"
        else:
            next_state = "blocked"
        now = datetime.now(UTC)
        decision = BobaWorkflowTransitionDecisionV1(
            transition_decision_id=_runtime_id("workflow_decision"),
            transition_request_id=request.transition_request_id,
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            decision=decision_value,
            decision_summary=(
                "All exact conditions passed for this one internal stage transition."
                if allowed
                else "The exact transition remains blocked; no target operation ran."
            ),
            source_stage_valid=source_valid,
            target_stage_valid=target_valid,
            graph_transition_valid=graph_valid,
            dependency_check_id=dependency.dependency_check_id,
            artifact_bindings_valid=artifacts_valid,
            project_snapshot_current=project_snapshot_current,
            workflow_revision_current=workflow_revision_current,
            rights_clear=rights_value,
            target_approval_valid=approval_valid,
            safety_decision_valid=safety_valid,
            integration_ready=integration_ready,
            checkpoint_ready=checkpoint_value,
            validation_ready=validation_value,
            quality_ready=quality_value,
            human_review_complete=human_value,
            lease_available=lease_available,
            idempotency_clear=not idempotency_conflict,
            conditions=_unique(conditions, maximum=500),
            unmet_conditions=_unique(unmet, maximum=500),
            blocking_reasons=hard_reasons,
            next_project_state=next_state,
            decision_created_at=now.isoformat(),
            decision_expires_at=(now + timedelta(minutes=5)).isoformat(),
            decision_valid=allowed,
            target_revalidation_required=True,
            confidence=1.0 if allowed else 0.9,
            limitations=[
                "This decision permits at most the exact displayed stage transition.",
                "It does not authorize unrestricted workflow resume, upload, or publication.",
            ],
        )
        controller.dependency_checks.append(dependency)
        controller.transition_decisions.append(decision)
        target.dependency_check_id = dependency.dependency_check_id
        target.transition_decision_id = decision.transition_decision_id
        target.approval_record_id = request.approval_record_id
        target.safety_decision_id = request.safety_decision_id
        if allowed:
            target.status = "ready"
            run.active_transition_decision_id = decision.transition_decision_id
        else:
            target.status = self._stage_state_for_decision(decision_value)
        run.current_project_state = next_state
        run.updated_at = now_iso()
        run.revision += 1
        controller.signal_usage.stage_dependency_validation_used = True
        controller.signal_usage.artifact_binding_validation_used = True
        controller.signal_usage.rights_gate_used = target_definition.rights_gate_required
        controller.signal_usage.target_module_approval_used = (
            target_definition.target_approval_required
        )
        controller.signal_usage.safety_gate_used = target_definition.safety_gate_required
        controller.signal_usage.output_quality_reviewer_used = (
            target_definition.output_quality_review_required
        )
        controller.signal_usage.human_decision_used = (
            target_definition.human_review_required or quality_human_required
        )
        self._append_event(
            controller,
            run,
            event_type="transition_allowed" if allowed else "transition_blocked",
            severity="info" if allowed else "warning",
            stage=target,
            transition_request=request,
            operation_id=target_definition.operation_id,
            technical_message=(
                f"Transition {request.transition_request_id} evaluated as "
                f"{decision_value}."
            ),
            easy_message=(
                f"BOBA checked the exact transition to {target_definition.display_name}. "
                + (
                    "It is ready for separate one-stage coordination."
                    if allowed
                    else "Nothing was continued."
                )
            ),
            confirmed_fact=f"Persisted decision: {decision_value}.",
            assessment="; ".join(hard_reasons[:4]),
            requires_attention=not allowed,
        )
        if next_state == "paused":
            self._pause_in_place(
                controller,
                run,
                stage=target,
                reason=hard_reasons[0] if hard_reasons else decision_value,
                category=self._pause_category_for_decision(decision_value),
                automatic=True,
                increment_revision=False,
            )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return decision

    async def advance_safe_read_only_stage(
        self,
        project_id: str,
        workflow_run_id: str,
        transition_decision_id: str,
        *,
        expected_revision: int,
        integration_parameters: Mapping[str, Any] | None = None,
    ) -> BobaIntegrationResponseV1:
        """Advance one evaluated read-only or planning stage through typed routing."""

        return await self._execute_allowed_transition(
            project_id,
            workflow_run_id,
            transition_decision_id,
            expected_revision=expected_revision,
            expected_decision="allowed_read_only_transition",
            integration_parameters=integration_parameters,
        )

    async def coordinate_approved_internal_transition(
        self,
        project_id: str,
        workflow_run_id: str,
        transition_decision_id: str,
        *,
        expected_revision: int,
        integration_parameters: Mapping[str, Any] | None = None,
        approval_binding: BobaIntegrationApprovalBindingV1 | None = None,
        safety_binding: BobaIntegrationSafetyBindingV1 | None = None,
    ) -> BobaIntegrationResponseV1:
        """Coordinate exactly one separately allowed execution-capable stage."""

        return await self._execute_allowed_transition(
            project_id,
            workflow_run_id,
            transition_decision_id,
            expected_revision=expected_revision,
            expected_decision="allowed_exact_internal_transition",
            integration_parameters=integration_parameters,
            approval_binding=approval_binding,
            safety_binding=safety_binding,
        )

    async def _execute_allowed_transition(
        self,
        project_id: str,
        workflow_run_id: str,
        transition_decision_id: str,
        *,
        expected_revision: int,
        expected_decision: Literal[
            "allowed_read_only_transition",
            "allowed_exact_internal_transition",
        ],
        integration_parameters: Mapping[str, Any] | None,
        approval_binding: BobaIntegrationApprovalBindingV1 | None = None,
        safety_binding: BobaIntegrationSafetyBindingV1 | None = None,
    ) -> BobaIntegrationResponseV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        if run.run_status in _TERMINAL_RUN_STATUSES:
            raise ValidationError("Terminal workflow runs cannot execute another stage.")
        decision = self._transition_decision(controller, transition_decision_id)
        if (
            decision.workflow_run_id != workflow_run_id
            or decision.project_id != project_id
        ):
            raise ValidationError("Transition decision belongs to another workflow run.")
        if not decision.decision_valid or decision.decision != expected_decision:
            raise ValidationError(
                "The transition decision does not allow this coordination method."
            )
        decision_expiry = _parse_time(decision.decision_expires_at)
        if decision_expiry is None or decision_expiry <= datetime.now(UTC):
            raise ValidationError("The exact transition decision has expired.")
        request = self._transition_request(
            controller,
            decision.transition_request_id,
        )
        target = self._stage_for_definition(
            controller,
            run,
            request.target_stage_definition_id,
            clip_id=request.clip_id,
            output_id=request.output_id,
        )
        definition = self._definition(controller, target.stage_definition_id)
        if target.status != "ready":
            raise ValidationError("The target stage is not ready for coordination.")
        if target.idempotency_key:
            completed_response = self._completed_integration_response(
                project_id,
                target.integration_transaction_id,
            )
            if (
                target.idempotency_key == request.idempotency_key
                and completed_response is not None
            ):
                return completed_response
            raise ValidationError(
                "The stage already has a different or incomplete idempotent attempt."
            )
        lease_mode: BobaWorkflowLeaseModeV1 = (
            "read_only_transition"
            if expected_decision == "allowed_read_only_transition"
            else "exact_internal_transition"
        )
        lease = self.store.acquire_boba_workflow_execution_lease(
            project_id,
            workflow_run_id=workflow_run_id,
            transition_request_id=request.transition_request_id,
            stage_instance_id=target.stage_instance_id,
            owner_id=self.lease_owner,
            lease_mode=lease_mode,
            revision=run.revision,
            project_snapshot_digest=run.project_snapshot_digest,
        )
        controller.execution_leases.append(lease)
        target.status = "running"
        target.started_at = now_iso()
        target.attempt_number = max(1, target.attempt_number)
        target.idempotency_key = request.idempotency_key
        target.input_digest = request.input_artifact_digest
        run.execution_lease_id = lease.execution_lease_id
        run.current_stage_instance_ids = [target.stage_instance_id]
        run.current_project_state = "transition_running"
        run.updated_at = now_iso()
        run.revision += 1
        self._append_event(
            controller,
            run,
            event_type=(
                "stage_started"
                if expected_decision == "allowed_read_only_transition"
                else "exact_internal_transition_started"
            ),
            stage=target,
            transition_request=request,
            operation_id=definition.operation_id,
            technical_message=(
                f"Stage {target.stage_instance_id} was persisted as running before "
                "typed target routing."
            ),
            easy_message=(
                f"BOBA started one registered internal stage: {definition.display_name}."
            ),
            confirmed_fact="No later workflow stage was scheduled.",
        )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)

        try:
            layer = self._integration_layer(controller)
            artifact_references = self._integration_artifact_references(
                controller,
                target,
            )
            parameters = {
                "workflow_run_id": workflow_run_id,
                "workflow_stage_instance_id": target.stage_instance_id,
                "workflow_transition_request_id": request.transition_request_id,
                "workflow_transition_decision_id": decision.transition_decision_id,
                "workflow_revision": run.revision,
                "clip_id": target.clip_id,
                "output_id": target.output_id,
                "target_revalidation_required": True,
                **dict(integration_parameters or {}),
            }
            envelope = layer.create_request_envelope(
                requesting_module_id="workflow_controller",
                target_module_id=definition.operation_module_id,
                target_operation_id=definition.operation_id,
                request_parameters=parameters,
                run_id=workflow_run_id,
                source_id=controller.source_id,
                artifact_references=artifact_references,
                approval_binding=approval_binding,
                safety_binding=safety_binding,
                project_snapshot_digest=run.project_snapshot_digest,
                idempotency_key=request.idempotency_key,
                correlation_id=run.correlation_id,
            )
            if envelope.safety_binding is not None:
                initial_request = layer._request_from_envelope(envelope)
                envelope.safety_binding.request_digest = initial_request.request_digest
            integration_request = layer._request_from_envelope(envelope)
            if (
                request.integration_request_id
                and request.integration_request_id != integration_request.request_id
            ):
                raise ValidationError(
                    "The persisted Integration request identity changed."
                )
            transaction = await layer.validate_request_envelope(envelope)
            controller = self._controller(project_id)
            run = self._run(controller, workflow_run_id)
            target = self._stage(controller, target.stage_instance_id)
            target.integration_transaction_id = transaction.transaction_id
            run.active_integration_transaction_id = transaction.transaction_id
            controller.signal_usage.integration_layer_used = True
            self.store.save_boba_workflow_controller(controller)
            response = await layer.route_typed_request(transaction.transaction_id)
        except Exception as exc:
            controller = self._controller(project_id)
            run = self._run(controller, workflow_run_id)
            target = self._stage(controller, target.stage_instance_id)
            self._fail_stage(
                controller,
                run,
                target,
                reason=f"Integration Layer coordination failed: {_bounded_text(exc)}",
                incident_type="integration_failure",
                timed_out=False,
                uncertain=expected_decision == "allowed_exact_internal_transition",
            )
            self._release_execution_lease(controller, run, target)
            self._refresh_summary(controller)
            self.store.save_boba_workflow_controller(controller)
            raise

        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        target = self._stage(controller, target.stage_instance_id)
        transaction = layer.inspect_transaction(transaction.transaction_id)
        if response.status not in {"succeeded", "duplicate_reused"}:
            self._fail_stage(
                controller,
                run,
                target,
                reason=(
                    f"Registered target returned {response.status}: "
                    f"{response.bounded_result.get('summary', 'no bounded summary')}"
                ),
                incident_type=(
                    "stage_timeout"
                    if response.status == "timed_out"
                    else "stage_failure"
                ),
                timed_out=response.status == "timed_out",
                uncertain=transaction.target_invocation_started,
            )
            self._release_execution_lease(controller, run, target)
            self._refresh_summary(controller)
            self.store.save_boba_workflow_controller(controller)
            return response
        if (
            expected_decision == "allowed_exact_internal_transition"
            and not transaction.target_independent_revalidation_confirmed
        ):
            self._fail_stage(
                controller,
                run,
                target,
                reason="The execution target did not independently revalidate.",
                incident_type="integration_failure",
                uncertain=True,
            )
            self._release_execution_lease(controller, run, target)
            self._refresh_summary(controller)
            self.store.save_boba_workflow_controller(controller)
            return response.model_copy(
                update={
                    "status": "rejected",
                    "warnings": [
                        *response.warnings,
                        "Target independent revalidation was not confirmed.",
                    ],
                }
            )
        try:
            self._bind_stage_result_artifacts(
                controller,
                run,
                target,
                definition,
                response,
            )
        except ValidationError as exc:
            self._fail_stage(
                controller,
                run,
                target,
                reason=str(exc),
                incident_type="missing_artifact",
                uncertain=False,
            )
            self._release_execution_lease(controller, run, target)
            self._refresh_summary(controller)
            self.store.save_boba_workflow_controller(controller)
            return response.model_copy(
                update={
                    "status": "rejected",
                    "warnings": [*response.warnings, str(exc)],
                }
            )
        target.status = "completed"
        target.completed_at = now_iso()
        target.result_digest = response.result_digest
        run.completed_stage_instance_ids = _unique(
            [*run.completed_stage_instance_ids, target.stage_instance_id],
            limit=2_048,
            maximum=180,
        )
        run.current_stage_instance_ids = []
        run.active_transition_request_id = None
        run.active_transition_decision_id = None
        run.active_integration_transaction_id = None
        run.current_project_state = "stage_completed"
        run.run_status = "active"
        run.updated_at = now_iso()
        run.revision += 1
        self._ready_successor_stages(controller, run, target)
        self._append_event(
            controller,
            run,
            event_type=(
                "stage_completed"
                if expected_decision == "allowed_read_only_transition"
                else "exact_internal_transition_completed"
            ),
            stage=target,
            transition_request=request,
            operation_id=definition.operation_id,
            technical_message=(
                f"Integration transaction {transaction.transaction_id} completed "
                f"stage {target.stage_instance_id}."
            ),
            easy_message=(
                f"BOBA completed {definition.display_name}. "
                "No later execution stage started automatically."
            ),
            confirmed_fact=f"Persisted result digest: {response.result_digest}.",
            evidence_reference_ids=target.output_artifact_binding_ids,
        )
        if target.stage_id == "internal_output_completion":
            self._mark_internal_output_complete(controller, run, target)
        self._release_execution_lease(controller, run, target)
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return response

    def pause_workflow(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        expected_revision: int,
        reason: str,
        category: BobaWorkflowPauseCategoryV1 = "manual",
        stage_instance_id: str | None = None,
    ) -> BobaWorkflowPauseRecordV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        if run.run_status in _TERMINAL_RUN_STATUSES:
            raise ValidationError("Terminal workflow runs cannot be paused.")
        stage = (
            self._stage(controller, stage_instance_id)
            if stage_instance_id
            else self._current_stage(controller, run)
        )
        pause = self._pause_in_place(
            controller,
            run,
            stage=stage,
            reason=reason,
            category=category,
            automatic=False,
            increment_revision=True,
        )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return pause

    def continue_controller(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        expected_revision: int,
    ) -> BobaWorkflowRunV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        if run.run_status not in {"paused", "blocked"}:
            raise ValidationError("Only a paused controller can be continued.")
        active_hold = self._active_recovery_hold(controller, run)
        if active_hold is not None and not active_hold.released:
            raise ValidationError(
                "The controller cannot continue while a Recovery Hold is active."
            )
        if run.active_integration_transaction_id:
            raise ValidationError(
                "The controller cannot continue while a target transaction is active."
            )
        pause = next(
            (
                item
                for item in reversed(controller.pause_records)
                if item.workflow_run_id == workflow_run_id
                and item.released_at is None
            ),
            None,
        )
        if pause is not None:
            pause.released_at = now_iso()
            pause.released_by_decision_id = "controller_continue"
        run.run_status = "active"
        run.current_project_state = "stage_ready"
        run.stop_reason = ""
        run.updated_at = now_iso()
        run.revision += 1
        self._append_event(
            controller,
            run,
            event_type="stage_ready",
            stage=self._current_stage(controller, run),
            technical_message="The controller pause was released without executing a stage.",
            easy_message=(
                "BOBA reopened stage planning. It did not resume every workflow stage."
            ),
            confirmed_fact="No target operation ran.",
        )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return run

    def cancel_workflow_run(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        expected_revision: int,
        reason: str,
    ) -> BobaWorkflowRunV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        if run.run_status in _TERMINAL_RUN_STATUSES:
            return run
        running_stages = [
            item for item in self._stages(controller, run) if item.status == "running"
        ]
        for stage in self._stages(controller, run):
            if stage.status in {
                "pending",
                "dependency_blocked",
                "ready",
                "awaiting_approval",
                "awaiting_safety_decision",
            }:
                stage.status = "cancelled"
                stage.completed_at = now_iso()
        run.run_status = "cancelled"
        run.current_project_state = "cancelled"
        run.stop_reason = _bounded_text(reason, maximum=900)
        run.completed_at = now_iso()
        run.updated_at = now_iso()
        run.revision += 1
        if running_stages:
            run.warnings = _unique(
                [
                    *run.warnings,
                    (
                        "Cancellation did not kill an active target; "
                        "completion is uncertain."
                    ),
                ],
                limit=128,
                maximum=900,
            )
        else:
            self._release_execution_lease(
                controller,
                run,
                self._current_stage(controller, run),
            )
        self._append_event(
            controller,
            run,
            event_type="workflow_cancelled",
            severity="warning",
            stage=self._current_stage(controller, run),
            technical_message=(
                f"Workflow scheduling was cancelled: {_bounded_text(reason)}"
            ),
            easy_message=(
                "BOBA stopped scheduling later stages. Existing artifacts were "
                "preserved."
            ),
            confirmed_fact="Source media and accepted outputs were not deleted.",
            assessment=(
                "An active target may still finish independently."
                if running_stages
                else ""
            ),
            requires_attention=bool(running_stages),
        )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return run

    def create_recovery_hold(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        failed_stage_instance_id: str,
        expected_revision: int,
        reason: str,
        observer_record_id: str | None = None,
    ) -> BobaWorkflowRecoveryHoldV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        if run.run_status in _TERMINAL_RUN_STATUSES:
            raise ValidationError("Terminal workflow runs cannot enter recovery.")
        stage = self._stage(controller, failed_stage_instance_id)
        if stage.workflow_run_id != workflow_run_id:
            raise ValidationError("Failed stage belongs to another workflow run.")
        if stage.status not in {
            "failed",
            "timed_out",
            "recovery_required",
            "blocked",
        }:
            raise ValidationError(
                "Recovery Holds require an honestly failed or blocked stage."
            )
        existing = self._active_recovery_hold(controller, run)
        if existing is not None:
            if existing.failed_stage_instance_id != failed_stage_instance_id:
                raise ValidationError(
                    "A different unresolved Recovery Hold is already active."
                )
            return existing
        hold = BobaWorkflowRecoveryHoldV1(
            recovery_hold_id=_runtime_id("workflow_recovery_hold"),
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            failed_stage_instance_id=failed_stage_instance_id,
            recovery_reason=_bounded_text(reason, maximum=900),
            observer_record_id=observer_record_id,
            hold_status="awaiting_autopilot",
            recovery_artifact_ids=list(stage.output_artifact_binding_ids),
            original_project_snapshot_digest=run.project_snapshot_digest,
            current_project_snapshot_digest=run.project_snapshot_digest,
            limitations=[
                "Autopilot owns diagnosis and repair coordination.",
                "Receiving a recovery result cannot resume the normal workflow.",
            ],
        )
        controller.recovery_holds.append(hold)
        run.active_recovery_hold_id = hold.recovery_hold_id
        run.run_status = "recovery"
        run.current_project_state = "recovery_required"
        run.stop_reason = hold.recovery_reason
        run.updated_at = now_iso()
        run.revision += 1
        handoff = BobaWorkflowHandoffV1(
            handoff_id=_runtime_id("workflow_handoff"),
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            stage_instance_id=stage.stage_instance_id,
            transition_request_id=stage.transition_request_id,
            target_module_id="autopilot_controller",
            reason=hold.recovery_reason,
            current_project_state="recovery_required",
            required_inputs=[
                "exact_recovery_hold",
                "failed_stage_identity",
                "current_project_snapshot",
                "bounded_failure_evidence",
            ],
            artifact_binding_ids=list(stage.output_artifact_binding_ids),
            allowed_actions=[
                "diagnose_through_registered_modules",
                "plan_bounded_recovery",
                "return_typed_recovery_result",
            ],
            prohibited_actions=[
                "continue_normal_workflow",
                "release_recovery_hold",
                "upload",
                "publish",
            ],
            apply_automatically=False,
            human_approval_required=True,
            priority="high",
        )
        controller.handoffs.append(handoff)
        controller.signal_usage.autopilot_handoff_used = True
        self._append_event(
            controller,
            run,
            event_type="recovery_requested",
            severity="warning",
            stage=stage,
            technical_message=(
                f"Recovery Hold {hold.recovery_hold_id} preserved failed stage "
                f"{stage.stage_instance_id}."
            ),
            easy_message=(
                "BOBA paused the normal workflow and sent the exact failed stage "
                "to the recovery system."
            ),
            confirmed_fact="The Recovery Hold remains active.",
            requires_attention=True,
            evidence_reference_ids=[hold.recovery_hold_id, handoff.handoff_id],
        )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return hold

    def receive_autopilot_recovery_result(
        self,
        project_id: str,
        workflow_run_id: str,
        recovery_hold_id: str,
        recovery_result: BobaIntegrationResponseV1 | Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> BobaWorkflowRecoveryHoldV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        hold = self._recovery_hold(controller, recovery_hold_id)
        if hold.workflow_run_id != workflow_run_id or hold.project_id != project_id:
            raise ValidationError("Recovery result does not match the Recovery Hold.")
        if hold.released:
            raise ValidationError("A released Recovery Hold cannot accept new results.")
        if isinstance(recovery_result, BobaIntegrationResponseV1):
            if recovery_result.project_id != project_id:
                raise ValidationError("Recovery result project identity changed.")
            if recovery_result.run_id not in {
                workflow_run_id,
                hold.autopilot_run_id,
            }:
                raise ValidationError("Recovery result run identity changed.")
            if recovery_result.status not in {"succeeded", "duplicate_reused"}:
                raise ValidationError("Autopilot recovery result did not succeed.")
            payload = dict(recovery_result.bounded_result)
            integration_response_id = recovery_result.response_id
        else:
            payload = dict(recovery_result)
            integration_response_id = str(
                payload.get("integration_response_id") or ""
            )
        exact_values = {
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "recovery_hold_id": recovery_hold_id,
            "failed_stage_instance_id": hold.failed_stage_instance_id,
        }
        for field, expected in exact_values.items():
            value = str(payload.get(field) or "")
            if value != expected:
                raise ValidationError(
                    f"Recovery result {field} does not match the active hold."
                )
        autopilot_run_id = str(payload.get("autopilot_run_id") or "")
        if not autopilot_run_id:
            raise ValidationError("Recovery result lacks an exact Autopilot run.")
        if hold.autopilot_run_id and hold.autopilot_run_id != autopilot_run_id:
            raise ValidationError("Recovery result Autopilot run identity changed.")
        snapshot_digest = str(
            payload.get("current_project_snapshot_digest") or ""
        )
        if (
            snapshot_digest != run.project_snapshot_digest
            or snapshot_digest != hold.current_project_snapshot_digest
        ):
            raise ValidationError("Autopilot recovery result is stale.")
        technical_validation = payload.get("technical_validation")
        if not self._technical_validation_passed(
            technical_validation if isinstance(technical_validation, Mapping) else None,
            required=True,
        ):
            raise ValidationError(
                "Recovery result lacks passing required technical validation."
            )
        raw_quality = payload.get("quality_decision")
        quality_value: BobaOutputAcceptanceDecisionV1 | Mapping[str, Any] | None
        quality_value = raw_quality if isinstance(raw_quality, Mapping) else None
        quality_ready, quality_human_required = self._quality_ready(
            quality_value,
            required=True,
        )
        if not quality_ready:
            raise ValidationError(
                "Recovery result lacks an accepted Output Quality decision."
            )
        failed_stage = self._stage(controller, hold.failed_stage_instance_id)
        payload_clip_id = str(payload.get("clip_id") or "")
        payload_output_id = str(payload.get("output_id") or "")
        if payload_clip_id and payload_clip_id != (failed_stage.clip_id or ""):
            raise ValidationError("Recovery result belongs to another clip.")
        if payload_output_id and payload_output_id != (failed_stage.output_id or ""):
            raise ValidationError("Recovery result belongs to another output.")
        artifact_values = payload.get("recovery_artifacts")
        if not isinstance(artifact_values, list) or not artifact_values:
            raise ValidationError("Recovery result lacks exact recovery artifacts.")
        recovery_artifact_ids: list[str] = []
        for index, value in enumerate(artifact_values[:64]):
            if not isinstance(value, Mapping):
                raise ValidationError("Recovery result artifact metadata is malformed.")
            reference = _validate_storage_reference(
                str(value.get("sanitized_storage_reference") or "")
            )
            digest = str(value.get("artifact_digest") or "")
            if not _DIGEST.fullmatch(digest):
                raise ValidationError("Recovery result artifact digest is malformed.")
            artifact_project = str(value.get("project_id") or project_id)
            artifact_clip = str(value.get("clip_id") or "") or None
            artifact_output = str(value.get("output_id") or "") or None
            if artifact_project != project_id:
                raise ValidationError("Recovery artifact belongs to another project.")
            if artifact_clip and artifact_clip != failed_stage.clip_id:
                raise ValidationError("Recovery artifact belongs to another clip.")
            if artifact_output and artifact_output != failed_stage.output_id:
                raise ValidationError("Recovery artifact belongs to another output.")
            binding = BobaWorkflowArtifactBindingV1(
                artifact_binding_id=_stable_id(
                    "workflow_recovery_artifact",
                    recovery_hold_id,
                    index,
                    digest,
                ),
                workflow_run_id=workflow_run_id,
                stage_instance_id=failed_stage.stage_instance_id,
                project_id=project_id,
                clip_id=artifact_clip or failed_stage.clip_id,
                output_id=artifact_output or failed_stage.output_id,
                artifact_type=str(value.get("artifact_type") or "recovery_output"),
                producer_module_id=str(
                    value.get("producer_module_id") or "autopilot_controller"
                ),
                producer_record_id=str(
                    value.get("producer_record_id")
                    or integration_response_id
                    or autopilot_run_id
                ),
                schema_id=str(value.get("schema_id") or "boba.recovery.output"),
                schema_version=str(value.get("schema_version") or "1"),
                artifact_digest=digest,
                sanitized_storage_reference=reference,
                immutable=True,
                accepted_output=bool(value.get("accepted_output")),
                source_media=False,
                source_media_read_only=True,
                required=True,
                available=bool(value.get("available", True)),
                stale=bool(value.get("stale", False)),
                malformed=bool(value.get("malformed", False)),
                safety_relevant=True,
                quality_relevant=True,
            )
            if binding.stale or binding.malformed or not binding.available:
                raise ValidationError("Recovery artifacts are not current and usable.")
            controller.artifact_bindings.append(binding)
            recovery_artifact_ids.append(binding.artifact_binding_id)
        hold.autopilot_run_id = autopilot_run_id
        hold.output_quality_decision_id = self._quality_decision_id(quality_value)
        raw_safety = payload.get("safety_decision")
        if isinstance(raw_safety, Mapping):
            hold.safety_decision_id = str(
                raw_safety.get("safety_decision_id") or ""
            ) or None
        hold.recovery_artifact_ids = _unique(
            [*hold.recovery_artifact_ids, *recovery_artifact_ids],
            limit=128,
            maximum=180,
        )
        hold.hold_status = (
            "awaiting_human_review"
            if quality_human_required
            else "resolved_pending_resume_review"
        )
        hold.resolution_summary = _bounded_text(
            payload.get("resolution_summary")
            or "Autopilot returned a typed recovery result for separate review.",
            maximum=900,
        )
        hold.human_review_required = quality_human_required
        run.active_autopilot_run_id = None
        run.run_status = "paused"
        run.current_project_state = "resume_eligibility_review"
        run.updated_at = now_iso()
        run.revision += 1
        controller.signal_usage.autopilot_handoff_used = True
        controller.signal_usage.output_quality_reviewer_used = True
        controller.signal_usage.safety_gate_used = bool(hold.safety_decision_id)
        controller.signal_usage.artifact_binding_validation_used = True
        self._append_event(
            controller,
            run,
            event_type="recovery_completed",
            stage=failed_stage,
            technical_message=(
                f"Typed recovery result for hold {recovery_hold_id} was received "
                "and bounded."
            ),
            easy_message=(
                "The recovery system returned a replacement result. The normal "
                "workflow is still paused while BOBA checks it."
            ),
            confirmed_fact="No normal workflow stage resumed.",
            evidence_reference_ids=recovery_artifact_ids,
        )
        self._append_event(
            controller,
            run,
            event_type="resume_eligibility_started",
            stage=failed_stage,
            technical_message="Resume-eligibility review is now required.",
            easy_message=(
                "BOBA is reviewing whether one exact next transition can be prepared."
            ),
            confirmed_fact="Eligibility has not yet been granted.",
        )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return hold

    def evaluate_resume_eligibility(
        self,
        project_id: str,
        workflow_run_id: str,
        recovery_hold_id: str,
        *,
        expected_revision: int,
        current_project_snapshot_digest: str,
        rights_clear: bool,
        approval_record: Mapping[str, Any] | BobaContract | None,
        safety_decision: BobaSafetyDecisionV1 | Mapping[str, Any] | None,
        checkpoint_valid: bool,
        rollback_state_clear: bool,
        technical_validation: Mapping[str, Any] | BobaContract | None,
        quality_decision: BobaOutputAcceptanceDecisionV1 | Mapping[str, Any] | None,
        human_decision: BobaWorkflowHumanDecisionV1 | Mapping[str, Any] | None = None,
    ) -> BobaWorkflowResumeEligibilityReviewV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        hold = self._recovery_hold(controller, recovery_hold_id)
        if hold.workflow_run_id != workflow_run_id or hold.project_id != project_id:
            raise ValidationError("Recovery Hold belongs to another workflow run.")
        failed_stage = self._stage(controller, hold.failed_stage_instance_id)
        definition = self._definition(controller, failed_stage.stage_definition_id)
        project_match = (
            current_project_snapshot_digest == run.project_snapshot_digest
            == hold.current_project_snapshot_digest
        )
        workflow_revision_match = expected_revision == run.revision
        recovery_resolved = hold.hold_status in {
            "resolved_pending_resume_review",
            "awaiting_human_review",
        }
        technical_passed = self._technical_validation_passed(
            technical_validation,
            required=True,
        )
        quality_accepted, quality_human_required = self._quality_ready(
            quality_decision,
            required=True,
        )
        approval_valid = self._approval_valid(
            approval_record,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            stage=failed_stage,
            operation_id=definition.operation_id,
        )
        safety_valid = self._resume_safety_valid(
            safety_decision,
            project_id=project_id,
            project_snapshot_digest=run.project_snapshot_digest,
            operation_id=definition.operation_id,
        )
        human_complete = self._human_decision_valid(
            human_decision,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            stage=failed_stage,
            request=None,
        )
        if not hold.human_review_required and not quality_human_required:
            human_complete = True
        no_active_recovery = not bool(run.active_autopilot_run_id)
        no_active_transition = not bool(
            run.active_transition_request_id
            or run.active_integration_transaction_id
        )
        current_artifacts = [
            item
            for item in controller.artifact_bindings
            if item.artifact_binding_id in hold.recovery_artifact_ids
        ]
        artifacts_current = bool(current_artifacts) and all(
            item.available and not item.stale and not item.malformed
            for item in current_artifacts
        )
        dependency = self.validate_workflow_dependencies(
            project_id,
            workflow_run_id,
            failed_stage.stage_instance_id,
            rights_ready=rights_clear,
            approval_ready=approval_valid,
            safety_ready=safety_valid,
            checkpoint_ready=checkpoint_valid,
            validation_ready=technical_passed,
            quality_ready=quality_accepted,
            human_review_ready=human_complete,
            persist=False,
        )
        retry_budget_clear = failed_stage.attempt_number < definition.maximum_attempts
        checks = {
            "project snapshot matches": project_match,
            "workflow revision matches": workflow_revision_match,
            "recovery is resolved": recovery_resolved,
            "technical validation passed": technical_passed,
            "output quality accepted": quality_accepted,
            "rights remain clear": rights_clear,
            "Safety decision is current": safety_valid,
            "target approval remains valid": approval_valid,
            "checkpoint is valid": checkpoint_valid,
            "rollback state is clear": rollback_state_clear,
            "no recovery action is active": no_active_recovery,
            "no workflow transition is active": no_active_transition,
            "recovery artifacts are current": artifacts_current,
            "stage dependencies remain ready": not dependency.blocks_transition,
            "required human review is complete": human_complete,
            "retry budget remains": retry_budget_clear,
        }
        missing = [label for label, passed in checks.items() if not passed]
        eligible = not missing
        review = BobaWorkflowResumeEligibilityReviewV1(
            resume_eligibility_review_id=_runtime_id("workflow_resume_review"),
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            recovery_hold_id=recovery_hold_id,
            paused_stage_instance_id=failed_stage.stage_instance_id,
            proposed_target_stage_definition_id=failed_stage.stage_definition_id,
            project_snapshot_match=project_match,
            workflow_revision_match=workflow_revision_match,
            recovery_resolved=recovery_resolved,
            output_quality_accepted=quality_accepted,
            technical_validation_passed=technical_passed,
            rights_clear=rights_clear,
            safety_decision_valid=safety_valid,
            target_approval_valid=approval_valid,
            checkpoint_valid=checkpoint_valid,
            rollback_state_clear=rollback_state_clear,
            no_active_recovery=no_active_recovery,
            no_active_conflicting_transition=no_active_transition,
            artifacts_current=artifacts_current,
            dependencies_ready=not dependency.blocks_transition,
            human_review_complete=human_complete,
            retry_budget_clear=retry_budget_clear,
            resume_eligible=eligible,
            missing_conditions=_unique(missing, maximum=500),
            blocking_conditions=_unique(
                [*missing, *dependency.failure_reasons],
                maximum=900,
            ),
            safest_next_action=(
                "Create one new exact transition request; do not execute it yet."
                if eligible
                else "Keep the normal workflow paused and resolve the listed conditions."
            ),
            limitations=[
                "Eligibility does not authorize unrestricted workflow resume.",
                "Eligibility does not execute the target stage.",
            ],
        )
        controller.resume_eligibility_reviews.append(review)
        run.run_status = "paused"
        run.current_project_state = (
            "transition_ready" if eligible else "resume_eligibility_review"
        )
        run.updated_at = now_iso()
        run.revision += 1
        self._append_event(
            controller,
            run,
            event_type="resume_eligible" if eligible else "resume_blocked",
            severity="info" if eligible else "warning",
            stage=failed_stage,
            technical_message=(
                f"Resume eligibility review {review.resume_eligibility_review_id} "
                f"completed with eligible={eligible}."
            ),
            easy_message=(
                "The repaired output passed its checks. BOBA can prepare one exact "
                "transition, but nothing resumed yet."
                if eligible
                else "BOBA kept the workflow paused because recovery conditions remain."
            ),
            confirmed_fact=f"Eligibility: {eligible}.",
            assessment="; ".join(missing[:4]),
            requires_attention=not eligible,
        )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        if eligible:
            hold = self._recovery_hold(controller, recovery_hold_id)
            hold.released = True
            hold.released_at = now_iso()
            hold.hold_status = "released"
            run.active_recovery_hold_id = None
            replacement = self._create_retry_stage_instance(
                controller,
                run,
                failed_stage,
            )
            self.store.save_boba_workflow_controller(controller)
            request = self.create_transition_request(
                project_id,
                workflow_run_id,
                source_stage_instance_id=failed_stage.stage_instance_id,
                target_stage_id=replacement.stage_id,
                expected_revision=run.revision,
                transition_type="return_from_recovery",
                reason="A separate exact recovery transition is required.",
                clip_id=replacement.clip_id,
                output_id=replacement.output_id,
                approval_record_id=self._record_id(
                    approval_record,
                    "approval_id",
                    "approval_record_id",
                ),
                safety_decision_id=self._record_id(
                    safety_decision,
                    "safety_decision_id",
                ),
                checkpoint_reference=None,
                checkpoint_digest=None,
                quality_decision_id=self._quality_decision_id(quality_decision),
                human_decision_id=self._record_id(
                    human_decision,
                    "human_decision_id",
                ),
            )
            controller = self._controller(project_id)
            run = self._run(controller, workflow_run_id)
            run.run_status = "paused"
            run.current_project_state = "transition_ready"
            run.stop_reason = (
                "Recovery is eligible; the new exact transition remains unexecuted."
            )
            run.active_transition_request_id = request.transition_request_id
            self._refresh_summary(controller)
            self.store.save_boba_workflow_controller(controller)
        return review

    def record_human_workflow_decision(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        expected_revision: int,
        decision_type: str,
        decision: str,
        reason: str,
        reviewer_reference: str,
        explicit_confirmation: bool,
        stage_instance_id: str | None = None,
        transition_request_id: str | None = None,
        conditions: Sequence[str] = (),
        expires_in_seconds: int | None = None,
    ) -> BobaWorkflowHumanDecisionV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        if run.run_status in _TERMINAL_RUN_STATUSES:
            raise ValidationError("Terminal workflow history is immutable.")
        if _SECRET_KEY.search(reviewer_reference):
            raise ValidationError("Reviewer references cannot contain credentials.")
        prohibited = {
            "authorize_upload",
            "authorize_publication",
            "skip_required_stage",
            "override_rights",
            "override_safety",
            "overwrite_accepted_output",
            "modify_source_media",
            "resume_everything",
        }
        if decision.casefold() in prohibited:
            raise ValidationError("The requested human authority is unavailable.")
        stage = self._stage(controller, stage_instance_id) if stage_instance_id else None
        if stage is not None and stage.workflow_run_id != workflow_run_id:
            raise ValidationError("Human decision stage belongs to another workflow run.")
        request = (
            self._transition_request(controller, transition_request_id)
            if transition_request_id
            else None
        )
        if request is not None and request.workflow_run_id != workflow_run_id:
            raise ValidationError(
                "Human decision transition belongs to another workflow run."
            )
        expiry = (
            (
                datetime.now(UTC)
                + timedelta(seconds=max(1, min(expires_in_seconds, 86_400)))
            ).isoformat()
            if expires_in_seconds is not None
            else None
        )
        record = BobaWorkflowHumanDecisionV1(
            human_decision_id=_runtime_id("workflow_human_decision"),
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            stage_instance_id=stage_instance_id,
            transition_request_id=transition_request_id,
            decision_type=_bounded_text(decision_type, maximum=160),
            decision=_bounded_text(decision, maximum=160),
            bounded_reason=_bounded_text(reason, maximum=900),
            reviewer_reference=_bounded_text(reviewer_reference, maximum=160),
            project_snapshot_digest=run.project_snapshot_digest,
            workflow_revision=run.revision,
            explicit_confirmation=explicit_confirmation,
            conditions=_unique(conditions, maximum=500),
            expires_at=expiry,
        )
        controller.human_decisions.append(record)
        run.human_decision_ids = _unique(
            [*run.human_decision_ids, record.human_decision_id],
            limit=512,
            maximum=180,
        )
        run.updated_at = now_iso()
        run.revision += 1
        controller.signal_usage.human_decision_used = True
        self._append_event(
            controller,
            run,
            event_type=(
                "stage_ready"
                if explicit_confirmation
                else "human_review_required"
            ),
            severity="info" if explicit_confirmation else "warning",
            stage=stage,
            transition_request=request,
            technical_message=(
                f"Bounded human workflow decision {record.human_decision_id} recorded."
            ),
            easy_message=(
                "BOBA recorded the review decision. It did not upload, publish, "
                "or run another stage."
            ),
            confirmed_fact=f"Explicit confirmation: {explicit_confirmation}.",
            requires_attention=not explicit_confirmation,
        )
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return record

    def complete_internal_output(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        expected_revision: int,
    ) -> BobaWorkflowRunV1:
        controller = self._controller(project_id)
        run = self._run(controller, workflow_run_id)
        self._require_revision(run, expected_revision)
        stage = self._stage_for_identity(
            controller,
            run,
            stage_id="internal_output_completion",
        )
        self._mark_internal_output_complete(controller, run, stage)
        run.revision += 1
        self._refresh_summary(controller)
        self.store.save_boba_workflow_controller(controller)
        return run

    def inspect_workflow_events(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> list[BobaWorkflowEventV1]:
        controller = self._controller(project_id)
        self._run(controller, workflow_run_id)
        persisted = self.store.load_boba_workflow_events(
            project_id,
            workflow_run_id,
        )
        if persisted:
            return persisted
        return sorted(
            [
                item
                for item in controller.workflow_events
                if item.workflow_run_id == workflow_run_id
            ],
            key=lambda item: item.sequence,
        )

    def export_workflow_controller(self, project_id: str) -> dict[str, Any]:
        self._controller(project_id)
        return self.store.export_boba_workflow_controller(project_id)

    def reset_workflow_controller_metadata(self, project_id: str) -> dict[str, Any]:
        return self.store.reset_boba_workflow_controller(project_id)

    def _controller(self, project_id: str) -> BobaWorkflowControllerSetV1:
        controller = self.store.load_boba_workflow_controller(project_id)
        if controller is None:
            raise NotFoundError(
                "BOBA Workflow Controller is not available.",
                details={"project_id": project_id},
            )
        return controller

    @staticmethod
    def _run(
        controller: BobaWorkflowControllerSetV1,
        workflow_run_id: str,
    ) -> BobaWorkflowRunV1:
        run = next(
            (
                item
                for item in controller.workflow_runs
                if item.workflow_run_id == workflow_run_id
            ),
            None,
        )
        if run is None:
            raise NotFoundError(
                "BOBA workflow run was not found.",
                details={"workflow_run_id": workflow_run_id},
            )
        return run

    @staticmethod
    def _stage(
        controller: BobaWorkflowControllerSetV1,
        stage_instance_id: str | None,
    ) -> BobaWorkflowStageInstanceV1:
        if not stage_instance_id:
            raise NotFoundError("BOBA workflow stage was not found.")
        stage = next(
            (
                item
                for item in controller.stage_instances
                if item.stage_instance_id == stage_instance_id
            ),
            None,
        )
        if stage is None:
            raise NotFoundError(
                "BOBA workflow stage was not found.",
                details={"stage_instance_id": stage_instance_id},
            )
        return stage

    @staticmethod
    def _definition(
        controller: BobaWorkflowControllerSetV1,
        stage_definition_id: str,
    ) -> BobaWorkflowStageDefinitionV1:
        definition = next(
            (
                item
                for item in controller.stage_definitions
                if item.stage_definition_id == stage_definition_id
            ),
            None,
        )
        if definition is None:
            raise NotFoundError(
                "BOBA workflow stage definition was not found.",
                details={"stage_definition_id": stage_definition_id},
            )
        return definition

    @staticmethod
    def _definitions(
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
    ) -> list[BobaWorkflowStageDefinitionV1]:
        snapshot = next(
            (
                item
                for item in controller.workflow_definition_snapshots
                if item.workflow_definition_id == run.workflow_definition_id
            ),
            None,
        )
        if snapshot is None:
            raise ValidationError("Workflow definition snapshot is unavailable.")
        by_id = {
            item.stage_definition_id: item
            for item in controller.stage_definitions
            if item.workflow_definition_id == run.workflow_definition_id
        }
        missing = [
            item for item in snapshot.stage_definition_ids if item not in by_id
        ]
        if missing:
            raise ValidationError(
                "Workflow definition stage metadata is incomplete.",
                details={"stage_definition_ids": missing},
            )
        return [by_id[item] for item in snapshot.stage_definition_ids]

    @staticmethod
    def _stages(
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
    ) -> list[BobaWorkflowStageInstanceV1]:
        return [
            item
            for item in controller.stage_instances
            if item.workflow_run_id == run.workflow_run_id
        ]

    def _stage_for_identity(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        *,
        stage_id: str,
        clip_id: str | None = None,
        output_id: str | None = None,
    ) -> BobaWorkflowStageInstanceV1:
        matches = [
            item
            for item in self._stages(controller, run)
            if item.stage_id == stage_id
            and (clip_id is None or item.clip_id == clip_id)
            and (output_id is None or item.output_id == output_id)
        ]
        if not matches:
            raise NotFoundError(
                "The exact workflow stage identity is unavailable.",
                details={
                    "stage_id": stage_id,
                    "clip_id": clip_id,
                    "output_id": output_id,
                },
            )
        if len(matches) != 1:
            active = [
                item
                for item in matches
                if item.status
                not in {
                    "completed",
                    "completed_with_limitations",
                    "failed",
                    "timed_out",
                    "cancelled",
                    "superseded",
                    "skipped_not_required",
                }
            ]
            if len(active) == 1:
                return active[0]
            raise ValidationError(
                "Workflow stage identity is ambiguous; exact clip/output is required."
            )
        return matches[0]

    def _stage_for_definition(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        stage_definition_id: str,
        *,
        clip_id: str | None = None,
        output_id: str | None = None,
    ) -> BobaWorkflowStageInstanceV1:
        definition = self._definition(controller, stage_definition_id)
        return self._stage_for_identity(
            controller,
            run,
            stage_id=definition.stage_id,
            clip_id=clip_id,
            output_id=output_id,
        )

    def _current_stage(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
    ) -> BobaWorkflowStageInstanceV1 | None:
        for stage_id in run.current_stage_instance_ids:
            try:
                return self._stage(controller, stage_id)
            except NotFoundError:
                continue
        stages = self._stages(controller, run)
        return next(
            (
                item
                for item in stages
                if item.status
                in {
                    "running",
                    "ready",
                    "awaiting_approval",
                    "awaiting_safety_decision",
                    "recovery_required",
                }
            ),
            stages[-1] if stages else None,
        )

    @staticmethod
    def _require_revision(run: BobaWorkflowRunV1, expected_revision: int) -> None:
        if expected_revision != run.revision:
            raise ValidationError(
                "Workflow revision is stale.",
                details={
                    "expected_revision": expected_revision,
                    "current_revision": run.revision,
                },
            )

    @staticmethod
    def _transition_request(
        controller: BobaWorkflowControllerSetV1,
        transition_request_id: str | None,
    ) -> BobaWorkflowTransitionRequestV1:
        if not transition_request_id:
            raise NotFoundError("Workflow transition request was not found.")
        request = next(
            (
                item
                for item in controller.transition_requests
                if item.transition_request_id == transition_request_id
            ),
            None,
        )
        if request is None:
            raise NotFoundError(
                "Workflow transition request was not found.",
                details={"transition_request_id": transition_request_id},
            )
        return request

    @staticmethod
    def _transition_decision(
        controller: BobaWorkflowControllerSetV1,
        transition_decision_id: str,
    ) -> BobaWorkflowTransitionDecisionV1:
        decision = next(
            (
                item
                for item in controller.transition_decisions
                if item.transition_decision_id == transition_decision_id
            ),
            None,
        )
        if decision is None:
            raise NotFoundError(
                "Workflow transition decision was not found.",
                details={"transition_decision_id": transition_decision_id},
            )
        return decision

    @staticmethod
    def _recovery_hold(
        controller: BobaWorkflowControllerSetV1,
        recovery_hold_id: str,
    ) -> BobaWorkflowRecoveryHoldV1:
        hold = next(
            (
                item
                for item in controller.recovery_holds
                if item.recovery_hold_id == recovery_hold_id
            ),
            None,
        )
        if hold is None:
            raise NotFoundError(
                "Workflow Recovery Hold was not found.",
                details={"recovery_hold_id": recovery_hold_id},
            )
        return hold

    @staticmethod
    def _active_recovery_hold(
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
    ) -> BobaWorkflowRecoveryHoldV1 | None:
        return next(
            (
                item
                for item in reversed(controller.recovery_holds)
                if item.workflow_run_id == run.workflow_run_id
                and not item.released
                and item.hold_status
                not in {"released", "resolved_pending_resume_review"}
            ),
            None,
        )

    def _create_stage_instances(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        *,
        clip_ids: Sequence[str],
        output_ids_by_clip: Mapping[str, str],
    ) -> list[BobaWorkflowStageInstanceV1]:
        definitions = self._definitions(controller, run)
        instances: list[BobaWorkflowStageInstanceV1] = []
        for definition in definitions:
            identities: list[tuple[str | None, str | None]]
            if definition.stage_scope == "project":
                identities = [(None, None)]
            elif definition.stage_scope == "clip":
                identities = [(clip_id, None) for clip_id in clip_ids]
            elif definition.stage_scope == "output":
                identities = [
                    (clip_id, output_ids_by_clip[clip_id])
                    for clip_id in clip_ids
                    if output_ids_by_clip.get(clip_id)
                ]
            else:
                identities = []
            for clip_id, output_id in identities:
                stage_instance_id = _stable_id(
                    "workflow_stage",
                    run.workflow_run_id,
                    definition.stage_id,
                    clip_id or "",
                    output_id or "",
                    1,
                )
                instances.append(
                    BobaWorkflowStageInstanceV1(
                        stage_instance_id=stage_instance_id,
                        workflow_run_id=run.workflow_run_id,
                        project_id=run.project_id,
                        clip_id=clip_id,
                        output_id=output_id,
                        stage_definition_id=definition.stage_definition_id,
                        stage_id=definition.stage_id,
                        attempt_number=1,
                        status=(
                            "completed"
                            if definition.stage_id == "workflow_created"
                            else "pending"
                        ),
                        created_at=run.created_at,
                        started_at=(
                            run.created_at
                            if definition.stage_id == "workflow_created"
                            else None
                        ),
                        completed_at=(
                            run.created_at
                            if definition.stage_id == "workflow_created"
                            else None
                        ),
                        project_snapshot_digest=run.project_snapshot_digest,
                        result_digest=(
                            _digest(
                                {
                                    "workflow_run_id": run.workflow_run_id,
                                    "stage_id": "workflow_created",
                                }
                            )
                            if definition.stage_id == "workflow_created"
                            else ""
                        ),
                        limitations=[
                            "The stage can invoke only its fixed registered operation."
                        ],
                    )
                )
        by_stage: dict[str, list[BobaWorkflowStageInstanceV1]] = {}
        for instance in instances:
            by_stage.setdefault(instance.stage_id, []).append(instance)

        def compatible(
            predecessor: BobaWorkflowStageInstanceV1,
            target: BobaWorkflowStageInstanceV1,
        ) -> bool:
            if (
                target.clip_id
                and predecessor.clip_id
                and predecessor.clip_id != target.clip_id
            ):
                return False
            if (
                target.output_id
                and predecessor.output_id
                and predecessor.output_id != target.output_id
            ):
                return False
            if target.output_id and predecessor.clip_id and target.clip_id:
                return predecessor.clip_id == target.clip_id
            if target.clip_id and predecessor.output_id:
                return predecessor.clip_id == target.clip_id
            return True

        for instance in instances:
            definition = self._definition(controller, instance.stage_definition_id)
            predecessors: list[BobaWorkflowStageInstanceV1] = []
            for predecessor_stage_id in definition.required_predecessor_stage_ids:
                predecessors.extend(
                    item
                    for item in by_stage.get(predecessor_stage_id, [])
                    if compatible(item, instance)
                )
            instance.predecessor_stage_instance_ids = _unique(
                [item.stage_instance_id for item in predecessors],
                limit=64,
                maximum=180,
            )
            for predecessor in predecessors:
                predecessor.successor_stage_instance_ids = _unique(
                    [
                        *predecessor.successor_stage_instance_ids,
                        instance.stage_instance_id,
                    ],
                    limit=64,
                    maximum=180,
                )
        return instances

    def _create_retry_stage_instance(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        failed_stage: BobaWorkflowStageInstanceV1,
    ) -> BobaWorkflowStageInstanceV1:
        definition = self._definition(
            controller,
            failed_stage.stage_definition_id,
        )
        attempt_number = failed_stage.attempt_number + 1
        if attempt_number > definition.maximum_attempts:
            raise ValidationError("The workflow stage retry limit is exhausted.")
        replacement = BobaWorkflowStageInstanceV1(
            stage_instance_id=_stable_id(
                "workflow_stage",
                run.workflow_run_id,
                failed_stage.stage_id,
                failed_stage.clip_id or "",
                failed_stage.output_id or "",
                attempt_number,
            ),
            workflow_run_id=run.workflow_run_id,
            project_id=run.project_id,
            clip_id=failed_stage.clip_id,
            output_id=failed_stage.output_id,
            stage_definition_id=failed_stage.stage_definition_id,
            stage_id=failed_stage.stage_id,
            attempt_number=attempt_number,
            status="pending",
            predecessor_stage_instance_ids=list(
                failed_stage.predecessor_stage_instance_ids
            ),
            successor_stage_instance_ids=list(
                failed_stage.successor_stage_instance_ids
            ),
            input_artifact_binding_ids=list(
                failed_stage.input_artifact_binding_ids
            ),
            project_snapshot_digest=run.project_snapshot_digest,
            limitations=[
                "This is a new exact attempt; failed history remains immutable."
            ],
        )
        if any(
            item.stage_instance_id == replacement.stage_instance_id
            for item in controller.stage_instances
        ):
            raise ValidationError("A replacement workflow stage already exists.")
        controller.stage_instances.append(replacement)
        run.current_stage_instance_ids = [replacement.stage_instance_id]
        return replacement

    @staticmethod
    def _artifact_matches_stage(
        artifact: BobaWorkflowArtifactBindingV1,
        stage: BobaWorkflowStageInstanceV1,
    ) -> bool:
        if (
            artifact.project_id != stage.project_id
            or artifact.workflow_run_id != stage.workflow_run_id
        ):
            return False
        if artifact.output_id and artifact.output_id != stage.output_id:
            return False
        if artifact.clip_id and artifact.clip_id != stage.clip_id:
            return False
        if stage.output_id and artifact.output_id:
            return artifact.output_id == stage.output_id
        if stage.clip_id and artifact.clip_id:
            return artifact.clip_id == stage.clip_id
        return artifact.clip_id is None and artifact.output_id is None

    def _integration_layer(
        self,
        controller: BobaWorkflowControllerSetV1,
    ) -> BobaIntegrationLayerV1:
        factory = self.integration_layer_factory
        if factory is None:
            raise ValidationError(
                "Workflow Controller Integration Layer adapter is unavailable."
            )
        if isinstance(factory, BobaIntegrationLayerV1):
            return factory
        try:
            layer = factory(
                controller.project_id,
                source_id=controller.source_id,
            )
        except TypeError:
            layer = factory(controller.project_id)
        if not isinstance(layer, BobaIntegrationLayerV1):
            raise ValidationError(
                "Workflow Controller received an invalid Integration Layer adapter."
            )
        return layer

    def _integration_operation_ready(
        self,
        project_id: str,
        operation_id: str,
    ) -> bool:
        try:
            controller = self._controller(project_id)
            layer = self._integration_layer(controller)
        except (NotFoundError, ValidationError, TypeError):
            return False
        operation = layer.operation_registry.get(operation_id)
        if operation is None or operation.future_gated or operation.prohibited:
            return False
        module = layer.module_registry.get(operation.module_id)
        return bool(
            module
            and module.implementation_status in {"available", "degraded"}
        )

    def _integration_artifact_references(
        self,
        controller: BobaWorkflowControllerSetV1,
        stage: BobaWorkflowStageInstanceV1,
    ) -> list[BobaIntegrationArtifactReferenceV1]:
        definition = self._definition(controller, stage.stage_definition_id)
        artifacts = [
            item
            for item in controller.artifact_bindings
            if self._artifact_matches_stage(item, stage)
            and not item.source_media
            and item.artifact_type
            in {
                *definition.required_artifact_types,
                *definition.optional_artifact_types,
            }
        ]
        return [
            BobaIntegrationArtifactReferenceV1(
                artifact_reference_id=item.artifact_binding_id,
                artifact_type=item.artifact_type,
                project_id=item.project_id,
                source_id=controller.source_id,
                producer_module_id=item.producer_module_id,
                producer_record_id=item.producer_record_id,
                schema_id=item.schema_id,
                schema_version=item.schema_version,
                sanitized_storage_reference=item.sanitized_storage_reference,
                artifact_digest=item.artifact_digest,
                immutable=item.immutable,
                required=item.required,
                available=item.available,
                stale=item.stale,
                malformed=item.malformed,
                rights_relevant=item.rights_relevant,
                safety_relevant=item.safety_relevant,
            )
            for item in artifacts
        ]

    def _completed_integration_response(
        self,
        project_id: str,
        transaction_id: str | None,
    ) -> BobaIntegrationResponseV1 | None:
        if not transaction_id:
            return None
        transaction = self.store.load_boba_integration_transaction(
            project_id,
            transaction_id,
        )
        layer = self.store.load_boba_integration_layer(project_id)
        if transaction is None or layer is None or not transaction.response_id:
            return None
        return next(
            (
                item
                for item in layer.integration_responses
                if item.response_id == transaction.response_id
                and item.status in {"succeeded", "duplicate_reused"}
            ),
            None,
        )

    def _bind_stage_result_artifacts(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        stage: BobaWorkflowStageInstanceV1,
        definition: BobaWorkflowStageDefinitionV1,
        response: BobaIntegrationResponseV1,
    ) -> None:
        raw_bindings = response.bounded_result.get("artifact_bindings")
        values = raw_bindings if isinstance(raw_bindings, list) else []
        candidates: list[BobaWorkflowArtifactBindingV1] = []
        for index, raw in enumerate(values[:64]):
            if not isinstance(raw, Mapping):
                raise ValidationError("Target artifact binding is malformed.")
            artifact_project = str(raw.get("project_id") or stage.project_id)
            artifact_run = str(raw.get("workflow_run_id") or run.workflow_run_id)
            artifact_clip = str(raw.get("clip_id") or "") or None
            artifact_output = str(raw.get("output_id") or "") or None
            if artifact_project != stage.project_id:
                raise ValidationError("Target artifact belongs to another project.")
            if artifact_run != run.workflow_run_id:
                raise ValidationError("Target artifact belongs to another workflow run.")
            if stage.clip_id and artifact_clip != stage.clip_id:
                raise ValidationError("Target artifact belongs to another clip.")
            if stage.output_id and artifact_output != stage.output_id:
                raise ValidationError("Target artifact belongs to another output.")
            artifact_type = str(raw.get("artifact_type") or "")
            if artifact_type not in definition.produced_artifact_types:
                raise ValidationError(
                    "Target returned an undeclared workflow artifact type."
                )
            digest = str(raw.get("artifact_digest") or "")
            if not _DIGEST.fullmatch(digest):
                raise ValidationError("Target artifact digest is malformed.")
            reference = _validate_storage_reference(
                str(raw.get("sanitized_storage_reference") or "")
            )
            candidate = BobaWorkflowArtifactBindingV1(
                artifact_binding_id=_stable_id(
                    "workflow_artifact",
                    run.workflow_run_id,
                    stage.stage_instance_id,
                    artifact_type,
                    index,
                    digest,
                ),
                workflow_run_id=run.workflow_run_id,
                stage_instance_id=stage.stage_instance_id,
                project_id=stage.project_id,
                clip_id=artifact_clip or stage.clip_id,
                output_id=artifact_output or stage.output_id,
                artifact_type=artifact_type,
                producer_module_id=definition.operation_module_id,
                producer_record_id=str(
                    raw.get("producer_record_id") or response.response_id
                ),
                schema_id=str(
                    raw.get("schema_id")
                    or f"boba.workflow.{artifact_type}"
                ),
                schema_version=str(raw.get("schema_version") or "1"),
                artifact_digest=digest,
                sanitized_storage_reference=reference,
                immutable=True,
                accepted_output=bool(raw.get("accepted_output")),
                source_media=False,
                source_media_read_only=True,
                required=True,
                available=bool(raw.get("available", True)),
                stale=bool(raw.get("stale", False)),
                malformed=bool(raw.get("malformed", False)),
                rights_relevant=bool(raw.get("rights_relevant")),
                safety_relevant=bool(raw.get("safety_relevant")),
                quality_relevant=bool(raw.get("quality_relevant")),
            )
            candidates.append(candidate)
        if not candidates and definition.side_effect_class in {
            "none",
            "BOBA_metadata_only",
        }:
            reference = (
                f"projects/{stage.project_id}/"
                f"{definition.operation_module_id}/index.json"
            )
            for artifact_type in definition.produced_artifact_types:
                candidates.append(
                    BobaWorkflowArtifactBindingV1(
                        artifact_binding_id=_stable_id(
                            "workflow_artifact",
                            run.workflow_run_id,
                            stage.stage_instance_id,
                            artifact_type,
                            response.result_digest,
                        ),
                        workflow_run_id=run.workflow_run_id,
                        stage_instance_id=stage.stage_instance_id,
                        project_id=stage.project_id,
                        clip_id=stage.clip_id,
                        output_id=stage.output_id,
                        artifact_type=artifact_type,
                        producer_module_id=definition.operation_module_id,
                        producer_record_id=response.response_id,
                        schema_id=f"boba.workflow.{artifact_type}",
                        schema_version="1",
                        artifact_digest=_digest(
                            {
                                "response_digest": response.result_digest,
                                "artifact_type": artifact_type,
                                "stage_instance_id": stage.stage_instance_id,
                            }
                        ),
                        sanitized_storage_reference=reference,
                        immutable=True,
                        accepted_output=False,
                        source_media=False,
                        source_media_read_only=True,
                        required=True,
                        available=True,
                        quality_relevant=definition.output_quality_review_required,
                    )
                )
        returned_types = {item.artifact_type for item in candidates}
        missing = sorted(set(definition.produced_artifact_types) - returned_types)
        if missing:
            raise ValidationError(
                "Stage cannot complete without required result artifacts.",
                details={"missing_artifact_types": missing},
            )
        for candidate in candidates:
            if candidate.stale or candidate.malformed or not candidate.available:
                raise ValidationError("Stage result artifact is not current and usable.")
            overwrite = next(
                (
                    item
                    for item in controller.artifact_bindings
                    if item.accepted_output
                    and item.sanitized_storage_reference
                    == candidate.sanitized_storage_reference
                    and item.artifact_digest != candidate.artifact_digest
                ),
                None,
            )
            if overwrite is not None:
                raise ValidationError(
                    "An accepted output cannot be overwritten by a new render."
                )
            existing = next(
                (
                    item
                    for item in controller.artifact_bindings
                    if item.artifact_binding_id == candidate.artifact_binding_id
                ),
                None,
            )
            if existing is not None:
                if existing.model_dump(mode="json") != candidate.model_dump(mode="json"):
                    raise ValidationError("Immutable stage artifact binding changed.")
            else:
                controller.artifact_bindings.append(candidate)
            stage.output_artifact_binding_ids = _unique(
                [
                    *stage.output_artifact_binding_ids,
                    candidate.artifact_binding_id,
                ],
                limit=128,
                maximum=180,
            )

    def _ready_successor_stages(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        completed_stage: BobaWorkflowStageInstanceV1,
    ) -> None:
        ready: list[str] = []
        for successor_id in completed_stage.successor_stage_instance_ids:
            successor = self._stage(controller, successor_id)
            if successor.status not in {"pending", "dependency_blocked"}:
                continue
            predecessors = [
                self._stage(controller, item)
                for item in successor.predecessor_stage_instance_ids
            ]
            if all(
                item.status in {"completed", "completed_with_limitations"}
                for item in predecessors
            ):
                successor.status = "ready"
                ready.append(successor.stage_instance_id)
        run.current_stage_instance_ids = _unique(
            ready,
            limit=256,
            maximum=180,
        )
        if ready:
            run.current_project_state = "stage_ready"

    def _release_execution_lease(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        stage: BobaWorkflowStageInstanceV1 | None,
    ) -> None:
        try:
            released = self.store.release_boba_workflow_execution_lease(
                run.project_id,
                workflow_run_id=run.workflow_run_id,
                owner_id=self.lease_owner,
            )
        except ValidationError as exc:
            run.warnings = _unique(
                [*run.warnings, f"Execution lease release warning: {exc}"],
                limit=128,
                maximum=900,
            )
            return
        if released:
            for lease in controller.execution_leases:
                if lease.execution_lease_id == run.execution_lease_id:
                    lease.lease_status = "released"
                    lease.refreshed_at = now_iso()
            run.execution_lease_id = None

    def _fail_stage(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        stage: BobaWorkflowStageInstanceV1,
        *,
        reason: str,
        incident_type: BobaWorkflowIncidentTypeV1,
        timed_out: bool = False,
        uncertain: bool = False,
    ) -> None:
        stage.status = "timed_out" if timed_out else "failed"
        stage.completed_at = now_iso()
        stage.failure_summary = _bounded_text(reason, maximum=900)
        stage.recovery_required = True
        run.failed_stage_instance_ids = _unique(
            [*run.failed_stage_instance_ids, stage.stage_instance_id],
            limit=512,
            maximum=180,
        )
        run.current_stage_instance_ids = [stage.stage_instance_id]
        run.active_transition_request_id = None
        run.active_transition_decision_id = None
        run.active_integration_transaction_id = None
        run.run_status = "paused"
        run.current_project_state = (
            "recovery_required" if not uncertain else "paused"
        )
        run.stop_reason = stage.failure_summary
        run.updated_at = now_iso()
        run.revision += 1
        self._record_incident(
            controller,
            run,
            incident_type=incident_type,
            title="Workflow stage did not complete",
            summary=stage.failure_summary,
            stage=stage,
            transition_request_id=stage.transition_request_id,
            project_state_uncertain=uncertain,
            recovery_required=True,
        )
        self._append_event(
            controller,
            run,
            event_type="stage_failed",
            severity="error",
            stage=stage,
            technical_message=stage.failure_summary,
            easy_message=(
                "This stage failed, so BOBA paused all later required work."
            ),
            confirmed_fact=f"Stage status: {stage.status}.",
            assessment=(
                "Target state is uncertain."
                if uncertain
                else "No success was recorded."
            ),
            requires_attention=True,
        )
        self._pause_in_place(
            controller,
            run,
            stage=stage,
            reason=stage.failure_summary,
            category="recovery_required",
            automatic=True,
            increment_revision=False,
        )
        if self._active_recovery_hold(controller, run) is None:
            hold = BobaWorkflowRecoveryHoldV1(
                recovery_hold_id=_runtime_id("workflow_recovery_hold"),
                workflow_run_id=run.workflow_run_id,
                project_id=run.project_id,
                failed_stage_instance_id=stage.stage_instance_id,
                recovery_reason=stage.failure_summary,
                hold_status="awaiting_autopilot",
                recovery_artifact_ids=list(stage.output_artifact_binding_ids),
                original_project_snapshot_digest=run.project_snapshot_digest,
                current_project_snapshot_digest=run.project_snapshot_digest,
                limitations=[
                    "Workflow Controller does not diagnose or repair this failure."
                ],
            )
            controller.recovery_holds.append(hold)
            run.active_recovery_hold_id = hold.recovery_hold_id
            run.run_status = "recovery"
            controller.handoffs.append(
                BobaWorkflowHandoffV1(
                    handoff_id=_runtime_id("workflow_handoff"),
                    workflow_run_id=run.workflow_run_id,
                    project_id=run.project_id,
                    stage_instance_id=stage.stage_instance_id,
                    transition_request_id=stage.transition_request_id,
                    target_module_id="autopilot_controller",
                    reason=stage.failure_summary,
                    current_project_state="recovery_required",
                    required_inputs=[
                        "failed_stage_identity",
                        "recovery_hold",
                        "bounded_failure_evidence",
                    ],
                    artifact_binding_ids=list(stage.output_artifact_binding_ids),
                    allowed_actions=[
                        "diagnose",
                        "plan_bounded_recovery",
                        "return_typed_result",
                    ],
                    prohibited_actions=[
                        "continue_normal_workflow",
                        "release_recovery_hold",
                    ],
                    apply_automatically=False,
                    human_approval_required=True,
                    priority="high",
                )
            )
            controller.signal_usage.autopilot_handoff_used = True

    def _pause_in_place(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        *,
        stage: BobaWorkflowStageInstanceV1 | None,
        reason: str,
        category: BobaWorkflowPauseCategoryV1,
        automatic: bool,
        increment_revision: bool,
    ) -> BobaWorkflowPauseRecordV1:
        pause = BobaWorkflowPauseRecordV1(
            pause_record_id=_runtime_id("workflow_pause"),
            workflow_run_id=run.workflow_run_id,
            project_id=run.project_id,
            stage_instance_id=stage.stage_instance_id if stage else None,
            pause_reason=_bounded_text(reason, maximum=900),
            pause_category=category,
            requested_by=(
                "workflow_controller" if automatic else "human_operator"
            ),
            automatic_pause=automatic,
            project_state_at_pause=run.current_project_state,
            project_snapshot_digest=run.project_snapshot_digest,
            active_operation_status=(
                "running_not_interrupted"
                if stage is not None and stage.status == "running"
                else "none"
            ),
            source_media_protected=True,
            accepted_outputs_protected=True,
            recovery_required=category
            in {
                "stage_failure",
                "validation_failure",
                "quality_rejection",
                "checkpoint_issue",
                "recovery_required",
                "uncertain_state",
            },
            human_review_required=category
            in {
                "manual",
                "rights_block",
                "safety_block",
                "approval_required",
                "uncertain_state",
            },
            resume_conditions=[
                "Revalidate the exact project snapshot.",
                "Resolve the pause cause.",
                "Create a new exact transition decision.",
            ],
        )
        controller.pause_records.append(pause)
        run.pause_record_ids = _unique(
            [*run.pause_record_ids, pause.pause_record_id],
            limit=256,
            maximum=180,
        )
        run.run_status = "paused"
        run.current_project_state = "paused"
        run.stop_reason = pause.pause_reason
        run.updated_at = now_iso()
        if increment_revision:
            run.revision += 1
        self._append_event(
            controller,
            run,
            event_type="workflow_paused",
            severity="warning",
            stage=stage,
            technical_message=f"Workflow paused: {pause.pause_reason}",
            easy_message=(
                "BOBA paused later stages and preserved the source and accepted outputs."
            ),
            confirmed_fact="No active target was killed by the controller.",
            requires_attention=True,
            available_user_actions=["inspect", "review_pause"],
        )
        if category in {"rights_block", "safety_block", "approval_required"}:
            target: BobaWorkflowHandoffTargetV1 = (
                "safety_gate"
                if category == "safety_block"
                else "human_operator"
            )
            controller.handoffs.append(
                BobaWorkflowHandoffV1(
                    handoff_id=_runtime_id("workflow_handoff"),
                    workflow_run_id=run.workflow_run_id,
                    project_id=run.project_id,
                    stage_instance_id=stage.stage_instance_id if stage else None,
                    transition_request_id=(
                        stage.transition_request_id if stage else None
                    ),
                    target_module_id=target,
                    reason=pause.pause_reason,
                    current_project_state="paused",
                    required_inputs=["exact_pause_record"],
                    allowed_actions=["inspect", "provide_exact_review"],
                    prohibited_actions=["bypass", "resume_everything"],
                    apply_automatically=False,
                    human_approval_required=True,
                )
            )
        return pause

    def _record_incident(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        *,
        incident_type: BobaWorkflowIncidentTypeV1,
        title: str,
        summary: str,
        stage: BobaWorkflowStageInstanceV1 | None = None,
        transition_request_id: str | None = None,
        project_state_uncertain: bool = False,
        recovery_required: bool = False,
    ) -> BobaWorkflowIncidentV1:
        fingerprint = _digest(
            {
                "workflow_run_id": run.workflow_run_id,
                "stage_instance_id": stage.stage_instance_id if stage else "",
                "incident_type": incident_type,
                "summary": _bounded_text(summary, maximum=900),
            }
        )
        existing = next(
            (
                item
                for item in controller.incidents
                if item.repeated_fingerprint == fingerprint
            ),
            None,
        )
        if existing is not None:
            existing.occurrence_count += 1
            return existing
        incident = BobaWorkflowIncidentV1(
            incident_id=_runtime_id("workflow_incident"),
            workflow_run_id=run.workflow_run_id,
            project_id=run.project_id,
            stage_instance_id=stage.stage_instance_id if stage else None,
            transition_request_id=transition_request_id,
            integration_transaction_id=(
                stage.integration_transaction_id if stage else None
            ),
            incident_type=incident_type,
            severity=(
                "critical"
                if project_state_uncertain
                else "error"
            ),
            title=_bounded_text(title, maximum=240),
            bounded_summary=_bounded_text(summary, maximum=900),
            evidence_reference_ids=(
                list(stage.output_artifact_binding_ids) if stage else []
            ),
            repeated_fingerprint=fingerprint,
            project_state_uncertain=project_state_uncertain,
            source_media_risk=False,
            accepted_output_risk=False,
            immediate_controller_action="pause",
            recovery_handoff_required=recovery_required,
            human_review_required=project_state_uncertain,
        )
        controller.incidents.append(incident)
        run.incident_ids = _unique(
            [*run.incident_ids, incident.incident_id],
            limit=512,
            maximum=180,
        )
        return incident

    def _append_event(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        *,
        event_type: BobaWorkflowEventTypeV1,
        technical_message: str,
        easy_message: str,
        stage: BobaWorkflowStageInstanceV1 | None = None,
        transition_request: BobaWorkflowTransitionRequestV1 | None = None,
        operation_id: str = "",
        severity: Literal[
            "info",
            "warning",
            "error",
            "critical",
            "unknown",
        ] = "info",
        confirmed_fact: str = "",
        assessment: str = "",
        requires_attention: bool = False,
        available_user_actions: Sequence[str] = (),
        evidence_reference_ids: Sequence[str] = (),
    ) -> BobaWorkflowEventV1:
        run_events = [
            item
            for item in controller.workflow_events
            if item.workflow_run_id == run.workflow_run_id
        ]
        sequence = max((item.sequence for item in run_events), default=0) + 1
        stages = self._stages(controller, run)
        required_definition_ids = {
            item.stage_definition_id
            for item in self._definitions(controller, run)
            if item.stage_id != "human_review"
        }
        required_stages = [
            item for item in stages if item.stage_definition_id in required_definition_ids
        ]
        completed = [
            item
            for item in required_stages
            if item.status in {"completed", "completed_with_limitations"}
        ]
        progress_total = len(required_stages) if required_stages else None
        progress_current = len(completed) if progress_total is not None else None
        progress_percent = (
            round((progress_current / progress_total) * 100.0, 2)
            if progress_total and progress_current is not None
            else None
        )
        event = BobaWorkflowEventV1(
            event_id=_runtime_id("workflow_event"),
            workflow_run_id=run.workflow_run_id,
            project_id=run.project_id,
            clip_id=stage.clip_id if stage else None,
            sequence=sequence,
            event_type=event_type,
            severity=severity,
            project_state=run.current_project_state,
            stage_instance_id=stage.stage_instance_id if stage else None,
            transition_request_id=(
                transition_request.transition_request_id
                if transition_request
                else None
            ),
            module_id="workflow_controller",
            operation_id=_bounded_text(operation_id, maximum=240),
            technical_message=_bounded_text(technical_message, maximum=1_200),
            easy_message=_bounded_text(easy_message, maximum=700),
            confirmed_fact=_bounded_text(confirmed_fact, maximum=700),
            assessment=_bounded_text(assessment, maximum=700),
            progress_current=progress_current,
            progress_total=progress_total,
            progress_percent=progress_percent,
            requires_attention=requires_attention,
            available_user_actions=_unique(
                available_user_actions,
                limit=16,
                maximum=160,
            ),
            evidence_reference_ids=_unique(
                evidence_reference_ids,
                limit=64,
                maximum=180,
            ),
        )
        controller.workflow_events.append(event)
        run.event_ids = _unique(
            [*run.event_ids, event.event_id],
            limit=4_096,
            maximum=180,
        )
        controller.signal_usage.event_stream_used = True
        return event

    def _run_snapshot(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
    ) -> dict[str, Any]:
        stages = self._stages(controller, run)
        stage_ids = {item.stage_instance_id for item in stages}
        return {
            "schema_version": "boba_workflow_run_inspection_v1",
            "project_id": run.project_id,
            "workflow_run": run.model_dump(mode="json"),
            "workflow_definition": next(
                (
                    item.model_dump(mode="json")
                    for item in controller.workflow_definition_snapshots
                    if item.workflow_definition_id == run.workflow_definition_id
                ),
                None,
            ),
            "stage_instances": [
                item.model_dump(mode="json") for item in stages
            ],
            "artifact_bindings": [
                item.model_dump(mode="json")
                for item in controller.artifact_bindings
                if item.workflow_run_id == run.workflow_run_id
            ],
            "transition_requests": [
                item.model_dump(mode="json")
                for item in controller.transition_requests
                if item.workflow_run_id == run.workflow_run_id
            ],
            "transition_decisions": [
                item.model_dump(mode="json")
                for item in controller.transition_decisions
                if item.workflow_run_id == run.workflow_run_id
            ],
            "dependency_checks": [
                item.model_dump(mode="json")
                for item in controller.dependency_checks
                if item.stage_instance_id in stage_ids
            ],
            "pause_records": [
                item.model_dump(mode="json")
                for item in controller.pause_records
                if item.workflow_run_id == run.workflow_run_id
            ],
            "recovery_holds": [
                item.model_dump(mode="json")
                for item in controller.recovery_holds
                if item.workflow_run_id == run.workflow_run_id
            ],
            "resume_eligibility_reviews": [
                item.model_dump(mode="json")
                for item in controller.resume_eligibility_reviews
                if item.workflow_run_id == run.workflow_run_id
            ],
            "incidents": [
                item.model_dump(mode="json")
                for item in controller.incidents
                if item.workflow_run_id == run.workflow_run_id
            ],
            "human_decisions": [
                item.model_dump(mode="json")
                for item in controller.human_decisions
                if item.workflow_run_id == run.workflow_run_id
            ],
            "events": [
                item.model_dump(mode="json")
                for item in controller.workflow_events
                if item.workflow_run_id == run.workflow_run_id
            ],
            "handoffs": [
                item.model_dump(mode="json")
                for item in controller.handoffs
                if item.workflow_run_id == run.workflow_run_id
            ],
            "summary": controller.controller_summary.model_dump(mode="json"),
            "signal_usage": controller.signal_usage.model_dump(mode="json"),
        }

    def _refresh_summary(
        self,
        controller: BobaWorkflowControllerSetV1,
    ) -> None:
        run_statuses = Counter(item.run_status for item in controller.workflow_runs)
        stage_statuses = Counter(item.status for item in controller.stage_instances)
        decisions = Counter(item.decision for item in controller.transition_decisions)
        current = next(
            (
                item
                for item in reversed(controller.workflow_runs)
                if item.run_status not in _TERMINAL_RUN_STATUSES
            ),
            controller.workflow_runs[-1] if controller.workflow_runs else None,
        )
        current_stage = (
            self._current_stage(controller, current) if current is not None else None
        )
        next_stage = ""
        if current is not None and current.run_status == "active":
            definitions = {
                item.stage_definition_id: item
                for item in self._definitions(controller, current)
            }
            candidates = [
                item
                for item in self._stages(controller, current)
                if item.status == "ready"
            ]
            if candidates:
                candidates.sort(
                    key=lambda item: (
                        list(definitions).index(item.stage_definition_id),
                        item.clip_id or "",
                        item.output_id or "",
                    )
                )
                next_stage = candidates[0].stage_id
        controller.controller_summary = BobaWorkflowControllerSummaryV1(
            workflow_definition_count=len(
                controller.workflow_definition_snapshots
            ),
            total_workflow_runs=len(controller.workflow_runs),
            active_workflow_run_count=run_statuses["active"],
            paused_workflow_run_count=run_statuses["paused"],
            recovery_hold_count=sum(
                1 for item in controller.recovery_holds if not item.released
            ),
            blocked_workflow_run_count=run_statuses["blocked"],
            completed_internal_output_count=sum(
                1 for item in controller.workflow_runs if item.internal_output_complete
            ),
            total_stage_instance_count=len(controller.stage_instances),
            completed_stage_count=(
                stage_statuses["completed"]
                + stage_statuses["completed_with_limitations"]
            ),
            failed_stage_count=stage_statuses["failed"] + stage_statuses["timed_out"],
            blocked_stage_count=(
                stage_statuses["blocked"] + stage_statuses["dependency_blocked"]
            ),
            total_transition_request_count=len(controller.transition_requests),
            allowed_transition_count=(
                decisions["allowed_read_only_transition"]
                + decisions["allowed_exact_internal_transition"]
            ),
            denied_transition_count=sum(
                count
                for value, count in decisions.items()
                if value
                not in {
                    "allowed_read_only_transition",
                    "allowed_exact_internal_transition",
                    "unknown",
                }
            ),
            stale_transition_count=decisions["blocked_stale_state"],
            recovery_transition_count=sum(
                1
                for item in controller.transition_requests
                if item.transition_type in {"enter_recovery", "return_from_recovery"}
            ),
            quality_block_count=decisions["blocked_quality"],
            safety_block_count=decisions["awaiting_safety_decision"],
            rights_block_count=decisions["blocked_rights"],
            concurrency_block_count=decisions["blocked_concurrency"],
            current_workflow_run_id=(
                current.workflow_run_id if current is not None else None
            ),
            current_project_state=(
                current.current_project_state
                if current is not None
                else "uninitialized"
            ),
            current_stage=current_stage.stage_id if current_stage else "",
            next_valid_stage=next_stage,
            current_pause_reason=(
                current.stop_reason
                if current is not None
                and current.run_status in {"paused", "blocked", "recovery"}
                else ""
            ),
            next_required_human_action=(
                "Review the current pause or recovery conditions."
                if current is not None
                and current.run_status in {"paused", "blocked", "recovery"}
                else ""
            ),
            safest_next_action=(
                "Inspect the next exact stage before creating a transition."
                if current is not None and current.run_status == "active"
                else (
                    "Resolve the persisted block; do not resume every stage."
                    if current is not None
                    and current.run_status in {"paused", "blocked", "recovery"}
                    else "No internal workflow action is required."
                )
            ),
            limitations=[
                "Workflow Controller never authorizes upload or publication.",
                "Internal completion is not public production completion.",
            ],
        )

    def _rights_clear(self, project_id: str, explicit: bool | None) -> bool:
        if explicit is not None:
            return explicit
        loader = getattr(self.store, "load_rights_permission_gate", None)
        if not callable(loader):
            return False
        rights = loader(project_id)
        if rights is None:
            return False
        decisions = getattr(rights, "gate_decisions", [])
        return bool(decisions) and all(
            not bool(getattr(item, "blocked", True)) for item in decisions
        )

    @staticmethod
    def _record_payload(
        value: Mapping[str, Any] | BobaContract | None,
    ) -> dict[str, Any]:
        if isinstance(value, BobaContract):
            return value.model_dump(mode="json")
        return dict(value) if isinstance(value, Mapping) else {}

    @classmethod
    def _record_id(
        cls,
        value: Mapping[str, Any] | BobaContract | None,
        *fields: str,
    ) -> str | None:
        payload = cls._record_payload(value)
        for field in fields:
            result = str(payload.get(field) or "")
            if result:
                return result
        return None

    def _approval_valid(
        self,
        approval: Mapping[str, Any] | BobaContract | None,
        *,
        project_id: str,
        workflow_run_id: str,
        stage: BobaWorkflowStageInstanceV1,
        operation_id: str,
    ) -> bool:
        payload = self._record_payload(approval)
        if not payload:
            return False
        expiry = _parse_time(
            str(
                payload.get("approval_expires_at")
                or payload.get("expires_at")
                or ""
            )
            or None
        )
        project = str(
            payload.get("approved_project_id")
            or payload.get("project_id")
            or ""
        )
        run_id = str(
            payload.get("approved_run_id")
            or payload.get("workflow_run_id")
            or ""
        )
        stage_id = str(
            payload.get("stage_instance_id")
            or payload.get("approved_stage_instance_id")
            or ""
        )
        operation = str(
            payload.get("target_operation_id")
            or payload.get("approved_operation_id")
            or payload.get("operation_id")
            or ""
        )
        clip_id = str(payload.get("clip_id") or "")
        output_id = str(payload.get("output_id") or "")
        return bool(
            payload.get("approved", True)
            and payload.get("explicit_confirmation")
            and project == project_id
            and run_id == workflow_run_id
            and stage_id == stage.stage_instance_id
            and operation == operation_id
            and (not clip_id or clip_id == (stage.clip_id or ""))
            and (not output_id or output_id == (stage.output_id or ""))
            and str(payload.get("current_match_status") or "matched")
            == "matched"
            and (expiry is None or expiry > datetime.now(UTC))
        )

    def _safety_valid(
        self,
        safety: BobaSafetyDecisionV1 | Mapping[str, Any] | None,
        *,
        project_id: str,
        request: BobaWorkflowTransitionRequestV1,
    ) -> bool:
        payload = self._record_payload(safety)
        if not payload:
            return False
        expiry = _parse_time(str(payload.get("decision_expires_at") or ""))
        return bool(
            str(payload.get("project_id") or "") == project_id
            and payload.get("decision")
            == "allowed_for_exact_internal_execution"
            and payload.get("decision_valid") is True
            and payload.get("decision_expired") is not True
            and expiry is not None
            and expiry > datetime.now(UTC)
            and str(payload.get("request_digest") or "") == request.request_digest
            and str(payload.get("project_snapshot_digest") or "")
            == request.project_snapshot_digest
            and str(payload.get("allowed_target_module") or "")
            == "workflow_controller"
            and str(payload.get("allowed_target_operation") or "")
            == "advance_exact_internal_stage"
            and payload.get("workflow_resume_authorized") is not True
        )

    def _resume_safety_valid(
        self,
        safety: BobaSafetyDecisionV1 | Mapping[str, Any] | None,
        *,
        project_id: str,
        project_snapshot_digest: str,
        operation_id: str,
    ) -> bool:
        payload = self._record_payload(safety)
        expiry = _parse_time(str(payload.get("decision_expires_at") or ""))
        return bool(
            payload
            and str(payload.get("project_id") or "") == project_id
            and payload.get("decision")
            == "allowed_for_exact_internal_execution"
            and payload.get("decision_valid") is True
            and payload.get("decision_expired") is not True
            and expiry is not None
            and expiry > datetime.now(UTC)
            and str(payload.get("project_snapshot_digest") or "")
            == project_snapshot_digest
            and str(payload.get("allowed_target_module") or "")
            == "workflow_controller"
            and str(payload.get("allowed_target_operation") or "")
            == "advance_exact_internal_stage"
            and operation_id != "workflow_controller.resume"
            and payload.get("workflow_resume_authorized") is not True
        )

    @staticmethod
    def _technical_validation_passed(
        validation: Mapping[str, Any] | BobaContract | None,
        *,
        required: bool,
    ) -> bool:
        if not required and validation is None:
            return True
        payload = (
            validation.model_dump(mode="json")
            if isinstance(validation, BobaContract)
            else dict(validation)
            if isinstance(validation, Mapping)
            else {}
        )
        if not payload:
            return False
        validators = payload.get("validators")
        if isinstance(validators, list):
            for validator in validators:
                if not isinstance(validator, Mapping):
                    return False
                if bool(validator.get("required", True)) and str(
                    validator.get("status") or ""
                ) not in {"passed", "pass"}:
                    return False
                if bool(validator.get("required", True)) and not (
                    validator.get("acceptance_criteria")
                    or payload.get("acceptance_criteria")
                ):
                    return False
        required_unavailable = payload.get("required_unavailable_validators")
        skipped_required = payload.get("skipped_required_validators")
        if isinstance(required_unavailable, list) and required_unavailable:
            return False
        if isinstance(skipped_required, list) and skipped_required:
            return False
        return bool(
            payload.get("passed") is True
            or payload.get("validation_passed") is True
            or str(payload.get("status") or "") in {"passed", "accepted"}
        )

    @staticmethod
    def _quality_ready(
        quality: BobaOutputAcceptanceDecisionV1 | Mapping[str, Any] | None,
        *,
        required: bool,
    ) -> tuple[bool, bool]:
        if not required and quality is None:
            return True, False
        payload = (
            quality.model_dump(mode="json")
            if isinstance(quality, BobaContract)
            else dict(quality)
            if isinstance(quality, Mapping)
            else {}
        )
        decision = str(payload.get("decision") or "")
        if decision not in _ALLOWED_QUALITY_DECISIONS:
            return False, decision == "needs_human_review" or bool(
                payload.get("human_review_required")
            )
        checks_complete = payload.get("required_checks_complete")
        if checks_complete is False:
            return False, bool(payload.get("human_review_required"))
        if payload.get("technical_eligible") is False:
            return False, bool(payload.get("human_review_required"))
        if payload.get("rights_clear_for_processing") is False:
            return False, bool(payload.get("human_review_required"))
        if payload.get("safety_clear_for_processing") is False:
            return False, bool(payload.get("human_review_required"))
        human_required = bool(payload.get("human_review_required")) or (
            decision == "accepted_with_disclosed_limitations"
        )
        return True, human_required

    @classmethod
    def _quality_decision_id(
        cls,
        quality: BobaOutputAcceptanceDecisionV1 | Mapping[str, Any] | None,
    ) -> str | None:
        return cls._record_id(
            quality,
            "acceptance_decision_id",
            "quality_decision_id",
        )

    def _human_decision_valid(
        self,
        human: BobaWorkflowHumanDecisionV1 | Mapping[str, Any] | None,
        *,
        project_id: str,
        workflow_run_id: str,
        stage: BobaWorkflowStageInstanceV1,
        request: BobaWorkflowTransitionRequestV1 | None,
    ) -> bool:
        payload = self._record_payload(human)
        if not payload:
            return False
        expiry = _parse_time(str(payload.get("expires_at") or "") or None)
        accepted = str(payload.get("decision") or "").casefold() in {
            "approved",
            "accepted",
            "confirmed",
            "continue_exact_stage",
            "accept_with_limitations",
        }
        return bool(
            str(payload.get("project_id") or "") == project_id
            and str(payload.get("workflow_run_id") or "") == workflow_run_id
            and (
                not payload.get("stage_instance_id")
                or str(payload.get("stage_instance_id"))
                == stage.stage_instance_id
            )
            and (
                request is None
                or not payload.get("transition_request_id")
                or str(payload.get("transition_request_id"))
                == request.transition_request_id
            )
            and str(payload.get("project_snapshot_digest") or "")
            == stage.project_snapshot_digest
            and payload.get("explicit_confirmation") is True
            and accepted
            and (expiry is None or expiry > datetime.now(UTC))
            and payload.get("upload_authorized") is not True
            and payload.get("publication_authorized") is not True
        )

    @staticmethod
    def _stage_state_for_decision(
        decision: BobaWorkflowTransitionDecisionValueV1,
    ) -> BobaWorkflowStageStateV1:
        if decision == "awaiting_approval":
            return "awaiting_approval"
        if decision == "awaiting_safety_decision":
            return "awaiting_safety_decision"
        if decision == "recovery_required":
            return "recovery_required"
        if decision in {
            "blocked_dependency",
            "blocked_checkpoint",
            "blocked_validation",
            "blocked_quality",
            "blocked_rights",
            "blocked_stale_state",
            "blocked_concurrency",
            "blocked_idempotency",
            "invalid_transition",
            "expired",
            "denied",
        }:
            return "blocked"
        return "dependency_blocked"

    @staticmethod
    def _pause_category_for_decision(
        decision: BobaWorkflowTransitionDecisionValueV1,
    ) -> BobaWorkflowPauseCategoryV1:
        mapping: dict[
            BobaWorkflowTransitionDecisionValueV1,
            BobaWorkflowPauseCategoryV1,
        ] = {
            "blocked_rights": "rights_block",
            "awaiting_approval": "approval_required",
            "awaiting_safety_decision": "safety_block",
            "blocked_checkpoint": "checkpoint_issue",
            "blocked_validation": "validation_failure",
            "blocked_quality": "quality_rejection",
            "blocked_stale_state": "stale_state",
            "blocked_concurrency": "concurrency_conflict",
            "recovery_required": "recovery_required",
        }
        return mapping.get(decision, "uncertain_state")

    def _mark_internal_output_complete(
        self,
        controller: BobaWorkflowControllerSetV1,
        run: BobaWorkflowRunV1,
        completion_stage: BobaWorkflowStageInstanceV1,
    ) -> None:
        if run.internal_output_complete:
            return
        stages = self._stages(controller, run)
        definitions = {
            item.stage_definition_id: item for item in self._definitions(controller, run)
        }
        required_incomplete = [
            item
            for item in stages
            if definitions[item.stage_definition_id].stage_id
            not in {"human_review", "internal_output_completion"}
            and item.status not in {"completed", "completed_with_limitations"}
        ]
        if required_incomplete:
            raise ValidationError(
                "Internal output completion requires every selected required stage.",
                details={
                    "stage_instance_ids": [
                        item.stage_instance_id for item in required_incomplete
                    ]
                },
            )
        output_stages = [item for item in stages if item.output_id]
        output_ids = {item.output_id for item in output_stages if item.output_id}
        for output_id in output_ids:
            output_artifacts = [
                item
                for item in controller.artifact_bindings
                if item.workflow_run_id == run.workflow_run_id
                and item.output_id == output_id
            ]
            artifact_types = {item.artifact_type for item in output_artifacts}
            missing = {
                "rendered_mp4",
                "render_manifest",
                "technical_validation",
                "output_quality_decision",
            } - artifact_types
            if missing:
                raise ValidationError(
                    "Internal output completion lacks required output evidence.",
                    details={
                        "output_id": output_id,
                        "missing_artifact_types": sorted(missing),
                    },
                )
            if any(
                item.stale or item.malformed or not item.available
                for item in output_artifacts
            ):
                raise ValidationError("Internal output artifacts are not current.")
        if any(
            not item.released and item.workflow_run_id == run.workflow_run_id
            for item in controller.recovery_holds
        ):
            raise ValidationError(
                "Internal output completion is blocked by an active Recovery Hold."
            )
        unresolved_incidents = [
            incident
            for incident in controller.incidents
            if incident.workflow_run_id == run.workflow_run_id
            and (
                incident.stage_instance_id is None
                or self._stage(controller, incident.stage_instance_id).status
                not in {"completed", "completed_with_limitations", "superseded"}
            )
        ]
        if unresolved_incidents:
            raise ValidationError(
                "Internal output completion is blocked by unresolved incidents."
            )
        latest_decision = next(
            (
                item
                for item in reversed(controller.transition_decisions)
                if item.transition_decision_id
                == completion_stage.transition_decision_id
            ),
            None,
        )
        if latest_decision is not None and not (
            latest_decision.rights_clear
            and latest_decision.safety_decision_valid
            and latest_decision.validation_ready
            and latest_decision.quality_ready
        ):
            raise ValidationError(
                "Internal completion gate evidence is incomplete."
            )
        completion_stage.status = "completed"
        completion_stage.completed_at = completion_stage.completed_at or now_iso()
        run.internal_output_complete = True
        run.run_status = "completed"
        run.current_project_state = "internal_output_complete"
        run.completed_at = now_iso()
        run.updated_at = now_iso()
        run.stop_reason = ""
        run.current_stage_instance_ids = []
        run.upload_authorized = False
        run.publication_authorized = False
        self._append_event(
            controller,
            run,
            event_type="internal_output_completed",
            stage=completion_stage,
            operation_id="workflow_controller.complete_internal_output",
            technical_message="All required internal completion gates passed.",
            easy_message=(
                "All required internal stages finished. Clips remain local and "
                "were not uploaded or published."
            ),
            confirmed_fact="internal_output_complete=true",
            evidence_reference_ids=completion_stage.output_artifact_binding_ids,
        )


__all__ = [
    "BobaWorkflowArtifactBindingV1",
    "BobaWorkflowControllerSetV1",
    "BobaWorkflowControllerSignalUsageV1",
    "BobaWorkflowControllerSummaryV1",
    "BobaWorkflowControllerV1",
    "BobaWorkflowDefinitionSnapshotV1",
    "BobaWorkflowDependencyCheckV1",
    "BobaWorkflowEventV1",
    "BobaWorkflowExecutionLeaseV1",
    "BobaWorkflowHandoffV1",
    "BobaWorkflowHumanDecisionV1",
    "BobaWorkflowIncidentV1",
    "BobaWorkflowPauseRecordV1",
    "BobaWorkflowRecoveryHoldV1",
    "BobaWorkflowResumeEligibilityReviewV1",
    "BobaWorkflowRunV1",
    "BobaWorkflowStageDefinitionV1",
    "BobaWorkflowStageInstanceV1",
    "BobaWorkflowTransitionDecisionV1",
    "BobaWorkflowTransitionRequestV1",
    "build_workflow_stage_registry",
    "calculate_workflow_idempotency_key",
    "calculate_workflow_request_digest",
    "capture_workflow_project_snapshot",
    "sanitize_workflow_export",
    "validate_workflow_graph",
]

"""Persisted, bounded coordination for BOBA's self-healing modules.

Autopilot Controller V1 coordinates typed BOBA operations. It never runs a
command, Git, FFmpeg, a network request, or a repair directly.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import Field

from olympus.boba.code_surgeon import BobaCodeApprovalRecordV1
from olympus.boba.code_surgeon import verify_approval as verify_code_approval
from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.tool_recovery import (
    BobaToolRecoveryApprovalV1,
    verify_recovery_approval,
)
from olympus.platform.errors import ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore

BobaAutopilotStateV1 = Literal[
    "created",
    "inspecting_project",
    "rights_review_required",
    "safety_review_required",
    "observer_required",
    "diagnosis_required",
    "root_cause_analysis_required",
    "repair_planning_required",
    "awaiting_repair_decision",
    "awaiting_execution_approval",
    "code_repair_ready",
    "tool_recovery_ready",
    "checkpoint_recovery_required",
    "approved_execution_pending",
    "execution_running",
    "execution_failed",
    "rollback_required",
    "rollback_running",
    "rollback_failed",
    "technical_validation_required",
    "output_quality_review_required",
    "human_quality_review_required",
    "repair_replanning_required",
    "root_cause_reanalysis_required",
    "awaiting_safety_gate",
    "ready_for_workflow_controller",
    "completed_internal_cycle",
    "paused",
    "cancelled",
    "blocked",
    "failed",
    "unknown",
]
BobaAutopilotRunStatusV1 = Literal[
    "created",
    "active",
    "awaiting_approval",
    "awaiting_human_review",
    "paused",
    "blocked",
    "completed_internal_cycle",
    "cancelled",
    "failed",
    "unknown",
]
BobaAutopilotControlModeV1 = Literal[
    "advisory_only",
    "safe_read_only_automatic",
    "approved_execution_coordination",
    "manual_step",
    "unknown",
]
BobaAutopilotTriggerV1 = Literal[
    "manual",
    "observer_finding",
    "error_doctor_case",
    "tool_failure",
    "rendering_failure",
    "validation_failure",
    "quality_rejection",
    "checkpoint_issue",
    "code_repair_request",
    "unknown",
]
BobaAutopilotTransitionStatusV1 = Literal[
    "planned",
    "allowed",
    "blocked",
    "applied",
    "rejected",
    "invalid",
    "superseded",
    "unknown",
]
BobaAutopilotActionTypeV1 = Literal[
    "inspect_project",
    "load_artifacts",
    "generate_observer",
    "generate_error_doctor",
    "generate_root_cause_analyzer",
    "generate_repair_planner",
    "request_execution_approval",
    "invoke_code_surgeon",
    "invoke_tool_recovery",
    "invoke_tool_recovery_rollback",
    "invoke_output_quality_review",
    "prepare_checkpoint_handoff",
    "prepare_validator_handoff",
    "prepare_safety_handoff",
    "prepare_workflow_handoff",
    "pause_controller",
    "cancel_controller",
    "stop_controller",
    "human_review",
    "unknown",
]
BobaAutopilotActionClassV1 = Literal[
    "automatic_read_only",
    "approval_required_read_only",
    "approval_required_execution",
    "future_gated",
    "prohibited",
    "unknown",
]
BobaAutopilotActionStatusV1 = Literal[
    "planned",
    "awaiting_approval",
    "ready",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "skipped",
    "blocked",
    "cancelled",
    "rolled_back",
    "superseded",
    "unknown",
]
BobaAutopilotInvocationModeV1 = Literal[
    "read_only_generation",
    "read_only_inspection",
    "approved_execution",
    "approved_rollback",
    "advisory_handoff",
    "unknown",
]
BobaAutopilotCheckpointStatusV1 = Literal[
    "not_required",
    "available",
    "valid",
    "invalid",
    "missing",
    "stale",
    "corrupt",
    "unverified",
    "unknown",
]
BobaAutopilotDecisionTypeV1 = Literal[
    "next_stage",
    "action_selection",
    "approval_requirement",
    "pause",
    "stop",
    "retry",
    "replan",
    "reanalyze",
    "rollback",
    "quality_routing",
    "handoff",
    "unknown",
]
BobaAutopilotIncidentTypeV1 = Literal[
    "module_failure",
    "module_timeout",
    "stale_artifact",
    "missing_artifact",
    "malformed_artifact",
    "approval_mismatch",
    "approval_expired",
    "budget_exhausted",
    "repeated_failure",
    "loop_detected",
    "checkpoint_invalid",
    "rollback_failure",
    "quality_rejection",
    "rights_block",
    "safety_block",
    "conflicting_evidence",
    "concurrency_conflict",
    "state_transition_error",
    "unknown",
]
BobaAutopilotEventTypeV1 = Literal[
    "run_created",
    "state_changed",
    "module_started",
    "module_completed",
    "module_failed",
    "approval_required",
    "approval_invalidated",
    "recovery_started",
    "recovery_completed",
    "recovery_failed",
    "rollback_started",
    "rollback_completed",
    "quality_review_started",
    "quality_review_completed",
    "quality_rejected",
    "rights_blocked",
    "safety_blocked",
    "safety_review_started",
    "safety_allowed",
    "safety_denied",
    "safety_human_review_required",
    "safety_more_evidence_required",
    "safety_decision_expired",
    "safety_decision_invalidated",
    "budget_warning",
    "budget_exhausted",
    "controller_paused",
    "controller_cancelled",
    "internal_cycle_completed",
    "human_review_required",
    "unknown",
]
BobaAutopilotHandoffTargetV1 = Literal[
    "observer",
    "error_doctor",
    "root_cause_analyzer",
    "repair_planner",
    "code_surgeon",
    "tool_recovery_brain",
    "output_quality_reviewer",
    "checkpoint_recovery_manager",
    "validator_runner",
    "safety_gate",
    "workflow_controller",
    "final_decision_bus",
    "rights_permission_gate",
    "live_companion",
    "human_operator",
    "unknown",
]
BobaAutopilotActionTargetV1 = Literal[
    "autopilot_controller",
    "observer",
    "error_doctor",
    "root_cause_analyzer",
    "repair_planner",
    "code_surgeon",
    "tool_recovery_brain",
    "output_quality_reviewer",
    "checkpoint_recovery_manager",
    "validator_runner",
    "safety_gate",
    "workflow_controller",
    "final_decision_bus",
    "rights_permission_gate",
    "live_companion",
    "human_operator",
    "unknown",
]
BobaAutopilotSeverityV1 = Literal[
    "info",
    "warning",
    "high",
    "critical",
    "unknown",
]
BobaAutopilotLockModeV1 = Literal[
    "safe_read_only_automatic",
    "approved_execution_coordination",
    "manual_step",
    "unknown",
]

JsonObject: TypeAlias = dict[str, Any]
AutopilotContextProvider: TypeAlias = Callable[[str], Awaitable[Mapping[str, Any]]]
AutopilotModuleInvoker: TypeAlias = Callable[
    [str, str, Mapping[str, Any]],
    Awaitable[Mapping[str, Any]],
]

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,180}$")
_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"']+")
_POSIX_PRIVATE_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users|root)/[^\s\"']+")
_SECRET_KEY = re.compile(
    r"(?i)(?:secret|token|password|credential|cookie|authorization|api[_-]?key)"
)
_TERMINAL_STATES: frozenset[BobaAutopilotStateV1] = frozenset(
    {"completed_internal_cycle", "cancelled", "blocked", "failed"}
)
_ACTIVE_RUN_STATUSES: frozenset[BobaAutopilotRunStatusV1] = frozenset(
    {"created", "active", "awaiting_approval", "awaiting_human_review", "paused"}
)
_RIGHTS_CLEAR = frozenset(
    {
        "owned",
        "licensed",
        "permission_granted",
        "approved",
        "cleared",
        "confirmed",
        "ready_for_human_review",
        "ready_for_processing",
    }
)
_RIGHTS_BLOCKED = frozenset(
    {
        "blocked",
        "permission_denied",
        "not_allowed",
        "do_not_process",
        "needs_permission",
        "needs_rights_review",
        "insufficient_information",
        "unknown",
    }
)
_SAFETY_CLEAR = frozenset(
    {
        "safe",
        "approved",
        "cleared",
        "passed",
        "eligible",
        "ready_for_processing",
        "clear_for_local_analysis",
    }
)
_SAFETY_BLOCKED = frozenset(
    {"blocked", "unsafe", "rejected", "do_not_process", "denied"}
)


def _text(value: Any, *, maximum: int = 900) -> str:
    compact = " ".join(str(value or "").split())
    compact = _WINDOWS_PATH.sub("[private-path]", compact)
    compact = _POSIX_PRIVATE_PATH.sub("[private-path]", compact)
    return compact[:maximum]


def _unique(
    values: Sequence[Any],
    *,
    limit: int = 64,
    maximum: int = 900,
) -> list[str]:
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


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 7:
        return "[bounded]"
    if isinstance(value, BobaContract):
        return _json_safe(value.model_dump(mode="json"), depth=depth + 1)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:128]:
            safe_key = _text(key, maximum=160)
            result[safe_key] = (
                "[redacted]"
                if _SECRET_KEY.search(safe_key)
                else _json_safe(item, depth=depth + 1)
            )
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:256]]
    if isinstance(value, Path):
        return _text(value.as_posix(), maximum=500)
    if isinstance(value, str):
        return _text(value, maximum=2_000)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _text(value, maximum=500)


def _canonical(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{_digest([str(part) for part in parts])[:24]}"


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


def _elapsed_seconds(started_at: str, ended_at: str | None = None) -> float:
    start = _parse_time(started_at)
    end = _parse_time(ended_at) or datetime.now(UTC)
    if start is None:
        return 0.0
    return round(max(0.0, (end - start).total_seconds()), 4)


class BobaAutopilotProjectLockV1(BobaContract):
    schema_version: Literal["boba_autopilot_lock_v1"] = "boba_autopilot_lock_v1"
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=180)
    acquired_at: str = Field(default_factory=now_iso, max_length=80)
    refreshed_at: str = Field(default_factory=now_iso, max_length=80)
    expires_at: str = Field(min_length=1, max_length=80)
    owner_identifier: str = Field(min_length=1, max_length=160)
    mode: BobaAutopilotLockModeV1
    stale: bool = False
    release_required: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaAutopilotRunV1(BobaContract):
    run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    started_at: str | None = Field(default=None, max_length=80)
    updated_at: str = Field(default_factory=now_iso, max_length=80)
    completed_at: str | None = Field(default=None, max_length=80)
    current_state: BobaAutopilotStateV1 = "created"
    previous_state: BobaAutopilotStateV1 = "unknown"
    run_status: BobaAutopilotRunStatusV1 = "created"
    control_mode: BobaAutopilotControlModeV1 = "safe_read_only_automatic"
    trigger: BobaAutopilotTriggerV1 = "manual"
    source_event_id: str | None = Field(default=None, max_length=180)
    project_snapshot_id: str = Field(default="", max_length=180)
    rights_status: str = Field(default="unknown", max_length=80)
    safety_status: str = Field(default="unknown", max_length=80)
    active_action_id: str | None = Field(default=None, max_length=180)
    active_module_invocation_id: str | None = Field(default=None, max_length=180)
    pending_approval_ids: list[str] = Field(default_factory=list, max_length=64)
    completed_action_ids: list[str] = Field(default_factory=list, max_length=256)
    failed_action_ids: list[str] = Field(default_factory=list, max_length=256)
    skipped_action_ids: list[str] = Field(default_factory=list, max_length=256)
    budget_id: str = Field(min_length=1, max_length=180)
    checkpoint_requirement_id: str | None = Field(default=None, max_length=180)
    decision_ids: list[str] = Field(default_factory=list, max_length=256)
    incident_ids: list[str] = Field(default_factory=list, max_length=256)
    handoff_ids: list[str] = Field(default_factory=list, max_length=256)
    live_event_ids: list[str] = Field(default_factory=list, max_length=2_000)
    stop_reason: str | None = Field(default=None, max_length=900)
    human_review_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaAutopilotProjectSnapshotV1(BobaContract):
    project_snapshot_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    captured_at: str = Field(default_factory=now_iso, max_length=80)
    source_artifact_versions: dict[str, str] = Field(default_factory=dict, max_length=64)
    module_artifact_states: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        max_length=64,
    )
    current_workflow_stage: str = Field(default="unknown", max_length=160)
    accepted_output_ids: list[str] = Field(default_factory=list, max_length=128)
    source_media_references: list[str] = Field(default_factory=list, max_length=32)
    source_media_read_only: bool = True
    rights_status: str = Field(default="unknown", max_length=80)
    safety_status: str = Field(default="unknown", max_length=80)
    active_external_operations: list[str] = Field(default_factory=list, max_length=32)
    active_recovery_runs: list[str] = Field(default_factory=list, max_length=32)
    active_code_surgeon_runs: list[str] = Field(default_factory=list, max_length=32)
    stale_artifact_ids: list[str] = Field(default_factory=list, max_length=64)
    missing_required_artifact_ids: list[str] = Field(default_factory=list, max_length=64)
    conflicting_artifact_ids: list[str] = Field(default_factory=list, max_length=64)
    snapshot_sha256: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaAutopilotStateTransitionV1(BobaContract):
    transition_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    sequence: int = Field(ge=1)
    from_state: BobaAutopilotStateV1
    to_state: BobaAutopilotStateV1
    transition_reason: str = Field(min_length=1, max_length=900)
    triggering_action_id: str | None = Field(default=None, max_length=180)
    triggering_module: str = Field(default="", max_length=160)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    preconditions: list[str] = Field(default_factory=list, max_length=32)
    preconditions_passed: bool = False
    blocked_preconditions: list[str] = Field(default_factory=list, max_length=32)
    approval_required: bool = False
    safety_gate_required: bool = False
    rights_gate_required: bool = False
    human_review_required: bool = False
    transition_status: BobaAutopilotTransitionStatusV1 = "planned"
    created_at: str = Field(default_factory=now_iso, max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotActionV1(BobaContract):
    action_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    action_type: BobaAutopilotActionTypeV1
    action_class: BobaAutopilotActionClassV1
    target_module: BobaAutopilotActionTargetV1
    target_operation: str = Field(min_length=1, max_length=160)
    source_handoff_id: str | None = Field(default=None, max_length=180)
    description: str = Field(min_length=1, max_length=700)
    rationale: str = Field(min_length=1, max_length=900)
    input_artifact_ids: list[str] = Field(default_factory=list, max_length=64)
    expected_output_artifact_type: str = Field(default="", max_length=180)
    prerequisites: list[str] = Field(default_factory=list, max_length=32)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=32)
    planned_snapshot_sha256: str = Field(default="", max_length=64)
    approval_binding_id: str | None = Field(default=None, max_length=180)
    safety_decision_id: str | None = Field(default=None, max_length=180)
    budget_cost: dict[str, float] = Field(default_factory=dict, max_length=16)
    risk_level: str = Field(default="low", max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=180)
    maximum_attempts: int = Field(default=1, ge=1, le=4)
    timeout_seconds: int = Field(default=300, ge=1, le=3_600)
    status: BobaAutopilotActionStatusV1 = "planned"
    started_at: str | None = Field(default=None, max_length=80)
    completed_at: str | None = Field(default=None, max_length=80)
    result_reference: str | None = Field(default=None, max_length=500)
    failure_summary: str | None = Field(default=None, max_length=1_200)
    next_action_on_success: str = Field(default="", max_length=700)
    next_action_on_failure: str = Field(default="", max_length=700)
    stop_conditions: list[str] = Field(default_factory=list, max_length=32)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=32)
    human_approval_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


AutopilotSafetyDecisionValidator: TypeAlias = Callable[
    [
        str,
        str,
        BobaAutopilotActionV1,
        str,
        Mapping[str, Any] | BobaContract,
    ],
    Mapping[str, Any] | BobaContract,
]


class BobaAutopilotModuleInvocationV1(BobaContract):
    module_invocation_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    action_id: str = Field(min_length=1, max_length=180)
    module_name: str = Field(min_length=1, max_length=160)
    operation_name: str = Field(min_length=1, max_length=160)
    invocation_mode: BobaAutopilotInvocationModeV1
    input_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    approval_verified: bool = False
    independently_revalidated_by_target: bool = False
    invocation_started_at: str = Field(default_factory=now_iso, max_length=80)
    invocation_completed_at: str | None = Field(default=None, max_length=80)
    status: BobaAutopilotActionStatusV1 = "running"
    output_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    bounded_result_summary: str = Field(default="", max_length=1_200)
    failure_class: str = Field(default="", max_length=160)
    failure_summary: str = Field(default="", max_length=1_200)
    timeout_occurred: bool = False
    retryable: bool = False
    changed_project_state: bool = False
    source_media_untouched: bool = True
    accepted_outputs_untouched: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotApprovalBindingV1(BobaContract):
    approval_binding_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    action_id: str = Field(min_length=1, max_length=180)
    target_module: str = Field(min_length=1, max_length=160)
    target_plan_id: str = Field(default="", max_length=180)
    target_strategy_id: str = Field(default="", max_length=180)
    target_artifact_digest: str = Field(default="", max_length=128)
    approval_record_id: str = Field(min_length=1, max_length=180)
    approval_type: str = Field(min_length=1, max_length=160)
    approved: bool = False
    approved_at: str | None = Field(default=None, max_length=80)
    approval_expires_at: str | None = Field(default=None, max_length=80)
    approved_by: str = Field(default="", max_length=160)
    approved_scope: list[str] = Field(default_factory=list, max_length=64)
    approved_parameters_digest: str = Field(default="", max_length=128)
    current_parameters_digest: str = Field(default="", max_length=128)
    exact_match: bool = False
    invalidation_reason: str | None = Field(default=None, max_length=900)
    explicit_confirmation: bool = False
    human_approval_required: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotRecoveryBudgetV1(BobaContract):
    budget_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    maximum_total_actions: int = Field(default=30, ge=1, le=30)
    maximum_execution_actions: int = Field(default=4, ge=0, le=4)
    maximum_module_invocations: int = Field(default=24, ge=1, le=24)
    maximum_total_retries: int = Field(default=4, ge=0, le=4)
    maximum_identical_failure_retries: int = Field(default=1, ge=0, le=1)
    maximum_total_duration_seconds: int = Field(default=3_600, ge=1, le=3_600)
    maximum_execution_duration_seconds: int = Field(default=1_800, ge=0, le=1_800)
    maximum_risk_score: float = Field(default=100.0, ge=0.0, le=100.0)
    maximum_code_repair_attempts: int = Field(default=2, ge=0, le=2)
    maximum_tool_recovery_attempts: int = Field(default=4, ge=0, le=4)
    maximum_quality_review_attempts: int = Field(default=3, ge=0, le=3)
    maximum_replanning_cycles: int = Field(default=2, ge=0, le=2)
    maximum_root_cause_reanalysis_cycles: int = Field(default=2, ge=0, le=2)
    automatic_read_only_allowed: bool = True
    execution_coordination_allowed: bool = False
    budget_reset_requires_human_approval: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotBudgetUsageV1(BobaContract):
    budget_usage_id: str = Field(min_length=1, max_length=180)
    budget_id: str = Field(min_length=1, max_length=180)
    actions_used: int = Field(default=0, ge=0)
    execution_actions_used: int = Field(default=0, ge=0)
    module_invocations_used: int = Field(default=0, ge=0)
    retries_used: int = Field(default=0, ge=0)
    identical_failure_retries_used: int = Field(default=0, ge=0)
    total_duration_seconds: float = Field(default=0.0, ge=0.0)
    execution_duration_seconds: float = Field(default=0.0, ge=0.0)
    current_risk_score: float = Field(default=0.0, ge=0.0)
    code_repair_attempts_used: int = Field(default=0, ge=0)
    tool_recovery_attempts_used: int = Field(default=0, ge=0)
    quality_review_attempts_used: int = Field(default=0, ge=0)
    replanning_cycles_used: int = Field(default=0, ge=0)
    root_cause_reanalysis_cycles_used: int = Field(default=0, ge=0)
    exhausted_dimensions: list[str] = Field(default_factory=list, max_length=32)
    budget_exhausted: bool = False
    next_action_allowed: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotCheckpointRequirementV1(BobaContract):
    checkpoint_requirement_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    required: bool = False
    requirement_source: str = Field(default="", max_length=180)
    checkpoint_reference: str = Field(default="", max_length=500)
    checkpoint_status: BobaAutopilotCheckpointStatusV1 = "not_required"
    checkpoint_validated: bool = False
    checkpoint_artifact_digest: str = Field(default="", max_length=128)
    state_preservation_required: list[str] = Field(default_factory=list, max_length=64)
    source_media_protected: bool = True
    accepted_outputs_protected: bool = True
    rollback_plan_reference: str = Field(default="", max_length=180)
    rollback_ready: bool = False
    blocks_execution: bool = False
    human_review_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotDecisionV1(BobaContract):
    decision_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    decision_type: BobaAutopilotDecisionTypeV1
    decision: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=900)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    alternatives_considered: list[str] = Field(default_factory=list, max_length=32)
    rejected_alternatives: list[str] = Field(default_factory=list, max_length=32)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_level: str = Field(default="unknown", max_length=80)
    rights_clear: bool = False
    safety_clear: bool = False
    approval_clear: bool = False
    budget_clear: bool = False
    checkpoint_clear: bool = False
    quality_clear: bool = False
    human_review_required: bool = False
    next_state: BobaAutopilotStateV1 = "unknown"
    next_action_id: str | None = Field(default=None, max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    reviewer_identity_hash: str = Field(default="", max_length=128)
    source: str = Field(default="controller", max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotIncidentV1(BobaContract):
    incident_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    action_id: str | None = Field(default=None, max_length=180)
    module_invocation_id: str | None = Field(default=None, max_length=180)
    incident_type: BobaAutopilotIncidentTypeV1
    severity: BobaAutopilotSeverityV1 = "warning"
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=1_200)
    observed_at: str = Field(default_factory=now_iso, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    repeated_fingerprint: str = Field(default="", max_length=128)
    occurrence_count: int = Field(default=1, ge=1)
    loop_risk: bool = False
    project_state_uncertain: bool = False
    source_media_risk: bool = False
    accepted_output_risk: bool = False
    immediate_controller_action: str = Field(default="", max_length=700)
    escalation_target: str = Field(default="human_operator", max_length=160)
    human_review_required: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    sequence: int = Field(ge=1)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    event_type: BobaAutopilotEventTypeV1
    severity: BobaAutopilotSeverityV1 = "info"
    state: BobaAutopilotStateV1
    action_id: str | None = Field(default=None, max_length=180)
    module_name: str = Field(default="", max_length=160)
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
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=180)
    run_id: str = Field(min_length=1, max_length=180)
    source_action_id: str | None = Field(default=None, max_length=180)
    source_decision_id: str | None = Field(default=None, max_length=180)
    target_module: BobaAutopilotHandoffTargetV1
    reason: str = Field(min_length=1, max_length=700)
    current_state: BobaAutopilotStateV1
    required_inputs: list[str] = Field(default_factory=list, max_length=32)
    blocking_conditions: list[str] = Field(default_factory=list, max_length=32)
    satisfied_conditions: list[str] = Field(default_factory=list, max_length=32)
    failed_conditions: list[str] = Field(default_factory=list, max_length=32)
    budget_status: str = Field(default="unknown", max_length=80)
    checkpoint_status: str = Field(default="unknown", max_length=80)
    quality_status: str = Field(default="unknown", max_length=80)
    rights_status: str = Field(default="unknown", max_length=80)
    safety_status: str = Field(default="unknown", max_length=80)
    allowed_actions: list[str] = Field(default_factory=list, max_length=32)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: bool = False
    human_approval_required: bool = True
    priority: str = Field(default="medium", max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotControllerSummaryV1(BobaContract):
    total_runs: int = Field(default=0, ge=0)
    active_run_count: int = Field(default=0, ge=0)
    paused_run_count: int = Field(default=0, ge=0)
    blocked_run_count: int = Field(default=0, ge=0)
    completed_internal_cycle_count: int = Field(default=0, ge=0)
    failed_run_count: int = Field(default=0, ge=0)
    total_state_transitions: int = Field(default=0, ge=0)
    automatic_read_only_action_count: int = Field(default=0, ge=0)
    approved_execution_action_count: int = Field(default=0, ge=0)
    approval_wait_count: int = Field(default=0, ge=0)
    approval_mismatch_count: int = Field(default=0, ge=0)
    budget_exhaustion_count: int = Field(default=0, ge=0)
    loop_prevention_count: int = Field(default=0, ge=0)
    rollback_count: int = Field(default=0, ge=0)
    quality_rejection_count: int = Field(default=0, ge=0)
    rights_block_count: int = Field(default=0, ge=0)
    safety_block_count: int = Field(default=0, ge=0)
    current_run_id: str | None = Field(default=None, max_length=180)
    current_state: BobaAutopilotStateV1 = "unknown"
    current_action: str = Field(default="", max_length=700)
    next_required_human_action: str = Field(default="", max_length=700)
    safest_next_action: str = Field(default="", max_length=700)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotControllerSignalUsageV1(BobaContract):
    observer_used: bool = False
    error_doctor_used: bool = False
    root_cause_analyzer_used: bool = False
    repair_planner_used: bool = False
    code_surgeon_used: bool = False
    tool_recovery_used: bool = False
    output_quality_reviewer_used: bool = False
    rights_gate_used: bool = False
    safety_gate_used: bool = False
    target_module_approval_used: bool = False
    project_snapshot_used: bool = False
    recovery_budget_used: bool = False
    checkpoint_reference_used: bool = False
    local_event_stream_used: bool = False
    direct_command_execution_used: Literal[False] = False
    direct_git_execution_used: Literal[False] = False
    direct_ffmpeg_execution_used: Literal[False] = False
    code_modified_directly: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_outputs_modified: Literal[False] = False
    workflow_resume_used: Literal[False] = False
    checkpoint_restore_used: Literal[False] = False
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
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaAutopilotControllerSetV1(BobaContract):
    schema_version: Literal["boba_autopilot_controller_v1"] = (
        "boba_autopilot_controller_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    active_run_id: str | None = Field(default=None, max_length=180)
    runs: list[BobaAutopilotRunV1] = Field(default_factory=list, max_length=128)
    project_snapshots: list[BobaAutopilotProjectSnapshotV1] = Field(
        default_factory=list,
        max_length=512,
    )
    state_transitions: list[BobaAutopilotStateTransitionV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    planned_actions: list[BobaAutopilotActionV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    module_invocations: list[BobaAutopilotModuleInvocationV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    approval_bindings: list[BobaAutopilotApprovalBindingV1] = Field(
        default_factory=list,
        max_length=512,
    )
    recovery_budgets: list[BobaAutopilotRecoveryBudgetV1] = Field(
        default_factory=list,
        max_length=256,
    )
    budget_usages: list[BobaAutopilotBudgetUsageV1] = Field(
        default_factory=list,
        max_length=256,
    )
    checkpoint_requirements: list[BobaAutopilotCheckpointRequirementV1] = Field(
        default_factory=list,
        max_length=512,
    )
    incidents: list[BobaAutopilotIncidentV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    decisions: list[BobaAutopilotDecisionV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    event_stream: list[BobaAutopilotEventV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    handoffs: list[BobaAutopilotHandoffV1] = Field(
        default_factory=list,
        max_length=1_000,
    )
    lock_metadata: BobaAutopilotProjectLockV1 | None = None
    controller_summary: BobaAutopilotControllerSummaryV1 = Field(
        default_factory=BobaAutopilotControllerSummaryV1
    )
    signal_usage: BobaAutopilotControllerSignalUsageV1 = Field(
        default_factory=BobaAutopilotControllerSignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


DEFAULT_AUTOPILOT_BUDGET_LIMITS: dict[str, int | float | bool] = {
    "maximum_total_actions": 30,
    "maximum_execution_actions": 4,
    "maximum_module_invocations": 24,
    "maximum_total_retries": 4,
    "maximum_identical_failure_retries": 1,
    "maximum_total_duration_seconds": 3_600,
    "maximum_execution_duration_seconds": 1_800,
    "maximum_risk_score": 100.0,
    "maximum_code_repair_attempts": 2,
    "maximum_tool_recovery_attempts": 4,
    "maximum_quality_review_attempts": 3,
    "maximum_replanning_cycles": 2,
    "maximum_root_cause_reanalysis_cycles": 2,
    "automatic_read_only_allowed": True,
    "execution_coordination_allowed": False,
    "budget_reset_requires_human_approval": True,
}

VALID_AUTOPILOT_TRANSITIONS: dict[
    BobaAutopilotStateV1,
    frozenset[BobaAutopilotStateV1],
] = {
    "created": frozenset({"inspecting_project", "paused", "cancelled", "failed"}),
    "inspecting_project": frozenset(
        {
            "rights_review_required",
            "safety_review_required",
            "observer_required",
            "diagnosis_required",
            "root_cause_analysis_required",
            "repair_planning_required",
            "awaiting_repair_decision",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "rights_review_required": frozenset(
        {"inspecting_project", "paused", "cancelled", "blocked", "failed"}
    ),
    "safety_review_required": frozenset(
        {"inspecting_project", "paused", "cancelled", "blocked", "failed"}
    ),
    "observer_required": frozenset(
        {"diagnosis_required", "paused", "cancelled", "blocked", "failed"}
    ),
    "diagnosis_required": frozenset(
        {
            "root_cause_analysis_required",
            "human_quality_review_required",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "root_cause_analysis_required": frozenset(
        {
            "repair_planning_required",
            "human_quality_review_required",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "repair_planning_required": frozenset(
        {"awaiting_repair_decision", "paused", "cancelled", "blocked", "failed"}
    ),
    "awaiting_repair_decision": frozenset(
        {
            "awaiting_execution_approval",
            "checkpoint_recovery_required",
            "code_repair_ready",
            "tool_recovery_ready",
            "technical_validation_required",
            "output_quality_review_required",
            "human_quality_review_required",
            "root_cause_reanalysis_required",
            "rights_review_required",
            "blocked",
            "paused",
            "cancelled",
            "failed",
        }
    ),
    "awaiting_execution_approval": frozenset(
        {
            "awaiting_execution_approval",
            "code_repair_ready",
            "tool_recovery_ready",
            "approved_execution_pending",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "code_repair_ready": frozenset(
        {
            "awaiting_execution_approval",
            "approved_execution_pending",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "tool_recovery_ready": frozenset(
        {
            "awaiting_execution_approval",
            "approved_execution_pending",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "checkpoint_recovery_required": frozenset(
        {"repair_replanning_required", "paused", "cancelled", "blocked", "failed"}
    ),
    "approved_execution_pending": frozenset(
        {"execution_running", "paused", "cancelled", "blocked", "failed"}
    ),
    "execution_running": frozenset(
        {
            "technical_validation_required",
            "output_quality_review_required",
            "execution_failed",
            "rollback_required",
            "paused",
            "blocked",
            "failed",
        }
    ),
    "execution_failed": frozenset(
        {
            "rollback_required",
            "repair_replanning_required",
            "root_cause_reanalysis_required",
            "paused",
            "blocked",
            "failed",
        }
    ),
    "rollback_required": frozenset(
        {"rollback_running", "paused", "cancelled", "blocked", "failed"}
    ),
    "rollback_running": frozenset(
        {
            "repair_replanning_required",
            "root_cause_reanalysis_required",
            "rollback_failed",
            "paused",
            "blocked",
            "failed",
        }
    ),
    "rollback_failed": frozenset({"paused", "cancelled", "blocked", "failed"}),
    "technical_validation_required": frozenset(
        {
            "output_quality_review_required",
            "repair_replanning_required",
            "root_cause_reanalysis_required",
            "rollback_required",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "output_quality_review_required": frozenset(
        {
            "human_quality_review_required",
            "awaiting_safety_gate",
            "repair_replanning_required",
            "root_cause_reanalysis_required",
            "rights_review_required",
            "safety_review_required",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "human_quality_review_required": frozenset(
        {
            "awaiting_safety_gate",
            "repair_replanning_required",
            "root_cause_reanalysis_required",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "repair_replanning_required": frozenset(
        {
            "repair_planning_required",
            "root_cause_reanalysis_required",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "root_cause_reanalysis_required": frozenset(
        {
            "root_cause_analysis_required",
            "human_quality_review_required",
            "paused",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "awaiting_safety_gate": frozenset(
        {"ready_for_workflow_controller", "paused", "cancelled", "blocked", "failed"}
    ),
    "ready_for_workflow_controller": frozenset(
        {"completed_internal_cycle", "paused", "cancelled", "blocked", "failed"}
    ),
    "completed_internal_cycle": frozenset(),
    "paused": frozenset(
        {
            "inspecting_project",
            "rights_review_required",
            "safety_review_required",
            "observer_required",
            "diagnosis_required",
            "root_cause_analysis_required",
            "repair_planning_required",
            "awaiting_repair_decision",
            "awaiting_execution_approval",
            "code_repair_ready",
            "tool_recovery_ready",
            "checkpoint_recovery_required",
            "approved_execution_pending",
            "technical_validation_required",
            "output_quality_review_required",
            "human_quality_review_required",
            "repair_replanning_required",
            "root_cause_reanalysis_required",
            "awaiting_safety_gate",
            "ready_for_workflow_controller",
            "cancelled",
            "blocked",
            "failed",
        }
    ),
    "cancelled": frozenset(),
    "blocked": frozenset(),
    "failed": frozenset(),
    "unknown": frozenset({"inspecting_project", "paused", "cancelled", "blocked", "failed"}),
}

_ACTION_CLASS_BY_TYPE: dict[
    BobaAutopilotActionTypeV1,
    BobaAutopilotActionClassV1,
] = {
    "inspect_project": "automatic_read_only",
    "load_artifacts": "automatic_read_only",
    "generate_observer": "automatic_read_only",
    "generate_error_doctor": "automatic_read_only",
    "generate_root_cause_analyzer": "automatic_read_only",
    "generate_repair_planner": "automatic_read_only",
    "request_execution_approval": "automatic_read_only",
    "invoke_code_surgeon": "approval_required_execution",
    "invoke_tool_recovery": "approval_required_execution",
    "invoke_tool_recovery_rollback": "approval_required_execution",
    "invoke_output_quality_review": "approval_required_read_only",
    "prepare_checkpoint_handoff": "future_gated",
    "prepare_validator_handoff": "future_gated",
    "prepare_safety_handoff": "future_gated",
    "prepare_workflow_handoff": "future_gated",
    "pause_controller": "automatic_read_only",
    "cancel_controller": "automatic_read_only",
    "stop_controller": "automatic_read_only",
    "human_review": "future_gated",
    "unknown": "unknown",
}

_SAFE_CODE_OPERATIONS = frozenset({"proposal_only", "validate_proposal"})
_SAFE_TOOL_OPERATIONS = frozenset({"plan", "health_check"})
_SAFE_QUALITY_OPERATIONS = frozenset({"artifact_review"})
_APPROVED_QUALITY_OPERATIONS = frozenset(
    {"technical_review", "baseline_compare", "human_review"}
)
_APPROVED_CODE_OPERATIONS = frozenset({"execute_approved", "prepare_local_commit"})
_APPROVED_TOOL_OPERATIONS = frozenset({"execute_approved", "validate_output", "rollback"})
_PROHIBITED_ACTIONS = [
    "Do not bypass rights or safety gates.",
    "Do not run arbitrary commands, Git, FFmpeg, or network operations.",
    "Do not modify source media or overwrite accepted outputs.",
    "Do not install packages, restart services, push, merge, deploy, upload, or publish.",
    "Do not resume Olympus from Autopilot Controller V1.",
]


def classify_autopilot_action(
    action_type: BobaAutopilotActionTypeV1,
    *,
    target_module: str = "",
    target_operation: str = "",
) -> BobaAutopilotActionClassV1:
    """Classify a bounded action without accepting artifact-provided callables."""

    if action_type == "invoke_code_surgeon":
        if target_module != "code_surgeon":
            return "prohibited"
        if target_operation in _SAFE_CODE_OPERATIONS:
            return "automatic_read_only"
        if target_operation in _APPROVED_CODE_OPERATIONS:
            return "approval_required_execution"
        return "prohibited"
    if action_type in {"invoke_tool_recovery", "invoke_tool_recovery_rollback"}:
        if target_module != "tool_recovery_brain":
            return "prohibited"
        if target_operation in _SAFE_TOOL_OPERATIONS:
            return "automatic_read_only"
        if target_operation == "validate_output":
            return "approval_required_read_only"
        if target_operation in _APPROVED_TOOL_OPERATIONS:
            return "approval_required_execution"
        return "prohibited"
    if action_type == "invoke_output_quality_review":
        if target_module != "output_quality_reviewer":
            return "prohibited"
        if target_operation in _SAFE_QUALITY_OPERATIONS:
            return "automatic_read_only"
        if target_operation in _APPROVED_QUALITY_OPERATIONS:
            return "approval_required_read_only"
        return "prohibited"
    return _ACTION_CLASS_BY_TYPE[action_type]


def validate_autopilot_state_transition(
    from_state: BobaAutopilotStateV1,
    to_state: BobaAutopilotStateV1,
) -> bool:
    """Return whether the V1 state graph permits an explicit transition."""

    return to_state in VALID_AUTOPILOT_TRANSITIONS.get(from_state, frozenset())


def fingerprint_autopilot_action(
    *,
    project_id: str,
    run_id: str,
    action_type: str,
    target_module: str,
    target_operation: str,
    target_plan_id: str = "",
    target_strategy_id: str = "",
    snapshot_sha256: str,
) -> str:
    """Build the deterministic idempotency fingerprint required by V1."""

    return _digest(
        {
            "project_id": project_id,
            "run_id": run_id,
            "action_type": action_type,
            "target_module": target_module,
            "target_operation": target_operation,
            "target_plan_id": target_plan_id,
            "target_strategy_id": target_strategy_id,
            "snapshot_sha256": snapshot_sha256,
        }
    )


def _artifact_state(
    *,
    store: BobaMemoryStore,
    project_id: str,
    module_name: str,
    loader_name: str,
    path_name: str,
) -> tuple[dict[str, Any], Any | None]:
    loader = getattr(store, loader_name)
    path_builder = getattr(store, path_name)
    path = path_builder(project_id)
    report = loader(project_id)
    exists = path.exists()
    valid = report is not None
    payload = (
        report.model_dump(mode="json")
        if isinstance(report, BobaContract)
        else _json_safe(report)
    )
    if not isinstance(payload, Mapping):
        payload = {}
    schema_version = _text(payload.get("schema_version"), maximum=120)
    created_at = _text(payload.get("created_at"), maximum=80)
    artifact_digest = _digest(payload) if payload else ""
    try:
        reference = path.relative_to(store.root).as_posix()
    except ValueError:
        reference = path.name
    state = {
        "artifact_id": module_name,
        "module_name": module_name,
        "reference": reference,
        "exists": exists,
        "valid": valid,
        "status": "current" if valid else "malformed" if exists else "missing",
        "schema_version": schema_version,
        "created_at": created_at,
        "artifact_digest": artifact_digest,
    }
    return state, report


def build_autopilot_project_snapshot(
    store: BobaMemoryStore,
    project_id: str,
    *,
    project_context: Mapping[str, Any] | None = None,
) -> BobaAutopilotProjectSnapshotV1:
    """Capture bounded persisted identities without reading source-media content."""

    context = dict(project_context or {})
    descriptors = (
        (
            "rights_permission_gate",
            "load_rights_permission_gate",
            "rights_permission_gate_path",
        ),
        ("observer", "load_observer_report", "observer_path"),
        ("error_doctor", "load_boba_error_doctor", "error_doctor_path"),
        (
            "root_cause_analyzer",
            "load_boba_root_cause_analyzer",
            "root_cause_analyzer_path",
        ),
        ("repair_planner", "load_boba_repair_planner", "repair_planner_path"),
        ("code_surgeon", "load_boba_code_surgeon", "code_surgeon_path"),
        ("tool_recovery_brain", "load_boba_tool_recovery", "tool_recovery_path"),
        (
            "output_quality_reviewer",
            "load_boba_output_quality_reviewer",
            "output_quality_reviewer_path",
        ),
    )
    states: dict[str, dict[str, Any]] = {}
    reports: dict[str, Any] = {}
    versions: dict[str, str] = {}
    for module_name, loader_name, path_name in descriptors:
        state, report = _artifact_state(
            store=store,
            project_id=project_id,
            module_name=module_name,
            loader_name=loader_name,
            path_name=path_name,
        )
        states[module_name] = state
        reports[module_name] = report
        if state["schema_version"]:
            versions[module_name] = str(state["schema_version"])

    context_states = context.get("module_artifact_states")
    if isinstance(context_states, Mapping):
        for module_name, raw_state in context_states.items():
            if isinstance(raw_state, Mapping):
                states[_text(module_name, maximum=160)] = dict(
                    _json_safe(raw_state)
                )

    dependencies = (
        ("observer", "rights_permission_gate"),
        ("error_doctor", "observer"),
        ("root_cause_analyzer", "error_doctor"),
        ("repair_planner", "root_cause_analyzer"),
        ("code_surgeon", "repair_planner"),
        ("tool_recovery_brain", "repair_planner"),
        ("output_quality_reviewer", "tool_recovery_brain"),
    )
    stale: list[str] = []
    conflicts: list[str] = []
    for downstream, upstream in dependencies:
        downstream_state = states.get(downstream, {})
        upstream_state = states.get(upstream, {})
        downstream_time = _parse_time(str(downstream_state.get("created_at") or ""))
        upstream_time = _parse_time(str(upstream_state.get("created_at") or ""))
        if (
            downstream_state.get("valid")
            and upstream_state.get("valid")
            and downstream_time is not None
            and upstream_time is not None
            and downstream_time < upstream_time
        ):
            downstream_state["status"] = "stale"
            downstream_state["stale_reason"] = f"{upstream} is newer."
            stale.append(downstream)

    rights_status = _text(context.get("rights_status"), maximum=80) or "unknown"
    rights_report = reports.get("rights_permission_gate")
    gate_decisions = getattr(rights_report, "gate_decisions", [])
    gate_statuses = [
        _text(getattr(item, "gate_status", ""), maximum=80)
        for item in gate_decisions
    ]
    if gate_statuses:
        if "blocked" in gate_statuses:
            rights_status = "blocked"
        elif any(
            status in {
                "needs_permission",
                "needs_rights_review",
                "insufficient_information",
            }
            for status in gate_statuses
        ):
            rights_status = "needs_rights_review"
        elif all(status == "ready_for_human_review" for status in gate_statuses):
            rights_status = "ready_for_human_review"

    safety_status = (
        _text(context.get("safety_status"), maximum=80)
        or "clear_for_local_analysis"
    )
    code_report = reports.get("code_surgeon")
    active_code_runs = [
        _text(getattr(item, "isolated_run_id", ""), maximum=180)
        for item in getattr(code_report, "isolated_runs", [])
        if getattr(item, "run_status", "")
        in {
            "worktree_ready",
            "patch_applied",
            "validation_running",
            "validation_passed",
            "local_commit_prepared",
        }
    ]
    tool_report = reports.get("tool_recovery_brain")
    active_recovery_runs = [
        _text(getattr(item, "recovery_attempt_id", ""), maximum=180)
        for item in getattr(tool_report, "recovery_attempts", [])
        if getattr(item, "status", "") == "running"
    ]
    if active_code_runs and active_recovery_runs:
        conflicts.extend(["code_surgeon", "tool_recovery_brain"])

    accepted_outputs = _unique(
        list(context.get("accepted_output_ids") or []),
        limit=128,
        maximum=180,
    )
    source_references = _unique(
        list(context.get("source_media_references") or []),
        limit=32,
        maximum=500,
    )
    active_external = _unique(
        list(context.get("active_external_operations") or []),
        limit=32,
        maximum=180,
    )
    missing = [
        module_name
        for module_name, state in states.items()
        if state.get("status") in {"missing", "malformed"}
    ]
    digest_payload = {
        "project_id": project_id,
        "source_artifact_versions": versions,
        "module_artifact_states": states,
        "current_workflow_stage": _text(
            context.get("current_workflow_stage"),
            maximum=160,
        )
        or "unknown",
        "accepted_output_ids": accepted_outputs,
        "source_media_references": source_references,
        "source_media_read_only": bool(context.get("source_media_read_only", True)),
        "rights_status": rights_status,
        "safety_status": safety_status,
        "active_external_operations": active_external,
        "active_recovery_runs": active_recovery_runs,
        "active_code_surgeon_runs": active_code_runs,
        "stale_artifact_ids": sorted(stale),
        "missing_required_artifact_ids": sorted(missing),
        "conflicting_artifact_ids": sorted(set(conflicts)),
    }
    snapshot_digest = _digest(digest_payload)
    return BobaAutopilotProjectSnapshotV1(
        project_snapshot_id=f"autopilot_snapshot_{snapshot_digest[:24]}",
        project_id=project_id,
        source_artifact_versions=versions,
        module_artifact_states=states,
        current_workflow_stage=str(digest_payload["current_workflow_stage"]),
        accepted_output_ids=accepted_outputs,
        source_media_references=source_references,
        source_media_read_only=bool(digest_payload["source_media_read_only"]),
        rights_status=rights_status,
        safety_status=safety_status,
        active_external_operations=active_external,
        active_recovery_runs=active_recovery_runs,
        active_code_surgeon_runs=active_code_runs,
        stale_artifact_ids=sorted(stale),
        missing_required_artifact_ids=sorted(missing),
        conflicting_artifact_ids=sorted(set(conflicts)),
        snapshot_sha256=snapshot_digest,
        warnings=[
            "Snapshot stores bounded identities and references only.",
            *(
                ["A malformed or unreadable module artifact was detected."]
                if any(
                    state.get("status") == "malformed" for state in states.values()
                )
                else []
            ),
        ],
    )


def _budget_for_run(
    controller: BobaAutopilotControllerSetV1,
    run: BobaAutopilotRunV1,
) -> BobaAutopilotRecoveryBudgetV1:
    budget = next(
        (item for item in reversed(controller.recovery_budgets) if item.budget_id == run.budget_id),
        None,
    )
    if budget is None:
        raise ValidationError("Autopilot recovery budget is unavailable.")
    return budget


def _usage_for_run(
    controller: BobaAutopilotControllerSetV1,
    run: BobaAutopilotRunV1,
) -> BobaAutopilotBudgetUsageV1:
    usage = next(
        (
            item
            for item in reversed(controller.budget_usages)
            if item.budget_id == run.budget_id
        ),
        None,
    )
    if usage is None:
        raise ValidationError("Autopilot budget usage is unavailable.")
    return usage


def calculate_autopilot_budget_usage(
    controller: BobaAutopilotControllerSetV1,
    run: BobaAutopilotRunV1,
) -> BobaAutopilotBudgetUsageV1:
    """Refresh elapsed usage and hard-limit truth for the current budget."""

    budget = _budget_for_run(controller, run)
    usage = _usage_for_run(controller, run)
    usage.total_duration_seconds = _elapsed_seconds(
        run.started_at or run.created_at,
        run.completed_at,
    )
    dimensions = {
        "total_actions": usage.actions_used >= budget.maximum_total_actions,
        "execution_actions": (
            usage.execution_actions_used >= budget.maximum_execution_actions
            and budget.maximum_execution_actions >= 0
        ),
        "module_invocations": (
            usage.module_invocations_used >= budget.maximum_module_invocations
        ),
        "total_retries": usage.retries_used >= budget.maximum_total_retries,
        "identical_failure_retries": (
            usage.identical_failure_retries_used
            >= budget.maximum_identical_failure_retries
        ),
        "total_duration_seconds": (
            usage.total_duration_seconds >= budget.maximum_total_duration_seconds
        ),
        "execution_duration_seconds": (
            usage.execution_duration_seconds
            >= budget.maximum_execution_duration_seconds
            and budget.maximum_execution_duration_seconds >= 0
        ),
        "risk_score": usage.current_risk_score >= budget.maximum_risk_score,
        "code_repair_attempts": (
            usage.code_repair_attempts_used >= budget.maximum_code_repair_attempts
            and budget.maximum_code_repair_attempts >= 0
        ),
        "tool_recovery_attempts": (
            usage.tool_recovery_attempts_used
            >= budget.maximum_tool_recovery_attempts
            and budget.maximum_tool_recovery_attempts >= 0
        ),
        "quality_review_attempts": (
            usage.quality_review_attempts_used
            >= budget.maximum_quality_review_attempts
            and budget.maximum_quality_review_attempts >= 0
        ),
        "replanning_cycles": (
            usage.replanning_cycles_used >= budget.maximum_replanning_cycles
            and budget.maximum_replanning_cycles >= 0
        ),
        "root_cause_reanalysis_cycles": (
            usage.root_cause_reanalysis_cycles_used
            >= budget.maximum_root_cause_reanalysis_cycles
            and budget.maximum_root_cause_reanalysis_cycles >= 0
        ),
    }
    usage.exhausted_dimensions = [
        name for name, exhausted in dimensions.items() if exhausted
    ]
    usage.budget_exhausted = bool(usage.exhausted_dimensions)
    usage.next_action_allowed = not usage.budget_exhausted
    return usage


def detect_autopilot_loop(
    controller: BobaAutopilotControllerSetV1,
    run: BobaAutopilotRunV1,
    *,
    action: BobaAutopilotActionV1 | None = None,
) -> str | None:
    """Detect identical failures, A-B-A state loops, and duplicate completion."""

    if action is not None:
        matching = [
            item
            for item in controller.planned_actions
            if item.run_id == run.run_id
            and item.idempotency_key == action.idempotency_key
            and item.action_id != action.action_id
        ]
        if any(item.status == "succeeded" for item in matching):
            return "A completed identical action already exists."
        failed = [item for item in matching if item.status in {"failed", "timed_out"}]
        budget = _budget_for_run(controller, run)
        if len(failed) > budget.maximum_identical_failure_retries:
            return "The identical action failed without new evidence."
    transitions = [
        item
        for item in controller.state_transitions
        if item.run_id == run.run_id and item.transition_status == "applied"
    ]
    if len(transitions) >= 3:
        states = [item.to_state for item in transitions[-3:]]
        if states[0] == states[2] and states[0] != states[1]:
            return f"An A-B-A state loop was detected: {' -> '.join(states)}."
    return None


def sanitize_autopilot_export(value: Any) -> Any:
    """Return a bounded JSON-safe export without private paths or secrets."""

    return _json_safe(value)


class BobaAutopilotControllerV1:
    """Coordinate typed BOBA modules through a persisted deterministic state machine."""

    def __init__(
        self,
        store: BobaMemoryStore,
        *,
        context_provider: AutopilotContextProvider | None = None,
        module_invoker: AutopilotModuleInvoker | None = None,
        safety_decision_validator: AutopilotSafetyDecisionValidator | None = None,
        lock_owner: str = "local_boba_api",
        lock_lease_seconds: int = 300,
    ) -> None:
        self.store = store
        self.context_provider = context_provider
        self.module_invoker = module_invoker
        self.safety_decision_validator = safety_decision_validator
        self.lock_owner = _text(lock_owner, maximum=160) or "local_boba_api"
        self.lock_lease_seconds = max(30, min(lock_lease_seconds, 900))

    async def _context(self, project_id: str) -> Mapping[str, Any]:
        if self.context_provider is None:
            return {}
        return await self.context_provider(project_id)

    async def _capture_snapshot(
        self,
        project_id: str,
    ) -> BobaAutopilotProjectSnapshotV1:
        return build_autopilot_project_snapshot(
            self.store,
            project_id,
            project_context=await self._context(project_id),
        )

    @staticmethod
    def _find_run(
        controller: BobaAutopilotControllerSetV1,
        run_id: str,
    ) -> BobaAutopilotRunV1:
        run = next((item for item in controller.runs if item.run_id == run_id), None)
        if run is None:
            raise ValidationError(
                "BOBA Autopilot run was not found.",
                details={"run_id": run_id},
            )
        return run

    def _load_controller(self, project_id: str) -> BobaAutopilotControllerSetV1:
        controller = self.store.load_boba_autopilot_controller(project_id)
        if controller is None:
            raise ValidationError(
                "BOBA Autopilot Controller V1 is not available.",
                details={"project_id": project_id},
            )
        return controller

    @staticmethod
    def _snapshot_for_run(
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotProjectSnapshotV1:
        snapshot = next(
            (
                item
                for item in reversed(controller.project_snapshots)
                if item.project_snapshot_id == run.project_snapshot_id
            ),
            None,
        )
        if snapshot is None:
            raise ValidationError("Autopilot project snapshot is unavailable.")
        return snapshot

    @staticmethod
    def _action(
        controller: BobaAutopilotControllerSetV1,
        action_id: str,
    ) -> BobaAutopilotActionV1:
        action = next(
            (item for item in controller.planned_actions if item.action_id == action_id),
            None,
        )
        if action is None:
            raise ValidationError(
                "BOBA Autopilot action was not found.",
                details={"action_id": action_id},
            )
        return action

    @staticmethod
    def _run_actions(
        controller: BobaAutopilotControllerSetV1,
        run_id: str,
    ) -> list[BobaAutopilotActionV1]:
        return [item for item in controller.planned_actions if item.run_id == run_id]

    @staticmethod
    def _run_events(
        controller: BobaAutopilotControllerSetV1,
        run_id: str,
    ) -> list[BobaAutopilotEventV1]:
        return [item for item in controller.event_stream if item.run_id == run_id]

    def _append_event(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        *,
        event_type: BobaAutopilotEventTypeV1,
        technical_message: str,
        easy_message: str,
        severity: BobaAutopilotSeverityV1 = "info",
        action: BobaAutopilotActionV1 | None = None,
        module_name: str = "",
        confirmed_fact: str = "",
        assessment: str = "",
        requires_attention: bool = False,
        available_user_actions: Sequence[str] = (),
        evidence_ids: Sequence[str] = (),
        warnings: Sequence[str] = (),
    ) -> BobaAutopilotEventV1:
        events = self._run_events(controller, run.run_id)
        sequence = 1 + max((item.sequence for item in events), default=0)
        actions = self._run_actions(controller, run.run_id)
        progress_total = len(actions) or None
        progress_current = (
            sum(item.status in {"succeeded", "skipped", "rolled_back"} for item in actions)
            if actions
            else None
        )
        progress_percent = (
            round(progress_current * 100.0 / progress_total, 2)
            if progress_current is not None and progress_total
            else None
        )
        event = BobaAutopilotEventV1(
            event_id=_stable_id(
                "autopilot_event",
                run.run_id,
                sequence,
                event_type,
                action.action_id if action else "",
            ),
            run_id=run.run_id,
            sequence=sequence,
            event_type=event_type,
            severity=severity,
            state=run.current_state,
            action_id=action.action_id if action else None,
            module_name=_text(module_name, maximum=160),
            technical_message=_text(technical_message, maximum=1_200),
            easy_message=_text(easy_message, maximum=700),
            confirmed_fact=_text(confirmed_fact, maximum=700),
            assessment=_text(assessment, maximum=700),
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
                evidence_ids,
                limit=64,
                maximum=180,
            ),
            warnings=_unique(warnings, limit=32),
        )
        controller.event_stream.append(event)
        controller.event_stream = controller.event_stream[-2_000:]
        run.live_event_ids.append(event.event_id)
        run.live_event_ids = run.live_event_ids[-2_000:]
        controller.signal_usage.local_event_stream_used = True
        return event

    def _incident(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        *,
        incident_type: BobaAutopilotIncidentTypeV1,
        title: str,
        summary: str,
        severity: BobaAutopilotSeverityV1 = "warning",
        action: BobaAutopilotActionV1 | None = None,
        invocation: BobaAutopilotModuleInvocationV1 | None = None,
        fingerprint: str = "",
        uncertain: bool = False,
        source_media_risk: bool = False,
        accepted_output_risk: bool = False,
    ) -> BobaAutopilotIncidentV1:
        prior = [
            item
            for item in controller.incidents
            if item.run_id == run.run_id
            and fingerprint
            and item.repeated_fingerprint == fingerprint
        ]
        incident = BobaAutopilotIncidentV1(
            incident_id=_stable_id(
                "autopilot_incident",
                run.run_id,
                incident_type,
                fingerprint,
                len(prior) + 1,
            ),
            run_id=run.run_id,
            action_id=action.action_id if action else None,
            module_invocation_id=(
                invocation.module_invocation_id if invocation else None
            ),
            incident_type=incident_type,
            severity=severity,
            title=_text(title, maximum=240),
            summary=_text(summary, maximum=1_200),
            evidence_ids=_unique(
                [
                    action.action_id if action else "",
                    invocation.module_invocation_id if invocation else "",
                ],
                limit=64,
                maximum=180,
            ),
            repeated_fingerprint=fingerprint,
            occurrence_count=len(prior) + 1,
            loop_risk=incident_type in {"loop_detected", "repeated_failure"},
            project_state_uncertain=uncertain,
            source_media_risk=source_media_risk,
            accepted_output_risk=accepted_output_risk,
            immediate_controller_action=(
                "Pause and require bounded human review."
                if uncertain or incident_type in {"loop_detected", "rollback_failure"}
                else "Stop the failed action and preserve evidence."
            ),
            escalation_target=(
                "safety_gate" if uncertain or source_media_risk else "human_operator"
            ),
            human_review_required=True,
        )
        controller.incidents.append(incident)
        controller.incidents = controller.incidents[-2_000:]
        run.incident_ids.append(incident.incident_id)
        run.incident_ids = run.incident_ids[-256:]
        return incident

    def _handoff(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        *,
        target_module: BobaAutopilotHandoffTargetV1,
        reason: str,
        action: BobaAutopilotActionV1 | None = None,
        decision: BobaAutopilotDecisionV1 | None = None,
        required_inputs: Sequence[str] = (),
        blocking_conditions: Sequence[str] = (),
        failed_conditions: Sequence[str] = (),
        priority: str = "medium",
        apply_automatically: bool = False,
    ) -> BobaAutopilotHandoffV1:
        if target_module not in {
            "observer",
            "error_doctor",
            "root_cause_analyzer",
            "repair_planner",
            "output_quality_reviewer",
        }:
            apply_automatically = False
        handoff_id = _stable_id(
            "autopilot_handoff",
            run.run_id,
            target_module,
            action.action_id if action else "",
            decision.decision_id if decision else "",
            reason,
        )
        existing = next(
            (item for item in controller.handoffs if item.handoff_id == handoff_id),
            None,
        )
        if existing is not None:
            return existing
        usage = calculate_autopilot_budget_usage(controller, run)
        checkpoint = next(
            (
                item
                for item in reversed(controller.checkpoint_requirements)
                if item.run_id == run.run_id
            ),
            None,
        )
        handoff = BobaAutopilotHandoffV1(
            handoff_id=handoff_id,
            run_id=run.run_id,
            source_action_id=action.action_id if action else None,
            source_decision_id=decision.decision_id if decision else None,
            target_module=target_module,
            reason=_text(reason, maximum=700),
            current_state=run.current_state,
            required_inputs=_unique(required_inputs, limit=32),
            blocking_conditions=_unique(blocking_conditions, limit=32),
            satisfied_conditions=_unique(
                [
                    "Project identity is exact.",
                    "Source media remains read-only.",
                    "Autopilot direct execution is disabled.",
                ],
                limit=32,
            ),
            failed_conditions=_unique(failed_conditions, limit=32),
            budget_status="exhausted" if usage.budget_exhausted else "available",
            checkpoint_status=(
                checkpoint.checkpoint_status if checkpoint else "unknown"
            ),
            quality_status=(
                "acceptable"
                if target_module
                in {"safety_gate", "workflow_controller", "final_decision_bus"}
                else "pending"
            ),
            rights_status=run.rights_status,
            safety_status=run.safety_status,
            allowed_actions=(
                ["Generate the named read-only BOBA artifact."]
                if apply_automatically
                else ["Review this bounded handoff and decide separately."]
            ),
            prohibited_actions=_PROHIBITED_ACTIONS,
            apply_automatically=apply_automatically,
            human_approval_required=not apply_automatically,
            priority=_text(priority, maximum=80),
        )
        controller.handoffs.append(handoff)
        controller.handoffs = controller.handoffs[-1_000:]
        run.handoff_ids.append(handoff.handoff_id)
        run.handoff_ids = run.handoff_ids[-256:]
        return handoff

    def _transition(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        to_state: BobaAutopilotStateV1,
        *,
        reason: str,
        action: BobaAutopilotActionV1 | None = None,
        triggering_module: str = "",
        evidence_ids: Sequence[str] = (),
        approval_required: bool = False,
        safety_gate_required: bool = False,
        rights_gate_required: bool = False,
        human_review_required: bool = False,
    ) -> BobaAutopilotStateTransitionV1:
        from_state = run.current_state
        allowed = validate_autopilot_state_transition(from_state, to_state)
        sequence = (
            1
            + max(
                (
                    item.sequence
                    for item in controller.state_transitions
                    if item.run_id == run.run_id
                ),
                default=0,
            )
        )
        transition = BobaAutopilotStateTransitionV1(
            transition_id=_stable_id(
                "autopilot_transition",
                run.run_id,
                sequence,
                from_state,
                to_state,
            ),
            run_id=run.run_id,
            sequence=sequence,
            from_state=from_state,
            to_state=to_state,
            transition_reason=_text(reason, maximum=900),
            triggering_action_id=action.action_id if action else None,
            triggering_module=_text(triggering_module, maximum=160),
            evidence_ids=_unique(evidence_ids, limit=64, maximum=180),
            preconditions=[
                "The transition is present in the V1 state graph.",
                "The run is not terminal.",
            ],
            preconditions_passed=allowed and from_state not in _TERMINAL_STATES,
            blocked_preconditions=(
                []
                if allowed and from_state not in _TERMINAL_STATES
                else ["The requested state transition is invalid or terminal."]
            ),
            approval_required=approval_required,
            safety_gate_required=safety_gate_required,
            rights_gate_required=rights_gate_required,
            human_review_required=human_review_required,
            transition_status=(
                "applied"
                if allowed and from_state not in _TERMINAL_STATES
                else "invalid"
            ),
        )
        controller.state_transitions.append(transition)
        controller.state_transitions = controller.state_transitions[-2_000:]
        if transition.transition_status != "applied":
            self._incident(
                controller,
                run,
                incident_type="state_transition_error",
                title="Invalid Autopilot state transition",
                summary=f"{from_state} cannot transition to {to_state}.",
                severity="high",
                action=action,
                fingerprint=_digest([from_state, to_state]),
            )
            raise ValidationError(
                "Invalid BOBA Autopilot state transition.",
                details={"from_state": from_state, "to_state": to_state},
            )
        run.previous_state = from_state
        run.current_state = to_state
        run.updated_at = now_iso()
        run.human_review_required = human_review_required
        if to_state == "awaiting_execution_approval":
            run.run_status = "awaiting_approval"
        elif to_state in {
            "rights_review_required",
            "safety_review_required",
            "human_quality_review_required",
        }:
            run.run_status = "awaiting_human_review"
        elif to_state == "paused":
            run.run_status = "paused"
        elif to_state == "blocked":
            run.run_status = "blocked"
        elif to_state == "cancelled":
            run.run_status = "cancelled"
            run.completed_at = now_iso()
        elif to_state == "failed":
            run.run_status = "failed"
            run.completed_at = now_iso()
        elif to_state == "completed_internal_cycle":
            run.run_status = "completed_internal_cycle"
            run.completed_at = now_iso()
        else:
            run.run_status = "active"
        self._append_event(
            controller,
            run,
            event_type="state_changed",
            technical_message=f"State changed from {from_state} to {to_state}: {reason}",
            easy_message=self._easy_state_message(to_state),
            action=action,
            module_name=triggering_module,
            confirmed_fact=f"Controller state is now {to_state}.",
            assessment=reason,
            requires_attention=human_review_required
            or to_state
            in {
                "rights_review_required",
                "safety_review_required",
                "awaiting_execution_approval",
                "blocked",
                "failed",
            },
            evidence_ids=evidence_ids,
        )
        return transition

    @staticmethod
    def _easy_state_message(state: BobaAutopilotStateV1) -> str:
        messages: dict[BobaAutopilotStateV1, str] = {
            "inspecting_project": "BOBA is checking saved project evidence only.",
            "rights_review_required": "BOBA stopped because rights need review.",
            "safety_review_required": "BOBA stopped because safety needs review.",
            "observer_required": "BOBA needs a fresh local Observer report.",
            "diagnosis_required": "BOBA is ready to diagnose the saved finding.",
            "root_cause_analysis_required": "BOBA is ready to compare possible causes.",
            "repair_planning_required": "BOBA is ready to prepare safe repair options.",
            "awaiting_repair_decision": "BOBA is deciding which advisory route is supported.",
            "awaiting_execution_approval": (
                "A repair is ready, but nothing will run without exact target approval."
            ),
            "approved_execution_pending": "The exact approved action passed controller checks.",
            "execution_running": "The target BOBA module is handling the approved action.",
            "technical_validation_required": "The result still needs technical validation.",
            "output_quality_review_required": "The result still needs quality review.",
            "human_quality_review_required": "A person must review the remaining quality question.",
            "awaiting_safety_gate": (
                "Quality review passed; BOBA prepared a future Safety Gate handoff."
            ),
            "ready_for_workflow_controller": (
                "BOBA prepared a future Workflow Controller handoff but did not resume Olympus."
            ),
            "completed_internal_cycle": (
                "BOBA completed its internal cycle without resuming or publishing anything."
            ),
            "paused": "BOBA Autopilot is paused.",
            "cancelled": "BOBA Autopilot was cancelled.",
            "blocked": "BOBA stopped at a hard block.",
            "failed": "BOBA Autopilot failed and preserved its evidence.",
        }
        return messages.get(state, f"BOBA controller state is {state.replace('_', ' ')}.")

    def _refresh_summary(
        self,
        controller: BobaAutopilotControllerSetV1,
    ) -> None:
        active_runs = [
            item for item in controller.runs if item.run_status in _ACTIVE_RUN_STATUSES
        ]
        current = next(
            (
                item
                for item in reversed(controller.runs)
                if item.run_id == controller.active_run_id
            ),
            active_runs[-1] if active_runs else None,
        )
        current_action = ""
        if current and current.active_action_id:
            action = next(
                (
                    item
                    for item in controller.planned_actions
                    if item.action_id == current.active_action_id
                ),
                None,
            )
            current_action = action.description if action else ""
        incidents = controller.incidents
        controller.controller_summary = BobaAutopilotControllerSummaryV1(
            total_runs=len(controller.runs),
            active_run_count=len(active_runs),
            paused_run_count=sum(
                item.run_status == "paused" for item in controller.runs
            ),
            blocked_run_count=sum(
                item.run_status == "blocked" for item in controller.runs
            ),
            completed_internal_cycle_count=sum(
                item.run_status == "completed_internal_cycle"
                for item in controller.runs
            ),
            failed_run_count=sum(
                item.run_status == "failed" for item in controller.runs
            ),
            total_state_transitions=len(controller.state_transitions),
            automatic_read_only_action_count=sum(
                item.action_class == "automatic_read_only"
                for item in controller.planned_actions
            ),
            approved_execution_action_count=sum(
                item.action_class == "approval_required_execution"
                and item.status in {"running", "succeeded", "failed", "rolled_back"}
                for item in controller.planned_actions
            ),
            approval_wait_count=sum(
                item.status == "awaiting_approval"
                for item in controller.planned_actions
            ),
            approval_mismatch_count=sum(
                item.incident_type in {"approval_mismatch", "approval_expired"}
                for item in incidents
            ),
            budget_exhaustion_count=sum(
                item.incident_type == "budget_exhausted" for item in incidents
            ),
            loop_prevention_count=sum(
                item.incident_type == "loop_detected" for item in incidents
            ),
            rollback_count=sum(
                item.action_type == "invoke_tool_recovery_rollback"
                and item.status in {"running", "succeeded", "failed"}
                for item in controller.planned_actions
            ),
            quality_rejection_count=sum(
                item.incident_type == "quality_rejection" for item in incidents
            ),
            rights_block_count=sum(
                item.incident_type == "rights_block" for item in incidents
            ),
            safety_block_count=sum(
                item.incident_type == "safety_block" for item in incidents
            ),
            current_run_id=current.run_id if current else None,
            current_state=current.current_state if current else "unknown",
            current_action=current_action,
            next_required_human_action=(
                "Complete the exact target-module approval."
                if current and current.run_status == "awaiting_approval"
                else "Review the current BOBA block."
                if current and current.human_review_required
                else ""
            ),
            safest_next_action=(
                "Plan or continue only safe read-only controller steps."
                if current and current.current_state not in _TERMINAL_STATES
                else "No automatic action is available."
            ),
            limitations=[
                "Autopilot completion does not resume Olympus.",
                "Autopilot cannot approve or directly execute repair commands.",
            ],
        )

    def _persist(
        self,
        controller: BobaAutopilotControllerSetV1,
    ) -> BobaAutopilotControllerSetV1:
        active = [
            item
            for item in controller.runs
            if item.run_status in _ACTIVE_RUN_STATUSES
            and item.control_mode != "advisory_only"
        ]
        controller.active_run_id = active[-1].run_id if active else None
        self._refresh_summary(controller)
        return self.store.save_boba_autopilot_controller(controller)

    def _new_action(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        *,
        action_type: BobaAutopilotActionTypeV1,
        target_module: BobaAutopilotActionTargetV1,
        target_operation: str,
        description: str,
        rationale: str,
        parameters: Mapping[str, Any] | None = None,
        expected_output: str = "",
        source_handoff_id: str | None = None,
        risk_level: str = "low",
        timeout_seconds: int = 300,
    ) -> BobaAutopilotActionV1:
        snapshot = self._snapshot_for_run(controller, run)
        safe_parameters = _json_safe(dict(parameters or {}))
        if not isinstance(safe_parameters, dict):
            safe_parameters = {}
        target_plan_id = _text(
            safe_parameters.get("recovery_plan_id")
            or safe_parameters.get("patch_proposal_id")
            or safe_parameters.get("target_plan_id"),
            maximum=180,
        )
        target_strategy_id = _text(
            safe_parameters.get("recovery_strategy_id")
            or safe_parameters.get("repair_strategy_id")
            or safe_parameters.get("target_strategy_id"),
            maximum=180,
        )
        idempotency = fingerprint_autopilot_action(
            project_id=run.project_id,
            run_id=run.run_id,
            action_type=action_type,
            target_module=target_module,
            target_operation=target_operation,
            target_plan_id=target_plan_id,
            target_strategy_id=target_strategy_id,
            snapshot_sha256=snapshot.snapshot_sha256,
        )
        existing = next(
            (
                item
                for item in reversed(controller.planned_actions)
                if item.run_id == run.run_id
                and item.idempotency_key == idempotency
                and item.status
                not in {"failed", "timed_out", "cancelled", "superseded"}
            ),
            None,
        )
        if existing is not None:
            return existing
        action_class = classify_autopilot_action(
            action_type,
            target_module=target_module,
            target_operation=target_operation,
        )
        action = BobaAutopilotActionV1(
            action_id=f"autopilot_action_{idempotency[:24]}",
            run_id=run.run_id,
            action_type=action_type,
            action_class=action_class,
            target_module=target_module,
            target_operation=_text(target_operation, maximum=160),
            source_handoff_id=source_handoff_id,
            description=_text(description, maximum=700),
            rationale=_text(rationale, maximum=900),
            input_artifact_ids=_unique(
                [
                    snapshot.project_snapshot_id,
                    target_plan_id,
                    target_strategy_id,
                ],
                limit=64,
                maximum=180,
            ),
            expected_output_artifact_type=_text(expected_output, maximum=180),
            prerequisites=[
                "Current project snapshot must match.",
                "Rights and safety must permit this action.",
                "Recovery budget must remain.",
                *(
                    ["Exact target-module approval must match and remain current."]
                    if action_class
                    in {"approval_required_read_only", "approval_required_execution"}
                    else []
                ),
            ],
            parameters=safe_parameters,
            planned_snapshot_sha256=snapshot.snapshot_sha256,
            budget_cost={
                "actions": 1.0,
                "module_invocations": (
                    0.0 if target_module == "autopilot_controller" else 1.0
                ),
                "execution_actions": (
                    1.0 if action_class == "approval_required_execution" else 0.0
                ),
            },
            risk_level=_text(risk_level, maximum=80),
            idempotency_key=idempotency,
            maximum_attempts=1,
            timeout_seconds=max(1, min(timeout_seconds, 3_600)),
            status=(
                "awaiting_approval"
                if action_class
                in {"approval_required_read_only", "approval_required_execution"}
                else "planned"
            ),
            next_action_on_success="Reinspect persisted target output and route conservatively.",
            next_action_on_failure="Record an incident and return to planning or analysis.",
            stop_conditions=[
                "Any rights or safety block.",
                "Any approval, checkpoint, budget, timeout, or loop mismatch.",
                "Any uncertain project, source-media, or accepted-output state.",
            ],
            prohibited_actions=_PROHIBITED_ACTIONS,
            human_approval_required=action_class
            in {
                "approval_required_read_only",
                "approval_required_execution",
                "future_gated",
            },
            limitations=[
                "This action can invoke only the registered typed operation.",
                "Controller planning does not grant target-module approval.",
            ],
        )
        if action.action_class in {"prohibited", "unknown"}:
            action.status = "blocked"
            action.failure_summary = "The action is not in the typed V1 registry."
        controller.planned_actions.append(action)
        controller.planned_actions = controller.planned_actions[-2_000:]
        run.active_action_id = action.action_id
        if action.status == "awaiting_approval":
            run.pending_approval_ids = _unique(
                [*run.pending_approval_ids, action.action_id],
                limit=64,
                maximum=180,
            )
            self._append_event(
                controller,
                run,
                event_type="approval_required",
                technical_message=(
                    f"Action {action.action_id} requires exact approval in "
                    f"{action.target_module}."
                ),
                easy_message=(
                    "BOBA has a plan, but nothing has been changed. Complete the "
                    "exact approval inside the target BOBA module first."
                ),
                severity="warning",
                action=action,
                module_name=action.target_module,
                requires_attention=True,
                available_user_actions=["Review required approval", "Pause BOBA"],
            )
        return action

    async def create_run(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
        control_mode: BobaAutopilotControlModeV1 = "safe_read_only_automatic",
        trigger: BobaAutopilotTriggerV1 = "manual",
        source_event_id: str | None = None,
        recovery_budget: Mapping[str, Any] | None = None,
    ) -> BobaAutopilotControllerSetV1:
        """Create a run and initial snapshot without executing a repair."""

        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError("Invalid BOBA Autopilot project id.")
        if control_mode == "unknown":
            raise ValidationError("Unknown BOBA Autopilot control mode is not runnable.")
        controller = self.store.load_boba_autopilot_controller(project_id)
        if controller is None:
            controller = BobaAutopilotControllerSetV1(
                project_id=project_id,
                source_id=_text(source_id or project_id, maximum=512),
                warnings=[
                    "BOBA Autopilot coordinates typed modules only.",
                    "No repair runs when a controller run is created.",
                ],
                limitations=[
                    "V1 does not implement Safety Gate, Workflow Controller, "
                    "Final Decision Bus, Checkpoint Recovery Manager, or Live Companion.",
                    "V1 does not directly run commands, Git, FFmpeg, network requests, "
                    "uploads, publication, merges, or deployments.",
                ],
            )
        conflicting = [
            item
            for item in controller.runs
            if item.run_status in _ACTIVE_RUN_STATUSES
            and item.control_mode != "advisory_only"
            and control_mode != "advisory_only"
        ]
        if conflicting:
            self._incident(
                controller,
                conflicting[-1],
                incident_type="concurrency_conflict",
                title="Conflicting Autopilot run",
                summary="Only one state-changing controller run may be active per project.",
                severity="high",
                fingerprint=_digest([project_id, "active_autopilot_run"]),
            )
            self._persist(controller)
            raise ValidationError(
                "A conflicting BOBA Autopilot run is already active.",
                details={"active_run_id": conflicting[-1].run_id},
            )

        run_id = f"autopilot_run_{uuid4().hex}"
        budget_values = dict(DEFAULT_AUTOPILOT_BUDGET_LIMITS)
        overrides = dict(recovery_budget or {})
        unknown_budget_fields = set(overrides) - set(DEFAULT_AUTOPILOT_BUDGET_LIMITS)
        if unknown_budget_fields:
            raise ValidationError(
                "Unknown Autopilot budget field.",
                details={"fields": sorted(unknown_budget_fields)},
            )
        budget_values.update(overrides)
        budget_values["execution_coordination_allowed"] = (
            control_mode == "approved_execution_coordination"
            and bool(overrides.get("execution_coordination_allowed", True))
        )
        if control_mode == "advisory_only":
            budget_values["automatic_read_only_allowed"] = False
            budget_values["execution_coordination_allowed"] = False
        budget_id = _stable_id("autopilot_budget", project_id, run_id, budget_values)
        budget = BobaAutopilotRecoveryBudgetV1(
            budget_id=budget_id,
            run_id=run_id,
            **budget_values,
        )
        usage = BobaAutopilotBudgetUsageV1(
            budget_usage_id=_stable_id("autopilot_usage", budget_id),
            budget_id=budget_id,
        )
        snapshot = await self._capture_snapshot(project_id)
        run = BobaAutopilotRunV1(
            run_id=run_id,
            project_id=project_id,
            correlation_id=f"autopilot_correlation_{uuid4().hex}",
            started_at=now_iso(),
            control_mode=control_mode,
            trigger=trigger,
            source_event_id=source_event_id,
            project_snapshot_id=snapshot.project_snapshot_id,
            rights_status=snapshot.rights_status,
            safety_status=snapshot.safety_status,
            budget_id=budget_id,
            limitations=[
                "Internal-cycle completion does not resume Olympus.",
                "Execution remains subject to exact target-module approval and revalidation.",
            ],
        )
        if control_mode != "advisory_only":
            lock = self.store.acquire_boba_autopilot_lock(
                project_id,
                run_id=run_id,
                owner_identifier=self.lock_owner,
                mode=control_mode,
                lease_seconds=self.lock_lease_seconds,
            )
            controller.lock_metadata = lock
        controller.runs.append(run)
        controller.project_snapshots.append(snapshot)
        controller.recovery_budgets.append(budget)
        controller.budget_usages.append(usage)
        controller.signal_usage.project_snapshot_used = True
        controller.signal_usage.recovery_budget_used = True
        controller.signal_usage.rights_gate_used = bool(
            snapshot.module_artifact_states.get("rights_permission_gate", {}).get(
                "valid"
            )
        )
        self._append_event(
            controller,
            run,
            event_type="run_created",
            technical_message=(
                f"Autopilot run {run_id} was created in {control_mode} mode."
            ),
            easy_message=(
                "BOBA created a controlled run and captured saved project state. "
                "No repair was executed."
            ),
            confirmed_fact="A controller run and bounded project snapshot were persisted.",
            assessment="The controller is ready to inspect saved evidence.",
        )
        self._transition(
            controller,
            run,
            "inspecting_project",
            reason="Run creation completed with a bounded project snapshot.",
            evidence_ids=[snapshot.project_snapshot_id],
        )
        return self._persist(controller)

    def inspect_run(
        self,
        project_id: str,
        run_id: str,
    ) -> BobaAutopilotControllerSetV1:
        """Load persisted run state without advancing it."""

        controller = self._load_controller(project_id)
        self._find_run(controller, run_id)
        return controller

    async def _refresh_snapshot(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotProjectSnapshotV1:
        snapshot = await self._capture_snapshot(run.project_id)
        existing = next(
            (
                item
                for item in reversed(controller.project_snapshots)
                if item.project_snapshot_id == snapshot.project_snapshot_id
            ),
            None,
        )
        if existing is None:
            controller.project_snapshots.append(snapshot)
            controller.project_snapshots = controller.project_snapshots[-512:]
        else:
            snapshot = existing
        run.project_snapshot_id = snapshot.project_snapshot_id
        run.rights_status = snapshot.rights_status
        run.safety_status = snapshot.safety_status
        run.updated_at = now_iso()
        return snapshot

    def _blocked_preflight_action(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        *,
        rights: bool,
        reason: str,
    ) -> BobaAutopilotActionV1:
        target: BobaAutopilotActionTargetV1 = (
            "rights_permission_gate" if rights else "safety_gate"
        )
        action = self._new_action(
            controller,
            run,
            action_type="human_review",
            target_module=target,
            target_operation="review",
            description=(
                "Review rights and permission state."
                if rights
                else "Review the blocking safety state."
            ),
            rationale=reason,
            expected_output="human_review_decision",
            risk_level="high",
        )
        action.status = "blocked"
        action.failure_summary = reason
        incident_type: BobaAutopilotIncidentTypeV1 = (
            "rights_block" if rights else "safety_block"
        )
        self._incident(
            controller,
            run,
            incident_type=incident_type,
            title="Rights review required" if rights else "Safety review required",
            summary=reason,
            severity="high",
            action=action,
            fingerprint=_digest([run.project_id, incident_type, reason]),
        )
        self._handoff(
            controller,
            run,
            target_module=(
                "rights_permission_gate" if rights else "safety_gate"
            ),
            reason=reason,
            action=action,
            blocking_conditions=[reason],
            failed_conditions=[reason],
            priority="critical",
        )
        self._handoff(
            controller,
            run,
            target_module="human_operator",
            reason=reason,
            action=action,
            blocking_conditions=[reason],
            failed_conditions=[reason],
            priority="critical",
        )
        return action

    def _latest_open_action(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotActionV1 | None:
        return next(
            (
                item
                for item in reversed(controller.planned_actions)
                if item.run_id == run.run_id
                and item.status in {"planned", "ready", "running", "awaiting_approval"}
            ),
            None,
        )

    async def plan_next_action(
        self,
        project_id: str,
        run_id: str,
    ) -> BobaAutopilotActionV1:
        """Plan one deterministic next action without executing it."""

        controller = self._load_controller(project_id)
        run = self._find_run(controller, run_id)
        if run.current_state in _TERMINAL_STATES:
            raise ValidationError(
                "Terminal BOBA Autopilot runs cannot plan another action.",
                details={"state": run.current_state},
            )
        if run.current_state == "paused":
            raise ValidationError("Paused BOBA Autopilot runs cannot plan actions.")
        open_action = self._latest_open_action(controller, run)
        if open_action is not None:
            return open_action
        snapshot = await self._refresh_snapshot(controller, run)
        usage = calculate_autopilot_budget_usage(controller, run)
        if usage.budget_exhausted:
            action = self._new_action(
                controller,
                run,
                action_type="stop_controller",
                target_module="autopilot_controller",
                target_operation="budget_stop",
                description="Stop because a hard recovery budget is exhausted.",
                rationale=", ".join(usage.exhausted_dimensions),
                risk_level="high",
            )
            action.status = "blocked"
            self._incident(
                controller,
                run,
                incident_type="budget_exhausted",
                title="Autopilot recovery budget exhausted",
                summary=", ".join(usage.exhausted_dimensions),
                severity="high",
                action=action,
                fingerprint=_digest([run.run_id, usage.exhausted_dimensions]),
            )
            self._append_event(
                controller,
                run,
                event_type="budget_exhausted",
                technical_message=(
                    "Autopilot stopped because hard budget dimensions were exhausted: "
                    f"{', '.join(usage.exhausted_dimensions)}."
                ),
                easy_message=(
                    "BOBA reached its safe recovery limit and stopped instead of "
                    "repeating work."
                ),
                severity="high",
                action=action,
                requires_attention=True,
                available_user_actions=["Review budget history", "Pause BOBA"],
            )
            self._transition(
                controller,
                run,
                "blocked",
                reason="A hard recovery budget was exhausted.",
                action=action,
                human_review_required=True,
            )
            self._persist(controller)
            return action

        if run.current_state == "inspecting_project":
            rights = snapshot.rights_status.casefold()
            safety = snapshot.safety_status.casefold()
            if rights in _RIGHTS_BLOCKED or rights not in _RIGHTS_CLEAR:
                explicit_block = rights in {
                    "blocked",
                    "permission_denied",
                    "not_allowed",
                    "do_not_process",
                }
                next_state: BobaAutopilotStateV1 = (
                    "blocked" if explicit_block else "rights_review_required"
                )
                self._transition(
                    controller,
                    run,
                    next_state,
                    reason=f"Rights state is {snapshot.rights_status}.",
                    evidence_ids=[snapshot.project_snapshot_id],
                    rights_gate_required=True,
                    human_review_required=True,
                )
                action = self._blocked_preflight_action(
                    controller,
                    run,
                    rights=True,
                    reason=(
                        f"Rights state {snapshot.rights_status} does not permit "
                        "automatic diagnostic progression."
                    ),
                )
                self._persist(controller)
                return action
            if safety in _SAFETY_BLOCKED or safety not in _SAFETY_CLEAR:
                explicit_block = safety in _SAFETY_BLOCKED
                next_state = "blocked" if explicit_block else "safety_review_required"
                self._transition(
                    controller,
                    run,
                    next_state,
                    reason=f"Safety state is {snapshot.safety_status}.",
                    evidence_ids=[snapshot.project_snapshot_id],
                    safety_gate_required=True,
                    human_review_required=True,
                )
                action = self._blocked_preflight_action(
                    controller,
                    run,
                    rights=False,
                    reason=(
                        f"Safety state {snapshot.safety_status} does not permit "
                        "automatic diagnostic progression."
                    ),
                )
                self._persist(controller)
                return action
            module_order: tuple[
                tuple[str, BobaAutopilotStateV1],
                ...,
            ] = (
                ("observer", "observer_required"),
                ("error_doctor", "diagnosis_required"),
                ("root_cause_analyzer", "root_cause_analysis_required"),
                ("repair_planner", "repair_planning_required"),
            )
            next_state = "awaiting_repair_decision"
            for module_name, required_state in module_order:
                state = snapshot.module_artifact_states.get(module_name, {})
                if state.get("status") in {"missing", "malformed", "stale"}:
                    next_state = required_state
                    break
            self._transition(
                controller,
                run,
                next_state,
                reason="Bounded artifact inspection selected the next required stage.",
                evidence_ids=[snapshot.project_snapshot_id],
            )

        action = self._plan_for_state(controller, run)
        loop_reason = detect_autopilot_loop(controller, run, action=action)
        if loop_reason:
            action.status = "blocked"
            action.failure_summary = loop_reason
            self._incident(
                controller,
                run,
                incident_type="loop_detected",
                title="Autopilot loop prevented",
                summary=loop_reason,
                severity="high",
                action=action,
                fingerprint=action.idempotency_key,
            )
            self._append_event(
                controller,
                run,
                event_type="controller_paused",
                technical_message=loop_reason,
                easy_message=(
                    "The same controller path repeated without new evidence. "
                    "BOBA stopped instead of looping."
                ),
                severity="high",
                action=action,
                requires_attention=True,
                available_user_actions=["Review incidents", "Cancel BOBA"],
            )
            self._transition(
                controller,
                run,
                "paused",
                reason=loop_reason,
                action=action,
                human_review_required=True,
            )
        self._persist(controller)
        return action

    def _plan_for_state(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotActionV1:
        state = run.current_state
        if state == "observer_required":
            return self._new_action(
                controller,
                run,
                action_type="generate_observer",
                target_module="observer",
                target_operation="generate",
                description="Generate a fresh read-only BOBA Observer report.",
                rationale="Observer evidence is missing, malformed, or stale.",
                expected_output="boba_observer_v1",
            )
        if state == "diagnosis_required":
            return self._new_action(
                controller,
                run,
                action_type="generate_error_doctor",
                target_module="error_doctor",
                target_operation="generate",
                description="Generate Error Doctor from the current Observer artifact.",
                rationale="Diagnosis is the next ordered read-only dependency.",
                expected_output="boba_error_doctor_v1",
            )
        if state == "root_cause_analysis_required":
            return self._new_action(
                controller,
                run,
                action_type="generate_root_cause_analyzer",
                target_module="root_cause_analyzer",
                target_operation="generate",
                description="Generate Root Cause Analyzer from Error Doctor evidence.",
                rationale="Root-cause ranking must precede repair planning.",
                expected_output="boba_root_cause_analyzer_v1",
            )
        if state == "repair_planning_required":
            return self._new_action(
                controller,
                run,
                action_type="generate_repair_planner",
                target_module="repair_planner",
                target_operation="generate",
                description="Generate advisory repair strategies and safety requirements.",
                rationale="Repair Planner consumes the current root-cause artifact.",
                expected_output="boba_repair_planner_v1",
            )
        if state == "awaiting_repair_decision":
            return self._plan_repair_route(controller, run)
        if state == "code_repair_ready":
            return self._plan_code_route(controller, run)
        if state == "tool_recovery_ready":
            return self._plan_tool_route(controller, run)
        if state == "technical_validation_required":
            return self._plan_technical_validation(controller, run)
        if state == "output_quality_review_required":
            return self._plan_quality_review(controller, run)
        if state == "checkpoint_recovery_required":
            action = self._new_action(
                controller,
                run,
                action_type="prepare_checkpoint_handoff",
                target_module="checkpoint_recovery_manager",
                target_operation="prepare_handoff",
                description="Prepare a checkpoint recovery handoff.",
                rationale="Autopilot V1 cannot create, repair, or restore checkpoints.",
                expected_output="checkpoint_recovery_handoff",
                risk_level="high",
            )
            self._handoff(
                controller,
                run,
                target_module="checkpoint_recovery_manager",
                reason=action.rationale,
                action=action,
                blocking_conditions=["A required checkpoint is not valid."],
                priority="critical",
            )
            return action
        if state == "human_quality_review_required":
            action = self._new_action(
                controller,
                run,
                action_type="human_review",
                target_module="human_operator",
                target_operation="quality_review",
                description="Review the bounded unresolved quality decision.",
                rationale="Automated evidence is insufficient for a safe decision.",
                expected_output="human_quality_decision",
                risk_level="medium",
            )
            self._handoff(
                controller,
                run,
                target_module="human_operator",
                reason=action.rationale,
                action=action,
                priority="high",
            )
            return action
        if state == "awaiting_safety_gate":
            return self._prepare_safety_handoff(controller, run)
        if state == "ready_for_workflow_controller":
            return self._prepare_workflow_handoff(controller, run)
        if state in {"rights_review_required", "safety_review_required"}:
            return self._blocked_preflight_action(
                controller,
                run,
                rights=state == "rights_review_required",
                reason=f"Controller state {state} requires external human review.",
            )
        raise ValidationError(
            "No BOBA Autopilot action can be planned for the current state.",
            details={"state": state},
        )

    def _selected_repair_case(self, project_id: str) -> Any | None:
        planner = self.store.load_boba_repair_planner(project_id)
        if planner is None or not planner.repair_cases:
            return None
        return sorted(
            planner.repair_cases,
            key=lambda item: (
                item.planning_status in {"plan_ready", "conditional_plan"},
                item.confidence,
                item.repair_case_id,
            ),
            reverse=True,
        )[0]

    def _plan_repair_route(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotActionV1:
        planner = self.store.load_boba_repair_planner(run.project_id)
        selected = self._selected_repair_case(run.project_id)
        if planner is None or selected is None:
            self._transition(
                controller,
                run,
                "root_cause_reanalysis_required",
                reason="Repair Planner output is missing or malformed.",
                human_review_required=True,
            )
            return self._new_action(
                controller,
                run,
                action_type="human_review",
                target_module="root_cause_analyzer",
                target_operation="review_missing_planner",
                description="Review missing Repair Planner evidence.",
                rationale="No valid repair case can be routed.",
                expected_output="root_cause_reanalysis_handoff",
            )
        status = selected.planning_status
        scope = selected.repair_scope
        if status in {"needs_more_evidence", "conflicting_causes", "unknown"}:
            self._transition(
                controller,
                run,
                "root_cause_reanalysis_required",
                reason=f"Repair Planner status is {status}.",
                evidence_ids=[selected.repair_case_id],
                human_review_required=status == "conflicting_causes",
            )
            return self._new_action(
                controller,
                run,
                action_type="human_review",
                target_module="root_cause_analyzer",
                target_operation="reanalyze",
                description="Request stronger root-cause evidence.",
                rationale=f"Repair Planner reported {status}.",
                parameters={"repair_case_id": selected.repair_case_id},
                expected_output="root_cause_reanalysis_handoff",
            )
        if status in {"intentional_safety_block", "blocked"}:
            self._transition(
                controller,
                run,
                "blocked",
                reason=selected.blocked_reason or f"Repair Planner status is {status}.",
                evidence_ids=[selected.repair_case_id],
                safety_gate_required=True,
                human_review_required=True,
            )
            return self._blocked_preflight_action(
                controller,
                run,
                rights=scope == "rights_permission",
                reason=selected.blocked_reason
                or "Repair Planner intentionally blocked repair.",
            )
        if scope == "rights_permission":
            self._transition(
                controller,
                run,
                "rights_review_required",
                reason="Repair Planner routed this case to rights review.",
                evidence_ids=[selected.repair_case_id],
                rights_gate_required=True,
                human_review_required=True,
            )
            return self._blocked_preflight_action(
                controller,
                run,
                rights=True,
                reason="Rights or permission evidence must be resolved first.",
            )
        if scope in {"checkpoint", "workflow"}:
            self._transition(
                controller,
                run,
                "checkpoint_recovery_required",
                reason=f"Repair scope {scope} requires a future checkpoint owner.",
                evidence_ids=[selected.checkpoint_plan_id],
                human_review_required=True,
            )
            return self._plan_for_state(controller, run)
        if scope == "code":
            self._transition(
                controller,
                run,
                "code_repair_ready",
                reason="Repair Planner selected a bounded code repair route.",
                evidence_ids=[selected.repair_case_id, selected.recommended_strategy_id],
                approval_required=True,
            )
            return self._plan_code_route(controller, run)
        handoff = next(
            (
                item
                for item in planner.execution_handoffs
                if item.repair_case_id == selected.repair_case_id
                and item.target_module == "tool_recovery_brain"
            ),
            None,
        )
        if scope == "tool" or handoff is not None:
            self._transition(
                controller,
                run,
                "tool_recovery_ready",
                reason="Repair Planner selected a bounded local tool recovery route.",
                evidence_ids=[selected.repair_case_id, selected.recommended_strategy_id],
                approval_required=True,
            )
            return self._plan_tool_route(controller, run)
        if scope in {"validation"}:
            self._transition(
                controller,
                run,
                "technical_validation_required",
                reason="Repair Planner requires validation rather than repair.",
                evidence_ids=[selected.validation_plan_id],
                human_review_required=True,
            )
            action = self._new_action(
                controller,
                run,
                action_type="prepare_validator_handoff",
                target_module="validator_runner",
                target_operation="prepare_handoff",
                description="Prepare a Validator Runner handoff.",
                rationale="Autopilot V1 does not execute arbitrary validators.",
                expected_output="validator_runner_handoff",
            )
            self._handoff(
                controller,
                run,
                target_module="validator_runner",
                reason=action.rationale,
                action=action,
                priority="high",
            )
            return action
        if status == "repair_not_required" or scope == "no_repair":
            quality = self.store.load_boba_output_quality_reviewer(run.project_id)
            if quality and quality.acceptance_decisions:
                self._transition(
                    controller,
                    run,
                    "output_quality_review_required",
                    reason="No repair is required; interpret the saved quality decision.",
                    evidence_ids=[quality.acceptance_decisions[-1].acceptance_decision_id],
                )
                return self._plan_quality_review(controller, run)
            self._transition(
                controller,
                run,
                "human_quality_review_required",
                reason="No repair is required, but no acceptable output-quality decision exists.",
                human_review_required=True,
            )
            return self._plan_for_state(controller, run)
        self._transition(
            controller,
            run,
            "human_quality_review_required",
            reason=f"Repair scope {scope} has no V1 execution owner.",
            human_review_required=True,
        )
        return self._plan_for_state(controller, run)

    def _checkpoint_for_action(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        action: BobaAutopilotActionV1,
    ) -> BobaAutopilotCheckpointRequirementV1:
        planner = self.store.load_boba_repair_planner(run.project_id)
        selected = self._selected_repair_case(run.project_id)
        checkpoint_plan = None
        rollback_plan = None
        if planner is not None and selected is not None:
            checkpoint_plan = next(
                (
                    item
                    for item in planner.checkpoint_plans
                    if item.checkpoint_plan_id == selected.checkpoint_plan_id
                ),
                None,
            )
            rollback_plan = next(
                (
                    item
                    for item in planner.rollback_plans
                    if item.rollback_plan_id == selected.rollback_plan_id
                ),
                None,
            )
        required = bool(
            checkpoint_plan and checkpoint_plan.checkpoint_required
        )
        reference = ""
        validated = False
        rollback_ready = bool(
            rollback_plan
            and rollback_plan.rollback_required
            and rollback_plan.rollback_steps
        )
        if action.target_module == "code_surgeon":
            code_report = self.store.load_boba_code_surgeon(run.project_id)
            proposal_id = _text(
                action.parameters.get("patch_proposal_id"),
                maximum=180,
            )
            proposal = next(
                (
                    item
                    for item in getattr(code_report, "patch_proposals", [])
                    if item.patch_proposal_id == proposal_id
                ),
                None,
            )
            if proposal is not None:
                reference = proposal.base_commit_sha
                validated = bool(
                    proposal.base_commit_sha
                    and proposal.applies_cleanly
                    and proposal.path_policy_passed
                )
        elif action.target_module == "tool_recovery_brain":
            tool_report = self.store.load_boba_tool_recovery(run.project_id)
            plan_id = _text(action.parameters.get("recovery_plan_id"), maximum=180)
            plan = next(
                (
                    item
                    for item in getattr(tool_report, "recovery_plans", [])
                    if item.recovery_plan_id == plan_id
                ),
                None,
            )
            recovery_case = next(
                (
                    item
                    for item in getattr(tool_report, "recovery_cases", [])
                    if plan is not None
                    and item.recovery_case_id == plan.recovery_case_id
                ),
                None,
            )
            if plan is not None:
                reference = _text(
                    plan.checkpoint_requirements.get("reference"),
                    maximum=500,
                )
                validated = bool(
                    not required
                    or (
                        recovery_case is not None
                        and recovery_case.checkpoint_ready
                        and reference
                    )
                )
                rollback_ready = bool(
                    recovery_case is not None and recovery_case.rollback_ready
                )
        if not required:
            status: BobaAutopilotCheckpointStatusV1 = "not_required"
            validated = True
        elif not reference:
            status = "missing"
        elif validated:
            status = "valid"
        else:
            status = "unverified"
        requirement = BobaAutopilotCheckpointRequirementV1(
            checkpoint_requirement_id=_stable_id(
                "autopilot_checkpoint",
                run.run_id,
                action.action_id,
                reference,
            ),
            run_id=run.run_id,
            required=required,
            requirement_source=(
                checkpoint_plan.checkpoint_plan_id if checkpoint_plan else ""
            ),
            checkpoint_reference=reference,
            checkpoint_status=status,
            checkpoint_validated=validated,
            checkpoint_artifact_digest=_digest(reference) if reference else "",
            state_preservation_required=(
                checkpoint_plan.state_to_preserve if checkpoint_plan else []
            ),
            source_media_protected=True,
            accepted_outputs_protected=True,
            rollback_plan_reference=(
                rollback_plan.rollback_plan_id if rollback_plan else ""
            ),
            rollback_ready=rollback_ready or not required,
            blocks_execution=required and (not validated or not rollback_ready),
            human_review_required=required,
            warnings=[
                "Autopilot checked persisted checkpoint evidence only.",
                "Autopilot did not create, repair, or restore a checkpoint.",
            ],
        )
        existing = next(
            (
                item
                for item in controller.checkpoint_requirements
                if item.checkpoint_requirement_id
                == requirement.checkpoint_requirement_id
            ),
            None,
        )
        if existing is None:
            controller.checkpoint_requirements.append(requirement)
            controller.checkpoint_requirements = (
                controller.checkpoint_requirements[-512:]
            )
        else:
            requirement = existing
        run.checkpoint_requirement_id = requirement.checkpoint_requirement_id
        controller.signal_usage.checkpoint_reference_used = bool(reference)
        return requirement

    def _plan_code_route(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotActionV1:
        selected = self._selected_repair_case(run.project_id)
        report = self.store.load_boba_code_surgeon(run.project_id)
        proposal = next(
            (
                item
                for item in reversed(getattr(report, "patch_proposals", []))
                if item.execution_status in {"validation_ready", "validation_passed"}
            ),
            None,
        )
        if proposal is None:
            return self._new_action(
                controller,
                run,
                action_type="invoke_code_surgeon",
                target_module="code_surgeon",
                target_operation="proposal_only",
                description="Prepare a proposal-only Code Surgeon review package.",
                rationale=(
                    "No executable patch exists. Autopilot cannot invent a diff or "
                    "approve a patch."
                ),
                parameters={
                    "repair_case_id": getattr(selected, "repair_case_id", ""),
                    "repair_strategy_id": getattr(
                        selected,
                        "recommended_strategy_id",
                        "",
                    ),
                },
                expected_output="boba_code_surgeon_v1",
                risk_level="low",
            )
        action = self._new_action(
            controller,
            run,
            action_type="invoke_code_surgeon",
            target_module="code_surgeon",
            target_operation="execute_approved",
            description="Coordinate one exact approved isolated Code Surgeon patch.",
            rationale=(
                "The persisted proposal is validation-ready but remains unapproved "
                "by Autopilot."
            ),
            parameters={
                "patch_proposal_id": proposal.patch_proposal_id,
                "repair_case_id": proposal.code_repair_case_id,
                "target_artifact_digest": proposal.diff_sha256,
                "base_commit_sha": proposal.base_commit_sha,
            },
            expected_output="boba_code_surgeon_v1",
            risk_level=proposal.risk_level,
            timeout_seconds=1_800,
        )
        self._checkpoint_for_action(controller, run, action)
        if run.current_state != "awaiting_execution_approval":
            self._transition(
                controller,
                run,
                "awaiting_execution_approval",
                reason="Code repair requires exact Code Surgeon approval.",
                action=action,
                evidence_ids=[proposal.patch_proposal_id, proposal.diff_sha256],
                approval_required=True,
                human_review_required=True,
            )
        return action

    def _plan_tool_route(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotActionV1:
        selected = self._selected_repair_case(run.project_id)
        report = self.store.load_boba_tool_recovery(run.project_id)
        plan = next(
            (
                item
                for item in reversed(getattr(report, "recovery_plans", []))
                if item.execution_status in {"not_started", "ready"}
            ),
            None,
        )
        if plan is None:
            handoff_id = ""
            planner = self.store.load_boba_repair_planner(run.project_id)
            if planner is not None and selected is not None:
                handoff = next(
                    (
                        item
                        for item in planner.execution_handoffs
                        if item.repair_case_id == selected.repair_case_id
                        and item.target_module == "tool_recovery_brain"
                    ),
                    None,
                )
                handoff_id = handoff.handoff_id if handoff else ""
            return self._new_action(
                controller,
                run,
                action_type="invoke_tool_recovery",
                target_module="tool_recovery_brain",
                target_operation="plan",
                description="Generate a bounded Tool Recovery plan without executing it.",
                rationale="A Tool Recovery handoff exists but no current recovery plan exists.",
                parameters={
                    "selected_handoff_id": handoff_id,
                    "selected_repair_strategy_id": getattr(
                        selected,
                        "recommended_strategy_id",
                        "",
                    ),
                },
                expected_output="boba_tool_recovery_brain_v1",
            )
        strategy = next(
            (
                item
                for item in plan.ordered_strategies
                if item.execution_allowed
            ),
            plan.ordered_strategies[0] if plan.ordered_strategies else None,
        )
        if strategy is None:
            self._transition(
                controller,
                run,
                "human_quality_review_required",
                reason="Tool Recovery has no bounded strategy to review.",
                human_review_required=True,
            )
            return self._plan_for_state(controller, run)
        action = self._new_action(
            controller,
            run,
            action_type="invoke_tool_recovery",
            target_module="tool_recovery_brain",
            target_operation="execute_approved",
            description="Coordinate one exact approved Tool Recovery strategy.",
            rationale=(
                "The selected strategy is persisted, bounded, and still requires "
                "its own exact target-module approval."
            ),
            parameters={
                "recovery_plan_id": plan.recovery_plan_id,
                "recovery_strategy_id": strategy.recovery_strategy_id,
                "recovery_case_id": plan.recovery_case_id,
                "tool_id": strategy.tool_id,
                "configuration_overrides": strategy.configuration_overrides,
                "retry_budget": plan.retry_budget,
                "time_budget_seconds": plan.time_budget_seconds,
                "quality_requirements": plan.quality_requirements,
                "checkpoint_reference": plan.checkpoint_requirements.get(
                    "reference",
                    "",
                ),
                "target_artifact_digest": _digest(
                    {
                        "plan": plan.model_dump(mode="json"),
                        "strategy": strategy.model_dump(mode="json"),
                    }
                ),
            },
            expected_output="boba_tool_recovery_brain_v1",
            risk_level="medium",
            timeout_seconds=min(plan.time_budget_seconds, 1_800),
        )
        self._checkpoint_for_action(controller, run, action)
        if run.current_state != "awaiting_execution_approval":
            self._transition(
                controller,
                run,
                "awaiting_execution_approval",
                reason="Tool recovery requires exact Tool Recovery approval.",
                action=action,
                evidence_ids=[
                    plan.recovery_plan_id,
                    strategy.recovery_strategy_id,
                ],
                approval_required=True,
                human_review_required=True,
            )
        return action

    def _plan_technical_validation(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotActionV1:
        report = self.store.load_boba_tool_recovery(run.project_id)
        attempt = next(
            (
                item
                for item in reversed(getattr(report, "recovery_attempts", []))
                if item.status in {"succeeded_pending_validation", "completed"}
            ),
            None,
        )
        if attempt is None:
            action = self._new_action(
                controller,
                run,
                action_type="prepare_validator_handoff",
                target_module="validator_runner",
                target_operation="prepare_handoff",
                description="Prepare a validator handoff for missing technical evidence.",
                rationale="No recoverable output attempt is available for typed validation.",
                expected_output="validator_runner_handoff",
            )
            self._handoff(
                controller,
                run,
                target_module="validator_runner",
                reason=action.rationale,
                action=action,
                priority="high",
            )
            return action
        validation = next(
            (
                item
                for item in reversed(getattr(report, "output_validations", []))
                if item.recovery_attempt_id == attempt.recovery_attempt_id
            ),
            None,
        )
        if validation is not None:
            if validation.accepted_for_quality_review and validation.required_checks_passed:
                self._transition(
                    controller,
                    run,
                    "output_quality_review_required",
                    reason="Typed Tool Recovery validation passed.",
                    evidence_ids=[validation.output_validation_id],
                )
                return self._plan_quality_review(controller, run)
            self._transition(
                controller,
                run,
                "repair_replanning_required",
                reason=validation.rejected_reason
                or "Typed Tool Recovery validation failed.",
                evidence_ids=[validation.output_validation_id],
                human_review_required=True,
            )
            action = self._new_action(
                controller,
                run,
                action_type="human_review",
                target_module="repair_planner",
                target_operation="replan",
                description="Return failed technical validation to Repair Planner.",
                rationale=validation.rejected_reason
                or "Required technical checks did not pass.",
                expected_output="repair_replanning_handoff",
            )
            self._handoff(
                controller,
                run,
                target_module="repair_planner",
                reason=action.rationale,
                action=action,
                priority="critical",
            )
            return action
        plan = next(
            (
                item
                for item in getattr(report, "recovery_plans", [])
                if item.recovery_plan_id == attempt.recovery_plan_id
            ),
            None,
        )
        return self._new_action(
            controller,
            run,
            action_type="invoke_tool_recovery",
            target_module="tool_recovery_brain",
            target_operation="validate_output",
            description="Coordinate typed validation of the recovered output.",
            rationale=(
                "Technical success is not final acceptance; the exact recovery "
                "output must pass its registered validation."
            ),
            parameters={
                "recovery_attempt_id": attempt.recovery_attempt_id,
                "recovery_plan_id": attempt.recovery_plan_id,
                "recovery_strategy_id": attempt.recovery_strategy_id,
                "target_artifact_digest": _digest(attempt.output_artifact_refs),
                "quality_requirements": (
                    plan.quality_requirements if plan is not None else []
                ),
            },
            expected_output="boba_tool_recovery_brain_v1",
            risk_level="low",
            timeout_seconds=300,
        )

    def _latest_quality_decision(self, project_id: str) -> Any | None:
        report = self.store.load_boba_output_quality_reviewer(project_id)
        if report is None or not report.acceptance_decisions:
            return None
        return report.acceptance_decisions[-1]

    def _quality_output_reference(self, project_id: str) -> str:
        tool_report = self.store.load_boba_tool_recovery(project_id)
        validation = next(
            (
                item
                for item in reversed(getattr(tool_report, "output_validations", []))
                if item.accepted_for_quality_review and item.output_artifact_ref
            ),
            None,
        )
        if validation is not None:
            return _text(validation.output_artifact_ref, maximum=500)
        context_report = self.store.load_boba_output_quality_reviewer(project_id)
        artifact = next(
            (
                item
                for item in reversed(getattr(context_report, "output_artifacts", []))
                if item.sanitized_artifact_reference
            ),
            None,
        )
        return (
            _text(artifact.sanitized_artifact_reference, maximum=500)
            if artifact is not None
            else ""
        )

    def _plan_quality_review(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotActionV1:
        decision = self._latest_quality_decision(run.project_id)
        if decision is not None:
            return self._interpret_quality_decision(controller, run, decision)
        output_reference = self._quality_output_reference(run.project_id)
        if not output_reference:
            self._transition(
                controller,
                run,
                "human_quality_review_required",
                reason="No exact output artifact is available for quality review.",
                human_review_required=True,
            )
            return self._plan_for_state(controller, run)
        return self._new_action(
            controller,
            run,
            action_type="invoke_output_quality_review",
            target_module="output_quality_reviewer",
            target_operation="artifact_review",
            description="Generate an artifact-only Output Quality Reviewer decision.",
            rationale=(
                "A technically validated output still requires independent quality review."
            ),
            parameters={
                "output_reference": output_reference,
                "rights_status": run.rights_status,
                "safety_status": run.safety_status,
                "review_mode": "artifact_only",
            },
            expected_output="boba_output_quality_reviewer_v1",
            risk_level="low",
            timeout_seconds=300,
        )

    def _interpret_quality_decision(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        quality_decision: Any,
    ) -> BobaAutopilotActionV1:
        value = _text(getattr(quality_decision, "decision", ""), maximum=120)
        evidence_id = _text(
            getattr(quality_decision, "acceptance_decision_id", ""),
            maximum=180,
        )
        decision = BobaAutopilotDecisionV1(
            decision_id=_stable_id(
                "autopilot_decision",
                run.run_id,
                evidence_id,
                value,
            ),
            run_id=run.run_id,
            decision_type="quality_routing",
            decision=value or "unknown",
            reason=_text(
                getattr(quality_decision, "decision_summary", ""),
                maximum=900,
            )
            or "Output Quality Reviewer produced no bounded summary.",
            evidence_ids=_unique([evidence_id], limit=64, maximum=180),
            confidence=float(getattr(quality_decision, "confidence", 0.0) or 0.0),
            rights_clear=bool(
                getattr(quality_decision, "rights_clear_for_processing", False)
            ),
            safety_clear=bool(
                getattr(quality_decision, "safety_clear_for_processing", False)
            ),
            approval_clear=False,
            budget_clear=not calculate_autopilot_budget_usage(
                controller,
                run,
            ).budget_exhausted,
            checkpoint_clear=True,
            quality_clear=value
            in {
                "accepted_for_next_internal_stage",
                "accepted_with_disclosed_limitations",
            },
            human_review_required=bool(
                getattr(quality_decision, "human_review_required", True)
            ),
            next_state="unknown",
            source="output_quality_reviewer",
            limitations=[
                "Autopilot cannot override the Output Quality Reviewer decision."
            ],
        )
        existing = next(
            (
                item
                for item in controller.decisions
                if item.decision_id == decision.decision_id
            ),
            None,
        )
        if existing is None:
            controller.decisions.append(decision)
            run.decision_ids.append(decision.decision_id)
        else:
            decision = existing
        if value == "accepted_for_next_internal_stage":
            decision.next_state = "awaiting_safety_gate"
            self._transition(
                controller,
                run,
                "awaiting_safety_gate",
                reason="Output Quality Reviewer accepted the output for the next internal gate.",
                evidence_ids=[evidence_id],
                safety_gate_required=True,
            )
            return self._prepare_safety_handoff(controller, run)
        if value == "accepted_with_disclosed_limitations":
            decision.next_state = "human_quality_review_required"
            self._transition(
                controller,
                run,
                "human_quality_review_required",
                reason="Disclosed limitations require explicit human review.",
                evidence_ids=[evidence_id],
                human_review_required=True,
            )
            return self._plan_for_state(controller, run)
        if value == "needs_human_review":
            decision.next_state = "human_quality_review_required"
            self._transition(
                controller,
                run,
                "human_quality_review_required",
                reason="Output Quality Reviewer requires subjective human review.",
                evidence_ids=[evidence_id],
                human_review_required=True,
            )
            return self._plan_for_state(controller, run)
        if value == "needs_more_evidence":
            decision.next_state = "human_quality_review_required"
            action = self._new_action(
                controller,
                run,
                action_type="prepare_validator_handoff",
                target_module="validator_runner",
                target_operation="prepare_handoff",
                description="Prepare a Validator Runner handoff for missing quality evidence.",
                rationale="Output Quality Reviewer needs more registered evidence.",
                expected_output="validator_runner_handoff",
            )
            self._handoff(
                controller,
                run,
                target_module="validator_runner",
                reason=action.rationale,
                action=action,
                decision=decision,
                priority="high",
            )
            self._transition(
                controller,
                run,
                "human_quality_review_required",
                reason="Missing quality evidence cannot be fabricated.",
                action=action,
                evidence_ids=[evidence_id],
                human_review_required=True,
            )
            return action
        if value == "rejected_technical":
            decision.next_state = "root_cause_reanalysis_required"
            target_state: BobaAutopilotStateV1 = "root_cause_reanalysis_required"
            target_module: BobaAutopilotHandoffTargetV1 = "root_cause_analyzer"
        elif value in {"rejected_quality", "rejected_regression"}:
            decision.next_state = "repair_replanning_required"
            target_state = "repair_replanning_required"
            target_module = "repair_planner"
        elif value == "blocked_rights":
            decision.next_state = "rights_review_required"
            target_state = "rights_review_required"
            target_module = "rights_permission_gate"
        elif value == "blocked_safety":
            decision.next_state = "safety_review_required"
            target_state = "safety_review_required"
            target_module = "safety_gate"
        else:
            decision.next_state = "human_quality_review_required"
            target_state = "human_quality_review_required"
            target_module = "human_operator"
        self._incident(
            controller,
            run,
            incident_type=(
                "rights_block"
                if value == "blocked_rights"
                else "safety_block"
                if value == "blocked_safety"
                else "quality_rejection"
            ),
            title="Output Quality Reviewer stopped progression",
            summary=decision.reason,
            severity="high",
            fingerprint=_digest([evidence_id, value]),
        )
        self._transition(
            controller,
            run,
            target_state,
            reason=decision.reason,
            evidence_ids=[evidence_id],
            human_review_required=True,
            rights_gate_required=value == "blocked_rights",
            safety_gate_required=value == "blocked_safety",
        )
        action = self._new_action(
            controller,
            run,
            action_type="human_review",
            target_module=target_module,
            target_operation="review_quality_rejection",
            description=f"Route {value.replace('_', ' ')} for bounded review.",
            rationale=decision.reason,
            expected_output="quality_rejection_handoff",
            risk_level="high",
        )
        self._handoff(
            controller,
            run,
            target_module=target_module,
            reason=decision.reason,
            action=action,
            decision=decision,
            priority="critical",
        )
        return action

    def _prepare_safety_handoff(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotActionV1:
        action = self._new_action(
            controller,
            run,
            action_type="prepare_safety_handoff",
            target_module="safety_gate",
            target_operation="prepare_handoff",
            description="Prepare the future Safety Gate handoff.",
            rationale=(
                "Quality review is acceptable, but Autopilot cannot make the "
                "independent safety decision."
            ),
            expected_output="safety_gate_handoff",
        )
        for target in (
            "safety_gate",
            "workflow_controller",
            "final_decision_bus",
            "live_companion",
        ):
            self._handoff(
                controller,
                run,
                target_module=target,
                reason=(
                    "Receive bounded internal-cycle evidence without automatic "
                    "workflow continuation."
                ),
                action=action,
                required_inputs=[
                    "Latest Output Quality Reviewer decision",
                    "Current rights and safety status",
                    "Controller budget, checkpoint, and incident summary",
                ],
                priority="high",
            )
        action.status = "succeeded"
        action.completed_at = now_iso()
        action.result_reference = "bounded_safety_handoffs"
        run.completed_action_ids = _unique(
            [*run.completed_action_ids, action.action_id],
            limit=256,
            maximum=180,
        )
        run.active_action_id = None
        if run.current_state == "awaiting_safety_gate":
            self._transition(
                controller,
                run,
                "ready_for_workflow_controller",
                reason=(
                    "Required Safety Gate, Workflow Controller, Final Decision Bus, "
                    "and Live Companion handoffs were prepared without applying them."
                ),
                action=action,
                safety_gate_required=True,
            )
            self._prepare_workflow_handoff(controller, run)
        return action

    def _prepare_workflow_handoff(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
    ) -> BobaAutopilotActionV1:
        action = self._new_action(
            controller,
            run,
            action_type="prepare_workflow_handoff",
            target_module="workflow_controller",
            target_operation="prepare_handoff",
            description="Prepare the future Workflow Controller handoff.",
            rationale="Autopilot has no authority to resume the Olympus workflow.",
            expected_output="workflow_controller_handoff",
        )
        self._handoff(
            controller,
            run,
            target_module="workflow_controller",
            reason=action.rationale,
            action=action,
            priority="high",
        )
        action.status = "succeeded"
        action.completed_at = now_iso()
        action.result_reference = "bounded_workflow_controller_handoff"
        run.completed_action_ids = _unique(
            [*run.completed_action_ids, action.action_id],
            limit=256,
            maximum=180,
        )
        run.active_action_id = None
        if run.current_state == "ready_for_workflow_controller":
            self._transition(
                controller,
                run,
                "completed_internal_cycle",
                reason=(
                    "The bounded internal diagnostic, validation, quality, safety, "
                    "and workflow handoffs are complete. Olympus remains paused."
                ),
                action=action,
            )
            self._append_event(
                controller,
                run,
                event_type="internal_cycle_completed",
                technical_message=(
                    "Autopilot completed its internal cycle without invoking workflow "
                    "resume, publication, deployment, push, or merge."
                ),
                easy_message=(
                    "The output passed review. BOBA prepared the next Safety Gate and "
                    "Workflow Controller handoffs, but Olympus has not resumed."
                ),
                action=action,
                confirmed_fact="Only bounded handoffs were prepared.",
            )
            if run.control_mode != "advisory_only":
                self.store.release_boba_autopilot_lock(
                    run.project_id,
                    run_id=run.run_id,
                    owner_identifier=self.lock_owner,
                )
                controller.lock_metadata = None
        return action

    def _consume_action_budget(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        action: BobaAutopilotActionV1,
        *,
        invocation: bool,
    ) -> None:
        budget = _budget_for_run(controller, run)
        usage = calculate_autopilot_budget_usage(controller, run)
        if usage.budget_exhausted:
            raise ValidationError(
                "BOBA Autopilot recovery budget is exhausted.",
                details={"dimensions": usage.exhausted_dimensions},
            )
        usage.actions_used += 1
        if invocation:
            usage.module_invocations_used += 1
        if action.action_class == "approval_required_execution":
            usage.execution_actions_used += 1
        if action.target_module == "code_surgeon" and action.target_operation in {
            "execute_approved",
            "prepare_local_commit",
        }:
            usage.code_repair_attempts_used += 1
        if action.target_module == "tool_recovery_brain" and action.target_operation in {
            "execute_approved",
            "rollback",
        }:
            usage.tool_recovery_attempts_used += 1
        if action.target_module == "output_quality_reviewer":
            usage.quality_review_attempts_used += 1
        risk_cost = {
            "low": 5.0,
            "medium": 20.0,
            "high": 40.0,
            "critical": 70.0,
        }.get(action.risk_level, 10.0)
        usage.current_risk_score = max(usage.current_risk_score, risk_cost)
        calculate_autopilot_budget_usage(controller, run)
        ratios = {
            "actions": usage.actions_used / budget.maximum_total_actions,
            "invocations": (
                usage.module_invocations_used / budget.maximum_module_invocations
            ),
            "time": (
                usage.total_duration_seconds / budget.maximum_total_duration_seconds
            ),
        }
        highest = max(ratios.values(), default=0.0)
        threshold = 100 if highest >= 1.0 else 90 if highest >= 0.9 else 70 if highest >= 0.7 else 0
        warning_key = f"budget_warning_{threshold}"
        if threshold and warning_key not in usage.warnings:
            usage.warnings.append(warning_key)
            self._append_event(
                controller,
                run,
                event_type=(
                    "budget_exhausted" if threshold == 100 else "budget_warning"
                ),
                technical_message=(
                    f"Autopilot recovery budget reached at least {threshold}% usage."
                ),
                easy_message=(
                    f"BOBA has used at least {threshold}% of its safe recovery limit."
                ),
                severity="high" if threshold >= 90 else "warning",
                action=action,
                requires_attention=threshold >= 90,
            )

    @staticmethod
    def _invocation_mode(
        action: BobaAutopilotActionV1,
    ) -> BobaAutopilotInvocationModeV1:
        if action.action_class == "automatic_read_only":
            return (
                "read_only_generation"
                if action.target_operation in {
                    "generate",
                    "plan",
                    "proposal_only",
                    "artifact_review",
                }
                else "read_only_inspection"
            )
        if action.target_operation == "rollback":
            return "approved_rollback"
        if action.action_class == "approval_required_execution":
            return "approved_execution"
        if action.action_class == "future_gated":
            return "advisory_handoff"
        return "read_only_inspection"

    def _set_module_signal(
        self,
        controller: BobaAutopilotControllerSetV1,
        module_name: str,
    ) -> None:
        mapping = {
            "observer": "observer_used",
            "error_doctor": "error_doctor_used",
            "root_cause_analyzer": "root_cause_analyzer_used",
            "repair_planner": "repair_planner_used",
            "code_surgeon": "code_surgeon_used",
            "tool_recovery_brain": "tool_recovery_used",
            "output_quality_reviewer": "output_quality_reviewer_used",
            "rights_permission_gate": "rights_gate_used",
        }
        field = mapping.get(module_name)
        if field:
            setattr(controller.signal_usage, field, True)

    async def _invoke_action(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        action: BobaAutopilotActionV1,
        *,
        approval_verified: bool,
        invocation_parameters: Mapping[str, Any] | None = None,
    ) -> tuple[BobaAutopilotModuleInvocationV1, Mapping[str, Any]]:
        if self.module_invoker is None:
            raise ValidationError(
                "The typed BOBA Autopilot module registry is unavailable."
            )
        allowed = {
            "observer": {"generate"},
            "error_doctor": {"generate"},
            "root_cause_analyzer": {"generate"},
            "repair_planner": {"generate"},
            "code_surgeon": {
                "proposal_only",
                "validate_proposal",
                "execute_approved",
                "prepare_local_commit",
            },
            "tool_recovery_brain": {
                "plan",
                "health_check",
                "execute_approved",
                "validate_output",
                "rollback",
            },
            "output_quality_reviewer": {
                "artifact_review",
                "technical_review",
                "baseline_compare",
                "human_review",
            },
        }
        if action.target_module not in allowed or action.target_operation not in allowed[
            action.target_module
        ]:
            raise ValidationError(
                "Autopilot rejected an arbitrary module or operation.",
                details={
                    "target_module": action.target_module,
                    "target_operation": action.target_operation,
                },
            )
        invocation = BobaAutopilotModuleInvocationV1(
            module_invocation_id=_stable_id(
                "autopilot_invocation",
                run.run_id,
                action.action_id,
                len(controller.module_invocations) + 1,
            ),
            run_id=run.run_id,
            action_id=action.action_id,
            module_name=action.target_module,
            operation_name=action.target_operation,
            invocation_mode=self._invocation_mode(action),
            input_reference_ids=action.input_artifact_ids,
            approval_verified=approval_verified,
            status="running",
        )
        controller.module_invocations.append(invocation)
        controller.module_invocations = controller.module_invocations[-2_000:]
        run.active_module_invocation_id = invocation.module_invocation_id
        self._append_event(
            controller,
            run,
            event_type=(
                "quality_review_started"
                if action.target_module == "output_quality_reviewer"
                else "recovery_started"
                if action.target_module == "tool_recovery_brain"
                and action.target_operation in {"execute_approved", "rollback"}
                else "module_started"
            ),
            technical_message=(
                f"Typed invocation started: {action.target_module}."
                f"{action.target_operation}."
            ),
            easy_message=(
                f"BOBA started the registered {action.target_module.replace('_', ' ')} "
                "step. No arbitrary command was accepted."
            ),
            action=action,
            module_name=action.target_module,
            confirmed_fact="A registered typed module operation started.",
        )
        parameters = dict(action.parameters)
        parameters.update(dict(invocation_parameters or {}))
        parameters["project_id"] = run.project_id
        try:
            result = await self.module_invoker(
                action.target_module,
                action.target_operation,
                parameters,
            )
        except Exception as exc:
            invocation.status = "failed"
            invocation.invocation_completed_at = now_iso()
            invocation.failure_class = exc.__class__.__name__
            invocation.failure_summary = _text(exc, maximum=1_200)
            invocation.retryable = False
            run.active_module_invocation_id = None
            raise
        safe_result = _json_safe(result)
        if not isinstance(safe_result, Mapping) or not safe_result:
            invocation.status = "failed"
            invocation.invocation_completed_at = now_iso()
            invocation.failure_class = "malformed_artifact"
            invocation.failure_summary = "Typed module returned no bounded mapping."
            run.active_module_invocation_id = None
            raise ValidationError("Typed BOBA module returned malformed output.")
        invocation.status = "succeeded"
        invocation.invocation_completed_at = now_iso()
        invocation.independently_revalidated_by_target = approval_verified
        invocation.output_reference_ids = _unique(
            [
                safe_result.get("schema_version"),
                safe_result.get("project_id"),
                safe_result.get("source_id"),
            ],
            limit=64,
            maximum=180,
        )
        invocation.bounded_result_summary = _text(
            (
                f"{action.target_module}.{action.target_operation} returned "
                f"{safe_result.get('schema_version', 'a bounded result')}."
            ),
            maximum=1_200,
        )
        invocation.changed_project_state = True
        invocation.source_media_untouched = True
        invocation.accepted_outputs_untouched = True
        run.active_module_invocation_id = None
        self._set_module_signal(controller, action.target_module)
        return invocation, safe_result

    async def _execute_safe_read_only_action(
        self,
        project_id: str,
        run_id: str,
        action_id: str,
    ) -> BobaAutopilotControllerSetV1:
        controller = self._load_controller(project_id)
        run = self._find_run(controller, run_id)
        action = self._action(controller, action_id)
        if action.run_id != run.run_id:
            raise ValidationError("Autopilot action belongs to another run.")
        if action.action_class != "automatic_read_only":
            raise ValidationError(
                "Safe advancement stopped before an approval-required action."
            )
        if action.status == "succeeded":
            return controller
        if action.status != "planned":
            raise ValidationError(
                "Autopilot action is not ready for safe read-only execution.",
                details={"status": action.status},
            )
        if run.control_mode == "advisory_only":
            raise ValidationError("Advisory-only runs do not invoke modules.")
        budget = _budget_for_run(controller, run)
        if not budget.automatic_read_only_allowed:
            raise ValidationError("Automatic read-only progression is disabled.")
        snapshot = await self._capture_snapshot(project_id)
        if snapshot.snapshot_sha256 != action.planned_snapshot_sha256:
            action.status = "blocked"
            action.failure_summary = "Project snapshot changed after action planning."
            self._incident(
                controller,
                run,
                incident_type="stale_artifact",
                title="Stale Autopilot action",
                summary=action.failure_summary,
                severity="high",
                action=action,
                fingerprint=action.idempotency_key,
            )
            self._persist(controller)
            raise ValidationError("Stale BOBA Autopilot action was blocked.")
        self._consume_action_budget(
            controller,
            run,
            action,
            invocation=action.target_module != "autopilot_controller",
        )
        action.status = "running"
        action.started_at = now_iso()
        run.active_action_id = action.action_id
        try:
            if action.target_module == "autopilot_controller":
                result: Mapping[str, Any] = {
                    "schema_version": "boba_autopilot_internal_v1",
                    "project_id": project_id,
                }
            else:
                _invocation, result = await self._invoke_action(
                    controller,
                    run,
                    action,
                    approval_verified=False,
                )
            action.status = "succeeded"
            action.completed_at = now_iso()
            action.result_reference = _text(
                result.get("schema_version") or action.expected_output_artifact_type,
                maximum=500,
            )
            run.completed_action_ids = _unique(
                [*run.completed_action_ids, action.action_id],
                limit=256,
                maximum=180,
            )
            run.active_action_id = None
            await self._refresh_snapshot(controller, run)
            self._post_safe_success(controller, run, action, result)
            self._append_event(
                controller,
                run,
                event_type=(
                    "quality_review_completed"
                    if action.target_module == "output_quality_reviewer"
                    else "module_completed"
                ),
                technical_message=(
                    f"Typed action {action.action_id} completed successfully."
                ),
                easy_message=(
                    f"BOBA completed the registered "
                    f"{action.target_module.replace('_', ' ')} step."
                ),
                action=action,
                module_name=action.target_module,
                confirmed_fact="The typed action returned a persisted bounded result.",
            )
        except Exception as exc:
            action.status = "failed"
            action.completed_at = now_iso()
            action.failure_summary = _text(exc, maximum=1_200)
            run.failed_action_ids = _unique(
                [*run.failed_action_ids, action.action_id],
                limit=256,
                maximum=180,
            )
            run.active_action_id = None
            incident_type: BobaAutopilotIncidentTypeV1 = (
                "malformed_artifact"
                if "malformed" in str(exc).casefold()
                else "module_failure"
            )
            self._incident(
                controller,
                run,
                incident_type=incident_type,
                title="Safe BOBA module invocation failed",
                summary=action.failure_summary,
                severity="high",
                action=action,
                fingerprint=_digest(
                    [action.idempotency_key, exc.__class__.__name__, str(exc)]
                ),
            )
            self._append_event(
                controller,
                run,
                event_type="module_failed",
                technical_message=action.failure_summary,
                easy_message=(
                    "The registered BOBA step failed. Autopilot stopped and "
                    "preserved the evidence."
                ),
                severity="high",
                action=action,
                module_name=action.target_module,
                requires_attention=True,
                available_user_actions=["Review incident", "Pause BOBA"],
            )
            if run.current_state not in _TERMINAL_STATES:
                self._transition(
                    controller,
                    run,
                    "paused",
                    reason="A safe typed module invocation failed.",
                    action=action,
                    human_review_required=True,
                )
            self._persist(controller)
            raise
        return self._persist(controller)

    def _post_safe_success(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        action: BobaAutopilotActionV1,
        result: Mapping[str, Any],
    ) -> None:
        if action.action_type == "generate_observer":
            self._transition(
                controller,
                run,
                "diagnosis_required",
                reason="Observer generation completed.",
                action=action,
                triggering_module="observer",
            )
        elif action.action_type == "generate_error_doctor":
            cases = result.get("diagnostic_cases")
            diagnostic_cases = cases if isinstance(cases, list) else []
            statuses = [
                _text(item.get("diagnosis_status"), maximum=80)
                for item in diagnostic_cases
                if isinstance(item, Mapping)
            ]
            if statuses and all(
                value in {"insufficient_evidence", "conflicting_evidence", "unknown"}
                for value in statuses
            ):
                self._transition(
                    controller,
                    run,
                    "human_quality_review_required",
                    reason="Error Doctor reported insufficient or conflicting evidence.",
                    action=action,
                    triggering_module="error_doctor",
                    human_review_required=True,
                )
            else:
                self._transition(
                    controller,
                    run,
                    "root_cause_analysis_required",
                    reason="Error Doctor generation completed.",
                    action=action,
                    triggering_module="error_doctor",
                )
        elif action.action_type == "generate_root_cause_analyzer":
            cases = result.get("analysis_cases")
            analysis_cases = cases if isinstance(cases, list) else []
            statuses = [
                _text(item.get("analysis_status"), maximum=80)
                for item in analysis_cases
                if isinstance(item, Mapping)
            ]
            if statuses and all(
                value
                in {
                    "insufficient_evidence",
                    "conflicting_evidence",
                    "intentional_safety_block",
                    "unknown",
                }
                for value in statuses
            ):
                self._transition(
                    controller,
                    run,
                    "human_quality_review_required",
                    reason="Root Cause Analyzer could not support one repair cause.",
                    action=action,
                    triggering_module="root_cause_analyzer",
                    human_review_required=True,
                )
            else:
                self._transition(
                    controller,
                    run,
                    "repair_planning_required",
                    reason="Root Cause Analyzer generation completed.",
                    action=action,
                    triggering_module="root_cause_analyzer",
                )
        elif action.action_type == "generate_repair_planner":
            self._transition(
                controller,
                run,
                "awaiting_repair_decision",
                reason="Repair Planner generation completed.",
                action=action,
                triggering_module="repair_planner",
            )
        elif (
            action.target_module == "output_quality_reviewer"
            and action.target_operation == "artifact_review"
        ):
            decision = self._latest_quality_decision(run.project_id)
            if decision is None:
                self._transition(
                    controller,
                    run,
                    "human_quality_review_required",
                    reason="Output Quality Reviewer returned no decision.",
                    action=action,
                    human_review_required=True,
                )
            else:
                self._interpret_quality_decision(controller, run, decision)

    async def advance_safe_read_only(
        self,
        project_id: str,
        run_id: str,
        *,
        maximum_steps: int = 12,
    ) -> BobaAutopilotControllerSetV1:
        """Advance only registered automatic read-only actions."""

        steps = max(1, min(maximum_steps, 30))
        for _step in range(steps):
            controller = self._load_controller(project_id)
            run = self._find_run(controller, run_id)
            if run.current_state in _TERMINAL_STATES or run.run_status in {
                "paused",
                "awaiting_approval",
                "awaiting_human_review",
            }:
                return controller
            try:
                action = await self.plan_next_action(project_id, run_id)
            except ValidationError:
                return self._load_controller(project_id)
            if action.action_class != "automatic_read_only" or action.status != "planned":
                return self._load_controller(project_id)
            await self._execute_safe_read_only_action(
                project_id,
                run_id,
                action.action_id,
            )
        return self._load_controller(project_id)

    def _approval_failure(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        action: BobaAutopilotActionV1,
        binding: BobaAutopilotApprovalBindingV1,
        reasons: Sequence[str],
    ) -> None:
        reason = "; ".join(_unique(reasons, limit=16, maximum=700))
        action.status = "awaiting_approval"
        action.failure_summary = reason
        action.approval_binding_id = binding.approval_binding_id
        self._incident(
            controller,
            run,
            incident_type=(
                "approval_expired"
                if any("expired" in item.casefold() for item in reasons)
                else "approval_mismatch"
            ),
            title="Exact target-module approval was rejected",
            summary=reason,
            severity="high",
            action=action,
            fingerprint=_digest(
                [action.idempotency_key, binding.approval_record_id, reasons]
            ),
        )
        self._append_event(
            controller,
            run,
            event_type="approval_invalidated",
            technical_message=reason,
            easy_message=(
                "The supplied approval no longer matches the exact saved repair. "
                "Nothing was executed."
            ),
            severity="high",
            action=action,
            module_name=action.target_module,
            requires_attention=True,
            available_user_actions=["Review exact target approval", "Pause BOBA"],
        )
        if run.current_state != "awaiting_execution_approval":
            self._transition(
                controller,
                run,
                "awaiting_execution_approval",
                reason="The exact target-module approval is missing or invalid.",
                action=action,
                approval_required=True,
                human_review_required=True,
            )

    def _verify_target_module_approval(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        action: BobaAutopilotActionV1,
        approval_record: Mapping[str, Any] | BobaContract,
    ) -> tuple[
        BobaAutopilotApprovalBindingV1,
        BobaCodeApprovalRecordV1 | BobaToolRecoveryApprovalV1,
    ]:
        raw = (
            approval_record.model_dump(mode="json")
            if isinstance(approval_record, BobaContract)
            else dict(approval_record)
        )
        reasons: list[str] = []
        target_plan_id = ""
        target_strategy_id = ""
        target_artifact_digest = _text(
            action.parameters.get("target_artifact_digest"),
            maximum=128,
        )
        approved_scope: list[str] = []
        approved_parameters: dict[str, Any]
        explicit_confirmation = False
        validated_approval: (
            BobaCodeApprovalRecordV1 | BobaToolRecoveryApprovalV1
        )
        approval_id: str
        approval_type: str
        approved_at: str | None
        expires_at: str | None
        approved_by: str
        approved: bool

        if action.target_module == "code_surgeon":
            try:
                code_approval = BobaCodeApprovalRecordV1.model_validate(raw)
            except Exception as exc:
                raise ValidationError(
                    "Malformed Code Surgeon approval record.",
                    details={"reason": _text(exc)},
                ) from exc
            report = self.store.load_boba_code_surgeon(run.project_id)
            target_plan_id = _text(
                action.parameters.get("patch_proposal_id"),
                maximum=180,
            )
            proposal = next(
                (
                    item
                    for item in getattr(report, "patch_proposals", [])
                    if item.patch_proposal_id == target_plan_id
                ),
                None,
            )
            if proposal is None:
                reasons.append("The approved Code Surgeon proposal is unavailable.")
            else:
                required_type = (
                    "local_commit_creation"
                    if action.target_operation == "prepare_local_commit"
                    else "isolated_patch_execution"
                )
                if required_type == "local_commit_creation":
                    reasons.extend(
                        verify_code_approval(
                            proposal,
                            code_approval,
                            required_type="local_commit_creation",
                        )
                    )
                else:
                    reasons.extend(
                        verify_code_approval(
                            proposal,
                            code_approval,
                            required_type="isolated_patch_execution",
                        )
                    )
                if proposal.diff_sha256 != target_artifact_digest:
                    reasons.append("The current patch digest changed after planning.")
            approved_scope = code_approval.approved_scope
            explicit_confirmation = code_approval.explicit_confirmation
            approved_parameters = {
                "repair_case_id": code_approval.code_repair_case_id,
                "patch_proposal_id": code_approval.patch_proposal_id,
                "approval_type": code_approval.approval_type,
                "base_commit_sha": code_approval.approved_base_commit_sha,
                "diff_sha256": code_approval.approved_diff_sha256,
                "scope": code_approval.approved_scope,
                "validation_commands": code_approval.approved_validation_commands,
                "special_paths": code_approval.approved_special_paths,
            }
            approval_id = code_approval.approval_id
            approval_type = code_approval.approval_type
            approved_at = code_approval.approved_at
            expires_at = code_approval.approval_expires_at
            approved_by = code_approval.approved_by
            approved = code_approval.approved
            validated_approval = code_approval
        elif action.target_module == "tool_recovery_brain":
            try:
                tool_approval = BobaToolRecoveryApprovalV1.model_validate(raw)
            except Exception as exc:
                raise ValidationError(
                    "Malformed Tool Recovery approval record.",
                    details={"reason": _text(exc)},
                ) from exc
            tool_report = self.store.load_boba_tool_recovery(run.project_id)
            target_plan_id = _text(
                action.parameters.get("recovery_plan_id"),
                maximum=180,
            )
            target_strategy_id = _text(
                action.parameters.get("recovery_strategy_id"),
                maximum=180,
            )
            plan = next(
                (
                    item
                    for item in getattr(tool_report, "recovery_plans", [])
                    if item.recovery_plan_id == target_plan_id
                ),
                None,
            )
            strategy = next(
                (
                    item
                    for item in getattr(plan, "ordered_strategies", [])
                    if item.recovery_strategy_id == target_strategy_id
                ),
                None,
            )
            if plan is None or strategy is None:
                reasons.append("The approved Tool Recovery plan or strategy is unavailable.")
            else:
                reasons.extend(
                    verify_recovery_approval(plan, strategy, tool_approval)
                )
                current_digest = _digest(
                    {
                        "plan": plan.model_dump(mode="json"),
                        "strategy": strategy.model_dump(mode="json"),
                    }
                )
                if action.target_operation != "rollback" and (
                    current_digest != target_artifact_digest
                ):
                    reasons.append("The current recovery plan changed after planning.")
            approved_scope = [
                *tool_approval.approved_strategy_ids,
                *tool_approval.approved_tool_ids,
            ]
            explicit_confirmation = bool(tool_approval.explicit_confirmation)
            approved_parameters = {
                "recovery_case_id": tool_approval.recovery_case_id,
                "recovery_plan_id": tool_approval.recovery_plan_id,
                "strategy_ids": tool_approval.approved_strategy_ids,
                "tool_ids": tool_approval.approved_tool_ids,
                "configuration_overrides": (
                    tool_approval.approved_configuration_overrides
                ),
                "retry_budget": tool_approval.approved_retry_budget,
                "time_budget_seconds": tool_approval.approved_time_budget_seconds,
                "quality_requirements": tool_approval.approved_quality_requirements,
                "checkpoint_reference": (
                    tool_approval.approved_checkpoint_reference
                ),
            }
            approval_id = tool_approval.approval_id
            approval_type = "tool_recovery_exact_execution"
            approved_at = tool_approval.approved_at
            expires_at = tool_approval.approval_expires_at
            approved_by = tool_approval.approved_by
            approved = tool_approval.approved
            validated_approval = tool_approval
        else:
            raise ValidationError(
                "This action has no target-module approval contract.",
                details={"target_module": action.target_module},
            )

        approved_digest = _digest(approved_parameters)
        current_digest = approved_digest if not reasons else _digest(action.parameters)
        binding = BobaAutopilotApprovalBindingV1(
            approval_binding_id=_stable_id(
                "autopilot_approval_binding",
                run.run_id,
                action.action_id,
                approval_id,
                approved_digest,
            ),
            run_id=run.run_id,
            action_id=action.action_id,
            target_module=action.target_module,
            target_plan_id=target_plan_id,
            target_strategy_id=target_strategy_id,
            target_artifact_digest=target_artifact_digest,
            approval_record_id=approval_id,
            approval_type=approval_type,
            approved=approved and not reasons,
            approved_at=approved_at,
            approval_expires_at=expires_at,
            approved_by=_text(approved_by, maximum=160),
            approved_scope=_unique(approved_scope, limit=64, maximum=500),
            approved_parameters_digest=approved_digest,
            current_parameters_digest=current_digest,
            exact_match=not reasons,
            invalidation_reason="; ".join(reasons) if reasons else None,
            explicit_confirmation=explicit_confirmation,
            warnings=[
                "Autopilot referenced an approval created by the target module.",
                "The target module must independently revalidate it during execution.",
            ],
        )
        controller.approval_bindings.append(binding)
        controller.approval_bindings = controller.approval_bindings[-512:]
        action.approval_binding_id = binding.approval_binding_id
        controller.signal_usage.target_module_approval_used = not reasons
        if reasons:
            self._approval_failure(controller, run, action, binding, reasons)
            raise ValidationError(
                "Exact target-module approval validation failed.",
                details={"reasons": reasons},
            )
        return binding, validated_approval

    @staticmethod
    def _latest_result_item(
        result: Mapping[str, Any],
        key: str,
    ) -> Mapping[str, Any]:
        values = result.get(key)
        if not isinstance(values, list):
            return {}
        return next(
            (item for item in reversed(values) if isinstance(item, Mapping)),
            {},
        )

    def _pause_for_uncertain_result(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        action: BobaAutopilotActionV1,
        invocation: BobaAutopilotModuleInvocationV1,
        result: Mapping[str, Any],
    ) -> bool:
        signal = result.get("signal_usage")
        signal = signal if isinstance(signal, Mapping) else {}
        uncertain = bool(result.get("project_state_uncertain"))
        source_risk = (
            result.get("source_media_untouched") is False
            or signal.get("source_media_modified") is True
        )
        accepted_risk = (
            result.get("accepted_outputs_untouched") is False
            or signal.get("accepted_outputs_modified") is True
            or signal.get("completed_outputs_modified") is True
        )
        if not (uncertain or source_risk or accepted_risk):
            return False
        invocation.changed_project_state = True
        invocation.source_media_untouched = not source_risk
        invocation.accepted_outputs_untouched = not accepted_risk
        incident = self._incident(
            controller,
            run,
            incident_type="module_failure",
            title="Target module reported uncertain protected state",
            summary=(
                "The controller could not prove that project, source-media, and "
                "accepted-output state remained safe."
            ),
            severity="critical",
            action=action,
            invocation=invocation,
            fingerprint=_digest(
                [action.idempotency_key, uncertain, source_risk, accepted_risk]
            ),
            uncertain=True,
            source_media_risk=source_risk,
            accepted_output_risk=accepted_risk,
        )
        self._handoff(
            controller,
            run,
            target_module="safety_gate",
            reason=incident.summary,
            action=action,
            blocking_conditions=["Protected project state is uncertain."],
            priority="critical",
        )
        self._handoff(
            controller,
            run,
            target_module="human_operator",
            reason=incident.summary,
            action=action,
            blocking_conditions=["Protected project state is uncertain."],
            priority="critical",
        )
        self._transition(
            controller,
            run,
            "paused",
            reason="Execution stopped because protected project state is uncertain.",
            action=action,
            human_review_required=True,
        )
        return True

    def _route_approved_result(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        action: BobaAutopilotActionV1,
        invocation: BobaAutopilotModuleInvocationV1,
        result: Mapping[str, Any],
    ) -> None:
        if self._pause_for_uncertain_result(
            controller,
            run,
            action,
            invocation,
            result,
        ):
            return
        if action.target_module == "code_surgeon":
            isolated = self._latest_result_item(result, "isolated_runs")
            status = _text(isolated.get("run_status"), maximum=80)
            if status in {"validation_passed", "local_commit_prepared", "completed"}:
                self._transition(
                    controller,
                    run,
                    "technical_validation_required",
                    reason="Code Surgeon reported required validation passed.",
                    action=action,
                    evidence_ids=[isolated.get("isolated_run_id", "")],
                )
                self._transition(
                    controller,
                    run,
                    "output_quality_review_required",
                    reason=(
                        "Code validation passed; behavior and output quality still "
                        "require independent review."
                    ),
                    action=action,
                )
                return
            self._transition(
                controller,
                run,
                "execution_failed",
                reason=_text(isolated.get("stop_reason"), maximum=900)
                or f"Code Surgeon ended with status {status or 'unknown'}.",
                action=action,
            )
            self._transition(
                controller,
                run,
                "repair_replanning_required",
                reason="A failed or rolled-back patch cannot be repeated automatically.",
                action=action,
                human_review_required=True,
            )
            return

        if action.target_module == "tool_recovery_brain":
            if action.target_operation == "rollback":
                rollback = self._latest_result_item(result, "rollback_records")
                status = _text(rollback.get("status"), maximum=80)
                if status == "completed":
                    self._transition(
                        controller,
                        run,
                        "repair_replanning_required",
                        reason="Tool Recovery rollback completed and preserved protected state.",
                        action=action,
                        human_review_required=True,
                    )
                    return
                self._transition(
                    controller,
                    run,
                    "rollback_failed",
                    reason=f"Tool Recovery rollback status is {status or 'unknown'}.",
                    action=action,
                    human_review_required=True,
                )
                self._transition(
                    controller,
                    run,
                    "blocked",
                    reason="Rollback failure blocks further Autopilot execution.",
                    action=action,
                    human_review_required=True,
                )
                return
            if action.target_operation == "validate_output":
                validation = self._latest_result_item(result, "output_validations")
                if bool(validation.get("required_checks_passed")) and bool(
                    validation.get("accepted_for_quality_review")
                ):
                    self._transition(
                        controller,
                        run,
                        "output_quality_review_required",
                        reason="Recovered output passed registered technical validation.",
                        action=action,
                        evidence_ids=[validation.get("output_validation_id", "")],
                    )
                else:
                    self._transition(
                        controller,
                        run,
                        "repair_replanning_required",
                        reason=_text(validation.get("rejected_reason"), maximum=900)
                        or "Recovered output failed required technical validation.",
                        action=action,
                        human_review_required=True,
                    )
                return
            attempt = self._latest_result_item(result, "recovery_attempts")
            status = _text(attempt.get("status"), maximum=80)
            if status in {"succeeded_pending_validation", "completed"}:
                self._transition(
                    controller,
                    run,
                    "technical_validation_required",
                    reason="Tool Recovery produced an output that still requires validation.",
                    action=action,
                    evidence_ids=[attempt.get("recovery_attempt_id", "")],
                )
                return
            invocation.timeout_occurred = status == "timed_out" or bool(
                attempt.get("timeout_occurred")
            )
            self._transition(
                controller,
                run,
                "execution_failed",
                reason=_text(attempt.get("failure_summary"), maximum=900)
                or f"Tool Recovery ended with status {status or 'unknown'}.",
                action=action,
            )
            rollback = self._latest_result_item(result, "rollback_records")
            if _text(rollback.get("status"), maximum=80) == "completed":
                self._transition(
                    controller,
                    run,
                    "repair_replanning_required",
                    reason="The failed Tool Recovery attempt was rolled back safely.",
                    action=action,
                    human_review_required=True,
                )
            else:
                rollback_action = self._new_action(
                    controller,
                    run,
                    action_type="invoke_tool_recovery_rollback",
                    target_module="tool_recovery_brain",
                    target_operation="rollback",
                    description="Coordinate the target module's exact bounded rollback.",
                    rationale="The failed recovery attempt has no completed rollback record.",
                    parameters={
                        **action.parameters,
                        "recovery_attempt_id": attempt.get("recovery_attempt_id", ""),
                        "rollback_trigger": (
                            attempt.get("failure_summary")
                            or attempt.get("stop_reason")
                            or "Recovery execution failed."
                        ),
                    },
                    expected_output="boba_tool_recovery_brain_v1",
                    risk_level="high",
                    timeout_seconds=300,
                )
                self._transition(
                    controller,
                    run,
                    "rollback_required",
                    reason="Only Tool Recovery's own approved rollback may proceed.",
                    action=rollback_action,
                    approval_required=True,
                    human_review_required=True,
                )
            return

        if action.target_module == "output_quality_reviewer":
            decision = self._latest_quality_decision(run.project_id)
            if decision is None:
                self._transition(
                    controller,
                    run,
                    "human_quality_review_required",
                    reason="Output Quality Reviewer returned no acceptance decision.",
                    action=action,
                    human_review_required=True,
                )
            else:
                self._interpret_quality_decision(controller, run, decision)

    async def coordinate_approved_action(
        self,
        project_id: str,
        run_id: str,
        *,
        action_id: str,
        approval_record: Mapping[str, Any] | BobaContract,
        safety_decision_id: str,
    ) -> BobaAutopilotControllerSetV1:
        """Coordinate one exact target-approved typed operation."""

        controller = self._load_controller(project_id)
        run = self._find_run(controller, run_id)
        action = self._action(controller, action_id)
        if action.run_id != run.run_id:
            raise ValidationError("Autopilot action belongs to another run.")
        if action.status == "succeeded":
            return controller
        if action.action_class not in {
            "approval_required_read_only",
            "approval_required_execution",
        }:
            raise ValidationError("This action is not approval-coordinated.")
        if run.run_status in {"cancelled", "blocked", "failed", "completed_internal_cycle"}:
            raise ValidationError("This Autopilot run cannot coordinate another action.")
        if run.control_mode == "advisory_only":
            raise ValidationError("Advisory-only runs cannot invoke target modules.")
        budget = _budget_for_run(controller, run)
        if (
            action.action_class == "approval_required_execution"
            and (
                run.control_mode != "approved_execution_coordination"
                or not budget.execution_coordination_allowed
            )
        ):
            raise ValidationError(
                "Approved execution coordination is disabled for this run."
            )
        snapshot = await self._capture_snapshot(project_id)
        if snapshot.snapshot_sha256 != action.planned_snapshot_sha256:
            action.status = "blocked"
            action.failure_summary = "Project snapshot changed after action planning."
            self._incident(
                controller,
                run,
                incident_type="stale_artifact",
                title="Stale approved Autopilot action",
                summary=action.failure_summary,
                severity="high",
                action=action,
                fingerprint=action.idempotency_key,
            )
            self._persist(controller)
            raise ValidationError("Stale BOBA Autopilot action was blocked.")
        if snapshot.rights_status.casefold() not in _RIGHTS_CLEAR:
            raise ValidationError("Rights state does not permit this action.")
        if snapshot.safety_status.casefold() not in _SAFETY_CLEAR:
            raise ValidationError("Safety state does not permit this action.")
        checkpoint = self._checkpoint_for_action(controller, run, action)
        if checkpoint.blocks_execution or not checkpoint.rollback_ready:
            self._incident(
                controller,
                run,
                incident_type="checkpoint_invalid",
                title="Checkpoint or rollback evidence is not ready",
                summary="Execution stayed blocked because recovery safeguards are incomplete.",
                severity="high",
                action=action,
                fingerprint=_digest(
                    [checkpoint.checkpoint_requirement_id, checkpoint.checkpoint_status]
                ),
            )
            self._persist(controller)
            raise ValidationError("Checkpoint or rollback requirements are not ready.")
        try:
            binding, verified_approval = self._verify_target_module_approval(
                controller,
                run,
                action,
                approval_record,
            )
        except ValidationError:
            self._persist(controller)
            raise
        if not safety_decision_id:
            self._append_event(
                controller,
                run,
                event_type="safety_more_evidence_required",
                technical_message=(
                    "Approved action coordination requires an exact Safety Gate "
                    "decision ID."
                ),
                easy_message=(
                    "BOBA did not start the action because its exact Safety Gate "
                    "decision is missing."
                ),
                severity="warning",
                action=action,
                module_name="safety_gate",
                requires_attention=True,
                available_user_actions=["Evaluate this exact action in Safety Gate"],
            )
            self._persist(controller)
            raise ValidationError(
                "An exact BOBA Safety Gate decision ID is required."
            )
        self._append_event(
            controller,
            run,
            event_type="safety_review_started",
            technical_message=(
                f"Revalidating Safety Gate decision {safety_decision_id} for "
                f"action {action.action_id}."
            ),
            easy_message=(
                "BOBA is checking that the exact safety decision still matches "
                "this action and current project state."
            ),
            action=action,
            module_name="safety_gate",
            evidence_ids=[safety_decision_id],
        )
        try:
            if self.safety_decision_validator is None:
                raise ValidationError(
                    "BOBA Safety Gate validation is unavailable.",
                    details={"decision": "more_evidence_required"},
                )
            safety_decision = self.safety_decision_validator(
                project_id,
                run_id,
                action,
                safety_decision_id,
                verified_approval,
            )
            decision_payload = (
                safety_decision.model_dump(mode="json")
                if isinstance(safety_decision, BobaContract)
                else dict(safety_decision)
            )
            if (
                decision_payload.get("safety_decision_id") != safety_decision_id
                or decision_payload.get("decision")
                != "allowed_for_exact_internal_execution"
                or not decision_payload.get("decision_valid")
            ):
                raise ValidationError(
                    "Safety Gate did not allow exact internal execution.",
                    details={
                        "decision": str(
                            decision_payload.get("decision") or "unknown"
                        )
                    },
                )
        except ValidationError as exc:
            safety_value = str(exc.details.get("decision") or "")
            invalidated = bool(exc.details.get("invalidated"))
            event_type: BobaAutopilotEventTypeV1 = (
                "safety_decision_expired"
                if safety_value == "expired"
                else "safety_decision_invalidated"
                if invalidated or safety_value == "blocked_stale_state"
                else "safety_human_review_required"
                if safety_value == "human_review_required"
                else "safety_more_evidence_required"
                if safety_value in {"more_evidence_required", "unknown"}
                else "safety_denied"
            )
            action.status = "blocked"
            action.failure_summary = _text(exc, maximum=1_200)
            self._incident(
                controller,
                run,
                incident_type="safety_block",
                title="Safety Gate blocked target-module coordination",
                summary=action.failure_summary,
                severity="high",
                action=action,
                fingerprint=_digest(
                    [action.idempotency_key, safety_decision_id, safety_value]
                ),
            )
            self._append_event(
                controller,
                run,
                event_type=event_type,
                technical_message=action.failure_summary,
                easy_message=(
                    "BOBA did not start the target action because the exact "
                    "Safety Gate decision is not currently valid."
                ),
                severity="warning",
                action=action,
                module_name="safety_gate",
                confirmed_fact="The target module was not invoked.",
                assessment=safety_value or "Safety evidence is incomplete.",
                requires_attention=True,
                available_user_actions=[
                    "Inspect or re-evaluate this exact Safety Gate request"
                ],
                evidence_ids=[safety_decision_id],
            )
            self._persist(controller)
            raise
        controller.signal_usage.safety_gate_used = True
        action.safety_decision_id = safety_decision_id
        self._append_event(
            controller,
            run,
            event_type="safety_allowed",
            technical_message=(
                f"Safety Gate decision {safety_decision_id} allows this exact "
                "internal execution subject to target-module revalidation."
            ),
            easy_message=(
                "BOBA confirmed this one exact safety decision. The target module "
                "must still check the approval and safety again."
            ),
            action=action,
            module_name="safety_gate",
            confirmed_fact="Safety Gate revalidation passed for this exact action.",
            evidence_ids=[safety_decision_id],
        )
        action.approval_binding_id = binding.approval_binding_id
        action.status = "ready"
        action.failure_summary = None
        run.pending_approval_ids = [
            item for item in run.pending_approval_ids if item != action.action_id
        ]
        if action.target_operation == "rollback":
            if run.current_state != "rollback_required":
                raise ValidationError("Rollback action is stale for the current state.")
            self._transition(
                controller,
                run,
                "rollback_running",
                reason="The exact Tool Recovery rollback approval passed.",
                action=action,
                approval_required=True,
            )
        elif action.action_class == "approval_required_execution":
            ready_state: BobaAutopilotStateV1 = (
                "code_repair_ready"
                if action.target_module == "code_surgeon"
                else "tool_recovery_ready"
            )
            if run.current_state == "awaiting_execution_approval":
                self._transition(
                    controller,
                    run,
                    ready_state,
                    reason="The exact target-module approval passed controller checks.",
                    action=action,
                    approval_required=True,
                )
            if run.current_state == ready_state:
                self._transition(
                    controller,
                    run,
                    "approved_execution_pending",
                    reason="The target-approved action is ready for typed invocation.",
                    action=action,
                    approval_required=True,
                )
            self._transition(
                controller,
                run,
                "execution_running",
                reason="The typed target module is independently revalidating execution.",
                action=action,
                triggering_module=action.target_module,
                approval_required=True,
            )
        self._consume_action_budget(controller, run, action, invocation=True)
        action.status = "running"
        action.started_at = now_iso()
        run.active_action_id = action.action_id
        invocation_parameters: dict[str, Any] = {"approval": verified_approval}
        if isinstance(verified_approval, BobaCodeApprovalRecordV1):
            invocation_parameters["approved_validation_commands"] = (
                verified_approval.approved_validation_commands
            )
        try:
            invocation, result = await self._invoke_action(
                controller,
                run,
                action,
                approval_verified=True,
                invocation_parameters=invocation_parameters,
            )
            action.status = "succeeded"
            action.completed_at = now_iso()
            action.result_reference = _text(
                result.get("schema_version") or action.expected_output_artifact_type,
                maximum=500,
            )
            run.completed_action_ids = _unique(
                [*run.completed_action_ids, action.action_id],
                limit=256,
                maximum=180,
            )
            run.active_action_id = None
            usage = _usage_for_run(controller, run)
            usage.execution_duration_seconds += _elapsed_seconds(
                action.started_at or now_iso(),
                action.completed_at,
            )
            await self._refresh_snapshot(controller, run)
            self._route_approved_result(
                controller,
                run,
                action,
                invocation,
                result,
            )
            self._append_event(
                controller,
                run,
                event_type=(
                    "rollback_completed"
                    if action.target_operation == "rollback"
                    else "recovery_completed"
                ),
                technical_message=(
                    f"Typed approved action {action.action_id} completed and was routed "
                    "from persisted target-module evidence."
                ),
                easy_message=(
                    "The exact approved BOBA step finished. Autopilot is still "
                    "checking validation and quality before any future handoff."
                ),
                action=action,
                module_name=action.target_module,
                confirmed_fact="The target module returned a bounded persisted result.",
            )
        except Exception as exc:
            action.status = "timed_out" if "timeout" in str(exc).casefold() else "failed"
            action.completed_at = now_iso()
            action.failure_summary = _text(exc, maximum=1_200)
            run.failed_action_ids = _unique(
                [*run.failed_action_ids, action.action_id],
                limit=256,
                maximum=180,
            )
            run.active_action_id = None
            self._incident(
                controller,
                run,
                incident_type=(
                    "module_timeout"
                    if action.status == "timed_out"
                    else "rollback_failure"
                    if action.target_operation == "rollback"
                    else "module_failure"
                ),
                title="Approved target-module coordination failed",
                summary=action.failure_summary,
                severity="critical" if action.target_operation == "rollback" else "high",
                action=action,
                fingerprint=_digest(
                    [action.idempotency_key, exc.__class__.__name__, str(exc)]
                ),
            )
            if action.target_operation == "rollback":
                self._transition(
                    controller,
                    run,
                    "rollback_failed",
                    reason="The target module's rollback operation failed.",
                    action=action,
                    human_review_required=True,
                )
                self._transition(
                    controller,
                    run,
                    "blocked",
                    reason="Rollback failure blocks further execution.",
                    action=action,
                    human_review_required=True,
                )
            elif run.current_state == "execution_running":
                self._transition(
                    controller,
                    run,
                    "execution_failed",
                    reason=action.failure_summary,
                    action=action,
                )
                self._transition(
                    controller,
                    run,
                    "repair_replanning_required",
                    reason="The failed exact action requires fresh evidence or replanning.",
                    action=action,
                    human_review_required=True,
                )
            else:
                self._transition(
                    controller,
                    run,
                    "paused",
                    reason="Approved read-only coordination failed.",
                    action=action,
                    human_review_required=True,
                )
            self._append_event(
                controller,
                run,
                event_type=(
                    "recovery_failed"
                ),
                technical_message=action.failure_summary,
                easy_message=(
                    "The approved BOBA step failed. Autopilot stopped and preserved "
                    "the bounded failure history."
                ),
                severity="high",
                action=action,
                module_name=action.target_module,
                requires_attention=True,
            )
            self._persist(controller)
            raise
        return self._persist(controller)

    def pause_run(
        self,
        project_id: str,
        run_id: str,
        *,
        reason: str = "Human requested a controller pause.",
    ) -> BobaAutopilotControllerSetV1:
        controller = self._load_controller(project_id)
        run = self._find_run(controller, run_id)
        if run.current_state in _TERMINAL_STATES:
            raise ValidationError("A terminal Autopilot run cannot be paused.")
        if run.active_module_invocation_id:
            raise ValidationError(
                "Pause cannot interrupt an active target-module operation unsafely."
            )
        if run.current_state != "paused":
            self._transition(
                controller,
                run,
                "paused",
                reason=reason,
                human_review_required=True,
            )
            run.stop_reason = _text(reason, maximum=900)
            self._append_event(
                controller,
                run,
                event_type="controller_paused",
                technical_message=reason,
                easy_message="BOBA paused controller coordination. Olympus was not resumed.",
                severity="warning",
                requires_attention=True,
                available_user_actions=["Continue BOBA controller", "Cancel BOBA run"],
            )
        return self._persist(controller)

    def continue_run(
        self,
        project_id: str,
        run_id: str,
    ) -> BobaAutopilotControllerSetV1:
        controller = self._load_controller(project_id)
        run = self._find_run(controller, run_id)
        if run.current_state != "paused":
            raise ValidationError("Only a paused Autopilot run can continue.")
        resume_state = run.previous_state
        if resume_state in _TERMINAL_STATES or resume_state in {
            "paused",
            "execution_running",
            "rollback_running",
            "unknown",
        }:
            resume_state = "inspecting_project"
        if run.control_mode != "advisory_only":
            lock = self.store.refresh_boba_autopilot_lock(
                project_id,
                run_id=run.run_id,
                owner_identifier=self.lock_owner,
                lease_seconds=self.lock_lease_seconds,
            )
            controller.lock_metadata = lock
        run.stop_reason = None
        self._transition(
            controller,
            run,
            resume_state,
            reason=(
                "Controller coordination continued from persisted state. "
                "Olympus workflow resume was not invoked."
            ),
        )
        return self._persist(controller)

    def cancel_run(
        self,
        project_id: str,
        run_id: str,
        *,
        reason: str = "Human cancelled future Autopilot actions.",
    ) -> BobaAutopilotControllerSetV1:
        controller = self._load_controller(project_id)
        run = self._find_run(controller, run_id)
        if run.current_state in _TERMINAL_STATES:
            return controller
        if run.active_module_invocation_id:
            raise ValidationError(
                "Cancellation cannot interrupt an active target-module operation unsafely."
            )
        for action in self._run_actions(controller, run.run_id):
            if action.status in {"planned", "ready", "awaiting_approval"}:
                action.status = "cancelled"
                action.completed_at = now_iso()
        self._transition(
            controller,
            run,
            "cancelled",
            reason=reason,
        )
        run.stop_reason = _text(reason, maximum=900)
        self._append_event(
            controller,
            run,
            event_type="controller_cancelled",
            technical_message=reason,
            easy_message="BOBA cancelled future controller actions without deleting evidence.",
            severity="warning",
            confirmed_fact="No active target operation was interrupted.",
        )
        if run.control_mode != "advisory_only":
            self.store.release_boba_autopilot_lock(
                project_id,
                run_id=run.run_id,
                owner_identifier=self.lock_owner,
            )
            controller.lock_metadata = None
        return self._persist(controller)

    def request_budget_reset(
        self,
        project_id: str,
        run_id: str,
        *,
        reason: str,
    ) -> BobaAutopilotControllerSetV1:
        controller = self._load_controller(project_id)
        run = self._find_run(controller, run_id)
        request_reference = (
            f"{run.budget_id}:{_digest(_text(reason, maximum=900))[:24]}"
        )
        action = self._new_action(
            controller,
            run,
            action_type="human_review",
            target_module="human_operator",
            target_operation="approve_budget_reset",
            description="Review a bounded Autopilot recovery-budget reset request.",
            rationale=reason,
            parameters={
                "target_plan_id": request_reference,
                "budget_id": run.budget_id,
            },
            expected_output="human_budget_reset_decision",
            risk_level="high",
        )
        if action.status == "awaiting_approval":
            return self._persist(controller)
        if action.status == "blocked":
            raise ValidationError(
                "A rejected budget-reset request requires a materially new reason."
            )
        action.status = "awaiting_approval"
        action.human_approval_required = True
        run.pending_approval_ids = _unique(
            [*run.pending_approval_ids, action.action_id],
            limit=64,
            maximum=180,
        )
        self._append_event(
            controller,
            run,
            event_type="approval_required",
            technical_message="A new recovery budget requires explicit human approval.",
            easy_message=(
                "BOBA reached or is approaching a recovery limit. More attempts "
                "require a separate human decision."
            ),
            severity="high",
            action=action,
            requires_attention=True,
        )
        return self._persist(controller)

    def _reset_budget_after_human_approval(
        self,
        controller: BobaAutopilotControllerSetV1,
        run: BobaAutopilotRunV1,
        *,
        reason: str,
    ) -> None:
        previous = _budget_for_run(controller, run)
        values = {
            key: getattr(previous, key)
            for key in DEFAULT_AUTOPILOT_BUDGET_LIMITS
        }
        budget_id = _stable_id(
            "autopilot_budget",
            run.project_id,
            run.run_id,
            len(controller.recovery_budgets) + 1,
            reason,
        )
        budget = BobaAutopilotRecoveryBudgetV1(
            budget_id=budget_id,
            run_id=run.run_id,
            **values,
            warnings=[
                "This budget was created by an explicit human reset decision.",
                f"Prior budget {previous.budget_id} remains in history.",
            ],
        )
        usage = BobaAutopilotBudgetUsageV1(
            budget_usage_id=_stable_id("autopilot_usage", budget_id),
            budget_id=budget_id,
        )
        controller.recovery_budgets.append(budget)
        controller.budget_usages.append(usage)
        run.budget_id = budget_id

    def record_human_decision(
        self,
        project_id: str,
        run_id: str,
        *,
        decision: str,
        reason: str,
        reviewer_identity: str,
        action_id: str | None = None,
        selected_alternative_id: str | None = None,
    ) -> BobaAutopilotControllerSetV1:
        controller = self._load_controller(project_id)
        run = self._find_run(controller, run_id)
        allowed = {
            "reject_proposed_action",
            "select_repair_alternative",
            "request_more_evidence",
            "pause_autopilot",
            "cancel_autopilot",
            "approve_disclosed_quality_limitation",
            "reject_output",
            "approve_budget_reset",
            "acknowledge_uncertain_project_state",
        }
        if decision not in allowed:
            raise ValidationError("Unknown bounded Autopilot human decision.")
        action = self._action(controller, action_id) if action_id else None
        reviewer_hash = _digest(
            [run.project_id, _text(reviewer_identity, maximum=160)]
        )
        record = BobaAutopilotDecisionV1(
            decision_id=_stable_id(
                "autopilot_human_decision",
                run.run_id,
                decision,
                action_id or "",
                len(controller.decisions) + 1,
            ),
            run_id=run.run_id,
            decision_type=(
                "pause"
                if decision == "pause_autopilot"
                else "stop"
                if decision in {"cancel_autopilot", "reject_proposed_action", "reject_output"}
                else "replan"
                if decision == "select_repair_alternative"
                else "reanalyze"
                if decision == "request_more_evidence"
                else "quality_routing"
                if decision == "approve_disclosed_quality_limitation"
                else "retry"
                if decision == "approve_budget_reset"
                else "unknown"
            ),
            decision=decision,
            reason=_text(reason, maximum=900),
            evidence_ids=_unique(
                [action_id or "", selected_alternative_id or ""],
                limit=64,
                maximum=180,
            ),
            alternatives_considered=_unique(
                [selected_alternative_id or ""],
                limit=32,
                maximum=180,
            ),
            confidence=1.0,
            risk_level="human_reviewed",
            rights_clear=run.rights_status.casefold() in _RIGHTS_CLEAR,
            safety_clear=run.safety_status.casefold() in _SAFETY_CLEAR,
            approval_clear=False,
            budget_clear=not calculate_autopilot_budget_usage(
                controller,
                run,
            ).budget_exhausted,
            checkpoint_clear=True,
            quality_clear=decision == "approve_disclosed_quality_limitation",
            human_review_required=False,
            next_state=run.current_state,
            next_action_id=action_id,
            reviewer_identity_hash=reviewer_hash,
            source="human_operator",
            limitations=[
                "This decision cannot authorize publication or bypass rights or safety."
            ],
        )
        controller.decisions.append(record)
        controller.decisions = controller.decisions[-2_000:]
        run.decision_ids = _unique(
            [*run.decision_ids, record.decision_id],
            limit=256,
            maximum=180,
        )
        if decision in {"reject_proposed_action", "reject_output"}:
            if action is not None and action.status in {
                "planned",
                "ready",
                "awaiting_approval",
            }:
                action.status = "blocked"
                action.failure_summary = reason
            if run.current_state != "paused":
                self._transition(
                    controller,
                    run,
                    "paused",
                    reason=reason,
                    action=action,
                    human_review_required=True,
                )
        elif decision == "select_repair_alternative":
            if not selected_alternative_id:
                raise ValidationError("A selected repair alternative ID is required.")
            if run.current_state != "repair_replanning_required":
                self._transition(
                    controller,
                    run,
                    "repair_replanning_required",
                    reason=reason,
                    action=action,
                )
        elif decision == "request_more_evidence":
            if run.current_state != "root_cause_reanalysis_required":
                self._transition(
                    controller,
                    run,
                    "root_cause_reanalysis_required",
                    reason=reason,
                    action=action,
                )
        elif decision == "pause_autopilot":
            self._persist(controller)
            return self.pause_run(project_id, run_id, reason=reason)
        elif decision == "cancel_autopilot":
            self._persist(controller)
            return self.cancel_run(project_id, run_id, reason=reason)
        elif decision == "approve_disclosed_quality_limitation":
            quality = self._latest_quality_decision(project_id)
            if (
                quality is None
                or getattr(quality, "decision", "")
                != "accepted_with_disclosed_limitations"
                or run.current_state != "human_quality_review_required"
            ):
                raise ValidationError(
                    "No disclosed-limitation quality decision is awaiting approval."
                )
            self._transition(
                controller,
                run,
                "awaiting_safety_gate",
                reason=reason,
                action=action,
                safety_gate_required=True,
            )
            self._prepare_safety_handoff(controller, run)
        elif decision == "approve_budget_reset":
            request = action
            if (
                request is None
                or request.target_operation != "approve_budget_reset"
                or request.status != "awaiting_approval"
            ):
                raise ValidationError("No exact budget-reset request is awaiting approval.")
            request.status = "succeeded"
            request.completed_at = now_iso()
            self._reset_budget_after_human_approval(
                controller,
                run,
                reason=reason,
            )
            run.pending_approval_ids = [
                item for item in run.pending_approval_ids if item != request.action_id
            ]
        elif decision == "acknowledge_uncertain_project_state":
            if run.current_state != "paused":
                raise ValidationError("Uncertain state acknowledgement requires a paused run.")
            run.human_review_required = True
            run.warnings = _unique(
                [
                    *run.warnings,
                    "Human acknowledged uncertain state; execution remains blocked.",
                ],
                limit=64,
            )
        return self._persist(controller)

    def export_run(
        self,
        project_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        controller = self.inspect_run(project_id, run_id)
        run = self._find_run(controller, run_id)
        payload = {
            "schema_version": "boba_autopilot_run_export_v1",
            "project_id": project_id,
            "exported_at": now_iso(),
            "run": run.model_dump(mode="json"),
            "project_snapshots": [
                item.model_dump(mode="json")
                for item in controller.project_snapshots
                if item.project_snapshot_id == run.project_snapshot_id
            ],
            "state_transitions": [
                item.model_dump(mode="json")
                for item in controller.state_transitions
                if item.run_id == run_id
            ],
            "planned_actions": [
                item.model_dump(mode="json")
                for item in controller.planned_actions
                if item.run_id == run_id
            ],
            "module_invocations": [
                item.model_dump(mode="json")
                for item in controller.module_invocations
                if item.run_id == run_id
            ],
            "approval_bindings": [
                item.model_dump(mode="json")
                for item in controller.approval_bindings
                if item.run_id == run_id
            ],
            "recovery_budgets": [
                item.model_dump(mode="json")
                for item in controller.recovery_budgets
                if item.run_id == run_id
            ],
            "budget_usages": [
                item.model_dump(mode="json")
                for item in controller.budget_usages
                if item.budget_id
                in {
                    budget.budget_id
                    for budget in controller.recovery_budgets
                    if budget.run_id == run_id
                }
            ],
            "checkpoint_requirements": [
                item.model_dump(mode="json")
                for item in controller.checkpoint_requirements
                if item.run_id == run_id
            ],
            "incidents": [
                item.model_dump(mode="json")
                for item in controller.incidents
                if item.run_id == run_id
            ],
            "decisions": [
                item.model_dump(mode="json")
                for item in controller.decisions
                if item.run_id == run_id
            ],
            "event_stream": [
                item.model_dump(mode="json")
                for item in controller.event_stream
                if item.run_id == run_id
            ],
            "handoffs": [
                item.model_dump(mode="json")
                for item in controller.handoffs
                if item.run_id == run_id
            ],
            "signal_usage": controller.signal_usage.model_dump(mode="json"),
            "privacy": {
                "private_paths_excluded": True,
                "secrets_excluded": True,
                "raw_media_excluded": True,
                "direct_command_execution_used": False,
                "workflow_resume_used": False,
                "publication_used": False,
            },
        }
        safe = sanitize_autopilot_export(payload)
        if not isinstance(safe, dict):
            raise ValidationError("Autopilot export is invalid.")
        return safe

    def reset_run_metadata(self, project_id: str) -> bool:
        """Remove Autopilot metadata only; upstream BOBA artifacts remain untouched."""

        return self.store.reset_boba_autopilot_controller(project_id)

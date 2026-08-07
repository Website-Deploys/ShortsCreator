"""Read-only BOBA repair-plan review projections and constrained action routing.

The Repair Plan Panel is a specialized mode of the BOBA Review UI and the BOBA
Error Doctor Panel. It is a trusted repair-plan projection, an evidence
workspace, a plan-comparison surface, an approval-requirement viewer, a
recovery-history viewer and a safe canonical action router.

It never generates a repair plan, revises one, approves or rejects one locally,
executes a plan or a step, runs a command, shell, PowerShell, Git or FFmpeg,
installs or downloads a tool, restarts a process, restores a checkpoint,
transitions a workflow, modifies code, artifacts or media, uploads or publishes.

Ownership chain preserved exactly as this repository defines it:

    Error Doctor case        -> ``diagnostic_case_id``
    Root Cause Analyzer case -> ``analysis_case_id``     (source_diagnostic_case_id)
    Repair Planner case      -> ``repair_case_id``       (source_analysis_case_id)
    Repair Planner strategy  -> ``repair_strategy_id``   (the reviewed repair plan)
    Repair Planner step      -> ``repair_step_id`` with ``order``
    Tool Recovery case       -> ``recovery_case_id``     (source_repair_case_id)
    Code Surgeon case        -> ``code_repair_case_id``  (source_repair_case_id)

``BobaRepairStepV1.target`` and ``BobaRepairRollbackPlanV1.rollback_steps`` may
contain command text, so neither is ever projected into a browser payload. The
panel reports only that a command is present in the source record.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from olympus.boba.contracts import BobaContract, now_iso

# Shared Error Doctor Panel primitives. Reusing them keeps bounded-excerpt,
# secret-redaction and private-path semantics identical across both reliability
# review panels.
from olympus.boba.error_doctor_review import (
    _FULL_PRIVATE_PATH,
    _SECRET_VALUE_PATTERNS,
    bounded_easy_explanation,
    bounded_excerpt,
)

# Shared Review UI primitives, so digests and sanitisation stay byte-identical
# with Review UI V1, Candidate Review V1, Clip Brief Review V1 and Error Doctor
# Review V1, which the confirmation tokens depend on.
from olympus.boba.review_ui import (
    _PRIVATE_PATH,
    _SENSITIVE_KEY,
    _active_workflow_run,
    _as_mapping,
    _digest,
    _parse_time,
    _safe_id,
    _safe_payload,
    _safe_text,
    _stable_id,
)
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from olympus.boba.integration import BobaIntegration


# Repair-plan identifiers are opaque, source-owned tokens.
_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,180}$")

# The one repair-plan schema this panel understands, taken verbatim from
# ``BobaRepairPlannerSetV1.schema_version``.
SUPPORTED_REPAIR_PLAN_SCHEMA_ID = "boba_repair_planner_v1"

# Shell metacharacters, transcribed from ``tool_recovery._SHELL_TOKEN``, plus the
# executable names the reliability modules already treat as tool invocations.
# These are used only to detect that a source field holds command text so the
# panel can withhold it. The matched text is never projected.
_SHELL_TOKEN = re.compile(r"(?:\|\||&&|[|><;`]|\$\(|\r|\n)")
_COMMAND_EXECUTABLE = re.compile(
    r"(?i)(?:^|[\s\"'])(?:ffmpeg|ffprobe|git|python|python3|pip|pip3|npm|npx|yarn|"
    r"pnpm|node|bash|sh|zsh|powershell|pwsh|cmd|docker|apt|apt-get|brew|curl|wget|"
    r"make|systemctl|kill|pkill|rm|mv|cp|chmod|chown|sudo|ssh|scp|rsync)\b"
)
_COMMAND_FLAG = re.compile(r"(?:^|\s)-{1,2}[A-Za-z][\w-]*(?:\s|=|$)")

MAX_COMPARISON_PLANS = 4
MAX_LOADED_PLANS = 500
MAX_QUEUE_PAGE_SIZE = 50
MAX_TIMELINE_ENTRIES = 100
MAX_ANNOTATIONS = 32
MAX_ANNOTATION_LENGTH = 4_000
MAX_STEP_DESCRIPTION_CHARS = 8_192
MAX_EVIDENCE_EXCERPT_CHARS = 16_384
MAX_EVIDENCE_CARDS = 100
MAX_EXPANDED_SOURCE_CARDS = 20
MAX_STEP_PROJECTIONS = 64

_MAX_EVENTS = 100
_MAX_SOURCE_CARDS = 24
_MAX_RISK_PROJECTIONS = 32
_MAX_APPROVAL_REQUIREMENTS = 32
_MAX_VERIFICATION_REQUIREMENTS = 48
_MAX_RECOVERY_LINKS = 64
_MAX_CONFLICTS = 32
_MAX_REASON_LENGTH = 500

# Exact label strings the panel must always use when it withholds source detail.
COMMAND_WITHHELD_NOTICE = "Command details withheld from the review panel."
PRIVATE_PATH_NOTICE = "Private path details redacted."
NOT_EXECUTABLE_NOTICE = "This step cannot be executed from this panel."
SOURCE_RETAINED_NOTICE = "Full source record retained by Repair Planner."

RepairPlanReviewFilter = Literal[
    "all_current",
    "human_review_required",
    "destructive",
    "reversible",
    "code_change",
    "artifact_change",
    "workflow_change",
    "tool_execution",
    "process_restart",
    "checkpoint_restore",
    "missing_approval",
    "missing_verification",
    "failed_recovery",
    "conflicts",
    "stale",
    "completed",
    "historical",
    "superseded",
]
RepairPlanReviewSort = Literal[
    "review_priority",
    "source_severity",
    "creation_order",
    "affected_module",
    "step_count",
    "repair_plan_id",
]
RepairApprovalRequirementType = Literal[
    "human_review",
    "safety_gate",
    "final_decision_bus",
    "workflow",
    "code_change",
    "artifact_change",
    "destructive_action",
    "tool_execution",
    "process_restart",
    "checkpoint_restore",
    "rights_gate",
    "rollback_plan",
    "validation_plan",
    "output_quality_review",
    "unknown",
]
RepairVerificationType = Literal[
    "pre_repair_check",
    "post_repair_check",
    "validator_run",
    "artifact_inspection",
    "output_quality_review",
    "rollback_validation",
    "checkpoint_validation",
    "unknown",
]
RepairPlanConflictType = Literal[
    "plan_identity_conflict",
    "analysis_identity_conflict",
    "incident_identity_conflict",
    "workflow_identity_conflict",
    "approval_status_conflict",
    "destructive_flag_conflict",
    "rollback_conflict",
    "verification_conflict",
    "recovery_status_conflict",
    "strategy_conflict",
    "source_digest_conflict",
    "lifecycle_conflict",
    "unknown",
]
RepairPlanComparisonType = Literal[
    "side_by_side",
    "alternative_strategies",
    "current_vs_historical",
    "same_incident",
    "same_analysis_case",
    "steps",
    "approvals",
    "risk",
    "verification",
    "recovery",
    "unknown",
]


# ----------------------------------------------------------------------
# Command and path detection: report presence, never the content
# ----------------------------------------------------------------------
def source_holds_command(value: object) -> bool:
    """Return True when a source field looks like executable command text.

    The matched text is never returned or projected. This exists only so the
    panel can say that Repair Planner recorded a command without showing it.
    """
    text = str(value or "")
    if not text.strip():
        return False
    if _SHELL_TOKEN.search(text):
        return True
    if _COMMAND_EXECUTABLE.search(text):
        return True
    return bool(_COMMAND_FLAG.search(text)) and " " in text.strip()


def source_holds_private_path(value: object) -> bool:
    text = str(value or "")
    return bool(_FULL_PRIVATE_PATH.search(text) or _PRIVATE_PATH.search(text))


def bounded_step_description(value: object) -> dict[str, Any]:
    """Bound a step description, withholding command text entirely.

    When the owner's text is command-like the panel emits the fixed withheld
    notice instead of the text, so no executable fragment reaches the browser.
    """
    if source_holds_command(value):
        return {
            "text": COMMAND_WITHHELD_NOTICE,
            "command_withheld": True,
            "private_paths_redacted": source_holds_private_path(value),
            "truncated": False,
        }
    projected = bounded_excerpt(value, maximum=MAX_STEP_DESCRIPTION_CHARS)
    return {
        "text": projected["text"],
        "command_withheld": False,
        "private_paths_redacted": projected["private_paths_redacted"],
        "truncated": projected["truncated"],
    }


def joined_owner_text(value: object, maximum: int = 900) -> str:
    """Flatten an owner field that may be a string or a list of strings.

    Several Repair Planner plan documents record prose as ``list[str]``
    (``rollback_validation``, ``comparison_baseline``). Reading those with
    ``_safe_text`` alone would emit a Python list repr into a browser payload,
    so they are joined into real sentences first.
    """
    if isinstance(value, list | tuple):
        parts = [_safe_text(item, maximum) for item in list(value)[:32]]
        return _safe_text(" ".join(part for part in parts if part), maximum)
    return _safe_text(value, maximum)


def _contains_secret(text: str) -> bool:
    if _SENSITIVE_KEY.search(text):
        return True
    return any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS)


# ----------------------------------------------------------------------
# Contracts
# ----------------------------------------------------------------------
class BobaRepairPlanRegistrySnapshotV1(BobaContract):
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = "1"
    created_at: str = Field(default_factory=now_iso)
    plan_source_ids: list[str] = Field(default_factory=list, max_length=24)
    evidence_source_ids: list[str] = Field(default_factory=list, max_length=24)
    approval_source_ids: list[str] = Field(default_factory=list, max_length=24)
    verification_source_ids: list[str] = Field(default_factory=list, max_length=24)
    available_source_ids: list[str] = Field(default_factory=list, max_length=24)
    unavailable_source_ids: list[str] = Field(default_factory=list, max_length=24)
    action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    unavailable_action_descriptor_ids: list[str] = Field(
        default_factory=list, max_length=32
    )
    registry_digest: str = Field(min_length=64, max_length=64)
    immutable: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairPlanReferenceV1(BobaContract):
    repair_plan_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    repair_plan_id: str = Field(min_length=1, max_length=180)
    # Repair Planner defines no strategy revision identity, so this stays None.
    repair_plan_revision_id: str | None = None
    repair_case_id: str = Field(min_length=1, max_length=180)
    source_analysis_case_id: str = Field(default="", max_length=180)
    source_diagnostic_case_id: str = Field(default="", max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    source_schema_id: str = Field(default="unknown", max_length=180)
    source_schema_version: str = Field(default="unknown", max_length=80)
    schema_supported: bool = False
    owner_module_id: str = Field(default="repair_planner", max_length=180)
    original_status: str = Field(default="unknown", max_length=120)
    original_strategy_type: str = Field(default="unknown", max_length=120)
    original_risk_level: str = Field(default="unknown", max_length=120)
    affected_stage_id: str = Field(default="", max_length=180)
    affected_module_id: str = Field(default="", max_length=180)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str | None = None
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    superseding_repair_plan_id: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairPlanReviewSessionV1(BobaContract):
    repair_plan_review_session_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    reviewer_context_id: str = Field(min_length=1, max_length=160)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    expires_at: str
    selected_repair_plan_id: str | None = None
    comparison_repair_plan_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_PLANS
    )
    active_filter: RepairPlanReviewFilter = "all_current"
    active_sort: RepairPlanReviewSort = "review_priority"
    active_section_id: str = "overview"
    show_historical: bool = False
    show_superseded: bool = False
    show_completed: bool = False
    show_technical_details: bool = False
    show_recovery_history: bool = True
    evidence_drawer_open: bool = False
    timeline_drawer_open: bool = False
    local_annotations: list[dict[str, str]] = Field(
        default_factory=list, max_length=MAX_ANNOTATIONS
    )
    read_repair_plan_ids: list[str] = Field(default_factory=list, max_length=256)
    session_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairPlanQueueItemV1(BobaContract):
    repair_plan_queue_item_id: str = Field(min_length=1, max_length=180)
    repair_plan_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    repair_plan_id: str = Field(min_length=1, max_length=180)
    repair_case_id: str = Field(min_length=1, max_length=180)
    source_analysis_case_id: str = Field(default="", max_length=180)
    source_diagnostic_case_id: str = Field(default="", max_length=180)
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(default="", max_length=900)
    owner_module_id: str = Field(default="repair_planner", max_length=180)
    original_status: str = Field(default="unknown", max_length=120)
    original_strategy_type: str = Field(default="unknown", max_length=120)
    original_risk_level: str = Field(default="unknown", max_length=120)
    original_reversibility: str = Field(default="unknown", max_length=120)
    original_destructiveness: str = Field(default="unknown", max_length=120)
    approval_status: str = Field(default="unavailable", max_length=120)
    verification_status: str = Field(default="unavailable", max_length=120)
    recovery_status: str = Field(default="unavailable", max_length=120)
    validation_status: str = Field(default="unavailable", max_length=120)
    artifact_status: str = Field(default="unavailable", max_length=120)
    workflow_status: str = Field(default="unavailable", max_length=120)
    affected_module_id: str = Field(default="", max_length=180)
    affected_stage_id: str = Field(default="", max_length=180)
    step_count: int = Field(default=0, ge=0)
    destructive: bool = False
    reversible: bool = False
    rollback_available: bool = False
    requires_code_change: bool = False
    requires_artifact_change: bool = False
    requires_workflow_transition: bool = False
    requires_tool_execution: bool = False
    requires_process_restart: bool = False
    requires_checkpoint_restore: bool = False
    requires_human_approval: bool = True
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    completed: bool = False
    source_marked_recommended: bool = False
    human_action_required: bool = False
    blocker_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    missing_approval_count: int = Field(default=0, ge=0)
    missing_verification_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    failed_recovery_attempt_count: int = Field(default=0, ge=0)
    command_bearing_step_count: int = Field(default=0, ge=0)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    source_module_ids: list[str] = Field(default_factory=list, max_length=24)
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=24)
    priority_tier: int = Field(default=0, ge=0, le=999)
    priority_reason: str = Field(default="", max_length=200)
    deterministic_sort_key: str = Field(min_length=1, max_length=240)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairPlanSnapshotV1(BobaContract):
    repair_plan_snapshot_id: str = Field(min_length=1, max_length=180)
    repair_plan_review_session_id: str = Field(min_length=1, max_length=180)
    repair_plan_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    repair_plan_id: str = Field(min_length=1, max_length=180)
    repair_case_id: str = Field(min_length=1, max_length=180)
    source_analysis_case_id: str = Field(default="", max_length=180)
    source_diagnostic_case_id: str = Field(default="", max_length=180)
    created_at: str = Field(default_factory=now_iso)
    refreshed_at: str = Field(default_factory=now_iso)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    repair_plan_digest: str = Field(min_length=64, max_length=64)
    source_record_references: list[dict[str, str]] = Field(
        default_factory=list, max_length=24
    )
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=24)
    step_projection_ids: list[str] = Field(
        default_factory=list, max_length=MAX_STEP_PROJECTIONS
    )
    risk_projection_ids: list[str] = Field(default_factory=list, max_length=32)
    approval_requirement_ids: list[str] = Field(default_factory=list, max_length=32)
    verification_requirement_ids: list[str] = Field(default_factory=list, max_length=48)
    evidence_card_ids: list[str] = Field(
        default_factory=list, max_length=MAX_EVIDENCE_CARDS
    )
    recovery_link_ids: list[str] = Field(default_factory=list, max_length=64)
    conflict_record_ids: list[str] = Field(default_factory=list, max_length=32)
    comparison_ids: list[str] = Field(default_factory=list, max_length=8)
    plan_status: str = Field(default="unknown", max_length=120)
    approval_status: str = Field(default="unavailable", max_length=120)
    verification_status: str = Field(default="unavailable", max_length=120)
    recovery_status: str = Field(default="unavailable", max_length=120)
    validation_status: str = Field(default="unavailable", max_length=120)
    artifact_status: str = Field(default="unavailable", max_length=120)
    workflow_status: str = Field(default="unavailable", max_length=120)
    rights_status: str = Field(default="unavailable", max_length=120)
    safety_status: str = Field(default="unavailable", max_length=120)
    final_decision_status: str = Field(default="unavailable", max_length=120)
    incident_status: str = Field(default="unavailable", max_length=120)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    completed: bool = False
    destructive: bool = False
    reversible: bool = False
    rollback_available: bool = False
    missing_approval_count: int = Field(default=0, ge=0)
    missing_verification_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    limitation_count: int = Field(default=0, ge=0)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    confirmation_context_digest: str = Field(min_length=64, max_length=64)
    snapshot_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairStepProjectionV1(BobaContract):
    repair_step_projection_id: str = Field(min_length=1, max_length=180)
    repair_plan_snapshot_id: str | None = None
    repair_plan_id: str = Field(min_length=1, max_length=180)
    source_module_id: str = Field(default="repair_planner", max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    source_step_id: str = Field(min_length=1, max_length=180)
    original_order: int = Field(ge=1, le=64)
    original_status: str = Field(default="proposed", max_length=120)
    original_step_type: str = Field(default="unknown", max_length=120)
    bounded_description: str = Field(default="", max_length=MAX_STEP_DESCRIPTION_CHARS)
    bounded_reason: str = Field(default="", max_length=MAX_STEP_DESCRIPTION_CHARS)
    affected_module_ids: list[str] = Field(default_factory=list, max_length=16)
    affected_operation_ids: list[str] = Field(default_factory=list, max_length=16)
    requires_code_change: bool = False
    requires_artifact_change: bool = False
    requires_tool_execution: bool = False
    requires_process_restart: bool = False
    requires_checkpoint_restore: bool = False
    requires_workflow_transition: bool = False
    requires_human_approval: bool = True
    destructive: bool = False
    reversible: bool = False
    rollback_available: bool = False
    verification_required: bool = True
    read_only_by_owner: bool = False
    raw_command_present_in_source: bool = False
    # The panel never projects command text or a private path into a payload.
    raw_command_exposed: Literal[False] = False
    private_path_present_in_source: bool = False
    private_path_exposed: Literal[False] = False
    executable_by_panel: Literal[False] = False
    bounded_safety_precondition: str = Field(default="", max_length=900)
    bounded_success_condition: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairRiskProjectionV1(BobaContract):
    repair_risk_projection_id: str = Field(min_length=1, max_length=180)
    repair_plan_snapshot_id: str | None = None
    repair_plan_id: str = Field(min_length=1, max_length=180)
    source_module_id: str = Field(default="repair_planner", max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    risk_dimension: str = Field(min_length=1, max_length=120)
    original_risk_level: str = Field(default="unknown", max_length=120)
    strategy_specific: bool = False
    blocked_by_owner: bool = False
    bounded_reasons: list[str] = Field(default_factory=list, max_length=16)
    bounded_mitigations: list[str] = Field(default_factory=list, max_length=16)
    bounded_residual_risk: str = Field(default="", max_length=900)
    acceptable_only_if: list[str] = Field(default_factory=list, max_length=16)
    confidence_value: float | None = None
    confidence_name: str = Field(default="", max_length=120)
    confidence_definition: str = Field(default="", max_length=700)
    current: bool = True
    stale: bool = False
    # A reversible plan is never presented as risk-free.
    reversible_does_not_mean_risk_free: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairApprovalRequirementV1(BobaContract):
    approval_requirement_id: str = Field(min_length=1, max_length=180)
    repair_plan_snapshot_id: str | None = None
    repair_plan_id: str = Field(min_length=1, max_length=180)
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(default="", max_length=180)
    source_record_digest: str = Field(default="", max_length=64)
    requirement_type: RepairApprovalRequirementType = "unknown"
    required: bool = True
    satisfied_by_owner: bool = False
    canonical_record_id: str | None = None
    canonical_record_digest: str | None = None
    current: bool = True
    stale: bool = False
    blocking: bool = True
    bounded_explanation: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_satisfaction_requires_record(self) -> BobaRepairApprovalRequirementV1:
        if self.satisfied_by_owner and not (
            self.canonical_record_id and self.canonical_record_digest
        ):
            raise ValueError(
                "An approval requirement cannot be satisfied without a canonical "
                "owner record and digest."
            )
        return self


class BobaRepairVerificationRequirementV1(BobaContract):
    verification_requirement_id: str = Field(min_length=1, max_length=180)
    repair_plan_snapshot_id: str | None = None
    repair_plan_id: str = Field(min_length=1, max_length=180)
    verification_type: RepairVerificationType = "unknown"
    required: bool = True
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(default="", max_length=180)
    source_record_digest: str = Field(default="", max_length=64)
    validator_ids: list[str] = Field(default_factory=list, max_length=32)
    artifact_reference_ids: list[str] = Field(default_factory=list, max_length=32)
    required_check_ids: list[str] = Field(default_factory=list, max_length=64)
    satisfied: bool = False
    independently_verified: bool = False
    blocks_acceptance_on_failure: bool = True
    current: bool = True
    stale: bool = False
    blocking: bool = True
    bounded_explanation: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_independent_verification(self) -> BobaRepairVerificationRequirementV1:
        if self.independently_verified and not self.satisfied:
            raise ValueError(
                "Independent verification cannot be recorded without the "
                "requirement being satisfied by its owner."
            )
        return self


class BobaRepairEvidenceCardV1(BobaContract):
    repair_evidence_card_id: str = Field(min_length=1, max_length=180)
    repair_plan_snapshot_id: str | None = None
    evidence_type: str = Field(min_length=1, max_length=120)
    source_module_id: str = Field(min_length=1, max_length=180)
    authority_domain: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(default="", max_length=64)
    source_schema_id: str = Field(default="unknown", max_length=180)
    source_schema_version: str = Field(default="unknown", max_length=80)
    title: str = Field(min_length=1, max_length=240)
    original_status: str = Field(default="unknown", max_length=160)
    original_decision: str | None = Field(default=None, max_length=200)
    bounded_summary: str = Field(default="", max_length=900)
    bounded_excerpt: str = Field(default="", max_length=MAX_EVIDENCE_EXCERPT_CHARS)
    excerpt_truncated: bool = False
    command_withheld: bool = False
    sensitive_values_redacted: bool = False
    private_paths_redacted: bool = False
    current: bool = False
    stale: bool = False
    historical: bool = False
    missing: bool = False
    authoritative: bool = True
    advisory_only: bool = False
    blocking: bool = False
    supports_step_ids: list[str] = Field(default_factory=list, max_length=32)
    supports_approval_requirement_ids: list[str] = Field(
        default_factory=list, max_length=32
    )
    supports_verification_requirement_ids: list[str] = Field(
        default_factory=list, max_length=32
    )
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairRecoveryLinkV1(BobaContract):
    repair_recovery_link_id: str = Field(min_length=1, max_length=180)
    repair_plan_snapshot_id: str | None = None
    repair_plan_id: str = Field(min_length=1, max_length=180)
    source_module_id: str = Field(default="tool_recovery", max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    recovery_case_id: str = Field(default="", max_length=180)
    recovery_attempt_id: str = Field(min_length=1, max_length=180)
    attempt_number: int | None = None
    original_status: str = Field(default="unknown", max_length=120)
    linked_by_strategy_id: bool = False
    attempted: bool = False
    completed: bool = False
    succeeded_by_owner: bool = False
    independently_verified: bool = False
    verification_source_ids: list[str] = Field(default_factory=list, max_length=16)
    rollback_attempted: bool = False
    rollback_status: str = Field(default="unavailable", max_length=120)
    resulting_failure_class: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    current: bool = True
    stale: bool = False
    historical: bool = False
    bounded_summary: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_recovery_claims(self) -> BobaRepairRecoveryLinkV1:
        if self.completed and not self.attempted:
            raise ValueError("A recovery attempt cannot complete without an attempt.")
        if self.independently_verified and not self.succeeded_by_owner:
            raise ValueError(
                "Independent verification requires the owner to report success first."
            )
        return self


class BobaRepairPlanConflictV1(BobaContract):
    conflict_record_id: str = Field(min_length=1, max_length=180)
    repair_plan_snapshot_id: str | None = None
    conflict_type: RepairPlanConflictType = "unknown"
    severity: str = Field(default="warning", max_length=80)
    source_record_ids: list[str] = Field(default_factory=list, max_length=16)
    source_record_digests: list[str] = Field(default_factory=list, max_length=16)
    step_projection_ids: list[str] = Field(default_factory=list, max_length=16)
    approval_requirement_ids: list[str] = Field(default_factory=list, max_length=16)
    verification_requirement_ids: list[str] = Field(default_factory=list, max_length=16)
    recovery_link_ids: list[str] = Field(default_factory=list, max_length=16)
    value_a: str = Field(default="", max_length=900)
    value_b: str = Field(default="", max_length=900)
    same_repair_plan: bool = False
    same_analysis_case: bool = False
    same_workflow_run: bool = False
    current_records: bool = False
    explicit_supersession_found: bool = False
    resolved: bool = False
    resolution_source_id: str | None = None
    blocks_action: bool = False
    human_review_required: bool = True
    bounded_summary: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Conflicts are reported only between records naming the same exact "
            "identity, and are never resolved by comparing confidence or risk.",
        ],
        max_length=16,
    )


class BobaRepairPlanComparisonV1(BobaContract):
    comparison_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    repair_plan_ids: list[str] = Field(min_length=2, max_length=MAX_COMPARISON_PLANS)
    created_at: str = Field(default_factory=now_iso)
    comparison_type: RepairPlanComparisonType = "side_by_side"
    same_repair_case: bool = False
    same_analysis_case: bool = False
    same_incident: bool = False
    same_workflow_run: bool = False
    repair_plan_snapshot_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_PLANS
    )
    strategy_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    step_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    approval_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    risk_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    destructive_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    rollback_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    verification_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    recovery_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    evidence_coverage_comparison: list[dict[str, Any]] = Field(
        default_factory=list, max_length=8
    )
    warning_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    limitation_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    current_repair_plan_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_PLANS
    )
    historical_repair_plan_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_PLANS
    )
    missing_field_paths: list[str] = Field(default_factory=list, max_length=32)
    no_automatic_winner: Literal[True] = True
    no_automatic_plan_selection: Literal[True] = True
    no_automatic_execution_selection: Literal[True] = True
    bounded_summary: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairPlanActionDescriptorV1(BobaContract):
    action_descriptor_id: str = Field(min_length=1, max_length=180)
    display_name: str = Field(min_length=1, max_length=160)
    action_class: str = Field(min_length=1, max_length=120)
    owning_module_id: str = Field(min_length=1, max_length=180)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    supported_plan_states: list[str] = Field(default_factory=list, max_length=16)
    allowed_decision_values: list[str] = Field(default_factory=list, max_length=16)
    requires_reason: bool = False
    maximum_reason_length: int = Field(default=_MAX_REASON_LENGTH, ge=0, le=1_200)
    requires_confirmation: bool = True
    requires_current_snapshot: bool = True
    requires_workflow_revision: bool = False
    requires_repair_plan_digest: bool = True
    requires_source_record_digests: bool = True
    requires_reviewer_context: bool = True
    requires_safety_gate: bool = False
    requires_final_decision_bus: bool = False
    authoritative: bool = False
    destructive: bool = False
    execution_capable: bool = False
    code_modifying: bool = False
    artifact_modifying: bool = False
    workflow_modifying: bool = False
    checkpoint_restoring: bool = False
    process_restarting: bool = False
    upload_or_publication: bool = False
    allowed_in_v1: bool = False
    availability: Literal["available", "unavailable"] = "unavailable"
    unavailable_reason: str = Field(default="", max_length=900)
    consequences: list[str] = Field(default_factory=list, max_length=12)
    does_not_do: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairPlanActionRequestV1(BobaContract):
    repair_plan_action_request_id: str = Field(min_length=1, max_length=180)
    repair_plan_review_session_id: str = Field(min_length=1, max_length=180)
    repair_plan_snapshot_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    repair_plan_id: str = Field(min_length=1, max_length=180)
    repair_case_id: str = Field(min_length=1, max_length=180)
    source_analysis_case_id: str = Field(default="", max_length=180)
    source_diagnostic_case_id: str = Field(default="", max_length=180)
    requested_at: str = Field(default_factory=now_iso)
    expires_at: str
    reviewer_context_id: str = Field(min_length=1, max_length=160)
    action_descriptor_id: str = Field(min_length=1, max_length=180)
    owning_module_id: str = Field(min_length=1, max_length=180)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    decision_value: str | None = Field(default=None, max_length=160)
    bounded_reason: str = Field(default="", max_length=_MAX_REASON_LENGTH)
    expected_project_snapshot_digest: str = Field(min_length=64, max_length=64)
    expected_workflow_revision: int = Field(default=0, ge=0)
    expected_repair_plan_digest: str = Field(min_length=64, max_length=64)
    expected_source_record_digests: dict[str, str] = Field(
        default_factory=dict, max_length=24
    )
    expected_safety_record_digest: str | None = Field(default=None, max_length=64)
    expected_final_decision_record_digest: str | None = Field(default=None, max_length=64)
    confirmation_context_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=180)
    confirmed: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairPlanActionReceiptV1(BobaContract):
    repair_plan_action_receipt_id: str = Field(min_length=1, max_length=180)
    repair_plan_action_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    repair_plan_id: str = Field(min_length=1, max_length=180)
    owning_module_id: str = Field(min_length=1, max_length=180)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    submitted_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None
    accepted_by_owner: bool = False
    canonical_request_id: str | None = None
    canonical_record_id: str | None = None
    canonical_record_digest: str | None = None
    canonical_status: str = "pending"
    authoritative_state_changed: bool = False
    plan_approved: bool = False
    plan_rejected: bool = False
    plan_revised: bool = False
    repair_executed: bool = False
    recovery_attempt_started: bool = False
    checkpoint_restored: bool = False
    process_restarted: bool = False
    workflow_changed: bool = False
    code_changed: bool = False
    artifact_changed: bool = False
    canonical_refresh_required: bool = True
    stale_state_rejected: bool = False
    duplicate_request_reused: bool = False
    error_code: str | None = None
    bounded_error_message: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairPlanReviewEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    repair_plan_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=180)
    source_event_id: str = Field(default="", max_length=180)
    source_sequence: int | None = None
    created_at: str | None = None
    received_at: str = Field(default_factory=now_iso)
    event_type: str = Field(default="canonical_event", max_length=160)
    severity: str = Field(default="informational", max_length=80)
    technical_message: str = Field(default="", max_length=MAX_STEP_DESCRIPTION_CHARS)
    easy_message: str = Field(default="", max_length=4_096)
    confirmed_fact: str = Field(default="", max_length=900)
    assessment: str = Field(default="", max_length=900)
    progress_current: int | None = None
    progress_total: int | None = None
    progress_percent: float | None = None
    requires_attention: bool = False
    canonical: bool = True
    replayed: bool = False
    represents_work: bool = True
    command_withheld: bool = False
    sensitive_values_redacted: bool = False
    private_paths_redacted: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairPlanReviewTimelineEntryV1(BobaContract):
    timeline_entry_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    repair_plan_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_event_id: str | None = None
    event_type: str = Field(default="canonical_event", max_length=160)
    occurred_at: str | None = None
    timestamp_precision: Literal["source", "unknown"] = "unknown"
    sequence: int | None = None
    confirmed_order: bool = False
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(default="", max_length=900)
    severity: str = Field(default="informational", max_length=80)
    current: bool = True
    historical: bool = False


class BobaRepairPlanReviewNotificationV1(BobaContract):
    notification_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    repair_plan_id: str = Field(min_length=1, max_length=180)
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    notification_type: str = Field(default="warning", max_length=120)
    severity: str = Field(default="warning", max_length=80)
    title: str = Field(min_length=1, max_length=240)
    bounded_message: str = Field(default="", max_length=900)
    requires_attention: bool = True
    human_action_required: bool = False
    current: bool = True
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairPlanReviewSummaryV1(BobaContract):
    total_plan_count: int = Field(default=0, ge=0)
    current_plan_count: int = Field(default=0, ge=0)
    stale_plan_count: int = Field(default=0, ge=0)
    historical_plan_count: int = Field(default=0, ge=0)
    superseded_plan_count: int = Field(default=0, ge=0)
    completed_plan_count: int = Field(default=0, ge=0)
    destructive_plan_count: int = Field(default=0, ge=0)
    reversible_plan_count: int = Field(default=0, ge=0)
    code_change_plan_count: int = Field(default=0, ge=0)
    artifact_change_plan_count: int = Field(default=0, ge=0)
    workflow_change_plan_count: int = Field(default=0, ge=0)
    checkpoint_restore_plan_count: int = Field(default=0, ge=0)
    process_restart_plan_count: int = Field(default=0, ge=0)
    tool_execution_plan_count: int = Field(default=0, ge=0)
    plans_requiring_human_review_count: int = Field(default=0, ge=0)
    plans_missing_approval_count: int = Field(default=0, ge=0)
    plans_missing_verification_count: int = Field(default=0, ge=0)
    plans_with_failed_recovery_count: int = Field(default=0, ge=0)
    command_bearing_step_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    current_selected_repair_plan_id: str | None = None
    current_comparison_repair_plan_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_PLANS
    )
    safest_next_review_action: str = Field(default="", max_length=700)
    required_human_actions: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairPlanReviewSignalUsageV1(BobaContract):
    canonical_repair_planner_records: bool = False
    canonical_root_cause_records: bool = False
    canonical_error_doctor_records: bool = False
    canonical_observer_records: bool = False
    canonical_code_surgeon_records: bool = False
    canonical_tool_recovery_records: bool = False
    canonical_validator_records: bool = False
    canonical_report_reader_records: bool = False
    canonical_artifact_records: bool = False
    canonical_output_quality_records: bool = False
    canonical_workflow_records: bool = False
    canonical_safety_records: bool = False
    canonical_final_decision_records: bool = False
    review_ui_integration: bool = True
    error_doctor_panel_integration: bool = True
    exact_identity_validation: bool = True
    exact_digest_validation: bool = True
    stale_snapshot_protection: bool = True
    bounded_step_projection: bool = True
    command_withholding: bool = True
    sensitive_value_redaction: bool = True
    private_path_redaction: bool = True
    canonical_action_receipts: bool = True
    truthful_events: bool = True
    plan_created_by_panel: Literal[False] = False
    plan_revised_by_panel: Literal[False] = False
    plan_approved_by_panel: Literal[False] = False
    plan_rejected_by_panel: Literal[False] = False
    plan_executed_by_panel: Literal[False] = False
    step_executed_by_panel: Literal[False] = False
    recovery_executed_by_panel: Literal[False] = False
    checkpoint_restored_by_panel: Literal[False] = False
    process_restarted_by_panel: Literal[False] = False
    workflow_changed_by_panel: Literal[False] = False
    code_modified_by_panel: Literal[False] = False
    artifact_modified_by_panel: Literal[False] = False
    raw_command_exposed: Literal[False] = False
    private_path_exposed: Literal[False] = False
    hidden_plan_ranking_created: Literal[False] = False
    hidden_repair_success_score_created: Literal[False] = False
    hidden_safety_score_created: Literal[False] = False
    optimistic_authority_update_used: Literal[False] = False
    arbitrary_module_used: Literal[False] = False
    arbitrary_operation_used: Literal[False] = False
    arbitrary_url_used: Literal[False] = False
    arbitrary_path_used: Literal[False] = False
    untrusted_html_used: Literal[False] = False
    command_execution_used: Literal[False] = False
    shell_execution_used: Literal[False] = False
    powershell_execution_used: Literal[False] = False
    git_execution_used: Literal[False] = False
    ffmpeg_execution_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    tool_download_used: Literal[False] = False
    media_generation_used: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_output_modified: Literal[False] = False
    approval_created_locally: Literal[False] = False
    safety_decision_created_locally: Literal[False] = False
    rights_decision_created_locally: Literal[False] = False
    final_decision_created_locally: Literal[False] = False
    upload_used: Literal[False] = False
    publication_used: Literal[False] = False
    external_analytics_used: Literal[False] = False
    rights_bypass_used: Literal[False] = False
    safety_bypass_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairPlanReviewSetV1(BobaContract):
    schema_version: Literal["boba_repair_plan_review_v1"] = "boba_repair_plan_review_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    registry_snapshots: list[BobaRepairPlanRegistrySnapshotV1] = Field(
        default_factory=list, max_length=8
    )
    review_sessions: list[BobaRepairPlanReviewSessionV1] = Field(
        default_factory=list, max_length=16
    )
    repair_plan_references: list[BobaRepairPlanReferenceV1] = Field(
        default_factory=list, max_length=MAX_LOADED_PLANS
    )
    repair_plan_queue_items: list[BobaRepairPlanQueueItemV1] = Field(
        default_factory=list, max_length=MAX_LOADED_PLANS
    )
    repair_plan_snapshots: list[BobaRepairPlanSnapshotV1] = Field(
        default_factory=list, max_length=16
    )
    step_projections: list[BobaRepairStepProjectionV1] = Field(
        default_factory=list, max_length=256
    )
    risk_projections: list[BobaRepairRiskProjectionV1] = Field(
        default_factory=list, max_length=128
    )
    approval_requirements: list[BobaRepairApprovalRequirementV1] = Field(
        default_factory=list, max_length=128
    )
    verification_requirements: list[BobaRepairVerificationRequirementV1] = Field(
        default_factory=list, max_length=192
    )
    evidence_cards: list[BobaRepairEvidenceCardV1] = Field(
        default_factory=list, max_length=256
    )
    recovery_links: list[BobaRepairRecoveryLinkV1] = Field(
        default_factory=list, max_length=128
    )
    conflict_records: list[BobaRepairPlanConflictV1] = Field(
        default_factory=list, max_length=128
    )
    comparisons: list[BobaRepairPlanComparisonV1] = Field(
        default_factory=list, max_length=8
    )
    action_requests: list[BobaRepairPlanActionRequestV1] = Field(
        default_factory=list, max_length=32
    )
    action_receipts: list[BobaRepairPlanActionReceiptV1] = Field(
        default_factory=list, max_length=32
    )
    timeline_entries: list[BobaRepairPlanReviewTimelineEntryV1] = Field(
        default_factory=list, max_length=MAX_TIMELINE_ENTRIES
    )
    events: list[BobaRepairPlanReviewEventV1] = Field(
        default_factory=list, max_length=_MAX_EVENTS
    )
    notifications: list[BobaRepairPlanReviewNotificationV1] = Field(
        default_factory=list, max_length=64
    )
    review_summary: BobaRepairPlanReviewSummaryV1
    signal_usage: BobaRepairPlanReviewSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


# ----------------------------------------------------------------------
# Fixed registries
# ----------------------------------------------------------------------
# (module_id, title, authority_domain, store loader, source class, advisory_only)
# Every loader name is a real ``BobaMemoryStore`` method verified during the audit.
_REPAIR_SOURCES: tuple[tuple[str, str, str, str, str, bool], ...] = (
    (
        "repair_planner",
        "Repair Planner",
        "repair_plan",
        "load_boba_repair_planner",
        "plan",
        False,
    ),
    (
        "root_cause_analyzer",
        "Root Cause Analyzer",
        "root_cause",
        "load_boba_root_cause_analyzer",
        "evidence",
        False,
    ),
    ("error_doctor", "Error Doctor", "diagnosis", "load_boba_error_doctor", "evidence", False),
    ("observer", "Observer", "observation", "load_observer_report", "evidence", False),
    (
        "code_surgeon",
        "Code Surgeon",
        "code_repair",
        "load_boba_code_surgeon",
        "evidence",
        False,
    ),
    (
        "tool_recovery",
        "Tool Recovery",
        "tool_recovery",
        "load_boba_tool_recovery",
        "evidence",
        False,
    ),
    (
        "validator_runner",
        "Validator Runner",
        "validation",
        "load_boba_validator_runner",
        "verification",
        False,
    ),
    (
        "report_reader",
        "Report Reader",
        "reporting",
        "load_boba_report_reader",
        "verification",
        False,
    ),
    (
        "artifact_inspector",
        "Artifact Inspector",
        "artifacts",
        "load_boba_artifact_inspector",
        "verification",
        False,
    ),
    (
        "output_quality_reviewer",
        "Output Quality Reviewer",
        "output_quality",
        "load_boba_output_quality_reviewer",
        "verification",
        False,
    ),
    (
        "workflow_controller",
        "Workflow Controller",
        "workflow",
        "load_boba_workflow_controller",
        "approval",
        False,
    ),
    ("safety_gate", "Safety Gate", "safety", "load_boba_safety_gate", "approval", False),
    (
        "final_decision_bus",
        "Final Decision Bus",
        "final_decision",
        "load_boba_final_decision_bus",
        "approval",
        False,
    ),
    (
        "autopilot_controller",
        "Autopilot Controller",
        "autopilot",
        "load_boba_autopilot_controller",
        "evidence",
        True,
    ),
)

# Only the Repair Planner record is required: it owns the repair plan identity.
_REQUIRED_SOURCE_IDS = ("repair_planner",)

# Fourteen deterministic presentation tiers. A tier is a display order, never a
# score, a plan ranking or a repair-success estimate.
REPAIR_PLAN_QUEUE_PRIORITY_TIERS: tuple[tuple[int, str], ...] = (
    (10, "current_destructive_plan_awaiting_human_or_safety_approval"),
    (20, "current_plan_proposing_code_artifact_or_workflow_change"),
    (30, "current_plan_proposing_checkpoint_restore_or_process_restart"),
    (40, "current_plan_with_conflicting_approval_records"),
    (50, "current_plan_with_missing_root_cause_evidence"),
    (60, "current_plan_with_missing_verification_requirements"),
    (70, "current_plan_linked_to_a_failed_recovery_attempt"),
    (80, "current_plan_with_stale_validator_or_artifact_evidence"),
    (90, "current_reversible_plan_awaiting_review"),
    (100, "other_current_plan_requiring_human_review"),
    (110, "other_current_plan"),
    (120, "completed_but_unverified_plan"),
    (130, "superseded_plan"),
    (140, "historical_plan"),
)

# Source-owned risk ordering, transcribed from ``BobaRepairRiskLevelV1`` usage.
# Used only for the explicit "source severity" sort, never to build a score.
_RISK_ORDER: tuple[str, ...] = (
    "blocking",
    "critical",
    "high",
    "moderate",
    "medium",
    "low",
    "minimal",
    "none",
    "unknown",
)

# The eleven named risk dimensions Repair Planner records on its own assessment.
_RISK_DIMENSIONS: tuple[str, ...] = (
    "overall_risk",
    "source_data_risk",
    "artifact_loss_risk",
    "output_quality_risk",
    "workflow_corruption_risk",
    "configuration_risk",
    "environment_risk",
    "security_risk",
    "rights_safety_risk",
    "external_dependency_risk",
    "rollback_failure_risk",
    "human_error_risk",
)

_SECTION_DEFINITIONS: tuple[tuple[str, str, bool], ...] = (
    ("overview", "Plan Overview", False),
    ("steps", "Proposed Steps", False),
    ("risk", "Risk Assessment", False),
    ("approvals", "Approval Requirements", False),
    ("verification", "Verification Requirements", False),
    ("evidence", "Evidence", True),
    ("recovery", "Recovery History", True),
    ("conflicts", "Conflicts", True),
    ("timeline", "Timeline", True),
)


def build_fixed_repair_source_registry() -> dict[str, dict[str, Any]]:
    """Return the fixed repair-plan evidence source registry."""
    registry: dict[str, dict[str, Any]] = {}
    for module_id, title, domain, loader, source_class, advisory in _REPAIR_SOURCES:
        if module_id in registry:
            raise ValidationError("Duplicate BOBA repair plan review source descriptor.")
        registry[module_id] = {
            "source_id": module_id,
            "title": title,
            "authority_domain": domain,
            "loader": loader,
            "source_class": source_class,
            "advisory_only": advisory,
            "required": module_id in _REQUIRED_SOURCE_IDS,
        }
    return registry


def build_fixed_repair_section_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for section_id, title, collapsed in _SECTION_DEFINITIONS:
        if section_id in registry:
            raise ValidationError("Duplicate BOBA repair plan review section descriptor.")
        registry[section_id] = {
            "section_id": section_id,
            "title": title,
            "collapsed_by_default": collapsed,
        }
    return registry


def build_fixed_repair_plan_action_registry() -> (
    dict[str, BobaRepairPlanActionDescriptorV1]
):
    """Return the fixed action registry.

    One action is available in V1. Review UI already owns an ``incident``-targeted
    acknowledgement operation, and a repair plan is bound to an exact incident
    through ``source_diagnostic_case_id``. That action acknowledges the linked
    incident and is labelled as doing nothing to the plan.

    ``ReviewTargetType`` defines no repair-plan target type, Repair Planner
    exposes only ``load``, ``generate``, ``export`` and ``reset``, and every
    execution path is an ``approved_execution`` operation owned elsewhere. Every
    other action is therefore declared unavailable with its exact reason.
    """
    definitions = [
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_acknowledge_linked_incident_v1",
            display_name="Acknowledge the linked incident",
            action_class="ui_metadata_acknowledgement",
            owning_module_id="review_ui",
            owning_operation_id="acknowledge_notification",
            supported_plan_states=["current", "stale", "completed"],
            allowed_decision_values=["acknowledged"],
            requires_reason=False,
            requires_confirmation=True,
            requires_current_snapshot=False,
            requires_repair_plan_digest=True,
            requires_source_record_digests=False,
            requires_reviewer_context=True,
            authoritative=False,
            allowed_in_v1=True,
            availability="available",
            consequences=[
                "Records the incident this plan belongs to in the Review UI "
                "session's acknowledged notification list, which Review UI owns.",
            ],
            does_not_do=[
                "Does not acknowledge, approve, reject or revise the repair plan.",
                "Does not change the plan status or any approval requirement.",
                "Does not execute the plan or any step.",
                "Does not start a recovery attempt or retry a tool.",
                "Does not restore a checkpoint or restart a process.",
                "Does not transition the workflow.",
                "Does not modify code, artifacts or media.",
                "Does not grant Rights, Safety or Final Decision approval.",
                "Does not run a command, shell, Git or FFmpeg.",
                "Does not upload or publish anything.",
            ],
            limitations=[
                "Review UI defines no repair-plan target type, so this "
                "acknowledgement is scoped to the linked incident only.",
                "The plan and the incident both stay visible until their owning "
                "modules resolve them.",
            ],
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_acknowledge_plan_v1",
            display_name="Acknowledge repair plan",
            action_class="ui_metadata_acknowledgement",
            owning_module_id="review_ui",
            owning_operation_id="unavailable_no_repair_plan_target_type",
            supported_plan_states=["current"],
            availability="unavailable",
            unavailable_reason=(
                "Review UI's ReviewTargetType vocabulary defines project, "
                "workflow_stage, incident, approval_request and other targets but "
                "no repair-plan target, and acknowledge_notification accepts only "
                "project, incident and workflow_stage."
            ),
            limitations=[
                "Acknowledging the plan itself would misattribute the canonical "
                "target type, so the linked-incident acknowledgement is offered "
                "instead.",
            ],
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_approve_plan_v1",
            display_name="Approve repair plan",
            action_class="human_plan_approval",
            owning_module_id="repair_planner",
            owning_operation_id="unavailable_no_canonical_plan_approval_operation",
            supported_plan_states=["current"],
            allowed_decision_values=["approve"],
            requires_reason=True,
            requires_workflow_revision=True,
            requires_safety_gate=True,
            requires_final_decision_bus=True,
            authoritative=True,
            availability="unavailable",
            unavailable_reason=(
                "Repair Planner records an approval gate but exposes no operation "
                "that records a human approval decision for it. Its registered "
                "operations are load, generate, export and reset only."
            ),
            limitations=[
                "Approving a plan would also require a Safety Gate classification "
                "and Final Decision Bus authorisation that no existing operation "
                "binds to a repair plan.",
                "The approval gate already pins final_human_approval_required.",
            ],
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_reject_plan_v1",
            display_name="Reject repair plan",
            action_class="human_plan_rejection",
            owning_module_id="repair_planner",
            owning_operation_id="unavailable_no_canonical_plan_rejection_operation",
            supported_plan_states=["current"],
            allowed_decision_values=["reject"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            unavailable_reason=(
                "No owning operation records a human rejection for a repair "
                "strategy. Repair Planner recomputes rejected_strategies itself."
            ),
            limitations=["Plan status is recomputed by Repair Planner, not edited."],
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_request_plan_revision_v1",
            display_name="Request repair-plan revision",
            action_class="human_revision_request",
            owning_module_id="repair_planner",
            owning_operation_id="unavailable_no_canonical_revision_request_operation",
            supported_plan_states=["current"],
            allowed_decision_values=["request_revision"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            unavailable_reason=(
                "Repair strategies carry no revision identity, so a revision "
                "request has nothing canonical to bind to."
            ),
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_request_plan_regeneration_v1",
            display_name="Request repair-plan regeneration",
            action_class="human_regeneration_request",
            owning_module_id="repair_planner",
            owning_operation_id="unavailable_no_single_plan_regeneration",
            supported_plan_states=["current"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            unavailable_reason=(
                "repair_planner.generate rebuilds the whole planning set from Root "
                "Cause Analyzer, which would make this panel a second Repair "
                "Planner. No single-plan regeneration operation exists."
            ),
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_request_recovery_attempt_v1",
            display_name="Request recovery attempt",
            action_class="recovery_execution_request",
            owning_module_id="tool_recovery_brain",
            owning_operation_id="unavailable_execution_action_withheld_in_v1",
            supported_plan_states=["current"],
            requires_reason=True,
            requires_workflow_revision=True,
            requires_safety_gate=True,
            requires_final_decision_bus=True,
            authoritative=True,
            destructive=True,
            execution_capable=True,
            artifact_modifying=True,
            availability="unavailable",
            unavailable_reason=(
                "tool_recovery_brain.execute_approved is an approved_execution "
                "operation that starts real tool processes."
            ),
            limitations=[
                "Repair Plan Panel V1 exposes no execution action; recovery must "
                "be started through its own approval chain, not from a panel.",
            ],
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_request_tool_retry_v1",
            display_name="Request tool retry",
            action_class="tool_retry_request",
            owning_module_id="tool_recovery_brain",
            owning_operation_id="unavailable_execution_action_withheld_in_v1",
            supported_plan_states=["current"],
            requires_reason=True,
            requires_safety_gate=True,
            authoritative=True,
            execution_capable=True,
            availability="unavailable",
            unavailable_reason=(
                "A tool retry runs a real command through Tool Recovery's "
                "approved_execution path and is withheld from the panel."
            ),
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_request_checkpoint_restore_v1",
            display_name="Request checkpoint restore",
            action_class="checkpoint_restore_request",
            owning_module_id="workflow_controller",
            owning_operation_id="unavailable_resume_is_future_gated",
            supported_plan_states=["current"],
            requires_reason=True,
            requires_workflow_revision=True,
            authoritative=True,
            execution_capable=True,
            workflow_modifying=True,
            checkpoint_restoring=True,
            availability="unavailable",
            unavailable_reason=(
                "workflow_controller.resume is registered future_gated, so no "
                "checkpoint restoration entry point is available at all."
            ),
            limitations=[
                "Restoring a checkpoint changes generated state and workflow "
                "position, which this panel must never do.",
            ],
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_escalate_plan_v1",
            display_name="Escalate repair plan",
            action_class="escalation_request",
            owning_module_id="repair_planner",
            owning_operation_id="unavailable_no_canonical_escalation_operation",
            supported_plan_states=["current"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            unavailable_reason=(
                "Repair Planner records execution handoff documents but no module "
                "exposes an operation that creates one."
            ),
            limitations=[
                "The execution handoffs Repair Planner already recorded are shown "
                "as evidence instead, and each pins apply_automatically=False.",
            ],
        ),
        BobaRepairPlanActionDescriptorV1(
            action_descriptor_id="repair_plan_action_record_plan_review_note_v1",
            display_name="Record repair-plan review note",
            action_class="advisory_reviewer_note",
            owning_module_id="creator_learning",
            owning_operation_id="unavailable_no_repair_plan_feedback_target_type",
            supported_plan_states=["current", "stale", "historical"],
            requires_reason=True,
            availability="unavailable",
            unavailable_reason=(
                "Creator Learning owns advisory feedback, but its "
                "BobaCreatorFeedbackTargetType vocabulary is creative-artifact "
                "scoped and defines no repair-plan, repair-case or incident target."
            ),
            limitations=[
                "Review-session annotations are offered instead and are always "
                "labelled as not part of the canonical repair plan.",
            ],
        ),
    ]
    registry: dict[str, BobaRepairPlanActionDescriptorV1] = {}
    for descriptor in definitions:
        if descriptor.action_descriptor_id in registry:
            raise ValidationError("Duplicate BOBA repair plan review action descriptor.")
        if descriptor.availability == "unavailable" and not descriptor.unavailable_reason:
            raise ValidationError(
                "An unavailable repair plan action must state why it is unavailable."
            )
        if descriptor.availability == "available" and descriptor.authoritative:
            raise ValidationError(
                "Repair Plan Review V1 exposes no authoritative repair-plan action."
            )
        if descriptor.availability == "available" and (
            descriptor.execution_capable
            or descriptor.destructive
            or descriptor.code_modifying
            or descriptor.artifact_modifying
            or descriptor.workflow_modifying
            or descriptor.checkpoint_restoring
            or descriptor.process_restarting
            or descriptor.upload_or_publication
        ):
            raise ValidationError(
                "Repair Plan Review V1 cannot expose an execution, destructive, "
                "code-modifying, artifact-modifying, workflow-modifying, "
                "checkpoint-restoring, process-restarting, upload or publication "
                "action."
            )
        registry[descriptor.action_descriptor_id] = descriptor
    return registry


def repair_plan_queue_priority_tiers() -> tuple[tuple[int, str], ...]:
    return REPAIR_PLAN_QUEUE_PRIORITY_TIERS


def source_risk_order() -> tuple[str, ...]:
    return _RISK_ORDER


def repair_risk_dimensions() -> tuple[str, ...]:
    return _RISK_DIMENSIONS


def descriptor_does_not_do(action_descriptor_id: str) -> list[str]:
    """Return the fixed non-consequence list for an action descriptor."""
    descriptor = build_fixed_repair_plan_action_registry().get(action_descriptor_id)
    return list(descriptor.does_not_do) if descriptor else []


# ----------------------------------------------------------------------
# Review engine
# ----------------------------------------------------------------------
class BobaRepairPlanReviewV1:
    """Read-only repair-plan review projections and constrained action routing."""

    def __init__(self, store: BobaMemoryStore, integration: BobaIntegration) -> None:
        self.store = store
        self.integration = integration

    # ------------------------------------------------------------------
    # Trusted source access
    # ------------------------------------------------------------------
    def _source_payload(self, source_id: str, project_id: str) -> dict[str, Any]:
        """Read one fixed source through its fixed store loader."""
        descriptor = build_fixed_repair_source_registry().get(source_id)
        if descriptor is None:
            raise ValidationError("Unknown BOBA repair plan review source.")
        loader = getattr(self.store, str(descriptor["loader"]), None)
        if loader is None:
            return {}
        try:
            return _as_mapping(loader(project_id))
        except (ValidationError, NotFoundError, OSError):
            return {}

    def _keyed_rows(
        self, source_id: str, project_id: str, list_key: str, key_field: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Group a source's records by the identity field that links them."""
        payload = self._source_payload(source_id, project_id)
        rows = payload.get(list_key)
        grouped: dict[str, list[dict[str, Any]]] = {}
        if not isinstance(rows, list):
            return grouped
        for entry in rows[:2_048]:
            if not isinstance(entry, Mapping):
                continue
            mapped = _as_mapping(entry)
            key = _safe_text(mapped.get(key_field), 180)
            if key:
                grouped.setdefault(key, []).append(mapped)
        return grouped

    def _indexed_rows(
        self, source_id: str, project_id: str, list_key: str, key_field: str
    ) -> dict[str, dict[str, Any]]:
        """Index a source's records by a unique identity field."""
        indexed: dict[str, dict[str, Any]] = {}
        for key, rows in self._keyed_rows(
            source_id, project_id, list_key, key_field
        ).items():
            if rows:
                indexed[key] = rows[0]
        return indexed

    def _plan_rows(self, project_id: str) -> list[tuple[dict[str, Any], dict[str, Any], int]]:
        """Return (strategy, owning planning case, creation index).

        A repair plan is one ``BobaRepairStrategyV1``. Repair Planner's own list
        order is preserved as the creation index; the panel never reorders the
        owner's records to imply a ranking.
        """
        payload = self._source_payload("repair_planner", project_id)
        strategies = payload.get("repair_strategies")
        if not isinstance(strategies, list):
            return []
        cases = self._indexed_rows(
            "repair_planner", project_id, "repair_cases", "repair_case_id"
        )
        rows: list[tuple[dict[str, Any], dict[str, Any], int]] = []
        for index, entry in enumerate(strategies[:MAX_LOADED_PLANS]):
            if not isinstance(entry, Mapping):
                continue
            strategy = _as_mapping(entry)
            if not _safe_text(strategy.get("repair_strategy_id"), 180):
                continue
            case_id = _safe_text(strategy.get("repair_case_id"), 180)
            rows.append((strategy, cases.get(case_id, {}), index))
        return rows

    def _plan_record(
        self, project_id: str, repair_plan_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], int]:
        for strategy, case, index in self._plan_rows(project_id):
            if _safe_text(strategy.get("repair_strategy_id"), 180) == repair_plan_id:
                return strategy, case, index
        raise ValidationError("BOBA repair plan record is unavailable.")

    def _repair_steps(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        """Group Repair Planner steps by the strategy that owns them."""
        payload = self._source_payload("repair_planner", project_id)
        strategies = payload.get("repair_strategies")
        grouped: dict[str, list[dict[str, Any]]] = {}
        if not isinstance(strategies, list):
            return grouped
        for entry in strategies[:MAX_LOADED_PLANS]:
            if not isinstance(entry, Mapping):
                continue
            strategy = _as_mapping(entry)
            strategy_id = _safe_text(strategy.get("repair_strategy_id"), 180)
            steps = strategy.get("proposed_steps")
            if not strategy_id or not isinstance(steps, list):
                continue
            rows = [
                _as_mapping(step)
                for step in steps[:MAX_STEP_PROJECTIONS]
                if isinstance(step, Mapping)
            ]
            grouped[strategy_id] = rows
        return grouped

    def _risk_assessments(self, project_id: str) -> dict[str, dict[str, Any]]:
        return self._indexed_rows(
            "repair_planner", project_id, "risk_assessments", "risk_assessment_id"
        )

    def _approval_gates(self, project_id: str) -> dict[str, dict[str, Any]]:
        return self._indexed_rows(
            "repair_planner", project_id, "approval_gates", "approval_gate_id"
        )

    def _rollback_plans(self, project_id: str) -> dict[str, dict[str, Any]]:
        return self._indexed_rows(
            "repair_planner", project_id, "rollback_plans", "rollback_plan_id"
        )

    def _checkpoint_plans(self, project_id: str) -> dict[str, dict[str, Any]]:
        return self._indexed_rows(
            "repair_planner", project_id, "checkpoint_plans", "checkpoint_plan_id"
        )

    def _validation_plans(self, project_id: str) -> dict[str, dict[str, Any]]:
        return self._indexed_rows(
            "repair_planner", project_id, "validation_plans", "validation_plan_id"
        )

    def _quality_preservation_plans(self, project_id: str) -> dict[str, dict[str, Any]]:
        return self._indexed_rows(
            "repair_planner",
            project_id,
            "quality_preservation_plans",
            "quality_preservation_plan_id",
        )

    def _execution_handoffs(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._keyed_rows(
            "repair_planner", project_id, "execution_handoffs", "repair_strategy_id"
        )

    def _rejected_strategies(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._keyed_rows(
            "repair_planner", project_id, "rejected_strategies", "repair_case_id"
        )

    def _analysis_cases(self, project_id: str) -> dict[str, dict[str, Any]]:
        return self._indexed_rows(
            "root_cause_analyzer", project_id, "analysis_cases", "analysis_case_id"
        )

    def _root_cause_candidates(self, project_id: str) -> dict[str, dict[str, Any]]:
        return self._indexed_rows(
            "root_cause_analyzer",
            project_id,
            "root_cause_candidates",
            "root_cause_candidate_id",
        )

    def _diagnostic_cases(self, project_id: str) -> dict[str, dict[str, Any]]:
        return self._indexed_rows(
            "error_doctor", project_id, "diagnostic_cases", "diagnostic_case_id"
        )

    def _recovery_cases_for(self, project_id: str, repair_case_id: str) -> list[dict[str, Any]]:
        return self._keyed_rows(
            "tool_recovery", project_id, "recovery_cases", "source_repair_case_id"
        ).get(repair_case_id, [])

    def _recovery_attempts(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._keyed_rows(
            "tool_recovery", project_id, "recovery_attempts", "recovery_case_id"
        )

    def _recovery_rollbacks(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._keyed_rows(
            "tool_recovery", project_id, "rollback_records", "recovery_attempt_id"
        )

    def _recovery_validations(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._keyed_rows(
            "tool_recovery", project_id, "output_validations", "recovery_attempt_id"
        )

    def _code_repair_cases_for(
        self, project_id: str, repair_case_id: str
    ) -> list[dict[str, Any]]:
        return self._keyed_rows(
            "code_surgeon", project_id, "repair_cases", "source_repair_case_id"
        ).get(repair_case_id, [])

    # ------------------------------------------------------------------
    # Digests and identity
    # ------------------------------------------------------------------
    def _workflow_run(self, project_id: str) -> dict[str, Any]:
        return _active_workflow_run(self._source_payload("workflow_controller", project_id))

    def _workflow_revision(self, project_id: str) -> int:
        revision = self._workflow_run(project_id).get("revision")
        return revision if isinstance(revision, int) and revision >= 0 else 0

    def _project_snapshot_digest(self, project_id: str) -> str:
        digests = {
            source_id: _digest(_safe_payload(self._source_payload(source_id, project_id)))
            for source_id in build_fixed_repair_source_registry()
        }
        return _digest(digests)

    def _repair_plan_digest(self, project_id: str, repair_plan_id: str) -> str:
        """Digest the exact plan, its case and every plan document it names."""
        try:
            strategy, case, _index = self._plan_record(project_id, repair_plan_id)
        except ValidationError:
            return _digest({"repair_plan_id": repair_plan_id, "state": "unavailable"})
        risk = self._risk_assessments(project_id).get(
            _safe_text(case.get("risk_assessment_id"), 180), {}
        )
        gate = self._approval_gates(project_id).get(
            _safe_text(case.get("approval_gate_id"), 180), {}
        )
        rollback = self._rollback_plans(project_id).get(
            _safe_text(case.get("rollback_plan_id"), 180), {}
        )
        checkpoint = self._checkpoint_plans(project_id).get(
            _safe_text(case.get("checkpoint_plan_id"), 180), {}
        )
        validation = self._validation_plans(project_id).get(
            _safe_text(case.get("validation_plan_id"), 180), {}
        )
        quality = self._quality_preservation_plans(project_id).get(
            _safe_text(case.get("quality_preservation_plan_id"), 180), {}
        )
        return _digest(
            {
                "strategy": _safe_payload(strategy),
                "case": _safe_payload(case),
                "risk": _safe_payload(risk),
                "approval_gate": _safe_payload(gate),
                "rollback": _safe_payload(rollback),
                "checkpoint": _safe_payload(checkpoint),
                "validation": _safe_payload(validation),
                "quality": _safe_payload(quality),
                "handoffs": _safe_payload(
                    self._execution_handoffs(project_id).get(repair_plan_id, [])
                ),
            }
        )

    def _safety_record_digest(self, project_id: str) -> str:
        return _digest(_safe_payload(self._source_payload("safety_gate", project_id)))

    def _final_decision_record_digest(self, project_id: str) -> str:
        return _digest(_safe_payload(self._source_payload("final_decision_bus", project_id)))

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def build_repair_plan_review_registry(self, project_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        sources = build_fixed_repair_source_registry()
        sections = build_fixed_repair_section_registry()
        actions = build_fixed_repair_plan_action_registry()
        available = [key for key in sources if self._source_payload(key, project_id)]
        unavailable = [key for key in sources if key not in available]
        source_rows = [
            {key: value for key, value in item.items() if key != "loader"}
            for item in sources.values()
        ]
        action_rows = [item.model_dump(mode="json") for item in actions.values()]
        payload = {
            "sources": source_rows,
            "sections": list(sections.values()),
            "actions": action_rows,
        }
        snapshot_id = _stable_id("repair_plan_registry", "v1", _digest(payload))
        stored = self.store.load_boba_repair_plan_review_registry(project_id, snapshot_id)
        registry = (
            BobaRepairPlanRegistrySnapshotV1.model_validate(stored)
            if isinstance(stored, Mapping)
            else BobaRepairPlanRegistrySnapshotV1(
                registry_snapshot_id=snapshot_id,
                plan_source_ids=[
                    key for key, row in sources.items() if row["source_class"] == "plan"
                ],
                evidence_source_ids=[
                    key for key, row in sources.items() if row["source_class"] == "evidence"
                ],
                approval_source_ids=[
                    key for key, row in sources.items() if row["source_class"] == "approval"
                ],
                verification_source_ids=[
                    key
                    for key, row in sources.items()
                    if row["source_class"] == "verification"
                ],
                available_source_ids=available,
                unavailable_source_ids=unavailable,
                action_descriptor_ids=list(actions),
                available_action_descriptor_ids=[
                    item.action_descriptor_id
                    for item in actions.values()
                    if item.allowed_in_v1 and item.availability == "available"
                ],
                unavailable_action_descriptor_ids=[
                    item.action_descriptor_id
                    for item in actions.values()
                    if not item.allowed_in_v1 or item.availability != "available"
                ],
                registry_digest=_digest(payload),
                limitations=[
                    "The registry is fixed source code; a browser request cannot "
                    "add a source, an action, a module, an operation, a URL, a "
                    "path or a command.",
                    "Repair Plan Panel V1 exposes no plan approval, plan "
                    "rejection, plan revision, execution, recovery, checkpoint "
                    "or workflow action.",
                    "A repair plan identity is the Repair Planner "
                    "repair_strategy_id, carried with its repair_case_id.",
                    NOT_EXECUTABLE_NOTICE,
                ],
            )
        )
        if not isinstance(stored, Mapping):
            self.store.save_boba_repair_plan_review_registry(
                project_id, snapshot_id, registry.model_dump(mode="json")
            )
        return {
            "registry_snapshot": registry.model_dump(mode="json"),
            "sources": source_rows,
            "sections": list(sections.values()),
            "actions": action_rows,
            "priority_tiers": [
                {"priority": priority, "reason": reason}
                for priority, reason in REPAIR_PLAN_QUEUE_PRIORITY_TIERS
            ],
            "source_risk_order": list(_RISK_ORDER),
            "risk_dimensions": list(_RISK_DIMENSIONS),
            "supported_repair_plan_schema_id": SUPPORTED_REPAIR_PLAN_SCHEMA_ID,
            "withheld_notices": {
                "command": COMMAND_WITHHELD_NOTICE,
                "private_path": PRIVATE_PATH_NOTICE,
                "not_executable": NOT_EXECUTABLE_NOTICE,
                "source_retained": SOURCE_RETAINED_NOTICE,
            },
        }

    def inspect_repair_plan_review_registry(self, project_id: str) -> dict[str, Any]:
        return self.build_repair_plan_review_registry(project_id)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_repair_plan_review_session(
        self,
        project_id: str,
        *,
        reviewer_context_id: str,
        selected_repair_plan_id: str | None = None,
        expires_in_seconds: int = 3_600,
    ) -> BobaRepairPlanReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(reviewer_context_id, "reviewer context id")
        if _SENSITIVE_KEY.search(reviewer_context_id):
            raise ValidationError("Reviewer context cannot contain credentials.")
        if selected_repair_plan_id is not None:
            _safe_id(selected_repair_plan_id, "repair plan id")
        session_id = f"repair_plan_review_session_{uuid4().hex}"
        now = datetime.now(UTC)
        session = BobaRepairPlanReviewSessionV1(
            repair_plan_review_session_id=session_id,
            project_id=project_id,
            reviewer_context_id=reviewer_context_id,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(
                now + timedelta(seconds=max(60, min(expires_in_seconds, 28_800)))
            ).isoformat(),
            selected_repair_plan_id=selected_repair_plan_id,
            session_digest=_digest(
                {
                    "session_id": session_id,
                    "project_id": project_id,
                    "reviewer_context_id": reviewer_context_id,
                    "selected_repair_plan_id": selected_repair_plan_id,
                }
            ),
            limitations=[
                "Review sessions hold only UI state.",
                "local_annotations are review-session metadata and are never part "
                "of the canonical repair plan.",
                NOT_EXECUTABLE_NOTICE,
            ],
        )
        self.store.save_boba_repair_plan_review_session(
            project_id, session_id, session.model_dump(mode="json")
        )
        return session

    def get_repair_plan_review_session(
        self, project_id: str, session_id: str
    ) -> BobaRepairPlanReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(session_id, "repair plan review session id")
        raw = self.store.load_boba_repair_plan_review_session(project_id, session_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA repair plan review session is unavailable.")
        session = BobaRepairPlanReviewSessionV1.model_validate(raw)
        if session.project_id != project_id:
            raise ValidationError("Repair plan review session belongs to another project.")
        expires_at = _parse_time(session.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            raise ValidationError("BOBA repair plan review session has expired.")
        return session

    def update_repair_plan_review_session(
        self, project_id: str, session_id: str, updates: Mapping[str, Any]
    ) -> BobaRepairPlanReviewSessionV1:
        session = self.get_repair_plan_review_session(project_id, session_id)
        allowed = {
            "selected_repair_plan_id",
            "comparison_repair_plan_ids",
            "active_filter",
            "active_sort",
            "active_section_id",
            "show_historical",
            "show_superseded",
            "show_completed",
            "show_technical_details",
            "show_recovery_history",
            "evidence_drawer_open",
            "timeline_drawer_open",
            "local_annotations",
            "read_repair_plan_ids",
        }
        unsafe = set(updates) - allowed
        if unsafe:
            raise ValidationError(
                "Repair plan review session update contains unsupported fields."
            )
        comparison = updates.get("comparison_repair_plan_ids")
        if isinstance(comparison, list) and len(comparison) > MAX_COMPARISON_PLANS:
            raise ValidationError(
                f"At most {MAX_COMPARISON_PLANS} repair plans may be compared."
            )
        payload = session.model_dump(mode="json")
        payload.update(_as_mapping(_safe_payload(dict(updates))))
        if "local_annotations" in updates:
            payload["local_annotations"] = self._bounded_annotations(
                updates.get("local_annotations")
            )
        payload["updated_at"] = now_iso()
        payload["session_digest"] = _digest(
            {key: value for key, value in payload.items() if key != "session_digest"}
        )
        updated = BobaRepairPlanReviewSessionV1.model_validate(payload)
        self.store.save_boba_repair_plan_review_session(
            project_id, session_id, updated.model_dump(mode="json")
        )
        return updated

    @staticmethod
    def _bounded_annotations(value: object) -> list[dict[str, str]]:
        """Bound and sanitise reviewer annotations. Never canonical plan text."""
        if not isinstance(value, list):
            return []
        rows: list[dict[str, str]] = []
        for entry in value[:MAX_ANNOTATIONS]:
            if not isinstance(entry, Mapping):
                continue
            text = _safe_text(entry.get("text"), MAX_ANNOTATION_LENGTH)
            if not text:
                continue
            if _contains_secret(text):
                raise ValidationError("Review annotations cannot contain credentials.")
            if source_holds_command(text):
                raise ValidationError(
                    "Review annotations cannot contain executable command text."
                )
            rows.append(
                {
                    "annotation_id": _safe_text(entry.get("annotation_id"), 120)
                    or _stable_id("repair_plan_annotation", text),
                    "repair_plan_id": _safe_text(entry.get("repair_plan_id"), 180),
                    "section_id": _safe_text(entry.get("section_id"), 120),
                    "text": text,
                    "notice": (
                        "Review-session annotation — not part of the canonical "
                        "repair plan."
                    ),
                }
            )
        return rows

    # ------------------------------------------------------------------
    # Repair plan references
    # ------------------------------------------------------------------
    def build_repair_plan_references(self, project_id: str) -> list[BobaRepairPlanReferenceV1]:
        """Project every persisted Repair Planner strategy as a reviewable plan."""
        _safe_id(project_id, "project id")
        payload = self._source_payload("repair_planner", project_id)
        if not payload:
            return []
        schema_id = _safe_text(payload.get("schema_version") or "unknown", 180)
        supported = schema_id == SUPPORTED_REPAIR_PLAN_SCHEMA_ID
        source_id = _safe_text(payload.get("source_id"), 512)
        created_at = _safe_text(payload.get("created_at"), 80) or now_iso()
        project_digest = self._project_snapshot_digest(project_id)
        run = self._workflow_run(project_id)
        run_id = _safe_text(run.get("workflow_run_id"), 180) or None
        stage_instance_id = _safe_text(run.get("current_stage_instance_id"), 180) or None
        revision = self._workflow_revision(project_id)
        analysis_cases = self._analysis_cases(project_id)

        references: list[BobaRepairPlanReferenceV1] = []
        for strategy, case, _index in self._plan_rows(project_id):
            repair_plan_id = _safe_text(strategy.get("repair_strategy_id"), 180)
            if not repair_plan_id or not _SAFE_RECORD_ID.fullmatch(repair_plan_id):
                continue
            repair_case_id = _safe_text(strategy.get("repair_case_id"), 180)
            if not repair_case_id:
                continue
            analysis_case_id = _safe_text(case.get("source_analysis_case_id"), 180)
            diagnostic_case_id = _safe_text(
                analysis_cases.get(analysis_case_id, {}).get("source_diagnostic_case_id"),
                180,
            )
            warnings: list[str] = []
            if not supported:
                warnings.append(
                    f"Repair plan schema '{schema_id}' is not supported by this panel."
                )
            if not case:
                warnings.append(
                    "The owning Repair Planner planning case is unavailable, so "
                    "plan status, approval gate and plan documents cannot be shown."
                )
            if not analysis_case_id:
                warnings.append(
                    "The plan names no Root Cause Analyzer case, so root-cause "
                    "evidence cannot be linked."
                )
            references.append(
                BobaRepairPlanReferenceV1(
                    repair_plan_reference_id=_stable_id(
                        "repair_plan_reference", project_id, repair_plan_id
                    ),
                    project_id=project_id,
                    source_id=source_id,
                    workflow_run_id=run_id,
                    stage_instance_id=stage_instance_id,
                    repair_plan_id=repair_plan_id,
                    # Repair Planner records no strategy revision identity.
                    repair_plan_revision_id=None,
                    repair_case_id=repair_case_id,
                    source_analysis_case_id=analysis_case_id,
                    source_diagnostic_case_id=diagnostic_case_id,
                    source_record_id=repair_plan_id,
                    source_record_digest=self._repair_plan_digest(
                        project_id, repair_plan_id
                    ),
                    source_schema_id=schema_id,
                    source_schema_version=schema_id,
                    schema_supported=supported,
                    original_status=_safe_text(
                        case.get("planning_status") or "unknown", 120
                    ),
                    original_strategy_type=_safe_text(
                        strategy.get("strategy_type") or "unknown", 120
                    ),
                    original_risk_level=_safe_text(
                        strategy.get("estimated_risk") or "unknown", 120
                    ),
                    affected_stage_id=_safe_text(case.get("workflow_stage"), 180),
                    affected_module_id=_safe_text(
                        strategy.get("target_module") or case.get("primary_module"), 180
                    ),
                    created_at=created_at,
                    updated_at=None,
                    project_snapshot_digest=project_digest,
                    workflow_revision=revision,
                    current=True,
                    # The owner keeps one current planning set, records no
                    # supersession marker and no historical archive, so these stay
                    # explicitly false and are never inferred from ordering.
                    stale=False,
                    historical=False,
                    superseded=False,
                    superseding_repair_plan_id=None,
                    warnings=warnings[:24],
                    limitations=[
                        "A repair plan is one Repair Planner repair strategy. Its "
                        "identity is the repair_strategy_id.",
                        "Repair Planner records no strategy revision identity and "
                        "no supersession field, so both remain absent.",
                        "The owner stores one current planning set; there is no "
                        "historical repair-plan archive.",
                        "Repair Planner proposed this strategy. The panel does not "
                        "state that it is the correct repair.",
                        SOURCE_RETAINED_NOTICE,
                    ],
                )
            )
        return references[:MAX_LOADED_PLANS]

    def _reference_for(
        self, project_id: str, repair_plan_id: str
    ) -> BobaRepairPlanReferenceV1:
        _safe_id(repair_plan_id, "repair plan id")
        for reference in self.build_repair_plan_references(project_id):
            if reference.repair_plan_id == repair_plan_id:
                return reference
        raise ValidationError(
            "BOBA repair plan is unknown, unavailable, or belongs to another project."
        )

    # ------------------------------------------------------------------
    # Step projections
    # ------------------------------------------------------------------
    def build_step_projections(
        self, project_id: str, repair_plan_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRepairStepProjectionV1]:
        """Project the owner's proposed steps without exposing command text."""
        reference = self._reference_for(project_id, repair_plan_id)
        strategy, _case, _index = self._plan_record(project_id, repair_plan_id)
        steps = self._repair_steps(project_id).get(repair_plan_id, [])
        rollback_available = bool(
            _safe_text(strategy.get("reversibility"), 120)
            in {"fully_reversible", "mostly_reversible", "partially_reversible"}
        )
        projections: list[BobaRepairStepProjectionV1] = []
        for step in steps[:MAX_STEP_PROJECTIONS]:
            step_id = _safe_text(step.get("repair_step_id"), 180)
            if not step_id:
                continue
            order = step.get("order")
            if not isinstance(order, int) or not 1 <= order <= MAX_STEP_PROJECTIONS:
                continue
            step_type = _safe_text(step.get("step_type") or "unknown", 120)
            description = bounded_step_description(step.get("description"))
            # ``target`` may hold literal command text, so it is never projected.
            # Only its command and private-path presence is reported.
            target_holds_command = source_holds_command(step.get("target"))
            target_holds_path = source_holds_private_path(step.get("target"))
            requires_command = bool(step.get("requires_command_execution"))
            warnings: list[str] = []
            if requires_command or target_holds_command:
                warnings.append(COMMAND_WITHHELD_NOTICE)
            if target_holds_path or description["private_paths_redacted"]:
                warnings.append(PRIVATE_PATH_NOTICE)
            projections.append(
                BobaRepairStepProjectionV1(
                    repair_step_projection_id=_stable_id(
                        "repair_step_projection", project_id, repair_plan_id, step_id
                    ),
                    repair_plan_snapshot_id=snapshot_id,
                    repair_plan_id=repair_plan_id,
                    source_record_id=step_id,
                    source_record_digest=_digest(_safe_payload(step)),
                    source_step_id=step_id,
                    original_order=order,
                    # Repair Planner records no per-step lifecycle status; every
                    # step it emits is a proposal.
                    original_status="proposed",
                    original_step_type=step_type,
                    bounded_description=description["text"],
                    # Repair Planner records no per-step rationale field.
                    bounded_reason="",
                    affected_module_ids=[
                        item
                        for item in [_safe_text(step.get("suggested_owner_module"), 180)]
                        if item
                    ],
                    # Repair Planner names no operation identity on a step.
                    affected_operation_ids=[],
                    requires_code_change=bool(step.get("requires_code_change")),
                    requires_artifact_change=step_type
                    in {"regenerate", "restore", "apply_patch"},
                    requires_tool_execution=requires_command
                    or step_type in {"retry", "switch_tool", "install_dependency"},
                    requires_process_restart=step_type == "restart_service",
                    requires_checkpoint_restore=step_type == "restore",
                    requires_workflow_transition=step_type
                    in {"switch_workflow", "resume_workflow"},
                    requires_human_approval=bool(
                        step.get("requires_human_approval", True)
                    ),
                    destructive=step_type in {"apply_patch", "restore", "regenerate"}
                    and not bool(step.get("read_only")),
                    reversible=bool(step.get("reversible")),
                    rollback_available=rollback_available
                    and bool(_safe_text(step.get("rollback_step_reference"), 180)),
                    verification_required=True,
                    read_only_by_owner=bool(step.get("read_only")),
                    raw_command_present_in_source=requires_command
                    or target_holds_command
                    or description["command_withheld"],
                    private_path_present_in_source=target_holds_path
                    or description["private_paths_redacted"],
                    bounded_safety_precondition=_safe_text(
                        step.get("safety_precondition"), 900
                    ),
                    bounded_success_condition=_safe_text(
                        step.get("success_condition"), 900
                    ),
                    warnings=warnings[:16],
                    limitations=[
                        NOT_EXECUTABLE_NOTICE,
                        "The step target field is never projected because it may "
                        "hold literal command text.",
                        "Repair Planner records no per-step status or rationale.",
                        "A reversible step is not a risk-free step, and a rollback "
                        "reference is not a rollback guarantee.",
                        SOURCE_RETAINED_NOTICE,
                    ],
                )
            )
        projections.sort(key=lambda item: (item.original_order, item.source_step_id))
        if not projections and reference.schema_supported:
            return []
        return projections

    def inspect_repair_steps(self, project_id: str, repair_plan_id: str) -> dict[str, Any]:
        projections = self.build_step_projections(project_id, repair_plan_id)
        return {
            "schema_version": "boba_repair_plan_review_steps_v1",
            "project_id": project_id,
            "repair_plan_id": repair_plan_id,
            "step_projections": [item.model_dump(mode="json") for item in projections],
            "step_count": len(projections),
            "command_bearing_step_count": sum(
                1 for item in projections if item.raw_command_present_in_source
            ),
            "destructive_step_count": sum(1 for item in projections if item.destructive),
            "read_only_step_count": sum(
                1 for item in projections if item.read_only_by_owner
            ),
            "raw_command_exposed": False,
            "private_path_exposed": False,
            "executable_by_panel": False,
            "notices": {
                "command": COMMAND_WITHHELD_NOTICE,
                "private_path": PRIVATE_PATH_NOTICE,
                "not_executable": NOT_EXECUTABLE_NOTICE,
                "source_retained": SOURCE_RETAINED_NOTICE,
            },
        }

    # ------------------------------------------------------------------
    # Risk projections
    # ------------------------------------------------------------------
    def build_risk_projections(
        self, project_id: str, repair_plan_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRepairRiskProjectionV1]:
        """Project every named owner risk dimension verbatim. No panel score."""
        _strategy, case, _index = self._plan_record(project_id, repair_plan_id)
        assessment = self._risk_assessments(project_id).get(
            _safe_text(case.get("risk_assessment_id"), 180), {}
        )
        if not assessment:
            return []
        record_id = _safe_text(assessment.get("risk_assessment_id"), 180) or "unavailable"
        record_digest = _digest(_safe_payload(assessment))
        shared_limitations = [
            "Risk levels are Repair Planner's own values, projected verbatim.",
            "The panel computes no composite risk score and no repair-success "
            "estimate.",
            "A reversible plan is not a risk-free plan.",
        ]
        projections: list[BobaRepairRiskProjectionV1] = []
        for dimension in _RISK_DIMENSIONS:
            level = _safe_text(assessment.get(dimension) or "unknown", 120)
            projections.append(
                BobaRepairRiskProjectionV1(
                    repair_risk_projection_id=_stable_id(
                        "repair_risk_projection", project_id, repair_plan_id, dimension
                    ),
                    repair_plan_snapshot_id=snapshot_id,
                    repair_plan_id=repair_plan_id,
                    source_record_id=record_id,
                    source_record_digest=record_digest,
                    risk_dimension=dimension,
                    original_risk_level=level,
                    strategy_specific=False,
                    blocked_by_owner=level == "blocked",
                    bounded_reasons=[
                        _safe_text(item, 700)
                        for item in assessment.get("residual_risks", [])
                        if isinstance(item, str)
                    ][:16]
                    if dimension == "overall_risk"
                    else [],
                    bounded_mitigations=[
                        _safe_text(item, 700)
                        for item in assessment.get("mitigations", [])
                        if isinstance(item, str)
                    ][:16]
                    if dimension == "overall_risk"
                    else [],
                    bounded_residual_risk="",
                    acceptable_only_if=[],
                    confidence_value=None,
                    confidence_name="",
                    confidence_definition="",
                    current=True,
                    stale=False,
                    warnings=[
                        _safe_text(item, 700)
                        for item in assessment.get("blockers", [])
                        if isinstance(item, str)
                    ][:16]
                    if level == "blocked"
                    else [],
                    limitations=shared_limitations,
                )
            )
        strategy_risks = assessment.get("strategy_risks")
        if isinstance(strategy_risks, list):
            for entry in strategy_risks[:_MAX_RISK_PROJECTIONS]:
                if not isinstance(entry, Mapping):
                    continue
                risk = _as_mapping(entry)
                if _safe_text(risk.get("strategy_id"), 180) != repair_plan_id:
                    continue
                confidence = risk.get("confidence")
                projections.append(
                    BobaRepairRiskProjectionV1(
                        repair_risk_projection_id=_stable_id(
                            "repair_risk_projection",
                            project_id,
                            repair_plan_id,
                            "strategy_specific",
                        ),
                        repair_plan_snapshot_id=snapshot_id,
                        repair_plan_id=repair_plan_id,
                        source_record_id=record_id,
                        source_record_digest=record_digest,
                        risk_dimension="strategy_risk",
                        original_risk_level=_safe_text(
                            risk.get("risk_level") or "unknown", 120
                        ),
                        strategy_specific=True,
                        blocked_by_owner=bool(risk.get("blocked")),
                        bounded_reasons=[
                            _safe_text(item, 700)
                            for item in risk.get("risk_reasons", [])
                            if isinstance(item, str)
                        ][:16],
                        bounded_mitigations=[
                            _safe_text(item, 700)
                            for item in risk.get("mitigations", [])
                            if isinstance(item, str)
                        ][:16],
                        bounded_residual_risk=_safe_text(risk.get("residual_risk"), 900),
                        acceptable_only_if=[
                            _safe_text(item, 700)
                            for item in risk.get("acceptable_only_if", [])
                            if isinstance(item, str)
                        ][:16],
                        confidence_value=float(confidence)
                        if isinstance(confidence, int | float)
                        else None,
                        confidence_name="repair_planner_reported_confidence"
                        if isinstance(confidence, int | float)
                        else "",
                        confidence_definition=(
                            "Repair Planner's own confidence in this strategy risk, "
                            "on its own 0.0 to 1.0 scale. The panel does not "
                            "compute, rescale or average it."
                        )
                        if isinstance(confidence, int | float)
                        else "",
                        current=True,
                        stale=False,
                        limitations=shared_limitations,
                    )
                )
        return projections[:_MAX_RISK_PROJECTIONS]

    def inspect_repair_risks(self, project_id: str, repair_plan_id: str) -> dict[str, Any]:
        projections = self.build_risk_projections(project_id, repair_plan_id)
        return {
            "schema_version": "boba_repair_plan_review_risk_v1",
            "project_id": project_id,
            "repair_plan_id": repair_plan_id,
            "risk_projections": [item.model_dump(mode="json") for item in projections],
            "risk_dimensions": list(_RISK_DIMENSIONS),
            "source_risk_order": list(_RISK_ORDER),
            "blocked_dimension_count": sum(
                1 for item in projections if item.blocked_by_owner
            ),
            "panel_risk_score_created": False,
            "panel_repair_success_score_created": False,
            "limitations": [
                "Risk levels are the owner's own values.",
                "A reversible plan is not a risk-free plan.",
            ],
        }

    # ------------------------------------------------------------------
    # Approval requirements
    # ------------------------------------------------------------------
    def build_approval_requirements(
        self, project_id: str, repair_plan_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRepairApprovalRequirementV1]:
        """Project the approvals the owner says this plan needs, and only those."""
        strategy, case, _index = self._plan_record(project_id, repair_plan_id)
        gate = self._approval_gates(project_id).get(
            _safe_text(case.get("approval_gate_id"), 180), {}
        )
        rollback = self._rollback_plans(project_id).get(
            _safe_text(case.get("rollback_plan_id"), 180), {}
        )
        validation = self._validation_plans(project_id).get(
            _safe_text(case.get("validation_plan_id"), 180), {}
        )
        gate_id = _safe_text(gate.get("approval_gate_id"), 180)
        gate_digest = _digest(_safe_payload(gate)) if gate else ""
        rows: list[BobaRepairApprovalRequirementV1] = []

        def add(
            requirement_type: RepairApprovalRequirementType,
            *,
            required: bool,
            source_module_id: str,
            source_record_id: str,
            source_record_digest: str,
            explanation: str,
            satisfied_by_owner: bool = False,
            canonical_record_id: str | None = None,
            canonical_record_digest: str | None = None,
            limitations: list[str] | None = None,
        ) -> None:
            if not required:
                return
            rows.append(
                BobaRepairApprovalRequirementV1(
                    approval_requirement_id=_stable_id(
                        "repair_approval_requirement",
                        project_id,
                        repair_plan_id,
                        requirement_type,
                    ),
                    repair_plan_snapshot_id=snapshot_id,
                    repair_plan_id=repair_plan_id,
                    source_module_id=source_module_id,
                    source_record_id=source_record_id,
                    source_record_digest=source_record_digest,
                    requirement_type=requirement_type,
                    required=True,
                    satisfied_by_owner=satisfied_by_owner,
                    canonical_record_id=canonical_record_id,
                    canonical_record_digest=canonical_record_digest,
                    current=True,
                    stale=False,
                    blocking=not satisfied_by_owner,
                    bounded_explanation=_safe_text(explanation, 900),
                    limitations=(
                        limitations
                        or [
                            "Repair Planner's approval-status vocabulary is "
                            "planning_only, awaiting_human_review, blocked, "
                            "not_required_for_no_action and unknown. It has no "
                            "approved value, so this panel can never show an "
                            "approved repair plan.",
                            "The panel records no approval of its own.",
                        ]
                    )[:16],
                )
            )

        if gate:
            add(
                "human_review",
                required=bool(gate.get("final_human_approval_required", True)),
                source_module_id="repair_planner",
                source_record_id=gate_id,
                source_record_digest=gate_digest,
                explanation=(
                    "Repair Planner pins final human approval for this repair case. "
                    f"Its recorded approval status is "
                    f"'{_safe_text(gate.get('approval_status') or 'unknown', 80)}'."
                ),
            )
            add(
                "safety_gate",
                required=bool(gate.get("safety_gate_required", True)),
                source_module_id="repair_planner",
                source_record_id=gate_id,
                source_record_digest=gate_digest,
                explanation=(
                    "Repair Planner requires a Safety Gate approval before this "
                    "plan may act."
                ),
                limitations=[
                    "No canonical record binds a Safety Gate decision to a repair "
                    "strategy identity, so satisfaction cannot be shown here.",
                    "The panel creates no Safety decision.",
                ],
            )
            add(
                "rights_gate",
                required=bool(gate.get("rights_gate_required")),
                source_module_id="repair_planner",
                source_record_id=gate_id,
                source_record_digest=gate_digest,
                explanation="Repair Planner requires a Rights and Permission review.",
                limitations=[
                    "No canonical record binds a Rights decision to a repair "
                    "strategy identity, so satisfaction cannot be shown here.",
                    "The panel creates no Rights decision.",
                ],
            )
            add(
                "output_quality_review",
                required=bool(gate.get("output_quality_review_required", True)),
                source_module_id="repair_planner",
                source_record_id=gate_id,
                source_record_digest=gate_digest,
                explanation=(
                    "Repair Planner requires an Output Quality review of the "
                    "repaired result."
                ),
                limitations=[
                    "Output Quality Reviewer records no repair-strategy identity, "
                    "so satisfaction cannot be shown here.",
                ],
            )
            add(
                "rollback_plan",
                required=bool(gate.get("rollback_plan_required", True)),
                source_module_id="repair_planner",
                source_record_id=gate_id,
                source_record_digest=gate_digest,
                explanation=(
                    "Repair Planner requires a rollback plan for this repair case."
                ),
                satisfied_by_owner=bool(rollback),
                canonical_record_id=_safe_text(rollback.get("rollback_plan_id"), 180)
                or None,
                canonical_record_digest=_digest(_safe_payload(rollback))
                if rollback
                else None,
                limitations=[
                    "A recorded rollback plan is not a guarantee that a rollback "
                    "will succeed.",
                    "Rollback step text is never projected because it may hold "
                    "command text.",
                ],
            )
            add(
                "validation_plan",
                required=bool(gate.get("validation_plan_required", True)),
                source_module_id="repair_planner",
                source_record_id=gate_id,
                source_record_digest=gate_digest,
                explanation=(
                    "Repair Planner requires a validation plan for this repair case."
                ),
                satisfied_by_owner=bool(validation),
                canonical_record_id=_safe_text(validation.get("validation_plan_id"), 180)
                or None,
                canonical_record_digest=_digest(_safe_payload(validation))
                if validation
                else None,
                limitations=[
                    "A recorded validation plan is not a completed validation run.",
                ],
            )
            add(
                "code_change",
                required=bool(gate.get("code_review_required")),
                source_module_id="repair_planner",
                source_record_id=gate_id,
                source_record_digest=gate_digest,
                explanation=(
                    "Repair Planner requires a code review because this plan "
                    "proposes a code change."
                ),
            )

        strategy_id = _safe_text(strategy.get("repair_strategy_id"), 180)
        strategy_digest = _digest(_safe_payload(strategy))
        strategy_type = _safe_text(strategy.get("strategy_type") or "unknown", 120)
        add(
            "tool_execution",
            required=bool(strategy.get("requires_command_execution")),
            source_module_id="repair_planner",
            source_record_id=strategy_id,
            source_record_digest=strategy_digest,
            explanation=(
                "The strategy declares that it needs command execution, which is "
                "owned by Tool Recovery's approved-execution path."
            ),
        )
        add(
            "process_restart",
            required=bool(strategy.get("requires_service_restart")),
            source_module_id="repair_planner",
            source_record_id=strategy_id,
            source_record_digest=strategy_digest,
            explanation="The strategy declares that it needs a service restart.",
        )
        add(
            "destructive_action",
            required=_safe_text(strategy.get("destructiveness"), 80)
            in {"medium", "high", "blocked"},
            source_module_id="repair_planner",
            source_record_id=strategy_id,
            source_record_digest=strategy_digest,
            explanation=(
                "Repair Planner rated this strategy's destructiveness as "
                f"'{_safe_text(strategy.get('destructiveness') or 'unknown', 80)}'."
            ),
        )
        add(
            "checkpoint_restore",
            required=strategy_type in {"restore_checkpoint", "resume_from_checkpoint"},
            source_module_id="repair_planner",
            source_record_id=strategy_id,
            source_record_digest=strategy_digest,
            explanation=(
                "The strategy proposes restoring or resuming from a checkpoint, "
                "which changes generated state and workflow position."
            ),
        )
        add(
            "workflow",
            required=strategy_type
            in {"switch_safe_workflow_path", "resume_from_checkpoint"},
            source_module_id="repair_planner",
            source_record_id=strategy_id,
            source_record_digest=strategy_digest,
            explanation="The strategy proposes changing the workflow path.",
        )
        add(
            "artifact_change",
            required=strategy_type in {"regenerate_artifact", "repair_generated_state"},
            source_module_id="repair_planner",
            source_record_id=strategy_id,
            source_record_digest=strategy_digest,
            explanation="The strategy proposes replacing or repairing an artifact.",
        )
        return rows[:_MAX_APPROVAL_REQUIREMENTS]

    def inspect_approval_requirements(
        self, project_id: str, repair_plan_id: str
    ) -> dict[str, Any]:
        rows = self.build_approval_requirements(project_id, repair_plan_id)
        return {
            "schema_version": "boba_repair_plan_review_approvals_v1",
            "project_id": project_id,
            "repair_plan_id": repair_plan_id,
            "approval_requirements": [item.model_dump(mode="json") for item in rows],
            "required_count": len(rows),
            "satisfied_count": sum(1 for item in rows if item.satisfied_by_owner),
            "missing_count": sum(1 for item in rows if not item.satisfied_by_owner),
            "blocking_count": sum(1 for item in rows if item.blocking),
            "approval_created_by_panel": False,
            "limitations": [
                "Repair Planner's approval-status vocabulary contains no approved "
                "value, so an approved repair plan can never be displayed.",
                "The panel grants no approval and records no Safety, Rights or "
                "Final Decision outcome.",
            ],
        }

    # ------------------------------------------------------------------
    # Verification requirements
    # ------------------------------------------------------------------
    def _validator_results(self, project_id: str) -> dict[str, dict[str, Any]]:
        """Index Validator Runner results by the validator identity they name."""
        payload = self._source_payload("validator_runner", project_id)
        rows = payload.get("validation_results")
        indexed: dict[str, dict[str, Any]] = {}
        if not isinstance(rows, list):
            return indexed
        for entry in rows[:1_024]:
            if not isinstance(entry, Mapping):
                continue
            mapped = _as_mapping(entry)
            validator_id = _safe_text(mapped.get("validator_id"), 180)
            if validator_id:
                indexed.setdefault(validator_id, mapped)
        return indexed

    def build_verification_requirements(
        self, project_id: str, repair_plan_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRepairVerificationRequirementV1]:
        """Project the verification the owner requires before acceptance."""
        _strategy, case, _index = self._plan_record(project_id, repair_plan_id)
        validation = self._validation_plans(project_id).get(
            _safe_text(case.get("validation_plan_id"), 180), {}
        )
        checkpoint = self._checkpoint_plans(project_id).get(
            _safe_text(case.get("checkpoint_plan_id"), 180), {}
        )
        rollback = self._rollback_plans(project_id).get(
            _safe_text(case.get("rollback_plan_id"), 180), {}
        )
        results = self._validator_results(project_id)
        rows: list[BobaRepairVerificationRequirementV1] = []

        def add(
            verification_type: RepairVerificationType,
            key: str,
            *,
            source_module_id: str,
            source_record_id: str,
            source_record_digest: str,
            explanation: str,
            validator_ids: list[str] | None = None,
            artifact_reference_ids: list[str] | None = None,
            required_check_ids: list[str] | None = None,
            satisfied: bool = False,
            blocks_acceptance_on_failure: bool = True,
            limitations: list[str] | None = None,
        ) -> None:
            rows.append(
                BobaRepairVerificationRequirementV1(
                    verification_requirement_id=_stable_id(
                        "repair_verification_requirement",
                        project_id,
                        repair_plan_id,
                        verification_type,
                        key,
                    ),
                    repair_plan_snapshot_id=snapshot_id,
                    repair_plan_id=repair_plan_id,
                    verification_type=verification_type,
                    required=True,
                    source_module_id=source_module_id,
                    source_record_id=source_record_id,
                    source_record_digest=source_record_digest,
                    validator_ids=(validator_ids or [])[:32],
                    artifact_reference_ids=(artifact_reference_ids or [])[:32],
                    required_check_ids=(required_check_ids or [])[:64],
                    satisfied=satisfied,
                    # The panel never verifies anything itself, so independent
                    # verification is always absent.
                    independently_verified=False,
                    blocks_acceptance_on_failure=blocks_acceptance_on_failure,
                    current=True,
                    stale=False,
                    blocking=not satisfied,
                    bounded_explanation=_safe_text(explanation, 900),
                    limitations=(
                        limitations
                        or [
                            "Owner-reported success is not independent "
                            "verification.",
                            "The panel runs no validator and inspects no artifact.",
                        ]
                    )[:16],
                )
            )

        if validation:
            plan_id = _safe_text(validation.get("validation_plan_id"), 180)
            plan_digest = _digest(_safe_payload(validation))
            for phase, key in (
                ("pre_repair_checks", "pre_repair_check"),
                ("post_repair_checks", "post_repair_check"),
            ):
                checks = validation.get(phase)
                if not isinstance(checks, list) or not checks:
                    continue
                mapped_checks = [
                    _as_mapping(item) for item in checks[:64] if isinstance(item, Mapping)
                ]
                add(
                    "pre_repair_check" if key == "pre_repair_check" else "post_repair_check",
                    phase,
                    source_module_id="repair_planner",
                    source_record_id=plan_id,
                    source_record_digest=plan_digest,
                    explanation=(
                        f"Repair Planner records {len(mapped_checks)} {key} "
                        "entries that must be satisfied."
                    ),
                    validator_ids=[
                        _safe_text(item.get("validator_name"), 180)
                        for item in mapped_checks
                        if _safe_text(item.get("validator_name"), 180)
                    ],
                    required_check_ids=[
                        _safe_text(item.get("validation_check_id"), 180)
                        for item in mapped_checks
                        if _safe_text(item.get("validation_check_id"), 180)
                    ],
                    blocks_acceptance_on_failure=any(
                        bool(item.get("blocks_acceptance_on_failure", True))
                        for item in mapped_checks
                    ),
                    limitations=[
                        "Check text is projected from the owner's record; command "
                        "text inside a check is withheld.",
                        "A recorded check is not an executed check.",
                    ],
                )
            required_validators = [
                _safe_text(item, 180)
                for item in validation.get("required_validators", [])
                if isinstance(item, str) and _safe_text(item, 180)
            ][:32]
            if required_validators:
                matched = [results.get(item, {}) for item in required_validators]
                satisfied = bool(matched) and all(
                    _safe_text(item.get("status"), 80) in {"passed", "satisfied"}
                    for item in matched
                    if item
                ) and all(bool(item) for item in matched)
                add(
                    "validator_run",
                    "required_validators",
                    source_module_id="validator_runner",
                    source_record_id=plan_id,
                    source_record_digest=plan_digest,
                    explanation=(
                        "Repair Planner requires these named validators to run "
                        "through Validator Runner."
                    ),
                    validator_ids=required_validators,
                    satisfied=satisfied,
                    limitations=[
                        "Validator Runner owns validator execution; this panel "
                        "only reports what it already recorded.",
                        "Owner-reported success is not independent verification.",
                    ],
                )
            quality_checks = [
                _safe_text(item, 700)
                for item in validation.get("output_quality_checks", [])
                if isinstance(item, str)
            ][:32]
            if quality_checks:
                add(
                    "output_quality_review",
                    "output_quality_checks",
                    source_module_id="output_quality_reviewer",
                    source_record_id=plan_id,
                    source_record_digest=plan_digest,
                    explanation=(
                        "Repair Planner requires output-quality checks on the "
                        "repaired result."
                    ),
                    limitations=[
                        "Output Quality Reviewer records no repair-strategy "
                        "identity, so no acceptance decision can be matched here.",
                    ],
                )
        if checkpoint and bool(checkpoint.get("checkpoint_validation_required")):
            add(
                "checkpoint_validation",
                "checkpoint",
                source_module_id="repair_planner",
                source_record_id=_safe_text(checkpoint.get("checkpoint_plan_id"), 180),
                source_record_digest=_digest(_safe_payload(checkpoint)),
                explanation=(
                    "Repair Planner requires the checkpoint to be validated before "
                    "the repair proceeds."
                ),
                artifact_reference_ids=[
                    _safe_text(item, 180)
                    for item in checkpoint.get("artifacts_to_preserve", [])
                    if isinstance(item, str) and _safe_text(item, 180)
                ],
                limitations=[
                    "Source media must remain untouched; the checkpoint plan pins "
                    "this and the panel never changes it.",
                ],
            )
        if checkpoint:
            artifacts = [
                _safe_text(item, 180)
                for item in checkpoint.get("artifacts_to_preserve", [])
                if isinstance(item, str) and _safe_text(item, 180)
            ][:32]
            if artifacts:
                add(
                    "artifact_inspection",
                    "preserved_artifacts",
                    source_module_id="artifact_inspector",
                    source_record_id=_safe_text(checkpoint.get("checkpoint_plan_id"), 180),
                    source_record_digest=_digest(_safe_payload(checkpoint)),
                    explanation=(
                        "The checkpoint plan names artifacts that must be preserved "
                        "and therefore inspected."
                    ),
                    artifact_reference_ids=artifacts,
                    limitations=[
                        "Artifact Inspector owns artifact inspection; the panel "
                        "opens, reads and probes no file.",
                    ],
                )
        rollback_validation_text = joined_owner_text(rollback.get("rollback_validation"))
        if rollback and rollback_validation_text:
            add(
                "rollback_validation",
                "rollback",
                source_module_id="repair_planner",
                source_record_id=_safe_text(rollback.get("rollback_plan_id"), 180),
                source_record_digest=_digest(_safe_payload(rollback)),
                explanation=rollback_validation_text,
                limitations=[
                    "A rollback plan being available does not mean a rollback is "
                    "guaranteed to succeed.",
                    "Rollback step text is never projected because it may hold "
                    "command text.",
                ],
            )
        return rows[:_MAX_VERIFICATION_REQUIREMENTS]

    def inspect_verification_requirements(
        self, project_id: str, repair_plan_id: str
    ) -> dict[str, Any]:
        rows = self.build_verification_requirements(project_id, repair_plan_id)
        return {
            "schema_version": "boba_repair_plan_review_verification_v1",
            "project_id": project_id,
            "repair_plan_id": repair_plan_id,
            "verification_requirements": [item.model_dump(mode="json") for item in rows],
            "required_count": len(rows),
            "satisfied_count": sum(1 for item in rows if item.satisfied),
            "missing_count": sum(1 for item in rows if not item.satisfied),
            "independently_verified_count": 0,
            "validator_executed_by_panel": False,
            "limitations": [
                "Owner-reported success is not independent verification.",
                "The panel runs no validator, opens no artifact and probes no media.",
            ],
        }

    # ------------------------------------------------------------------
    # Evidence cards
    # ------------------------------------------------------------------
    @staticmethod
    def _card(
        *,
        project_id: str,
        repair_plan_id: str,
        snapshot_id: str | None,
        evidence_type: str,
        source_module_id: str,
        record: Mapping[str, Any],
        record_id: str,
        title: str,
        original_status: str,
        summary: object = "",
        excerpt: object = "",
        original_decision: str | None = None,
        advisory_only: bool = False,
        blocking: bool = False,
        missing: bool = False,
        limitations: list[str] | None = None,
    ) -> BobaRepairEvidenceCardV1:
        descriptor = build_fixed_repair_source_registry().get(source_module_id, {})
        projected = bounded_excerpt(excerpt, maximum=MAX_EVIDENCE_EXCERPT_CHARS)
        withheld = source_holds_command(excerpt)
        return BobaRepairEvidenceCardV1(
            repair_evidence_card_id=_stable_id(
                "repair_evidence_card",
                project_id,
                repair_plan_id,
                source_module_id,
                evidence_type,
                record_id,
            ),
            repair_plan_snapshot_id=snapshot_id,
            evidence_type=evidence_type,
            source_module_id=source_module_id,
            authority_domain=str(descriptor.get("authority_domain") or "unknown"),
            source_record_id=record_id or "unavailable",
            source_record_digest=_digest(_safe_payload(record)) if record else "",
            title=_safe_text(title, 240) or "Canonical Record",
            original_status=_safe_text(original_status or "unknown", 160),
            original_decision=_safe_text(original_decision, 200) if original_decision else None,
            bounded_summary=bounded_easy_explanation(summary)[:900],
            bounded_excerpt=COMMAND_WITHHELD_NOTICE if withheld else projected["text"],
            excerpt_truncated=False if withheld else bool(projected["truncated"]),
            command_withheld=withheld,
            sensitive_values_redacted=bool(projected["sensitive_values_redacted"]),
            private_paths_redacted=withheld
            or bool(projected["private_paths_redacted"]),
            current=not missing,
            stale=False,
            historical=False,
            missing=missing,
            authoritative=not advisory_only,
            advisory_only=advisory_only,
            blocking=blocking,
            limitations=(limitations or [SOURCE_RETAINED_NOTICE])[:16],
        )

    def build_repair_evidence_cards(
        self, project_id: str, repair_plan_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRepairEvidenceCardV1]:
        """Project the canonical records that support or bound this plan."""
        strategy, case, _index = self._plan_record(project_id, repair_plan_id)
        repair_case_id = _safe_text(strategy.get("repair_case_id"), 180)
        analysis_case_id = _safe_text(case.get("source_analysis_case_id"), 180)
        analysis = self._analysis_cases(project_id).get(analysis_case_id, {})
        diagnostic_case_id = _safe_text(analysis.get("source_diagnostic_case_id"), 180)
        diagnostic = self._diagnostic_cases(project_id).get(diagnostic_case_id, {})
        candidates = self._root_cause_candidates(project_id)
        cards: list[BobaRepairEvidenceCardV1] = []

        def card(**kwargs: Any) -> None:
            cards.append(
                self._card(
                    project_id=project_id,
                    repair_plan_id=repair_plan_id,
                    snapshot_id=snapshot_id,
                    **kwargs,
                )
            )

        card(
            evidence_type="repair_strategy",
            source_module_id="repair_planner",
            record=strategy,
            record_id=repair_plan_id,
            title=_safe_text(strategy.get("title"), 240) or "Proposed Repair Strategy",
            original_status=_safe_text(strategy.get("strategy_type") or "unknown", 160),
            summary=strategy.get("easy_explanation") or strategy.get("description"),
            excerpt=strategy.get("rationale"),
            limitations=[
                "Repair Planner proposed this strategy. It is not a statement that "
                "the repair is correct.",
                SOURCE_RETAINED_NOTICE,
            ],
        )
        if case:
            card(
                evidence_type="repair_planning_case",
                source_module_id="repair_planner",
                record=case,
                record_id=repair_case_id,
                title=_safe_text(case.get("title"), 240) or "Repair Planning Case",
                original_status=_safe_text(case.get("planning_status") or "unknown", 160),
                summary=case.get("expected_workflow_impact"),
                excerpt=case.get("blocked_reason"),
                blocking=_safe_text(case.get("planning_status"), 120)
                in {"blocked", "intentional_safety_block", "conflicting_causes"},
            )
        for list_key, id_field, evidence_type, title, status_field in (
            ("risk_assessments", "risk_assessment_id", "repair_risk_assessment",
             "Repair Risk Assessment", "overall_risk"),
            ("approval_gates", "approval_gate_id", "repair_approval_gate",
             "Repair Approval Gate", "approval_status"),
            ("rollback_plans", "rollback_plan_id", "repair_rollback_plan",
             "Repair Rollback Plan", "rollback_scope"),
            ("checkpoint_plans", "checkpoint_plan_id", "repair_checkpoint_plan",
             "Repair Checkpoint Plan", "checkpoint_type"),
            ("validation_plans", "validation_plan_id", "repair_validation_plan",
             "Repair Validation Plan", "unknown"),
            ("quality_preservation_plans", "quality_preservation_plan_id",
             "quality_preservation_plan", "Quality Preservation Plan", "unknown"),
        ):
            record_id = _safe_text(case.get(id_field), 180)
            record = self._indexed_rows(
                "repair_planner", project_id, list_key, id_field
            ).get(record_id, {})
            if not record:
                continue
            card(
                evidence_type=evidence_type,
                source_module_id="repair_planner",
                record=record,
                record_id=record_id,
                title=title,
                original_status=_safe_text(record.get(status_field) or "recorded", 160),
                # Rollback step text may hold command text and is never projected.
                excerpt="",
                limitations=[
                    "Rollback and step text is never projected because it may hold "
                    "command text.",
                    SOURCE_RETAINED_NOTICE,
                ]
                if evidence_type == "repair_rollback_plan"
                else None,
            )
        for handoff in self._execution_handoffs(project_id).get(repair_plan_id, [])[:8]:
            card(
                evidence_type="repair_execution_handoff",
                source_module_id="repair_planner",
                record=handoff,
                record_id=_safe_text(handoff.get("handoff_id"), 180),
                title=(
                    "Execution handoff to "
                    f"{_safe_text(handoff.get('target_module') or 'unknown', 120)}"
                ),
                original_status=_safe_text(handoff.get("priority") or "unknown", 160),
                summary=handoff.get("reason"),
                limitations=[
                    "Every execution handoff Repair Planner records pins "
                    "apply_automatically=False and human_approval_required=True.",
                    "The panel cannot create, send or act on a handoff.",
                ],
            )
        for rejected in self._rejected_strategies(project_id).get(repair_case_id, [])[:8]:
            card(
                evidence_type="repair_rejected_strategy",
                source_module_id="repair_planner",
                record=rejected,
                record_id=_safe_text(rejected.get("rejected_strategy_id"), 180),
                title=_safe_text(rejected.get("title"), 240) or "Rejected Strategy",
                original_status=_safe_text(
                    rejected.get("strategy_type") or "rejected", 160
                ),
                summary=rejected.get("rejection_reason"),
                excerpt=rejected.get("safety_reason"),
                limitations=[
                    "Repair Planner rejected this alternative itself. The panel "
                    "recorded no rejection.",
                ],
            )
        if analysis:
            card(
                evidence_type="root_cause_analysis_case",
                source_module_id="root_cause_analyzer",
                record=analysis,
                record_id=analysis_case_id,
                title=_safe_text(analysis.get("title"), 240) or "Root Cause Analysis",
                original_status=_safe_text(
                    analysis.get("analysis_status") or "unknown", 160
                ),
                summary=analysis.get("most_likely_root_cause"),
                limitations=[
                    "A most-likely root cause is Root Cause Analyzer's own "
                    "assessment, not a confirmed fact.",
                ],
            )
        else:
            card(
                evidence_type="root_cause_analysis_case",
                source_module_id="root_cause_analyzer",
                record={},
                record_id=analysis_case_id or "unavailable",
                title="Root Cause Analysis (unavailable)",
                original_status="unavailable",
                missing=True,
                blocking=True,
                limitations=[
                    "The plan cannot be traced to a root-cause analysis case, so "
                    "its evidence basis cannot be shown.",
                ],
            )
        selected_candidate_id = _safe_text(
            case.get("selected_root_cause_candidate_id"), 180
        )
        for candidate_id in [
            selected_candidate_id,
            *[
                _safe_text(item, 180)
                for item in case.get("root_cause_candidate_ids", [])
                if isinstance(item, str)
            ],
        ][:MAX_EXPANDED_SOURCE_CARDS]:
            candidate = candidates.get(candidate_id, {})
            if not candidate_id:
                continue
            if not candidate:
                card(
                    evidence_type="root_cause_candidate",
                    source_module_id="root_cause_analyzer",
                    record={},
                    record_id=candidate_id,
                    title="Root Cause Candidate (unavailable)",
                    original_status="unavailable",
                    missing=True,
                    blocking=True,
                    limitations=[
                        "The plan names a root-cause candidate that is no longer "
                        "available from its owner.",
                    ],
                )
                continue
            card(
                evidence_type="root_cause_candidate",
                source_module_id="root_cause_analyzer",
                record=candidate,
                record_id=candidate_id,
                title=_safe_text(candidate.get("title"), 240) or "Root Cause Candidate",
                original_status=_safe_text(candidate.get("category") or "unknown", 160),
                original_decision="selected"
                if candidate_id == selected_candidate_id
                else "considered",
                summary=candidate.get("candidate_summary"),
                limitations=[
                    "A root-cause candidate is a hypothesis unless its owner "
                    "records verification.",
                    "Repair Planner selected this candidate; the panel did not.",
                ],
            )
        if diagnostic:
            card(
                evidence_type="diagnostic_case",
                source_module_id="error_doctor",
                record=diagnostic,
                record_id=diagnostic_case_id,
                title=_safe_text(diagnostic.get("title"), 240) or "Diagnostic Case",
                original_status=_safe_text(
                    diagnostic.get("diagnosis_status") or "unknown", 160
                ),
                summary=diagnostic.get("easy_explanation"),
                limitations=[
                    "The diagnosis is Error Doctor's own assessment.",
                    "This is the incident the linked-incident acknowledgement acts "
                    "on.",
                ],
            )
        for recovery in self._recovery_cases_for(project_id, repair_case_id)[:8]:
            card(
                evidence_type="tool_recovery_case",
                source_module_id="tool_recovery",
                record=recovery,
                record_id=_safe_text(recovery.get("recovery_case_id"), 180),
                title=_safe_text(recovery.get("title"), 240) or "Tool Recovery Case",
                original_status=_safe_text(
                    recovery.get("blocked_reason") or "recorded", 160
                ),
                summary=recovery.get("failure_class"),
                limitations=[
                    "Tool Recovery owns recovery execution. A recovery attempt "
                    "reported as successful is not independently verified, and "
                    "recovered is not resolved.",
                ],
            )
        for code_case in self._code_repair_cases_for(project_id, repair_case_id)[:8]:
            card(
                evidence_type="code_repair_case",
                source_module_id="code_surgeon",
                record=code_case,
                record_id=_safe_text(code_case.get("code_repair_case_id"), 180),
                title=_safe_text(code_case.get("title"), 240) or "Code Repair Case",
                original_status=_safe_text(
                    code_case.get("blocked_reason") or "recorded", 160
                ),
                summary=code_case.get("justification"),
                limitations=[
                    "Code Surgeon owns code repair. No patch text, diff or source "
                    "code is projected by this panel.",
                ],
            )
        results = self._validator_results(project_id)
        validation = self._validation_plans(project_id).get(
            _safe_text(case.get("validation_plan_id"), 180), {}
        )
        for validator_id in [
            _safe_text(item, 180)
            for item in validation.get("required_validators", [])
            if isinstance(item, str)
        ][:8]:
            result = results.get(validator_id, {})
            card(
                evidence_type="validation_result",
                source_module_id="validator_runner",
                record=result,
                record_id=_safe_text(result.get("result_id"), 180) or validator_id,
                title=f"Validator result: {validator_id}",
                original_status=_safe_text(result.get("status") or "unavailable", 160),
                missing=not result,
                blocking=not result,
                limitations=[
                    "Validator Runner owns validator execution and its own result "
                    "status.",
                ],
            )
        run = self._workflow_run(project_id)
        if run:
            card(
                evidence_type="workflow_run",
                source_module_id="workflow_controller",
                record=run,
                record_id=_safe_text(run.get("workflow_run_id"), 180),
                title="Workflow Run",
                original_status=_safe_text(run.get("status") or "unknown", 160),
                limitations=[
                    "Workflow Controller owns workflow position. The panel "
                    "transitions nothing.",
                ],
            )
        for source_id, evidence_type, title in (
            ("safety_gate", "safety_decision", "Safety Gate decision"),
            ("final_decision_bus", "final_decision", "Final Decision Bus decision"),
            ("output_quality_reviewer", "output_quality_review", "Output Quality review"),
        ):
            card(
                evidence_type=evidence_type,
                source_module_id=source_id,
                record={},
                record_id="unavailable",
                title=f"{title} (not bound to a repair plan)",
                original_status="unavailable",
                missing=True,
                limitations=[
                    f"{title} records carry no repair-strategy identity, so none "
                    "can be matched to this plan.",
                    "The panel creates no such decision.",
                ],
            )
        autopilot = self._source_payload("autopilot_controller", project_id)
        if autopilot:
            card(
                evidence_type="autopilot_context",
                source_module_id="autopilot_controller",
                record=autopilot,
                record_id=_safe_text(autopilot.get("schema_version"), 180) or "autopilot",
                title="Autopilot context",
                original_status="recorded",
                advisory_only=True,
                limitations=[
                    "Autopilot context is advisory only and never authorises a "
                    "repair.",
                ],
            )
        return cards[:MAX_EVIDENCE_CARDS]

    def inspect_repair_evidence(
        self, project_id: str, repair_plan_id: str
    ) -> dict[str, Any]:
        cards = self.build_repair_evidence_cards(project_id, repair_plan_id)
        return {
            "schema_version": "boba_repair_plan_review_evidence_v1",
            "project_id": project_id,
            "repair_plan_id": repair_plan_id,
            "evidence_cards": [item.model_dump(mode="json") for item in cards],
            "evidence_count": len(cards),
            "missing_evidence_count": sum(1 for item in cards if item.missing),
            "blocking_evidence_count": sum(1 for item in cards if item.blocking),
            "advisory_evidence_count": sum(1 for item in cards if item.advisory_only),
            "command_withheld_count": sum(1 for item in cards if item.command_withheld),
            "raw_command_exposed": False,
            "private_path_exposed": False,
            "limitations": [
                "Evidence is projected from canonical owner records and is never "
                "rewritten.",
                SOURCE_RETAINED_NOTICE,
            ],
        }

    # ------------------------------------------------------------------
    # Linked recovery history
    # ------------------------------------------------------------------
    def build_recovery_links(
        self, project_id: str, repair_plan_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRepairRecoveryLinkV1]:
        """Project Tool Recovery attempts reached through this plan's repair case."""
        strategy, _case, _index = self._plan_record(project_id, repair_plan_id)
        repair_case_id = _safe_text(strategy.get("repair_case_id"), 180)
        attempts_by_case = self._recovery_attempts(project_id)
        rollbacks = self._recovery_rollbacks(project_id)
        validations = self._recovery_validations(project_id)
        links: list[BobaRepairRecoveryLinkV1] = []
        for recovery_case in self._recovery_cases_for(project_id, repair_case_id):
            recovery_case_id = _safe_text(recovery_case.get("recovery_case_id"), 180)
            named_strategies = [
                _safe_text(item, 180)
                for item in recovery_case.get("source_repair_strategy_ids", [])
                if isinstance(item, str)
            ]
            linked_by_strategy = repair_plan_id in named_strategies
            for attempt in attempts_by_case.get(recovery_case_id, [])[:_MAX_RECOVERY_LINKS]:
                attempt_id = _safe_text(attempt.get("recovery_attempt_id"), 180)
                if not attempt_id:
                    continue
                status = _safe_text(attempt.get("status") or "unknown", 120)
                rollback_rows = rollbacks.get(attempt_id, [])
                validation_rows = validations.get(attempt_id, [])
                attempt_number = attempt.get("attempt_number")
                warnings: list[str] = []
                if not linked_by_strategy:
                    warnings.append(
                        "This attempt is linked through the repair case, not "
                        "through this exact strategy identity."
                    )
                if status in {"failed", "timed_out", "blocked", "rejected", "rolled_back"}:
                    warnings.append(
                        f"Tool Recovery reported this attempt as '{status}'."
                    )
                links.append(
                    BobaRepairRecoveryLinkV1(
                        repair_recovery_link_id=_stable_id(
                            "repair_recovery_link", project_id, repair_plan_id, attempt_id
                        ),
                        repair_plan_snapshot_id=snapshot_id,
                        repair_plan_id=repair_plan_id,
                        source_record_id=attempt_id,
                        source_record_digest=_digest(_safe_payload(attempt)),
                        recovery_case_id=recovery_case_id,
                        recovery_attempt_id=attempt_id,
                        attempt_number=attempt_number
                        if isinstance(attempt_number, int)
                        else None,
                        original_status=status,
                        linked_by_strategy_id=linked_by_strategy,
                        attempted=status != "not_started",
                        completed=status
                        in {
                            "completed",
                            "succeeded_pending_validation",
                            "failed",
                            "timed_out",
                            "rolled_back",
                            "rejected",
                        },
                        succeeded_by_owner=status
                        in {"completed", "succeeded_pending_validation"},
                        # The panel never verifies a recovery outcome itself.
                        independently_verified=False,
                        verification_source_ids=[
                            _safe_text(item.get("output_validation_id"), 180)
                            for item in validation_rows[:16]
                            if _safe_text(item.get("output_validation_id"), 180)
                        ],
                        rollback_attempted=bool(rollback_rows),
                        rollback_status=_safe_text(
                            rollback_rows[0].get("status") if rollback_rows else "",
                            120,
                        )
                        or "unavailable",
                        resulting_failure_class=_safe_text(
                            attempt.get("failure_class"), 120
                        )
                        or None,
                        started_at=_safe_text(attempt.get("execution_started_at"), 80)
                        or None,
                        completed_at=_safe_text(attempt.get("execution_completed_at"), 80)
                        or None,
                        current=True,
                        stale=False,
                        historical=False,
                        bounded_summary=bounded_easy_explanation(
                            attempt.get("failure_summary")
                        )[:900],
                        warnings=warnings[:16],
                        limitations=[
                            "Tool Recovery owns recovery execution and its own "
                            "attempt status.",
                            "Owner-reported success is not independent "
                            "verification, and recovered is not resolved.",
                            "Recorded commands are never projected; only their "
                            "presence is reported.",
                            NOT_EXECUTABLE_NOTICE,
                        ],
                    )
                )
        return links[:_MAX_RECOVERY_LINKS]

    def inspect_linked_recovery_history(
        self, project_id: str, repair_plan_id: str
    ) -> dict[str, Any]:
        links = self.build_recovery_links(project_id, repair_plan_id)
        return {
            "schema_version": "boba_repair_plan_review_recovery_v1",
            "project_id": project_id,
            "repair_plan_id": repair_plan_id,
            "recovery_links": [item.model_dump(mode="json") for item in links],
            "attempt_count": len(links),
            "failed_attempt_count": sum(
                1
                for item in links
                if item.original_status
                in {"failed", "timed_out", "blocked", "rejected", "rolled_back"}
            ),
            "owner_reported_success_count": sum(
                1 for item in links if item.succeeded_by_owner
            ),
            "independently_verified_count": 0,
            "recovery_started_by_panel": False,
            "limitations": [
                "Owner-reported success is not independent verification.",
                "Recovered is not resolved.",
                NOT_EXECUTABLE_NOTICE,
            ],
        }

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------
    def detect_repair_plan_conflicts(
        self, project_id: str, repair_plan_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRepairPlanConflictV1]:
        """Report disagreements between records naming the same exact identity.

        A conflict is never resolved by preferring a higher confidence, a lower
        risk or a more recent timestamp. It is reported for a human.
        """
        strategy, case, _index = self._plan_record(project_id, repair_plan_id)
        repair_case_id = _safe_text(strategy.get("repair_case_id"), 180)
        analysis_case_id = _safe_text(case.get("source_analysis_case_id"), 180)
        run = self._workflow_run(project_id)
        run_id = _safe_text(run.get("workflow_run_id"), 180)
        conflicts: list[BobaRepairPlanConflictV1] = []

        def add(
            conflict_type: RepairPlanConflictType,
            key: str,
            *,
            severity: str,
            value_a: str,
            value_b: str,
            summary: str,
            source_record_ids: list[str],
            source_record_digests: list[str] | None = None,
            blocks_action: bool = False,
            same_analysis_case: bool = True,
        ) -> None:
            conflicts.append(
                BobaRepairPlanConflictV1(
                    conflict_record_id=_stable_id(
                        "repair_plan_conflict",
                        project_id,
                        repair_plan_id,
                        conflict_type,
                        key,
                    ),
                    repair_plan_snapshot_id=snapshot_id,
                    conflict_type=conflict_type,
                    severity=severity,
                    source_record_ids=[item for item in source_record_ids if item][:16],
                    source_record_digests=(source_record_digests or [])[:16],
                    value_a=_safe_text(value_a, 900),
                    value_b=_safe_text(value_b, 900),
                    same_repair_plan=True,
                    same_analysis_case=same_analysis_case,
                    same_workflow_run=bool(run_id),
                    current_records=True,
                    explicit_supersession_found=False,
                    resolved=False,
                    resolution_source_id=None,
                    blocks_action=blocks_action,
                    human_review_required=True,
                    bounded_summary=_safe_text(summary, 900),
                )
            )

        # Duplicate plan identity inside the owner's own current set.
        duplicates = [
            item
            for item, _case, _idx in self._plan_rows(project_id)
            if _safe_text(item.get("repair_strategy_id"), 180) == repair_plan_id
        ]
        if len(duplicates) > 1:
            add(
                "plan_identity_conflict",
                "duplicate",
                severity="critical",
                value_a=f"{len(duplicates)} strategy records",
                value_b=repair_plan_id,
                summary=(
                    "More than one Repair Planner strategy record claims this exact "
                    "repair_strategy_id."
                ),
                source_record_ids=[repair_plan_id],
                source_record_digests=[
                    _digest(_safe_payload(item)) for item in duplicates[:16]
                ],
                blocks_action=True,
            )

        # Two planning cases claiming the same repair_case_id with different parents.
        case_parents = {
            _safe_text(item.get("source_analysis_case_id"), 180)
            for item in self._keyed_rows(
                "repair_planner", project_id, "repair_cases", "repair_case_id"
            ).get(repair_case_id, [])
        }
        if len(case_parents) > 1:
            add(
                "analysis_identity_conflict",
                "case_parent",
                severity="critical",
                value_a=", ".join(sorted(item for item in case_parents if item)),
                value_b=repair_case_id,
                summary=(
                    "Records naming this exact repair_case_id disagree about which "
                    "root-cause analysis case owns it."
                ),
                source_record_ids=[repair_case_id],
                blocks_action=True,
                same_analysis_case=False,
            )

        # Two analysis cases claiming the same analysis_case_id with different incidents.
        if analysis_case_id:
            incident_parents = {
                _safe_text(item.get("source_diagnostic_case_id"), 180)
                for item in self._keyed_rows(
                    "root_cause_analyzer", project_id, "analysis_cases", "analysis_case_id"
                ).get(analysis_case_id, [])
            }
            if len(incident_parents) > 1:
                add(
                    "incident_identity_conflict",
                    "analysis_parent",
                    severity="critical",
                    value_a=", ".join(sorted(item for item in incident_parents if item)),
                    value_b=analysis_case_id,
                    summary=(
                        "Records naming this exact analysis_case_id disagree about "
                        "which incident it came from."
                    ),
                    source_record_ids=[analysis_case_id],
                    blocks_action=True,
                )

        gate = self._approval_gates(project_id).get(
            _safe_text(case.get("approval_gate_id"), 180), {}
        )
        actionable = any(
            bool(strategy.get(flag))
            for flag in (
                "requires_command_execution",
                "requires_code_change",
                "requires_configuration_change",
                "requires_service_restart",
                "requires_package_installation",
            )
        )
        if gate and _safe_text(gate.get("approval_status"), 120) == (
            "not_required_for_no_action"
        ) and actionable:
            add(
                "approval_status_conflict",
                "not_required_but_actionable",
                severity="critical",
                value_a="not_required_for_no_action",
                value_b="strategy declares an action that changes state",
                summary=(
                    "The approval gate for this repair case says approval is not "
                    "required for a no-action plan, but the strategy declares an "
                    "action that changes state."
                ),
                source_record_ids=[
                    _safe_text(gate.get("approval_gate_id"), 180),
                    repair_plan_id,
                ],
                blocks_action=True,
            )

        destructiveness = _safe_text(strategy.get("destructiveness") or "unknown", 80)
        reversibility = _safe_text(strategy.get("reversibility") or "unknown", 80)
        if destructiveness == "none" and actionable:
            add(
                "destructive_flag_conflict",
                "none_but_actionable",
                severity="warning",
                value_a="destructiveness=none",
                value_b="strategy declares a state-changing action",
                summary=(
                    "The strategy is rated non-destructive yet declares an action "
                    "that changes code, configuration, packages or a process."
                ),
                source_record_ids=[repair_plan_id],
            )
        if reversibility == "fully_reversible" and destructiveness in {"high", "blocked"}:
            add(
                "destructive_flag_conflict",
                "reversible_but_destructive",
                severity="warning",
                value_a=f"reversibility={reversibility}",
                value_b=f"destructiveness={destructiveness}",
                summary=(
                    "The strategy is rated fully reversible and highly destructive "
                    "at the same time. Reversible does not mean risk-free."
                ),
                source_record_ids=[repair_plan_id],
            )

        rollback = self._rollback_plans(project_id).get(
            _safe_text(case.get("rollback_plan_id"), 180), {}
        )
        if gate and bool(gate.get("rollback_plan_required", True)) and not rollback:
            add(
                "rollback_conflict",
                "required_but_absent",
                severity="critical",
                value_a="rollback_plan_required=true",
                value_b="no rollback plan record",
                summary=(
                    "The approval gate requires a rollback plan but no rollback "
                    "plan record is available for this repair case."
                ),
                source_record_ids=[_safe_text(gate.get("approval_gate_id"), 180)],
                blocks_action=True,
            )
        if rollback and not bool(rollback.get("rollback_required")) and (
            destructiveness in {"medium", "high", "blocked"}
        ):
            add(
                "rollback_conflict",
                "not_required_but_destructive",
                severity="warning",
                value_a="rollback_required=false",
                value_b=f"destructiveness={destructiveness}",
                summary=(
                    "The rollback plan says no rollback is required while the "
                    "strategy is rated destructive."
                ),
                source_record_ids=[
                    _safe_text(rollback.get("rollback_plan_id"), 180),
                    repair_plan_id,
                ],
            )

        validation = self._validation_plans(project_id).get(
            _safe_text(case.get("validation_plan_id"), 180), {}
        )
        if validation and bool(validation.get("requires_validator_runner")) and not [
            item
            for item in validation.get("required_validators", [])
            if isinstance(item, str) and item.strip()
        ]:
            add(
                "verification_conflict",
                "validator_runner_without_validators",
                severity="warning",
                value_a="requires_validator_runner=true",
                value_b="required_validators is empty",
                summary=(
                    "The validation plan requires Validator Runner but names no "
                    "validator to run."
                ),
                source_record_ids=[_safe_text(validation.get("validation_plan_id"), 180)],
            )
        results = self._validator_results(project_id)
        failed = [
            validator_id
            for validator_id in [
                _safe_text(item, 180)
                for item in validation.get("required_validators", [])
                if isinstance(item, str)
            ]
            if _safe_text(results.get(validator_id, {}).get("status"), 80)
            in {"failed", "blocked"}
        ]
        if failed and _safe_text(case.get("planning_status"), 120) == "plan_ready":
            add(
                "verification_conflict",
                "plan_ready_with_failed_validator",
                severity="critical",
                value_a="planning_status=plan_ready",
                value_b=", ".join(sorted(failed))[:400],
                summary=(
                    "The planning case is marked ready while a validator it "
                    "requires has a failing Validator Runner result."
                ),
                source_record_ids=[repair_case_id, *failed],
                blocks_action=True,
            )

        validations = self._recovery_validations(project_id)
        for link in self.build_recovery_links(project_id, repair_plan_id):
            if not link.succeeded_by_owner:
                continue
            rows = validations.get(link.recovery_attempt_id, [])
            unmet = [
                item
                for item in rows
                if not bool(item.get("required_checks_passed", True))
            ]
            if unmet:
                add(
                    "recovery_status_conflict",
                    link.recovery_attempt_id,
                    severity="critical",
                    value_a=f"attempt status={link.original_status}",
                    value_b="required output checks did not pass",
                    summary=(
                        "Tool Recovery reported this attempt as successful while "
                        "its own output validation records unmet required checks."
                    ),
                    source_record_ids=[link.recovery_attempt_id],
                    blocks_action=True,
                )

        recommended_id = _safe_text(case.get("recommended_strategy_id"), 180)
        if recommended_id == repair_plan_id and not bool(strategy.get("recommended")):
            add(
                "strategy_conflict",
                "recommended_flag",
                severity="warning",
                value_a="case recommends this strategy",
                value_b="strategy.recommended=false",
                summary=(
                    "The planning case recommends this strategy while the strategy "
                    "record does not mark itself recommended."
                ),
                source_record_ids=[repair_case_id, repair_plan_id],
            )
        rejected_ids = {
            _safe_text(item, 180)
            for item in case.get("rejected_strategy_ids", [])
            if isinstance(item, str)
        }
        if repair_plan_id in rejected_ids and repair_plan_id in {
            _safe_text(item, 180)
            for item in case.get("strategy_ids", [])
            if isinstance(item, str)
        }:
            add(
                "lifecycle_conflict",
                "active_and_rejected",
                severity="critical",
                value_a="listed in strategy_ids",
                value_b="listed in rejected_strategy_ids",
                summary=(
                    "The planning case lists this exact strategy as both active "
                    "and rejected."
                ),
                source_record_ids=[repair_case_id, repair_plan_id],
                blocks_action=True,
            )
        if not bool(case.get("repair_needed", True)) and actionable:
            add(
                "lifecycle_conflict",
                "repair_not_needed_but_actionable",
                severity="critical",
                value_a="repair_needed=false",
                value_b="strategy declares a state-changing action",
                summary=(
                    "The planning case says no repair is needed while this strategy "
                    "declares an action that changes state."
                ),
                source_record_ids=[repair_case_id, repair_plan_id],
                blocks_action=True,
            )
        if _safe_text(case.get("planning_status"), 120) == "repair_not_required" and (
            _safe_text(strategy.get("strategy_type"), 120) not in {"no_action", "unknown"}
        ):
            add(
                "lifecycle_conflict",
                "not_required_but_typed",
                severity="warning",
                value_a="planning_status=repair_not_required",
                value_b=f"strategy_type={_safe_text(strategy.get('strategy_type'), 120)}",
                summary=(
                    "The planning case says no repair is required while this "
                    "strategy proposes a repair type."
                ),
                source_record_ids=[repair_case_id, repair_plan_id],
            )
        stage = _safe_text(case.get("workflow_stage"), 180)
        for recovery_case in self._recovery_cases_for(project_id, repair_case_id):
            recovery_stage = _safe_text(recovery_case.get("workflow_stage"), 180)
            if stage and recovery_stage and recovery_stage != stage:
                add(
                    "workflow_identity_conflict",
                    _safe_text(recovery_case.get("recovery_case_id"), 180),
                    severity="warning",
                    value_a=f"repair case stage={stage}",
                    value_b=f"recovery case stage={recovery_stage}",
                    summary=(
                        "A Tool Recovery case built from this exact repair case "
                        "names a different workflow stage."
                    ),
                    source_record_ids=[
                        repair_case_id,
                        _safe_text(recovery_case.get("recovery_case_id"), 180),
                    ],
                )
        return conflicts[:_MAX_CONFLICTS]

    def inspect_repair_plan_conflicts(
        self, project_id: str, repair_plan_id: str
    ) -> dict[str, Any]:
        conflicts = self.detect_repair_plan_conflicts(project_id, repair_plan_id)
        return {
            "schema_version": "boba_repair_plan_review_conflicts_v1",
            "project_id": project_id,
            "repair_plan_id": repair_plan_id,
            "conflict_records": [item.model_dump(mode="json") for item in conflicts],
            "conflict_count": len(conflicts),
            "blocking_conflict_count": sum(1 for item in conflicts if item.blocks_action),
            "auto_resolved_count": 0,
            "limitations": [
                "Conflicts are reported only between records naming the same exact "
                "identity.",
                "A conflict is never resolved by comparing confidence, risk or "
                "recency.",
            ],
        }

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------
    @staticmethod
    def _priority(
        *,
        current: bool,
        historical: bool,
        superseded: bool,
        completed: bool,
        independently_verified: bool,
        destructive: bool,
        missing_human_or_safety_approval: bool,
        requires_code_change: bool,
        requires_artifact_change: bool,
        requires_workflow_transition: bool,
        requires_checkpoint_restore: bool,
        requires_process_restart: bool,
        approval_conflict: bool,
        missing_root_cause_evidence: bool,
        missing_verification: bool,
        failed_recovery: bool,
        missing_validator_evidence: bool,
        reversible: bool,
        human_action_required: bool,
    ) -> tuple[int, str]:
        """Return a deterministic display tier. A tier is never a score."""
        if historical:
            return 140, "historical_plan"
        if superseded:
            return 130, "superseded_plan"
        if completed and not independently_verified:
            return 120, "completed_but_unverified_plan"
        if current and destructive and missing_human_or_safety_approval:
            return 10, "current_destructive_plan_awaiting_human_or_safety_approval"
        if current and (
            requires_code_change or requires_artifact_change or requires_workflow_transition
        ):
            return 20, "current_plan_proposing_code_artifact_or_workflow_change"
        if current and (requires_checkpoint_restore or requires_process_restart):
            return 30, "current_plan_proposing_checkpoint_restore_or_process_restart"
        if current and approval_conflict:
            return 40, "current_plan_with_conflicting_approval_records"
        if current and missing_root_cause_evidence:
            return 50, "current_plan_with_missing_root_cause_evidence"
        if current and missing_verification:
            return 60, "current_plan_with_missing_verification_requirements"
        if current and failed_recovery:
            return 70, "current_plan_linked_to_a_failed_recovery_attempt"
        if current and missing_validator_evidence:
            return 80, "current_plan_with_stale_validator_or_artifact_evidence"
        if current and reversible:
            return 90, "current_reversible_plan_awaiting_review"
        if current and human_action_required:
            return 100, "other_current_plan_requiring_human_review"
        return 110, "other_current_plan"

    def _queue_item(
        self, project_id: str, reference: BobaRepairPlanReferenceV1, index: int
    ) -> BobaRepairPlanQueueItemV1:
        repair_plan_id = reference.repair_plan_id
        strategy, case, _order = self._plan_record(project_id, repair_plan_id)
        steps = self.build_step_projections(project_id, repair_plan_id)
        approvals = self.build_approval_requirements(project_id, repair_plan_id)
        verifications = self.build_verification_requirements(project_id, repair_plan_id)
        evidence = self.build_repair_evidence_cards(project_id, repair_plan_id)
        recovery = self.build_recovery_links(project_id, repair_plan_id)
        conflicts = self.detect_repair_plan_conflicts(project_id, repair_plan_id)
        gate = self._approval_gates(project_id).get(
            _safe_text(case.get("approval_gate_id"), 180), {}
        )
        rollback = self._rollback_plans(project_id).get(
            _safe_text(case.get("rollback_plan_id"), 180), {}
        )
        validation = self._validation_plans(project_id).get(
            _safe_text(case.get("validation_plan_id"), 180), {}
        )
        destructiveness = _safe_text(strategy.get("destructiveness") or "unknown", 120)
        reversibility = _safe_text(strategy.get("reversibility") or "unknown", 120)
        destructive = destructiveness in {"medium", "high", "blocked"} or any(
            item.destructive for item in steps
        )
        reversible = reversibility in {"fully_reversible", "mostly_reversible"}
        missing_approvals = [item for item in approvals if not item.satisfied_by_owner]
        missing_verifications = [item for item in verifications if not item.satisfied]
        missing_evidence = [item for item in evidence if item.missing]
        failed_recovery = [
            item
            for item in recovery
            if item.original_status
            in {"failed", "timed_out", "blocked", "rejected", "rolled_back"}
        ]
        # A sibling strategy's recovery success is never this plan's success:
        # attempts reached through the shared repair case may have executed a
        # different strategy, so the owner must have named this exact one.
        completed = any(
            item.succeeded_by_owner and item.linked_by_strategy_id
            for item in recovery
        )
        blockers = [
            item
            for item in conflicts
            if item.blocks_action or item.severity in {"critical", "blocking"}
        ]
        requires_code_change = bool(strategy.get("requires_code_change")) or any(
            item.requires_code_change for item in steps
        )
        requires_artifact_change = any(item.requires_artifact_change for item in steps)
        requires_workflow_transition = any(
            item.requires_workflow_transition for item in steps
        )
        requires_checkpoint_restore = any(
            item.requires_checkpoint_restore for item in steps
        )
        requires_process_restart = bool(strategy.get("requires_service_restart")) or any(
            item.requires_process_restart for item in steps
        )
        requires_tool_execution = bool(strategy.get("requires_command_execution")) or any(
            item.requires_tool_execution for item in steps
        )
        human_action_required = bool(
            case.get("human_review_required", True)
        ) or bool(missing_approvals)
        priority, reason = self._priority(
            current=reference.current,
            historical=reference.historical,
            superseded=reference.superseded,
            completed=completed,
            independently_verified=False,
            destructive=destructive,
            missing_human_or_safety_approval=any(
                item.requirement_type in {"human_review", "safety_gate"}
                for item in missing_approvals
            ),
            requires_code_change=requires_code_change,
            requires_artifact_change=requires_artifact_change,
            requires_workflow_transition=requires_workflow_transition,
            requires_checkpoint_restore=requires_checkpoint_restore,
            requires_process_restart=requires_process_restart,
            approval_conflict=any(
                item.conflict_type == "approval_status_conflict" for item in conflicts
            ),
            missing_root_cause_evidence=any(
                item.missing and item.source_module_id == "root_cause_analyzer"
                for item in evidence
            ),
            missing_verification=bool(missing_verifications),
            failed_recovery=bool(failed_recovery),
            missing_validator_evidence=any(
                item.missing and item.source_module_id == "validator_runner"
                for item in evidence
            ),
            reversible=reversible,
            human_action_required=human_action_required,
        )
        available_actions = self._available_actions(reference, blockers)
        return BobaRepairPlanQueueItemV1(
            repair_plan_queue_item_id=_stable_id(
                "repair_plan_queue_item", project_id, repair_plan_id
            ),
            repair_plan_reference_id=reference.repair_plan_reference_id,
            project_id=project_id,
            workflow_run_id=reference.workflow_run_id,
            stage_instance_id=reference.stage_instance_id,
            repair_plan_id=repair_plan_id,
            repair_case_id=reference.repair_case_id,
            source_analysis_case_id=reference.source_analysis_case_id,
            source_diagnostic_case_id=reference.source_diagnostic_case_id,
            title=_safe_text(strategy.get("title"), 240) or "Proposed Repair Strategy",
            bounded_summary=bounded_easy_explanation(
                strategy.get("easy_explanation") or strategy.get("description")
            )[:900],
            original_status=reference.original_status,
            original_strategy_type=reference.original_strategy_type,
            original_risk_level=reference.original_risk_level,
            original_reversibility=reversibility,
            original_destructiveness=destructiveness,
            approval_status=_safe_text(gate.get("approval_status") or "unavailable", 120),
            verification_status="satisfied"
            if verifications and not missing_verifications
            else "incomplete"
            if verifications
            else "unavailable",
            recovery_status="owner_reported_success"
            if completed
            else "failed"
            if failed_recovery
            else "attempted"
            if recovery
            else "unavailable",
            validation_status="planned" if validation else "unavailable",
            artifact_status="preservation_planned"
            if _safe_text(case.get("primary_artifact"), 180)
            else "unavailable",
            workflow_status=_safe_text(
                self._workflow_run(project_id).get("status") or "unavailable", 120
            ),
            affected_module_id=reference.affected_module_id,
            affected_stage_id=reference.affected_stage_id,
            step_count=len(steps),
            destructive=destructive,
            reversible=reversible,
            rollback_available=bool(rollback) and bool(rollback.get("rollback_required")),
            requires_code_change=requires_code_change,
            requires_artifact_change=requires_artifact_change,
            requires_workflow_transition=requires_workflow_transition,
            requires_tool_execution=requires_tool_execution,
            requires_process_restart=requires_process_restart,
            requires_checkpoint_restore=requires_checkpoint_restore,
            requires_human_approval=True,
            current=reference.current,
            stale=reference.stale,
            historical=reference.historical,
            superseded=reference.superseded,
            completed=completed,
            source_marked_recommended=bool(strategy.get("recommended")),
            human_action_required=human_action_required,
            blocker_count=len(blockers),
            warning_count=len(reference.warnings)
            + sum(len(item.warnings) for item in steps),
            missing_approval_count=len(missing_approvals),
            missing_verification_count=len(missing_verifications),
            missing_evidence_count=len(missing_evidence),
            conflict_count=len(conflicts),
            failed_recovery_attempt_count=len(failed_recovery),
            command_bearing_step_count=sum(
                1 for item in steps if item.raw_command_present_in_source
            ),
            available_action_descriptor_ids=available_actions,
            source_module_ids=sorted({item.source_module_id for item in evidence})[:24],
            source_record_digests={
                item.source_module_id: item.source_record_digest
                for item in evidence
                if item.source_record_digest
            },
            priority_tier=priority,
            priority_reason=reason,
            deterministic_sort_key=f"{index:06d}:{repair_plan_id}",
            warnings=list(reference.warnings)[:16],
            limitations=[
                "A priority tier is a display order, never a score, a plan ranking "
                "or a repair-success estimate.",
                "Repair Planner proposed this strategy.",
                NOT_EXECUTABLE_NOTICE,
            ],
        )

    @staticmethod
    def _filter_queue(
        items: list[BobaRepairPlanQueueItemV1], active_filter: RepairPlanReviewFilter
    ) -> list[BobaRepairPlanQueueItemV1]:
        predicates: dict[
            RepairPlanReviewFilter, Any
        ] = {
            "all_current": lambda item: item.current
            and not item.historical
            and not item.superseded,
            "human_review_required": lambda item: item.human_action_required,
            "destructive": lambda item: item.destructive,
            "reversible": lambda item: item.reversible,
            "code_change": lambda item: item.requires_code_change,
            "artifact_change": lambda item: item.requires_artifact_change,
            "workflow_change": lambda item: item.requires_workflow_transition,
            "tool_execution": lambda item: item.requires_tool_execution,
            "process_restart": lambda item: item.requires_process_restart,
            "checkpoint_restore": lambda item: item.requires_checkpoint_restore,
            "missing_approval": lambda item: item.missing_approval_count > 0,
            "missing_verification": lambda item: item.missing_verification_count > 0,
            "failed_recovery": lambda item: item.failed_recovery_attempt_count > 0,
            "conflicts": lambda item: item.conflict_count > 0,
            "stale": lambda item: item.stale,
            "completed": lambda item: item.completed,
            "historical": lambda item: item.historical,
            "superseded": lambda item: item.superseded,
        }
        predicate = predicates.get(active_filter)
        if predicate is None:
            raise ValidationError("Unsupported repair plan review filter.")
        return [item for item in items if predicate(item)]

    @staticmethod
    def _sort_queue(
        items: list[BobaRepairPlanQueueItemV1], active_sort: RepairPlanReviewSort
    ) -> list[BobaRepairPlanQueueItemV1]:
        def risk_rank(item: BobaRepairPlanQueueItemV1) -> int:
            level = item.original_risk_level
            return _RISK_ORDER.index(level) if level in _RISK_ORDER else len(_RISK_ORDER)

        keys: dict[RepairPlanReviewSort, Any] = {
            "review_priority": lambda item: (
                item.priority_tier,
                item.deterministic_sort_key,
            ),
            "source_severity": lambda item: (risk_rank(item), item.deterministic_sort_key),
            "creation_order": lambda item: item.deterministic_sort_key,
            "affected_module": lambda item: (
                item.affected_module_id,
                item.deterministic_sort_key,
            ),
            "step_count": lambda item: (-item.step_count, item.deterministic_sort_key),
            "repair_plan_id": lambda item: item.repair_plan_id,
        }
        key = keys.get(active_sort)
        if key is None:
            raise ValidationError("Unsupported repair plan review sort.")
        return sorted(items, key=key)

    def build_repair_plan_queue(
        self,
        project_id: str,
        *,
        active_filter: RepairPlanReviewFilter = "all_current",
        active_sort: RepairPlanReviewSort = "review_priority",
        offset: int = 0,
        limit: int = MAX_QUEUE_PAGE_SIZE,
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        if offset < 0:
            raise ValidationError("Repair plan queue offset cannot be negative.")
        page_size = max(1, min(limit, MAX_QUEUE_PAGE_SIZE))
        references = self.build_repair_plan_references(project_id)
        items = [
            self._queue_item(project_id, reference, index)
            for index, reference in enumerate(references)
        ]
        filtered = self._sort_queue(self._filter_queue(items, active_filter), active_sort)
        window = filtered[offset : offset + page_size]
        return {
            "schema_version": "boba_repair_plan_review_queue_v1",
            "project_id": project_id,
            "active_filter": active_filter,
            "active_sort": active_sort,
            "offset": offset,
            "limit": page_size,
            "total_count": len(items),
            "filtered_count": len(filtered),
            "returned_count": len(window),
            "has_more": offset + page_size < len(filtered),
            "items": [item.model_dump(mode="json") for item in window],
            "priority_tiers": [
                {"priority": priority, "reason": reason}
                for priority, reason in REPAIR_PLAN_QUEUE_PRIORITY_TIERS
            ],
            "limitations": [
                "The queue orders plans for display and never ranks them by "
                "expected repair success.",
                "Repair Planner proposed every plan shown here.",
            ],
        }

    def inspect_repair_plan_queue(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.build_repair_plan_queue(project_id, **kwargs)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    def _available_actions(
        self,
        reference: BobaRepairPlanReferenceV1,
        blocking_conflicts: list[BobaRepairPlanConflictV1] | None = None,
    ) -> list[str]:
        state = (
            "superseded"
            if reference.superseded
            else "historical"
            if reference.historical
            else "stale"
            if reference.stale
            else "current"
        )
        # An ambiguous identity chain makes the linked incident unsafe to name.
        ambiguous = any(
            item.conflict_type
            in {
                "plan_identity_conflict",
                "analysis_identity_conflict",
                "incident_identity_conflict",
            }
            for item in blocking_conflicts or []
        )
        available: list[str] = []
        for descriptor in build_fixed_repair_plan_action_registry().values():
            if not descriptor.allowed_in_v1 or descriptor.availability != "available":
                continue
            if descriptor.supported_plan_states and state not in (
                descriptor.supported_plan_states
            ):
                continue
            if not reference.schema_supported:
                continue
            if descriptor.requires_current_snapshot and not reference.current:
                continue
            if ambiguous:
                continue
            if descriptor.owning_operation_id == "acknowledge_notification" and not (
                reference.source_diagnostic_case_id
            ):
                continue
            available.append(descriptor.action_descriptor_id)
        return available

    def build_repair_plan_snapshot(
        self, project_id: str, session_id: str, repair_plan_id: str
    ) -> dict[str, Any]:
        """Build one immutable, digest-pinned view of an exact repair plan."""
        session = self.get_repair_plan_review_session(project_id, session_id)
        reference = self._reference_for(project_id, repair_plan_id)
        _strategy, case, _index = self._plan_record(project_id, repair_plan_id)
        snapshot_id = f"repair_plan_snapshot_{uuid4().hex}"
        steps = self.build_step_projections(
            project_id, repair_plan_id, snapshot_id=snapshot_id
        )
        risks = self.build_risk_projections(
            project_id, repair_plan_id, snapshot_id=snapshot_id
        )
        approvals = self.build_approval_requirements(
            project_id, repair_plan_id, snapshot_id=snapshot_id
        )
        verifications = self.build_verification_requirements(
            project_id, repair_plan_id, snapshot_id=snapshot_id
        )
        cards = self.build_repair_evidence_cards(
            project_id, repair_plan_id, snapshot_id=snapshot_id
        )
        recovery = self.build_recovery_links(
            project_id, repair_plan_id, snapshot_id=snapshot_id
        )
        conflicts = self.detect_repair_plan_conflicts(
            project_id, repair_plan_id, snapshot_id=snapshot_id
        )
        digests = {
            item.source_module_id: item.source_record_digest
            for item in cards
            if item.source_record_digest
        }
        gate = self._approval_gates(project_id).get(
            _safe_text(case.get("approval_gate_id"), 180), {}
        )
        rollback = self._rollback_plans(project_id).get(
            _safe_text(case.get("rollback_plan_id"), 180), {}
        )
        blocking = [
            item
            for item in conflicts
            if item.blocks_action or item.severity in {"critical", "blocking"}
        ]
        available_actions = self._available_actions(reference, blocking)
        plan_digest = self._repair_plan_digest(project_id, repair_plan_id)
        # A sibling strategy's recovery success is never this plan's success:
        # attempts reached through the shared repair case may have executed a
        # different strategy, so the owner must have named this exact one.
        completed = any(
            item.succeeded_by_owner and item.linked_by_strategy_id
            for item in recovery
        )

        def status_of(module_id: str) -> str:
            matched = [item for item in cards if item.source_module_id == module_id]
            if not matched:
                return "unavailable"
            if all(item.missing for item in matched):
                return "unavailable"
            return _safe_text(
                next(item.original_status for item in matched if not item.missing), 120
            )

        warnings = [
            *reference.warnings,
            *[item.bounded_summary for item in blocking],
        ]
        limitations = [
            "This snapshot is a read-only projection of canonical owner records.",
            "Repair Planner proposed this strategy. The panel does not state that "
            "it is the correct repair.",
            "A reversible plan is not a risk-free plan, and an available rollback "
            "is not a guaranteed rollback.",
            "Owner-reported success is not independent verification, and recovered "
            "is not resolved.",
            COMMAND_WITHHELD_NOTICE,
            PRIVATE_PATH_NOTICE,
            NOT_EXECUTABLE_NOTICE,
            SOURCE_RETAINED_NOTICE,
        ]
        base = {
            "repair_plan_snapshot_id": snapshot_id,
            "repair_plan_review_session_id": session.repair_plan_review_session_id,
            "repair_plan_reference_id": reference.repair_plan_reference_id,
            "project_id": project_id,
            "workflow_run_id": reference.workflow_run_id,
            "stage_instance_id": reference.stage_instance_id,
            "repair_plan_id": repair_plan_id,
            "repair_case_id": reference.repair_case_id,
            "source_analysis_case_id": reference.source_analysis_case_id,
            "source_diagnostic_case_id": reference.source_diagnostic_case_id,
            "project_snapshot_digest": reference.project_snapshot_digest,
            "workflow_revision": reference.workflow_revision,
            "repair_plan_digest": plan_digest,
            "source_record_references": [
                {
                    "source_module_id": item.source_module_id,
                    "source_record_id": item.source_record_id,
                    "evidence_type": item.evidence_type,
                }
                for item in cards[:24]
            ],
            "source_record_digests": digests,
            "step_projection_ids": [item.repair_step_projection_id for item in steps],
            "risk_projection_ids": [item.repair_risk_projection_id for item in risks],
            "approval_requirement_ids": [
                item.approval_requirement_id for item in approvals
            ],
            "verification_requirement_ids": [
                item.verification_requirement_id for item in verifications
            ],
            "evidence_card_ids": [item.repair_evidence_card_id for item in cards],
            "recovery_link_ids": [item.repair_recovery_link_id for item in recovery],
            "conflict_record_ids": [item.conflict_record_id for item in conflicts],
            "comparison_ids": [],
            "plan_status": reference.original_status,
            "approval_status": _safe_text(
                gate.get("approval_status") or "unavailable", 120
            ),
            "verification_status": "satisfied"
            if verifications and all(item.satisfied for item in verifications)
            else "incomplete"
            if verifications
            else "unavailable",
            "recovery_status": "owner_reported_success"
            if completed
            else "attempted"
            if recovery
            else "unavailable",
            "validation_status": status_of("validator_runner"),
            "artifact_status": status_of("artifact_inspector"),
            "workflow_status": status_of("workflow_controller"),
            "rights_status": "unavailable",
            "safety_status": status_of("safety_gate"),
            "final_decision_status": status_of("final_decision_bus"),
            "incident_status": status_of("error_doctor"),
            "current": reference.current,
            "stale": reference.stale,
            "historical": reference.historical,
            "superseded": reference.superseded,
            "completed": completed,
            "destructive": _safe_text(_strategy.get("destructiveness"), 80)
            in {"medium", "high", "blocked"},
            "reversible": _safe_text(_strategy.get("reversibility"), 80)
            in {"fully_reversible", "mostly_reversible"},
            "rollback_available": bool(rollback)
            and bool(rollback.get("rollback_required")),
            "missing_approval_count": sum(
                1 for item in approvals if not item.satisfied_by_owner
            ),
            "missing_verification_count": sum(
                1 for item in verifications if not item.satisfied
            ),
            "missing_evidence_count": sum(1 for item in cards if item.missing),
            "conflict_count": len(conflicts),
            "warning_count": len(warnings),
            "limitation_count": len(limitations),
            "available_action_descriptor_ids": available_actions,
        }
        confirmation_digest = _digest(
            {
                "project": reference.project_snapshot_digest,
                "revision": reference.workflow_revision,
                "repair_plan": plan_digest,
                "sources": digests,
                "actions": available_actions,
            }
        )
        snapshot = BobaRepairPlanSnapshotV1(
            **base,
            confirmation_context_digest=confirmation_digest,
            snapshot_digest=_digest(base),
            warnings=[item for item in warnings if item][:24],
            limitations=limitations[:24],
        )
        self.store.save_boba_repair_plan_review_snapshot(
            project_id, snapshot_id, snapshot.model_dump(mode="json")
        )
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "repair_plan_reference": reference.model_dump(mode="json"),
            "step_projections": [item.model_dump(mode="json") for item in steps],
            "risk_projections": [item.model_dump(mode="json") for item in risks],
            "approval_requirements": [item.model_dump(mode="json") for item in approvals],
            "verification_requirements": [
                item.model_dump(mode="json") for item in verifications
            ],
            "evidence_cards": [item.model_dump(mode="json") for item in cards],
            "recovery_links": [item.model_dump(mode="json") for item in recovery],
            "conflict_records": [item.model_dump(mode="json") for item in conflicts],
            "action_confirmations": self._action_confirmations(snapshot),
        }

    def refresh_repair_plan_snapshot(
        self, project_id: str, snapshot_id: str
    ) -> dict[str, Any]:
        snapshot = self._snapshot(project_id, snapshot_id)
        return self.build_repair_plan_snapshot(
            project_id,
            snapshot.repair_plan_review_session_id,
            snapshot.repair_plan_id,
        )

    def _snapshot(self, project_id: str, snapshot_id: str) -> BobaRepairPlanSnapshotV1:
        _safe_id(project_id, "project id")
        _safe_id(snapshot_id, "repair plan snapshot id")
        raw = self.store.load_boba_repair_plan_review_snapshot(project_id, snapshot_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA repair plan snapshot is unavailable.")
        snapshot = BobaRepairPlanSnapshotV1.model_validate(raw)
        if snapshot.project_id != project_id:
            raise ValidationError("Repair plan snapshot belongs to another project.")
        return snapshot

    def _action_confirmations(self, snapshot: BobaRepairPlanSnapshotV1) -> dict[str, str]:
        registry = build_fixed_repair_plan_action_registry()
        tokens: dict[str, str] = {}
        for action_id in snapshot.available_action_descriptor_ids:
            descriptor = registry.get(action_id)
            if descriptor is None:
                continue
            tokens[action_id] = _digest(
                {
                    "snapshot": snapshot.snapshot_digest,
                    "action": descriptor.action_descriptor_id,
                    "repair_plan": snapshot.repair_plan_digest,
                }
            )
        return tokens

    def inspect_repair_plan(self, project_id: str, repair_plan_id: str) -> dict[str, Any]:
        reference = self._reference_for(project_id, repair_plan_id)
        return {
            "schema_version": "boba_repair_plan_review_plan_v1",
            "project_id": project_id,
            "repair_plan_id": repair_plan_id,
            "repair_plan_reference": reference.model_dump(mode="json"),
            "step_projections": [
                item.model_dump(mode="json")
                for item in self.build_step_projections(project_id, repair_plan_id)
            ],
            "risk_projections": [
                item.model_dump(mode="json")
                for item in self.build_risk_projections(project_id, repair_plan_id)
            ],
            "approval_requirements": [
                item.model_dump(mode="json")
                for item in self.build_approval_requirements(project_id, repair_plan_id)
            ],
            "verification_requirements": [
                item.model_dump(mode="json")
                for item in self.build_verification_requirements(
                    project_id, repair_plan_id
                )
            ],
            "evidence_cards": [
                item.model_dump(mode="json")
                for item in self.build_repair_evidence_cards(project_id, repair_plan_id)
            ],
            "recovery_links": [
                item.model_dump(mode="json")
                for item in self.build_recovery_links(project_id, repair_plan_id)
            ],
            "conflict_records": [
                item.model_dump(mode="json")
                for item in self.detect_repair_plan_conflicts(project_id, repair_plan_id)
            ],
            "notices": {
                "command": COMMAND_WITHHELD_NOTICE,
                "private_path": PRIVATE_PATH_NOTICE,
                "not_executable": NOT_EXECUTABLE_NOTICE,
                "source_retained": SOURCE_RETAINED_NOTICE,
            },
            "limitations": [
                "Repair Planner proposed this strategy.",
                "The panel creates, revises, approves, rejects and executes nothing.",
            ],
        }

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    def compare_repair_plans(
        self,
        project_id: str,
        repair_plan_ids: Sequence[str],
        *,
        comparison_type: RepairPlanComparisonType = "side_by_side",
    ) -> dict[str, Any]:
        """Compare exact plans field by field. No winner is ever selected."""
        _safe_id(project_id, "project id")
        unique: list[str] = []
        for item in repair_plan_ids:
            plan_id = _safe_id(str(item), "repair plan id")
            if plan_id not in unique:
                unique.append(plan_id)
        if len(unique) < 2:
            raise ValidationError("At least two distinct repair plans are required.")
        if len(unique) > MAX_COMPARISON_PLANS:
            raise ValidationError(
                f"At most {MAX_COMPARISON_PLANS} repair plans may be compared."
            )
        references = {
            plan_id: self._reference_for(project_id, plan_id) for plan_id in unique
        }
        records = {plan_id: self._plan_record(project_id, plan_id) for plan_id in unique}
        steps = {
            plan_id: self.build_step_projections(project_id, plan_id)
            for plan_id in unique
        }
        risks = {
            plan_id: self.build_risk_projections(project_id, plan_id)
            for plan_id in unique
        }
        approvals = {
            plan_id: self.build_approval_requirements(project_id, plan_id)
            for plan_id in unique
        }
        verifications = {
            plan_id: self.build_verification_requirements(project_id, plan_id)
            for plan_id in unique
        }
        evidence = {
            plan_id: self.build_repair_evidence_cards(project_id, plan_id)
            for plan_id in unique
        }
        recovery = {
            plan_id: self.build_recovery_links(project_id, plan_id) for plan_id in unique
        }
        conflicts = {
            plan_id: self.detect_repair_plan_conflicts(project_id, plan_id)
            for plan_id in unique
        }
        missing_field_paths: list[str] = []

        def rows(builder: Any) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for plan_id in unique:
                row = {"repair_plan_id": plan_id}
                row.update(builder(plan_id))
                result.append(row)
            return result

        def strategy_row(plan_id: str) -> dict[str, Any]:
            strategy, case, _index = records[plan_id]
            for field in ("strategy_type", "estimated_risk", "reversibility"):
                if not _safe_text(strategy.get(field), 120):
                    missing_field_paths.append(f"{plan_id}.strategy.{field}")
            return {
                "title": _safe_text(strategy.get("title"), 240),
                "strategy_type": _safe_text(strategy.get("strategy_type") or "unknown", 120),
                "target_module": _safe_text(strategy.get("target_module"), 180),
                "source_marked_recommended": bool(strategy.get("recommended")),
                "source_rank": strategy.get("rank")
                if isinstance(strategy.get("rank"), int)
                else None,
                "planning_status": _safe_text(
                    case.get("planning_status") or "unknown", 120
                ),
                "automation_eligibility": _safe_text(
                    strategy.get("automation_eligibility") or "unknown", 120
                ),
                "bounded_summary": bounded_easy_explanation(
                    strategy.get("easy_explanation") or strategy.get("description")
                )[:900],
            }

        comparison_id = _stable_id("repair_plan_comparison", project_id, *unique)
        case_ids = {references[plan_id].repair_case_id for plan_id in unique}
        analysis_ids = {references[plan_id].source_analysis_case_id for plan_id in unique}
        incident_ids = {
            references[plan_id].source_diagnostic_case_id for plan_id in unique
        }
        run_ids = {references[plan_id].workflow_run_id for plan_id in unique}
        comparison = BobaRepairPlanComparisonV1(
            comparison_id=comparison_id,
            project_id=project_id,
            repair_plan_ids=unique,
            comparison_type=comparison_type,
            same_repair_case=len(case_ids) == 1,
            same_analysis_case=len(analysis_ids) == 1 and bool(next(iter(analysis_ids))),
            same_incident=len(incident_ids) == 1 and bool(next(iter(incident_ids))),
            same_workflow_run=len(run_ids) == 1,
            repair_plan_snapshot_ids=[],
            strategy_comparison=rows(strategy_row),
            step_comparison=rows(
                lambda plan_id: {
                    "step_count": len(steps[plan_id]),
                    "destructive_step_count": sum(
                        1 for item in steps[plan_id] if item.destructive
                    ),
                    "read_only_step_count": sum(
                        1 for item in steps[plan_id] if item.read_only_by_owner
                    ),
                    "command_bearing_step_count": sum(
                        1
                        for item in steps[plan_id]
                        if item.raw_command_present_in_source
                    ),
                    "step_types": sorted(
                        {item.original_step_type for item in steps[plan_id]}
                    )[:16],
                    "raw_command_exposed": False,
                }
            ),
            approval_comparison=rows(
                lambda plan_id: {
                    "required_count": len(approvals[plan_id]),
                    "satisfied_count": sum(
                        1 for item in approvals[plan_id] if item.satisfied_by_owner
                    ),
                    "missing_count": sum(
                        1 for item in approvals[plan_id] if not item.satisfied_by_owner
                    ),
                    "requirement_types": sorted(
                        {item.requirement_type for item in approvals[plan_id]}
                    )[:16],
                }
            ),
            risk_comparison=rows(
                lambda plan_id: {
                    "overall_risk": next(
                        (
                            item.original_risk_level
                            for item in risks[plan_id]
                            if item.risk_dimension == "overall_risk"
                        ),
                        "unavailable",
                    ),
                    "blocked_dimension_count": sum(
                        1 for item in risks[plan_id] if item.blocked_by_owner
                    ),
                    "source_estimated_risk": _safe_text(
                        records[plan_id][0].get("estimated_risk") or "unknown", 120
                    ),
                    "panel_risk_score": None,
                }
            ),
            destructive_comparison=rows(
                lambda plan_id: {
                    "destructiveness": _safe_text(
                        records[plan_id][0].get("destructiveness") or "unknown", 120
                    ),
                    "requires_code_change": bool(
                        records[plan_id][0].get("requires_code_change")
                    ),
                    "requires_command_execution": bool(
                        records[plan_id][0].get("requires_command_execution")
                    ),
                    "requires_service_restart": bool(
                        records[plan_id][0].get("requires_service_restart")
                    ),
                    "requires_package_installation": bool(
                        records[plan_id][0].get("requires_package_installation")
                    ),
                }
            ),
            rollback_comparison=rows(
                lambda plan_id: {
                    "reversibility": _safe_text(
                        records[plan_id][0].get("reversibility") or "unknown", 120
                    ),
                    "requires_checkpoint": bool(
                        records[plan_id][0].get("requires_checkpoint")
                    ),
                    "requires_backup": bool(records[plan_id][0].get("requires_backup")),
                    "rollback_requirement_satisfied": any(
                        item.requirement_type == "rollback_plan" and item.satisfied_by_owner
                        for item in approvals[plan_id]
                    ),
                    "rollback_guaranteed": False,
                }
            ),
            verification_comparison=rows(
                lambda plan_id: {
                    "required_count": len(verifications[plan_id]),
                    "satisfied_count": sum(
                        1 for item in verifications[plan_id] if item.satisfied
                    ),
                    "independently_verified_count": 0,
                    "verification_types": sorted(
                        {item.verification_type for item in verifications[plan_id]}
                    )[:16],
                }
            ),
            recovery_comparison=rows(
                lambda plan_id: {
                    "attempt_count": len(recovery[plan_id]),
                    "owner_reported_success_count": sum(
                        1 for item in recovery[plan_id] if item.succeeded_by_owner
                    ),
                    "failed_attempt_count": sum(
                        1
                        for item in recovery[plan_id]
                        if item.original_status
                        in {"failed", "timed_out", "blocked", "rejected", "rolled_back"}
                    ),
                    "independently_verified_count": 0,
                }
            ),
            evidence_coverage_comparison=rows(
                lambda plan_id: {
                    "evidence_count": len(evidence[plan_id]),
                    "missing_evidence_count": sum(
                        1 for item in evidence[plan_id] if item.missing
                    ),
                    "source_module_ids": sorted(
                        {item.source_module_id for item in evidence[plan_id]}
                    )[:24],
                }
            ),
            warning_comparison=rows(
                lambda plan_id: {
                    "warning_count": len(references[plan_id].warnings),
                    "conflict_count": len(conflicts[plan_id]),
                    "blocking_conflict_count": sum(
                        1 for item in conflicts[plan_id] if item.blocks_action
                    ),
                }
            ),
            limitation_comparison=rows(
                lambda plan_id: {
                    "limitation_count": len(references[plan_id].limitations),
                    "schema_supported": references[plan_id].schema_supported,
                }
            ),
            current_repair_plan_ids=[
                plan_id for plan_id in unique if references[plan_id].current
            ],
            historical_repair_plan_ids=[
                plan_id for plan_id in unique if references[plan_id].historical
            ],
            missing_field_paths=sorted(set(missing_field_paths))[:32],
            bounded_summary=_safe_text(
                f"Comparing {len(unique)} Repair Planner strategies field by field.",
                900,
            ),
            limitations=[
                "The panel selects no winner, no recommended plan and no plan to "
                "execute.",
                "Where a source omits a field it is listed as missing rather than "
                "filled in.",
                "A source rank or recommended flag is Repair Planner's own value.",
                COMMAND_WITHHELD_NOTICE,
            ],
        )
        return {
            "schema_version": "boba_repair_plan_review_comparison_v1",
            "project_id": project_id,
            "comparison": comparison.model_dump(mode="json"),
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _action_descriptor(self, action_id: str) -> BobaRepairPlanActionDescriptorV1:
        _safe_id(action_id, "action descriptor id")
        descriptor = build_fixed_repair_plan_action_registry().get(action_id)
        if descriptor is None:
            raise ValidationError("Unknown fixed BOBA repair plan review action descriptor.")
        return descriptor

    def create_repair_plan_action_request(
        self,
        project_id: str,
        *,
        repair_plan_review_session_id: str,
        repair_plan_snapshot_id: str,
        action_descriptor_id: str,
        decision_value: str | None,
        reason: str,
        confirmation_context_digest: str,
        idempotency_key: str,
        confirmed: bool,
    ) -> BobaRepairPlanActionRequestV1:
        session = self.get_repair_plan_review_session(
            project_id, repair_plan_review_session_id
        )
        snapshot = self._snapshot(project_id, repair_plan_snapshot_id)
        if snapshot.repair_plan_review_session_id != (
            session.repair_plan_review_session_id
        ):
            raise ValidationError("Repair plan snapshot belongs to another review session.")
        descriptor = self._action_descriptor(action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            raise ValidationError(
                "This BOBA repair plan review action is unavailable in V1: "
                f"{descriptor.unavailable_reason}"
            )
        if descriptor.action_descriptor_id not in snapshot.available_action_descriptor_ids:
            raise ValidationError("The action is unavailable for this exact repair plan.")
        if descriptor.allowed_decision_values and decision_value not in (
            descriptor.allowed_decision_values
        ):
            raise ValidationError("Unsupported decision value for this fixed action.")
        if descriptor.requires_reason and not reason.strip():
            raise ValidationError("This repair plan review action requires a reason.")
        if len(reason) > descriptor.maximum_reason_length:
            raise ValidationError("Repair plan review reason exceeds the allowed length.")
        if _contains_secret(reason):
            raise ValidationError("Repair plan review reasons cannot contain credentials.")
        if _PRIVATE_PATH.search(reason) or _FULL_PRIVATE_PATH.search(reason):
            raise ValidationError(
                "Repair plan review reasons cannot contain private path material."
            )
        if source_holds_command(reason):
            raise ValidationError(
                "Repair plan review reasons cannot contain executable command text."
            )
        if not confirmed:
            raise ValidationError("Explicit repair plan review confirmation is required.")
        if descriptor.requires_reviewer_context and not session.reviewer_context_id:
            raise ValidationError("An exact reviewer context is required.")
        expected = self._action_confirmations(snapshot).get(descriptor.action_descriptor_id)
        if not expected or confirmation_context_digest != expected:
            raise ValidationError(
                "Repair plan review confirmation does not match the current plan."
            )
        _safe_id(idempotency_key, "idempotency key")
        request = BobaRepairPlanActionRequestV1(
            repair_plan_action_request_id=f"repair_plan_action_{uuid4().hex}",
            repair_plan_review_session_id=session.repair_plan_review_session_id,
            repair_plan_snapshot_id=snapshot.repair_plan_snapshot_id,
            project_id=project_id,
            workflow_run_id=snapshot.workflow_run_id,
            stage_instance_id=snapshot.stage_instance_id,
            repair_plan_id=snapshot.repair_plan_id,
            repair_case_id=snapshot.repair_case_id,
            source_analysis_case_id=snapshot.source_analysis_case_id,
            source_diagnostic_case_id=snapshot.source_diagnostic_case_id,
            expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            reviewer_context_id=session.reviewer_context_id,
            action_descriptor_id=descriptor.action_descriptor_id,
            owning_module_id=descriptor.owning_module_id,
            owning_operation_id=descriptor.owning_operation_id,
            decision_value=decision_value,
            bounded_reason=_safe_text(reason, descriptor.maximum_reason_length),
            expected_project_snapshot_digest=snapshot.project_snapshot_digest,
            expected_workflow_revision=snapshot.workflow_revision,
            expected_repair_plan_digest=snapshot.repair_plan_digest,
            expected_source_record_digests=snapshot.source_record_digests
            if descriptor.requires_source_record_digests
            else {},
            expected_safety_record_digest=(
                self._safety_record_digest(project_id)
                if descriptor.requires_safety_gate
                else None
            ),
            expected_final_decision_record_digest=(
                self._final_decision_record_digest(project_id)
                if descriptor.requires_final_decision_bus
                else None
            ),
            confirmation_context_digest=confirmation_context_digest,
            idempotency_key=idempotency_key,
            confirmed=True,
            limitations=list(descriptor.does_not_do)[:16],
        )
        self.store.save_boba_repair_plan_review_action(
            project_id,
            request.repair_plan_action_request_id,
            request.model_dump(mode="json"),
        )
        return request

    def describe_repair_plan_action_confirmation(
        self, project_id: str, repair_plan_snapshot_id: str, action_descriptor_id: str
    ) -> dict[str, Any]:
        """Return the exact confirmation text a reviewer must read and accept."""
        snapshot = self._snapshot(project_id, repair_plan_snapshot_id)
        descriptor = self._action_descriptor(action_descriptor_id)
        token = self._action_confirmations(snapshot).get(descriptor.action_descriptor_id)
        return {
            "schema_version": "boba_repair_plan_review_confirmation_v1",
            "project_id": project_id,
            "repair_plan_snapshot_id": snapshot.repair_plan_snapshot_id,
            "repair_plan_id": snapshot.repair_plan_id,
            "action_descriptor_id": descriptor.action_descriptor_id,
            "available": descriptor.action_descriptor_id
            in snapshot.available_action_descriptor_ids,
            "unavailable_reason": descriptor.unavailable_reason,
            "confirmation_context_digest": token,
            "owning_module_id": descriptor.owning_module_id,
            "owning_operation_id": descriptor.owning_operation_id,
            "consequences": list(descriptor.consequences),
            "does_not_do": list(descriptor.does_not_do),
            "confirmation_statement": (
                "This request does not directly execute commands, modify code, "
                "change artifacts, restore a checkpoint, restart a process, "
                "transition the workflow, grant Rights or Safety approval, upload "
                "content or publish content."
            ),
        }

    def validate_repair_plan_action_request(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        """Re-read canonical state and reject stale or drifted submissions."""
        request = self._action_request(project_id, request_id)
        expires_at = _parse_time(request.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            return {
                "valid": False,
                "code": "expired_snapshot",
                "message": "The repair plan review action expired before submission.",
            }
        descriptor = self._action_descriptor(request.action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "This repair plan review action is no longer available.",
            }
        try:
            reference = self._reference_for(project_id, request.repair_plan_id)
        except ValidationError:
            return {
                "valid": False,
                "code": "repair_plan_removed",
                "message": "The repair plan is no longer available.",
            }
        if reference.repair_case_id != request.repair_case_id:
            return {
                "valid": False,
                "code": "repair_case_identity_mismatch",
                "message": "The plan now belongs to a different repair case.",
            }
        if reference.source_analysis_case_id != request.source_analysis_case_id:
            return {
                "valid": False,
                "code": "analysis_identity_mismatch",
                "message": "The plan now references a different root-cause analysis case.",
            }
        if reference.source_diagnostic_case_id != request.source_diagnostic_case_id:
            return {
                "valid": False,
                "code": "incident_identity_mismatch",
                "message": "The plan now references a different incident.",
            }
        if reference.workflow_run_id != request.workflow_run_id:
            return {
                "valid": False,
                "code": "workflow_identity_mismatch",
                "message": "The plan now references a different workflow run.",
            }
        if self._project_snapshot_digest(project_id) != (
            request.expected_project_snapshot_digest
        ):
            return {
                "valid": False,
                "code": "stale_project_snapshot",
                "message": "The project changed while this review was open.",
            }
        if descriptor.requires_workflow_revision and self._workflow_revision(
            project_id
        ) != request.expected_workflow_revision:
            return {
                "valid": False,
                "code": "workflow_revision_mismatch",
                "message": "The workflow revision changed while this review was open.",
            }
        if self._repair_plan_digest(project_id, request.repair_plan_id) != (
            request.expected_repair_plan_digest
        ):
            return {
                "valid": False,
                "code": "repair_plan_digest_mismatch",
                "message": "The repair plan changed while this review was open.",
            }
        live = {
            item.source_module_id: item.source_record_digest
            for item in self.build_repair_evidence_cards(
                project_id, request.repair_plan_id
            )
            if item.source_record_digest
        }
        for module_id, digest in request.expected_source_record_digests.items():
            if live.get(module_id) != digest:
                return {
                    "valid": False,
                    "code": "source_record_digest_mismatch",
                    "message": (
                        "A canonical source record changed while this review was open."
                    ),
                }
        if request.expected_safety_record_digest is not None and (
            self._safety_record_digest(project_id) != request.expected_safety_record_digest
        ):
            return {
                "valid": False,
                "code": "safety_record_digest_mismatch",
                "message": "The Safety Gate record changed while this review was open.",
            }
        if request.expected_final_decision_record_digest is not None and (
            self._final_decision_record_digest(project_id)
            != request.expected_final_decision_record_digest
        ):
            return {
                "valid": False,
                "code": "final_decision_record_digest_mismatch",
                "message": (
                    "The Final Decision Bus record changed while this review was open."
                ),
            }
        blocking = [
            item
            for item in self.detect_repair_plan_conflicts(project_id, request.repair_plan_id)
            if item.blocks_action or item.severity in {"critical", "blocking"}
        ]
        if descriptor.action_descriptor_id not in self._available_actions(
            reference, blocking
        ):
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "The action is no longer available for this exact repair plan.",
            }
        return {
            "valid": True,
            "code": "current",
            "message": "Exact repair plan state remains current.",
        }

    def _action_request(
        self, project_id: str, request_id: str
    ) -> BobaRepairPlanActionRequestV1:
        _safe_id(project_id, "project id")
        _safe_id(request_id, "repair plan action request id")
        raw = self.store.load_boba_repair_plan_review_action(project_id, request_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA repair plan review action request is unavailable.")
        request = BobaRepairPlanActionRequestV1.model_validate(raw)
        if request.project_id != project_id:
            raise ValidationError("Repair plan action belongs to another project.")
        return request

    async def submit_repair_plan_action_to_owner(
        self, project_id: str, request_id: str
    ) -> BobaRepairPlanActionReceiptV1:
        """Submit to the canonical owner and persist an immutable receipt."""
        request = self._action_request(project_id, request_id)
        existing = self.store.load_boba_repair_plan_review_receipt_for_action(
            project_id, request_id
        )
        if isinstance(existing, Mapping):
            receipt = BobaRepairPlanActionReceiptV1.model_validate(existing)
            return receipt.model_copy(update={"duplicate_request_reused": True})
        validation = self.validate_repair_plan_action_request(project_id, request_id)
        if not validation["valid"]:
            return self._persist_receipt(
                project_id,
                self._receipt(
                    request,
                    canonical_status="rejected_stale_state",
                    stale_state_rejected=True,
                    error_code=str(validation["code"]),
                    message=str(validation["message"]),
                    limitations=["No canonical owner was contacted; nothing changed."],
                ),
            )
        descriptor = self._action_descriptor(request.action_descriptor_id)
        if (
            descriptor.owning_module_id == "review_ui"
            and descriptor.owning_operation_id == "acknowledge_notification"
        ):
            return await self._submit_acknowledgement(project_id, request)
        return self._persist_receipt(
            project_id,
            self._receipt(
                request,
                canonical_status="owner_route_unavailable",
                error_code="owner_route_unavailable",
                message="No exact canonical owner route exists for this V1 action.",
                limitations=["No authoritative state changed."],
            ),
        )

    @staticmethod
    def _receipt(
        request: BobaRepairPlanActionRequestV1,
        *,
        canonical_status: str,
        stale_state_rejected: bool = False,
        error_code: str | None = None,
        message: str = "",
        limitations: list[str] | None = None,
    ) -> BobaRepairPlanActionReceiptV1:
        return BobaRepairPlanActionReceiptV1(
            repair_plan_action_receipt_id=f"repair_plan_receipt_{uuid4().hex}",
            repair_plan_action_request_id=request.repair_plan_action_request_id,
            project_id=request.project_id,
            repair_plan_id=request.repair_plan_id,
            owning_module_id=request.owning_module_id,
            owning_operation_id=request.owning_operation_id,
            completed_at=now_iso(),
            accepted_by_owner=False,
            canonical_status=canonical_status,
            authoritative_state_changed=False,
            plan_approved=False,
            plan_rejected=False,
            plan_revised=False,
            repair_executed=False,
            recovery_attempt_started=False,
            checkpoint_restored=False,
            process_restarted=False,
            workflow_changed=False,
            code_changed=False,
            artifact_changed=False,
            stale_state_rejected=stale_state_rejected,
            error_code=error_code,
            bounded_error_message=_safe_text(message, 900),
            limitations=limitations or [],
        )

    async def _submit_acknowledgement(
        self, project_id: str, request: BobaRepairPlanActionRequestV1
    ) -> BobaRepairPlanActionReceiptV1:
        """Route to Review UI, the owner of incident acknowledgement metadata."""
        incident_id = request.source_diagnostic_case_id
        if not incident_id:
            return self._persist_receipt(
                project_id,
                self._receipt(
                    request,
                    canonical_status="owner_route_unavailable",
                    error_code="incident_identity_unavailable",
                    message=(
                        "The repair plan names no incident identity, so there is "
                        "nothing canonical to acknowledge."
                    ),
                    limitations=["No authoritative state changed."],
                ),
            )
        try:
            session_payload = self.integration.create_boba_review_session(
                project_id,
                reviewer_context_id=request.reviewer_context_id,
                review_mode="incident_review",
                target_type="incident",
                target_id=incident_id,
            )
            review_session_id = _safe_text(
                _as_mapping(session_payload).get("review_session_id"), 180
            )
            if not review_session_id:
                raise ValidationError("Review UI returned no review session identity.")
            acknowledged = self.integration.acknowledge_boba_review_notification(
                project_id, review_session_id, incident_id
            )
        except (ValidationError, NotFoundError) as error:
            return self._persist_receipt(
                project_id,
                self._receipt(
                    request,
                    canonical_status="rejected_by_owner",
                    error_code="owner_rejected",
                    message=str(error),
                    limitations=[
                        "Review UI rejected the acknowledgement; nothing changed.",
                    ],
                ),
            )
        payload = _as_mapping(acknowledged)
        acknowledged_ids = payload.get("acknowledged_notification_ids")
        if not isinstance(acknowledged_ids, list) or incident_id not in [
            str(item) for item in acknowledged_ids
        ]:
            return self._persist_receipt(
                project_id,
                self._receipt(
                    request,
                    canonical_status="malformed_owner_response",
                    error_code="malformed_canonical_response",
                    message=(
                        "Review UI did not record this incident identity in its "
                        "acknowledged list."
                    ),
                    limitations=["No authoritative state changed."],
                ),
            )
        accepted = self._receipt(request, canonical_status="acknowledged")
        return self._persist_receipt(
            project_id,
            accepted.model_copy(
                update={
                    "owning_module_id": "review_ui",
                    "owning_operation_id": "acknowledge_notification",
                    "accepted_by_owner": True,
                    "canonical_request_id": request.repair_plan_action_request_id,
                    "canonical_record_id": _safe_text(
                        payload.get("review_session_id"), 180
                    ),
                    "canonical_record_digest": _safe_text(
                        payload.get("session_digest"), 64
                    )
                    or _digest(_safe_payload(payload)),
                    "canonical_status": "acknowledged",
                    # Acknowledgement is Review-UI-session metadata about the
                    # linked incident. No repair plan, approval, execution,
                    # recovery, checkpoint, workflow, code or artifact authority
                    # changes.
                    "authoritative_state_changed": False,
                    "canonical_refresh_required": True,
                    "limitations": [
                        "Acknowledgement changes Review UI session metadata for the "
                        "linked incident only.",
                        "The repair plan stays exactly as Repair Planner recorded it.",
                        *descriptor_does_not_do(request.action_descriptor_id),
                    ][:16],
                }
            ),
        )

    def _persist_receipt(
        self, project_id: str, receipt: BobaRepairPlanActionReceiptV1
    ) -> BobaRepairPlanActionReceiptV1:
        if receipt.authoritative_state_changed and not (
            receipt.canonical_record_id and receipt.canonical_record_digest
        ):
            raise ValidationError(
                "Authoritative state cannot change without a canonical owner record."
            )
        for flag, label in (
            (receipt.plan_approved, "plan approval"),
            (receipt.plan_rejected, "plan rejection"),
            (receipt.plan_revised, "plan revision"),
            (receipt.repair_executed, "repair execution"),
            (receipt.recovery_attempt_started, "recovery start"),
            (receipt.checkpoint_restored, "checkpoint restore"),
            (receipt.process_restarted, "process restart"),
            (receipt.workflow_changed, "workflow change"),
            (receipt.code_changed, "code change"),
            (receipt.artifact_changed, "artifact change"),
        ):
            if flag and not (receipt.canonical_record_id and receipt.canonical_record_digest):
                raise ValidationError(
                    f"A receipt cannot claim {label} without a canonical owner record."
                )
        self.store.save_boba_repair_plan_review_receipt(
            project_id,
            receipt.repair_plan_action_receipt_id,
            receipt.model_dump(mode="json"),
        )
        return receipt

    def inspect_repair_plan_action_receipt(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        request = self._action_request(project_id, request_id)
        receipt = self.store.load_boba_repair_plan_review_receipt_for_action(
            project_id, request_id
        )
        return {
            "request": request.model_dump(mode="json"),
            "receipt": _safe_payload(receipt) if receipt else None,
        }

    # ------------------------------------------------------------------
    # Events and timeline
    # ------------------------------------------------------------------
    def inspect_repair_plan_events(
        self, project_id: str, *, after_sequence: int = 0, limit: int = _MAX_EVENTS
    ) -> dict[str, Any]:
        """Project bounded, de-duplicated canonical events. No invented progress."""
        _safe_id(project_id, "project id")
        strategy_case: dict[str, str] = {
            _safe_text(strategy.get("repair_case_id"), 180): _safe_text(
                strategy.get("repair_strategy_id"), 180
            )
            for strategy, _case, _index in self._plan_rows(project_id)
        }
        seen: set[tuple[str, str]] = set()
        events: list[BobaRepairPlanReviewEventV1] = []
        truncated_at_source = False
        for source_id in (
            "validator_runner",
            "artifact_inspector",
            "report_reader",
            "final_decision_bus",
            "workflow_controller",
            "tool_recovery",
            "code_surgeon",
            "repair_planner",
        ):
            payload = self._source_payload(source_id, project_id)
            rows = payload.get("events")
            if not isinstance(rows, list):
                continue
            if len(rows) > _MAX_EVENTS:
                truncated_at_source = True
            for row in rows[-_MAX_EVENTS:]:
                if not isinstance(row, Mapping):
                    continue
                safe = _as_mapping(_safe_payload(row))
                event_id = _safe_text(
                    safe.get("event_id") or safe.get("id"), 180
                ) or _stable_id("repair_plan_event", source_id, _digest(safe))
                key = (source_id, event_id)
                if key in seen:
                    continue
                seen.add(key)
                raw_sequence = safe.get("sequence")
                sequence = (
                    raw_sequence
                    if isinstance(raw_sequence, int) and raw_sequence >= 0
                    else None
                )
                if sequence is not None and sequence <= after_sequence:
                    continue
                raw_current = safe.get("progress_current")
                raw_total = safe.get("progress_total")
                current = (
                    raw_current if isinstance(raw_current, int) and raw_current >= 0 else None
                )
                total = raw_total if isinstance(raw_total, int) and raw_total > 0 else None
                event_type = _safe_text(safe.get("event_type") or "canonical_event", 160)
                raw_message = safe.get("technical_message") or safe.get("message")
                withheld = source_holds_command(raw_message)
                technical = bounded_excerpt(
                    raw_message, maximum=MAX_STEP_DESCRIPTION_CHARS
                )
                repair_plan_id = _safe_text(safe.get("repair_strategy_id"), 180) or (
                    strategy_case.get(_safe_text(safe.get("repair_case_id"), 180), "")
                )
                events.append(
                    BobaRepairPlanReviewEventV1(
                        event_id=_stable_id("repair_plan_event", source_id, event_id),
                        project_id=project_id,
                        repair_plan_id=repair_plan_id or None,
                        source_module_id=source_id,
                        source_event_id=event_id,
                        source_sequence=sequence,
                        created_at=_safe_text(
                            safe.get("created_at") or safe.get("occurred_at"), 80
                        )
                        or None,
                        event_type=event_type,
                        severity=_safe_text(safe.get("severity") or "informational", 80),
                        technical_message=COMMAND_WITHHELD_NOTICE
                        if withheld
                        else technical["text"],
                        easy_message=bounded_easy_explanation(
                            safe.get("easy_message") or safe.get("summary")
                        ),
                        confirmed_fact=_safe_text(safe.get("confirmed_fact"), 900),
                        assessment=_safe_text(safe.get("assessment"), 900),
                        progress_current=current,
                        progress_total=total,
                        progress_percent=(
                            min(100.0, round(current / total * 100, 4))
                            if current is not None and total
                            else None
                        ),
                        requires_attention=bool(safe.get("requires_attention")),
                        canonical=True,
                        replayed=bool(safe.get("replayed")),
                        represents_work=event_type
                        not in {
                            "heartbeat",
                            "keepalive",
                            "ping",
                            "stream_open",
                            "stream_idle",
                        },
                        command_withheld=withheld,
                        sensitive_values_redacted=bool(
                            technical["sensitive_values_redacted"]
                        ),
                        private_paths_redacted=withheld
                        or bool(technical["private_paths_redacted"]),
                    )
                )
        events.sort(
            key=lambda item: (
                item.created_at or "",
                item.source_module_id,
                item.source_sequence or 0,
                item.event_id,
            )
        )
        bounded = events[-max(1, min(limit, _MAX_EVENTS)) :]
        return {
            "schema_version": "boba_repair_plan_review_events_v1",
            "project_id": project_id,
            "events": [item.model_dump(mode="json") for item in bounded],
            "has_more": len(events) > len(bounded) or truncated_at_source,
            "latest_sequence": max(
                (item.source_sequence or 0 for item in bounded), default=after_sequence
            ),
        }

    def inspect_repair_plan_timeline(
        self, project_id: str, *, limit: int = MAX_TIMELINE_ENTRIES
    ) -> dict[str, Any]:
        events = self.inspect_repair_plan_events(project_id, limit=limit)["events"]
        entries = [
            BobaRepairPlanReviewTimelineEntryV1(
                timeline_entry_id=_stable_id(
                    "repair_plan_timeline", str(event["event_id"])
                ),
                project_id=project_id,
                repair_plan_id=event.get("repair_plan_id"),
                source_module_id=str(event["source_module_id"]),
                source_record_id=str(event.get("source_event_id") or event["event_id"]),
                source_event_id=event.get("source_event_id"),
                event_type=str(event["event_type"]),
                occurred_at=event.get("created_at"),
                timestamp_precision="source" if event.get("created_at") else "unknown",
                sequence=event.get("source_sequence"),
                confirmed_order=event.get("source_sequence") is not None,
                title=str(event["event_type"]).replace("_", " ").title()
                or "Canonical Event",
                bounded_summary=str(event.get("easy_message") or ""),
                severity=str(event.get("severity") or "informational"),
                current=not bool(event.get("replayed")),
                historical=bool(event.get("replayed")),
            ).model_dump(mode="json")
            for event in events
        ]
        return {
            "schema_version": "boba_repair_plan_review_timeline_v1",
            "project_id": project_id,
            "entries": entries[:MAX_TIMELINE_ENTRIES],
            "limitations": [
                "Entry order follows the owner's own timestamps and sequence "
                "numbers; where a source records neither, the order is not "
                "confirmed.",
            ],
        }

    # ------------------------------------------------------------------
    # Signal usage, aggregate build, export and reset
    # ------------------------------------------------------------------
    def _signal_usage(self, project_id: str) -> BobaRepairPlanReviewSignalUsageV1:
        def present(source_id: str) -> bool:
            return bool(self._source_payload(source_id, project_id))

        return BobaRepairPlanReviewSignalUsageV1(
            canonical_repair_planner_records=present("repair_planner"),
            canonical_root_cause_records=present("root_cause_analyzer"),
            canonical_error_doctor_records=present("error_doctor"),
            canonical_observer_records=present("observer"),
            canonical_code_surgeon_records=present("code_surgeon"),
            canonical_tool_recovery_records=present("tool_recovery"),
            canonical_validator_records=present("validator_runner"),
            canonical_report_reader_records=present("report_reader"),
            canonical_artifact_records=present("artifact_inspector"),
            canonical_output_quality_records=present("output_quality_reviewer"),
            canonical_workflow_records=present("workflow_controller"),
            canonical_safety_records=present("safety_gate"),
            canonical_final_decision_records=present("final_decision_bus"),
            unavailable_signals=[
                source_id
                for source_id in build_fixed_repair_source_registry()
                if not present(source_id)
            ],
            limitations=[
                "Signal usage records which canonical owners were read, not who "
                "planned or decided anything.",
                "No flag here means the panel acted; every write flag is pinned "
                "false by contract.",
            ],
        )

    def build_repair_plan_review(self, project_id: str) -> dict[str, Any]:
        registry = self.build_repair_plan_review_registry(project_id)
        references = self.build_repair_plan_references(project_id)
        items = [
            self._queue_item(project_id, reference, index)
            for index, reference in enumerate(references)
        ]
        items.sort(key=lambda item: (item.priority_tier, item.deterministic_sort_key))
        events = self.inspect_repair_plan_events(project_id)
        notifications = [
            BobaRepairPlanReviewNotificationV1(
                notification_id=_stable_id(
                    "repair_plan_notification", project_id, item.repair_plan_id
                ),
                project_id=project_id,
                repair_plan_id=item.repair_plan_id,
                source_module_id="repair_planner",
                source_record_id=item.repair_plan_id,
                notification_type=(
                    "blocking"
                    if item.blocker_count
                    else "conflict"
                    if item.conflict_count
                    else "failed_recovery"
                    if item.failed_recovery_attempt_count
                    else "missing_approval"
                    if item.missing_approval_count
                    else "warning"
                ),
                severity="critical" if item.blocker_count else "warning",
                title=item.title,
                bounded_message=item.bounded_summary or item.priority_reason,
                requires_attention=True,
                human_action_required=item.human_action_required,
                current=item.current,
                limitations=[
                    "Acknowledging this notice does not approve, reject, revise or "
                    "execute the repair plan.",
                ],
            )
            for item in items
            if item.blocker_count
            or item.conflict_count
            or item.failed_recovery_attempt_count
            or item.missing_approval_count
            or item.warning_count
        ][:64]
        summary = BobaRepairPlanReviewSummaryV1(
            total_plan_count=len(items),
            current_plan_count=sum(1 for item in items if item.current),
            stale_plan_count=sum(1 for item in items if item.stale),
            historical_plan_count=sum(1 for item in items if item.historical),
            superseded_plan_count=sum(1 for item in items if item.superseded),
            completed_plan_count=sum(1 for item in items if item.completed),
            destructive_plan_count=sum(1 for item in items if item.destructive),
            reversible_plan_count=sum(1 for item in items if item.reversible),
            code_change_plan_count=sum(1 for item in items if item.requires_code_change),
            artifact_change_plan_count=sum(
                1 for item in items if item.requires_artifact_change
            ),
            workflow_change_plan_count=sum(
                1 for item in items if item.requires_workflow_transition
            ),
            checkpoint_restore_plan_count=sum(
                1 for item in items if item.requires_checkpoint_restore
            ),
            process_restart_plan_count=sum(
                1 for item in items if item.requires_process_restart
            ),
            tool_execution_plan_count=sum(
                1 for item in items if item.requires_tool_execution
            ),
            plans_requiring_human_review_count=sum(
                1 for item in items if item.human_action_required
            ),
            plans_missing_approval_count=sum(
                1 for item in items if item.missing_approval_count > 0
            ),
            plans_missing_verification_count=sum(
                1 for item in items if item.missing_verification_count > 0
            ),
            plans_with_failed_recovery_count=sum(
                1 for item in items if item.failed_recovery_attempt_count > 0
            ),
            command_bearing_step_count=sum(
                item.command_bearing_step_count for item in items
            ),
            missing_evidence_count=sum(item.missing_evidence_count for item in items),
            conflict_count=sum(item.conflict_count for item in items),
            safest_next_review_action=(
                "Read the highest-priority repair plan, its proposed steps and its "
                "canonical evidence before any owner is asked to act."
                if items
                else "No repair-plan review work is outstanding."
            ),
            required_human_actions=[
                f"{item.repair_plan_id}: {item.priority_reason}"
                for item in items
                if item.human_action_required
            ][:24],
            limitations=[
                "Counts describe projected canonical records, not panel decisions.",
                "A completed plan is not a verified plan.",
                "A reversible plan is not a risk-free plan.",
            ],
        )
        result = BobaRepairPlanReviewSetV1(
            project_id=project_id,
            source_id=_safe_text(
                self._source_payload("repair_planner", project_id).get("source_id"), 512
            ),
            registry_snapshots=[
                BobaRepairPlanRegistrySnapshotV1.model_validate(
                    registry["registry_snapshot"]
                )
            ],
            repair_plan_references=references,
            repair_plan_queue_items=items,
            events=[
                BobaRepairPlanReviewEventV1.model_validate(item)
                for item in events["events"]
            ],
            notifications=notifications,
            review_summary=summary,
            signal_usage=self._signal_usage(project_id),
            limitations=[
                "Repair Plan Panel V1 is a read-only repair-plan projection, an "
                "evidence workspace, a plan-comparison surface, an "
                "approval-requirement viewer, a recovery-history viewer and a safe "
                "canonical action router. It does not generate a repair plan, "
                "revise one, approve or reject one, or execute a plan or a step.",
                "Repair Planner proposed every plan shown here. The panel never "
                "states that a plan is the correct repair.",
                "Reversible does not mean risk-free, and an available rollback is "
                "not a guaranteed rollback.",
                "Owner-reported success is not independent verification, and "
                "recovered is not resolved.",
                COMMAND_WITHHELD_NOTICE,
                PRIVATE_PATH_NOTICE,
                NOT_EXECUTABLE_NOTICE,
                SOURCE_RETAINED_NOTICE,
            ],
        )
        self.store.save_boba_repair_plan_review(project_id, result.model_dump(mode="json"))
        return result.model_dump(mode="json")

    def load_repair_plan_review(self, project_id: str) -> dict[str, Any] | None:
        _safe_id(project_id, "project id")
        return self.store.load_boba_repair_plan_review(project_id)

    def export_repair_plan_review(
        self, project_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "boba_repair_plan_review_export_v1",
            "project_id": project_id,
            "exported_at": now_iso(),
            "queue": self.build_repair_plan_queue(project_id, limit=MAX_QUEUE_PAGE_SIZE),
            "timeline": self.inspect_repair_plan_timeline(project_id, limit=50),
            "privacy": {
                "raw_commands_excluded": True,
                "command_arguments_excluded": True,
                "shell_text_excluded": True,
                "rollback_step_text_excluded": True,
                "step_target_excluded": True,
                "private_paths_excluded": True,
                "sensitive_values_excluded": True,
                "raw_logs_excluded": True,
                "raw_patches_excluded": True,
                "source_code_excluded": True,
                "raw_media_excluded": True,
                "source_records_duplicated": False,
                "plan_text_rewritten": False,
                "plan_created": False,
                "plan_revised": False,
                "plan_approved": False,
                "plan_rejected": False,
                "plan_executed": False,
                "step_executed": False,
                "recovery_executed": False,
                "checkpoint_restored": False,
                "process_restarted": False,
                "workflow_changed": False,
                "code_modified": False,
                "artifact_modified": False,
                "source_media_modified": False,
                "accepted_output_modified": False,
                "upload_used": False,
                "publication_used": False,
            },
        }
        if session_id:
            payload["session"] = self.get_repair_plan_review_session(
                project_id, session_id
            ).model_dump(mode="json")
        return _as_mapping(_safe_payload(payload))

    def reset_repair_plan_review_metadata(
        self, project_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        if session_id:
            _safe_id(session_id, "repair plan review session id")
            removed = self.store.delete_boba_repair_plan_review_session(
                project_id, session_id
            )
            return {
                "schema_version": "boba_repair_plan_review_reset_v1",
                "project_id": project_id,
                "session_removed": removed,
                "repair_plan_records_preserved": True,
                "repair_case_records_preserved": True,
                "risk_assessment_records_preserved": True,
                "approval_gate_records_preserved": True,
                "rollback_plan_records_preserved": True,
                "checkpoint_plan_records_preserved": True,
                "validation_plan_records_preserved": True,
                "root_cause_records_preserved": True,
                "incident_records_preserved": True,
                "recovery_history_preserved": True,
                "code_repair_history_preserved": True,
                "validator_history_preserved": True,
                "artifact_history_preserved": True,
                "workflow_history_preserved": True,
                "review_ui_history_preserved": True,
                "action_receipt_history_preserved": True,
            }
        return self.store.reset_boba_repair_plan_review_metadata(project_id)

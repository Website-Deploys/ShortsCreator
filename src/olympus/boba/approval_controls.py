"""BOBA Approval / Reject Buttons V1 - eligibility and truthful decision presentation.

This module is an **interaction layer**, not an approval authority. It does not
create a second approval system, a second decision path or a second store model
for decisions.

Canonical ownership is unchanged:

    Review UI action chain  -> owns request identity, digests, expiry,
                               staleness validation, idempotency and the
                               immutable receipt
    Workflow Controller     -> owns the human decision record and the revision
    Safety Gate             -> owns safety authorisation
    Final Decision Bus      -> owns final action authorisation
    Autopilot / owners      -> own execution

What this module adds:

1. A read-only *eligibility* projection that derives, from the canonical owner
   registries, which approve/reject decisions are genuinely offered for an exact
   target, and why the others are not.
2. A truthful *button state* for each decision.
3. A receipt projection that keeps four things apart that are easy to conflate:
   the user's decision, the owner's decision, the Safety decision and the
   execution result.

An approval receipt is never an execution receipt. A rejection receipt is never
an error receipt. Approving something does not execute it, advance a workflow,
grant Safety authorisation, restore a checkpoint, modify code, artifacts or
media, run a command, upload or publish.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import Field, model_validator

from olympus.boba.contracts import BobaContract, now_iso
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
    build_fixed_review_action_registry,
)
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from olympus.boba.integration import BobaIntegration


MAX_ELIGIBILITY_ROWS = 32
MAX_HISTORY_ROWS = 100
MAX_TIMELINE_ENTRIES = 100
MAX_COMPARISON_DECISIONS = 4
MAX_EVENTS = 100
MAX_REASON_LENGTH = 500
MAX_WARNINGS = 24

# The decision values the Workflow Controller's human-decision vocabulary
# actually accepts, transcribed from the Review UI action registry.
APPROVE_DECISION = "approve"
REJECT_DECISION = "reject"
REQUEST_REVISION_DECISION = "request_revision"

# Shell and command detection, so a bounded reason can never smuggle a command.
_SHELL_TOKEN = re.compile(r"(?:\|\||&&|[|><;`]|\$\(|\r|\n)")
_COMMAND_EXECUTABLE = re.compile(
    r"(?i)(?:^|[\s\"'])(?:ffmpeg|ffprobe|git|python3?|pip3?|npm|npx|yarn|pnpm|node|"
    r"bash|sh|zsh|powershell|pwsh|cmd|docker|apt|apt-get|brew|curl|wget|make|"
    r"systemctl|kill|pkill|rm|mv|cp|chmod|chown|sudo|ssh|scp|rsync)\b"
)
_URL = re.compile(r"(?i)\b(?:https?|ftp|file)://")
_UNC_PATH = re.compile(r"\\\\[^\s\\]+")
_TRAVERSAL = re.compile(r"\.\./|\.\.\\")

NOT_EXECUTION_NOTICE = (
    "This records a human decision only. It does not execute anything."
)
NOT_SAFETY_NOTICE = (
    "This does not grant Safety Gate approval; Safety Gate remains authoritative."
)
NOT_WORKFLOW_NOTICE = (
    "This does not advance the workflow; the Workflow Controller owns transitions."
)
STALE_NOTICE = (
    "The reviewed state changed after this control was displayed. Refresh and "
    "read the current state before deciding again."
)
REJECTION_NOTICE = (
    "A rejection is an explicit recorded human decision. It deletes nothing, "
    "rolls nothing back and changes no artifact."
)

ApprovalButtonState = Literal[
    "approve_available",
    "reject_available",
    "pending",
    "approved",
    "rejected",
    "expired",
    "invalidated",
    "blocked",
    "requires_review",
    "unavailable",
]

ApprovalDecisionKind = Literal["approve", "reject", "request_revision"]

ApprovalIneligibilityReason = Literal[
    "no_canonical_operation",
    "action_not_available_in_v1",
    "target_type_not_supported",
    "no_workflow_run_bound",
    "advisory_only_not_authoritative",
    "already_decided",
    "expired",
    "safety_gate_blocked",
    "rights_unknown_or_blocked",
    "evidence_missing",
    "owner_unavailable",
    "eligible",
]


def _contains_unsafe_text(value: str) -> str | None:
    """Return a refusal reason when a bounded reason carries unsafe material."""
    if _SENSITIVE_KEY.search(value):
        return "a credential-like token"
    if _SHELL_TOKEN.search(value) or _COMMAND_EXECUTABLE.search(value):
        return "executable command text"
    if _URL.search(value):
        return "an external URL"
    if _PRIVATE_PATH.search(value) or _UNC_PATH.search(value):
        return "a private filesystem path"
    if _TRAVERSAL.search(value):
        return "a path traversal sequence"
    return None


def bounded_reason(value: object, maximum: int = MAX_REASON_LENGTH) -> str:
    """Bound a reviewer reason, refusing unsafe material outright.

    The raw input is validated *before* sanitisation on purpose. ``_safe_text``
    redacts private paths, and in doing so it rewrites ``https://`` into
    ``http[private-path]/`` because ``[A-Za-z]:[\\/]`` matches ``s:/``. Checking
    the sanitised text would therefore silently accept the very material this
    refuses. Validate what the caller actually sent, then bound it.
    """
    raw = "" if value is None else str(value)
    if not raw.strip():
        return ""
    unsafe = _contains_unsafe_text(raw)
    if unsafe:
        raise ValidationError(f"A decision reason cannot contain {unsafe}.")
    text = _safe_text(raw, maximum)
    if _contains_unsafe_text(text):
        raise ValidationError("A decision reason cannot contain unsafe material.")
    return text


# ----------------------------------------------------------------------
# Contracts
# ----------------------------------------------------------------------
class BobaApprovalControlRegistrySnapshotV1(BobaContract):
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso)
    decision_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    available_decision_action_ids: list[str] = Field(default_factory=list, max_length=32)
    unavailable_decision_action_ids: list[str] = Field(default_factory=list, max_length=32)
    supported_decision_values: list[str] = Field(default_factory=list, max_length=16)
    supported_target_types: list[str] = Field(default_factory=list, max_length=32)
    owning_module_ids: list[str] = Field(default_factory=list, max_length=16)
    registry_digest: str = Field(min_length=64, max_length=64)
    immutable: Literal[True] = True
    # The interaction layer owns no authority of its own.
    creates_approval_authority: Literal[False] = False
    creates_second_decision_path: Literal[False] = False
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaApprovalEligibilityV1(BobaContract):
    eligibility_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    target_type: str = Field(min_length=1, max_length=80)
    target_id: str = Field(default="", max_length=180)
    action_descriptor_id: str = Field(min_length=1, max_length=180)
    owning_module_id: str = Field(min_length=1, max_length=180)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    decision_kind: ApprovalDecisionKind
    button_state: ApprovalButtonState
    eligible: bool = False
    reason_code: ApprovalIneligibilityReason = "no_canonical_operation"
    bounded_explanation: str = Field(default="", max_length=900)
    requires_reason: bool = True
    requires_confirmation: bool = True
    requires_workflow_revision: bool = False
    requires_target_digest: bool = False
    authoritative_for_owner: bool = False
    # Nothing here is ever an execution or authorisation grant.
    grants_execution: Literal[False] = False
    grants_safety_approval: Literal[False] = False
    grants_rights_approval: Literal[False] = False
    advances_workflow: Literal[False] = False
    warnings: list[str] = Field(default_factory=list, max_length=MAX_WARNINGS)
    limitations: list[str] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_eligibility_reason(self) -> BobaApprovalEligibilityV1:
        if self.eligible and self.reason_code != "eligible":
            raise ValueError("An eligible decision must carry the eligible reason code.")
        if not self.eligible and self.reason_code == "eligible":
            raise ValueError("An ineligible decision cannot carry the eligible reason code.")
        if self.eligible and self.button_state not in {
            "approve_available",
            "reject_available",
            "requires_review",
        }:
            raise ValueError("An eligible decision must expose an actionable state.")
        return self


class BobaApprovalControlSnapshotV1(BobaContract):
    approval_control_snapshot_id: str = Field(min_length=1, max_length=180)
    review_session_id: str = Field(min_length=1, max_length=180)
    review_snapshot_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    target_type: str = Field(min_length=1, max_length=80)
    target_id: str = Field(default="", max_length=180)
    created_at: str = Field(default_factory=now_iso)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    target_digest: str = Field(min_length=64, max_length=64)
    safety_record_digest: str = Field(min_length=64, max_length=64)
    final_decision_record_digest: str = Field(min_length=64, max_length=64)
    eligibility_ids: list[str] = Field(default_factory=list, max_length=MAX_ELIGIBILITY_ROWS)
    eligible_decision_kinds: list[str] = Field(default_factory=list, max_length=8)
    safety_status: str = Field(default="unavailable", max_length=120)
    rights_status: str = Field(default="unavailable", max_length=120)
    validation_status: str = Field(default="unavailable", max_length=120)
    quality_status: str = Field(default="unavailable", max_length=120)
    checkpoint_status: str = Field(default="unavailable", max_length=120)
    budget_status: str = Field(default="unavailable", max_length=120)
    workflow_status: str = Field(default="unavailable", max_length=120)
    expires_at: str | None = None
    already_decided: bool = False
    snapshot_digest: str = Field(min_length=64, max_length=64)
    confirmation_context_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=MAX_WARNINGS)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaApprovalDecisionReceiptV1(BobaContract):
    """Keeps the user decision, owner decision, Safety decision and execution apart."""

    approval_decision_receipt_id: str = Field(min_length=1, max_length=180)
    review_action_request_id: str = Field(min_length=1, max_length=180)
    review_action_receipt_id: str = Field(default="", max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    target_type: str = Field(min_length=1, max_length=80)
    target_id: str = Field(default="", max_length=180)
    decision_kind: ApprovalDecisionKind
    owning_module_id: str = Field(min_length=1, max_length=180)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    submitted_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None

    # 1. What the human chose.
    user_decision_recorded: bool = False
    user_decision_value: str = Field(default="", max_length=80)
    bounded_reason: str = Field(default="", max_length=MAX_REASON_LENGTH)

    # 2. What the canonical owner did with it.
    owner_accepted: bool = False
    canonical_record_id: str | None = None
    canonical_record_digest: str | None = None
    canonical_status: str = Field(default="pending", max_length=120)

    # 3. Safety remains separately owned.
    safety_decision_present: bool = False
    safety_decision_granted_here: Literal[False] = False

    # 4. Execution is a separate fact reported by a separate owner.
    execution_reported_by_owner: bool = False
    execution_owner_module_id: str | None = None

    # Truthful negative claims.
    workflow_advanced: bool = False
    checkpoint_restored: Literal[False] = False
    code_changed: Literal[False] = False
    artifact_changed: Literal[False] = False
    media_modified: Literal[False] = False
    upload_performed: Literal[False] = False
    publication_performed: Literal[False] = False

    stale_state_rejected: bool = False
    duplicate_request_reused: bool = False
    already_decided: bool = False
    error_code: str | None = None
    bounded_error_message: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=MAX_WARNINGS)
    limitations: list[str] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_decision_claims(self) -> BobaApprovalDecisionReceiptV1:
        if self.owner_accepted and not (
            self.canonical_record_id and self.canonical_record_digest
        ):
            raise ValueError(
                "An owner-accepted decision must name a canonical owner record and digest."
            )
        if self.execution_reported_by_owner and not self.execution_owner_module_id:
            raise ValueError(
                "Execution cannot be reported without naming the owning module."
            )
        if self.workflow_advanced and not self.canonical_record_id:
            raise ValueError(
                "A workflow advance cannot be claimed without a canonical owner record."
            )
        if self.user_decision_recorded and not self.user_decision_value:
            raise ValueError("A recorded user decision must name its decision value.")
        return self


class BobaApprovalControlEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    created_at: str = Field(default_factory=now_iso)
    event_type: Literal[
        "approval_requested",
        "approval_confirmed",
        "approval_rejected",
        "approval_denied",
        "approval_expired",
        "approval_stale",
        "approval_conflict",
        "rejection_submitted",
        "rejection_accepted",
        "request_already_decided",
    ]
    decision_kind: ApprovalDecisionKind | None = None
    target_type: str = Field(default="", max_length=80)
    target_id: str = Field(default="", max_length=180)
    review_action_request_id: str = Field(default="", max_length=180)
    owning_module_id: str = Field(default="", max_length=180)
    bounded_message: str = Field(default="", max_length=900)
    # An event never claims execution merely because a decision was recorded.
    claims_execution: Literal[False] = False
    claims_workflow_advance: Literal[False] = False
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaApprovalControlSignalUsageV1(BobaContract):
    canonical_review_ui_records: bool = False
    canonical_workflow_records: bool = False
    canonical_safety_records: bool = False
    canonical_final_decision_records: bool = False
    canonical_autopilot_records: bool = False
    canonical_output_quality_records: bool = False
    reuses_review_ui_action_chain: Literal[True] = True
    reuses_review_ui_idempotency: Literal[True] = True
    second_approval_authority_created: Literal[False] = False
    second_decision_path_created: Literal[False] = False
    second_database_created: Literal[False] = False
    second_idempotency_mechanism_created: Literal[False] = False
    optimistic_approval_shown: Literal[False] = False
    safety_gate_bypassed: Literal[False] = False
    rights_bypassed: Literal[False] = False
    budget_bypassed: Literal[False] = False
    validation_bypassed: Literal[False] = False
    execution_performed: Literal[False] = False
    repair_executed: Literal[False] = False
    recovery_executed: Literal[False] = False
    workflow_advanced_by_panel: Literal[False] = False
    checkpoint_restored: Literal[False] = False
    code_modified: Literal[False] = False
    artifact_modified: Literal[False] = False
    media_modified: Literal[False] = False
    command_execution_used: Literal[False] = False
    ffmpeg_execution_used: Literal[False] = False
    upload_used: Literal[False] = False
    publication_used: Literal[False] = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaApprovalControlSummaryV1(BobaContract):
    eligible_decision_count: int = Field(default=0, ge=0)
    ineligible_decision_count: int = Field(default=0, ge=0)
    approve_available: bool = False
    reject_available: bool = False
    blocked_count: int = Field(default=0, ge=0)
    already_decided_count: int = Field(default=0, ge=0)
    safest_next_review_action: str = Field(default="", max_length=700)
    required_human_actions: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaApprovalControlSetV1(BobaContract):
    schema_version: Literal["boba_approval_controls_v1"] = "boba_approval_controls_v1"
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso)
    registry_snapshots: list[BobaApprovalControlRegistrySnapshotV1] = Field(
        default_factory=list, max_length=8
    )
    eligibility_rows: list[BobaApprovalEligibilityV1] = Field(
        default_factory=list, max_length=MAX_ELIGIBILITY_ROWS
    )
    events: list[BobaApprovalControlEventV1] = Field(
        default_factory=list, max_length=MAX_EVENTS
    )
    control_summary: BobaApprovalControlSummaryV1
    signal_usage: BobaApprovalControlSignalUsageV1
    limitations: list[str] = Field(default_factory=list, max_length=32)


# ----------------------------------------------------------------------
# Fixed registry, derived from the canonical Review UI action registry
# ----------------------------------------------------------------------
def build_fixed_approval_decision_registry() -> dict[str, dict[str, Any]]:
    """Return the decision-capable subset of the canonical Review UI registry.

    A descriptor qualifies only when the canonical Review UI action registry
    already declares approve/reject-style decision values for it. Nothing is
    added, renamed or re-enabled here.
    """
    registry: dict[str, dict[str, Any]] = {}
    for descriptor in build_fixed_review_action_registry().values():
        values = list(descriptor.allowed_decision_values)
        if not values:
            continue
        approve_like = [
            value
            for value in values
            if value == APPROVE_DECISION
            or value.startswith("accept")
            or value.startswith("approve")
        ]
        reject_like = [
            value
            for value in values
            if value == REJECT_DECISION or value.startswith("reject") or value.startswith("deny")
        ]
        if not approve_like and not reject_like:
            continue
        registry[descriptor.action_descriptor_id] = {
            "action_descriptor_id": descriptor.action_descriptor_id,
            "action_class": descriptor.action_class,
            "owning_module_id": descriptor.owning_module_id,
            "owning_operation_id": descriptor.owning_operation_id,
            "supported_target_types": list(descriptor.supported_target_types),
            "allowed_decision_values": values,
            "approve_values": approve_like,
            "reject_values": reject_like,
            "requires_reason": bool(descriptor.requires_reason),
            "requires_confirmation": bool(descriptor.requires_confirmation),
            "requires_workflow_revision": bool(
                getattr(descriptor, "requires_workflow_revision", False)
            ),
            "requires_target_digest": bool(
                getattr(descriptor, "requires_target_digest", False)
            ),
            "allowed_in_v1": bool(descriptor.allowed_in_v1),
            "availability": descriptor.availability,
            "limitations": list(descriptor.limitations),
        }
    if not registry:
        raise ValidationError(
            "No canonical Review UI action declares approve or reject decision values."
        )
    return registry


def approval_button_states() -> tuple[str, ...]:
    """Return the truthful button states this layer can present."""
    return (
        "approve_available",
        "reject_available",
        "pending",
        "approved",
        "rejected",
        "expired",
        "invalidated",
        "blocked",
        "requires_review",
        "unavailable",
    )


class BobaApprovalTimelineEntryV1(BobaContract):
    """One read-only timeline entry.

    Owner facts are projected verbatim and kept separate from derived
    presentation, so a reader can always tell which is which. A timeline entry
    creates no authority and claims no execution.
    """

    timeline_entry_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    entry_kind: Literal["approval_control_event", "owner_decision_record"]
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)

    # Owner facts, exactly as the owning record stated them.
    owner_fact: Literal[True] = True
    event_type: str = Field(default="", max_length=160)
    decision_kind: str | None = None
    decision_value: str = Field(default="", max_length=80)
    target_type: str = Field(default="", max_length=80)
    target_id: str = Field(default="", max_length=180)
    owning_module_id: str = Field(default="", max_length=180)
    bounded_message: str = Field(default="", max_length=900)
    bounded_reason: str = Field(default="", max_length=MAX_REASON_LENGTH)
    workflow_revision: int | None = None
    sequence: int | None = None
    occurred_at: str | None = None
    timestamp_precision: Literal["source", "unknown"] = "unknown"
    confirmed_order: bool = False

    # Derived presentation, clearly separated from the facts above.
    derived_title: str = Field(default="", max_length=240)
    derived_summary: str = Field(default="", max_length=900)

    # A timeline entry never asserts a side effect.
    claims_execution: Literal[False] = False
    claims_workflow_advance: Literal[False] = False
    claims_safety_approval: Literal[False] = False
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaApprovalDecisionComparisonV1(BobaContract):
    """A read-only, side-by-side comparison of existing decisions.

    No winner is selected, no best decision is inferred, and no authority
    changes. When the decisions refer to incompatible targets the comparison
    reports that truthfully rather than inventing equivalence.
    """

    comparison_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    review_action_request_ids: list[str] = Field(
        min_length=2, max_length=MAX_COMPARISON_DECISIONS
    )
    created_at: str = Field(default_factory=now_iso)

    compatible: bool = False
    incompatibility_reason: str = Field(default="", max_length=900)
    same_target_type: bool = False
    same_target_id: bool = False

    # Owner facts per decision, projected verbatim.
    owner_fact_rows: list[dict[str, Any]] = Field(
        default_factory=list, max_length=MAX_COMPARISON_DECISIONS
    )
    # Derived presentation, kept separate from the facts above.
    presentation_rows: list[dict[str, Any]] = Field(
        default_factory=list, max_length=MAX_COMPARISON_DECISIONS
    )
    differing_fields: list[str] = Field(default_factory=list, max_length=32)
    decision_kinds: list[str] = Field(default_factory=list, max_length=8)
    canonical_statuses: list[str] = Field(default_factory=list, max_length=8)

    # Pinned negatives.
    no_automatic_winner: Literal[True] = True
    no_best_decision_inferred: Literal[True] = True
    authority_changed: Literal[False] = False
    mutation_performed: Literal[False] = False
    approval_created: Literal[False] = False
    safety_overridden: Literal[False] = False

    bounded_summary: str = Field(default="", max_length=900)
    limitations: list[str] = Field(default_factory=list, max_length=16)


# ----------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------
class BobaApprovalControlsV1:
    """Eligibility and truthful presentation over the canonical Review UI chain."""

    def __init__(self, store: BobaMemoryStore, integration: BobaIntegration) -> None:
        self.store = store
        self.integration = integration

    # ------------------------------------------------------------------
    # Canonical source access
    # ------------------------------------------------------------------
    _LOADERS: ClassVar[dict[str, str]] = {
        "review_ui": "load_boba_review_ui",
        "workflow_controller": "load_boba_workflow_controller",
        "safety_gate": "load_boba_safety_gate",
        "final_decision_bus": "load_boba_final_decision_bus",
        "autopilot_controller": "load_boba_autopilot_controller",
        "output_quality_reviewer": "load_boba_output_quality_reviewer",
        "validator_runner": "load_boba_validator_runner",
        "artifact_inspector": "load_boba_artifact_inspector",
    }

    def _source_payload(self, module_id: str, project_id: str) -> dict[str, Any]:
        loader_name = self._LOADERS.get(module_id)
        if loader_name is None:
            raise ValidationError("Unknown BOBA approval control source module.")
        loader = getattr(self.store, loader_name, None)
        if loader is None:
            return {}
        try:
            return _as_mapping(loader(project_id))
        except (ValidationError, NotFoundError, OSError):
            return {}

    def _workflow_run(self, project_id: str) -> dict[str, Any]:
        return _active_workflow_run(self._source_payload("workflow_controller", project_id))

    def _workflow_revision(self, project_id: str) -> int:
        revision = self._workflow_run(project_id).get("revision")
        return revision if isinstance(revision, int) and revision >= 0 else 0

    def _project_snapshot_digest(self, project_id: str) -> str:
        return _digest(
            {
                module_id: _digest(_safe_payload(self._source_payload(module_id, project_id)))
                for module_id in self._LOADERS
            }
        )

    def _target_digest(self, project_id: str, target_type: str, target_id: str) -> str:
        """Digest the exact target so a changed target invalidates the decision."""
        run = self._workflow_run(project_id)
        return _digest(
            {
                "target_type": target_type,
                "target_id": target_id,
                "workflow_run_id": _safe_text(run.get("workflow_run_id"), 180),
                "workflow_revision": self._workflow_revision(project_id),
                "stage": _safe_text(run.get("current_stage_instance_id"), 180),
                "workflow": _safe_payload(run),
            }
        )

    def _safety_record_digest(self, project_id: str) -> str:
        return _digest(_safe_payload(self._source_payload("safety_gate", project_id)))

    def _final_decision_record_digest(self, project_id: str) -> str:
        return _digest(_safe_payload(self._source_payload("final_decision_bus", project_id)))

    # ------------------------------------------------------------------
    # Owner-reported gate states (never invented, never overridden)
    # ------------------------------------------------------------------
    def _latest(self, project_id: str, module_id: str, key: str) -> dict[str, Any]:
        rows = self._source_payload(module_id, project_id).get(key)
        if not isinstance(rows, list) or not rows:
            return {}
        last = rows[-1]
        return _as_mapping(last) if isinstance(last, Mapping) else {}

    def _safety_status(self, project_id: str) -> str:
        decision = self._latest(project_id, "safety_gate", "safety_decisions")
        if not decision:
            return "unavailable"
        return _safe_text(decision.get("outcome") or decision.get("decision") or "recorded", 120)

    def _rights_status(self, project_id: str) -> str:
        review = self._latest(project_id, "safety_gate", "rights_reviews")
        if not review:
            return "unavailable"
        return _safe_text(review.get("rights_status") or "recorded", 120)

    def _validation_status(self, project_id: str) -> str:
        decision = self._latest(project_id, "validator_runner", "suite_decisions")
        if not decision:
            return "unavailable"
        return _safe_text(decision.get("outcome") or decision.get("status") or "recorded", 120)

    def _quality_status(self, project_id: str) -> str:
        decision = self._latest(
            project_id, "output_quality_reviewer", "acceptance_decisions"
        )
        if not decision:
            return "unavailable"
        return _safe_text(decision.get("decision") or "recorded", 120)

    def _checkpoint_status(self, project_id: str) -> str:
        review = self._latest(project_id, "safety_gate", "checkpoint_reviews")
        if not review:
            return "unavailable"
        return _safe_text(review.get("checkpoint_status") or "recorded", 120)

    def _budget_status(self, project_id: str) -> str:
        run = self._latest(project_id, "autopilot_controller", "runs")
        if not run:
            return "unavailable"
        return _safe_text(run.get("budget_status") or run.get("status") or "recorded", 120)

    def _workflow_status(self, project_id: str) -> str:
        run = self._workflow_run(project_id)
        return _safe_text(run.get("status") or "unavailable", 120) if run else "unavailable"

    def _safety_blocks(self, project_id: str) -> bool:
        """True when the owner's own latest Safety decision denies action."""
        status = self._safety_status(project_id).lower()
        return any(token in status for token in ("den", "block", "refus", "reject"))

    def _rights_blocks(self, project_id: str) -> bool:
        status = self._rights_status(project_id).lower()
        if status == "unavailable":
            return True
        return any(token in status for token in ("block", "unknown", "den", "unclear"))

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def build_approval_control_registry(self, project_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        registry = build_fixed_approval_decision_registry()
        rows = list(registry.values())
        payload = {"decisions": rows, "states": list(approval_button_states())}
        snapshot_id = _stable_id("approval_control_registry", "v1", _digest(payload))
        stored = self.store.load_boba_approval_control_registry(project_id, snapshot_id)
        snapshot = (
            BobaApprovalControlRegistrySnapshotV1.model_validate(stored)
            if isinstance(stored, Mapping)
            else BobaApprovalControlRegistrySnapshotV1(
                registry_snapshot_id=snapshot_id,
                decision_action_descriptor_ids=list(registry),
                available_decision_action_ids=[
                    key
                    for key, row in registry.items()
                    if row["allowed_in_v1"] and row["availability"] == "available"
                ],
                unavailable_decision_action_ids=[
                    key
                    for key, row in registry.items()
                    if not row["allowed_in_v1"] or row["availability"] != "available"
                ],
                supported_decision_values=sorted(
                    {v for row in rows for v in row["allowed_decision_values"]}
                ),
                supported_target_types=sorted(
                    {t for row in rows for t in row["supported_target_types"]}
                ),
                owning_module_ids=sorted({row["owning_module_id"] for row in rows}),
                registry_digest=_digest(payload),
                limitations=[
                    "This registry is the decision-capable subset of the canonical "
                    "Review UI action registry. It adds no action and re-enables none.",
                    "An action the Review UI marks unavailable stays unavailable here.",
                    NOT_EXECUTION_NOTICE,
                    NOT_SAFETY_NOTICE,
                    NOT_WORKFLOW_NOTICE,
                ],
            )
        )
        if not isinstance(stored, Mapping):
            self.store.save_boba_approval_control_registry(
                project_id, snapshot_id, snapshot.model_dump(mode="json")
            )
        return {
            "registry_snapshot": snapshot.model_dump(mode="json"),
            "decisions": rows,
            "button_states": list(approval_button_states()),
            "notices": {
                "not_execution": NOT_EXECUTION_NOTICE,
                "not_safety": NOT_SAFETY_NOTICE,
                "not_workflow": NOT_WORKFLOW_NOTICE,
                "stale": STALE_NOTICE,
                "rejection": REJECTION_NOTICE,
            },
        }

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    def inspect_approval_eligibility(
        self, project_id: str, target_type: str, target_id: str = ""
    ) -> list[BobaApprovalEligibilityV1]:
        """Derive, per canonical descriptor, whether approve/reject is offered."""
        _safe_id(project_id, "project id")
        if target_id:
            _safe_id(target_id, "target id")
        registry = build_fixed_approval_decision_registry()
        run = self._workflow_run(project_id)
        run_bound = bool(_safe_text(run.get("workflow_run_id"), 180))
        safety_blocked = self._safety_blocks(project_id)
        rights_blocked = self._rights_blocks(project_id)
        decided = self._already_decided(project_id, target_type, target_id)
        rows: list[BobaApprovalEligibilityV1] = []

        for row in registry.values():
            for kind, values in (
                ("approve", row["approve_values"]),
                ("reject", row["reject_values"]),
            ):
                if not values:
                    continue
                state: ApprovalButtonState = "unavailable"
                reason: ApprovalIneligibilityReason = "no_canonical_operation"
                eligible = False
                explanation = ""
                warnings: list[str] = []

                if not row["allowed_in_v1"] or row["availability"] != "available":
                    reason = "action_not_available_in_v1"
                    explanation = (
                        f"The canonical Review UI action "
                        f"{row['action_descriptor_id']} is marked "
                        f"{row['availability']} and allowed_in_v1="
                        f"{row['allowed_in_v1']} by its owner. This layer does not "
                        "re-enable an action its owner disabled."
                    )
                elif target_type not in row["supported_target_types"]:
                    reason = "target_type_not_supported"
                    explanation = (
                        f"The owner supports target types "
                        f"{row['supported_target_types']}, not '{target_type}'."
                    )
                elif row["requires_workflow_revision"] and not run_bound:
                    reason = "no_workflow_run_bound"
                    explanation = (
                        "The owner requires an exact workflow run and revision, and "
                        "no active workflow run is bound to this project."
                    )
                elif decided:
                    state = "approved" if decided == "approve" else "rejected"
                    reason = "already_decided"
                    explanation = (
                        f"A human decision '{decided}' is already recorded for this "
                        "exact target. The existing canonical decision is returned "
                        "instead of a new one."
                    )
                elif kind == "approve" and safety_blocked:
                    state = "blocked"
                    reason = "safety_gate_blocked"
                    explanation = (
                        f"Safety Gate's own latest decision is "
                        f"'{self._safety_status(project_id)}'. Approving here cannot "
                        "override it."
                    )
                    warnings.append(NOT_SAFETY_NOTICE)
                elif kind == "approve" and rights_blocked:
                    state = "blocked"
                    reason = "rights_unknown_or_blocked"
                    explanation = (
                        f"Rights status is '{self._rights_status(project_id)}'. An "
                        "action requiring rights cannot be approved while rights are "
                        "unknown or blocked."
                    )
                else:
                    eligible = True
                    reason = "eligible"
                    state = "approve_available" if kind == "approve" else "reject_available"
                    explanation = (
                        f"{row['owning_module_id']}.{row['owning_operation_id']} "
                        f"accepts {values} for target type '{target_type}'."
                    )

                rows.append(
                    BobaApprovalEligibilityV1(
                        eligibility_id=_stable_id(
                            "approval_eligibility",
                            project_id,
                            target_type,
                            target_id,
                            row["action_descriptor_id"],
                            kind,
                        ),
                        project_id=project_id,
                        target_type=target_type,
                        target_id=target_id,
                        action_descriptor_id=row["action_descriptor_id"],
                        owning_module_id=row["owning_module_id"],
                        owning_operation_id=row["owning_operation_id"],
                        decision_kind=kind,
                        button_state=state,
                        eligible=eligible,
                        reason_code=reason,
                        bounded_explanation=_safe_text(explanation, 900),
                        requires_reason=row["requires_reason"],
                        requires_confirmation=row["requires_confirmation"],
                        requires_workflow_revision=row["requires_workflow_revision"],
                        requires_target_digest=row["requires_target_digest"],
                        authoritative_for_owner=row["owning_module_id"]
                        == "workflow_controller",
                        warnings=warnings[:MAX_WARNINGS],
                        limitations=[
                            NOT_EXECUTION_NOTICE,
                            NOT_SAFETY_NOTICE,
                            NOT_WORKFLOW_NOTICE,
                            *row["limitations"],
                        ][:24],
                    )
                )
        return rows[:MAX_ELIGIBILITY_ROWS]

    def _already_decided(
        self, project_id: str, target_type: str, target_id: str
    ) -> str | None:
        """Return the recorded decision for this exact target, if the owner has one."""
        payload = self._source_payload("workflow_controller", project_id)
        rows = payload.get("human_decisions")
        if not isinstance(rows, list):
            return None
        for entry in reversed(rows[-MAX_HISTORY_ROWS:]):
            if not isinstance(entry, Mapping):
                continue
            row = _as_mapping(entry)
            bound = _safe_text(
                row.get("stage_instance_id") or row.get("transition_request_id"), 180
            )
            if target_id and bound and bound != target_id:
                continue
            decision = _safe_text(row.get("decision"), 80)
            if decision in {APPROVE_DECISION, REJECT_DECISION}:
                return decision
        return None

    # ------------------------------------------------------------------
    # Snapshot: binds the exact identity the decision will be checked against
    # ------------------------------------------------------------------
    def build_approval_control_snapshot(
        self,
        project_id: str,
        review_session_id: str,
        review_snapshot_id: str,
        target_type: str,
        target_id: str = "",
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        _safe_id(review_session_id, "review session id")
        _safe_id(review_snapshot_id, "review snapshot id")
        rows = self.inspect_approval_eligibility(project_id, target_type, target_id)
        run = self._workflow_run(project_id)
        eligible = [row for row in rows if row.eligible]
        decided = self._already_decided(project_id, target_type, target_id)
        snapshot_key = _digest([project_id, target_type, target_id, review_snapshot_id])
        snapshot_id = f"approval_control_snapshot_{snapshot_key[:24]}"
        base = {
            "approval_control_snapshot_id": snapshot_id,
            "review_session_id": review_session_id,
            "review_snapshot_id": review_snapshot_id,
            "project_id": project_id,
            "workflow_run_id": _safe_text(run.get("workflow_run_id"), 180) or None,
            "stage_instance_id": _safe_text(run.get("current_stage_instance_id"), 180)
            or None,
            "target_type": target_type,
            "target_id": target_id,
            "project_snapshot_digest": self._project_snapshot_digest(project_id),
            "workflow_revision": self._workflow_revision(project_id),
            "target_digest": self._target_digest(project_id, target_type, target_id),
            "safety_record_digest": self._safety_record_digest(project_id),
            "final_decision_record_digest": self._final_decision_record_digest(project_id),
            "eligibility_ids": [row.eligibility_id for row in rows],
            "eligible_decision_kinds": sorted({row.decision_kind for row in eligible}),
            "safety_status": self._safety_status(project_id),
            "rights_status": self._rights_status(project_id),
            "validation_status": self._validation_status(project_id),
            "quality_status": self._quality_status(project_id),
            "checkpoint_status": self._checkpoint_status(project_id),
            "budget_status": self._budget_status(project_id),
            "workflow_status": self._workflow_status(project_id),
            "expires_at": _safe_text(run.get("expires_at"), 80) or None,
            "already_decided": decided is not None,
        }
        snapshot = BobaApprovalControlSnapshotV1(
            **base,
            snapshot_digest=_digest(base),
            confirmation_context_digest=_digest(
                {
                    "snapshot": _digest(base),
                    "target": base["target_digest"],
                    "safety": base["safety_record_digest"],
                    "revision": base["workflow_revision"],
                }
            ),
            warnings=[row.bounded_explanation for row in rows if row.button_state == "blocked"][
                :MAX_WARNINGS
            ],
            limitations=[
                NOT_EXECUTION_NOTICE,
                NOT_SAFETY_NOTICE,
                NOT_WORKFLOW_NOTICE,
                REJECTION_NOTICE,
                "Decision identity, expiry, staleness and idempotency are owned by "
                "the Review UI action chain, which this layer submits through.",
            ],
        )
        self.store.save_boba_approval_control_snapshot(
            project_id, snapshot_id, snapshot.model_dump(mode="json")
        )
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "eligibility": [row.model_dump(mode="json") for row in rows],
            "notices": {
                "not_execution": NOT_EXECUTION_NOTICE,
                "not_safety": NOT_SAFETY_NOTICE,
                "not_workflow": NOT_WORKFLOW_NOTICE,
                "stale": STALE_NOTICE,
                "rejection": REJECTION_NOTICE,
            },
        }

    def _snapshot(self, project_id: str, snapshot_id: str) -> BobaApprovalControlSnapshotV1:
        _safe_id(project_id, "project id")
        _safe_id(snapshot_id, "approval control snapshot id")
        raw = self.store.load_boba_approval_control_snapshot(project_id, snapshot_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA approval control snapshot is unavailable.")
        snapshot = BobaApprovalControlSnapshotV1.model_validate(raw)
        if snapshot.project_id != project_id:
            raise ValidationError("Approval control snapshot belongs to another project.")
        return snapshot

    # ------------------------------------------------------------------
    # Staleness revalidation, before anything reaches an owner
    # ------------------------------------------------------------------
    def revalidate_approval_snapshot(
        self, project_id: str, snapshot_id: str
    ) -> dict[str, Any]:
        """Re-read every bound identity and refuse on any drift."""
        snapshot = self._snapshot(project_id, snapshot_id)
        checks: list[tuple[str, str, object, object]] = [
            (
                "stale_project_snapshot",
                "The project changed while this control was displayed.",
                self._project_snapshot_digest(project_id),
                snapshot.project_snapshot_digest,
            ),
            (
                "workflow_revision_mismatch",
                "The workflow revision changed while this control was displayed.",
                self._workflow_revision(project_id),
                snapshot.workflow_revision,
            ),
            (
                "target_digest_mismatch",
                "The reviewed target changed while this control was displayed.",
                self._target_digest(project_id, snapshot.target_type, snapshot.target_id),
                snapshot.target_digest,
            ),
            (
                "safety_record_digest_mismatch",
                "The Safety Gate record changed while this control was displayed.",
                self._safety_record_digest(project_id),
                snapshot.safety_record_digest,
            ),
            (
                "final_decision_record_digest_mismatch",
                "The Final Decision Bus record changed while this control was displayed.",
                self._final_decision_record_digest(project_id),
                snapshot.final_decision_record_digest,
            ),
        ]
        for code, message, live, expected in checks:
            if live != expected:
                return {"valid": False, "code": code, "message": message, "stale": True}

        for code, message, live, expected in (
            (
                "safety_state_changed",
                "The Safety Gate state changed while this control was displayed.",
                self._safety_status(project_id),
                snapshot.safety_status,
            ),
            (
                "rights_state_changed",
                "The Rights state changed while this control was displayed.",
                self._rights_status(project_id),
                snapshot.rights_status,
            ),
            (
                "validation_state_changed",
                "The validation state changed while this control was displayed.",
                self._validation_status(project_id),
                snapshot.validation_status,
            ),
            (
                "quality_state_changed",
                "The quality decision changed while this control was displayed.",
                self._quality_status(project_id),
                snapshot.quality_status,
            ),
            (
                "checkpoint_state_changed",
                "The checkpoint state changed while this control was displayed.",
                self._checkpoint_status(project_id),
                snapshot.checkpoint_status,
            ),
            (
                "budget_state_changed",
                "The budget state changed while this control was displayed.",
                self._budget_status(project_id),
                snapshot.budget_status,
            ),
        ):
            if live != expected:
                return {"valid": False, "code": code, "message": message, "stale": True}

        expires_at = _parse_time(snapshot.expires_at) if snapshot.expires_at else None
        if expires_at is not None and expires_at <= datetime.now(UTC):
            return {
                "valid": False,
                "code": "expired",
                "message": "The reviewed approval window expired.",
                "stale": True,
            }
        if self._already_decided(project_id, snapshot.target_type, snapshot.target_id):
            return {
                "valid": False,
                "code": "already_decided",
                "message": "A human decision is already recorded for this exact target.",
                "stale": False,
            }
        return {
            "valid": True,
            "code": "current",
            "message": "Every bound identity still matches the canonical owners.",
            "stale": False,
        }

    # ------------------------------------------------------------------
    # Decision submission: delegates to the canonical Review UI chain
    # ------------------------------------------------------------------
    def _eligibility_for(
        self, project_id: str, snapshot: BobaApprovalControlSnapshotV1, kind: str
    ) -> BobaApprovalEligibilityV1:
        rows = self.inspect_approval_eligibility(
            project_id, snapshot.target_type, snapshot.target_id
        )
        for row in rows:
            if row.decision_kind == kind and row.eligible:
                return row
        blocked = next((row for row in rows if row.decision_kind == kind), None)
        detail = blocked.bounded_explanation if blocked else "no canonical descriptor"
        raise ValidationError(
            f"A '{kind}' decision is not available for this exact target: {detail}"
        )

    def create_approval_decision_request(
        self,
        project_id: str,
        *,
        approval_control_snapshot_id: str,
        decision_kind: str,
        reason: str = "",
        idempotency_key: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        """Bind an exact decision and create it through the Review UI action chain."""
        if decision_kind not in {APPROVE_DECISION, REJECT_DECISION}:
            raise ValidationError(
                "Only an approve or reject decision may be created from this control."
            )
        snapshot = self._snapshot(project_id, approval_control_snapshot_id)
        eligibility = self._eligibility_for(project_id, snapshot, decision_kind)
        if not confirmed:
            raise ValidationError("An explicit confirmation is required before deciding.")
        safe_reason = bounded_reason(reason)
        if eligibility.requires_reason and not safe_reason:
            raise ValidationError("This decision requires a bounded reason.")

        revalidation = self.revalidate_approval_snapshot(
            project_id, approval_control_snapshot_id
        )
        if not revalidation["valid"]:
            self._emit(
                project_id,
                "approval_stale" if revalidation.get("stale") else "request_already_decided",
                decision_kind=decision_kind,
                target_type=snapshot.target_type,
                target_id=snapshot.target_id,
                message=str(revalidation["message"]),
            )
            return {
                "created": False,
                "code": str(revalidation["code"]),
                "message": str(revalidation["message"]),
                "stale": bool(revalidation.get("stale")),
                "notice": STALE_NOTICE,
            }

        # The Review UI owns request identity, digests, expiry and idempotency.
        request = self.integration.create_boba_review_action_request(
            project_id,
            review_session_id=snapshot.review_session_id,
            review_snapshot_id=snapshot.review_snapshot_id,
            action_descriptor_id=eligibility.action_descriptor_id,
            decision_value=decision_kind,
            reason=safe_reason,
            confirmation_context_digest=snapshot.confirmation_context_digest,
            idempotency_key=idempotency_key,
            confirmed=True,
        )
        request_id = _safe_text(
            _as_mapping(request).get("review_action_request_id"), 180
        )
        self._emit(
            project_id,
            "approval_requested",
            decision_kind=decision_kind,
            target_type=snapshot.target_type,
            target_id=snapshot.target_id,
            request_id=request_id,
            owning_module_id=eligibility.owning_module_id,
            message=(
                f"A human {decision_kind} decision was prepared for "
                f"{eligibility.owning_module_id}.{eligibility.owning_operation_id}."
            ),
        )
        return {
            "created": True,
            "review_action_request_id": request_id,
            "request": _as_mapping(request),
            "decision_kind": decision_kind,
            "owning_module_id": eligibility.owning_module_id,
            "owning_operation_id": eligibility.owning_operation_id,
            "notices": {
                "not_execution": NOT_EXECUTION_NOTICE,
                "not_safety": NOT_SAFETY_NOTICE,
                "not_workflow": NOT_WORKFLOW_NOTICE,
            },
        }

    async def submit_approval_decision(
        self, project_id: str, review_action_request_id: str, decision_kind: str
    ) -> BobaApprovalDecisionReceiptV1:
        """Submit through the Review UI chain and project a truthful receipt.

        The Review UI performs its own staleness revalidation and idempotency.
        This layer never invents a successful approval: every field below is
        derived from the canonical receipt the owner returned.
        """
        if decision_kind not in {APPROVE_DECISION, REJECT_DECISION}:
            raise ValidationError("Only an approve or reject decision may be submitted.")
        _safe_id(review_action_request_id, "review action request id")

        existing = self.store.load_boba_approval_control_receipt_for_request(
            project_id, review_action_request_id
        )
        if isinstance(existing, Mapping):
            receipt = BobaApprovalDecisionReceiptV1.model_validate(existing)
            self._emit(
                project_id,
                "request_already_decided",
                decision_kind=decision_kind,
                request_id=review_action_request_id,
                message="The existing canonical decision was returned unchanged.",
            )
            return receipt.model_copy(update={"duplicate_request_reused": True})

        receipt_key = _digest([review_action_request_id, decision_kind])
        receipt_id = f"approval_decision_receipt_{receipt_key[:24]}"
        owner_receipt = _as_mapping(
            await self.integration.submit_boba_review_action_to_owner(
                project_id, review_action_request_id
            )
        )
        accepted = bool(owner_receipt.get("accepted_by_owner"))
        stale = bool(owner_receipt.get("stale_state_rejected"))
        canonical_id = _safe_text(owner_receipt.get("canonical_record_id"), 180) or None
        canonical_digest = (
            _safe_text(owner_receipt.get("canonical_record_digest"), 64) or None
        )
        safety_present = self._safety_status(project_id) != "unavailable"

        receipt = BobaApprovalDecisionReceiptV1(
            approval_decision_receipt_id=receipt_id,
            review_action_request_id=review_action_request_id,
            review_action_receipt_id=_safe_text(owner_receipt.get("action_receipt_id"), 180),
            project_id=project_id,
            target_type=_safe_text(owner_receipt.get("target_type") or "workflow_stage", 80),
            target_id=_safe_text(owner_receipt.get("target_id"), 180),
            decision_kind=decision_kind,
            owning_module_id=_safe_text(
                owner_receipt.get("owning_module_id") or "workflow_controller", 180
            ),
            owning_operation_id=_safe_text(
                owner_receipt.get("owning_operation_id")
                or "record_human_workflow_decision",
                240,
            ),
            completed_at=_safe_text(owner_receipt.get("completed_at"), 80) or None,
            # 1. the human's choice was recorded only if the owner accepted it
            user_decision_recorded=accepted,
            user_decision_value=decision_kind if accepted else "",
            bounded_reason="",
            # 2. the owner's own outcome
            owner_accepted=accepted,
            canonical_record_id=canonical_id if accepted else None,
            canonical_record_digest=canonical_digest if accepted else None,
            canonical_status=_safe_text(owner_receipt.get("canonical_status") or "pending", 120),
            # 3. Safety stays separately owned
            safety_decision_present=safety_present,
            # 4. execution is a separate fact; a decision is never an execution
            execution_reported_by_owner=False,
            execution_owner_module_id=None,
            workflow_advanced=False,
            stale_state_rejected=stale,
            error_code=_safe_text(owner_receipt.get("error_code"), 120) or None,
            bounded_error_message=_safe_text(
                owner_receipt.get("bounded_error_message"), 900
            ),
            warnings=[
                _safe_text(item, 300)
                for item in owner_receipt.get("warnings", [])
                if isinstance(item, str)
            ][:MAX_WARNINGS],
            limitations=[
                NOT_EXECUTION_NOTICE,
                NOT_SAFETY_NOTICE,
                NOT_WORKFLOW_NOTICE,
                *( [REJECTION_NOTICE] if decision_kind == REJECT_DECISION else [] ),
                "The Workflow Controller owns this decision record and its revision.",
            ][:24],
        )
        self._persist_receipt(project_id, receipt)

        if stale:
            event = "approval_stale"
            message = STALE_NOTICE
        elif not accepted:
            event = "approval_denied"
            message = (
                f"The canonical owner did not accept the decision: "
                f"{receipt.canonical_status}."
            )
        elif decision_kind == APPROVE_DECISION:
            event = "approval_confirmed"
            message = (
                "The Workflow Controller recorded a human approval. Nothing was "
                "executed and no workflow advanced."
            )
        else:
            event = "rejection_accepted"
            message = (
                "The Workflow Controller recorded a human rejection. Nothing was "
                "deleted, rolled back or changed."
            )
        self._emit(
            project_id,
            event,
            decision_kind=decision_kind,
            target_type=receipt.target_type,
            target_id=receipt.target_id,
            request_id=review_action_request_id,
            owning_module_id=receipt.owning_module_id,
            message=message,
        )
        return receipt

    def _persist_receipt(
        self, project_id: str, receipt: BobaApprovalDecisionReceiptV1
    ) -> BobaApprovalDecisionReceiptV1:
        """Refuse to persist any receipt that overstates what happened."""
        if receipt.owner_accepted and not (
            receipt.canonical_record_id and receipt.canonical_record_digest
        ):
            raise ValidationError(
                "An accepted decision must name a canonical owner record and digest."
            )
        if receipt.execution_reported_by_owner and not receipt.execution_owner_module_id:
            raise ValidationError(
                "Execution cannot be reported without naming the owning module."
            )
        self.store.save_boba_approval_control_receipt(
            project_id,
            receipt.approval_decision_receipt_id,
            receipt.model_dump(mode="json"),
        )
        return receipt

    def inspect_decision_status(
        self, project_id: str, review_action_request_id: str
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        _safe_id(review_action_request_id, "review action request id")
        stored = self.store.load_boba_approval_control_receipt_for_request(
            project_id, review_action_request_id
        )
        return {
            "schema_version": "boba_approval_controls_status_v1",
            "project_id": project_id,
            "review_action_request_id": review_action_request_id,
            "decided": bool(stored),
            "receipt": _safe_payload(stored) if stored else None,
            "notice": NOT_EXECUTION_NOTICE,
        }

    def inspect_decision_history(self, project_id: str) -> dict[str, Any]:
        """Project the owner's own human-decision history, newest last."""
        _safe_id(project_id, "project id")
        payload = self._source_payload("workflow_controller", project_id)
        rows = payload.get("human_decisions")
        entries: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for entry in rows[-MAX_HISTORY_ROWS:]:
                if not isinstance(entry, Mapping):
                    continue
                row = _as_mapping(entry)
                entries.append(
                    {
                        "human_decision_id": _safe_text(row.get("human_decision_id"), 180),
                        "decision": _safe_text(row.get("decision"), 80),
                        "decision_type": _safe_text(row.get("decision_type"), 120),
                        "bounded_reason": _safe_text(row.get("bounded_reason"), 500),
                        "decided_at": _safe_text(row.get("decided_at"), 80),
                        "workflow_revision": row.get("workflow_revision"),
                        "stage_instance_id": _safe_text(row.get("stage_instance_id"), 180),
                        "reviewer_reference": _safe_text(row.get("reviewer_reference"), 160),
                        "upload_authorized": False,
                        "publication_authorized": False,
                    }
                )
        return {
            "schema_version": "boba_approval_controls_history_v1",
            "project_id": project_id,
            "entries": entries,
            "entry_count": len(entries),
            "owner_module_id": "workflow_controller",
            "limitations": [
                "History is the Workflow Controller's own immutable decision record.",
                NOT_EXECUTION_NOTICE,
            ],
        }

    # ------------------------------------------------------------------
    # Append-only truthful events
    # ------------------------------------------------------------------
    def _emit(
        self,
        project_id: str,
        event_type: str,
        *,
        decision_kind: str | None = None,
        target_type: str = "",
        target_id: str = "",
        request_id: str = "",
        owning_module_id: str = "",
        message: str = "",
    ) -> BobaApprovalControlEventV1:
        existing = self.store.load_boba_approval_control_events(project_id) or []
        # Sequences are 1-based so a cursor of 0 still returns the first event.
        sequence = len(existing) + 1
        event_key = _digest([project_id, event_type, request_id, str(sequence)])
        event_id = f"approval_control_event_{sequence:05d}_{event_key[:16]}"
        event = BobaApprovalControlEventV1(
            event_id=event_id,
            project_id=project_id,
            sequence=sequence,
            event_type=event_type,
            decision_kind=decision_kind,
            target_type=_safe_text(target_type, 80),
            target_id=_safe_text(target_id, 180),
            review_action_request_id=_safe_text(request_id, 180),
            owning_module_id=_safe_text(owning_module_id, 180),
            bounded_message=_safe_text(message, 900),
            limitations=[NOT_EXECUTION_NOTICE],
        )
        self.store.append_boba_approval_control_event(
            project_id, event.model_dump(mode="json")
        )
        return event

    def inspect_approval_events(
        self, project_id: str, *, after_sequence: int = 0, limit: int = MAX_EVENTS
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        rows = self.store.load_boba_approval_control_events(project_id) or []
        events = [
            BobaApprovalControlEventV1.model_validate(row).model_dump(mode="json")
            for row in rows
            if isinstance(row, Mapping)
        ]
        filtered = [e for e in events if int(e["sequence"]) > after_sequence]
        bounded = filtered[: max(1, min(limit, MAX_EVENTS))]
        return {
            "schema_version": "boba_approval_controls_events_v1",
            "project_id": project_id,
            "events": bounded,
            "append_only": True,
            "has_more": len(filtered) > len(bounded),
            "latest_sequence": max((int(e["sequence"]) for e in bounded), default=after_sequence),
        }

    # ------------------------------------------------------------------
    # Aggregate, export and reset
    # ------------------------------------------------------------------
    def _signal_usage(self, project_id: str) -> BobaApprovalControlSignalUsageV1:
        def present(module_id: str) -> bool:
            return bool(self._source_payload(module_id, project_id))

        return BobaApprovalControlSignalUsageV1(
            canonical_review_ui_records=present("review_ui"),
            canonical_workflow_records=present("workflow_controller"),
            canonical_safety_records=present("safety_gate"),
            canonical_final_decision_records=present("final_decision_bus"),
            canonical_autopilot_records=present("autopilot_controller"),
            canonical_output_quality_records=present("output_quality_reviewer"),
            unavailable_signals=[m for m in self._LOADERS if not present(m)],
            limitations=[
                "Signal usage records which canonical owners were read, not who "
                "decided anything.",
            ],
        )

    def build_approval_controls(
        self, project_id: str, target_type: str = "workflow_stage", target_id: str = ""
    ) -> dict[str, Any]:
        registry = self.build_approval_control_registry(project_id)
        rows = self.inspect_approval_eligibility(project_id, target_type, target_id)
        eligible = [row for row in rows if row.eligible]
        events = self.inspect_approval_events(project_id)
        summary = BobaApprovalControlSummaryV1(
            eligible_decision_count=len(eligible),
            ineligible_decision_count=len(rows) - len(eligible),
            approve_available=any(row.decision_kind == "approve" for row in eligible),
            reject_available=any(row.decision_kind == "reject" for row in eligible),
            blocked_count=sum(1 for row in rows if row.button_state == "blocked"),
            already_decided_count=sum(
                1 for row in rows if row.reason_code == "already_decided"
            ),
            safest_next_review_action=(
                "Read the bound target, Safety state and Rights state before deciding."
                if eligible
                else "No approve or reject decision is available for this target."
            ),
            required_human_actions=[
                f"{row.decision_kind}: {row.bounded_explanation[:120]}"
                for row in eligible
            ][:16],
            limitations=[NOT_EXECUTION_NOTICE, NOT_SAFETY_NOTICE, NOT_WORKFLOW_NOTICE],
        )
        result = BobaApprovalControlSetV1(
            project_id=project_id,
            registry_snapshots=[
                BobaApprovalControlRegistrySnapshotV1.model_validate(
                    registry["registry_snapshot"]
                )
            ],
            eligibility_rows=rows,
            events=[
                BobaApprovalControlEventV1.model_validate(item) for item in events["events"]
            ],
            control_summary=summary,
            signal_usage=self._signal_usage(project_id),
            limitations=[
                "Approval / Reject Buttons V1 is an interaction layer. It derives "
                "eligibility from the canonical Review UI action registry and submits "
                "decisions through the existing Review UI action chain.",
                "It creates no approval authority, no second decision path, no second "
                "database and no second idempotency mechanism.",
                NOT_EXECUTION_NOTICE,
                NOT_SAFETY_NOTICE,
                NOT_WORKFLOW_NOTICE,
                REJECTION_NOTICE,
            ],
        )
        self.store.save_boba_approval_controls(project_id, result.model_dump(mode="json"))
        return result.model_dump(mode="json")

    def load_approval_controls(self, project_id: str) -> dict[str, Any] | None:
        _safe_id(project_id, "project id")
        return self.store.load_boba_approval_controls(project_id)

    def export_approval_controls(self, project_id: str) -> dict[str, Any]:
        payload = {
            "schema_version": "boba_approval_controls_export_v1",
            "project_id": project_id,
            "exported_at": now_iso(),
            "registry": self.build_approval_control_registry(project_id),
            "history": self.inspect_decision_history(project_id),
            "events": self.inspect_approval_events(project_id),
            "privacy": {
                "sensitive_values_excluded": True,
                "raw_commands_excluded": True,
                "private_paths_excluded": True,
                "raw_media_excluded": True,
                "reviewer_identity_bounded": True,
                "execution_performed": False,
                "workflow_advanced": False,
                "safety_approval_granted": False,
                "upload_used": False,
                "publication_used": False,
            },
        }
        return _as_mapping(_safe_payload(payload))

    def reset_approval_control_metadata(self, project_id: str) -> dict[str, Any]:
        """Remove only interaction metadata. Every owner history is preserved."""
        _safe_id(project_id, "project id")
        return self.store.reset_boba_approval_control_metadata(project_id)

    # ------------------------------------------------------------------
    # Timeline: a read-only projection, never a second event stream
    # ------------------------------------------------------------------
    def inspect_approval_timeline(
        self, project_id: str, *, limit: int = MAX_TIMELINE_ENTRIES
    ) -> dict[str, Any]:
        """Project the existing append-only event log and the owner's decisions.

        This opens no second event stream and persists nothing. Every fact comes
        from a record another owner already wrote; derived presentation is kept
        in separate fields so a reader can tell the two apart.
        """
        _safe_id(project_id, "project id")
        entries: list[BobaApprovalTimelineEntryV1] = []

        # 1. This layer's own append-only interaction events.
        for row in self.store.load_boba_approval_control_events(project_id):
            if not isinstance(row, Mapping):
                continue
            event = _as_mapping(_safe_payload(row))
            sequence = event.get("sequence")
            event_type = _safe_text(event.get("event_type"), 160)
            occurred_at = _safe_text(event.get("created_at"), 80) or None
            entries.append(
                BobaApprovalTimelineEntryV1(
                    timeline_entry_id=_stable_id(
                        "approval_timeline",
                        project_id,
                        "event",
                        _safe_text(event.get("event_id"), 180),
                    ),
                    project_id=project_id,
                    entry_kind="approval_control_event",
                    source_module_id="approval_controls",
                    source_record_id=_safe_text(event.get("event_id"), 180) or "event",
                    event_type=event_type,
                    decision_kind=_safe_text(event.get("decision_kind"), 80) or None,
                    target_type=_safe_text(event.get("target_type"), 80),
                    target_id=_safe_text(event.get("target_id"), 180),
                    owning_module_id=_safe_text(event.get("owning_module_id"), 180),
                    bounded_message=_safe_text(event.get("bounded_message"), 900),
                    sequence=sequence if isinstance(sequence, int) else None,
                    occurred_at=occurred_at,
                    timestamp_precision="source" if occurred_at else "unknown",
                    confirmed_order=isinstance(sequence, int),
                    derived_title=event_type.replace("_", " ").title() or "Approval Event",
                    derived_summary=_safe_text(event.get("bounded_message"), 900),
                    limitations=[NOT_EXECUTION_NOTICE],
                )
            )

        # 2. The Workflow Controller's own immutable decision records.
        for index, row in enumerate(self.inspect_decision_history(project_id)["entries"]):
            decided_at = _safe_text(row.get("decided_at"), 80) or None
            decision = _safe_text(row.get("decision"), 80)
            revision = row.get("workflow_revision")
            entries.append(
                BobaApprovalTimelineEntryV1(
                    timeline_entry_id=_stable_id(
                        "approval_timeline",
                        project_id,
                        "decision",
                        _safe_text(row.get("human_decision_id"), 180) or str(index),
                    ),
                    project_id=project_id,
                    entry_kind="owner_decision_record",
                    source_module_id="workflow_controller",
                    source_record_id=_safe_text(row.get("human_decision_id"), 180)
                    or f"human_decision_{index}",
                    event_type="owner_human_decision",
                    decision_kind=decision
                    if decision in {APPROVE_DECISION, REJECT_DECISION}
                    else None,
                    decision_value=decision,
                    target_type="workflow_stage",
                    target_id=_safe_text(row.get("stage_instance_id"), 180),
                    owning_module_id="workflow_controller",
                    bounded_reason=_safe_text(row.get("bounded_reason"), MAX_REASON_LENGTH),
                    workflow_revision=revision if isinstance(revision, int) else None,
                    occurred_at=decided_at,
                    timestamp_precision="source" if decided_at else "unknown",
                    confirmed_order=decided_at is not None,
                    derived_title=f"Workflow Controller recorded: {decision or 'unknown'}",
                    derived_summary=_safe_text(row.get("bounded_reason"), 900),
                    limitations=[
                        "The Workflow Controller owns this record and its revision.",
                        NOT_EXECUTION_NOTICE,
                    ],
                )
            )

        # Deterministic ordering: owner timestamps first, then the append-only
        # sequence, then a stable id. Nothing is reordered by inferred priority.
        entries.sort(
            key=lambda item: (
                item.occurred_at or "",
                item.entry_kind,
                item.sequence if item.sequence is not None else 0,
                item.timeline_entry_id,
            )
        )
        bounded = entries[: max(1, min(limit, MAX_TIMELINE_ENTRIES))]
        return {
            "schema_version": "boba_approval_controls_timeline_v1",
            "project_id": project_id,
            "entries": [item.model_dump(mode="json") for item in bounded],
            "entry_count": len(bounded),
            "total_available": len(entries),
            "has_more": len(entries) > len(bounded),
            "empty": not entries,
            "status": (
                "No approval decision or approval event has been recorded for this "
                "project."
                if not entries
                else f"{len(entries)} recorded entries projected from their owners."
            ),
            "mutation_performed": False,
            "second_event_stream_created": False,
            "limitations": [
                "The timeline is a read-only projection of records their owners "
                "already wrote. It persists nothing.",
                "Owner facts and derived presentation are separate fields.",
                "Entry order follows owner timestamps and the append-only sequence; "
                "where a record has neither, the order is not confirmed.",
                NOT_EXECUTION_NOTICE,
                NOT_WORKFLOW_NOTICE,
            ],
        }

    # ------------------------------------------------------------------
    # Comparison: read-only, never selects a winner
    # ------------------------------------------------------------------
    def compare_approval_decisions(
        self, project_id: str, review_action_request_ids: Sequence[str]
    ) -> dict[str, Any]:
        """Compare existing decisions side by side without choosing between them."""
        _safe_id(project_id, "project id")
        unique: list[str] = []
        for item in review_action_request_ids:
            request_id = _safe_id(str(item), "review action request id")
            if request_id not in unique:
                unique.append(request_id)
        if len(unique) < 2:
            raise ValidationError("At least two distinct decisions are required.")
        if len(unique) > MAX_COMPARISON_DECISIONS:
            raise ValidationError(
                f"At most {MAX_COMPARISON_DECISIONS} decisions may be compared."
            )

        receipts: list[BobaApprovalDecisionReceiptV1] = []
        for request_id in unique:
            stored = self.store.load_boba_approval_control_receipt_for_request(
                project_id, request_id
            )
            if not isinstance(stored, Mapping):
                raise ValidationError(
                    f"Decision '{request_id}' is unknown for this project."
                )
            receipt = BobaApprovalDecisionReceiptV1.model_validate(stored)
            if receipt.project_id != project_id:
                raise ValidationError("A decision belongs to another project.")
            receipts.append(receipt)

        target_types = {r.target_type for r in receipts}
        target_ids = {r.target_id for r in receipts}
        same_target_type = len(target_types) == 1
        same_target_id = len(target_ids) == 1
        compatible = same_target_type and same_target_id
        incompatibility = ""
        if not compatible:
            incompatibility = (
                "These decisions do not refer to the same target, so their fields "
                f"are not equivalent. Target types seen: {sorted(target_types)}. "
                f"Target ids seen: {sorted(target_ids)}."
            )

        owner_rows = [
            {
                "review_action_request_id": r.review_action_request_id,
                "decision_kind": r.decision_kind,
                "user_decision_recorded": r.user_decision_recorded,
                "user_decision_value": r.user_decision_value,
                "owner_accepted": r.owner_accepted,
                "canonical_status": r.canonical_status,
                "canonical_record_id": r.canonical_record_id,
                "owning_module_id": r.owning_module_id,
                "owning_operation_id": r.owning_operation_id,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "stale_state_rejected": r.stale_state_rejected,
                "duplicate_request_reused": r.duplicate_request_reused,
                "already_decided": r.already_decided,
                "error_code": r.error_code,
                "safety_decision_present": r.safety_decision_present,
                "execution_reported_by_owner": r.execution_reported_by_owner,
                "workflow_advanced": r.workflow_advanced,
                "submitted_at": r.submitted_at,
                "completed_at": r.completed_at,
            }
            for r in receipts
        ]

        def state_of(r: BobaApprovalDecisionReceiptV1) -> str:
            if r.stale_state_rejected:
                return "stale"
            if r.already_decided:
                return "already_decided"
            if not r.owner_accepted:
                return "not_accepted"
            return "approved" if r.decision_kind == APPROVE_DECISION else "rejected"

        presentation_rows = [
            {
                "review_action_request_id": r.review_action_request_id,
                "derived_state": state_of(r),
                "derived_label": (
                    f"{r.owning_module_id} recorded {r.decision_kind}"
                    if r.owner_accepted
                    else f"not accepted ({r.canonical_status})"
                ),
                "derived_claims_no_side_effects": not (
                    r.execution_reported_by_owner or r.workflow_advanced
                ),
            }
            for r in receipts
        ]

        compared_fields = (
            "decision_kind",
            "owner_accepted",
            "canonical_status",
            "target_type",
            "target_id",
            "stale_state_rejected",
            "already_decided",
            "error_code",
            "owning_module_id",
        )
        differing = sorted(
            field
            for field in compared_fields
            if len({str(row[field]) for row in owner_rows}) > 1
        )
        comparison = BobaApprovalDecisionComparisonV1(
            comparison_id=_stable_id("approval_comparison", project_id, *unique),
            project_id=project_id,
            review_action_request_ids=unique,
            compatible=compatible,
            incompatibility_reason=_safe_text(incompatibility, 900),
            same_target_type=same_target_type,
            same_target_id=same_target_id,
            owner_fact_rows=owner_rows,
            presentation_rows=presentation_rows,
            differing_fields=differing,
            decision_kinds=sorted({r.decision_kind for r in receipts}),
            canonical_statuses=sorted({r.canonical_status for r in receipts}),
            bounded_summary=_safe_text(
                f"Comparing {len(unique)} recorded decisions field by field."
                if compatible
                else f"Comparing {len(unique)} decisions that do not share a target.",
                900,
            ),
            limitations=[
                "No winner is selected and no best decision is inferred.",
                "Owner facts and derived presentation are separate fields.",
                "Comparison reads persisted receipts only; nothing is mutated.",
                NOT_EXECUTION_NOTICE,
                NOT_SAFETY_NOTICE,
            ],
        )
        return {
            "schema_version": "boba_approval_controls_comparison_v1",
            "project_id": project_id,
            "comparison": comparison.model_dump(mode="json"),
        }

"""Read-only BOBA Clip Brief review projections and constrained action routing.

The Clip Brief Panel is a specialized mode of the BOBA Review UI and the BOBA
Candidate Review Panel. It is a read-only brief projection, an evidence
workspace, a comparison interface and a safe canonical action router.

It never generates, regenerates or rewrites a clip brief, never invents a field
that the owner schema does not define, never builds a quality or virality score,
and never chooses a preferred brief. Every value it shows is copied verbatim from
the module that owns it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from olympus.boba.contracts import BobaContract, now_iso

# Shared Review UI primitives. Reusing them keeps digest and sanitisation
# semantics byte-identical to Review UI V1 and Candidate Review V1, which the
# confirmation tokens depend on.
from olympus.boba.review_ui import (
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


# Brief identifiers are opaque, source-owned tokens.
_SAFE_BRIEF_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")

# The one schema this panel understands, taken verbatim from the owner set's
# ``brief_version`` literal. Anything else is reported as unsupported.
SUPPORTED_BRIEF_SCHEMA_ID = "boba_clip_brief_generator_v1"

_TIME_PRECISION = 3
MAX_COMPARISON_BRIEFS = 4
MAX_LOADED_BRIEFS = 500
MAX_QUEUE_PAGE_SIZE = 50
MAX_TIMELINE_ENTRIES = 100
MAX_ANNOTATION_LENGTH = 4_000
MAX_BOUNDED_DISPLAY_CHARS = 16_384
MAX_EXPANDED_SOURCE_CARDS = 20
_MAX_EVENTS = 100
_MAX_SOURCE_CARDS = 24
_MAX_FIELD_PROJECTIONS = 64
_MAX_SECTION_PROJECTIONS = 24
_MAX_EVIDENCE_LINKS = 48
_MAX_CONFLICTS = 32
_MAX_REASON_LENGTH = 500

ClipBriefReviewFilter = Literal[
    "all_current",
    "human_review_required",
    "current_selected_candidate",
    "missing_required_fields",
    "missing_evidence",
    "conflicts",
    "stale",
    "complete_for_owner_schema",
    "warnings",
    "historical",
    "superseded",
]
ClipBriefReviewSort = Literal[
    "review_priority",
    "candidate_rank",
    "created_sequence",
    "source_start_time",
    "brief_id",
]
ClipBriefComparisonType = Literal[
    "side_by_side",
    "current_vs_historical",
    "candidate_briefs",
    "source_window",
    "completeness",
    "evidence_coverage",
    "hook",
    "narrative",
    "creative_guidance",
    "unknown",
]
ClipBriefCompletenessStatus = Literal[
    "complete",
    "complete_with_optional_gaps",
    "missing_required_fields",
    "schema_unavailable",
    "unsupported_schema",
    "stale",
    "blocked",
    "unknown",
]
ClipBriefConflictType = Literal[
    "candidate_identity_conflict",
    "clip_identity_conflict",
    "source_window_conflict",
    "duration_conflict",
    "transcript_conflict",
    "hook_conflict",
    "narrative_conflict",
    "editorial_status_conflict",
    "workflow_state_conflict",
    "source_digest_conflict",
    "revision_conflict",
    "lifecycle_conflict",
    "unknown",
]
ClipBriefFieldCategory = Literal[
    "identity",
    "overview",
    "objective",
    "audience",
    "source_window",
    "duration",
    "hook",
    "narrative",
    "story_arc",
    "beats",
    "ending",
    "transcript",
    "caption_guidance",
    "motion_guidance",
    "music_guidance",
    "evidence",
    "warning",
    "limitation",
    "metadata",
    "unknown",
]


def _seconds(value: object) -> float | None:
    """Return a bounded, rounded float second value, or None when unusable."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    if numeric != numeric or numeric in {float("inf"), float("-inf")}:
        return None
    if numeric < 0.0 or numeric > 172_800.0:
        return None
    return round(numeric, _TIME_PRECISION)


def _bounded_display(value: object) -> tuple[str, bool]:
    """Return a bounded display string and whether it was truncated."""
    if isinstance(value, str):
        text = value
    elif value is None:
        return ("", False)
    else:
        text = repr(value)
    if len(text) <= MAX_BOUNDED_DISPLAY_CHARS:
        return (text, False)
    return (text[:MAX_BOUNDED_DISPLAY_CHARS], True)


def _value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, Mapping):
        return "object"
    return "unknown"


def _is_present(value: object) -> bool:
    """A field is present when the owner persisted a usable value.

    An explicit null, an empty string and an empty list are all *absent* for
    completeness purposes but are reported distinctly so the reviewer can tell
    them apart.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | dict):
        return bool(value)
    return True


def _is_empty(value: object) -> bool:
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | dict):
        return len(value) == 0
    return False


class BobaClipBriefRegistrySnapshotV1(BobaContract):
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = "1"
    created_at: str = Field(default_factory=now_iso)
    brief_source_ids: list[str] = Field(default_factory=list, max_length=32)
    available_source_ids: list[str] = Field(default_factory=list, max_length=32)
    unavailable_source_ids: list[str] = Field(default_factory=list, max_length=32)
    action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    unavailable_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    section_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    registry_digest: str = Field(min_length=64, max_length=64)
    immutable: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaClipBriefReferenceV1(BobaContract):
    brief_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    candidate_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=160)
    brief_revision_id: str | None = None
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    brief_schema_id: str = Field(default="unknown", max_length=180)
    brief_schema_version: str = Field(default="unknown", max_length=80)
    schema_supported: bool = False
    lifecycle_bucket: str = Field(default="unknown", max_length=80)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(ge=0.0)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    superseding_brief_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_exact_source_window(self) -> BobaClipBriefReferenceV1:
        if self.end_seconds < self.start_seconds:
            raise ValueError("Clip brief end_seconds cannot precede start_seconds.")
        return self


class BobaClipBriefReviewSessionV1(BobaContract):
    clip_brief_review_session_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    reviewer_context_id: str = Field(min_length=1, max_length=160)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    expires_at: str
    selected_brief_id: str | None = None
    selected_candidate_id: str | None = None
    comparison_brief_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_BRIEFS
    )
    active_filter: ClipBriefReviewFilter = "all_current"
    active_sort: ClipBriefReviewSort = "review_priority"
    active_section_id: str = "identity"
    show_historical: bool = False
    show_technical_details: bool = False
    show_source_evidence: bool = True
    show_empty_optional_fields: bool = False
    evidence_drawer_open: bool = False
    timeline_drawer_open: bool = False
    local_annotations: list[dict[str, str]] = Field(default_factory=list, max_length=32)
    session_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaClipBriefQueueItemV1(BobaContract):
    brief_queue_item_id: str = Field(min_length=1, max_length=180)
    brief_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    candidate_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(default="", max_length=900)
    owner_module_id: str = Field(default="clip_brief", max_length=160)
    original_status: str = Field(default="unknown", max_length=160)
    candidate_status: str = Field(default="unavailable", max_length=160)
    editorial_status: str = Field(default="unavailable", max_length=160)
    completeness_status: ClipBriefCompletenessStatus = "unknown"
    evidence_status: str = Field(default="unknown", max_length=80)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(ge=0.0)
    candidate_rank: int | None = Field(default=None, ge=1)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    human_action_required: bool = False
    blocker_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    missing_required_field_count: int = Field(default=0, ge=0)
    missing_optional_field_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=16)
    source_module_ids: list[str] = Field(default_factory=list, max_length=16)
    source_record_ids: list[str] = Field(default_factory=list, max_length=24)
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=24)
    priority_tier: int = Field(default=0, ge=0, le=999)
    priority_reason: str = Field(default="", max_length=160)
    deterministic_sort_key: str = Field(min_length=1, max_length=240)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaClipBriefFieldProjectionV1(BobaContract):
    field_projection_id: str = Field(min_length=1, max_length=180)
    brief_snapshot_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=180)
    field_path: str = Field(min_length=1, max_length=240)
    field_display_name: str = Field(min_length=1, max_length=160)
    field_category: ClipBriefFieldCategory = "unknown"
    original_value: Any = None
    original_value_digest: str = Field(default="", max_length=64)
    value_type: str = Field(default="unknown", max_length=40)
    required_by_owner_schema: bool = False
    present: bool = False
    empty: bool = False
    unavailable: bool = False
    truncated_for_display: bool = False
    source_owned: bool = True
    advisory: bool = False
    human_editable: bool = False
    current: bool = True
    stale: bool = False
    bounded_explanation: str = Field(default="", max_length=600)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefSectionProjectionV1(BobaContract):
    section_projection_id: str = Field(min_length=1, max_length=180)
    brief_snapshot_id: str | None = None
    section_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    field_projection_ids: list[str] = Field(default_factory=list, max_length=_MAX_FIELD_PROJECTIONS)
    source_card_ids: list[str] = Field(default_factory=list, max_length=_MAX_SOURCE_CARDS)
    evidence_link_ids: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_LINKS)
    visible: bool = True
    empty: bool = False
    unavailable: bool = False
    required_field_count: int = Field(default=0, ge=0)
    present_required_field_count: int = Field(default=0, ge=0)
    optional_field_count: int = Field(default=0, ge=0)
    present_optional_field_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    limitation_count: int = Field(default=0, ge=0)
    collapsed_by_default: bool = False
    bounded_empty_message: str = Field(default="", max_length=400)
    bounded_unavailable_message: str = Field(default="", max_length=400)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefSourceCardV1(BobaContract):
    source_card_id: str = Field(min_length=1, max_length=180)
    brief_snapshot_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=160)
    authority_domain: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    source_schema_id: str = Field(default="unknown", max_length=180)
    source_schema_version: str = Field(default="unknown", max_length=80)
    title: str = Field(min_length=1, max_length=240)
    original_status: str = Field(default="unknown", max_length=160)
    original_decision: str | None = Field(default=None, max_length=200)
    bounded_summary: str = Field(default="", max_length=900)
    easy_explanation: str = Field(default="", max_length=900)
    current: bool = False
    stale: bool = False
    historical: bool = False
    expired: bool = False
    invalidated: bool = False
    superseded: bool = False
    authoritative: bool = True
    advisory_only: bool = False
    blocking: bool = False
    human_review_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefEvidenceLinkV1(BobaContract):
    evidence_link_id: str = Field(min_length=1, max_length=180)
    brief_snapshot_id: str | None = None
    brief_field_path: str = Field(min_length=1, max_length=240)
    evidence_type: str = Field(min_length=1, max_length=120)
    source_module_id: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(default="", max_length=64)
    candidate_id: str | None = None
    clip_id: str | None = None
    transcript_segment_ids: list[str] = Field(default_factory=list, max_length=32)
    artifact_reference_ids: list[str] = Field(default_factory=list, max_length=24)
    source_start_seconds: float | None = None
    source_end_seconds: float | None = None
    exact_identity_match: bool = False
    digest_match: bool = False
    current: bool = False
    stale: bool = False
    missing: bool = False
    authoritative: bool = True
    advisory: bool = False
    bounded_summary: str = Field(default="", max_length=600)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefCompletenessV1(BobaContract):
    completeness_record_id: str = Field(min_length=1, max_length=180)
    brief_snapshot_id: str | None = None
    owner_schema_id: str = Field(default="unknown", max_length=180)
    owner_schema_version: str = Field(default="unknown", max_length=80)
    required_field_paths: list[str] = Field(default_factory=list, max_length=_MAX_FIELD_PROJECTIONS)
    present_required_field_paths: list[str] = Field(
        default_factory=list, max_length=_MAX_FIELD_PROJECTIONS
    )
    missing_required_field_paths: list[str] = Field(
        default_factory=list, max_length=_MAX_FIELD_PROJECTIONS
    )
    optional_field_paths: list[str] = Field(default_factory=list, max_length=_MAX_FIELD_PROJECTIONS)
    present_optional_field_paths: list[str] = Field(
        default_factory=list, max_length=_MAX_FIELD_PROJECTIONS
    )
    missing_optional_field_paths: list[str] = Field(
        default_factory=list, max_length=_MAX_FIELD_PROJECTIONS
    )
    required_field_count: int = Field(default=0, ge=0)
    present_required_field_count: int = Field(default=0, ge=0)
    optional_field_count: int = Field(default=0, ge=0)
    present_optional_field_count: int = Field(default=0, ge=0)
    required_completion_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    optional_completion_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    completeness_status: ClipBriefCompletenessStatus = "unknown"
    complete_for_owner_schema: bool = False
    creative_quality_assessed: Literal[False] = False
    technical_quality_assessed: Literal[False] = False
    blocking_reasons: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Completeness means only that required owner-schema fields are "
            "present. It is not a creative, technical, safety or approval "
            "judgement, and it does not mean the brief is ready to render or "
            "publish.",
        ],
        max_length=16,
    )


class BobaClipBriefConflictV1(BobaContract):
    conflict_record_id: str = Field(min_length=1, max_length=180)
    brief_snapshot_id: str | None = None
    conflict_type: ClipBriefConflictType = "unknown"
    severity: str = Field(default="warning", max_length=80)
    brief_field_paths: list[str] = Field(default_factory=list, max_length=16)
    source_card_ids: list[str] = Field(default_factory=list, max_length=16)
    source_record_ids: list[str] = Field(default_factory=list, max_length=16)
    value_a: str = Field(default="", max_length=900)
    value_b: str = Field(default="", max_length=900)
    same_candidate: bool = False
    same_clip: bool = False
    same_workflow_run: bool = False
    current_records: bool = False
    explicit_supersession_found: bool = False
    resolved: bool = False
    resolution_source_id: str | None = None
    blocks_review_action: bool = False
    human_review_required: bool = False
    bounded_summary: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Conflicts are reported only when records refer to the same exact "
            "identity. They are never resolved by averaging confidence.",
        ],
        max_length=16,
    )


class BobaClipBriefComparisonV1(BobaContract):
    comparison_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    brief_ids: list[str] = Field(min_length=2, max_length=MAX_COMPARISON_BRIEFS)
    candidate_ids: list[str] = Field(default_factory=list, max_length=MAX_COMPARISON_BRIEFS)
    created_at: str = Field(default_factory=now_iso)
    comparison_type: ClipBriefComparisonType = "side_by_side"
    same_candidate: bool = False
    same_clip: bool = False
    same_workflow_run: bool = False
    brief_snapshot_ids: list[str] = Field(default_factory=list, max_length=MAX_COMPARISON_BRIEFS)
    field_comparisons: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    section_comparisons: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    completeness_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    evidence_coverage_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    source_window_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    duration_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    warning_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    limitation_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    current_brief_ids: list[str] = Field(default_factory=list, max_length=MAX_COMPARISON_BRIEFS)
    historical_brief_ids: list[str] = Field(default_factory=list, max_length=MAX_COMPARISON_BRIEFS)
    no_automatic_winner: Literal[True] = True
    bounded_summary: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefActionDescriptorV1(BobaContract):
    action_descriptor_id: str = Field(min_length=1, max_length=180)
    display_name: str = Field(min_length=1, max_length=160)
    action_class: str = Field(min_length=1, max_length=120)
    owning_module_id: str = Field(min_length=1, max_length=160)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    supported_brief_states: list[str] = Field(default_factory=list, max_length=16)
    allowed_decision_values: list[str] = Field(default_factory=list, max_length=16)
    requires_reason: bool = False
    maximum_reason_length: int = Field(default=_MAX_REASON_LENGTH, ge=0, le=1_200)
    requires_confirmation: bool = True
    requires_current_snapshot: bool = True
    requires_workflow_revision: bool = False
    requires_brief_digest: bool = True
    requires_source_record_digests: bool = True
    requires_reviewer_context: bool = True
    authoritative: bool = False
    destructive: bool = False
    execution_capable: bool = False
    upload_or_publication: bool = False
    allowed_in_v1: bool = False
    availability: Literal["available", "unavailable"] = "unavailable"
    consequences: list[str] = Field(default_factory=list, max_length=12)
    does_not_do: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefActionRequestV1(BobaContract):
    clip_brief_action_request_id: str = Field(min_length=1, max_length=180)
    clip_brief_review_session_id: str = Field(min_length=1, max_length=180)
    brief_snapshot_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    candidate_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=160)
    requested_at: str = Field(default_factory=now_iso)
    expires_at: str
    reviewer_context_id: str = Field(min_length=1, max_length=160)
    action_descriptor_id: str = Field(min_length=1, max_length=180)
    owning_module_id: str = Field(min_length=1, max_length=160)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    decision_value: str | None = Field(default=None, max_length=160)
    bounded_reason: str = Field(default="", max_length=_MAX_REASON_LENGTH)
    expected_project_snapshot_digest: str = Field(min_length=64, max_length=64)
    expected_workflow_revision: int = Field(default=0, ge=0)
    expected_brief_digest: str = Field(min_length=64, max_length=64)
    expected_source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=24)
    confirmation_context_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=180)
    confirmed: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefActionReceiptV1(BobaContract):
    clip_brief_action_receipt_id: str = Field(min_length=1, max_length=180)
    clip_brief_action_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=160)
    candidate_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    owning_module_id: str = Field(min_length=1, max_length=160)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    submitted_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None
    accepted_by_owner: bool = False
    canonical_request_id: str | None = None
    canonical_record_id: str | None = None
    canonical_record_digest: str | None = None
    canonical_status: str = "pending"
    authoritative_state_changed: bool = False
    canonical_refresh_required: bool = True
    stale_state_rejected: bool = False
    duplicate_request_reused: bool = False
    error_code: str | None = None
    bounded_error_message: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefSnapshotV1(BobaContract):
    brief_snapshot_id: str = Field(min_length=1, max_length=180)
    clip_brief_review_session_id: str = Field(min_length=1, max_length=180)
    brief_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    candidate_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=160)
    created_at: str = Field(default_factory=now_iso)
    refreshed_at: str = Field(default_factory=now_iso)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    brief_digest: str = Field(min_length=64, max_length=64)
    source_record_references: list[dict[str, str]] = Field(default_factory=list, max_length=24)
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=24)
    field_projection_ids: list[str] = Field(
        default_factory=list, max_length=_MAX_FIELD_PROJECTIONS
    )
    section_projection_ids: list[str] = Field(
        default_factory=list, max_length=_MAX_SECTION_PROJECTIONS
    )
    source_card_ids: list[str] = Field(default_factory=list, max_length=_MAX_SOURCE_CARDS)
    evidence_link_ids: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_LINKS)
    completeness_record_id: str = Field(default="", max_length=180)
    conflict_record_ids: list[str] = Field(default_factory=list, max_length=_MAX_CONFLICTS)
    comparison_ids: list[str] = Field(default_factory=list, max_length=8)
    brief_status: str = Field(default="unknown", max_length=160)
    candidate_status: str = Field(default="unavailable", max_length=160)
    editorial_status: str = Field(default="unavailable", max_length=160)
    rights_status: str = Field(default="unavailable", max_length=160)
    workflow_status: str = Field(default="unavailable", max_length=160)
    artifact_status: str = Field(default="unavailable", max_length=160)
    validation_status: str = Field(default="unavailable", max_length=160)
    human_review_status: str = Field(default="unavailable", max_length=160)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    missing_required_field_count: int = Field(default=0, ge=0)
    missing_optional_field_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    limitation_count: int = Field(default=0, ge=0)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=16)
    confirmation_context_digest: str = Field(min_length=64, max_length=64)
    snapshot_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaClipBriefReviewEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    brief_id: str | None = None
    candidate_id: str | None = None
    clip_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=160)
    source_event_id: str | None = None
    source_sequence: int | None = Field(default=None, ge=0)
    created_at: str | None = None
    received_at: str = Field(default_factory=now_iso)
    event_type: str = Field(min_length=1, max_length=160)
    severity: str = Field(default="informational", max_length=80)
    technical_message: str = Field(default="", max_length=900)
    easy_message: str = Field(default="", max_length=900)
    confirmed_fact: str = Field(default="", max_length=900)
    assessment: str = Field(default="", max_length=900)
    progress_current: int | None = Field(default=None, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    progress_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    requires_attention: bool = False
    canonical: bool = True
    replayed: bool = False
    represents_work: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefReviewTimelineEntryV1(BobaContract):
    timeline_entry_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    brief_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_event_id: str | None = None
    event_type: str = Field(default="canonical_event", max_length=160)
    occurred_at: str | None = None
    timestamp_precision: Literal["exact", "source", "unknown"] = "unknown"
    sequence: int | None = Field(default=None, ge=0)
    confirmed_order: bool = False
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(default="", max_length=900)
    confirmed_fact: str = Field(default="", max_length=900)
    source_assessment: str = Field(default="", max_length=900)
    severity: str = Field(default="informational", max_length=80)
    current: bool = True
    historical: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefReviewNotificationV1(BobaContract):
    notification_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    brief_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=180)
    notification_type: str = Field(min_length=1, max_length=120)
    severity: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    bounded_message: str = Field(default="", max_length=900)
    created_at: str = Field(default_factory=now_iso)
    requires_attention: bool = False
    human_action_required: bool = False
    acknowledged: bool = False
    current: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefReviewSummaryV1(BobaContract):
    total_brief_count: int = Field(default=0, ge=0)
    current_brief_count: int = Field(default=0, ge=0)
    stale_brief_count: int = Field(default=0, ge=0)
    historical_brief_count: int = Field(default=0, ge=0)
    superseded_brief_count: int = Field(default=0, ge=0)
    complete_brief_count: int = Field(default=0, ge=0)
    missing_required_field_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    pending_human_review_count: int = Field(default=0, ge=0)
    blocked_brief_count: int = Field(default=0, ge=0)
    current_selected_brief_id: str | None = None
    current_comparison_brief_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_BRIEFS
    )
    safest_next_review_action: str | None = None
    required_human_actions: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaClipBriefReviewSignalUsageV1(BobaContract):
    canonical_clip_brief_records: bool = False
    canonical_candidate_records: bool = False
    canonical_editorial_records: bool = False
    canonical_creative_records: bool = False
    canonical_hook_retention_records: bool = False
    canonical_caption_motion_records: bool = False
    canonical_music_mood_records: bool = False
    canonical_workflow_records: bool = False
    canonical_rights_records: bool = False
    canonical_artifact_records: bool = False
    review_ui_integration: bool = True
    candidate_review_integration: bool = True
    exact_identity_validation: bool = True
    exact_digest_validation: bool = True
    stale_snapshot_protection: bool = True
    canonical_action_receipts: bool = True
    truthful_events: bool = True
    brief_generated_by_panel: bool = False
    brief_regenerated_by_panel: bool = False
    brief_rewritten_by_panel: bool = False
    hidden_quality_score_created: bool = False
    hidden_virality_score_created: bool = False
    brief_approved_locally: bool = False
    brief_rejected_locally: bool = False
    optimistic_authority_update_used: bool = False
    arbitrary_module_used: bool = False
    arbitrary_operation_used: bool = False
    arbitrary_url_used: bool = False
    arbitrary_path_used: bool = False
    external_media_used: bool = False
    untrusted_html_used: bool = False
    command_execution_used: bool = False
    shell_execution_used: bool = False
    git_execution_used: bool = False
    ffmpeg_execution_used: bool = False
    media_generation_used: bool = False
    source_media_modified: bool = False
    accepted_output_modified: bool = False
    workflow_transition_used: bool = False
    approval_created_locally: bool = False
    safety_decision_created_locally: bool = False
    upload_used: bool = False
    publication_used: bool = False
    external_analytics_used: bool = False
    rights_bypass_used: bool = False
    safety_bypass_used: bool = False
    destructive_action_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaClipBriefReviewSetV1(BobaContract):
    schema_version: Literal["boba_clip_brief_review_v1"] = "boba_clip_brief_review_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    registry_snapshots: list[BobaClipBriefRegistrySnapshotV1] = Field(
        default_factory=list, max_length=8
    )
    review_sessions: list[BobaClipBriefReviewSessionV1] = Field(
        default_factory=list, max_length=16
    )
    brief_references: list[BobaClipBriefReferenceV1] = Field(
        default_factory=list, max_length=MAX_LOADED_BRIEFS
    )
    brief_queue_items: list[BobaClipBriefQueueItemV1] = Field(
        default_factory=list, max_length=MAX_LOADED_BRIEFS
    )
    brief_snapshots: list[BobaClipBriefSnapshotV1] = Field(default_factory=list, max_length=16)
    field_projections: list[BobaClipBriefFieldProjectionV1] = Field(
        default_factory=list, max_length=_MAX_FIELD_PROJECTIONS
    )
    section_projections: list[BobaClipBriefSectionProjectionV1] = Field(
        default_factory=list, max_length=_MAX_SECTION_PROJECTIONS
    )
    source_cards: list[BobaClipBriefSourceCardV1] = Field(
        default_factory=list, max_length=_MAX_SOURCE_CARDS
    )
    evidence_links: list[BobaClipBriefEvidenceLinkV1] = Field(
        default_factory=list, max_length=_MAX_EVIDENCE_LINKS
    )
    completeness_records: list[BobaClipBriefCompletenessV1] = Field(
        default_factory=list, max_length=16
    )
    conflict_records: list[BobaClipBriefConflictV1] = Field(
        default_factory=list, max_length=_MAX_CONFLICTS
    )
    comparisons: list[BobaClipBriefComparisonV1] = Field(default_factory=list, max_length=8)
    action_requests: list[BobaClipBriefActionRequestV1] = Field(
        default_factory=list, max_length=64
    )
    action_receipts: list[BobaClipBriefActionReceiptV1] = Field(
        default_factory=list, max_length=64
    )
    timeline_entries: list[BobaClipBriefReviewTimelineEntryV1] = Field(
        default_factory=list, max_length=MAX_TIMELINE_ENTRIES
    )
    events: list[BobaClipBriefReviewEventV1] = Field(default_factory=list, max_length=_MAX_EVENTS)
    notifications: list[BobaClipBriefReviewNotificationV1] = Field(
        default_factory=list, max_length=64
    )
    review_summary: BobaClipBriefReviewSummaryV1 = Field(
        default_factory=BobaClipBriefReviewSummaryV1
    )
    signal_usage: BobaClipBriefReviewSignalUsageV1 = Field(
        default_factory=BobaClipBriefReviewSignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


CLIP_BRIEF_QUEUE_PRIORITY_TIERS: tuple[tuple[int, str], ...] = (
    (10, "selected_candidate_brief_with_critical_rights_or_safety_block"),
    (20, "identity_or_source_window_conflict"),
    (30, "requires_exact_human_review"),
    (40, "missing_required_owner_schema_fields"),
    (50, "missing_required_source_evidence"),
    (60, "stale_brief_for_current_selected_candidate"),
    (70, "current_brief_for_source_selected_candidate"),
    (80, "current_brief_with_warnings_or_limitations"),
    (90, "other_current_brief"),
    (100, "rejected_candidate_brief"),
    (110, "superseded_brief"),
    (120, "historical_brief"),
)

# Fixed evidence sources, each read through a fixed store loader.
_BRIEF_SOURCES: tuple[tuple[str, str, str, str, bool], ...] = (
    ("clip_brief", "Clip Brief Generator", "clip_brief", "load_clip_briefs", False),
    (
        "clip_discovery",
        "Candidate Clip Discovery",
        "candidate_discovery",
        "load_candidate_clip_discovery",
        False,
    ),
    ("clip_ranking", "Clip Ranking", "candidate_rank", "load_clip_ranking", False),
    (
        "editorial_decision",
        "Editorial Decision",
        "editorial_selection",
        "load_editorial_decisions",
        False,
    ),
    ("explanation", "Explanation Engine", "explanation", "load_explanations", True),
    (
        "creative_director",
        "Creative Director",
        "creative_direction",
        "load_creative_direction_v2",
        True,
    ),
    ("hook_retention", "Hook + Retention Brain", "hook_retention", "load_hook_retention", True),
    ("caption_motion", "Caption + Motion Brain", "caption_motion", "load_caption_motion", True),
    ("music_mood", "Music Mood Brain", "music_mood", "load_music_mood", True),
    (
        "rights_permission_gate",
        "Rights + Permission Gate",
        "rights",
        "load_rights_permission_gate",
        False,
    ),
    ("safety_gate", "Safety Gate", "safety", "load_boba_safety_gate", False),
    (
        "workflow_controller",
        "Workflow Controller",
        "workflow",
        "load_boba_workflow_controller",
        False,
    ),
    (
        "artifact_inspector",
        "Artifact Inspector",
        "artifacts",
        "load_boba_artifact_inspector",
        False,
    ),
    ("validator_runner", "Validator Runner", "validation", "load_boba_validator_runner", False),
)

_REQUIRED_SOURCE_IDS = ("clip_brief",)

# The owner schema, transcribed verbatim from ``BobaClipBriefV1``. This table is
# fixed source code: a browser request can never add, remove or reclassify a
# field, and no field is listed that the owner does not define.
#   (field_path, display name, category, required by owner schema, section)
_OWNER_SCHEMA_FIELDS: tuple[tuple[str, str, ClipBriefFieldCategory, bool, str], ...] = (
    ("brief_id", "Brief ID", "identity", True, "identity"),
    ("project_id", "Project ID", "identity", True, "identity"),
    ("candidate_id", "Candidate ID", "identity", True, "identity"),
    ("ranked_clip_id", "Ranked clip ID", "identity", True, "identity"),
    ("brief_title", "Brief title", "overview", True, "overview"),
    ("final_clip_angle", "Final clip angle", "objective", True, "overview"),
    ("target_viewer_feeling", "Target viewer feeling", "audience", True, "overview"),
    ("production_priority", "Production priority", "metadata", True, "overview"),
    ("render_readiness", "Render readiness", "metadata", True, "overview"),
    ("confidence", "Owner confidence", "metadata", True, "overview"),
    ("source_window.start_seconds", "Source start", "source_window", True, "source_window"),
    ("source_window.end_seconds", "Source end", "source_window", True, "source_window"),
    ("source_window.duration_seconds", "Target duration", "duration", True, "source_window"),
    ("hook_instruction", "Hook instruction", "hook", True, "hook"),
    (
        "opening_three_second_instruction",
        "Opening three seconds",
        "hook",
        True,
        "hook",
    ),
    ("story_instruction", "Story instruction", "narrative", True, "story"),
    ("cut_instruction", "Cut instruction", "narrative", True, "story"),
    ("retention_instruction", "Retention instruction", "narrative", True, "story"),
    ("caption_instruction", "Caption instruction", "caption_guidance", True, "creative"),
    ("motion_instruction", "Motion instruction", "motion_guidance", True, "creative"),
    ("audio_instruction", "Audio instruction", "music_guidance", True, "creative"),
    ("sfx_instruction", "SFX instruction", "music_guidance", True, "creative"),
    ("risk_fixes", "Risk fixes", "warning", False, "warnings"),
    ("editor_checklist", "Editor checklist", "evidence", False, "checklist"),
    ("human_review_notes", "Human review notes", "metadata", False, "checklist"),
    ("warnings", "Warnings", "warning", False, "warnings"),
    ("limitations", "Limitations", "limitation", False, "limitations"),
)

# Sections are built only from fields the owner schema actually defines. There is
# deliberately no "beats" or "ending" section: BobaClipBriefV1 defines neither.
_SECTION_DEFINITIONS: tuple[tuple[str, str, bool], ...] = (
    ("identity", "Identity", False),
    ("overview", "Brief Overview", False),
    ("source_window", "Exact Source Window and Target Duration", False),
    ("hook", "Hook", False),
    ("story", "Story, Cuts and Retention", False),
    ("creative", "Caption, Motion and Audio Guidance", False),
    ("checklist", "Editor Checklist and Review Notes", True),
    ("warnings", "Warnings and Risk Fixes", True),
    ("limitations", "Limitations", True),
)

_INSTRUCTION_FIELDS = frozenset(
    {
        "hook_instruction",
        "opening_three_second_instruction",
        "story_instruction",
        "cut_instruction",
        "retention_instruction",
        "caption_instruction",
        "motion_instruction",
        "audio_instruction",
        "sfx_instruction",
    }
)

_LIFECYCLE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("selected_briefs", "selected"),
    ("backup_briefs", "backup"),
    ("blocked_briefs", "blocked"),
)


def build_fixed_clip_brief_source_registry() -> dict[str, dict[str, Any]]:
    """Return the fixed clip-brief evidence source registry."""
    registry: dict[str, dict[str, Any]] = {}
    for module_id, title, domain, loader_name, advisory in _BRIEF_SOURCES:
        if module_id in registry:
            raise ValidationError("Duplicate BOBA clip brief review source descriptor.")
        registry[module_id] = {
            "source_id": module_id,
            "title": title,
            "authority_domain": domain,
            "loader": loader_name,
            "advisory_only": advisory,
            "required": module_id in _REQUIRED_SOURCE_IDS,
        }
    return registry


def build_fixed_clip_brief_section_registry() -> dict[str, dict[str, Any]]:
    """Return the fixed section registry derived from the owner schema."""
    registry: dict[str, dict[str, Any]] = {}
    for section_id, title, collapsed in _SECTION_DEFINITIONS:
        if section_id in registry:
            raise ValidationError("Duplicate BOBA clip brief review section descriptor.")
        fields = [row for row in _OWNER_SCHEMA_FIELDS if row[4] == section_id]
        registry[section_id] = {
            "section_id": section_id,
            "title": title,
            "collapsed_by_default": collapsed,
            "field_paths": [row[0] for row in fields],
            "required_field_paths": [row[0] for row in fields if row[3]],
        }
    return registry


def owner_schema_required_field_paths() -> tuple[str, ...]:
    """Required field paths, fixed by the owner model and never by a request."""
    return tuple(row[0] for row in _OWNER_SCHEMA_FIELDS if row[3])


def owner_schema_optional_field_paths() -> tuple[str, ...]:
    return tuple(row[0] for row in _OWNER_SCHEMA_FIELDS if not row[3])


def build_fixed_clip_brief_action_registry() -> dict[str, BobaClipBriefActionDescriptorV1]:
    """Return the fixed action registry.

    Only actions with a real, already-implemented canonical owning operation are
    available. Approval, rejection, revision and regeneration are declared with
    their limitation rather than wired to an invented owner.
    """
    definitions = [
        BobaClipBriefActionDescriptorV1(
            action_descriptor_id="clip_brief_action_submit_feedback_v1",
            display_name="Submit clip brief feedback",
            action_class="advisory_creator_feedback",
            owning_module_id="creator_learning",
            owning_operation_id="record_creator_feedback_event",
            supported_brief_states=["current", "stale", "historical"],
            allowed_decision_values=["approved", "rejected", "liked", "disliked", "chose"],
            requires_reason=True,
            maximum_reason_length=_MAX_REASON_LENGTH,
            requires_confirmation=True,
            requires_current_snapshot=True,
            requires_brief_digest=True,
            requires_source_record_digests=True,
            requires_reviewer_context=True,
            authoritative=False,
            allowed_in_v1=True,
            availability="available",
            consequences=[
                "Records a bounded, reversible creator-feedback event owned by "
                "Creator Learning against this exact clip brief.",
            ],
            does_not_do=[
                "Does not approve or reject the clip brief.",
                "Does not change any field of the persisted brief.",
                "Does not regenerate or rewrite the brief.",
                "Does not change the candidate or editorial decision.",
                "Does not grant Rights or create a Safety allowance.",
                "Does not render, advance the workflow, upload or publish.",
            ],
            limitations=[
                "Creator Learning feedback is explicitly advisory; it never "
                "overrides source truth or safety.",
            ],
        ),
        BobaClipBriefActionDescriptorV1(
            action_descriptor_id="clip_brief_action_record_review_note_v1",
            display_name="Record clip brief review note",
            action_class="advisory_creator_note",
            owning_module_id="creator_learning",
            owning_operation_id="record_creator_feedback_event",
            supported_brief_states=["current", "stale", "historical", "superseded"],
            allowed_decision_values=["noted"],
            requires_reason=True,
            maximum_reason_length=_MAX_REASON_LENGTH,
            requires_confirmation=True,
            requires_current_snapshot=False,
            requires_brief_digest=True,
            requires_source_record_digests=False,
            requires_reviewer_context=True,
            authoritative=False,
            allowed_in_v1=True,
            availability="available",
            consequences=[
                "Records a bounded reviewer note owned by Creator Learning "
                "against this exact clip brief.",
            ],
            does_not_do=[
                "Does not become part of the canonical clip brief.",
                "Does not approve, reject or revise the brief.",
            ],
            limitations=["A review note is advisory metadata, not a decision."],
        ),
        BobaClipBriefActionDescriptorV1(
            action_descriptor_id="clip_brief_action_approve_v1",
            display_name="Approve exact clip brief",
            action_class="human_brief_approval",
            owning_module_id="clip_brief",
            owning_operation_id="unavailable_no_canonical_brief_approval_operation",
            supported_brief_states=["current"],
            allowed_decision_values=["approve"],
            requires_reason=True,
            requires_workflow_revision=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Clip Brief Generator owns the brief but exposes no operation "
                "that records a human approval for one exact brief.",
                "Its only entry point regenerates the whole brief set from "
                "signals, which would make this panel a second brief generator.",
                "Unavailable in V1. No substitute owner was invented.",
            ],
        ),
        BobaClipBriefActionDescriptorV1(
            action_descriptor_id="clip_brief_action_reject_v1",
            display_name="Reject exact clip brief",
            action_class="human_brief_rejection",
            owning_module_id="clip_brief",
            owning_operation_id="unavailable_no_canonical_brief_rejection_operation",
            supported_brief_states=["current"],
            allowed_decision_values=["reject"],
            requires_reason=True,
            requires_workflow_revision=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "No owning module records a human rejection for a single brief.",
                "The brief lifecycle bucket is owned by Clip Brief Generator "
                "and is recomputed, not edited.",
            ],
        ),
        BobaClipBriefActionDescriptorV1(
            action_descriptor_id="clip_brief_action_request_revision_v1",
            display_name="Request clip brief revision",
            action_class="human_revision_request",
            owning_module_id="clip_brief",
            owning_operation_id="unavailable_no_canonical_revision_request_operation",
            supported_brief_states=["current"],
            allowed_decision_values=["request_revision"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Clip briefs carry no revision identity, so a revision request "
                "has nothing canonical to bind to.",
                "No owning operation records a per-brief revision request.",
            ],
        ),
        BobaClipBriefActionDescriptorV1(
            action_descriptor_id="clip_brief_action_request_regeneration_v1",
            display_name="Request clip brief regeneration",
            action_class="human_regeneration_request",
            owning_module_id="clip_brief",
            owning_operation_id="unavailable_no_canonical_single_brief_regeneration",
            supported_brief_states=["current"],
            allowed_decision_values=["request_regeneration"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Regeneration would re-run Clip Brief Generator for the whole "
                "project set, which this panel must never do.",
                "There is no single-brief regeneration operation.",
            ],
        ),
    ]
    registry: dict[str, BobaClipBriefActionDescriptorV1] = {}
    for descriptor in definitions:
        if descriptor.action_descriptor_id in registry:
            raise ValidationError("Duplicate BOBA clip brief review action descriptor.")
        if descriptor.upload_or_publication or descriptor.execution_capable:
            raise ValidationError(
                "Clip Brief Review V1 cannot expose execution or publication actions."
            )
        if descriptor.destructive:
            raise ValidationError("Clip Brief Review V1 cannot expose destructive actions.")
        if descriptor.availability == "available" and descriptor.authoritative:
            raise ValidationError(
                "Clip Brief Review V1 exposes no authoritative clip brief action."
            )
        registry[descriptor.action_descriptor_id] = descriptor
    return registry


class BobaClipBriefReviewV1:
    """Project canonical clip-brief records for human review.

    Every field, status and decision surfaced here is copied verbatim from the
    module that owns it. This class computes only presentation projections:
    field presence against the fixed owner schema, evidence links from persisted
    relationships, exact-identity conflicts, and a deterministic priority tier.
    None of those is a quality judgement.
    """

    def __init__(self, store: BobaMemoryStore, integration: BobaIntegration) -> None:
        self.store = store
        self.integration = integration

    # ------------------------------------------------------------------
    # Source access
    # ------------------------------------------------------------------
    def _source_payload(self, source_id: str, project_id: str) -> dict[str, Any]:
        registry = build_fixed_clip_brief_source_registry()
        descriptor = registry.get(source_id)
        if descriptor is None:
            raise ValidationError("Unknown BOBA clip brief review source.")
        loader = getattr(self.store, str(descriptor["loader"]), None)
        if loader is None:
            return {}
        try:
            return _as_mapping(loader(project_id))
        except (ValidationError, NotFoundError, OSError):
            return {}

    def _brief_rows(self, project_id: str) -> list[tuple[dict[str, Any], str, int]]:
        """Return (brief, lifecycle bucket, creation index) in owner order."""
        payload = self._source_payload("clip_brief", project_id)
        rows: list[tuple[dict[str, Any], str, int]] = []
        index = 0
        for key, bucket in _LIFECYCLE_BUCKETS:
            entries = payload.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                rows.append((_as_mapping(entry), bucket, index))
                index += 1
                if index >= MAX_LOADED_BRIEFS:
                    return rows
        return rows

    def _candidate_rows(self, project_id: str) -> dict[str, dict[str, Any]]:
        payload = self._source_payload("clip_discovery", project_id)
        rows = payload.get("candidates")
        result: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, Mapping):
                    mapped = _as_mapping(row)
                    key = _safe_text(mapped.get("candidate_id"), 128)
                    if key:
                        result[key] = mapped
        return result

    def _ranked_rows(self, project_id: str) -> dict[str, dict[str, Any]]:
        payload = self._source_payload("clip_ranking", project_id)
        rows = payload.get("ranked_candidates")
        result: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, Mapping):
                    mapped = _as_mapping(row)
                    key = _safe_text(mapped.get("candidate_id"), 128)
                    if key:
                        result[key] = mapped
        return result

    def _editorial_rows(self, project_id: str) -> dict[str, dict[str, Any]]:
        payload = self._source_payload("editorial_decision", project_id)
        rows = payload.get("decisions")
        result: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, Mapping):
                    mapped = _as_mapping(row)
                    key = _safe_text(mapped.get("candidate_id"), 128)
                    if key:
                        result[key] = mapped
        return result

    @staticmethod
    def _field_value(brief: Mapping[str, Any], field_path: str) -> tuple[object, bool]:
        """Resolve a dotted owner-schema path. Returns (value, path_exists)."""
        current: object = brief
        for part in field_path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return (None, False)
            current = current[part]
        return (current, True)

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def build_clip_brief_review_registry(self, project_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        sources = build_fixed_clip_brief_source_registry()
        sections = build_fixed_clip_brief_section_registry()
        actions = build_fixed_clip_brief_action_registry()
        available = [key for key in sources if self._source_payload(key, project_id)]
        unavailable = [key for key in sources if key not in available]
        source_rows = [
            {key: value for key, value in item.items() if key != "loader"}
            for item in sources.values()
        ]
        action_rows = [item.model_dump(mode="json") for item in actions.values()]
        section_rows = list(sections.values())
        payload = {
            "sources": source_rows,
            "sections": section_rows,
            "actions": action_rows,
            "required_fields": list(owner_schema_required_field_paths()),
            "optional_fields": list(owner_schema_optional_field_paths()),
        }
        snapshot_id = _stable_id("clip_brief_registry", "v1", _digest(payload))
        stored = self.store.load_boba_clip_brief_review_registry(project_id, snapshot_id)
        registry = (
            BobaClipBriefRegistrySnapshotV1.model_validate(stored)
            if isinstance(stored, Mapping)
            else BobaClipBriefRegistrySnapshotV1(
                registry_snapshot_id=snapshot_id,
                brief_source_ids=list(sources),
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
                section_descriptor_ids=list(sections),
                registry_digest=_digest(payload),
                limitations=[
                    "The registry is fixed source code; browser requests cannot "
                    "add sources, sections, fields, modules, operations, URLs, "
                    "paths or commands.",
                    "The owner schema field list is transcribed from "
                    "BobaClipBriefV1 and is never configured per request.",
                    "Clip Brief Review V1 exposes no authoritative brief "
                    "approval, rejection, revision or regeneration action.",
                ],
            )
        )
        if not isinstance(stored, Mapping):
            self.store.save_boba_clip_brief_review_registry(
                project_id, snapshot_id, registry.model_dump(mode="json")
            )
        return {
            "registry_snapshot": registry.model_dump(mode="json"),
            "sources": source_rows,
            "sections": section_rows,
            "actions": action_rows,
            "required_field_paths": list(owner_schema_required_field_paths()),
            "optional_field_paths": list(owner_schema_optional_field_paths()),
            "supported_brief_schema_id": SUPPORTED_BRIEF_SCHEMA_ID,
        }

    def inspect_clip_brief_review_registry(self, project_id: str) -> dict[str, Any]:
        return self.build_clip_brief_review_registry(project_id)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_clip_brief_review_session(
        self,
        project_id: str,
        *,
        reviewer_context_id: str,
        selected_brief_id: str | None = None,
        expires_in_seconds: int = 3_600,
    ) -> BobaClipBriefReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(reviewer_context_id, "reviewer context id")
        if _SENSITIVE_KEY.search(reviewer_context_id):
            raise ValidationError("Reviewer context cannot contain credentials.")
        if selected_brief_id is not None:
            _safe_id(selected_brief_id, "brief id")
        session_id = f"clip_brief_review_session_{uuid4().hex}"
        now = datetime.now(UTC)
        session = BobaClipBriefReviewSessionV1(
            clip_brief_review_session_id=session_id,
            project_id=project_id,
            reviewer_context_id=reviewer_context_id,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(
                now + timedelta(seconds=max(60, min(expires_in_seconds, 28_800)))
            ).isoformat(),
            selected_brief_id=selected_brief_id,
            session_digest=_digest(
                {
                    "session_id": session_id,
                    "project_id": project_id,
                    "reviewer_context_id": reviewer_context_id,
                    "selected_brief_id": selected_brief_id,
                }
            ),
            limitations=[
                "Review sessions hold only UI state.",
                "local_annotations are review-session metadata and are never "
                "part of the canonical clip brief.",
            ],
        )
        self.store.save_boba_clip_brief_review_session(
            project_id, session_id, session.model_dump(mode="json")
        )
        return session

    def get_clip_brief_review_session(
        self, project_id: str, session_id: str
    ) -> BobaClipBriefReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(session_id, "clip brief review session id")
        raw = self.store.load_boba_clip_brief_review_session(project_id, session_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA clip brief review session is unavailable.")
        session = BobaClipBriefReviewSessionV1.model_validate(raw)
        if session.project_id != project_id:
            raise ValidationError("Clip brief review session belongs to another project.")
        expires_at = _parse_time(session.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            raise ValidationError("BOBA clip brief review session has expired.")
        return session

    def update_clip_brief_review_session(
        self, project_id: str, session_id: str, updates: Mapping[str, Any]
    ) -> BobaClipBriefReviewSessionV1:
        session = self.get_clip_brief_review_session(project_id, session_id)
        allowed = {
            "selected_brief_id",
            "selected_candidate_id",
            "comparison_brief_ids",
            "active_filter",
            "active_sort",
            "active_section_id",
            "show_historical",
            "show_technical_details",
            "show_source_evidence",
            "show_empty_optional_fields",
            "evidence_drawer_open",
            "timeline_drawer_open",
            "local_annotations",
        }
        unsafe = set(updates) - allowed
        if unsafe:
            raise ValidationError(
                "Clip brief review session update contains unsupported fields."
            )
        comparison = updates.get("comparison_brief_ids")
        if isinstance(comparison, list) and len(comparison) > MAX_COMPARISON_BRIEFS:
            raise ValidationError(
                f"At most {MAX_COMPARISON_BRIEFS} clip briefs may be compared."
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
        updated = BobaClipBriefReviewSessionV1.model_validate(payload)
        self.store.save_boba_clip_brief_review_session(
            project_id, session_id, updated.model_dump(mode="json")
        )
        return updated

    @staticmethod
    def _bounded_annotations(value: object) -> list[dict[str, str]]:
        """Bound and sanitise reviewer annotations. Never canonical brief text."""
        if not isinstance(value, list):
            return []
        rows: list[dict[str, str]] = []
        for entry in value[:32]:
            if not isinstance(entry, Mapping):
                continue
            text = _safe_text(entry.get("text"), MAX_ANNOTATION_LENGTH)
            if not text:
                continue
            if _SENSITIVE_KEY.search(text):
                raise ValidationError("Review annotations cannot contain credentials.")
            rows.append(
                {
                    "annotation_id": _safe_text(entry.get("annotation_id"), 120)
                    or _stable_id("clip_brief_annotation", text),
                    "field_path": _safe_text(entry.get("field_path"), 240),
                    "text": text,
                    "notice": "Review-session annotation — not part of the canonical clip brief.",
                }
            )
        return rows

    # ------------------------------------------------------------------
    # Brief references
    # ------------------------------------------------------------------
    def build_clip_brief_references(self, project_id: str) -> list[BobaClipBriefReferenceV1]:
        """Project every persisted brief with its exact owner identity."""
        _safe_id(project_id, "project id")
        payload = self._source_payload("clip_brief", project_id)
        if not payload:
            return []
        schema_id = _safe_text(payload.get("brief_version") or "unknown", 180)
        supported = schema_id == SUPPORTED_BRIEF_SCHEMA_ID
        source_id = _safe_text(payload.get("source_id"), 512)
        created_at = _safe_text(payload.get("created_at"), 80) or now_iso()
        record_digest = _digest(_safe_payload(payload))
        project_digest = self._project_snapshot_digest(project_id)
        workflow = _active_workflow_run(
            self._source_payload("workflow_controller", project_id)
        )
        run_id = _safe_text(workflow.get("workflow_run_id"), 180) or None
        stage_id = _safe_text(workflow.get("current_stage_instance_id"), 180) or None
        revision = self._workflow_revision(project_id)
        candidates = self._candidate_rows(project_id)

        references: list[BobaClipBriefReferenceV1] = []
        for brief, bucket, _index in self._brief_rows(project_id):
            brief_id = _safe_text(brief.get("brief_id"), 160)
            if not brief_id or not _SAFE_BRIEF_ID.fullmatch(brief_id):
                continue
            if _safe_text(brief.get("project_id"), 128) != project_id:
                # Cross-project brief records are never projected.
                continue
            candidate_id = _safe_text(brief.get("candidate_id"), 128)
            clip_id = _safe_text(brief.get("ranked_clip_id"), 128)
            if not candidate_id or not clip_id:
                continue
            window = _as_mapping(brief.get("source_window"))
            start = _seconds(window.get("start_seconds")) or 0.0
            end = _seconds(window.get("end_seconds")) or 0.0
            duration = _seconds(window.get("duration_seconds")) or 0.0
            warnings: list[str] = []
            if not supported:
                warnings.append(
                    f"Brief schema '{schema_id}' is not supported by this panel."
                )
            if candidate_id not in candidates:
                warnings.append(
                    "No canonical Candidate Clip Discovery record matches this "
                    "candidate identity."
                )
            references.append(
                BobaClipBriefReferenceV1(
                    brief_reference_id=_stable_id(
                        "clip_brief_reference", project_id, brief_id
                    ),
                    project_id=project_id,
                    source_id=source_id,
                    workflow_run_id=run_id,
                    stage_instance_id=stage_id,
                    candidate_id=candidate_id,
                    clip_id=clip_id,
                    brief_id=brief_id,
                    # The owner schema defines no revision identity, so it stays
                    # absent. It is never inferred from timestamps or filenames.
                    brief_revision_id=None,
                    source_record_id=schema_id,
                    source_record_digest=record_digest,
                    brief_schema_id=schema_id,
                    brief_schema_version=schema_id,
                    schema_supported=supported,
                    lifecycle_bucket=bucket,
                    project_snapshot_digest=project_digest,
                    workflow_revision=revision,
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=duration,
                    current=True,
                    # The owner persists no supersession or historical marker, so
                    # these stay false rather than being guessed.
                    superseded=False,
                    superseding_brief_id=None,
                    created_at=created_at,
                    warnings=warnings[:24],
                    limitations=[
                        "Clip briefs carry no revision identity and no "
                        "supersession field, so both remain absent.",
                        "The owner stores only one current brief set; there is "
                        "no historical brief archive.",
                    ],
                )
            )
        return references[:MAX_LOADED_BRIEFS]

    def _reference_for(self, project_id: str, brief_id: str) -> BobaClipBriefReferenceV1:
        _safe_id(brief_id, "brief id")
        for reference in self.build_clip_brief_references(project_id):
            if reference.brief_id == brief_id:
                return reference
        raise ValidationError(
            "BOBA clip brief is unknown, unavailable, or belongs to another project."
        )

    def _brief_record(self, project_id: str, brief_id: str) -> dict[str, Any]:
        for brief, _bucket, _index in self._brief_rows(project_id):
            if _safe_text(brief.get("brief_id"), 160) == brief_id:
                return brief
        raise ValidationError("BOBA clip brief record is unavailable.")

    def _workflow_revision(self, project_id: str) -> int:
        run = _active_workflow_run(self._source_payload("workflow_controller", project_id))
        revision = run.get("revision")
        return revision if isinstance(revision, int) and revision >= 0 else 0

    def _project_snapshot_digest(self, project_id: str) -> str:
        digests = {
            source_id: _digest(_safe_payload(self._source_payload(source_id, project_id)))
            for source_id in build_fixed_clip_brief_source_registry()
        }
        return _digest(digests)

    def _brief_digest(self, project_id: str, brief_id: str) -> str:
        try:
            brief = self._brief_record(project_id, brief_id)
        except ValidationError:
            return _digest({"brief_id": brief_id, "state": "unavailable"})
        candidate_id = _safe_text(brief.get("candidate_id"), 128)
        return _digest(
            {
                "brief": _safe_payload(brief),
                "candidate": _safe_payload(
                    self._candidate_rows(project_id).get(candidate_id, {})
                ),
                "editorial": _safe_payload(
                    self._editorial_rows(project_id).get(candidate_id, {})
                ),
            }
        )

    # ------------------------------------------------------------------
    # Field and section projections
    # ------------------------------------------------------------------
    def build_field_projections(
        self,
        project_id: str,
        brief_id: str,
        *,
        snapshot_id: str | None = None,
    ) -> list[BobaClipBriefFieldProjectionV1]:
        """Project only fields the owner schema defines, preserving each value."""
        reference = self._reference_for(project_id, brief_id)
        brief = self._brief_record(project_id, brief_id)
        safe_brief = _as_mapping(_safe_payload(brief))
        projections: list[BobaClipBriefFieldProjectionV1] = []
        for field_path, display, category, required, _section in _OWNER_SCHEMA_FIELDS:
            value, path_exists = self._field_value(safe_brief, field_path)
            present = path_exists and _is_present(value)
            empty = path_exists and _is_empty(value)
            display_value, truncated = _bounded_display(value)
            advisory = field_path in {
                "caption_instruction",
                "motion_instruction",
                "audio_instruction",
                "sfx_instruction",
            }
            projections.append(
                BobaClipBriefFieldProjectionV1(
                    field_projection_id=_stable_id(
                        "clip_brief_field", project_id, brief_id, field_path
                    ),
                    brief_snapshot_id=snapshot_id,
                    source_module_id="clip_brief",
                    source_record_id=reference.source_record_id,
                    field_path=field_path,
                    field_display_name=display,
                    field_category=category,
                    # The original owner value, untouched. Easy-language text is
                    # kept separately in bounded_explanation.
                    original_value=value if not truncated else display_value,
                    original_value_digest=_digest(value) if path_exists else "",
                    value_type=_value_type(value) if path_exists else "absent",
                    required_by_owner_schema=required,
                    present=present,
                    empty=empty,
                    unavailable=not path_exists,
                    truncated_for_display=truncated,
                    source_owned=True,
                    advisory=advisory,
                    human_editable=False,
                    current=reference.current,
                    stale=reference.stale,
                    bounded_explanation=self._field_explanation(
                        display, required, present, empty, path_exists, advisory
                    ),
                    limitations=(
                        ["This guidance is advisory, not a decision."] if advisory else []
                    ),
                )
            )
        return projections[:_MAX_FIELD_PROJECTIONS]

    @staticmethod
    def _field_explanation(
        display: str,
        required: bool,
        present: bool,
        empty: bool,
        path_exists: bool,
        advisory: bool,
    ) -> str:
        """Plain-language explanation, kept strictly separate from the value."""
        kind = "required" if required else "optional"
        if not path_exists:
            return f"{display} is {kind} but is missing from the persisted brief."
        if empty:
            return f"{display} is {kind} and the owner persisted it as empty."
        if not present:
            return f"{display} is {kind} and the owner persisted no usable value."
        if advisory:
            return f"{display} was supplied by the owner as advisory guidance."
        return f"{display} was supplied by the owner."

    def build_section_projections(
        self,
        project_id: str,
        brief_id: str,
        fields: list[BobaClipBriefFieldProjectionV1],
        *,
        snapshot_id: str | None = None,
        source_card_ids: list[str] | None = None,
        evidence_link_ids: list[str] | None = None,
    ) -> list[BobaClipBriefSectionProjectionV1]:
        by_path = {item.field_path: item for item in fields}
        sections: list[BobaClipBriefSectionProjectionV1] = []
        for section_id, title, collapsed in _SECTION_DEFINITIONS:
            paths = [row[0] for row in _OWNER_SCHEMA_FIELDS if row[4] == section_id]
            members = [by_path[path] for path in paths if path in by_path]
            required = [item for item in members if item.required_by_owner_schema]
            optional = [item for item in members if not item.required_by_owner_schema]
            sections.append(
                BobaClipBriefSectionProjectionV1(
                    section_projection_id=_stable_id(
                        "clip_brief_section", project_id, brief_id, section_id
                    ),
                    brief_snapshot_id=snapshot_id,
                    section_id=section_id,
                    title=title,
                    field_projection_ids=[item.field_projection_id for item in members],
                    source_card_ids=(source_card_ids or [])[:MAX_EXPANDED_SOURCE_CARDS],
                    evidence_link_ids=(evidence_link_ids or [])[:_MAX_EVIDENCE_LINKS],
                    visible=True,
                    empty=not any(item.present for item in members),
                    unavailable=not members,
                    required_field_count=len(required),
                    present_required_field_count=sum(1 for item in required if item.present),
                    optional_field_count=len(optional),
                    present_optional_field_count=sum(1 for item in optional if item.present),
                    warning_count=sum(len(item.warnings) for item in members),
                    limitation_count=sum(len(item.limitations) for item in members),
                    collapsed_by_default=collapsed,
                    bounded_empty_message=(
                        "The owner persisted no usable value for this section."
                    ),
                    bounded_unavailable_message=(
                        "The owner schema defines no field for this section."
                    ),
                )
            )
        return sections[:_MAX_SECTION_PROJECTIONS]

    # ------------------------------------------------------------------
    # Completeness
    # ------------------------------------------------------------------
    def build_completeness(
        self,
        project_id: str,
        brief_id: str,
        fields: list[BobaClipBriefFieldProjectionV1],
        *,
        snapshot_id: str | None = None,
    ) -> BobaClipBriefCompletenessV1:
        """Presence of required owner-schema fields. Never a quality judgement."""
        reference = self._reference_for(project_id, brief_id)
        required_paths = list(owner_schema_required_field_paths())
        optional_paths = list(owner_schema_optional_field_paths())
        by_path = {item.field_path: item for item in fields}
        present_required = [
            path for path in required_paths if by_path.get(path) and by_path[path].present
        ]
        missing_required = [path for path in required_paths if path not in present_required]
        present_optional = [
            path for path in optional_paths if by_path.get(path) and by_path[path].present
        ]
        missing_optional = [path for path in optional_paths if path not in present_optional]

        if not reference.schema_supported:
            status: ClipBriefCompletenessStatus = "unsupported_schema"
        elif reference.stale:
            status = "stale"
        elif missing_required:
            status = "missing_required_fields"
        elif missing_optional:
            status = "complete_with_optional_gaps"
        else:
            status = "complete"

        return BobaClipBriefCompletenessV1(
            completeness_record_id=_stable_id(
                "clip_brief_completeness", project_id, brief_id
            ),
            brief_snapshot_id=snapshot_id,
            owner_schema_id=reference.brief_schema_id,
            owner_schema_version=reference.brief_schema_version,
            required_field_paths=required_paths,
            present_required_field_paths=present_required,
            missing_required_field_paths=missing_required,
            optional_field_paths=optional_paths,
            present_optional_field_paths=present_optional,
            missing_optional_field_paths=missing_optional,
            required_field_count=len(required_paths),
            present_required_field_count=len(present_required),
            optional_field_count=len(optional_paths),
            present_optional_field_count=len(present_optional),
            required_completion_ratio=(
                round(len(present_required) / len(required_paths), 6)
                if required_paths
                else 0.0
            ),
            optional_completion_ratio=(
                round(len(present_optional) / len(optional_paths), 6)
                if optional_paths
                else 0.0
            ),
            completeness_status=status,
            complete_for_owner_schema=not missing_required and reference.schema_supported,
            blocking_reasons=(
                [f"Missing required owner field: {path}" for path in missing_required][:16]
            ),
        )

    def inspect_clip_brief_completeness(
        self, project_id: str, brief_id: str
    ) -> dict[str, Any]:
        fields = self.build_field_projections(project_id, brief_id)
        record = self.build_completeness(project_id, brief_id, fields)
        return {
            "schema_version": "boba_clip_brief_review_completeness_v1",
            "project_id": project_id,
            "brief_id": brief_id,
            "completeness": record.model_dump(mode="json"),
            "limitations": [
                "Completeness reflects only the presence of required owner-schema "
                "fields. It is not creative quality, technical validation, "
                "Rights clearance, Safety approval or render readiness.",
            ],
        }

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------
    def build_evidence_links(
        self,
        project_id: str,
        brief_id: str,
        *,
        snapshot_id: str | None = None,
    ) -> list[BobaClipBriefEvidenceLinkV1]:
        """Link evidence only through persisted identities and relationships."""
        reference = self._reference_for(project_id, brief_id)
        candidate = self._candidate_rows(project_id).get(reference.candidate_id, {})
        ranked = self._ranked_rows(project_id).get(reference.candidate_id, {})
        editorial = self._editorial_rows(project_id).get(reference.candidate_id, {})
        links: list[BobaClipBriefEvidenceLinkV1] = []

        def link(
            field_path: str,
            evidence_type: str,
            module_id: str,
            record: Mapping[str, Any],
            *,
            advisory: bool,
            transcript_ids: list[str] | None = None,
            start: float | None = None,
            end: float | None = None,
        ) -> None:
            present = bool(record)
            payload = self._source_payload(module_id, project_id)
            links.append(
                BobaClipBriefEvidenceLinkV1(
                    evidence_link_id=_stable_id(
                        "clip_brief_evidence", project_id, brief_id, field_path, module_id
                    ),
                    brief_snapshot_id=snapshot_id,
                    brief_field_path=field_path,
                    evidence_type=evidence_type,
                    source_module_id=module_id,
                    source_record_id=_safe_text(
                        payload.get("schema_version") or payload.get("brief_version") or module_id,
                        180,
                    ),
                    source_record_digest=(
                        _digest(_safe_payload(payload)) if payload else ""
                    ),
                    candidate_id=reference.candidate_id if present else None,
                    clip_id=reference.clip_id if present else None,
                    transcript_segment_ids=(transcript_ids or [])[:32],
                    source_start_seconds=start,
                    source_end_seconds=end,
                    exact_identity_match=present
                    and _safe_text(record.get("candidate_id"), 128) == reference.candidate_id,
                    digest_match=bool(payload),
                    current=present,
                    missing=not present,
                    authoritative=not advisory,
                    advisory=advisory,
                    bounded_summary=(
                        f"{evidence_type} evidence linked by exact candidate identity."
                        if present
                        else f"No {evidence_type} record exists for this candidate."
                    ),
                    limitations=(
                        [] if present else ["Missing evidence is never treated as a pass."]
                    ),
                )
            )

        evidence = _as_mapping(candidate.get("evidence"))
        transcript_ids = [
            _safe_text(item, 128)
            for item in evidence.get("topic_segment_ids", [])
            if isinstance(item, str)
        ]
        link(
            "candidate_id",
            "candidate_record",
            "clip_discovery",
            candidate,
            advisory=False,
            transcript_ids=transcript_ids,
            start=_seconds(candidate.get("start_seconds")),
            end=_seconds(candidate.get("end_seconds")),
        )
        link("ranked_clip_id", "ranking_record", "clip_ranking", ranked, advisory=False)
        link(
            "candidate_id",
            "editorial_decision",
            "editorial_decision",
            editorial,
            advisory=False,
        )
        for field_path, module_id, advisory in (
            ("story_instruction", "explanation", True),
            ("hook_instruction", "hook_retention", True),
            ("caption_instruction", "caption_motion", True),
            ("motion_instruction", "caption_motion", True),
            ("audio_instruction", "music_mood", True),
        ):
            record = self._module_record_for_candidate(
                module_id, project_id, reference.candidate_id
            )
            link(field_path, f"{module_id}_record", module_id, record, advisory=advisory)
        link(
            "source_window.start_seconds",
            "workflow_state",
            "workflow_controller",
            _active_workflow_run(self._source_payload("workflow_controller", project_id)),
            advisory=False,
        )
        return links[:_MAX_EVIDENCE_LINKS]

    def _module_record_for_candidate(
        self, module_id: str, project_id: str, candidate_id: str
    ) -> dict[str, Any]:
        """Find the record a module persisted for this exact candidate identity."""
        payload = self._source_payload(module_id, project_id)
        for key in (
            "candidate_explanations",
            "analyses",
            "recommendations",
            "selected_briefs",
            "directions",
        ):
            rows = payload.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                mapped = _as_mapping(row)
                if _safe_text(mapped.get("candidate_id"), 128) == candidate_id:
                    return mapped
        return {}

    def inspect_clip_brief_evidence(self, project_id: str, brief_id: str) -> dict[str, Any]:
        links = self.build_evidence_links(project_id, brief_id)
        return {
            "schema_version": "boba_clip_brief_review_evidence_v1",
            "project_id": project_id,
            "brief_id": brief_id,
            "evidence_links": [item.model_dump(mode="json") for item in links],
            "missing_evidence_count": sum(1 for item in links if item.missing),
            "limitations": [
                "Evidence is linked only through persisted identities. It is "
                "never inferred from similar text.",
            ],
        }

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------
    def detect_clip_brief_conflicts(
        self,
        project_id: str,
        brief_id: str,
        *,
        snapshot_id: str | None = None,
    ) -> list[BobaClipBriefConflictV1]:
        """Report conflicts only between records with the same exact identity."""
        reference = self._reference_for(project_id, brief_id)
        brief = self._brief_record(project_id, brief_id)
        candidate = self._candidate_rows(project_id).get(reference.candidate_id, {})
        editorial = self._editorial_rows(project_id).get(reference.candidate_id, {})
        conflicts: list[BobaClipBriefConflictV1] = []

        def add(
            conflict_type: ClipBriefConflictType,
            severity: str,
            paths: list[str],
            value_a: object,
            value_b: object,
            summary: str,
            *,
            blocks: bool = False,
        ) -> None:
            conflicts.append(
                BobaClipBriefConflictV1(
                    conflict_record_id=_stable_id(
                        "clip_brief_conflict", project_id, brief_id, conflict_type
                    ),
                    brief_snapshot_id=snapshot_id,
                    conflict_type=conflict_type,
                    severity=severity,
                    brief_field_paths=paths[:16],
                    source_record_ids=[reference.source_record_id],
                    value_a=_safe_text(value_a, 900),
                    value_b=_safe_text(value_b, 900),
                    same_candidate=True,
                    same_clip=True,
                    same_workflow_run=reference.workflow_run_id is not None,
                    current_records=reference.current,
                    # The owner persists no supersession marker, so no conflict
                    # can be auto-resolved by supersession.
                    explicit_supersession_found=False,
                    resolved=False,
                    blocks_review_action=blocks,
                    human_review_required=True,
                    bounded_summary=summary,
                )
            )

        # Candidate identity: the brief names a candidate the owner never discovered.
        if not candidate:
            add(
                "candidate_identity_conflict",
                "critical",
                ["candidate_id"],
                reference.candidate_id,
                "no candidate record",
                "The brief names a candidate with no Candidate Clip Discovery record.",
                blocks=True,
            )

        # Source window: brief window versus the candidate's persisted window.
        candidate_start = _seconds(candidate.get("start_seconds"))
        candidate_end = _seconds(candidate.get("end_seconds"))
        if candidate_start is not None and candidate_end is not None:
            if abs(candidate_start - reference.start_seconds) > 1e-3 or abs(
                candidate_end - reference.end_seconds
            ) > 1e-3:
                add(
                    "source_window_conflict",
                    "critical",
                    ["source_window.start_seconds", "source_window.end_seconds"],
                    f"{reference.start_seconds}-{reference.end_seconds}",
                    f"{candidate_start}-{candidate_end}",
                    "The brief source window differs from the candidate's "
                    "persisted window for the same identity.",
                    blocks=True,
                )
            expected = round(candidate_end - candidate_start, _TIME_PRECISION)
            if abs(expected - reference.duration_seconds) > 1e-2:
                add(
                    "duration_conflict",
                    "warning",
                    ["source_window.duration_seconds"],
                    reference.duration_seconds,
                    expected,
                    "The brief target duration differs from the candidate window "
                    "length. Both values are shown as persisted.",
                )

        # Lifecycle: a selected brief for a candidate Editorial Decision rejected.
        editorial_payload = self._source_payload("editorial_decision", project_id)
        rejected_ids = {
            _safe_text(item, 128)
            for item in editorial_payload.get("rejected_clip_ids", [])
            if isinstance(item, str)
        }
        if reference.lifecycle_bucket == "selected" and reference.candidate_id in rejected_ids:
            add(
                "editorial_status_conflict",
                "critical",
                ["candidate_id"],
                "clip_brief: selected",
                "editorial_decision: rejected",
                "The brief is in the selected bucket while Editorial Decision "
                "rejected the same candidate.",
                blocks=True,
            )
        elif (
            reference.lifecycle_bucket == "blocked"
            and bool(editorial.get("selected"))
        ):
            add(
                "lifecycle_conflict",
                "warning",
                ["candidate_id"],
                "clip_brief: blocked",
                "editorial_decision: selected",
                "The brief is blocked while Editorial Decision selected the same candidate.",
            )

        # Clip identity: brief's ranked clip versus Editorial Decision's.
        editorial_clip = _safe_text(editorial.get("ranked_clip_id"), 128)
        if editorial_clip and editorial_clip != reference.clip_id:
            add(
                "clip_identity_conflict",
                "critical",
                ["ranked_clip_id"],
                reference.clip_id,
                editorial_clip,
                "The brief and Editorial Decision reference different ranked clips "
                "for the same candidate.",
                blocks=True,
            )

        # Two current briefs claiming the same identity, with no supersession.
        duplicates = [
            row
            for row, _bucket, _index in self._brief_rows(project_id)
            if _safe_text(row.get("candidate_id"), 128) == reference.candidate_id
            and _safe_text(row.get("brief_id"), 160) != brief_id
        ]
        if duplicates:
            add(
                "revision_conflict",
                "warning",
                ["brief_id", "candidate_id"],
                brief_id,
                _safe_text(duplicates[0].get("brief_id"), 160),
                "More than one current brief claims this candidate identity and "
                "the owner records no supersession.",
            )

        if not reference.schema_supported:
            add(
                "unknown",
                "warning",
                ["brief_id"],
                reference.brief_schema_id,
                SUPPORTED_BRIEF_SCHEMA_ID,
                "The brief schema is not supported by this panel.",
            )
        _ = brief
        return conflicts[:_MAX_CONFLICTS]

    def inspect_clip_brief_conflicts(self, project_id: str, brief_id: str) -> dict[str, Any]:
        conflicts = self.detect_clip_brief_conflicts(project_id, brief_id)
        return {
            "schema_version": "boba_clip_brief_review_conflicts_v1",
            "project_id": project_id,
            "brief_id": brief_id,
            "conflict_records": [item.model_dump(mode="json") for item in conflicts],
            "blocking_conflict_count": sum(
                1 for item in conflicts if item.blocks_review_action
            ),
            "limitations": [
                "Conflicts are reported only for the same exact identity and are "
                "never resolved by averaging confidence.",
                "Different advisory recommendations are not treated as an "
                "authoritative conflict.",
            ],
        }

    # ------------------------------------------------------------------
    # Source cards
    # ------------------------------------------------------------------
    def build_source_cards(
        self,
        project_id: str,
        brief_id: str,
        *,
        snapshot_id: str | None = None,
    ) -> list[BobaClipBriefSourceCardV1]:
        registry = build_fixed_clip_brief_source_registry()
        reference = self._reference_for(project_id, brief_id)
        cards: list[BobaClipBriefSourceCardV1] = []
        for source_id, descriptor in registry.items():
            payload = self._source_payload(source_id, project_id)
            title = str(descriptor["title"])
            advisory = bool(descriptor["advisory_only"])
            if not payload:
                cards.append(
                    BobaClipBriefSourceCardV1(
                        source_card_id=_stable_id(
                            "clip_brief_source_card", project_id, brief_id, source_id
                        ),
                        brief_snapshot_id=snapshot_id,
                        source_module_id=source_id,
                        authority_domain=str(descriptor["authority_domain"]),
                        source_record_id=_stable_id("unavailable", project_id, source_id),
                        source_record_digest=_digest(
                            {"module": source_id, "state": "unavailable"}
                        ),
                        title=title,
                        original_status="unavailable",
                        bounded_summary=(
                            "No canonical record is available from this module."
                        ),
                        easy_explanation=f"{title} has not supplied a record.",
                        current=False,
                        authoritative=not advisory,
                        advisory_only=advisory,
                        limitations=[
                            "An unavailable source record is never treated as a pass."
                        ],
                    )
                )
                continue
            safe = _as_mapping(_safe_payload(payload))
            status, decision, summary = self._source_status(
                source_id, safe, reference
            )
            cards.append(
                BobaClipBriefSourceCardV1(
                    source_card_id=_stable_id(
                        "clip_brief_source_card", project_id, brief_id, source_id
                    ),
                    brief_snapshot_id=snapshot_id,
                    source_module_id=source_id,
                    authority_domain=str(descriptor["authority_domain"]),
                    source_record_id=_safe_text(
                        safe.get("schema_version") or safe.get("brief_version") or source_id, 180
                    ),
                    source_record_digest=_digest(safe),
                    source_schema_id=_safe_text(
                        safe.get("schema_version") or safe.get("brief_version") or "unknown", 180
                    ),
                    source_schema_version=_safe_text(
                        safe.get("schema_version") or safe.get("brief_version") or "1", 80
                    ),
                    title=title,
                    original_status=status,
                    original_decision=decision,
                    bounded_summary=summary,
                    easy_explanation=f"{title} reports {status.replace('_', ' ')}.",
                    current=True,
                    authoritative=not advisory,
                    advisory_only=advisory,
                    blocking=status in {"blocked", "rejected", "failed", "denied"},
                    human_review_required=status in {"awaiting_human_review", "needs_revision"},
                    warnings=[
                        _safe_text(item, 300)
                        for item in safe.get("warnings", [])
                        if isinstance(item, str)
                    ][:12],
                    limitations=(
                        [
                            _safe_text(item, 300)
                            for item in safe.get("limitations", [])
                            if isinstance(item, str)
                        ][:12]
                        + (
                            ["This module's output is advisory, not a decision."]
                            if advisory
                            else []
                        )
                    ),
                )
            )
        return cards[:_MAX_SOURCE_CARDS]

    def _source_status(
        self,
        source_id: str,
        payload: Mapping[str, Any],
        reference: BobaClipBriefReferenceV1,
    ) -> tuple[str, str | None, str]:
        """Extract this module's own verbatim status for this brief's identity."""
        if source_id == "clip_brief":
            return (
                reference.lifecycle_bucket,
                _safe_text(
                    self._brief_record(reference.project_id, reference.brief_id).get(
                        "render_readiness"
                    ),
                    120,
                )
                or None,
                _safe_text(payload.get("project_summary"), 900),
            )
        if source_id == "clip_discovery":
            row = self._candidate_rows(reference.project_id).get(reference.candidate_id, {})
            if not row:
                return ("candidate_not_found", None, "This candidate is not in the record.")
            return (
                "discovered",
                _safe_text(row.get("candidate_type"), 80) or None,
                _safe_text(row.get("discovery_reason"), 600),
            )
        if source_id == "clip_ranking":
            row = self._ranked_rows(reference.project_id).get(reference.candidate_id, {})
            if not row:
                return ("not_ranked", None, "Clip Ranking did not rank this candidate.")
            return (
                _safe_text(row.get("tier"), 80) or "ranked",
                _safe_text(row.get("production_priority"), 80) or None,
                "; ".join(
                    _safe_text(item, 200)
                    for item in row.get("ranking_reasons", [])
                    if isinstance(item, str)
                )[:900],
            )
        if source_id == "editorial_decision":
            row = self._editorial_rows(reference.project_id).get(reference.candidate_id, {})
            rejected = {
                _safe_text(item, 128)
                for item in payload.get("rejected_clip_ids", [])
                if isinstance(item, str)
            }
            if not row:
                if reference.candidate_id in rejected:
                    return ("rejected", "rejected", "Editorial Decision rejected this.")
                return (
                    "no_editorial_decision",
                    None,
                    "Editorial Decision has not decided on this candidate.",
                )
            return (
                "selected" if bool(row.get("selected")) else "not_selected",
                _safe_text(row.get("render_readiness"), 80) or None,
                "; ".join(
                    _safe_text(item, 200)
                    for item in row.get("decision_reasons", [])
                    if isinstance(item, str)
                )[:900],
            )
        record = self._module_record_for_candidate(
            source_id, reference.project_id, reference.candidate_id
        )
        if record:
            return (
                "record_available",
                None,
                _safe_text(
                    record.get("summary") or record.get("reason") or "A record exists.", 900
                ),
            )
        status = _safe_text(payload.get("status") or "available", 160)
        return (
            status,
            None,
            _safe_text(payload.get("summary") or "Canonical record available.", 900),
        )

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    def build_clip_brief_snapshot(
        self, project_id: str, session_id: str, brief_id: str
    ) -> dict[str, Any]:
        session = self.get_clip_brief_review_session(project_id, session_id)
        reference = self._reference_for(project_id, brief_id)
        snapshot_id = f"clip_brief_snapshot_{uuid4().hex}"
        fields = self.build_field_projections(project_id, brief_id, snapshot_id=snapshot_id)
        cards = self.build_source_cards(project_id, brief_id, snapshot_id=snapshot_id)
        links = self.build_evidence_links(project_id, brief_id, snapshot_id=snapshot_id)
        conflicts = self.detect_clip_brief_conflicts(
            project_id, brief_id, snapshot_id=snapshot_id
        )
        completeness = self.build_completeness(
            project_id, brief_id, fields, snapshot_id=snapshot_id
        )
        sections = self.build_section_projections(
            project_id,
            brief_id,
            fields,
            snapshot_id=snapshot_id,
            source_card_ids=[card.source_card_id for card in cards],
            evidence_link_ids=[link.evidence_link_id for link in links],
        )
        digests = {card.source_module_id: card.source_record_digest for card in cards}
        project_digest = self._project_snapshot_digest(project_id)
        revision = self._workflow_revision(project_id)
        brief_digest = self._brief_digest(project_id, brief_id)
        confirmation = _digest(
            {
                "project": project_digest,
                "revision": revision,
                "brief": brief_digest,
                "brief_id": brief_id,
                "candidate_id": reference.candidate_id,
            }
        )

        def status_of(module_id: str) -> str:
            return next(
                (c.original_status for c in cards if c.source_module_id == module_id),
                "unavailable",
            )

        blocking = [item for item in conflicts if item.blocks_review_action]
        snapshot = BobaClipBriefSnapshotV1(
            brief_snapshot_id=snapshot_id,
            clip_brief_review_session_id=session.clip_brief_review_session_id,
            brief_reference_id=reference.brief_reference_id,
            project_id=project_id,
            workflow_run_id=reference.workflow_run_id,
            stage_instance_id=reference.stage_instance_id,
            candidate_id=reference.candidate_id,
            clip_id=reference.clip_id,
            brief_id=brief_id,
            project_snapshot_digest=project_digest,
            workflow_revision=revision,
            brief_digest=brief_digest,
            source_record_references=[
                {"module_id": c.source_module_id, "record_id": c.source_record_id}
                for c in cards
            ],
            source_record_digests=digests,
            field_projection_ids=[item.field_projection_id for item in fields],
            section_projection_ids=[item.section_projection_id for item in sections],
            source_card_ids=[card.source_card_id for card in cards],
            evidence_link_ids=[link.evidence_link_id for link in links],
            completeness_record_id=completeness.completeness_record_id,
            conflict_record_ids=[item.conflict_record_id for item in conflicts],
            brief_status=reference.lifecycle_bucket,
            candidate_status=status_of("clip_discovery"),
            editorial_status=status_of("editorial_decision"),
            rights_status=status_of("rights_permission_gate"),
            workflow_status=status_of("workflow_controller"),
            artifact_status=status_of("artifact_inspector"),
            validation_status=status_of("validator_runner"),
            human_review_status=(
                "awaiting_human_review" if conflicts else "no_pending_review"
            ),
            current=reference.current,
            stale=reference.stale,
            historical=reference.historical,
            superseded=reference.superseded,
            missing_required_field_count=len(completeness.missing_required_field_paths),
            missing_optional_field_count=len(completeness.missing_optional_field_paths),
            missing_evidence_count=sum(1 for link in links if link.missing),
            conflict_count=len(conflicts),
            warning_count=sum(len(card.warnings) for card in cards),
            limitation_count=sum(len(card.limitations) for card in cards),
            available_action_descriptor_ids=self._available_actions(reference, blocking),
            confirmation_context_digest=confirmation,
            snapshot_digest=_digest(
                {
                    "project": project_digest,
                    "revision": revision,
                    "brief": brief_digest,
                    "sources": digests,
                    "session": session.clip_brief_review_session_id,
                }
            ),
            limitations=[
                "Snapshot status is display-only and links to canonical owner records.",
                "Clip Brief Review V1 exposes no authoritative brief action.",
            ],
        )
        self.store.save_boba_clip_brief_review_snapshot(
            project_id, snapshot_id, snapshot.model_dump(mode="json")
        )
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "brief_reference": reference.model_dump(mode="json"),
            "field_projections": [item.model_dump(mode="json") for item in fields],
            "section_projections": [item.model_dump(mode="json") for item in sections],
            "source_cards": [card.model_dump(mode="json") for card in cards],
            "evidence_links": [link.model_dump(mode="json") for link in links],
            "completeness": completeness.model_dump(mode="json"),
            "conflict_records": [item.model_dump(mode="json") for item in conflicts],
            "action_confirmations": self._action_confirmations(snapshot),
        }

    def refresh_clip_brief_snapshot(
        self, project_id: str, snapshot_id: str
    ) -> dict[str, Any]:
        snapshot = self._snapshot(project_id, snapshot_id)
        return self.build_clip_brief_snapshot(
            project_id, snapshot.clip_brief_review_session_id, snapshot.brief_id
        )

    def _snapshot(self, project_id: str, snapshot_id: str) -> BobaClipBriefSnapshotV1:
        _safe_id(project_id, "project id")
        _safe_id(snapshot_id, "brief snapshot id")
        raw = self.store.load_boba_clip_brief_review_snapshot(project_id, snapshot_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA clip brief review snapshot is unavailable.")
        snapshot = BobaClipBriefSnapshotV1.model_validate(raw)
        if snapshot.project_id != project_id:
            raise ValidationError("Clip brief snapshot belongs to another project.")
        return snapshot

    def _action_confirmations(self, snapshot: BobaClipBriefSnapshotV1) -> dict[str, str]:
        registry = build_fixed_clip_brief_action_registry()
        tokens: dict[str, str] = {}
        for action_id in snapshot.available_action_descriptor_ids:
            descriptor = registry.get(action_id)
            if descriptor is None:
                continue
            tokens[action_id] = _digest(
                {
                    "snapshot": snapshot.snapshot_digest,
                    "action": descriptor.action_descriptor_id,
                    "brief": snapshot.brief_digest,
                }
            )
        return tokens

    def _available_actions(
        self,
        reference: BobaClipBriefReferenceV1,
        blocking_conflicts: list[BobaClipBriefConflictV1] | None = None,
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
        available: list[str] = []
        for descriptor in build_fixed_clip_brief_action_registry().values():
            if not descriptor.allowed_in_v1 or descriptor.availability != "available":
                continue
            if descriptor.supported_brief_states and state not in (
                descriptor.supported_brief_states
            ):
                continue
            if descriptor.requires_current_snapshot and not reference.current:
                continue
            if descriptor.requires_current_snapshot and blocking_conflicts:
                continue
            available.append(descriptor.action_descriptor_id)
        return available

    def inspect_clip_brief(self, project_id: str, brief_id: str) -> dict[str, Any]:
        reference = self._reference_for(project_id, brief_id)
        fields = self.build_field_projections(project_id, brief_id)
        return {
            "schema_version": "boba_clip_brief_review_brief_v1",
            "project_id": project_id,
            "brief_id": brief_id,
            "brief_reference": reference.model_dump(mode="json"),
            "field_projections": [item.model_dump(mode="json") for item in fields],
            "section_projections": [
                item.model_dump(mode="json")
                for item in self.build_section_projections(project_id, brief_id, fields)
            ],
            "source_cards": [
                card.model_dump(mode="json")
                for card in self.build_source_cards(project_id, brief_id)
            ],
            "evidence_links": [
                link.model_dump(mode="json")
                for link in self.build_evidence_links(project_id, brief_id)
            ],
            "completeness": self.build_completeness(
                project_id, brief_id, fields
            ).model_dump(mode="json"),
            "conflict_records": [
                item.model_dump(mode="json")
                for item in self.detect_clip_brief_conflicts(project_id, brief_id)
            ],
        }

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------
    def build_clip_brief_queue(
        self,
        project_id: str,
        *,
        review_filter: str = "all_current",
        sort: str = "review_priority",
        offset: int = 0,
        limit: int = MAX_QUEUE_PAGE_SIZE,
    ) -> dict[str, Any]:
        references = self.build_clip_brief_references(project_id)
        items = [
            self._queue_item(project_id, reference, index)
            for index, reference in enumerate(references)
        ]
        items = self._filter_queue(items, review_filter)
        items = self._sort_queue(items, sort)
        safe_offset = max(0, offset)
        safe_limit = max(1, min(limit, MAX_QUEUE_PAGE_SIZE))
        return {
            "schema_version": "boba_clip_brief_review_queue_v1",
            "project_id": project_id,
            "total": len(items),
            "offset": safe_offset,
            "limit": safe_limit,
            "active_filter": review_filter,
            "active_sort": sort,
            "priority_tiers": [
                {"priority": priority, "reason": reason}
                for priority, reason in CLIP_BRIEF_QUEUE_PRIORITY_TIERS
            ],
            "items": [
                item.model_dump(mode="json")
                for item in items[safe_offset : safe_offset + safe_limit]
            ],
        }

    def inspect_clip_brief_queue(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.build_clip_brief_queue(project_id, **kwargs)

    @staticmethod
    def _filter_queue(
        items: list[BobaClipBriefQueueItemV1], review_filter: str
    ) -> list[BobaClipBriefQueueItemV1]:
        if review_filter in {"all_current", "", "all"}:
            return [item for item in items if not item.historical]
        if review_filter == "human_review_required":
            return [item for item in items if item.human_action_required]
        if review_filter == "current_selected_candidate":
            return [item for item in items if item.editorial_status == "selected"]
        if review_filter == "missing_required_fields":
            return [item for item in items if item.missing_required_field_count > 0]
        if review_filter == "missing_evidence":
            return [item for item in items if item.missing_evidence_count > 0]
        if review_filter == "conflicts":
            return [item for item in items if item.conflict_count > 0]
        if review_filter == "stale":
            return [item for item in items if item.stale]
        if review_filter == "complete_for_owner_schema":
            return [
                item
                for item in items
                if item.completeness_status in {"complete", "complete_with_optional_gaps"}
            ]
        if review_filter == "warnings":
            return [item for item in items if item.warning_count > 0]
        if review_filter == "historical":
            return [item for item in items if item.historical]
        if review_filter == "superseded":
            return [item for item in items if item.superseded]
        raise ValidationError("Unsupported clip brief review filter.")

    @staticmethod
    def _sort_queue(
        items: list[BobaClipBriefQueueItemV1], sort: str
    ) -> list[BobaClipBriefQueueItemV1]:
        rows = list(items)
        if sort in {"review_priority", "", "priority"}:
            rows.sort(key=lambda item: (item.priority_tier, item.deterministic_sort_key))
        elif sort == "candidate_rank":
            # Briefs without a source-owned candidate rank sort last, never invented.
            rows.sort(
                key=lambda item: (
                    item.candidate_rank is None,
                    item.candidate_rank or 0,
                    item.brief_id,
                )
            )
        elif sort in {"created_sequence", "source_start_time"}:
            rows.sort(key=lambda item: (item.deterministic_sort_key, item.brief_id))
        elif sort == "brief_id":
            rows.sort(key=lambda item: item.brief_id)
        else:
            raise ValidationError("Unsupported clip brief review sort.")
        return rows

    def _queue_item(
        self, project_id: str, reference: BobaClipBriefReferenceV1, creation_index: int
    ) -> BobaClipBriefQueueItemV1:
        brief_id = reference.brief_id
        brief = self._brief_record(project_id, brief_id)
        fields = self.build_field_projections(project_id, brief_id)
        completeness = self.build_completeness(project_id, brief_id, fields)
        links = self.build_evidence_links(project_id, brief_id)
        conflicts = self.detect_clip_brief_conflicts(project_id, brief_id)
        cards = self.build_source_cards(project_id, brief_id)
        candidate_status = next(
            (c.original_status for c in cards if c.source_module_id == "clip_discovery"),
            "unavailable",
        )
        editorial_status = next(
            (c.original_status for c in cards if c.source_module_id == "editorial_decision"),
            "unavailable",
        )
        ranked = self._ranked_rows(project_id).get(reference.candidate_id, {})
        rank_value = ranked.get("rank")
        rank = rank_value if isinstance(rank_value, int) and rank_value >= 1 else None
        missing_evidence = sum(1 for link in links if link.missing)
        blocking = [item for item in conflicts if item.blocks_review_action]
        rights_blocked = self._domain_blocked(project_id, "rights_permission_gate")
        safety_blocked = self._domain_blocked(project_id, "safety_gate")
        warning_count = len(
            [item for item in brief.get("warnings", []) if isinstance(item, str)]
        ) + len([item for item in brief.get("limitations", []) if isinstance(item, str)])

        priority, reason = self._priority(
            selected=editorial_status == "selected",
            blocked=rights_blocked or safety_blocked,
            has_blocking_conflict=bool(blocking),
            human_required=bool(conflicts),
            missing_required=bool(completeness.missing_required_field_paths),
            missing_evidence=missing_evidence > 0,
            stale=reference.stale,
            rejected=editorial_status == "rejected",
            superseded=reference.superseded,
            historical=reference.historical,
            has_warnings=warning_count > 0,
        )
        digests = {card.source_module_id: card.source_record_digest for card in cards}
        return BobaClipBriefQueueItemV1(
            brief_queue_item_id=_stable_id("clip_brief_queue", project_id, brief_id),
            brief_reference_id=reference.brief_reference_id,
            project_id=project_id,
            workflow_run_id=reference.workflow_run_id,
            stage_instance_id=reference.stage_instance_id,
            candidate_id=reference.candidate_id,
            clip_id=reference.clip_id,
            brief_id=brief_id,
            title=_safe_text(brief.get("brief_title"), 240) or brief_id,
            bounded_summary=_safe_text(brief.get("final_clip_angle"), 900),
            owner_module_id="clip_brief",
            original_status=reference.lifecycle_bucket,
            candidate_status=candidate_status,
            editorial_status=editorial_status,
            completeness_status=completeness.completeness_status,
            evidence_status=("complete" if missing_evidence == 0 else "incomplete"),
            start_seconds=reference.start_seconds,
            end_seconds=reference.end_seconds,
            duration_seconds=reference.duration_seconds,
            candidate_rank=rank,
            current=reference.current,
            stale=reference.stale,
            historical=reference.historical,
            superseded=reference.superseded,
            human_action_required=bool(conflicts),
            blocker_count=len(blocking)
            + (1 if rights_blocked else 0)
            + (1 if safety_blocked else 0),
            warning_count=warning_count,
            missing_required_field_count=len(completeness.missing_required_field_paths),
            missing_optional_field_count=len(completeness.missing_optional_field_paths),
            missing_evidence_count=missing_evidence,
            conflict_count=len(conflicts),
            available_action_descriptor_ids=self._available_actions(reference, blocking),
            source_module_ids=[card.source_module_id for card in cards if card.current],
            source_record_ids=list(digests),
            source_record_digests=digests,
            priority_tier=priority,
            priority_reason=reason,
            deterministic_sort_key=(
                f"{priority:03d}:"
                f"{(rank if rank is not None else 9_999):04d}:"
                f"{creation_index:04d}:"
                f"{reference.start_seconds:012.3f}:{brief_id}"
            ),
            warnings=[
                _safe_text(item, 300)
                for item in brief.get("warnings", [])
                if isinstance(item, str)
            ][:12],
            limitations=[
                "Completeness and evidence status are display projections, not "
                "quality decisions.",
            ],
        )

    @staticmethod
    def _priority(
        *,
        selected: bool,
        blocked: bool,
        has_blocking_conflict: bool,
        human_required: bool,
        missing_required: bool,
        missing_evidence: bool,
        stale: bool,
        rejected: bool,
        superseded: bool,
        historical: bool,
        has_warnings: bool,
    ) -> tuple[int, str]:
        """Deterministic presentation tier. Never a quality score."""
        tiers = dict(CLIP_BRIEF_QUEUE_PRIORITY_TIERS)
        if selected and blocked:
            return (10, tiers[10])
        if has_blocking_conflict:
            return (20, tiers[20])
        if historical:
            return (120, tiers[120])
        if superseded:
            return (110, tiers[110])
        if rejected:
            return (100, tiers[100])
        if human_required:
            return (30, tiers[30])
        if missing_required:
            return (40, tiers[40])
        if missing_evidence:
            return (50, tiers[50])
        if stale and selected:
            return (60, tiers[60])
        if selected:
            return (70, tiers[70])
        if has_warnings:
            return (80, tiers[80])
        return (90, tiers[90])

    def _domain_blocked(self, project_id: str, source_id: str) -> bool:
        payload = self._source_payload(source_id, project_id)
        status = _safe_text(payload.get("status") or payload.get("decision"), 160).lower()
        return bool(payload) and any(
            token in status for token in ("block", "deny", "reject", "fail")
        )

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    def build_clip_brief_comparison(
        self,
        project_id: str,
        brief_ids: list[str],
        *,
        comparison_type: str = "side_by_side",
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        unique: list[str] = []
        for brief_id in brief_ids:
            _safe_id(brief_id, "brief id")
            if brief_id not in unique:
                unique.append(brief_id)
        if len(unique) < 2:
            raise ValidationError("At least two distinct clip briefs are required.")
        if len(unique) > MAX_COMPARISON_BRIEFS:
            raise ValidationError(
                f"At most {MAX_COMPARISON_BRIEFS} clip briefs may be compared."
            )
        if comparison_type not in {
            "side_by_side",
            "current_vs_historical",
            "candidate_briefs",
            "source_window",
            "completeness",
            "evidence_coverage",
            "hook",
            "narrative",
            "creative_guidance",
            "unknown",
        }:
            raise ValidationError("Unsupported clip brief comparison type.")
        references = [self._reference_for(project_id, item) for item in unique]
        field_rows = {item: self.build_field_projections(project_id, item) for item in unique}
        completeness = {
            item: self.build_completeness(project_id, item, field_rows[item])
            for item in unique
        }
        links = {item: self.build_evidence_links(project_id, item) for item in unique}
        candidate_ids = [reference.candidate_id for reference in references]
        clip_ids = {reference.clip_id for reference in references}
        run_ids = {reference.workflow_run_id for reference in references}

        comparison = BobaClipBriefComparisonV1(
            comparison_id=_stable_id("clip_brief_comparison", project_id, *unique),
            project_id=project_id,
            brief_ids=unique,
            candidate_ids=candidate_ids,
            comparison_type=comparison_type,
            same_candidate=len(set(candidate_ids)) == 1,
            same_clip=len(clip_ids) == 1,
            same_workflow_run=len(run_ids) == 1,
            field_comparisons=[
                {
                    "field_path": path,
                    "field_display_name": display,
                    "required_by_owner_schema": required,
                    "values": [
                        {
                            "brief_id": item,
                            "present": next(
                                (
                                    row.present
                                    for row in field_rows[item]
                                    if row.field_path == path
                                ),
                                False,
                            ),
                            "original_value": next(
                                (
                                    row.original_value
                                    for row in field_rows[item]
                                    if row.field_path == path
                                ),
                                None,
                            ),
                        }
                        for item in unique
                    ],
                }
                for path, display, _category, required, _section in _OWNER_SCHEMA_FIELDS
            ][:64],
            section_comparisons=[
                {
                    "section_id": section_id,
                    "title": title,
                    "present_required_counts": [
                        {
                            "brief_id": item,
                            "present_required": sum(
                                1
                                for row in field_rows[item]
                                if row.required_by_owner_schema
                                and row.present
                                and any(
                                    entry[0] == row.field_path and entry[4] == section_id
                                    for entry in _OWNER_SCHEMA_FIELDS
                                )
                            ),
                        }
                        for item in unique
                    ],
                }
                for section_id, title, _collapsed in _SECTION_DEFINITIONS
            ][:32],
            completeness_comparison=[
                {
                    "brief_id": item,
                    "completeness_status": completeness[item].completeness_status,
                    "complete_for_owner_schema": completeness[item].complete_for_owner_schema,
                    "missing_required_field_paths": completeness[
                        item
                    ].missing_required_field_paths,
                    "required_completion_ratio": completeness[item].required_completion_ratio,
                }
                for item in unique
            ],
            evidence_coverage_comparison=[
                {
                    "brief_id": item,
                    "linked_evidence": len(links[item]),
                    "missing_evidence": sum(1 for link in links[item] if link.missing),
                }
                for item in unique
            ],
            source_window_comparison=[
                {
                    "brief_id": reference.brief_id,
                    "candidate_id": reference.candidate_id,
                    "start_seconds": reference.start_seconds,
                    "end_seconds": reference.end_seconds,
                }
                for reference in references
            ],
            duration_comparison=[
                {
                    "brief_id": reference.brief_id,
                    "duration_seconds": reference.duration_seconds,
                }
                for reference in references
            ],
            warning_comparison=[
                {
                    "brief_id": reference.brief_id,
                    "warnings": reference.warnings[:8],
                }
                for reference in references
            ],
            limitation_comparison=[
                {
                    "brief_id": reference.brief_id,
                    "limitations": reference.limitations[:8],
                }
                for reference in references
            ],
            current_brief_ids=[r.brief_id for r in references if r.current],
            historical_brief_ids=[r.brief_id for r in references if r.historical],
            bounded_summary=(
                f"Side-by-side projection of {len(unique)} clip briefs from their "
                "canonical owner records. No winner is chosen."
            ),
            limitations=[
                "The panel does not choose a preferred brief and computes no "
                "winner score.",
                "Missing fields are shown explicitly rather than filled in.",
                "Completeness is not a quality comparison.",
            ],
        )
        return {"comparison": comparison.model_dump(mode="json")}

    # ------------------------------------------------------------------
    # Canonical action routing
    # ------------------------------------------------------------------
    def _action_descriptor(self, action_id: str) -> BobaClipBriefActionDescriptorV1:
        _safe_id(action_id, "action descriptor id")
        descriptor = build_fixed_clip_brief_action_registry().get(action_id)
        if descriptor is None:
            raise ValidationError("Unknown fixed BOBA clip brief review action descriptor.")
        return descriptor

    def create_clip_brief_action_request(
        self,
        project_id: str,
        *,
        clip_brief_review_session_id: str,
        brief_snapshot_id: str,
        action_descriptor_id: str,
        decision_value: str | None,
        reason: str,
        confirmation_context_digest: str,
        idempotency_key: str,
        confirmed: bool,
    ) -> BobaClipBriefActionRequestV1:
        session = self.get_clip_brief_review_session(
            project_id, clip_brief_review_session_id
        )
        snapshot = self._snapshot(project_id, brief_snapshot_id)
        if snapshot.clip_brief_review_session_id != session.clip_brief_review_session_id:
            raise ValidationError("Clip brief snapshot belongs to another review session.")
        descriptor = self._action_descriptor(action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            raise ValidationError("This BOBA clip brief review action is unavailable in V1.")
        if descriptor.action_descriptor_id not in snapshot.available_action_descriptor_ids:
            raise ValidationError("The action is unavailable for this exact clip brief.")
        if descriptor.allowed_decision_values and decision_value not in (
            descriptor.allowed_decision_values
        ):
            raise ValidationError("Unsupported decision value for this fixed action.")
        if descriptor.requires_reason and not reason.strip():
            raise ValidationError("This clip brief review action requires a reason.")
        if len(reason) > descriptor.maximum_reason_length:
            raise ValidationError("Clip brief review reason exceeds the allowed length.")
        if _SENSITIVE_KEY.search(reason):
            raise ValidationError("Clip brief review reasons cannot contain credentials.")
        if not confirmed:
            raise ValidationError("Explicit clip brief review confirmation is required.")
        if descriptor.requires_reviewer_context and not session.reviewer_context_id:
            raise ValidationError("An exact reviewer context is required.")
        expected = self._action_confirmations(snapshot).get(descriptor.action_descriptor_id)
        if not expected or confirmation_context_digest != expected:
            raise ValidationError(
                "Clip brief review confirmation does not match the current brief."
            )
        _safe_id(idempotency_key, "idempotency key")
        request = BobaClipBriefActionRequestV1(
            clip_brief_action_request_id=f"clip_brief_action_{uuid4().hex}",
            clip_brief_review_session_id=session.clip_brief_review_session_id,
            brief_snapshot_id=snapshot.brief_snapshot_id,
            project_id=project_id,
            workflow_run_id=snapshot.workflow_run_id,
            stage_instance_id=snapshot.stage_instance_id,
            candidate_id=snapshot.candidate_id,
            clip_id=snapshot.clip_id,
            brief_id=snapshot.brief_id,
            expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            reviewer_context_id=session.reviewer_context_id,
            action_descriptor_id=descriptor.action_descriptor_id,
            owning_module_id=descriptor.owning_module_id,
            owning_operation_id=descriptor.owning_operation_id,
            decision_value=decision_value,
            bounded_reason=_safe_text(reason, descriptor.maximum_reason_length),
            expected_project_snapshot_digest=snapshot.project_snapshot_digest,
            expected_workflow_revision=snapshot.workflow_revision,
            expected_brief_digest=snapshot.brief_digest,
            expected_source_record_digests=snapshot.source_record_digests,
            confirmation_context_digest=confirmation_context_digest,
            idempotency_key=idempotency_key,
            confirmed=True,
            limitations=list(descriptor.does_not_do)[:16],
        )
        self.store.save_boba_clip_brief_review_action(
            project_id, request.clip_brief_action_request_id, request.model_dump(mode="json")
        )
        return request

    def validate_clip_brief_action_request(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        """Re-read canonical state and reject stale or drifted submissions."""
        request = self._action_request(project_id, request_id)
        expires_at = _parse_time(request.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            return {
                "valid": False,
                "code": "expired_snapshot",
                "message": "The clip brief review action expired before submission.",
            }
        descriptor = self._action_descriptor(request.action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "This clip brief review action is no longer available.",
            }
        try:
            reference = self._reference_for(project_id, request.brief_id)
        except ValidationError:
            return {
                "valid": False,
                "code": "brief_removed",
                "message": "The clip brief is no longer available.",
            }
        if reference.candidate_id != request.candidate_id:
            return {
                "valid": False,
                "code": "candidate_identity_mismatch",
                "message": "The brief now references a different candidate.",
            }
        if reference.clip_id != request.clip_id:
            return {
                "valid": False,
                "code": "clip_identity_mismatch",
                "message": "The brief now references a different ranked clip.",
            }
        if self._project_snapshot_digest(project_id) != (
            request.expected_project_snapshot_digest
        ):
            return {
                "valid": False,
                "code": "stale_project_snapshot",
                "message": "The project changed while this review was open.",
            }
        if self._workflow_revision(project_id) != request.expected_workflow_revision:
            return {
                "valid": False,
                "code": "workflow_revision_mismatch",
                "message": "The workflow revision changed while this review was open.",
            }
        if self._brief_digest(project_id, request.brief_id) != request.expected_brief_digest:
            return {
                "valid": False,
                "code": "brief_digest_mismatch",
                "message": "The clip brief changed while this review was open.",
            }
        live = {
            card.source_module_id: card.source_record_digest
            for card in self.build_source_cards(project_id, request.brief_id)
        }
        for module_id, digest in request.expected_source_record_digests.items():
            if live.get(module_id) != digest:
                return {
                    "valid": False,
                    "code": "source_record_digest_mismatch",
                    "message": "A canonical source record changed while this review was open.",
                }
        blocking = [
            item
            for item in self.detect_clip_brief_conflicts(project_id, request.brief_id)
            if item.blocks_review_action
        ]
        if descriptor.action_descriptor_id not in self._available_actions(reference, blocking):
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "The action is no longer available for this exact brief.",
            }
        return {"valid": True, "code": "current", "message": "Exact clip brief remains current."}

    def _action_request(
        self, project_id: str, request_id: str
    ) -> BobaClipBriefActionRequestV1:
        _safe_id(project_id, "project id")
        _safe_id(request_id, "clip brief action request id")
        raw = self.store.load_boba_clip_brief_review_action(project_id, request_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA clip brief review action request is unavailable.")
        request = BobaClipBriefActionRequestV1.model_validate(raw)
        if request.project_id != project_id:
            raise ValidationError("Clip brief action belongs to another project.")
        return request

    async def submit_clip_brief_action_to_owner(
        self, project_id: str, request_id: str
    ) -> BobaClipBriefActionReceiptV1:
        """Submit to the canonical owner and persist an immutable receipt."""
        request = self._action_request(project_id, request_id)
        existing = self.store.load_boba_clip_brief_review_receipt_for_action(
            project_id, request_id
        )
        if isinstance(existing, Mapping):
            receipt = BobaClipBriefActionReceiptV1.model_validate(existing)
            return receipt.model_copy(update={"duplicate_request_reused": True})
        validation = self.validate_clip_brief_action_request(project_id, request_id)
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
        if descriptor.owning_module_id == "creator_learning":
            return await self._submit_creator_feedback(project_id, request, descriptor)
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
        request: BobaClipBriefActionRequestV1,
        *,
        canonical_status: str,
        stale_state_rejected: bool = False,
        error_code: str | None = None,
        message: str = "",
        limitations: list[str] | None = None,
    ) -> BobaClipBriefActionReceiptV1:
        return BobaClipBriefActionReceiptV1(
            clip_brief_action_receipt_id=f"clip_brief_receipt_{uuid4().hex}",
            clip_brief_action_request_id=request.clip_brief_action_request_id,
            project_id=request.project_id,
            brief_id=request.brief_id,
            candidate_id=request.candidate_id,
            clip_id=request.clip_id,
            owning_module_id=request.owning_module_id,
            owning_operation_id=request.owning_operation_id,
            completed_at=now_iso(),
            accepted_by_owner=False,
            canonical_status=canonical_status,
            authoritative_state_changed=False,
            stale_state_rejected=stale_state_rejected,
            error_code=error_code,
            bounded_error_message=_safe_text(message, 900),
            limitations=limitations or [],
        )

    async def _submit_creator_feedback(
        self,
        project_id: str,
        request: BobaClipBriefActionRequestV1,
        descriptor: BobaClipBriefActionDescriptorV1,
    ) -> BobaClipBriefActionReceiptV1:
        """Route to Creator Learning, the owner of advisory creator feedback."""
        action = str(request.decision_value or "noted")
        event_type = {
            "approved": "approval",
            "rejected": "rejection",
            "liked": "rating",
            "disliked": "rating",
            "chose": "chosen_alternative",
            "noted": "preference_note",
        }.get(action, "preference_note")
        try:
            record = await self.integration.record_creator_feedback_event(
                project_id,
                event_type=event_type,  # type: ignore[arg-type]
                target_type="clip_brief",
                target_id=request.brief_id,
                user_action=action,  # type: ignore[arg-type]
                note=request.bounded_reason,
                reversible=True,
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
                        "Creator Learning rejected the feedback; nothing changed.",
                    ],
                ),
            )
        payload = _as_mapping(record)
        canonical_id = _safe_text(payload.get("event_id"), 180)
        if not canonical_id:
            return self._persist_receipt(
                project_id,
                self._receipt(
                    request,
                    canonical_status="malformed_owner_response",
                    error_code="malformed_canonical_response",
                    message="The owning module returned no canonical record identifier.",
                    limitations=["No authoritative state changed."],
                ),
            )
        accepted = self._receipt(request, canonical_status="recorded")
        return self._persist_receipt(
            project_id,
            accepted.model_copy(
                update={
                    "owning_module_id": "creator_learning",
                    "owning_operation_id": "record_creator_feedback_event",
                    "accepted_by_owner": True,
                    "canonical_request_id": request.clip_brief_action_request_id,
                    "canonical_record_id": canonical_id,
                    "canonical_record_digest": _digest(_safe_payload(payload)),
                    "canonical_status": _safe_text(
                        payload.get("user_action") or "recorded", 160
                    ),
                    # Creator Learning owns an advisory record. It has a canonical
                    # identity but changes no clip-brief authority.
                    "authoritative_state_changed": False,
                    "canonical_refresh_required": True,
                    "limitations": [
                        "Creator Learning feedback is advisory and never overrides "
                        "source truth or safety.",
                        *descriptor.does_not_do,
                    ][:16],
                }
            ),
        )

    def _persist_receipt(
        self, project_id: str, receipt: BobaClipBriefActionReceiptV1
    ) -> BobaClipBriefActionReceiptV1:
        if receipt.authoritative_state_changed and not (
            receipt.canonical_record_id and receipt.canonical_record_digest
        ):
            raise ValidationError(
                "Authoritative state cannot change without a canonical owner record."
            )
        self.store.save_boba_clip_brief_review_receipt(
            project_id,
            receipt.clip_brief_action_receipt_id,
            receipt.model_dump(mode="json"),
        )
        return receipt

    def inspect_clip_brief_action_receipt(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        request = self._action_request(project_id, request_id)
        receipt = self.store.load_boba_clip_brief_review_receipt_for_action(
            project_id, request_id
        )
        return {
            "request": request.model_dump(mode="json"),
            "receipt": _safe_payload(receipt) if receipt else None,
        }

    # ------------------------------------------------------------------
    # Events, timeline, build, export, reset
    # ------------------------------------------------------------------
    def inspect_clip_brief_events(
        self, project_id: str, *, after_sequence: int = 0, limit: int = _MAX_EVENTS
    ) -> dict[str, Any]:
        """Project bounded, de-duplicated canonical events. No invented progress."""
        _safe_id(project_id, "project id")
        seen: set[tuple[str, str]] = set()
        events: list[BobaClipBriefReviewEventV1] = []
        truncated_at_source = False
        for source_id in ("clip_brief", "clip_discovery", "editorial_decision",
                          "workflow_controller"):
            payload = self._source_payload(source_id, project_id)
            rows = payload.get("events")
            if not isinstance(rows, list):
                continue
            if len(rows) > _MAX_EVENTS:
                # Older canonical events exist but are not read. Say so rather
                # than implying the stream is complete.
                truncated_at_source = True
            for row in rows[-_MAX_EVENTS:]:
                if not isinstance(row, Mapping):
                    continue
                safe = _as_mapping(_safe_payload(row))
                event_id = _safe_text(
                    safe.get("event_id") or safe.get("id"), 180
                ) or _stable_id("clip_brief_event", source_id, _digest(safe))
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
                events.append(
                    BobaClipBriefReviewEventV1(
                        event_id=_stable_id("clip_brief_event", source_id, event_id),
                        project_id=project_id,
                        brief_id=_safe_text(safe.get("brief_id"), 160) or None,
                        candidate_id=_safe_text(safe.get("candidate_id"), 128) or None,
                        source_module_id=source_id,
                        source_event_id=event_id,
                        source_sequence=sequence,
                        created_at=_safe_text(
                            safe.get("created_at") or safe.get("occurred_at"), 80
                        )
                        or None,
                        event_type=event_type,
                        severity=_safe_text(safe.get("severity") or "informational", 80),
                        technical_message=_safe_text(
                            safe.get("technical_message") or safe.get("message"), 900
                        ),
                        easy_message=_safe_text(
                            safe.get("easy_message") or safe.get("summary"), 900
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
                        not in {"heartbeat", "keepalive", "ping", "stream_open", "stream_idle"},
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
            "schema_version": "boba_clip_brief_review_events_v1",
            "project_id": project_id,
            "events": [item.model_dump(mode="json") for item in bounded],
            "has_more": len(events) > len(bounded) or truncated_at_source,
            "latest_sequence": max(
                (item.source_sequence or 0 for item in bounded), default=after_sequence
            ),
        }

    def inspect_clip_brief_timeline(
        self, project_id: str, *, limit: int = MAX_TIMELINE_ENTRIES
    ) -> dict[str, Any]:
        events = self.inspect_clip_brief_events(project_id, limit=limit)["events"]
        entries = [
            BobaClipBriefReviewTimelineEntryV1(
                timeline_entry_id=_stable_id("clip_brief_timeline", str(event["event_id"])),
                project_id=project_id,
                brief_id=event.get("brief_id"),
                source_module_id=str(event["source_module_id"]),
                source_record_id=str(event.get("source_event_id") or event["event_id"]),
                source_event_id=event.get("source_event_id"),
                event_type=str(event["event_type"]),
                occurred_at=event.get("created_at"),
                timestamp_precision="source" if event.get("created_at") else "unknown",
                sequence=event.get("source_sequence"),
                confirmed_order=event.get("source_sequence") is not None,
                title=str(event["event_type"]).replace("_", " ").title() or "Canonical Event",
                bounded_summary=str(event.get("easy_message") or ""),
                confirmed_fact=str(event.get("confirmed_fact") or ""),
                source_assessment=str(event.get("assessment") or ""),
                severity=str(event.get("severity") or "informational"),
                current=not bool(event.get("replayed")),
                historical=bool(event.get("replayed")),
            ).model_dump(mode="json")
            for event in events
        ]
        return {
            "schema_version": "boba_clip_brief_review_timeline_v1",
            "project_id": project_id,
            "entries": entries[:MAX_TIMELINE_ENTRIES],
        }

    def _signal_usage(self, project_id: str) -> BobaClipBriefReviewSignalUsageV1:
        def present(source_id: str) -> bool:
            return bool(self._source_payload(source_id, project_id))

        return BobaClipBriefReviewSignalUsageV1(
            canonical_clip_brief_records=present("clip_brief"),
            canonical_candidate_records=present("clip_discovery"),
            canonical_editorial_records=present("editorial_decision"),
            canonical_creative_records=present("creative_director"),
            canonical_hook_retention_records=present("hook_retention"),
            canonical_caption_motion_records=present("caption_motion"),
            canonical_music_mood_records=present("music_mood"),
            canonical_workflow_records=present("workflow_controller"),
            canonical_rights_records=present("rights_permission_gate"),
            canonical_artifact_records=present("artifact_inspector"),
            unavailable_signals=[
                source_id
                for source_id in build_fixed_clip_brief_source_registry()
                if not present(source_id)
            ],
            limitations=[
                "Signal usage records which canonical owners were read, not who decided.",
            ],
        )

    def build_clip_brief_review(self, project_id: str) -> dict[str, Any]:
        registry = self.build_clip_brief_review_registry(project_id)
        references = self.build_clip_brief_references(project_id)
        items = [
            self._queue_item(project_id, reference, index)
            for index, reference in enumerate(references)
        ]
        items.sort(key=lambda item: (item.priority_tier, item.deterministic_sort_key))
        events = self.inspect_clip_brief_events(project_id)
        notifications = [
            BobaClipBriefReviewNotificationV1(
                notification_id=_stable_id(
                    "clip_brief_notification", project_id, item.brief_id
                ),
                project_id=project_id,
                brief_id=item.brief_id,
                source_module_id="clip_brief",
                source_record_id=item.source_record_ids[0]
                if item.source_record_ids
                else "clip_brief",
                notification_type=(
                    "blocking"
                    if item.blocker_count
                    else "conflict"
                    if item.conflict_count
                    else "missing_required_fields"
                    if item.missing_required_field_count
                    else "warning"
                ),
                severity="critical" if item.blocker_count else "warning",
                title=item.title,
                bounded_message=item.bounded_summary or item.priority_reason,
                requires_attention=True,
                human_action_required=item.human_action_required,
                current=item.current,
                limitations=[
                    "Acknowledging this notice does not resolve the source issue.",
                ],
            )
            for item in items
            if item.blocker_count
            or item.conflict_count
            or item.missing_required_field_count
            or item.warning_count
        ][:64]
        summary = BobaClipBriefReviewSummaryV1(
            total_brief_count=len(items),
            current_brief_count=sum(1 for item in items if item.current),
            stale_brief_count=sum(1 for item in items if item.stale),
            historical_brief_count=sum(1 for item in items if item.historical),
            superseded_brief_count=sum(1 for item in items if item.superseded),
            complete_brief_count=sum(
                1
                for item in items
                if item.completeness_status in {"complete", "complete_with_optional_gaps"}
            ),
            missing_required_field_count=sum(
                item.missing_required_field_count for item in items
            ),
            missing_evidence_count=sum(item.missing_evidence_count for item in items),
            conflict_count=sum(item.conflict_count for item in items),
            pending_human_review_count=sum(1 for item in items if item.human_action_required),
            blocked_brief_count=sum(1 for item in items if item.blocker_count),
            safest_next_review_action=(
                "Review the highest-priority clip brief and its source evidence."
                if items
                else "No clip brief review work is outstanding."
            ),
            required_human_actions=[
                f"{item.brief_id}: {item.priority_reason}"
                for item in items
                if item.human_action_required
            ][:24],
            limitations=[
                "Counts describe projected canonical records, not panel decisions.",
                "Completeness counts are not quality counts.",
            ],
        )
        result = BobaClipBriefReviewSetV1(
            project_id=project_id,
            source_id=_safe_text(
                self._source_payload("clip_brief", project_id).get("source_id"), 512
            ),
            registry_snapshots=[
                BobaClipBriefRegistrySnapshotV1.model_validate(
                    registry["registry_snapshot"]
                )
            ],
            brief_references=references,
            brief_queue_items=items,
            events=[
                BobaClipBriefReviewEventV1.model_validate(item) for item in events["events"]
            ],
            notifications=notifications,
            review_summary=summary,
            signal_usage=self._signal_usage(project_id),
            limitations=[
                "Clip Brief Panel V1 is a read-only projection, evidence "
                "workspace, comparison interface and canonical routing layer. It "
                "does not generate, regenerate or rewrite briefs.",
                "Completeness means only that required owner-schema fields are "
                "present; it is not quality, safety or approval.",
                "No authoritative clip brief action exists in V1.",
            ],
        )
        self.store.save_boba_clip_brief_review(project_id, result.model_dump(mode="json"))
        return result.model_dump(mode="json")

    def load_clip_brief_review(self, project_id: str) -> dict[str, Any] | None:
        _safe_id(project_id, "project id")
        return self.store.load_boba_clip_brief_review(project_id)

    def export_clip_brief_review(
        self, project_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "boba_clip_brief_review_export_v1",
            "project_id": project_id,
            "exported_at": now_iso(),
            "queue": self.build_clip_brief_queue(project_id, limit=MAX_QUEUE_PAGE_SIZE),
            "timeline": self.inspect_clip_brief_timeline(project_id, limit=50),
            "privacy": {
                "private_paths_excluded": True,
                "raw_media_excluded": True,
                "raw_transcripts_excluded": True,
                "sensitive_values_excluded": True,
                "source_records_duplicated": False,
                "brief_text_rewritten": False,
                "source_media_modified": False,
                "accepted_output_modified": False,
                "upload_used": False,
                "publication_used": False,
            },
        }
        if session_id:
            payload["session"] = self.get_clip_brief_review_session(
                project_id, session_id
            ).model_dump(mode="json")
        return _as_mapping(_safe_payload(payload))

    def reset_clip_brief_review_metadata(
        self, project_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        if session_id:
            _safe_id(session_id, "clip brief review session id")
            removed = self.store.delete_boba_clip_brief_review_session(
                project_id, session_id
            )
            return {
                "schema_version": "boba_clip_brief_review_reset_v1",
                "project_id": project_id,
                "session_removed": removed,
                "clip_brief_records_preserved": True,
                "candidate_review_history_preserved": True,
                "review_ui_history_preserved": True,
                "action_receipt_history_preserved": True,
            }
        return self.store.reset_boba_clip_brief_review_metadata(project_id)

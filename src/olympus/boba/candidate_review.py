"""Read-only BOBA Candidate Review Panel projections and constrained action routing.

The Candidate Review Panel is a specialized mode of the BOBA Review UI. It is a
presentation, comparison and canonical action-routing layer. It never discovers
candidates, never reranks them, never recomputes a source-owned score, never
builds a hidden composite score, and never chooses a winner.

Candidate identity, exact source time ranges, original ranks, original scores and
their original scales and definitions always remain owned by the module that
produced them.
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
# semantics byte-identical to Review UI V1, which the confirmation tokens rely on.
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


CandidateReviewFilter = Literal[
    "all_current",
    "human_review_required",
    "source_shortlisted",
    "selected",
    "rejected",
    "blocked",
    "stale",
    "overlapping",
    "missing_evidence",
    "historical",
]
CandidateReviewSort = Literal[
    "review_priority",
    "original_rank",
    "source_start_time",
    "duration",
    "creation_order",
    "candidate_id",
]
CandidateComparisonType = Literal[
    "side_by_side",
    "rank",
    "score_breakdown",
    "source_window",
    "overlap",
    "evidence_coverage",
    "creative_plan",
    "historical_revision",
    "unknown",
]
CandidateReviewStatus = Literal[
    "awaiting_human_review",
    "source_shortlisted",
    "source_selected",
    "source_rejected",
    "blocked",
    "informational",
    "historical",
    "unavailable",
    "unknown",
]

# Precision used for every time-range calculation. Source ranges are float
# seconds; rounding to milliseconds removes binary float noise deterministically
# without ever widening or narrowing a candidate window.
# Candidate identifiers are opaque, source-owned tokens.
_SAFE_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

_TIME_PRECISION = 3
_EXACT_BOUNDARY_EPSILON = 1e-6
SUBSTANTIAL_OVERLAP_IOU_THRESHOLD = 0.60

MAX_COMPARISON_CANDIDATES = 4
MAX_LOADED_CANDIDATES = 500
MAX_QUEUE_PAGE_SIZE = 50
MAX_TRANSCRIPT_CONTEXT_SECONDS = 60
MAX_TIMELINE_ENTRIES = 100
_MAX_EVENTS = 100
_MAX_SOURCE_CARDS = 24
_MAX_SCORE_CARDS = 32
_MAX_OVERLAP_RECORDS = 200
_MAX_REASON_LENGTH = 500


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


def _overlap_metrics(
    a_start: float,
    a_end: float,
    b_start: float,
    b_end: float,
) -> dict[str, float]:
    """Deterministic time-range overlap from exact persisted boundaries."""
    intersection_start = max(a_start, b_start)
    intersection_end = min(a_end, b_end)
    overlap = round(max(0.0, intersection_end - intersection_start), _TIME_PRECISION)
    duration_a = round(max(0.0, a_end - a_start), _TIME_PRECISION)
    duration_b = round(max(0.0, b_end - b_start), _TIME_PRECISION)
    union = round(duration_a + duration_b - overlap, _TIME_PRECISION)
    iou = round(overlap / union, 6) if union > 0 else 0.0
    return {
        "overlap_seconds": overlap,
        "union_seconds": max(0.0, union),
        "intersection_over_union": max(0.0, min(1.0, iou)),
        "candidate_a_coverage": round(overlap / duration_a, 6) if duration_a > 0 else 0.0,
        "candidate_b_coverage": round(overlap / duration_b, 6) if duration_b > 0 else 0.0,
    }


class BobaCandidateReviewRegistrySnapshotV1(BobaContract):
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = "1"
    created_at: str = Field(default_factory=now_iso)
    candidate_source_ids: list[str] = Field(default_factory=list, max_length=32)
    available_source_ids: list[str] = Field(default_factory=list, max_length=32)
    unavailable_source_ids: list[str] = Field(default_factory=list, max_length=32)
    action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    unavailable_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    registry_digest: str = Field(min_length=64, max_length=64)
    immutable: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaCandidateReferenceV1(BobaContract):
    candidate_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    candidate_id: str = Field(min_length=1, max_length=128)
    candidate_revision_id: str | None = None
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    candidate_schema_id: str = Field(default="unknown", max_length=180)
    candidate_schema_version: str = Field(default="unknown", max_length=80)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(gt=0.0)
    transcript_segment_ids: list[str] = Field(default_factory=list, max_length=32)
    speaker_reference_ids: list[str] = Field(default_factory=list, max_length=16)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    superseding_candidate_id: str | None = None
    source_media_reference_id: str = Field(default="", max_length=180)
    created_at: str = Field(default_factory=now_iso)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_exact_source_window(self) -> BobaCandidateReferenceV1:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Candidate end_seconds must be greater than start_seconds.")
        expected = round(self.end_seconds - self.start_seconds, _TIME_PRECISION)
        if abs(expected - round(self.duration_seconds, _TIME_PRECISION)) > 1e-3:
            raise ValueError(
                "Candidate duration_seconds must match the exact persisted source range."
            )
        return self


class BobaCandidateReviewSessionV1(BobaContract):
    candidate_review_session_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    reviewer_context_id: str = Field(min_length=1, max_length=160)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    expires_at: str
    selected_candidate_id: str | None = None
    comparison_candidate_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_CANDIDATES
    )
    locally_shortlisted_candidate_ids: list[str] = Field(default_factory=list, max_length=64)
    active_filter: CandidateReviewFilter = "all_current"
    active_sort: CandidateReviewSort = "review_priority"
    show_rejected: bool = False
    show_historical: bool = False
    show_technical_details: bool = False
    transcript_context_seconds: int = Field(
        default=15, ge=0, le=MAX_TRANSCRIPT_CONTEXT_SECONDS
    )
    evidence_drawer_open: bool = False
    timeline_drawer_open: bool = False
    session_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateQueueItemV1(BobaContract):
    candidate_queue_item_id: str = Field(min_length=1, max_length=180)
    candidate_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    candidate_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(default="", max_length=900)
    original_discovery_status: str = Field(default="unknown", max_length=160)
    original_rank: int | None = Field(default=None, ge=1)
    original_rank_total: int | None = Field(default=None, ge=0)
    rank_owner_module_id: str = Field(default="", max_length=160)
    primary_score: float | None = None
    primary_score_name: str = Field(default="", max_length=160)
    primary_score_owner_module_id: str = Field(default="", max_length=160)
    editorial_status: str = Field(default="unavailable", max_length=160)
    review_status: CandidateReviewStatus = "unknown"
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    rejected: bool = False
    selected: bool = False
    human_action_required: bool = False
    blocker_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    duplicate_group_id: str | None = None
    overlap_group_ids: list[str] = Field(default_factory=list, max_length=24)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=16)
    source_module_ids: list[str] = Field(default_factory=list, max_length=16)
    source_record_ids: list[str] = Field(default_factory=list, max_length=24)
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=24)
    priority_tier: int = Field(default=0, ge=0, le=999)
    priority_reason: str = Field(default="", max_length=160)
    deterministic_sort_key: str = Field(min_length=1, max_length=240)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateSourceCardV1(BobaContract):
    source_card_id: str = Field(min_length=1, max_length=180)
    candidate_snapshot_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=160)
    authority_domain: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    source_schema_id: str = Field(default="unknown", max_length=180)
    source_schema_version: str = Field(default="unknown", max_length=80)
    title: str = Field(min_length=1, max_length=240)
    original_status: str = Field(default="unknown", max_length=160)
    original_decision: str | None = Field(default=None, max_length=200)
    original_rank: int | None = Field(default=None, ge=1)
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
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateScoreCardV1(BobaContract):
    score_card_id: str = Field(min_length=1, max_length=180)
    candidate_snapshot_id: str | None = None
    candidate_id: str = Field(min_length=1, max_length=128)
    source_module_id: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=180)
    score_name: str = Field(min_length=1, max_length=160)
    score_value: float
    score_scale_min: float
    score_scale_max: float
    score_definition: str = Field(min_length=1, max_length=600)
    score_direction: Literal["higher_is_better", "lower_is_better", "unknown"] = "unknown"
    rank: int | None = Field(default=None, ge=1)
    rank_total: int | None = Field(default=None, ge=0)
    tied: bool = False
    weight: float | None = None
    weighted_by_source: bool = False
    source_owned_composite: bool = False
    current: bool = True
    stale: bool = False
    comparable_across_candidates: bool = True
    bounded_explanation: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateOverlapV1(BobaContract):
    overlap_record_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_a_id: str = Field(min_length=1, max_length=128)
    candidate_b_id: str = Field(min_length=1, max_length=128)
    candidate_a_start_seconds: float = Field(ge=0.0)
    candidate_a_end_seconds: float = Field(ge=0.0)
    candidate_b_start_seconds: float = Field(ge=0.0)
    candidate_b_end_seconds: float = Field(ge=0.0)
    overlap_seconds: float = Field(ge=0.0)
    union_seconds: float = Field(ge=0.0)
    intersection_over_union: float = Field(ge=0.0, le=1.0)
    candidate_a_coverage: float = Field(ge=0.0, le=1.0)
    candidate_b_coverage: float = Field(ge=0.0, le=1.0)
    exact_duplicate_window: bool = False
    substantial_overlap: bool = False
    partial_overlap: bool = False
    contained: bool = False
    source_time_overlap_only: bool = True
    same_candidate_identity: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Overlap is time-range overlap computed from exact persisted "
            "boundaries. It is not a semantic duplication claim.",
        ],
        max_length=24,
    )


class BobaCandidateComparisonV1(BobaContract):
    comparison_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_ids: list[str] = Field(min_length=2, max_length=MAX_COMPARISON_CANDIDATES)
    created_at: str = Field(default_factory=now_iso)
    comparison_type: CandidateComparisonType = "side_by_side"
    common_source_id: str = Field(default="", max_length=512)
    same_workflow_run: bool = False
    candidate_snapshot_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_CANDIDATES
    )
    rank_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    score_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    duration_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    overlap_record_ids: list[str] = Field(default_factory=list, max_length=16)
    discovery_reason_comparison: list[dict[str, Any]] = Field(
        default_factory=list, max_length=8
    )
    editorial_status_comparison: list[dict[str, Any]] = Field(
        default_factory=list, max_length=8
    )
    evidence_coverage_comparison: list[dict[str, Any]] = Field(
        default_factory=list, max_length=8
    )
    warnings_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    limitations_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    no_automatic_winner: Literal[True] = True
    bounded_summary: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateActionDescriptorV1(BobaContract):
    action_descriptor_id: str = Field(min_length=1, max_length=180)
    display_name: str = Field(min_length=1, max_length=160)
    action_class: str = Field(min_length=1, max_length=120)
    owning_module_id: str = Field(min_length=1, max_length=160)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    supported_candidate_states: list[str] = Field(default_factory=list, max_length=16)
    allowed_decision_values: list[str] = Field(default_factory=list, max_length=16)
    requires_reason: bool = False
    maximum_reason_length: int = Field(default=_MAX_REASON_LENGTH, ge=0, le=1_200)
    requires_confirmation: bool = True
    requires_current_snapshot: bool = True
    requires_workflow_revision: bool = False
    requires_candidate_digest: bool = True
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
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateActionRequestV1(BobaContract):
    candidate_action_request_id: str = Field(min_length=1, max_length=180)
    candidate_review_session_id: str = Field(min_length=1, max_length=180)
    candidate_snapshot_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    candidate_id: str = Field(min_length=1, max_length=128)
    candidate_revision_id: str | None = None
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
    expected_candidate_digest: str = Field(min_length=64, max_length=64)
    expected_source_record_digests: dict[str, str] = Field(
        default_factory=dict, max_length=24
    )
    confirmation_context_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=180)
    confirmed: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateActionReceiptV1(BobaContract):
    candidate_action_receipt_id: str = Field(min_length=1, max_length=180)
    candidate_action_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
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
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateSnapshotV1(BobaContract):
    candidate_snapshot_id: str = Field(min_length=1, max_length=180)
    candidate_review_session_id: str = Field(min_length=1, max_length=180)
    candidate_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    candidate_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso)
    refreshed_at: str = Field(default_factory=now_iso)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    candidate_digest: str = Field(min_length=64, max_length=64)
    source_record_references: list[dict[str, str]] = Field(
        default_factory=list, max_length=24
    )
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=24)
    source_card_ids: list[str] = Field(default_factory=list, max_length=_MAX_SOURCE_CARDS)
    score_card_ids: list[str] = Field(default_factory=list, max_length=_MAX_SCORE_CARDS)
    comparison_ids: list[str] = Field(default_factory=list, max_length=8)
    overlap_record_ids: list[str] = Field(default_factory=list, max_length=24)
    discovery_status: str = Field(default="unavailable", max_length=160)
    rank_status: str = Field(default="unavailable", max_length=160)
    editorial_status: str = Field(default="unavailable", max_length=160)
    rights_status: str = Field(default="unavailable", max_length=160)
    workflow_status: str = Field(default="unavailable", max_length=160)
    artifact_status: str = Field(default="unavailable", max_length=160)
    validation_status: str = Field(default="unavailable", max_length=160)
    human_review_status: str = Field(default="unavailable", max_length=160)
    current: bool = True
    stale: bool = False
    historical: bool = False
    selected: bool = False
    rejected: bool = False
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    limitation_count: int = Field(default=0, ge=0)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=16)
    confirmation_context_digest: str = Field(min_length=64, max_length=64)
    snapshot_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateReviewEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_id: str | None = None
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
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateReviewTimelineEntryV1(BobaContract):
    timeline_entry_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_id: str | None = None
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
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateReviewNotificationV1(BobaContract):
    notification_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_id: str | None = None
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
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateReviewSummaryV1(BobaContract):
    total_candidate_count: int = Field(default=0, ge=0)
    current_candidate_count: int = Field(default=0, ge=0)
    stale_candidate_count: int = Field(default=0, ge=0)
    historical_candidate_count: int = Field(default=0, ge=0)
    selected_candidate_count: int = Field(default=0, ge=0)
    rejected_candidate_count: int = Field(default=0, ge=0)
    pending_human_review_count: int = Field(default=0, ge=0)
    blocked_candidate_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    substantial_overlap_pair_count: int = Field(default=0, ge=0)
    exact_duplicate_window_count: int = Field(default=0, ge=0)
    current_selected_candidate_id: str | None = None
    current_comparison_candidate_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_CANDIDATES
    )
    safest_next_review_action: str | None = None
    required_human_actions: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateReviewSignalUsageV1(BobaContract):
    canonical_candidate_discovery_records: bool = False
    canonical_ranking_records: bool = False
    canonical_editorial_records: bool = False
    canonical_explanation_records: bool = False
    canonical_creative_records: bool = False
    canonical_workflow_records: bool = False
    canonical_rights_records: bool = False
    canonical_artifact_records: bool = False
    review_ui_integration: bool = True
    exact_time_range_validation: bool = True
    exact_digest_validation: bool = True
    stale_snapshot_protection: bool = True
    deterministic_overlap_calculation: bool = True
    canonical_action_receipts: bool = True
    truthful_events: bool = True
    arbitrary_candidate_created: bool = False
    candidate_score_recalculated: bool = False
    hidden_composite_score_created: bool = False
    candidate_selected_locally: bool = False
    candidate_rejected_locally: bool = False
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


class BobaCandidateReviewSetV1(BobaContract):
    schema_version: Literal["boba_candidate_review_v1"] = "boba_candidate_review_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    registry_snapshots: list[BobaCandidateReviewRegistrySnapshotV1] = Field(
        default_factory=list, max_length=8
    )
    review_sessions: list[BobaCandidateReviewSessionV1] = Field(
        default_factory=list, max_length=16
    )
    candidate_references: list[BobaCandidateReferenceV1] = Field(
        default_factory=list, max_length=MAX_LOADED_CANDIDATES
    )
    candidate_queue_items: list[BobaCandidateQueueItemV1] = Field(
        default_factory=list, max_length=MAX_LOADED_CANDIDATES
    )
    candidate_snapshots: list[BobaCandidateSnapshotV1] = Field(
        default_factory=list, max_length=16
    )
    source_cards: list[BobaCandidateSourceCardV1] = Field(
        default_factory=list, max_length=_MAX_SOURCE_CARDS
    )
    score_cards: list[BobaCandidateScoreCardV1] = Field(
        default_factory=list, max_length=_MAX_SCORE_CARDS
    )
    comparisons: list[BobaCandidateComparisonV1] = Field(default_factory=list, max_length=8)
    overlap_records: list[BobaCandidateOverlapV1] = Field(
        default_factory=list, max_length=_MAX_OVERLAP_RECORDS
    )
    action_requests: list[BobaCandidateActionRequestV1] = Field(
        default_factory=list, max_length=64
    )
    action_receipts: list[BobaCandidateActionReceiptV1] = Field(
        default_factory=list, max_length=64
    )
    timeline_entries: list[BobaCandidateReviewTimelineEntryV1] = Field(
        default_factory=list, max_length=MAX_TIMELINE_ENTRIES
    )
    events: list[BobaCandidateReviewEventV1] = Field(
        default_factory=list, max_length=_MAX_EVENTS
    )
    notifications: list[BobaCandidateReviewNotificationV1] = Field(
        default_factory=list, max_length=64
    )
    review_summary: BobaCandidateReviewSummaryV1 = Field(
        default_factory=BobaCandidateReviewSummaryV1
    )
    signal_usage: BobaCandidateReviewSignalUsageV1 = Field(
        default_factory=BobaCandidateReviewSignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


CANDIDATE_QUEUE_PRIORITY_TIERS: tuple[tuple[int, str], ...] = (
    (10, "selected_candidate_with_critical_rights_or_safety_block"),
    (20, "requires_exact_human_selection_decision"),
    (30, "conflicting_editorial_records"),
    (40, "missing_required_discovery_or_rank_evidence"),
    (50, "stale_canonical_evidence"),
    (60, "source_shortlisted_by_editorial_decision"),
    (70, "strong_original_rank_without_human_decision"),
    (80, "substantial_overlap_requires_comparison"),
    (90, "current_candidate_in_source_rank_order"),
    (100, "rejected_current_candidate"),
    (110, "superseded_candidate"),
    (120, "historical_candidate"),
)

# Fixed candidate evidence sources. Each entry names the exact owning module,
# its authority domain, the fixed store loader and whether it is advisory.
_CANDIDATE_SOURCES: tuple[tuple[str, str, str, str, bool], ...] = (
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
    ("clip_brief", "Clip Brief Generator", "creative_brief", "load_clip_briefs", True),
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

_REQUIRED_SOURCE_IDS = ("clip_discovery",)

# Score definitions are copied verbatim from the owning module's contract so the
# panel never invents a scale, a direction or a meaning.
_DISCOVERY_SCORES: tuple[tuple[str, str, float, float, str], ...] = (
    (
        "confidence",
        "confidence",
        0.0,
        1.0,
        "Candidate Clip Discovery confidence that the detected window is a "
        "coherent candidate clip. Scale 0.0-1.0. Not a performance or "
        "virality prediction.",
    ),
    (
        "standalone_score",
        "standalone_score",
        0.0,
        1.0,
        "Candidate Clip Discovery estimate of how well the window stands alone "
        "without surrounding context. Scale 0.0-1.0.",
    ),
)

_RANKING_BREAKDOWN_KEYS: tuple[str, ...] = (
    "hook_score",
    "payoff_score",
    "standalone_score",
    "emotional_score",
    "clarity_score",
    "novelty_score",
    "pacing_score",
    "retention_score",
    "context_risk_score",
    "repetition_penalty",
    "overlap_penalty",
    "rights_safety_penalty",
    "memory_alignment_score",
    "final_score",
)

_PENALTY_KEYS = frozenset(
    {"context_risk_score", "repetition_penalty", "overlap_penalty", "rights_safety_penalty"}
)


def build_fixed_candidate_source_registry() -> dict[str, dict[str, Any]]:
    """Return the fixed candidate evidence source registry."""
    registry: dict[str, dict[str, Any]] = {}
    for module_id, title, domain, loader_name, advisory in _CANDIDATE_SOURCES:
        if module_id in registry:
            raise ValidationError("Duplicate BOBA candidate review source descriptor.")
        registry[module_id] = {
            "source_id": module_id,
            "title": title,
            "authority_domain": domain,
            "loader": loader_name,
            "advisory_only": advisory,
            "required": module_id in _REQUIRED_SOURCE_IDS,
        }
    return registry


def build_fixed_candidate_action_registry() -> dict[str, BobaCandidateActionDescriptorV1]:
    """Return the fixed candidate action registry.

    Only actions with a real, already-implemented canonical owning operation are
    available in V1. Everything else is declared with its limitation rather than
    being wired to an invented owner.
    """
    definitions = [
        BobaCandidateActionDescriptorV1(
            action_descriptor_id="candidate_action_submit_feedback_v1",
            display_name="Submit candidate feedback",
            action_class="advisory_creator_feedback",
            owning_module_id="creator_learning",
            owning_operation_id="record_creator_feedback_event",
            supported_candidate_states=["current", "stale", "rejected", "selected"],
            allowed_decision_values=["approved", "rejected", "liked", "disliked", "chose"],
            requires_reason=True,
            maximum_reason_length=_MAX_REASON_LENGTH,
            requires_confirmation=True,
            requires_current_snapshot=True,
            requires_candidate_digest=True,
            requires_source_record_digests=True,
            requires_reviewer_context=True,
            authoritative=False,
            allowed_in_v1=True,
            availability="available",
            consequences=[
                "Records a bounded, reversible creator-feedback event owned by "
                "Creator Learning for this exact candidate.",
            ],
            does_not_do=[
                "Does not select or reject the candidate editorially.",
                "Does not change the Editorial Decision record.",
                "Does not change the candidate rank or score.",
                "Does not grant Rights or create a Safety allowance.",
                "Does not render, advance the workflow, upload or publish.",
            ],
            limitations=[
                "Creator Learning feedback is explicitly advisory; it never "
                "overrides source truth or safety.",
            ],
        ),
        BobaCandidateActionDescriptorV1(
            action_descriptor_id="candidate_action_record_review_note_v1",
            display_name="Record candidate review note",
            action_class="advisory_creator_note",
            owning_module_id="creator_learning",
            owning_operation_id="record_creator_feedback_event",
            supported_candidate_states=["current", "stale", "rejected", "selected", "historical"],
            allowed_decision_values=["noted"],
            requires_reason=True,
            maximum_reason_length=_MAX_REASON_LENGTH,
            requires_confirmation=True,
            requires_current_snapshot=True,
            requires_candidate_digest=True,
            requires_source_record_digests=False,
            requires_reviewer_context=True,
            authoritative=False,
            allowed_in_v1=True,
            availability="available",
            consequences=[
                "Records a bounded reviewer note owned by Creator Learning "
                "against this exact candidate.",
            ],
            does_not_do=[
                "Does not select, reject or shortlist the candidate.",
                "Does not change any source-owned decision.",
            ],
            limitations=["A review note is advisory metadata, not a decision."],
        ),
        BobaCandidateActionDescriptorV1(
            action_descriptor_id="candidate_action_select_candidate_v1",
            display_name="Select exact candidate",
            action_class="human_editorial_selection",
            owning_module_id="editorial_decision",
            owning_operation_id="unavailable_no_canonical_human_selection_operation",
            supported_candidate_states=["current"],
            allowed_decision_values=["select"],
            requires_reason=True,
            requires_workflow_revision=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Editorial Decision owns candidate selection, but it exposes no "
                "operation that records a human selection for one exact candidate.",
                "Its only entry points regenerate the whole editorial set from "
                "signals, which would make the panel a second editorial engine.",
                "Unavailable in V1. No substitute owner was invented.",
            ],
        ),
        BobaCandidateActionDescriptorV1(
            action_descriptor_id="candidate_action_reject_candidate_v1",
            display_name="Reject exact candidate",
            action_class="human_editorial_rejection",
            owning_module_id="editorial_decision",
            owning_operation_id="unavailable_no_canonical_human_rejection_operation",
            supported_candidate_states=["current"],
            allowed_decision_values=["reject"],
            requires_reason=True,
            requires_workflow_revision=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Editorial Decision owns candidate rejection but exposes no "
                "single-candidate human rejection operation.",
                "The BOBA candidate approve/reject API operates on Content Scout "
                "source-video candidates, which are a different record type.",
                "Unavailable in V1.",
            ],
        ),
        BobaCandidateActionDescriptorV1(
            action_descriptor_id="candidate_action_request_revision_v1",
            display_name="Request candidate revision",
            action_class="human_revision_request",
            owning_module_id="editorial_decision",
            owning_operation_id="unavailable_no_canonical_revision_request_operation",
            supported_candidate_states=["current"],
            allowed_decision_values=["request_revision"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "No owning module records a per-candidate revision request.",
                "Candidate records carry no revision identity to bind a request to.",
            ],
        ),
        BobaCandidateActionDescriptorV1(
            action_descriptor_id="candidate_action_request_alternate_v1",
            display_name="Request alternate candidate",
            action_class="human_alternate_request",
            owning_module_id="clip_discovery",
            owning_operation_id="unavailable_no_canonical_alternate_request_operation",
            supported_candidate_states=["current"],
            allowed_decision_values=["request_alternate"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Requesting an alternate would require re-running Candidate Clip "
                "Discovery, which this panel must never do.",
            ],
        ),
    ]
    registry: dict[str, BobaCandidateActionDescriptorV1] = {}
    for descriptor in definitions:
        if descriptor.action_descriptor_id in registry:
            raise ValidationError("Duplicate BOBA candidate review action descriptor.")
        if descriptor.upload_or_publication or descriptor.execution_capable:
            raise ValidationError(
                "Candidate Review V1 cannot expose execution or publication actions."
            )
        if descriptor.destructive:
            raise ValidationError("Candidate Review V1 cannot expose destructive actions.")
        if descriptor.availability == "available" and descriptor.authoritative:
            raise ValidationError(
                "Candidate Review V1 exposes no authoritative candidate action."
            )
        registry[descriptor.action_descriptor_id] = descriptor
    return registry


class BobaCandidateReviewV1:
    """Project canonical candidate records for human review.

    Every number, rank, status and decision surfaced here is copied verbatim from
    the module that owns it. This class computes only two things of its own:
    deterministic time-range overlap from exact persisted boundaries, and a
    deterministic presentation priority tier. Neither is a quality judgement.
    """

    def __init__(self, store: BobaMemoryStore, integration: BobaIntegration) -> None:
        self.store = store
        self.integration = integration

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def build_candidate_review_registry(self, project_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        sources = build_fixed_candidate_source_registry()
        actions = build_fixed_candidate_action_registry()
        available_sources = [
            source_id
            for source_id in sources
            if self._source_payload(source_id, project_id)
        ]
        unavailable_sources = [
            source_id for source_id in sources if source_id not in available_sources
        ]
        action_rows = [item.model_dump(mode="json") for item in actions.values()]
        payload = {
            "sources": [
                {key: value for key, value in item.items() if key != "loader"}
                for item in sources.values()
            ],
            "actions": action_rows,
        }
        registry_snapshot_id = _stable_id("candidate_review_registry", "v1", _digest(payload))
        stored = self.store.load_boba_candidate_review_registry(
            project_id, registry_snapshot_id
        )
        registry = (
            BobaCandidateReviewRegistrySnapshotV1.model_validate(stored)
            if isinstance(stored, Mapping)
            else BobaCandidateReviewRegistrySnapshotV1(
                registry_snapshot_id=registry_snapshot_id,
                candidate_source_ids=list(sources),
                available_source_ids=available_sources,
                unavailable_source_ids=unavailable_sources,
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
                    "The registry is fixed source code; browser requests cannot add "
                    "candidate sources, modules, operations, URLs, paths or commands.",
                    "Candidate Review V1 exposes no authoritative candidate "
                    "selection or rejection action.",
                ],
            )
        )
        if not isinstance(stored, Mapping):
            self.store.save_boba_candidate_review_registry(
                project_id, registry_snapshot_id, registry.model_dump(mode="json")
            )
        return {
            "registry_snapshot": registry.model_dump(mode="json"),
            "sources": payload["sources"],
            "actions": action_rows,
        }

    def inspect_candidate_review_registry(self, project_id: str) -> dict[str, Any]:
        return self.build_candidate_review_registry(project_id)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_candidate_review_session(
        self,
        project_id: str,
        *,
        reviewer_context_id: str,
        selected_candidate_id: str | None = None,
        expires_in_seconds: int = 3_600,
    ) -> BobaCandidateReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(reviewer_context_id, "reviewer context id")
        if _SENSITIVE_KEY.search(reviewer_context_id):
            raise ValidationError("Reviewer context cannot contain credentials.")
        if selected_candidate_id is not None:
            _safe_id(selected_candidate_id, "candidate id")
        session_id = f"candidate_review_session_{uuid4().hex}"
        now = datetime.now(UTC)
        session = BobaCandidateReviewSessionV1(
            candidate_review_session_id=session_id,
            project_id=project_id,
            reviewer_context_id=reviewer_context_id,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(
                now + timedelta(seconds=max(60, min(expires_in_seconds, 28_800)))
            ).isoformat(),
            selected_candidate_id=selected_candidate_id,
            session_digest=_digest(
                {
                    "session_id": session_id,
                    "project_id": project_id,
                    "reviewer_context_id": reviewer_context_id,
                    "selected_candidate_id": selected_candidate_id,
                }
            ),
            limitations=[
                "Review sessions hold only UI state.",
                "locally_shortlisted_candidate_ids is a review-session shortlist, "
                "not an Editorial Decision shortlist.",
            ],
        )
        self.store.save_boba_candidate_review_session(
            project_id, session_id, session.model_dump(mode="json")
        )
        return session

    def get_candidate_review_session(
        self, project_id: str, session_id: str
    ) -> BobaCandidateReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(session_id, "candidate review session id")
        raw = self.store.load_boba_candidate_review_session(project_id, session_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA candidate review session is unavailable.")
        session = BobaCandidateReviewSessionV1.model_validate(raw)
        if session.project_id != project_id:
            raise ValidationError("Candidate review session belongs to another project.")
        expires_at = _parse_time(session.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            raise ValidationError("BOBA candidate review session has expired.")
        return session

    def update_candidate_review_session(
        self,
        project_id: str,
        session_id: str,
        updates: Mapping[str, Any],
    ) -> BobaCandidateReviewSessionV1:
        session = self.get_candidate_review_session(project_id, session_id)
        allowed = {
            "selected_candidate_id",
            "comparison_candidate_ids",
            "locally_shortlisted_candidate_ids",
            "active_filter",
            "active_sort",
            "show_rejected",
            "show_historical",
            "show_technical_details",
            "transcript_context_seconds",
            "evidence_drawer_open",
            "timeline_drawer_open",
        }
        unsafe = set(updates) - allowed
        if unsafe:
            raise ValidationError(
                "Candidate review session update contains unsupported fields."
            )
        comparison = updates.get("comparison_candidate_ids")
        if isinstance(comparison, list) and len(comparison) > MAX_COMPARISON_CANDIDATES:
            raise ValidationError(
                f"At most {MAX_COMPARISON_CANDIDATES} candidates may be compared."
            )
        payload = session.model_dump(mode="json")
        payload.update(_as_mapping(_safe_payload(dict(updates))))
        payload["updated_at"] = now_iso()
        payload["session_digest"] = _digest(
            {key: value for key, value in payload.items() if key != "session_digest"}
        )
        updated = BobaCandidateReviewSessionV1.model_validate(payload)
        self.store.save_boba_candidate_review_session(
            project_id, session_id, updated.model_dump(mode="json")
        )
        return updated

    # ------------------------------------------------------------------
    # Source access
    # ------------------------------------------------------------------
    def _source_payload(self, source_id: str, project_id: str) -> dict[str, Any]:
        """Load one canonical owner record through its fixed store loader."""
        registry = build_fixed_candidate_source_registry()
        descriptor = registry.get(source_id)
        if descriptor is None:
            raise ValidationError("Unknown BOBA candidate review source.")
        loader = getattr(self.store, str(descriptor["loader"]), None)
        if loader is None:
            return {}
        try:
            return _as_mapping(loader(project_id))
        except (ValidationError, NotFoundError, OSError):
            return {}

    def _candidate_rows(self, project_id: str) -> list[dict[str, Any]]:
        discovery = self._source_payload("clip_discovery", project_id)
        rows = discovery.get("candidates")
        if not isinstance(rows, list):
            return []
        return [
            _as_mapping(row)
            for row in rows[:MAX_LOADED_CANDIDATES]
            if isinstance(row, Mapping)
        ]

    def _ranked_rows(self, project_id: str) -> dict[str, dict[str, Any]]:
        ranking = self._source_payload("clip_ranking", project_id)
        rows = ranking.get("ranked_candidates")
        result: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                mapped = _as_mapping(row)
                candidate_id = _safe_text(mapped.get("candidate_id"), 128)
                if candidate_id:
                    result[candidate_id] = mapped
        return result

    def _editorial_rows(self, project_id: str) -> dict[str, dict[str, Any]]:
        editorial = self._source_payload("editorial_decision", project_id)
        rows = editorial.get("decisions")
        result: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                mapped = _as_mapping(row)
                candidate_id = _safe_text(mapped.get("candidate_id"), 128)
                if candidate_id:
                    result[candidate_id] = mapped
        return result

    # ------------------------------------------------------------------
    # Candidate references
    # ------------------------------------------------------------------
    def build_candidate_references(self, project_id: str) -> list[BobaCandidateReferenceV1]:
        """Project every discovered candidate with its exact persisted window."""
        _safe_id(project_id, "project id")
        discovery = self._source_payload("clip_discovery", project_id)
        source_id = _safe_text(discovery.get("source_id"), 512)
        discovery_digest = _digest(_safe_payload(discovery)) if discovery else ""
        workflow = _active_workflow_run(
            self._source_payload("workflow_controller", project_id)
        )
        run_id = _safe_text(workflow.get("workflow_run_id"), 180) or None
        stage_id = _safe_text(workflow.get("current_stage_instance_id"), 180) or None
        references: list[BobaCandidateReferenceV1] = []
        for row in self._candidate_rows(project_id):
            candidate_id = _safe_text(row.get("candidate_id"), 128)
            if not candidate_id or not _SAFE_CANDIDATE_ID.fullmatch(candidate_id):
                continue
            if _safe_text(row.get("project_id"), 128) != project_id:
                # Cross-project candidate records are never projected.
                continue
            start = _seconds(row.get("start_seconds"))
            end = _seconds(row.get("end_seconds"))
            if start is None or end is None or end <= start:
                continue
            duration = round(end - start, _TIME_PRECISION)
            evidence = _as_mapping(row.get("evidence"))
            transcript_ids = [
                _safe_text(item, 128)
                for item in evidence.get("topic_segment_ids", [])
                if isinstance(item, str)
            ][:32]
            references.append(
                BobaCandidateReferenceV1(
                    candidate_reference_id=_stable_id(
                        "candidate_reference", project_id, candidate_id
                    ),
                    project_id=project_id,
                    source_id=source_id,
                    workflow_run_id=run_id,
                    stage_instance_id=stage_id,
                    candidate_id=candidate_id,
                    candidate_revision_id=None,
                    source_record_id=_safe_text(
                        discovery.get("schema_version") or "clip_discovery", 180
                    ),
                    source_record_digest=discovery_digest or _digest({"candidate": candidate_id}),
                    candidate_schema_id="boba_candidate_clip_v1",
                    candidate_schema_version=_safe_text(
                        discovery.get("schema_version") or "unknown", 80
                    ),
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=duration,
                    transcript_segment_ids=transcript_ids,
                    speaker_reference_ids=[],
                    current=True,
                    source_media_reference_id=project_id,
                    limitations=[
                        "Speaker references are opaque source-owned identifiers. "
                        "The panel never identifies people from audio or frames.",
                        "Candidate records carry no revision identity, so "
                        "candidate_revision_id is always absent.",
                    ],
                )
            )
        return references[:MAX_LOADED_CANDIDATES]

    def _reference_for(
        self, project_id: str, candidate_id: str
    ) -> BobaCandidateReferenceV1:
        _safe_id(candidate_id, "candidate id")
        for reference in self.build_candidate_references(project_id):
            if reference.candidate_id == candidate_id:
                return reference
        raise ValidationError(
            "BOBA candidate is unknown, unavailable, or belongs to another project."
        )

    # ------------------------------------------------------------------
    # Overlap
    # ------------------------------------------------------------------
    def calculate_candidate_overlaps(
        self,
        project_id: str,
        candidate_id: str | None = None,
    ) -> list[BobaCandidateOverlapV1]:
        """Deterministic pairwise time-range overlap from exact boundaries."""
        references = self.build_candidate_references(project_id)
        records: list[BobaCandidateOverlapV1] = []
        for index, first in enumerate(references):
            for second in references[index + 1 :]:
                if candidate_id is not None and candidate_id not in {
                    first.candidate_id,
                    second.candidate_id,
                }:
                    continue
                record = self._overlap_record(project_id, first, second)
                if record is not None:
                    records.append(record)
        records.sort(
            key=lambda item: (
                -item.intersection_over_union,
                item.candidate_a_id,
                item.candidate_b_id,
            )
        )
        return records[:_MAX_OVERLAP_RECORDS]

    def _overlap_record(
        self,
        project_id: str,
        first: BobaCandidateReferenceV1,
        second: BobaCandidateReferenceV1,
    ) -> BobaCandidateOverlapV1 | None:
        metrics = _overlap_metrics(
            first.start_seconds, first.end_seconds, second.start_seconds, second.end_seconds
        )
        if metrics["overlap_seconds"] <= 0.0:
            return None
        exact = (
            abs(first.start_seconds - second.start_seconds) <= _EXACT_BOUNDARY_EPSILON
            and abs(first.end_seconds - second.end_seconds) <= _EXACT_BOUNDARY_EPSILON
        )
        iou = metrics["intersection_over_union"]
        substantial = exact or iou >= SUBSTANTIAL_OVERLAP_IOU_THRESHOLD
        contained = (
            metrics["candidate_a_coverage"] >= 1.0 - _EXACT_BOUNDARY_EPSILON
            or metrics["candidate_b_coverage"] >= 1.0 - _EXACT_BOUNDARY_EPSILON
        )
        return BobaCandidateOverlapV1(
            overlap_record_id=_stable_id(
                "candidate_overlap", project_id, first.candidate_id, second.candidate_id
            ),
            project_id=project_id,
            candidate_a_id=first.candidate_id,
            candidate_b_id=second.candidate_id,
            candidate_a_start_seconds=first.start_seconds,
            candidate_a_end_seconds=first.end_seconds,
            candidate_b_start_seconds=second.start_seconds,
            candidate_b_end_seconds=second.end_seconds,
            overlap_seconds=metrics["overlap_seconds"],
            union_seconds=metrics["union_seconds"],
            intersection_over_union=iou,
            candidate_a_coverage=min(1.0, metrics["candidate_a_coverage"]),
            candidate_b_coverage=min(1.0, metrics["candidate_b_coverage"]),
            exact_duplicate_window=exact,
            substantial_overlap=substantial,
            partial_overlap=not substantial,
            contained=contained,
            source_time_overlap_only=True,
            same_candidate_identity=first.candidate_id == second.candidate_id,
            limitations=[
                "Overlap is time-range overlap computed from exact persisted "
                "boundaries. It is not a semantic duplication claim.",
                f"substantial_overlap uses a fixed IoU threshold of "
                f"{SUBSTANTIAL_OVERLAP_IOU_THRESHOLD}.",
                "Overlapping candidates are never rejected automatically.",
            ],
        )

    # ------------------------------------------------------------------
    # Score cards
    # ------------------------------------------------------------------
    def build_score_cards(
        self,
        project_id: str,
        candidate_id: str,
        *,
        snapshot_id: str | None = None,
    ) -> list[BobaCandidateScoreCardV1]:
        """Copy every source-owned score verbatim, with its original scale."""
        cards: list[BobaCandidateScoreCardV1] = []
        discovery_row = next(
            (
                row
                for row in self._candidate_rows(project_id)
                if _safe_text(row.get("candidate_id"), 128) == candidate_id
            ),
            {},
        )
        discovery_record = _safe_text(
            self._source_payload("clip_discovery", project_id).get("schema_version")
            or "clip_discovery",
            180,
        )
        for field_name, score_name, low, high, definition in _DISCOVERY_SCORES:
            value = discovery_row.get(field_name)
            if not isinstance(value, int | float) or isinstance(value, bool):
                continue
            cards.append(
                BobaCandidateScoreCardV1(
                    score_card_id=_stable_id(
                        "candidate_score", project_id, candidate_id, score_name
                    ),
                    candidate_snapshot_id=snapshot_id,
                    candidate_id=candidate_id,
                    source_module_id="clip_discovery",
                    source_record_id=discovery_record,
                    score_name=score_name,
                    score_value=float(value),
                    score_scale_min=low,
                    score_scale_max=high,
                    score_definition=definition,
                    score_direction="higher_is_better",
                    weight=None,
                    weighted_by_source=False,
                    source_owned_composite=False,
                    comparable_across_candidates=True,
                    bounded_explanation=(
                        "Owned by Candidate Clip Discovery. The panel does not "
                        "recompute or rescale it."
                    ),
                    limitations=[
                        "This score is not a probability and not a virality "
                        "prediction unless its owner defines it as one.",
                        "Discovery scores use a 0.0-1.0 scale and are not "
                        "comparable with Clip Ranking's 0-100 scores.",
                    ],
                )
            )

        ranked = self._ranked_rows(project_id).get(candidate_id, {})
        if ranked:
            ranking_record = _safe_text(
                self._source_payload("clip_ranking", project_id).get("schema_version")
                or "clip_ranking",
                180,
            )
            rank_value = ranked.get("rank")
            rank = rank_value if isinstance(rank_value, int) and rank_value >= 1 else None
            rank_total = len(self._ranked_rows(project_id)) or None
            tied = self._is_tied(project_id, candidate_id)
            breakdown = _as_mapping(ranked.get("score_breakdown"))
            total = ranked.get("total_score")
            if isinstance(total, int | float) and not isinstance(total, bool):
                cards.append(
                    BobaCandidateScoreCardV1(
                        score_card_id=_stable_id(
                            "candidate_score", project_id, candidate_id, "total_score"
                        ),
                        candidate_snapshot_id=snapshot_id,
                        candidate_id=candidate_id,
                        source_module_id="clip_ranking",
                        source_record_id=ranking_record,
                        score_name="total_score",
                        score_value=float(total),
                        score_scale_min=0.0,
                        score_scale_max=100.0,
                        score_definition=(
                            "Clip Ranking total score for this candidate. Scale "
                            "0-100. This is Clip Ranking's own composite; the "
                            "panel does not create or alter a composite."
                        ),
                        score_direction="higher_is_better",
                        rank=rank,
                        rank_total=rank_total,
                        tied=tied,
                        weight=None,
                        weighted_by_source=True,
                        source_owned_composite=True,
                        bounded_explanation=(
                            "Owned by Clip Ranking. Rank and score are its "
                            "decisions, not the panel's."
                        ),
                        limitations=[
                            "A high ranking score is not editorial approval and "
                            "not a performance guarantee.",
                        ],
                    )
                )
            for key in _RANKING_BREAKDOWN_KEYS:
                if key == "final_score":
                    continue
                value = breakdown.get(key)
                if not isinstance(value, int | float) or isinstance(value, bool):
                    continue
                penalty = key in _PENALTY_KEYS
                cards.append(
                    BobaCandidateScoreCardV1(
                        score_card_id=_stable_id(
                            "candidate_score", project_id, candidate_id, key
                        ),
                        candidate_snapshot_id=snapshot_id,
                        candidate_id=candidate_id,
                        source_module_id="clip_ranking",
                        source_record_id=ranking_record,
                        score_name=key,
                        score_value=float(value),
                        score_scale_min=0.0,
                        score_scale_max=100.0,
                        score_definition=(
                            f"Clip Ranking component '{key}' on a 0-100 scale, as "
                            "persisted in its score breakdown."
                        ),
                        score_direction="lower_is_better" if penalty else "higher_is_better",
                        weight=None,
                        weighted_by_source=False,
                        source_owned_composite=False,
                        comparable_across_candidates=True,
                        bounded_explanation=(
                            "Component score owned by Clip Ranking. The panel "
                            "displays it without reweighting."
                        ),
                        limitations=[
                            "Component weights are not persisted by the owner, so "
                            "no weight is shown.",
                            "The panel never combines components into a new score.",
                        ],
                    )
                )

        editorial = self._editorial_rows(project_id).get(candidate_id, {})
        confidence = editorial.get("confidence")
        if isinstance(confidence, int | float) and not isinstance(confidence, bool):
            cards.append(
                BobaCandidateScoreCardV1(
                    score_card_id=_stable_id(
                        "candidate_score", project_id, candidate_id, "editorial_confidence"
                    ),
                    candidate_snapshot_id=snapshot_id,
                    candidate_id=candidate_id,
                    source_module_id="editorial_decision",
                    source_record_id="boba_editorial_decision_engine_v1",
                    score_name="editorial_confidence",
                    score_value=float(confidence),
                    score_scale_min=0.0,
                    score_scale_max=1.0,
                    score_definition=(
                        "Editorial Decision confidence in its own decision for "
                        "this candidate. Scale 0.0-1.0."
                    ),
                    score_direction="higher_is_better",
                    weight=None,
                    source_owned_composite=False,
                    comparable_across_candidates=False,
                    bounded_explanation="Owned by Editorial Decision.",
                    limitations=[
                        "Editorial confidence is on a 0.0-1.0 scale and is not "
                        "comparable with Clip Ranking's 0-100 scores.",
                    ],
                )
            )
        return cards[:_MAX_SCORE_CARDS]

    def _is_tied(self, project_id: str, candidate_id: str) -> bool:
        ranked = self._ranked_rows(project_id)
        target = ranked.get(candidate_id, {})
        score = target.get("total_score")
        if not isinstance(score, int | float) or isinstance(score, bool):
            return False
        matches = [
            other
            for other, row in ranked.items()
            if other != candidate_id
            and isinstance(row.get("total_score"), int | float)
            and abs(float(row["total_score"]) - float(score)) <= _EXACT_BOUNDARY_EPSILON
        ]
        return bool(matches)

    # ------------------------------------------------------------------
    # Source cards
    # ------------------------------------------------------------------
    def build_source_cards(
        self,
        project_id: str,
        candidate_id: str,
        *,
        snapshot_id: str | None = None,
    ) -> list[BobaCandidateSourceCardV1]:
        """One card per owning module, preserving its original status verbatim."""
        registry = build_fixed_candidate_source_registry()
        cards: list[BobaCandidateSourceCardV1] = []
        for source_id, descriptor in registry.items():
            payload = self._source_payload(source_id, project_id)
            title = str(descriptor["title"])
            domain = str(descriptor["authority_domain"])
            advisory = bool(descriptor["advisory_only"])
            if not payload:
                cards.append(
                    BobaCandidateSourceCardV1(
                        source_card_id=_stable_id(
                            "candidate_source_card", project_id, candidate_id, source_id
                        ),
                        candidate_snapshot_id=snapshot_id,
                        source_module_id=source_id,
                        authority_domain=domain,
                        source_record_id=_stable_id("unavailable", project_id, source_id),
                        source_record_digest=_digest(
                            {"module": source_id, "state": "unavailable"}
                        ),
                        title=title,
                        original_status="unavailable",
                        bounded_summary=(
                            "No canonical record is available from this module for "
                            "this project."
                        ),
                        easy_explanation=f"{title} has not supplied a record.",
                        current=False,
                        advisory_only=advisory,
                        limitations=[
                            "An unavailable source record is never treated as a pass.",
                        ],
                    )
                )
                continue
            safe = _as_mapping(_safe_payload(payload))
            status, decision, rank, summary = self._candidate_status_from(
                source_id, safe, candidate_id
            )
            cards.append(
                BobaCandidateSourceCardV1(
                    source_card_id=_stable_id(
                        "candidate_source_card", project_id, candidate_id, source_id
                    ),
                    candidate_snapshot_id=snapshot_id,
                    source_module_id=source_id,
                    authority_domain=domain,
                    source_record_id=_safe_text(
                        safe.get("schema_version") or source_id, 180
                    ),
                    source_record_digest=_digest(safe),
                    source_schema_id=_safe_text(safe.get("schema_version") or "unknown", 180),
                    source_schema_version=_safe_text(safe.get("schema_version") or "1", 80),
                    title=title,
                    original_status=status,
                    original_decision=decision,
                    original_rank=rank,
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
                    limitations=[
                        _safe_text(item, 300)
                        for item in safe.get("limitations", [])
                        if isinstance(item, str)
                    ][:12]
                    + (
                        ["This module's output is advisory, not a decision."]
                        if advisory
                        else []
                    ),
                )
            )
        return cards[:_MAX_SOURCE_CARDS]

    def _candidate_status_from(
        self,
        source_id: str,
        payload: Mapping[str, Any],
        candidate_id: str,
    ) -> tuple[str, str | None, int | None, str]:
        """Extract this module's own verbatim status for one candidate."""
        if source_id == "clip_discovery":
            row = next(
                (
                    _as_mapping(item)
                    for item in payload.get("candidates", [])
                    if isinstance(item, Mapping)
                    and _safe_text(item.get("candidate_id"), 128) == candidate_id
                ),
                {},
            )
            if not row:
                return ("not_discovered", None, None, "This candidate is not in the record.")
            return (
                "discovered",
                _safe_text(row.get("candidate_type"), 80) or None,
                None,
                _safe_text(row.get("discovery_reason"), 600),
            )
        if source_id == "clip_ranking":
            row = self._ranked_rows_from(payload).get(candidate_id, {})
            if not row:
                rejected = [
                    _as_mapping(item)
                    for item in payload.get("rejected_candidates", [])
                    if isinstance(item, Mapping)
                    and _safe_text(item.get("candidate_id"), 128) == candidate_id
                ]
                if rejected:
                    return (
                        "rejected",
                        "rejected",
                        None,
                        _safe_text(rejected[0].get("reason"), 400),
                    )
                return ("not_ranked", None, None, "Clip Ranking did not rank this candidate.")
            rank_value = row.get("rank")
            return (
                _safe_text(row.get("tier"), 80) or "ranked",
                _safe_text(row.get("production_priority"), 80) or None,
                rank_value if isinstance(rank_value, int) and rank_value >= 1 else None,
                "; ".join(
                    _safe_text(item, 200)
                    for item in row.get("ranking_reasons", [])
                    if isinstance(item, str)
                )[:900],
            )
        if source_id == "editorial_decision":
            row = next(
                (
                    _as_mapping(item)
                    for item in payload.get("decisions", [])
                    if isinstance(item, Mapping)
                    and _safe_text(item.get("candidate_id"), 128) == candidate_id
                ),
                {},
            )
            selected_ids = [
                _safe_text(item, 128)
                for item in payload.get("selected_clip_ids", [])
                if isinstance(item, str)
            ]
            rejected_ids = [
                _safe_text(item, 128)
                for item in payload.get("rejected_clip_ids", [])
                if isinstance(item, str)
            ]
            if not row:
                if candidate_id in rejected_ids:
                    return ("rejected", "rejected", None, "Editorial Decision rejected this.")
                return (
                    "no_editorial_decision",
                    None,
                    None,
                    "Editorial Decision has not decided on this candidate.",
                )
            selected = bool(row.get("selected")) or candidate_id in selected_ids
            rank_value = row.get("rank")
            return (
                "selected" if selected else "not_selected",
                _safe_text(row.get("render_readiness"), 80) or None,
                rank_value if isinstance(rank_value, int) and rank_value >= 1 else None,
                "; ".join(
                    _safe_text(item, 200)
                    for item in row.get("decision_reasons", [])
                    if isinstance(item, str)
                )[:900],
            )
        for key, label in (
            ("candidate_explanations", "explanation"),
            ("analyses", "analysis"),
            ("recommendations", "recommendation"),
            ("selected_briefs", "brief"),
        ):
            rows = payload.get(key)
            if not isinstance(rows, list):
                continue
            match = next(
                (
                    _as_mapping(item)
                    for item in rows
                    if isinstance(item, Mapping)
                    and _safe_text(item.get("candidate_id"), 128) == candidate_id
                ),
                {},
            )
            if match:
                return (
                    f"{label}_available",
                    None,
                    None,
                    _safe_text(
                        match.get("summary")
                        or match.get("bounded_summary")
                        or match.get("reason")
                        or f"A {label} exists for this candidate.",
                        900,
                    ),
                )
        status = _safe_text(payload.get("status") or "available", 160)
        return (
            status,
            None,
            None,
            _safe_text(payload.get("summary") or "Canonical record available.", 900),
        )

    @staticmethod
    def _ranked_rows_from(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
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

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------
    def build_candidate_queue(
        self,
        project_id: str,
        *,
        review_filter: str = "all_current",
        sort: str = "review_priority",
        offset: int = 0,
        limit: int = MAX_QUEUE_PAGE_SIZE,
    ) -> dict[str, Any]:
        references = self.build_candidate_references(project_id)
        overlaps = self.calculate_candidate_overlaps(project_id)
        items = [
            self._queue_item(project_id, reference, index, overlaps)
            for index, reference in enumerate(references)
        ]
        items = self._filter_queue(items, review_filter)
        items = self._sort_queue(items, sort)
        safe_offset = max(0, offset)
        safe_limit = max(1, min(limit, MAX_QUEUE_PAGE_SIZE))
        window = items[safe_offset : safe_offset + safe_limit]
        return {
            "schema_version": "boba_candidate_review_queue_v1",
            "project_id": project_id,
            "total": len(items),
            "offset": safe_offset,
            "limit": safe_limit,
            "active_filter": review_filter,
            "active_sort": sort,
            "priority_tiers": [
                {"priority": priority, "reason": reason}
                for priority, reason in CANDIDATE_QUEUE_PRIORITY_TIERS
            ],
            "items": [item.model_dump(mode="json") for item in window],
        }

    def inspect_candidate_queue(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.build_candidate_queue(project_id, **kwargs)

    @staticmethod
    def _filter_queue(
        items: list[BobaCandidateQueueItemV1], review_filter: str
    ) -> list[BobaCandidateQueueItemV1]:
        if review_filter in {"all_current", "", "all"}:
            return [item for item in items if not item.historical]
        if review_filter == "human_review_required":
            return [item for item in items if item.human_action_required]
        if review_filter == "source_shortlisted":
            return [item for item in items if item.editorial_status == "selected"]
        if review_filter == "selected":
            return [item for item in items if item.selected]
        if review_filter == "rejected":
            return [item for item in items if item.rejected]
        if review_filter == "blocked":
            return [item for item in items if item.blocker_count > 0]
        if review_filter == "stale":
            return [item for item in items if item.stale]
        if review_filter == "overlapping":
            return [item for item in items if item.overlap_group_ids]
        if review_filter == "missing_evidence":
            return [item for item in items if item.missing_evidence_count > 0]
        if review_filter == "historical":
            return [item for item in items if item.historical or item.superseded]
        raise ValidationError("Unsupported candidate review filter.")

    @staticmethod
    def _sort_queue(
        items: list[BobaCandidateQueueItemV1], sort: str
    ) -> list[BobaCandidateQueueItemV1]:
        rows = list(items)
        if sort in {"review_priority", "", "priority"}:
            rows.sort(key=lambda item: (item.priority_tier, item.deterministic_sort_key))
        elif sort == "original_rank":
            # Candidates without a source-owned rank sort last, never invented.
            rows.sort(
                key=lambda item: (
                    item.original_rank is None,
                    item.original_rank or 0,
                    item.candidate_id,
                )
            )
        elif sort == "source_start_time" or sort == "duration" or sort == "creation_order":
            rows.sort(key=lambda item: (item.deterministic_sort_key, item.candidate_id))
        elif sort == "candidate_id":
            rows.sort(key=lambda item: item.candidate_id)
        else:
            raise ValidationError("Unsupported candidate review sort.")
        return rows

    def _queue_item(
        self,
        project_id: str,
        reference: BobaCandidateReferenceV1,
        creation_index: int,
        overlaps: list[BobaCandidateOverlapV1],
    ) -> BobaCandidateQueueItemV1:
        candidate_id = reference.candidate_id
        discovery_row = next(
            (
                row
                for row in self._candidate_rows(project_id)
                if _safe_text(row.get("candidate_id"), 128) == candidate_id
            ),
            {},
        )
        ranked = self._ranked_rows(project_id).get(candidate_id, {})
        editorial = self._editorial_rows(project_id).get(candidate_id, {})
        editorial_payload = self._source_payload("editorial_decision", project_id)
        ranking_payload = self._source_payload("clip_ranking", project_id)

        selected_ids = {
            _safe_text(item, 128)
            for item in editorial_payload.get("selected_clip_ids", [])
            if isinstance(item, str)
        }
        editorial_rejected = {
            _safe_text(item, 128)
            for item in editorial_payload.get("rejected_clip_ids", [])
            if isinstance(item, str)
        }
        ranking_rejected = {
            _safe_text(item, 128)
            for item in ranking_payload.get("rejected_clip_ids", [])
            if isinstance(item, str)
        }
        shortlisted = {
            _safe_text(item, 128)
            for item in ranking_payload.get("recommended_clip_ids", [])
            if isinstance(item, str)
        }

        selected = bool(editorial.get("selected")) or candidate_id in selected_ids
        rejected = candidate_id in editorial_rejected or candidate_id in ranking_rejected
        rank_value = ranked.get("rank")
        rank = rank_value if isinstance(rank_value, int) and rank_value >= 1 else None
        total_score = ranked.get("total_score")
        primary_score = (
            float(total_score)
            if isinstance(total_score, int | float) and not isinstance(total_score, bool)
            else None
        )
        primary_name = "total_score" if primary_score is not None else ""
        primary_owner = "clip_ranking" if primary_score is not None else ""
        if primary_score is None:
            confidence = discovery_row.get("confidence")
            if isinstance(confidence, int | float) and not isinstance(confidence, bool):
                primary_score = float(confidence)
                primary_name = "confidence"
                primary_owner = "clip_discovery"

        editorial_status = (
            "selected"
            if selected
            else "rejected"
            if candidate_id in editorial_rejected
            else "not_selected"
            if editorial
            else "unavailable"
        )
        missing_evidence = sum(
            1
            for present in (bool(discovery_row), bool(ranked), bool(editorial))
            if not present
        )
        conflict_count = 1 if (selected and rejected) else 0
        rights_blocked = self._rights_blocked(project_id)
        safety_blocked = self._safety_blocked(project_id)
        blocker_count = (1 if rights_blocked else 0) + (1 if safety_blocked else 0)
        overlap_ids = [
            record.overlap_record_id
            for record in overlaps
            if candidate_id in {record.candidate_a_id, record.candidate_b_id}
        ]
        duplicate_group = next(
            (
                record.overlap_record_id
                for record in overlaps
                if record.exact_duplicate_window
                and candidate_id in {record.candidate_a_id, record.candidate_b_id}
            ),
            None,
        )
        substantial = any(
            record.substantial_overlap
            for record in overlaps
            if candidate_id in {record.candidate_a_id, record.candidate_b_id}
        )
        human_required = not editorial and bool(discovery_row)

        priority, reason, review_status = self._priority(
            selected=selected,
            rejected=rejected,
            blocked=blocker_count > 0,
            conflict=conflict_count > 0,
            missing_evidence=missing_evidence > 0,
            stale=reference.stale,
            shortlisted=selected or candidate_id in shortlisted,
            rank=rank,
            substantial_overlap=substantial,
            superseded=reference.superseded,
            historical=reference.historical,
            human_required=human_required,
        )
        digests: dict[str, str] = {}
        modules: list[str] = []
        for source_id in ("clip_discovery", "clip_ranking", "editorial_decision"):
            payload = self._source_payload(source_id, project_id)
            if payload:
                modules.append(source_id)
                digests[source_id] = _digest(_safe_payload(payload))
        return BobaCandidateQueueItemV1(
            candidate_queue_item_id=_stable_id("candidate_queue", project_id, candidate_id),
            candidate_reference_id=reference.candidate_reference_id,
            project_id=project_id,
            workflow_run_id=reference.workflow_run_id,
            stage_instance_id=reference.stage_instance_id,
            candidate_id=candidate_id,
            title=_safe_text(discovery_row.get("suggested_title"), 240) or candidate_id,
            bounded_summary=_safe_text(discovery_row.get("discovery_reason"), 900),
            original_discovery_status=(
                _safe_text(discovery_row.get("candidate_type"), 160) or "unknown"
            ),
            original_rank=rank,
            original_rank_total=len(self._ranked_rows(project_id)) or None,
            rank_owner_module_id="clip_ranking" if rank is not None else "",
            primary_score=primary_score,
            primary_score_name=primary_name,
            primary_score_owner_module_id=primary_owner,
            editorial_status=editorial_status,
            review_status=review_status,
            current=reference.current,
            stale=reference.stale,
            historical=reference.historical,
            superseded=reference.superseded,
            rejected=rejected,
            selected=selected,
            human_action_required=human_required,
            blocker_count=blocker_count,
            warning_count=len(
                [item for item in discovery_row.get("warnings", []) if isinstance(item, str)]
            ),
            missing_evidence_count=missing_evidence,
            conflict_count=conflict_count,
            duplicate_group_id=duplicate_group,
            overlap_group_ids=overlap_ids[:24],
            available_action_descriptor_ids=self._available_actions(reference),
            source_module_ids=modules,
            source_record_ids=list(digests),
            source_record_digests=digests,
            priority_tier=priority,
            priority_reason=reason,
            deterministic_sort_key=(
                f"{priority:03d}:"
                f"{(rank if rank is not None else 9_999):04d}:"
                f"{reference.start_seconds:012.3f}:"
                f"{creation_index:04d}:{candidate_id}"
            ),
            warnings=[
                _safe_text(item, 300)
                for item in discovery_row.get("warnings", [])
                if isinstance(item, str)
            ][:12],
            limitations=[
                "Rank and scores are owned by their source modules.",
                "Overlap is time-range overlap only.",
            ],
        )

    @staticmethod
    def _priority(
        *,
        selected: bool,
        rejected: bool,
        blocked: bool,
        conflict: bool,
        missing_evidence: bool,
        stale: bool,
        shortlisted: bool,
        rank: int | None,
        substantial_overlap: bool,
        superseded: bool,
        historical: bool,
        human_required: bool,
    ) -> tuple[int, str, CandidateReviewStatus]:
        """Deterministic presentation tier. Never a quality score."""
        if selected and blocked:
            return (10, CANDIDATE_QUEUE_PRIORITY_TIERS[0][1], "blocked")
        if historical:
            return (120, CANDIDATE_QUEUE_PRIORITY_TIERS[11][1], "historical")
        if superseded:
            return (110, CANDIDATE_QUEUE_PRIORITY_TIERS[10][1], "historical")
        if rejected:
            return (100, CANDIDATE_QUEUE_PRIORITY_TIERS[9][1], "source_rejected")
        if human_required:
            return (20, CANDIDATE_QUEUE_PRIORITY_TIERS[1][1], "awaiting_human_review")
        if conflict:
            return (30, CANDIDATE_QUEUE_PRIORITY_TIERS[2][1], "blocked")
        if missing_evidence:
            return (40, CANDIDATE_QUEUE_PRIORITY_TIERS[3][1], "awaiting_human_review")
        if stale:
            return (50, CANDIDATE_QUEUE_PRIORITY_TIERS[4][1], "informational")
        if shortlisted:
            return (
                60,
                CANDIDATE_QUEUE_PRIORITY_TIERS[5][1],
                "source_selected" if selected else "source_shortlisted",
            )
        if rank is not None and rank <= 3:
            return (70, CANDIDATE_QUEUE_PRIORITY_TIERS[6][1], "awaiting_human_review")
        if substantial_overlap:
            return (80, CANDIDATE_QUEUE_PRIORITY_TIERS[7][1], "informational")
        return (90, CANDIDATE_QUEUE_PRIORITY_TIERS[8][1], "informational")

    def _rights_blocked(self, project_id: str) -> bool:
        payload = self._source_payload("rights_permission_gate", project_id)
        status = _safe_text(payload.get("status") or payload.get("decision"), 160).lower()
        return bool(payload) and any(
            token in status for token in ("block", "deny", "reject", "fail")
        )

    def _safety_blocked(self, project_id: str) -> bool:
        payload = self._source_payload("safety_gate", project_id)
        status = _safe_text(payload.get("status") or payload.get("decision"), 160).lower()
        return bool(payload) and any(
            token in status for token in ("block", "deny", "reject", "fail")
        )

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    def _workflow_revision(self, project_id: str) -> int:
        run = _active_workflow_run(self._source_payload("workflow_controller", project_id))
        revision = run.get("revision")
        return revision if isinstance(revision, int) and revision >= 0 else 0

    def _project_snapshot_digest(self, project_id: str) -> str:
        digests = {
            source_id: _digest(_safe_payload(self._source_payload(source_id, project_id)))
            for source_id in build_fixed_candidate_source_registry()
        }
        return _digest(digests)

    def _candidate_digest(self, project_id: str, candidate_id: str) -> str:
        row = next(
            (
                row
                for row in self._candidate_rows(project_id)
                if _safe_text(row.get("candidate_id"), 128) == candidate_id
            ),
            {},
        )
        ranked = self._ranked_rows(project_id).get(candidate_id, {})
        editorial = self._editorial_rows(project_id).get(candidate_id, {})
        return _digest(
            {
                "candidate": _safe_payload(row),
                "ranked": _safe_payload(ranked),
                "editorial": _safe_payload(editorial),
            }
        )

    def build_candidate_snapshot(
        self,
        project_id: str,
        session_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        session = self.get_candidate_review_session(project_id, session_id)
        reference = self._reference_for(project_id, candidate_id)
        snapshot_id = f"candidate_snapshot_{uuid4().hex}"
        source_cards = self.build_source_cards(project_id, candidate_id, snapshot_id=snapshot_id)
        score_cards = self.build_score_cards(project_id, candidate_id, snapshot_id=snapshot_id)
        overlaps = self.calculate_candidate_overlaps(project_id, candidate_id)
        queue_item = self._queue_item(project_id, reference, 0, overlaps)
        digests = {card.source_module_id: card.source_record_digest for card in source_cards}
        project_digest = self._project_snapshot_digest(project_id)
        revision = self._workflow_revision(project_id)
        candidate_digest = self._candidate_digest(project_id, candidate_id)
        confirmation = _digest(
            {
                "project": project_digest,
                "revision": revision,
                "candidate": candidate_digest,
                "candidate_id": candidate_id,
            }
        )
        snapshot_payload = {
            "project": project_digest,
            "revision": revision,
            "candidate": candidate_digest,
            "sources": digests,
            "session": session.candidate_review_session_id,
        }

        def status_of(module_id: str) -> str:
            return next(
                (
                    card.original_status
                    for card in source_cards
                    if card.source_module_id == module_id
                ),
                "unavailable",
            )

        snapshot = BobaCandidateSnapshotV1(
            candidate_snapshot_id=snapshot_id,
            candidate_review_session_id=session.candidate_review_session_id,
            candidate_reference_id=reference.candidate_reference_id,
            project_id=project_id,
            workflow_run_id=reference.workflow_run_id,
            stage_instance_id=reference.stage_instance_id,
            candidate_id=candidate_id,
            project_snapshot_digest=project_digest,
            workflow_revision=revision,
            candidate_digest=candidate_digest,
            source_record_references=[
                {"module_id": card.source_module_id, "record_id": card.source_record_id}
                for card in source_cards
            ],
            source_record_digests=digests,
            source_card_ids=[card.source_card_id for card in source_cards],
            score_card_ids=[card.score_card_id for card in score_cards],
            overlap_record_ids=[record.overlap_record_id for record in overlaps],
            discovery_status=status_of("clip_discovery"),
            rank_status=status_of("clip_ranking"),
            editorial_status=status_of("editorial_decision"),
            rights_status=status_of("rights_permission_gate"),
            workflow_status=status_of("workflow_controller"),
            artifact_status=status_of("artifact_inspector"),
            validation_status=status_of("validator_runner"),
            human_review_status=(
                "awaiting_human_review" if queue_item.human_action_required else "no_pending_review"
            ),
            current=reference.current,
            stale=reference.stale,
            historical=reference.historical,
            selected=queue_item.selected,
            rejected=queue_item.rejected,
            missing_evidence_count=queue_item.missing_evidence_count,
            conflict_count=queue_item.conflict_count,
            warning_count=sum(len(card.warnings) for card in source_cards),
            limitation_count=sum(len(card.limitations) for card in source_cards),
            available_action_descriptor_ids=self._available_actions(reference),
            confirmation_context_digest=confirmation,
            snapshot_digest=_digest(snapshot_payload),
            limitations=[
                "Snapshot status is display-only and links to canonical owner records.",
                "Candidate Review V1 exposes no authoritative selection action.",
            ],
        )
        self.store.save_boba_candidate_review_snapshot(
            project_id, snapshot_id, snapshot.model_dump(mode="json")
        )
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "candidate_reference": reference.model_dump(mode="json"),
            "queue_item": queue_item.model_dump(mode="json"),
            "source_cards": [card.model_dump(mode="json") for card in source_cards],
            "score_cards": [card.model_dump(mode="json") for card in score_cards],
            "overlap_records": [record.model_dump(mode="json") for record in overlaps],
            "action_confirmations": self._action_confirmations(snapshot),
        }

    def refresh_candidate_snapshot(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = self._snapshot(project_id, snapshot_id)
        return self.build_candidate_snapshot(
            project_id, snapshot.candidate_review_session_id, snapshot.candidate_id
        )

    def _snapshot(self, project_id: str, snapshot_id: str) -> BobaCandidateSnapshotV1:
        _safe_id(project_id, "project id")
        _safe_id(snapshot_id, "candidate snapshot id")
        raw = self.store.load_boba_candidate_review_snapshot(project_id, snapshot_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA candidate review snapshot is unavailable.")
        snapshot = BobaCandidateSnapshotV1.model_validate(raw)
        if snapshot.project_id != project_id:
            raise ValidationError("Candidate snapshot belongs to another project.")
        return snapshot

    def _action_confirmations(self, snapshot: BobaCandidateSnapshotV1) -> dict[str, str]:
        """Per-action confirmation token bound to this exact snapshot."""
        registry = build_fixed_candidate_action_registry()
        tokens: dict[str, str] = {}
        for action_id in snapshot.available_action_descriptor_ids:
            descriptor = registry.get(action_id)
            if descriptor is None:
                continue
            tokens[action_id] = _digest(
                {
                    "snapshot": snapshot.snapshot_digest,
                    "action": descriptor.action_descriptor_id,
                    "candidate": snapshot.candidate_digest,
                }
            )
        return tokens

    def _available_actions(self, reference: BobaCandidateReferenceV1) -> list[str]:
        available: list[str] = []
        state = (
            "historical"
            if reference.historical
            else "stale"
            if reference.stale
            else "current"
        )
        for descriptor in build_fixed_candidate_action_registry().values():
            if not descriptor.allowed_in_v1 or descriptor.availability != "available":
                continue
            if descriptor.supported_candidate_states and state not in (
                descriptor.supported_candidate_states
            ):
                continue
            if descriptor.requires_current_snapshot and not reference.current:
                continue
            available.append(descriptor.action_descriptor_id)
        return available

    def inspect_candidate(self, project_id: str, candidate_id: str) -> dict[str, Any]:
        reference = self._reference_for(project_id, candidate_id)
        overlaps = self.calculate_candidate_overlaps(project_id, candidate_id)
        return {
            "schema_version": "boba_candidate_review_candidate_v1",
            "project_id": project_id,
            "candidate_reference": reference.model_dump(mode="json"),
            "queue_item": self._queue_item(project_id, reference, 0, overlaps).model_dump(
                mode="json"
            ),
            "source_cards": [
                card.model_dump(mode="json")
                for card in self.build_source_cards(project_id, candidate_id)
            ],
            "score_cards": [
                card.model_dump(mode="json")
                for card in self.build_score_cards(project_id, candidate_id)
            ],
            "overlap_records": [record.model_dump(mode="json") for record in overlaps],
            "transcript": self.inspect_candidate_transcript(project_id, candidate_id),
        }

    def inspect_candidate_overlaps(
        self, project_id: str, candidate_id: str
    ) -> dict[str, Any]:
        self._reference_for(project_id, candidate_id)
        records = self.calculate_candidate_overlaps(project_id, candidate_id)
        return {
            "schema_version": "boba_candidate_review_overlaps_v1",
            "project_id": project_id,
            "candidate_id": candidate_id,
            "substantial_overlap_iou_threshold": SUBSTANTIAL_OVERLAP_IOU_THRESHOLD,
            "overlap_records": [record.model_dump(mode="json") for record in records],
            "limitations": [
                "Overlap is time-range overlap computed from exact persisted "
                "boundaries. It is not a semantic duplication claim.",
            ],
        }

    def inspect_candidate_transcript(
        self,
        project_id: str,
        candidate_id: str,
        *,
        context_seconds: int = 15,
    ) -> dict[str, Any]:
        """Return the source-owned transcript snippets bound to this candidate."""
        reference = self._reference_for(project_id, candidate_id)
        bounded_context = max(0, min(context_seconds, MAX_TRANSCRIPT_CONTEXT_SECONDS))
        row = next(
            (
                row
                for row in self._candidate_rows(project_id)
                if _safe_text(row.get("candidate_id"), 128) == candidate_id
            ),
            {},
        )
        evidence = _as_mapping(row.get("evidence"))
        snippets = [
            _safe_text(item, 1_200)
            for item in evidence.get("transcript_snippets", [])
            if isinstance(item, str)
        ][:5]
        return {
            "schema_version": "boba_candidate_review_transcript_v1",
            "project_id": project_id,
            "candidate_id": candidate_id,
            "candidate_start_seconds": reference.start_seconds,
            "candidate_end_seconds": reference.end_seconds,
            "context_seconds": bounded_context,
            "context_start_seconds": max(0.0, reference.start_seconds - bounded_context),
            "context_end_seconds": reference.end_seconds + bounded_context,
            "candidate_transcript_snippets": snippets,
            "transcript_segment_ids": reference.transcript_segment_ids,
            "source_module_id": "clip_discovery",
            "limitations": [
                "Transcript text is reproduced verbatim from the owning record.",
                "Context bounds are display hints only; they never change the "
                "candidate boundaries.",
                "Only transcript snippets persisted on the candidate record are "
                "available; the panel does not re-transcribe media.",
            ],
        }

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    def build_candidate_comparison(
        self,
        project_id: str,
        candidate_ids: list[str],
        *,
        comparison_type: str = "side_by_side",
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        unique: list[str] = []
        for candidate_id in candidate_ids:
            _safe_id(candidate_id, "candidate id")
            if candidate_id not in unique:
                unique.append(candidate_id)
        if len(unique) < 2:
            raise ValidationError("At least two distinct candidates are required.")
        if len(unique) > MAX_COMPARISON_CANDIDATES:
            raise ValidationError(
                f"At most {MAX_COMPARISON_CANDIDATES} candidates may be compared."
            )
        if comparison_type not in {
            "side_by_side",
            "rank",
            "score_breakdown",
            "source_window",
            "overlap",
            "evidence_coverage",
            "creative_plan",
            "historical_revision",
            "unknown",
        }:
            raise ValidationError("Unsupported candidate comparison type.")
        references = [self._reference_for(project_id, item) for item in unique]
        source_ids = {reference.source_id for reference in references}
        run_ids = {reference.workflow_run_id for reference in references}
        overlaps = [
            record
            for record in self.calculate_candidate_overlaps(project_id)
            if record.candidate_a_id in unique and record.candidate_b_id in unique
        ]
        ranked = self._ranked_rows(project_id)
        editorial = self._editorial_rows(project_id)
        rows = {
            row_id: next(
                (
                    row
                    for row in self._candidate_rows(project_id)
                    if _safe_text(row.get("candidate_id"), 128) == row_id
                ),
                {},
            )
            for row_id in unique
        }
        comparison = BobaCandidateComparisonV1(
            comparison_id=_stable_id("candidate_comparison", project_id, *unique),
            project_id=project_id,
            candidate_ids=unique,
            comparison_type=comparison_type,
            common_source_id=next(iter(source_ids)) if len(source_ids) == 1 else "",
            same_workflow_run=len(run_ids) == 1,
            rank_comparison=[
                {
                    "candidate_id": item,
                    "original_rank": ranked.get(item, {}).get("rank"),
                    "rank_owner_module_id": "clip_ranking" if ranked.get(item) else "",
                    "tier": ranked.get(item, {}).get("tier"),
                    "tied": self._is_tied(project_id, item),
                }
                for item in unique
            ],
            score_comparison=[
                card.model_dump(mode="json")
                for item in unique
                for card in self.build_score_cards(project_id, item)
            ][:64],
            duration_comparison=[
                {
                    "candidate_id": reference.candidate_id,
                    "start_seconds": reference.start_seconds,
                    "end_seconds": reference.end_seconds,
                    "duration_seconds": reference.duration_seconds,
                }
                for reference in references
            ],
            overlap_record_ids=[record.overlap_record_id for record in overlaps],
            discovery_reason_comparison=[
                {
                    "candidate_id": item,
                    "candidate_type": _safe_text(rows[item].get("candidate_type"), 80),
                    "discovery_reason": _safe_text(rows[item].get("discovery_reason"), 600),
                    "source_module_id": "clip_discovery",
                }
                for item in unique
            ],
            editorial_status_comparison=[
                {
                    "candidate_id": item,
                    "selected": bool(editorial.get(item, {}).get("selected")),
                    "render_readiness": editorial.get(item, {}).get("render_readiness"),
                    "source_module_id": "editorial_decision",
                    "available": bool(editorial.get(item)),
                }
                for item in unique
            ],
            evidence_coverage_comparison=[
                {
                    "candidate_id": item,
                    "discovery_present": bool(rows[item]),
                    "ranking_present": bool(ranked.get(item)),
                    "editorial_present": bool(editorial.get(item)),
                }
                for item in unique
            ],
            warnings_comparison=[
                {
                    "candidate_id": item,
                    "warnings": [
                        _safe_text(entry, 300)
                        for entry in rows[item].get("warnings", [])
                        if isinstance(entry, str)
                    ][:8],
                }
                for item in unique
            ],
            limitations_comparison=[
                {
                    "candidate_id": item,
                    "limitations": [
                        "Scores retain their original owner, scale and definition.",
                    ],
                }
                for item in unique
            ],
            bounded_summary=(
                f"Side-by-side projection of {len(unique)} candidates from their "
                "canonical owner records. No winner is chosen."
            ),
            limitations=[
                "The panel does not choose a winner and does not rank candidates.",
                "Scores from different modules use different scales and are not "
                "directly comparable.",
                "Overlap shown here is time-range overlap only.",
            ],
        )
        return {
            "comparison": comparison.model_dump(mode="json"),
            "overlap_records": [record.model_dump(mode="json") for record in overlaps],
        }

    # ------------------------------------------------------------------
    # Canonical action routing
    # ------------------------------------------------------------------
    def _action_descriptor(self, action_descriptor_id: str) -> BobaCandidateActionDescriptorV1:
        _safe_id(action_descriptor_id, "action descriptor id")
        descriptor = build_fixed_candidate_action_registry().get(action_descriptor_id)
        if descriptor is None:
            raise ValidationError("Unknown fixed BOBA candidate review action descriptor.")
        return descriptor

    def create_candidate_action_request(
        self,
        project_id: str,
        *,
        candidate_review_session_id: str,
        candidate_snapshot_id: str,
        action_descriptor_id: str,
        decision_value: str | None,
        reason: str,
        confirmation_context_digest: str,
        idempotency_key: str,
        confirmed: bool,
    ) -> BobaCandidateActionRequestV1:
        session = self.get_candidate_review_session(project_id, candidate_review_session_id)
        snapshot = self._snapshot(project_id, candidate_snapshot_id)
        if snapshot.candidate_review_session_id != session.candidate_review_session_id:
            raise ValidationError("Candidate snapshot belongs to another review session.")
        descriptor = self._action_descriptor(action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            raise ValidationError(
                "This BOBA candidate review action is unavailable in V1."
            )
        if descriptor.action_descriptor_id not in snapshot.available_action_descriptor_ids:
            raise ValidationError("The action is unavailable for this exact candidate.")
        if descriptor.allowed_decision_values and decision_value not in (
            descriptor.allowed_decision_values
        ):
            raise ValidationError("Unsupported decision value for this fixed action.")
        if descriptor.requires_reason and not reason.strip():
            raise ValidationError("This candidate review action requires a reason.")
        if len(reason) > descriptor.maximum_reason_length:
            raise ValidationError("Candidate review reason exceeds the allowed length.")
        if _SENSITIVE_KEY.search(reason):
            raise ValidationError("Candidate review reasons cannot contain credentials.")
        if not confirmed:
            raise ValidationError("Explicit candidate review confirmation is required.")
        if descriptor.requires_reviewer_context and not session.reviewer_context_id:
            raise ValidationError("An exact reviewer context is required.")
        expected = self._action_confirmations(snapshot).get(descriptor.action_descriptor_id)
        if not expected or confirmation_context_digest != expected:
            raise ValidationError(
                "Candidate review confirmation does not match the current candidate."
            )
        _safe_id(idempotency_key, "idempotency key")
        request = BobaCandidateActionRequestV1(
            candidate_action_request_id=f"candidate_action_{uuid4().hex}",
            candidate_review_session_id=session.candidate_review_session_id,
            candidate_snapshot_id=snapshot.candidate_snapshot_id,
            project_id=project_id,
            workflow_run_id=snapshot.workflow_run_id,
            stage_instance_id=snapshot.stage_instance_id,
            candidate_id=snapshot.candidate_id,
            candidate_revision_id=None,
            expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            reviewer_context_id=session.reviewer_context_id,
            action_descriptor_id=descriptor.action_descriptor_id,
            owning_module_id=descriptor.owning_module_id,
            owning_operation_id=descriptor.owning_operation_id,
            decision_value=decision_value,
            bounded_reason=_safe_text(reason, descriptor.maximum_reason_length),
            expected_project_snapshot_digest=snapshot.project_snapshot_digest,
            expected_workflow_revision=snapshot.workflow_revision,
            expected_candidate_digest=snapshot.candidate_digest,
            expected_source_record_digests=snapshot.source_record_digests,
            confirmation_context_digest=confirmation_context_digest,
            idempotency_key=idempotency_key,
            confirmed=True,
            limitations=list(descriptor.does_not_do)[:16],
        )
        self.store.save_boba_candidate_review_action(
            project_id, request.candidate_action_request_id, request.model_dump(mode="json")
        )
        return request

    def validate_candidate_action_request(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        """Re-read canonical state and reject stale or drifted submissions."""
        request = self._action_request(project_id, request_id)
        expires_at = _parse_time(request.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            return {
                "valid": False,
                "code": "expired_snapshot",
                "message": "The candidate review action expired before submission.",
            }
        descriptor = self._action_descriptor(request.action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "This candidate review action is no longer available.",
            }
        try:
            reference = self._reference_for(project_id, request.candidate_id)
        except ValidationError:
            return {
                "valid": False,
                "code": "candidate_removed",
                "message": "The candidate is no longer available.",
            }
        if self._project_snapshot_digest(project_id) != request.expected_project_snapshot_digest:
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
        if self._candidate_digest(project_id, request.candidate_id) != (
            request.expected_candidate_digest
        ):
            return {
                "valid": False,
                "code": "candidate_digest_mismatch",
                "message": "The candidate record changed while this review was open.",
            }
        live = {
            card.source_module_id: card.source_record_digest
            for card in self.build_source_cards(project_id, request.candidate_id)
        }
        for module_id, digest in request.expected_source_record_digests.items():
            if live.get(module_id) != digest:
                return {
                    "valid": False,
                    "code": "source_record_digest_mismatch",
                    "message": "A canonical source record changed while this review was open.",
                }
        if descriptor.action_descriptor_id not in self._available_actions(reference):
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "The action is no longer available for this exact candidate.",
            }
        return {
            "valid": True,
            "code": "current",
            "message": "Exact candidate remains current.",
        }

    def _action_request(
        self, project_id: str, request_id: str
    ) -> BobaCandidateActionRequestV1:
        _safe_id(project_id, "project id")
        _safe_id(request_id, "candidate action request id")
        raw = self.store.load_boba_candidate_review_action(project_id, request_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA candidate review action request is unavailable.")
        request = BobaCandidateActionRequestV1.model_validate(raw)
        if request.project_id != project_id:
            raise ValidationError("Candidate action belongs to another project.")
        return request

    async def submit_candidate_action_to_owner(
        self, project_id: str, request_id: str
    ) -> BobaCandidateActionReceiptV1:
        """Submit to the canonical owner and persist an immutable receipt."""
        request = self._action_request(project_id, request_id)
        existing = self.store.load_boba_candidate_review_receipt_for_action(
            project_id, request_id
        )
        if isinstance(existing, Mapping):
            receipt = BobaCandidateActionReceiptV1.model_validate(existing)
            return receipt.model_copy(update={"duplicate_request_reused": True})
        validation = self.validate_candidate_action_request(project_id, request_id)
        if not validation["valid"]:
            return self._persist_receipt(
                project_id,
                BobaCandidateActionReceiptV1(
                    candidate_action_receipt_id=f"candidate_receipt_{uuid4().hex}",
                    candidate_action_request_id=request.candidate_action_request_id,
                    project_id=project_id,
                    candidate_id=request.candidate_id,
                    owning_module_id=request.owning_module_id,
                    owning_operation_id=request.owning_operation_id,
                    completed_at=now_iso(),
                    accepted_by_owner=False,
                    canonical_status="rejected_stale_state",
                    authoritative_state_changed=False,
                    stale_state_rejected=True,
                    error_code=str(validation["code"]),
                    bounded_error_message=str(validation["message"]),
                    limitations=["No canonical owner was contacted; nothing changed."],
                ),
            )
        descriptor = self._action_descriptor(request.action_descriptor_id)
        if descriptor.owning_module_id == "creator_learning":
            return await self._submit_creator_feedback(project_id, request, descriptor)
        return self._persist_receipt(
            project_id,
            BobaCandidateActionReceiptV1(
                candidate_action_receipt_id=f"candidate_receipt_{uuid4().hex}",
                candidate_action_request_id=request.candidate_action_request_id,
                project_id=project_id,
                candidate_id=request.candidate_id,
                owning_module_id=request.owning_module_id,
                owning_operation_id=request.owning_operation_id,
                completed_at=now_iso(),
                canonical_status="owner_route_unavailable",
                accepted_by_owner=False,
                authoritative_state_changed=False,
                error_code="owner_route_unavailable",
                bounded_error_message=(
                    "No exact canonical owner route exists for this V1 action."
                ),
                limitations=["No authoritative state changed."],
            ),
        )

    async def _submit_creator_feedback(
        self,
        project_id: str,
        request: BobaCandidateActionRequestV1,
        descriptor: BobaCandidateActionDescriptorV1,
    ) -> BobaCandidateActionReceiptV1:
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
                target_type="candidate",
                target_id=request.candidate_id,
                user_action=action,  # type: ignore[arg-type]
                note=request.bounded_reason,
                reversible=True,
            )
        except (ValidationError, NotFoundError) as error:
            return self._persist_receipt(
                project_id,
                BobaCandidateActionReceiptV1(
                    candidate_action_receipt_id=f"candidate_receipt_{uuid4().hex}",
                    candidate_action_request_id=request.candidate_action_request_id,
                    project_id=project_id,
                    candidate_id=request.candidate_id,
                    owning_module_id=request.owning_module_id,
                    owning_operation_id=request.owning_operation_id,
                    completed_at=now_iso(),
                    canonical_status="rejected_by_owner",
                    accepted_by_owner=False,
                    authoritative_state_changed=False,
                    error_code="owner_rejected",
                    bounded_error_message=_safe_text(str(error), 900),
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
                BobaCandidateActionReceiptV1(
                    candidate_action_receipt_id=f"candidate_receipt_{uuid4().hex}",
                    candidate_action_request_id=request.candidate_action_request_id,
                    project_id=project_id,
                    candidate_id=request.candidate_id,
                    owning_module_id=request.owning_module_id,
                    owning_operation_id=request.owning_operation_id,
                    completed_at=now_iso(),
                    canonical_status="malformed_owner_response",
                    accepted_by_owner=False,
                    authoritative_state_changed=False,
                    error_code="malformed_canonical_response",
                    bounded_error_message=(
                        "The owning module returned no canonical record identifier."
                    ),
                    limitations=["No authoritative state changed."],
                ),
            )
        return self._persist_receipt(
            project_id,
            BobaCandidateActionReceiptV1(
                candidate_action_receipt_id=f"candidate_receipt_{uuid4().hex}",
                candidate_action_request_id=request.candidate_action_request_id,
                project_id=project_id,
                candidate_id=request.candidate_id,
                owning_module_id="creator_learning",
                owning_operation_id="record_creator_feedback_event",
                completed_at=now_iso(),
                accepted_by_owner=True,
                canonical_request_id=request.candidate_action_request_id,
                canonical_record_id=canonical_id,
                canonical_record_digest=_digest(_safe_payload(payload)),
                canonical_status=_safe_text(payload.get("user_action") or "recorded", 160),
                # Creator Learning owns an advisory record. It is a canonical
                # record with an identity, but it changes no editorial authority.
                authoritative_state_changed=False,
                canonical_refresh_required=True,
                limitations=[
                    "Creator Learning feedback is advisory and never overrides "
                    "source truth or safety.",
                    *descriptor.does_not_do,
                ],
            ),
        )

    def _persist_receipt(
        self, project_id: str, receipt: BobaCandidateActionReceiptV1
    ) -> BobaCandidateActionReceiptV1:
        if receipt.authoritative_state_changed and not (
            receipt.canonical_record_id and receipt.canonical_record_digest
        ):
            raise ValidationError(
                "Authoritative state cannot change without a canonical owner record."
            )
        self.store.save_boba_candidate_review_receipt(
            project_id,
            receipt.candidate_action_receipt_id,
            receipt.model_dump(mode="json"),
        )
        return receipt

    def inspect_candidate_action_receipt(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        request = self._action_request(project_id, request_id)
        receipt = self.store.load_boba_candidate_review_receipt_for_action(
            project_id, request_id
        )
        return {
            "request": request.model_dump(mode="json"),
            "receipt": _safe_payload(receipt) if receipt else None,
        }

    # ------------------------------------------------------------------
    # Events and timeline
    # ------------------------------------------------------------------
    def inspect_candidate_events(
        self,
        project_id: str,
        *,
        after_sequence: int = 0,
        limit: int = _MAX_EVENTS,
    ) -> dict[str, Any]:
        """Project bounded, de-duplicated canonical events. No invented progress."""
        _safe_id(project_id, "project id")
        seen: set[tuple[str, str]] = set()
        events: list[BobaCandidateReviewEventV1] = []
        for source_id in ("clip_discovery", "clip_ranking", "editorial_decision",
                          "workflow_controller"):
            payload = self._source_payload(source_id, project_id)
            rows = payload.get("events")
            if not isinstance(rows, list):
                continue
            for row in rows[-_MAX_EVENTS:]:
                if not isinstance(row, Mapping):
                    continue
                safe = _as_mapping(_safe_payload(row))
                event_id = (
                    _safe_text(safe.get("event_id") or safe.get("id"), 180)
                    or _stable_id("candidate_event", source_id, _digest(safe))
                )
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
                percent = (
                    min(100.0, round(current / total * 100, 4))
                    if current is not None and total
                    else None
                )
                event_type = _safe_text(safe.get("event_type") or "canonical_event", 160)
                events.append(
                    BobaCandidateReviewEventV1(
                        event_id=_stable_id("candidate_event", source_id, event_id),
                        project_id=project_id,
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
                        progress_percent=percent,
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
            "schema_version": "boba_candidate_review_events_v1",
            "project_id": project_id,
            "events": [item.model_dump(mode="json") for item in bounded],
            "has_more": len(events) > len(bounded),
            "latest_sequence": max(
                (item.source_sequence or 0 for item in bounded), default=after_sequence
            ),
        }

    def inspect_candidate_timeline(
        self, project_id: str, *, limit: int = MAX_TIMELINE_ENTRIES
    ) -> dict[str, Any]:
        events = self.inspect_candidate_events(project_id, limit=limit)["events"]
        entries = [
            BobaCandidateReviewTimelineEntryV1(
                timeline_entry_id=_stable_id("candidate_timeline", str(event["event_id"])),
                project_id=project_id,
                candidate_id=event.get("candidate_id"),
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
            "schema_version": "boba_candidate_review_timeline_v1",
            "project_id": project_id,
            "entries": entries[:MAX_TIMELINE_ENTRIES],
        }

    # ------------------------------------------------------------------
    # Build, export, reset
    # ------------------------------------------------------------------
    def _notifications(
        self, project_id: str, items: list[BobaCandidateQueueItemV1]
    ) -> list[BobaCandidateReviewNotificationV1]:
        notifications: list[BobaCandidateReviewNotificationV1] = []
        for item in items:
            if not (
                item.blocker_count
                or item.conflict_count
                or item.human_action_required
                or item.stale
            ):
                continue
            notifications.append(
                BobaCandidateReviewNotificationV1(
                    notification_id=_stable_id(
                        "candidate_notification", project_id, item.candidate_id
                    ),
                    project_id=project_id,
                    candidate_id=item.candidate_id,
                    source_module_id=(
                        item.source_module_ids[0] if item.source_module_ids else "clip_discovery"
                    ),
                    source_record_id=(
                        item.source_record_ids[0] if item.source_record_ids else "clip_discovery"
                    ),
                    notification_type=(
                        "blocking"
                        if item.blocker_count
                        else "conflict"
                        if item.conflict_count
                        else "human_review_required"
                        if item.human_action_required
                        else "stale"
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
            )
        return notifications[:64]

    def _summary(
        self,
        items: list[BobaCandidateQueueItemV1],
        overlaps: list[BobaCandidateOverlapV1],
        session: BobaCandidateReviewSessionV1 | None,
    ) -> BobaCandidateReviewSummaryV1:
        return BobaCandidateReviewSummaryV1(
            total_candidate_count=len(items),
            current_candidate_count=sum(1 for item in items if item.current),
            stale_candidate_count=sum(1 for item in items if item.stale),
            historical_candidate_count=sum(
                1 for item in items if item.historical or item.superseded
            ),
            selected_candidate_count=sum(1 for item in items if item.selected),
            rejected_candidate_count=sum(1 for item in items if item.rejected),
            pending_human_review_count=sum(
                1 for item in items if item.human_action_required
            ),
            blocked_candidate_count=sum(1 for item in items if item.blocker_count),
            missing_evidence_count=sum(item.missing_evidence_count for item in items),
            conflict_count=sum(item.conflict_count for item in items),
            substantial_overlap_pair_count=sum(
                1 for record in overlaps if record.substantial_overlap
            ),
            exact_duplicate_window_count=sum(
                1 for record in overlaps if record.exact_duplicate_window
            ),
            current_selected_candidate_id=(
                session.selected_candidate_id if session else None
            ),
            current_comparison_candidate_ids=(
                list(session.comparison_candidate_ids) if session else []
            ),
            safest_next_review_action=(
                "Review the highest-priority candidate and its source evidence."
                if items
                else "No candidate review work is outstanding."
            ),
            required_human_actions=[
                f"{item.candidate_id}: {item.priority_reason}"
                for item in items
                if item.human_action_required
            ][:24],
            limitations=[
                "Counts describe projected canonical records, not panel decisions.",
                "No candidate is selected automatically.",
            ],
        )

    def _signal_usage(self, project_id: str) -> BobaCandidateReviewSignalUsageV1:
        def present(source_id: str) -> bool:
            return bool(self._source_payload(source_id, project_id))

        unavailable = [
            source_id
            for source_id in build_fixed_candidate_source_registry()
            if not present(source_id)
        ]
        return BobaCandidateReviewSignalUsageV1(
            canonical_candidate_discovery_records=present("clip_discovery"),
            canonical_ranking_records=present("clip_ranking"),
            canonical_editorial_records=present("editorial_decision"),
            canonical_explanation_records=present("explanation"),
            canonical_creative_records=any(
                present(source_id)
                for source_id in ("clip_brief", "hook_retention", "caption_motion", "music_mood")
            ),
            canonical_workflow_records=present("workflow_controller"),
            canonical_rights_records=present("rights_permission_gate"),
            canonical_artifact_records=present("artifact_inspector"),
            unavailable_signals=unavailable,
            limitations=[
                "Signal usage records which canonical owners were read, not who decided.",
            ],
        )

    def build_candidate_review(self, project_id: str) -> dict[str, Any]:
        registry = self.build_candidate_review_registry(project_id)
        references = self.build_candidate_references(project_id)
        overlaps = self.calculate_candidate_overlaps(project_id)
        items = [
            self._queue_item(project_id, reference, index, overlaps)
            for index, reference in enumerate(references)
        ]
        items.sort(key=lambda item: (item.priority_tier, item.deterministic_sort_key))
        events = self.inspect_candidate_events(project_id)
        result = BobaCandidateReviewSetV1(
            project_id=project_id,
            source_id=_safe_text(
                self._source_payload("clip_discovery", project_id).get("source_id"), 512
            ),
            registry_snapshots=[
                BobaCandidateReviewRegistrySnapshotV1.model_validate(
                    registry["registry_snapshot"]
                )
            ],
            candidate_references=references,
            candidate_queue_items=items,
            overlap_records=overlaps,
            events=[
                BobaCandidateReviewEventV1.model_validate(item) for item in events["events"]
            ],
            notifications=self._notifications(project_id, items),
            review_summary=self._summary(items, overlaps, None),
            signal_usage=self._signal_usage(project_id),
            limitations=[
                "Candidate Review Panel V1 is a presentation, comparison and "
                "canonical routing layer. It does not discover, rerank or select "
                "candidates.",
                "Source scores are not virality or performance guarantees.",
                "No authoritative candidate selection action exists in V1.",
            ],
        )
        self.store.save_boba_candidate_review(project_id, result.model_dump(mode="json"))
        return result.model_dump(mode="json")

    def load_candidate_review(self, project_id: str) -> dict[str, Any] | None:
        _safe_id(project_id, "project id")
        return self.store.load_boba_candidate_review(project_id)

    def export_candidate_review(
        self, project_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "boba_candidate_review_export_v1",
            "project_id": project_id,
            "exported_at": now_iso(),
            "queue": self.build_candidate_queue(project_id, limit=MAX_QUEUE_PAGE_SIZE),
            "overlap_records": [
                record.model_dump(mode="json")
                for record in self.calculate_candidate_overlaps(project_id)
            ],
            "timeline": self.inspect_candidate_timeline(project_id, limit=50),
            "privacy": {
                "private_paths_excluded": True,
                "raw_media_excluded": True,
                "raw_transcripts_excluded": True,
                "secrets_excluded": True,
                "source_records_duplicated": False,
                "source_media_modified": False,
                "accepted_output_modified": False,
                "upload_used": False,
                "publication_used": False,
                "speaker_identity_inferred": False,
                "biometric_inference_used": False,
            },
        }
        if session_id:
            payload["session"] = self.get_candidate_review_session(
                project_id, session_id
            ).model_dump(mode="json")
        return _as_mapping(_safe_payload(payload))

    def reset_candidate_review_metadata(
        self, project_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        if session_id:
            _safe_id(session_id, "candidate review session id")
            removed = self.store.delete_boba_candidate_review_session(project_id, session_id)
            return {
                "schema_version": "boba_candidate_review_reset_v1",
                "project_id": project_id,
                "session_removed": removed,
                "candidate_records_preserved": True,
                "ranking_records_preserved": True,
                "editorial_history_preserved": True,
                "review_ui_history_preserved": True,
                "action_receipt_history_preserved": True,
            }
        return self.store.reset_boba_candidate_review_metadata(project_id)

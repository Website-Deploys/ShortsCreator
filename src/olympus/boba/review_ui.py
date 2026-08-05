"""Read-only BOBA Review UI projections and constrained action routing.

The review UI is deliberately a presentation layer.  It stores sessions,
preferences, and canonical-action receipts, but it never becomes the owner of
rights, safety, validation, quality, workflow, or final-decision state.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping
from uuid import uuid4

from pydantic import Field, field_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.memory import sanitize_memory_payload
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import ValidationError

if TYPE_CHECKING:
    from olympus.boba.integration import BobaIntegration


ReviewMode = Literal[
    "project_overview",
    "workflow_review",
    "clip_review",
    "output_review",
    "approval_review",
    "quality_review",
    "validation_review",
    "artifact_review",
    "recovery_review",
    "incident_review",
    "final_decision_review",
    "comparison_review",
    "historical_review",
]
ReviewTargetType = Literal[
    "project",
    "workflow_stage",
    "candidate_clip",
    "selected_clip",
    "rendered_output",
    "recovered_output",
    "accepted_output",
    "approval_request",
    "validation_run",
    "quality_review",
    "artifact",
    "report_bundle",
    "recovery_run",
    "incident",
    "final_decision",
    "dispatch_envelope",
    "unknown",
]
QueueCategory = Literal[
    "critical_attention",
    "blocked",
    "human_review_required",
    "ready_for_review",
    "awaiting_evidence",
    "in_progress",
    "completed",
    "historical",
    "informational",
    "unavailable",
    "unknown",
]

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,180}$")
_SENSITIVE_KEY = re.compile(r"(secret|token|password|credential|cookie|authorization)", re.I)
_PRIVATE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|file:|/home/|/Users/|\\\\)", re.I)
_MAX_SOURCE_CARDS = 16
_MAX_EVENTS = 100
_MAX_QUEUE = 100


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    return f"{prefix}_{_digest([str(part) for part in parts])[:24]}"


def _safe_id(value: str, label: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValidationError(f"Invalid {label}.")
    return value


def _safe_text(value: object, maximum: int = 700) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    if _PRIVATE_PATH.search(text):
        text = _PRIVATE_PATH.sub("[private-path]", text)
    return text[:maximum]


def _safe_payload(value: Any) -> Any:
    """Return a bounded, JSON-safe projection with secrets and paths removed."""
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]"
            if _SENSITIVE_KEY.search(str(key))
            else _safe_payload(item)
            for key, item in value.items()
            if str(key).lower() not in {"raw_log", "raw_logs", "raw_patch", "media_path"}
        }
    if isinstance(value, list | tuple | set):
        return [_safe_payload(item) for item in list(value)[:64]]
    if isinstance(value, str):
        return _safe_text(value, 1_200)
    return sanitize_memory_payload(value, max_excerpt_chars=1_200, path="boba.review_ui")


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_stale(payload: Mapping[str, Any]) -> bool:
    if bool(payload.get("stale") or payload.get("expired") or payload.get("invalidated")):
        return True
    expires_at = _parse_time(payload.get("expires_at"))
    return expires_at is not None and expires_at <= datetime.now(UTC)


def _first_text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _safe_text(value)
    return ""


def _record_id(payload: Mapping[str, Any], module_id: str) -> str:
    for key in (
        "source_record_id",
        "final_decision_id",
        "review_case_id",
        "workflow_run_id",
        "validation_run_id",
        "artifact_inspection_run_id",
        "report_bundle_id",
        "decision_id",
        "request_id",
        "id",
    ):
        value = payload.get(key)
        if isinstance(value, str) and _SAFE_ID.fullmatch(value):
            return value
    return _stable_id("review_source", module_id, _digest(payload))


def _source_status(payload: Mapping[str, Any]) -> str:
    for key in (
        "original_status",
        "status",
        "run_status",
        "decision_status",
        "review_status",
        "disposition",
        "state",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _safe_text(value, 120)
    for key in ("summary", "result"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            status = _source_status(_as_mapping(nested))
            if status != "unknown":
                return status
    return "unknown"


def _source_decision(payload: Mapping[str, Any]) -> str | None:
    for key in ("original_decision", "decision", "acceptance_decision", "final_disposition"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _safe_text(value, 160)
        if isinstance(value, Mapping):
            nested = _first_text(_as_mapping(value), "decision", "disposition", "status")
            if nested:
                return nested
    return None


def _has_human_review(payload: Mapping[str, Any]) -> bool:
    if bool(payload.get("human_review_required")):
        return True
    text = " ".join(
        _safe_text(value, 400)
        for value in (
            payload.get("status"),
            payload.get("decision"),
            payload.get("summary"),
        )
    ).lower()
    return "human review" in text or "requires_human" in text


def _is_blocking(payload: Mapping[str, Any], status: str) -> bool:
    if bool(payload.get("blocking") or payload.get("blocked")):
        return True
    text = f"{status} {_source_decision(payload) or ''}".lower()
    return any(token in text for token in ("block", "hold", "fail", "deny", "reject", "missing"))


class BobaReviewUiRegistrySnapshotV1(BobaContract):
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = "1"
    created_at: str = Field(default_factory=now_iso)
    view_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    available_review_modes: list[str] = Field(default_factory=list, max_length=32)
    unavailable_review_modes: list[str] = Field(default_factory=list, max_length=32)
    available_action_ids: list[str] = Field(default_factory=list, max_length=32)
    unavailable_action_ids: list[str] = Field(default_factory=list, max_length=32)
    registry_digest: str = Field(min_length=64, max_length=64)
    immutable: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaReviewViewDescriptorV1(BobaContract):
    view_descriptor_id: str = Field(min_length=1, max_length=180)
    review_mode: ReviewMode
    display_name: str = Field(min_length=1, max_length=160)
    supported_target_types: list[ReviewTargetType] = Field(default_factory=list, max_length=24)
    required_source_modules: list[str] = Field(default_factory=list, max_length=24)
    optional_source_modules: list[str] = Field(default_factory=list, max_length=24)
    required_identity_fields: list[str] = Field(default_factory=list, max_length=24)
    section_ids: list[str] = Field(default_factory=list, max_length=32)
    supported_comparison_types: list[str] = Field(default_factory=list, max_length=12)
    event_source_module_ids: list[str] = Field(default_factory=list, max_length=24)
    availability: Literal["available", "unavailable"] = "available"
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewActionDescriptorV1(BobaContract):
    action_descriptor_id: str = Field(min_length=1, max_length=180)
    display_name: str = Field(min_length=1, max_length=160)
    action_class: str = Field(min_length=1, max_length=120)
    owning_module_id: str = Field(min_length=1, max_length=160)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    supported_review_modes: list[ReviewMode] = Field(default_factory=list, max_length=24)
    supported_target_types: list[ReviewTargetType] = Field(default_factory=list, max_length=24)
    allowed_decision_values: list[str] = Field(default_factory=list, max_length=16)
    requires_reason: bool = False
    maximum_reason_length: int = Field(default=900, ge=0, le=1_200)
    requires_confirmation: bool = True
    requires_current_snapshot: bool = True
    requires_workflow_revision: bool = True
    requires_target_digest: bool = True
    requires_approval_context: bool = False
    requires_safety_context: bool = False
    requires_human_identity: bool = True
    destructive: bool = False
    execution_capable: bool = False
    upload_or_publication: bool = False
    allowed_in_v1: bool = False
    availability: Literal["available", "unavailable"] = "unavailable"
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewSessionV1(BobaContract):
    review_session_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    expires_at: str
    reviewer_context_id: str = Field(min_length=1, max_length=160)
    selected_review_mode: ReviewMode = "project_overview"
    selected_target_type: ReviewTargetType = "project"
    selected_target_id: str = ""
    selected_clip_id: str | None = None
    selected_output_id: str | None = None
    selected_attempt_id: str | None = None
    comparison_target_ids: list[str] = Field(default_factory=list, max_length=4)
    active_filter_id: str = "all"
    active_sort: str = "priority"
    active_tab: str = "overview"
    evidence_drawer_open: bool = False
    event_drawer_open: bool = False
    compact_mode: bool = False
    read_queue_item_ids: list[str] = Field(default_factory=list, max_length=256)
    acknowledged_notification_ids: list[str] = Field(default_factory=list, max_length=256)
    session_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewQueueItemV1(BobaContract):
    queue_item_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    target_type: ReviewTargetType
    target_id: str = Field(min_length=1, max_length=180)
    clip_id: str | None = None
    output_id: str | None = None
    attempt_id: str | None = None
    review_mode: ReviewMode
    priority: int = Field(ge=0, le=999)
    display_category: QueueCategory
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(default="", max_length=900)
    source_module_ids: list[str] = Field(default_factory=list, max_length=16)
    source_record_ids: list[str] = Field(default_factory=list, max_length=32)
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=32)
    primary_reason: str = Field(default="", max_length=700)
    blocker_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    human_action_required: bool = False
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=16)
    current: bool = True
    stale: bool = False
    historical: bool = False
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    queue_sort_key: str = Field(min_length=1, max_length=240)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewTargetV1(BobaContract):
    review_target_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    target_type: ReviewTargetType
    target_id: str = Field(min_length=1, max_length=180)
    clip_id: str | None = None
    output_id: str | None = None
    artifact_reference_ids: list[str] = Field(default_factory=list, max_length=32)
    attempt_id: str | None = None
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    target_digest: str = Field(min_length=64, max_length=64)
    current: bool = True
    stale: bool = False
    historical: bool = False
    source_module_ids: list[str] = Field(default_factory=list, max_length=24)
    source_record_ids: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewSnapshotV1(BobaContract):
    review_snapshot_id: str = Field(min_length=1, max_length=180)
    review_session_id: str = Field(min_length=1, max_length=180)
    review_target_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso)
    refreshed_at: str = Field(default_factory=now_iso)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    target_digest: str = Field(min_length=64, max_length=64)
    source_record_references: list[dict[str, str]] = Field(default_factory=list, max_length=32)
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=32)
    section_ids: list[str] = Field(default_factory=list, max_length=32)
    source_card_ids: list[str] = Field(default_factory=list, max_length=32)
    timeline_entry_ids: list[str] = Field(default_factory=list, max_length=128)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=16)
    rights_status: str = "unavailable"
    safety_status: str = "unavailable"
    approval_status: str = "unavailable"
    workflow_status: str = "unavailable"
    artifact_status: str = "unavailable"
    validation_status: str = "unavailable"
    quality_status: str = "unavailable"
    recovery_status: str = "unavailable"
    final_decision_status: str = "unavailable"
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    limitation_count: int = Field(default=0, ge=0)
    human_action_required: bool = False
    current: bool = True
    stale: bool = False
    snapshot_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewSourceCardV1(BobaContract):
    source_card_id: str = Field(min_length=1, max_length=180)
    review_snapshot_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=160)
    authority_domain: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    source_schema_id: str = Field(default="unknown", max_length=180)
    source_schema_version: str = Field(default="unknown", max_length=80)
    original_status: str = Field(default="unknown", max_length=160)
    original_decision: str | None = Field(default=None, max_length=200)
    display_category: QueueCategory = "unknown"
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(default="", max_length=900)
    easy_explanation: str = Field(default="", max_length=900)
    current: bool = False
    stale: bool = False
    expired: bool = False
    invalidated: bool = False
    superseded: bool = False
    authoritative: bool = True
    advisory_only: bool = False
    human_review_required: bool = False
    blocking: bool = False
    details_route: str = Field(default="", max_length=360)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewSectionV1(BobaContract):
    review_section_id: str = Field(min_length=1, max_length=180)
    review_snapshot_id: str | None = None
    section_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    source_card_ids: list[str] = Field(default_factory=list, max_length=32)
    ordered_item_references: list[str] = Field(default_factory=list, max_length=64)
    visible: bool = True
    collapsed_by_default: bool = False
    empty: bool = False
    loading: bool = False
    unavailable: bool = False
    bounded_empty_message: str = Field(default="", max_length=500)
    bounded_unavailable_message: str = Field(default="", max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewActionRequestV1(BobaContract):
    review_action_request_id: str = Field(min_length=1, max_length=180)
    review_session_id: str = Field(min_length=1, max_length=180)
    review_snapshot_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    requested_at: str = Field(default_factory=now_iso)
    reviewer_context_id: str = Field(min_length=1, max_length=160)
    action_descriptor_id: str = Field(min_length=1, max_length=180)
    owning_module_id: str = Field(min_length=1, max_length=160)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    review_target_id: str = Field(min_length=1, max_length=180)
    target_type: ReviewTargetType
    target_id: str = Field(min_length=1, max_length=180)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    clip_id: str | None = None
    output_id: str | None = None
    attempt_id: str | None = None
    decision_value: str | None = Field(default=None, max_length=160)
    bounded_reason: str = Field(default="", max_length=1_200)
    expected_project_snapshot_digest: str = Field(min_length=64, max_length=64)
    expected_workflow_revision: int = Field(default=0, ge=0)
    expected_target_digest: str = Field(min_length=64, max_length=64)
    expected_source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=32)
    confirmation_context_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=180)
    expires_at: str
    confirmed: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewActionReceiptV1(BobaContract):
    action_receipt_id: str = Field(min_length=1, max_length=180)
    review_action_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    owning_module_id: str = Field(min_length=1, max_length=160)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    submitted_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None
    canonical_request_id: str | None = None
    canonical_record_id: str | None = None
    canonical_record_digest: str | None = None
    canonical_status: str = "pending"
    accepted_by_owner: bool = False
    authoritative_state_changed: bool = False
    canonical_refresh_required: bool = True
    stale_state_rejected: bool = False
    duplicate_request_reused: bool = False
    error_code: str | None = None
    bounded_error_message: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewTimelineEntryV1(BobaContract):
    timeline_entry_id: str = Field(min_length=1, max_length=180)
    review_snapshot_id: str | None = None
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
    review_ui_explanation: str = Field(default="", max_length=900)
    severity: str = Field(default="informational", max_length=80)
    current: bool = True
    historical: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewNotificationV1(BobaContract):
    notification_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    review_target_id: str = Field(min_length=1, max_length=180)
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
    acknowledged_at: str | None = None
    canonical_issue_resolved: bool = False
    current: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewUiEventV1(BobaContract):
    ui_event_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    review_target_id: str | None = None
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
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewUiPreferencesV1(BobaContract):
    preferences_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    reviewer_context_id: str = Field(min_length=1, max_length=160)
    default_review_mode: ReviewMode = "project_overview"
    default_sort: str = "priority"
    default_filters: list[str] = Field(default_factory=list, max_length=24)
    compact_mode: bool = False
    show_technical_details: bool = False
    show_historical_records: bool = False
    reduced_motion: bool = False
    auto_open_critical_attention: bool = True
    event_drawer_default_open: bool = False
    evidence_drawer_default_open: bool = False
    updated_at: str = Field(default_factory=now_iso)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewUiSummaryV1(BobaContract):
    active_session_count: int = Field(default=0, ge=0)
    total_queue_item_count: int = Field(default=0, ge=0)
    critical_attention_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    human_review_required_count: int = Field(default=0, ge=0)
    ready_for_review_count: int = Field(default=0, ge=0)
    awaiting_evidence_count: int = Field(default=0, ge=0)
    current_target_id: str | None = None
    current_review_mode: str | None = None
    current_workflow_stage: str | None = None
    current_blocker_count: int = Field(default=0, ge=0)
    current_missing_evidence_count: int = Field(default=0, ge=0)
    current_conflict_count: int = Field(default=0, ge=0)
    latest_canonical_event_at: str | None = None
    event_stream_connected: bool = False
    safest_next_review_action: str | None = None
    required_human_actions: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewUiSignalUsageV1(BobaContract):
    canonical_source_records_used: bool = True
    workflow_controller_used: bool = False
    rights_gate_used: bool = False
    safety_gate_used: bool = False
    validator_runner_used: bool = False
    output_quality_reviewer_used: bool = False
    artifact_inspector_used: bool = False
    report_reader_used: bool = False
    autopilot_used: bool = False
    final_decision_bus_used: bool = False
    integration_layer_used: bool = False
    exact_identity_binding_used: bool = True
    stale_snapshot_protection_used: bool = True
    canonical_action_receipts_used: bool = True
    truthful_events_used: bool = True
    responsive_layout_used: bool = True
    keyboard_navigation_used: bool = True
    reduced_motion_used: bool = True
    untrusted_html_rendering_used: bool = False
    arbitrary_api_url_used: bool = False
    arbitrary_operation_used: bool = False
    arbitrary_module_used: bool = False
    arbitrary_path_used: bool = False
    external_media_used: bool = False
    optimistic_authority_change_used: bool = False
    local_approval_created: bool = False
    local_safety_decision_created: bool = False
    local_rights_decision_created: bool = False
    local_validation_decision_created: bool = False
    local_quality_decision_created: bool = False
    local_workflow_transition_created: bool = False
    fake_progress_used: bool = False
    command_execution_used: bool = False
    shell_execution_used: bool = False
    git_execution_used: bool = False
    ffmpeg_execution_used: bool = False
    repair_execution_used: bool = False
    checkpoint_restore_used: bool = False
    source_media_modified: bool = False
    accepted_outputs_modified: bool = False
    uploading_used: bool = False
    publication_used: bool = False
    external_analytics_used: bool = False
    network_access_outside_existing_api_used: bool = False
    rights_bypass_used: bool = False
    safety_bypass_used: bool = False
    destructive_action_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaReviewUiSetV1(BobaContract):
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = "review_ui"
    created_at: str = Field(default_factory=now_iso)
    registry_snapshots: list[BobaReviewUiRegistrySnapshotV1] = Field(default_factory=list, max_length=8)
    view_descriptors: list[BobaReviewViewDescriptorV1] = Field(default_factory=list, max_length=32)
    action_descriptors: list[BobaReviewActionDescriptorV1] = Field(default_factory=list, max_length=32)
    review_sessions: list[BobaReviewSessionV1] = Field(default_factory=list, max_length=16)
    review_queue_items: list[BobaReviewQueueItemV1] = Field(default_factory=list, max_length=_MAX_QUEUE)
    review_snapshots: list[BobaReviewSnapshotV1] = Field(default_factory=list, max_length=32)
    source_cards: list[BobaReviewSourceCardV1] = Field(default_factory=list, max_length=_MAX_SOURCE_CARDS)
    review_sections: list[BobaReviewSectionV1] = Field(default_factory=list, max_length=32)
    review_actions: list[BobaReviewActionRequestV1] = Field(default_factory=list, max_length=64)
    action_receipts: list[BobaReviewActionReceiptV1] = Field(default_factory=list, max_length=64)
    timeline_entries: list[BobaReviewTimelineEntryV1] = Field(default_factory=list, max_length=_MAX_EVENTS)
    notifications: list[BobaReviewNotificationV1] = Field(default_factory=list, max_length=64)
    events: list[BobaReviewUiEventV1] = Field(default_factory=list, max_length=_MAX_EVENTS)
    preferences: list[BobaReviewUiPreferencesV1] = Field(default_factory=list, max_length=32)
    ui_summary: BobaReviewUiSummaryV1 = Field(default_factory=BobaReviewUiSummaryV1)
    signal_usage: BobaReviewUiSignalUsageV1 = Field(default_factory=BobaReviewUiSignalUsageV1)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


def build_fixed_review_view_registry() -> dict[str, BobaReviewViewDescriptorV1]:
    sections = ["overview", "workflow", "artifacts", "validation", "quality", "final_decision", "timeline"]
    definitions: list[tuple[ReviewMode, str, list[ReviewTargetType], list[str]]] = [
        ("project_overview", "Project overview", ["project"], sections),
        ("workflow_review", "Workflow review", ["project", "workflow_stage"], ["workflow", "timeline", "events"]),
        ("clip_review", "Clip review", ["candidate_clip", "selected_clip"], ["overview", "creative_plan", "captions", "motion"]),
        ("output_review", "Rendered output review", ["rendered_output", "accepted_output"], ["preview", "artifacts", "validation", "quality"]),
        ("approval_review", "Approval review", ["approval_request"], ["approval", "rights", "safety"]),
        ("quality_review", "Quality review", ["quality_review", "rendered_output"], ["quality", "artifacts", "validation"]),
        ("validation_review", "Validation review", ["validation_run", "rendered_output"], ["validation", "artifacts"]),
        ("artifact_review", "Artifact review", ["artifact", "rendered_output"], ["artifacts", "lineage"]),
        ("recovery_review", "Recovery review", ["recovery_run", "incident"], ["recovery", "timeline"]),
        ("incident_review", "Incident review", ["incident"], ["warnings", "timeline", "artifacts"]),
        ("final_decision_review", "Final decision review", ["final_decision", "dispatch_envelope"], ["final_decision", "rights", "safety", "workflow"]),
        ("comparison_review", "Comparison review", ["rendered_output", "candidate_clip"], ["comparison", "quality", "artifacts"]),
        ("historical_review", "Historical review", ["project", "workflow_stage", "rendered_output"], ["timeline", "events"]),
    ]
    registry: dict[str, BobaReviewViewDescriptorV1] = {}
    for mode, label, targets, section_ids in definitions:
        descriptor_id = f"review_view_{mode}_v1"
        if descriptor_id in registry:
            raise ValidationError("Duplicate BOBA Review UI view descriptor.")
        registry[descriptor_id] = BobaReviewViewDescriptorV1(
            view_descriptor_id=descriptor_id,
            review_mode=mode,
            display_name=label,
            supported_target_types=targets,
            required_source_modules=["workflow_controller"],
            optional_source_modules=["rights_permission_gate", "safety_gate", "validator_runner", "output_quality_reviewer", "artifact_inspector", "report_reader", "final_decision_bus"],
            required_identity_fields=["project_id", "target_id", "target_digest"],
            section_ids=section_ids,
            supported_comparison_types=["candidate", "output"] if mode == "comparison_review" else [],
            event_source_module_ids=["workflow_controller", "validator_runner", "artifact_inspector", "report_reader", "final_decision_bus"],
        )
    return registry


def build_fixed_review_action_registry() -> dict[str, BobaReviewActionDescriptorV1]:
    definitions = [
        BobaReviewActionDescriptorV1(
            action_descriptor_id="review_action_acknowledge_notification_v1",
            display_name="Acknowledge review notification",
            action_class="ui_metadata",
            owning_module_id="review_ui",
            owning_operation_id="acknowledge_notification",
            supported_review_modes=["project_overview", "workflow_review", "incident_review", "historical_review"],
            supported_target_types=["project", "incident", "workflow_stage"],
            requires_reason=False,
            requires_confirmation=True,
            requires_workflow_revision=False,
            requires_target_digest=False,
            allowed_in_v1=True,
            availability="available",
            limitations=["Acknowledgement does not resolve the canonical source issue."],
        ),
        BobaReviewActionDescriptorV1(
            action_descriptor_id="review_action_output_quality_human_review_v1",
            display_name="Submit output quality decision",
            action_class="human_quality_decision",
            owning_module_id="output_quality_reviewer",
            owning_operation_id="record_human_review",
            supported_review_modes=["output_review", "quality_review"],
            supported_target_types=["quality_review", "rendered_output"],
            allowed_decision_values=["accept_for_next_internal_stage", "accept_with_disclosed_limitation", "reject_output", "send_back_to_tool_recovery", "send_back_to_repair_planner", "request_more_evidence"],
            requires_reason=True,
            requires_approval_context=True,
            requires_safety_context=True,
            availability="unavailable",
            limitations=["Unavailable until an exact quality review target and owner binding are present."],
        ),
        BobaReviewActionDescriptorV1(
            action_descriptor_id="review_action_workflow_human_decision_v1",
            display_name="Submit workflow human decision",
            action_class="human_workflow_decision",
            owning_module_id="workflow_controller",
            owning_operation_id="record_human_decision",
            supported_review_modes=["workflow_review", "approval_review"],
            supported_target_types=["workflow_stage", "approval_request"],
            allowed_decision_values=["approve", "reject", "request_revision"],
            requires_reason=True,
            requires_approval_context=True,
            requires_safety_context=True,
            availability="unavailable",
            limitations=["Unavailable until an exact workflow decision request is selected."],
        ),
        BobaReviewActionDescriptorV1(
            action_descriptor_id="review_action_safety_human_review_v1",
            display_name="Submit Safety review",
            action_class="human_safety_decision",
            owning_module_id="safety_gate",
            owning_operation_id="record_human_review",
            supported_review_modes=["approval_review", "incident_review"],
            supported_target_types=["approval_request", "incident"],
            allowed_decision_values=["approve_exact_medium_risk_action", "deny_action", "request_more_evidence", "acknowledge_disclosed_limitation", "approve_stricter_budget_reset", "select_safer_alternative", "keep_project_paused"],
            requires_reason=True,
            requires_approval_context=True,
            requires_safety_context=True,
            availability="unavailable",
            limitations=["Unavailable until the exact Safety evaluation case is selected."],
        ),
    ]
    registry: dict[str, BobaReviewActionDescriptorV1] = {}
    for descriptor in definitions:
        if descriptor.action_descriptor_id in registry:
            raise ValidationError("Duplicate BOBA Review UI action descriptor.")
        if descriptor.upload_or_publication or descriptor.execution_capable:
            raise ValidationError("Review UI V1 action registry cannot expose execution or publication.")
        registry[descriptor.action_descriptor_id] = descriptor
    return registry


_SOURCE_LOADERS: dict[str, tuple[str, str, Callable[[BobaMemoryStore, str], Any]]]
_SOURCE_LOADERS = {
    "rights_permission_gate": ("Rights + Permission Gate", "rights", lambda store, project_id: store.load_boba_rights_permission_gate(project_id)),
    "safety_gate": ("Safety Gate", "safety", lambda store, project_id: store.load_boba_safety_gate(project_id)),
    "workflow_controller": ("Workflow Controller", "workflow", lambda store, project_id: store.load_boba_workflow_controller(project_id)),
    "validator_runner": ("Validator Runner", "validation", lambda store, project_id: store.load_boba_validator_runner(project_id)),
    "output_quality_reviewer": ("Output Quality Reviewer", "quality", lambda store, project_id: store.load_boba_output_quality_reviewer(project_id)),
    "artifact_inspector": ("Artifact Inspector", "artifacts", lambda store, project_id: store.load_boba_artifact_inspector(project_id)),
    "report_reader": ("Report Reader", "reports", lambda store, project_id: store.load_boba_report_reader(project_id)),
    "tool_recovery": ("Tool Recovery Brain", "recovery", lambda store, project_id: store.load_boba_tool_recovery(project_id)),
    "autopilot_controller": ("Autopilot Controller", "autopilot", lambda store, project_id: store.load_boba_autopilot_controller(project_id)),
    "integration_layer": ("Integration Layer", "integration", lambda store, project_id: store.load_boba_integration_layer(project_id)),
    "final_decision_bus": ("Final Decision Bus", "final_decision", lambda store, project_id: store.load_boba_final_decision_bus(project_id)),
}


class BobaReviewUiV1:
    """Build bounded review projections from canonical BOBA source records."""

    def __init__(self, store: BobaMemoryStore, integration: BobaIntegration) -> None:
        self.store = store
        self.integration = integration

    def build_review_ui_registry(self, project_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        views = build_fixed_review_view_registry()
        actions = build_fixed_review_action_registry()
        payload = {"views": [item.model_dump(mode="json") for item in views.values()], "actions": [item.model_dump(mode="json") for item in actions.values()]}
        registry = BobaReviewUiRegistrySnapshotV1(
            registry_snapshot_id=_stable_id("review_registry", "v1", _digest(payload)),
            view_descriptor_ids=list(views),
            action_descriptor_ids=list(actions),
            available_review_modes=[item.review_mode for item in views.values() if item.availability == "available"],
            unavailable_review_modes=[item.review_mode for item in views.values() if item.availability != "available"],
            available_action_ids=[item.action_descriptor_id for item in actions.values() if item.allowed_in_v1 and item.availability == "available"],
            unavailable_action_ids=[item.action_descriptor_id for item in actions.values() if not item.allowed_in_v1 or item.availability != "available"],
            registry_digest=_digest(payload),
            limitations=["The registry is fixed source code; browser requests cannot add modules, operations, URLs, or commands."],
        )
        self.store.save_boba_review_ui_registry(project_id, registry.registry_snapshot_id, registry.model_dump(mode="json"))
        return {"registry_snapshot": registry.model_dump(mode="json"), "views": [item.model_dump(mode="json") for item in views.values()], "actions": [item.model_dump(mode="json") for item in actions.values()]}

    def inspect_review_ui_registry(self, project_id: str) -> dict[str, Any]:
        return self.build_review_ui_registry(project_id)

    def create_review_session(
        self,
        project_id: str,
        *,
        reviewer_context_id: str,
        review_mode: ReviewMode = "project_overview",
        target_type: ReviewTargetType = "project",
        target_id: str = "",
        expires_in_seconds: int = 3_600,
    ) -> BobaReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(reviewer_context_id, "reviewer context id")
        session_id = f"review_session_{uuid4().hex}"
        now = datetime.now(UTC)
        session_payload = {"session_id": session_id, "project_id": project_id, "reviewer_context_id": reviewer_context_id, "review_mode": review_mode, "target_type": target_type, "target_id": target_id}
        session = BobaReviewSessionV1(
            review_session_id=session_id,
            project_id=project_id,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=max(60, min(expires_in_seconds, 28_800)))).isoformat(),
            reviewer_context_id=reviewer_context_id,
            selected_review_mode=review_mode,
            selected_target_type=target_type,
            selected_target_id=_safe_text(target_id, 180),
            session_digest=_digest(session_payload),
            limitations=["Review sessions hold only UI state; they are not approvals or source decisions."],
        )
        self.store.save_boba_review_ui_session(project_id, session_id, session.model_dump(mode="json"))
        return session

    def get_review_session(self, project_id: str, session_id: str) -> BobaReviewSessionV1:
        _safe_id(session_id, "review session id")
        raw = self.store.load_boba_review_ui_session(project_id, session_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA Review UI session is unavailable.")
        session = BobaReviewSessionV1.model_validate(raw)
        if _parse_time(session.expires_at) is None or _parse_time(session.expires_at) <= datetime.now(UTC):
            raise ValidationError("BOBA Review UI session has expired.")
        return session

    def update_review_preferences(self, project_id: str, session_id: str, updates: Mapping[str, Any]) -> BobaReviewSessionV1:
        session = self.get_review_session(project_id, session_id)
        allowed = {"selected_review_mode", "selected_target_type", "selected_target_id", "selected_clip_id", "selected_output_id", "selected_attempt_id", "comparison_target_ids", "active_filter_id", "active_sort", "active_tab", "evidence_drawer_open", "event_drawer_open", "compact_mode", "read_queue_item_ids", "acknowledged_notification_ids"}
        unsafe = set(updates) - allowed
        if unsafe:
            raise ValidationError("Review session update contains unsupported fields.")
        payload = session.model_dump(mode="json")
        payload.update(_safe_payload(dict(updates)))
        payload["updated_at"] = now_iso()
        payload["session_digest"] = _digest({key: value for key, value in payload.items() if key != "session_digest"})
        updated = BobaReviewSessionV1.model_validate(payload)
        self.store.save_boba_review_ui_session(project_id, session_id, updated.model_dump(mode="json"))
        return updated

    def build_review_queue(
        self,
        project_id: str,
        *,
        category: str | None = None,
        include_historical: bool = False,
        sort: str = "priority",
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        cards = self._source_cards(project_id)
        items = [self._queue_item(project_id, card) for card in cards]
        if not include_historical:
            items = [item for item in items if not item.historical]
        if category and category != "all":
            items = [item for item in items if item.display_category == category]
        if sort == "updated":
            items.sort(key=lambda item: (item.updated_at, item.queue_item_id), reverse=True)
        else:
            items.sort(key=lambda item: (item.priority, item.queue_sort_key, item.queue_item_id))
        safe_offset = max(0, offset)
        safe_limit = max(1, min(limit, 100))
        return {"schema_version": "boba_review_ui_queue_v1", "project_id": project_id, "total": len(items), "offset": safe_offset, "limit": safe_limit, "items": [item.model_dump(mode="json") for item in items[safe_offset : safe_offset + safe_limit]]}

    def inspect_review_queue(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.build_review_queue(project_id, **kwargs)

    def inspect_review_target(self, project_id: str, review_target_id: str) -> dict[str, Any]:
        _safe_id(review_target_id, "review target id")
        cards = self._source_cards(project_id)
        if review_target_id == f"review_target_project_{project_id}":
            target = self._project_target(project_id, cards)
            return {"target": target.model_dump(mode="json"), "source_cards": [card.model_dump(mode="json") for card in cards]}
        for card in cards:
            target = self._target_from_card(project_id, card, cards)
            if target.review_target_id == review_target_id:
                return {"target": target.model_dump(mode="json"), "source_cards": [card.model_dump(mode="json") for card in cards if card.source_module_id == card.source_module_id]}
        raise ValidationError("BOBA Review UI target is unavailable or belongs to another project.")

    def build_review_snapshot(self, project_id: str, session_id: str, review_target_id: str | None = None) -> dict[str, Any]:
        session = self.get_review_session(project_id, session_id)
        cards = self._source_cards(project_id)
        target_id = review_target_id or session.selected_target_id or f"review_target_project_{project_id}"
        target_payload = self.inspect_review_target(project_id, target_id)
        target = BobaReviewTargetV1.model_validate(target_payload["target"])
        cards_for_target = [BobaReviewSourceCardV1.model_validate(item) for item in target_payload["source_cards"]]
        events = self.inspect_review_events(project_id, limit=100)["events"]
        snapshot_payload = {"project": target.project_snapshot_digest, "target": target.target_digest, "sources": {card.source_record_id: card.source_record_digest for card in cards_for_target}, "session": session.review_session_id}
        snapshot = BobaReviewSnapshotV1(
            review_snapshot_id=f"review_snapshot_{uuid4().hex}",
            review_session_id=session.review_session_id,
            review_target_id=target.review_target_id,
            project_id=project_id,
            project_snapshot_digest=target.project_snapshot_digest,
            workflow_revision=target.workflow_revision,
            target_digest=target.target_digest,
            source_record_references=[{"module_id": card.source_module_id, "record_id": card.source_record_id} for card in cards_for_target],
            source_record_digests={card.source_record_id: card.source_record_digest for card in cards_for_target},
            section_ids=["overview", "workflow", "rights", "safety", "artifacts", "validation", "quality", "final_decision", "timeline"],
            source_card_ids=[card.source_card_id for card in cards_for_target],
            timeline_entry_ids=[str(item.get("ui_event_id") or "") for item in events if item.get("ui_event_id")],
            available_action_descriptor_ids=self._available_actions(target),
            rights_status=self._status_for(cards_for_target, "rights_permission_gate"),
            safety_status=self._status_for(cards_for_target, "safety_gate"),
            approval_status="unavailable",
            workflow_status=self._status_for(cards_for_target, "workflow_controller"),
            artifact_status=self._status_for(cards_for_target, "artifact_inspector"),
            validation_status=self._status_for(cards_for_target, "validator_runner"),
            quality_status=self._status_for(cards_for_target, "output_quality_reviewer"),
            recovery_status=self._status_for(cards_for_target, "tool_recovery"),
            final_decision_status=self._status_for(cards_for_target, "final_decision_bus"),
            missing_evidence_count=sum(1 for card in cards_for_target if card.original_status in {"unknown", "unavailable"}),
            conflict_count=sum(1 for card in cards_for_target if "conflict" in card.bounded_summary.lower()),
            warning_count=sum(len(card.warnings) for card in cards_for_target),
            limitation_count=sum(len(card.limitations) for card in cards_for_target),
            human_action_required=any(card.human_review_required for card in cards_for_target),
            current=target.current,
            stale=target.stale,
            snapshot_digest=_digest(snapshot_payload),
            limitations=["Snapshot status is display-only and links to canonical owner records."],
        )
        self.store.save_boba_review_ui_snapshot(project_id, snapshot.review_snapshot_id, snapshot.model_dump(mode="json"))
        return {"snapshot": snapshot.model_dump(mode="json"), "target": target.model_dump(mode="json"), "source_cards": [card.model_dump(mode="json") for card in cards_for_target], "sections": [section.model_dump(mode="json") for section in self._sections(snapshot, cards_for_target)]}

    def refresh_review_snapshot(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        raw = self.store.load_boba_review_ui_snapshot(project_id, snapshot_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA Review UI snapshot is unavailable.")
        snapshot = BobaReviewSnapshotV1.model_validate(raw)
        return self.build_review_snapshot(project_id, snapshot.review_session_id, snapshot.review_target_id)

    def create_review_action_request(
        self,
        project_id: str,
        *,
        review_session_id: str,
        review_snapshot_id: str,
        action_descriptor_id: str,
        decision_value: str | None,
        reason: str,
        confirmation_context_digest: str,
        idempotency_key: str,
        confirmed: bool,
    ) -> BobaReviewActionRequestV1:
        session = self.get_review_session(project_id, review_session_id)
        snapshot = self._snapshot(project_id, review_snapshot_id)
        descriptor = self._action_descriptor(action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            raise ValidationError("This BOBA Review UI action is unavailable in V1.")
        target = BobaReviewTargetV1.model_validate(self.inspect_review_target(project_id, snapshot.review_target_id)["target"])
        if descriptor.supported_target_types and target.target_type not in descriptor.supported_target_types:
            raise ValidationError("The action is unavailable for this exact review target.")
        if descriptor.requires_reason and not reason.strip():
            raise ValidationError("This review action requires a reason.")
        if len(reason) > descriptor.maximum_reason_length:
            raise ValidationError("Review action reason exceeds the allowed length.")
        if descriptor.allowed_decision_values and decision_value not in descriptor.allowed_decision_values:
            raise ValidationError("Unsupported decision value for this fixed review action.")
        if not confirmed:
            raise ValidationError("Explicit review action confirmation is required.")
        if confirmation_context_digest != _digest({"snapshot": snapshot.snapshot_digest, "action": descriptor.action_descriptor_id, "target": target.target_digest}):
            raise ValidationError("Review action confirmation does not match the current target.")
        _safe_id(idempotency_key, "idempotency key")
        request = BobaReviewActionRequestV1(
            review_action_request_id=f"review_action_{uuid4().hex}",
            review_session_id=session.review_session_id,
            review_snapshot_id=snapshot.review_snapshot_id,
            project_id=project_id,
            reviewer_context_id=session.reviewer_context_id,
            action_descriptor_id=descriptor.action_descriptor_id,
            owning_module_id=descriptor.owning_module_id,
            owning_operation_id=descriptor.owning_operation_id,
            review_target_id=target.review_target_id,
            target_type=target.target_type,
            target_id=target.target_id,
            workflow_run_id=target.workflow_run_id,
            stage_instance_id=target.stage_instance_id,
            clip_id=target.clip_id,
            output_id=target.output_id,
            attempt_id=target.attempt_id,
            decision_value=decision_value,
            bounded_reason=_safe_text(reason, descriptor.maximum_reason_length),
            expected_project_snapshot_digest=snapshot.project_snapshot_digest,
            expected_workflow_revision=snapshot.workflow_revision,
            expected_target_digest=snapshot.target_digest,
            expected_source_record_digests=snapshot.source_record_digests,
            confirmation_context_digest=confirmation_context_digest,
            idempotency_key=idempotency_key,
            expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            confirmed=True,
        )
        self.store.save_boba_review_ui_action(project_id, request.review_action_request_id, request.model_dump(mode="json"))
        return request

    def validate_review_action_request(self, project_id: str, action_request_id: str) -> dict[str, Any]:
        request = self._action_request(project_id, action_request_id)
        if _parse_time(request.expires_at) is None or _parse_time(request.expires_at) <= datetime.now(UTC):
            return {"valid": False, "code": "expired_snapshot", "message": "The review action expired before submission."}
        current_target = BobaReviewTargetV1.model_validate(self.inspect_review_target(project_id, request.review_target_id)["target"])
        if current_target.project_snapshot_digest != request.expected_project_snapshot_digest:
            return {"valid": False, "code": "stale_project_snapshot", "message": "The project changed while this review was open."}
        if current_target.workflow_revision != request.expected_workflow_revision:
            return {"valid": False, "code": "workflow_revision_mismatch", "message": "The workflow revision changed while this review was open."}
        if current_target.target_digest != request.expected_target_digest:
            return {"valid": False, "code": "target_digest_mismatch", "message": "The review target changed while this review was open."}
        return {"valid": True, "code": "current", "message": "Exact review target remains current."}

    async def submit_review_action_to_owner(self, project_id: str, action_request_id: str) -> BobaReviewActionReceiptV1:
        request = self._action_request(project_id, action_request_id)
        existing = self.store.load_boba_review_ui_receipt_for_action(project_id, action_request_id)
        if isinstance(existing, Mapping):
            receipt = BobaReviewActionReceiptV1.model_validate(existing)
            receipt.duplicate_request_reused = True
            return receipt
        validation = self.validate_review_action_request(project_id, action_request_id)
        if not validation["valid"]:
            receipt = BobaReviewActionReceiptV1(
                action_receipt_id=f"review_receipt_{uuid4().hex}", review_action_request_id=request.review_action_request_id, project_id=project_id,
                owning_module_id=request.owning_module_id, owning_operation_id=request.owning_operation_id,
                completed_at=now_iso(), canonical_status="rejected_stale_state", stale_state_rejected=True,
                error_code=str(validation["code"]), bounded_error_message=str(validation["message"]),
            )
            self.store.save_boba_review_ui_receipt(project_id, receipt.action_receipt_id, receipt.model_dump(mode="json"))
            return receipt
        if request.action_descriptor_id == "review_action_acknowledge_notification_v1":
            session = self.get_review_session(project_id, request.review_session_id)
            notification_id = request.target_id
            if notification_id not in session.acknowledged_notification_ids:
                self.update_review_preferences(project_id, session.review_session_id, {"acknowledged_notification_ids": [*session.acknowledged_notification_ids, notification_id]})
            receipt = BobaReviewActionReceiptV1(
                action_receipt_id=f"review_receipt_{uuid4().hex}", review_action_request_id=request.review_action_request_id, project_id=project_id,
                owning_module_id="review_ui", owning_operation_id="acknowledge_notification", completed_at=now_iso(),
                canonical_request_id=request.review_action_request_id, canonical_record_id=notification_id,
                canonical_record_digest=_digest({"notification_id": notification_id, "session_id": session.review_session_id}),
                canonical_status="acknowledged", accepted_by_owner=True, authoritative_state_changed=False,
                canonical_refresh_required=True, limitations=["Acknowledgement changes only review-session metadata; the source issue remains visible until its owner resolves it."],
            )
            self.store.save_boba_review_ui_receipt(project_id, receipt.action_receipt_id, receipt.model_dump(mode="json"))
            return receipt
        raise ValidationError("No exact canonical owner route is available for this V1 action.")

    def inspect_review_action_receipt(self, project_id: str, action_request_id: str) -> dict[str, Any]:
        request = self._action_request(project_id, action_request_id)
        receipt = self.store.load_boba_review_ui_receipt_for_action(project_id, action_request_id)
        return {"request": request.model_dump(mode="json"), "receipt": _safe_payload(receipt) if receipt else None}

    def inspect_review_timeline(self, project_id: str, *, limit: int = 100) -> dict[str, Any]:
        events = self.inspect_review_events(project_id, limit=limit)["events"]
        entries = [self._timeline_entry(BobaReviewUiEventV1.model_validate(event)) for event in events]
        return {"schema_version": "boba_review_ui_timeline_v1", "project_id": project_id, "entries": [item.model_dump(mode="json") for item in entries]}

    def inspect_review_events(self, project_id: str, *, after_sequence: int = 0, limit: int = 100) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        events: list[BobaReviewUiEventV1] = []
        for module_id, (_, _, loader) in _SOURCE_LOADERS.items():
            try:
                payload = _as_mapping(loader(self.store, project_id))
            except ValidationError:
                payload = {}
            for event in self._event_rows(module_id, payload):
                if event.source_sequence is None or event.source_sequence > after_sequence:
                    events.append(event)
        events.sort(key=lambda item: (item.created_at or "", item.source_module_id, item.source_sequence or 0, item.ui_event_id))
        bounded = events[-max(1, min(limit, _MAX_EVENTS)) :]
        return {"schema_version": "boba_review_ui_events_v1", "project_id": project_id, "events": [item.model_dump(mode="json") for item in bounded], "has_more": len(events) > len(bounded)}

    def acknowledge_review_notification(self, project_id: str, session_id: str, notification_id: str) -> BobaReviewSessionV1:
        _safe_id(notification_id, "notification id")
        session = self.get_review_session(project_id, session_id)
        return self.update_review_preferences(project_id, session_id, {"acknowledged_notification_ids": [*session.acknowledged_notification_ids, notification_id]})

    def export_review_ui(self, project_id: str, session_id: str | None = None) -> dict[str, Any]:
        cards = self._source_cards(project_id)
        queue = self.build_review_queue(project_id, limit=100)
        payload: dict[str, Any] = {"schema_version": "boba_review_ui_export_v1", "project_id": project_id, "exported_at": now_iso(), "source_cards": [card.model_dump(mode="json") for card in cards], "queue": queue, "timeline": self.inspect_review_timeline(project_id, limit=50), "privacy": {"private_paths_excluded": True, "raw_media_excluded": True, "raw_reports_excluded": True, "raw_logs_excluded": True, "secrets_excluded": True, "source_media_modified": False, "accepted_outputs_modified": False, "upload_used": False, "publication_used": False}}
        if session_id:
            payload["session"] = self.get_review_session(project_id, session_id).model_dump(mode="json")
        return _safe_payload(payload)

    def reset_review_ui_metadata(self, project_id: str, session_id: str | None = None) -> dict[str, Any]:
        if session_id:
            _safe_id(session_id, "review session id")
            removed = self.store.delete_boba_review_ui_session(project_id, session_id)
            return {"project_id": project_id, "session_removed": removed, "source_records_preserved": True, "workflow_history_preserved": True, "validation_history_preserved": True, "quality_history_preserved": True, "artifact_history_preserved": True, "final_decision_history_preserved": True}
        return self.store.reset_boba_review_ui_metadata(project_id)

    def build_review_ui(self, project_id: str) -> dict[str, Any]:
        registry = self.build_review_ui_registry(project_id)
        cards = self._source_cards(project_id)
        queue = self.build_review_queue(project_id, limit=100)
        events = self.inspect_review_events(project_id, limit=100)
        notifications = self._notifications(project_id, cards)
        summary = self._summary(queue["items"], events["events"])
        signal = BobaReviewUiSignalUsageV1(
            workflow_controller_used=any(card.source_module_id == "workflow_controller" and card.current for card in cards),
            rights_gate_used=any(card.source_module_id == "rights_permission_gate" and card.current for card in cards),
            safety_gate_used=any(card.source_module_id == "safety_gate" and card.current for card in cards),
            validator_runner_used=any(card.source_module_id == "validator_runner" and card.current for card in cards),
            output_quality_reviewer_used=any(card.source_module_id == "output_quality_reviewer" and card.current for card in cards),
            artifact_inspector_used=any(card.source_module_id == "artifact_inspector" and card.current for card in cards),
            report_reader_used=any(card.source_module_id == "report_reader" and card.current for card in cards),
            autopilot_used=any(card.source_module_id == "autopilot_controller" and card.current for card in cards),
            final_decision_bus_used=any(card.source_module_id == "final_decision_bus" and card.current for card in cards),
            integration_layer_used=any(card.source_module_id == "integration_layer" and card.current for card in cards),
            unavailable_signals=[card.source_module_id for card in cards if not card.current],
        )
        result = BobaReviewUiSetV1(
            project_id=project_id,
            registry_snapshots=[BobaReviewUiRegistrySnapshotV1.model_validate(registry["registry_snapshot"])],
            view_descriptors=[BobaReviewViewDescriptorV1.model_validate(item) for item in registry["views"]],
            action_descriptors=[BobaReviewActionDescriptorV1.model_validate(item) for item in registry["actions"]],
            review_queue_items=[BobaReviewQueueItemV1.model_validate(item) for item in queue["items"]],
            source_cards=cards,
            notifications=notifications,
            events=[BobaReviewUiEventV1.model_validate(item) for item in events["events"]],
            ui_summary=summary,
            signal_usage=signal,
            limitations=["Review UI V1 is a presentation and routing layer. It does not create authoritative decisions."],
        )
        self.store.save_boba_review_ui(project_id, result.model_dump(mode="json"))
        return result.model_dump(mode="json")

    def _source_cards(self, project_id: str) -> list[BobaReviewSourceCardV1]:
        cards: list[BobaReviewSourceCardV1] = []
        for module_id, (title, domain, loader) in _SOURCE_LOADERS.items():
            try:
                payload = _as_mapping(loader(self.store, project_id))
            except ValidationError:
                payload = {}
            if not payload:
                cards.append(BobaReviewSourceCardV1(
                    source_card_id=_stable_id("review_card", project_id, module_id, "unavailable"), source_module_id=module_id,
                    authority_domain=domain, source_record_id=_stable_id("unavailable", project_id, module_id), source_record_digest=_digest({"module": module_id, "state": "unavailable"}),
                    original_status="unavailable", display_category="unavailable", title=title,
                    bounded_summary="No canonical record is currently available for this project.",
                    easy_explanation=f"{title} has not supplied a current review record.", current=False, authoritative=True,
                    details_route=f"/api/v1/boba/projects/{project_id}/{module_id.replace('_', '-')}", limitations=["Unavailable source records are not treated as passed."],
                ))
                continue
            safe = _as_mapping(_safe_payload(payload))
            status = _source_status(safe)
            stale = _is_stale(safe)
            blocking = _is_blocking(safe, status)
            human = _has_human_review(safe)
            category: QueueCategory = "blocked" if blocking else "human_review_required" if human else "ready_for_review" if status not in {"unknown", "unavailable"} else "awaiting_evidence"
            source_id = _record_id(safe, module_id)
            summary = _first_text(safe, "summary", "reason", "message", "description", "result") or f"Canonical {title} record is available."
            cards.append(BobaReviewSourceCardV1(
                source_card_id=_stable_id("review_card", project_id, module_id, source_id), source_module_id=module_id,
                authority_domain=domain, source_record_id=source_id, source_record_digest=_digest(safe),
                source_schema_id=_safe_text(safe.get("schema_version") or safe.get("schema_id") or "unknown", 180), source_schema_version=_safe_text(safe.get("version") or "1", 80),
                original_status=status, original_decision=_source_decision(safe), display_category=category, title=title,
                bounded_summary=summary, easy_explanation=f"{title} reports {status}.", current=not stale,
                stale=stale, expired=bool(safe.get("expired")), invalidated=bool(safe.get("invalidated")), superseded=bool(safe.get("superseded")),
                authoritative=True, advisory_only=False, human_review_required=human, blocking=blocking,
                details_route=f"/api/v1/boba/projects/{project_id}/{module_id.replace('_', '-')}", warnings=[_safe_text(item, 300) for item in safe.get("warnings", []) if isinstance(item, str)][:16], limitations=[_safe_text(item, 300) for item in safe.get("limitations", []) if isinstance(item, str)][:16],
            ))
        return cards

    def _queue_item(self, project_id: str, card: BobaReviewSourceCardV1) -> BobaReviewQueueItemV1:
        target = self._target_from_card(project_id, card, [card])
        priority, category = self._priority(card)
        return BobaReviewQueueItemV1(
            queue_item_id=_stable_id("review_queue", project_id, card.source_module_id, card.source_record_digest), project_id=project_id,
            target_type=target.target_type, target_id=target.review_target_id, review_mode=self._mode_for_card(card), priority=priority,
            display_category=category, title=card.title, bounded_summary=card.bounded_summary, source_module_ids=[card.source_module_id], source_record_ids=[card.source_record_id], source_record_digests={card.source_record_id: card.source_record_digest}, primary_reason=card.original_status,
            blocker_count=1 if card.blocking else 0, warning_count=len(card.warnings), missing_evidence_count=1 if not card.current or card.original_status in {"unknown", "unavailable"} else 0,
            conflict_count=1 if "conflict" in card.bounded_summary.lower() else 0, human_action_required=card.human_review_required,
            available_action_descriptor_ids=[], current=card.current, stale=card.stale, historical=card.superseded,
            queue_sort_key=f"{priority:03d}:{card.source_module_id}:{card.source_record_id}", warnings=card.warnings, limitations=card.limitations,
        )

    def _target_from_card(self, project_id: str, card: BobaReviewSourceCardV1, all_cards: list[BobaReviewSourceCardV1]) -> BobaReviewTargetV1:
        target_type: ReviewTargetType = "project"
        if card.source_module_id == "workflow_controller": target_type = "workflow_stage"
        elif card.source_module_id == "output_quality_reviewer": target_type = "quality_review"
        elif card.source_module_id == "artifact_inspector": target_type = "artifact"
        elif card.source_module_id == "validator_runner": target_type = "validation_run"
        elif card.source_module_id == "tool_recovery": target_type = "recovery_run"
        elif card.source_module_id == "final_decision_bus": target_type = "final_decision"
        source_digests = {item.source_record_id: item.source_record_digest for item in all_cards}
        project_digest = _digest(source_digests)
        return BobaReviewTargetV1(
            review_target_id=_stable_id("review_target", project_id, card.source_module_id, card.source_record_id), project_id=project_id,
            target_type=target_type, target_id=card.source_record_id, project_snapshot_digest=project_digest,
            workflow_revision=self._workflow_revision(project_id), target_digest=card.source_record_digest,
            current=card.current, stale=card.stale, historical=card.superseded, source_module_ids=[card.source_module_id], source_record_ids=[card.source_record_id], warnings=card.warnings, limitations=card.limitations,
        )

    def _project_target(self, project_id: str, cards: list[BobaReviewSourceCardV1]) -> BobaReviewTargetV1:
        digests = {card.source_record_id: card.source_record_digest for card in cards}
        digest = _digest(digests)
        return BobaReviewTargetV1(review_target_id=f"review_target_project_{project_id}", project_id=project_id, target_type="project", target_id=project_id, project_snapshot_digest=digest, workflow_revision=self._workflow_revision(project_id), target_digest=digest, current=any(card.current for card in cards), stale=all(card.stale or not card.current for card in cards), source_module_ids=[card.source_module_id for card in cards], source_record_ids=[card.source_record_id for card in cards], limitations=["Project target aggregates canonical references; it does not merge or override source decisions."])

    def _workflow_revision(self, project_id: str) -> int:
        payload = _as_mapping(self.store.load_boba_workflow_controller(project_id))
        for key in ("revision", "workflow_revision"):
            value = payload.get(key)
            if isinstance(value, int) and value >= 0:
                return value
        return 0

    @staticmethod
    def _status_for(cards: list[BobaReviewSourceCardV1], module_id: str) -> str:
        return next((card.original_status for card in cards if card.source_module_id == module_id), "unavailable")

    @staticmethod
    def _mode_for_card(card: BobaReviewSourceCardV1) -> ReviewMode:
        return {"workflow_controller": "workflow_review", "validator_runner": "validation_review", "output_quality_reviewer": "quality_review", "artifact_inspector": "artifact_review", "tool_recovery": "recovery_review", "final_decision_bus": "final_decision_review"}.get(card.source_module_id, "project_overview")

    @staticmethod
    def _priority(card: BobaReviewSourceCardV1) -> tuple[int, QueueCategory]:
        if card.source_module_id in {"rights_permission_gate", "safety_gate"} and card.blocking: return 10, "critical_attention"
        if card.source_module_id == "artifact_inspector" and card.blocking: return 20, "critical_attention"
        if card.source_module_id == "workflow_controller" and card.blocking: return 30, "blocked"
        if card.human_review_required: return 40 if card.source_module_id not in {"output_quality_reviewer", "final_decision_bus"} else 50 if card.source_module_id == "output_quality_reviewer" else 60, "human_review_required"
        if card.source_module_id == "validator_runner" and (card.blocking or not card.current): return 70, "awaiting_evidence"
        if card.source_module_id == "artifact_inspector" and (card.stale or not card.current): return 80, "awaiting_evidence"
        if card.source_module_id == "tool_recovery": return 90, "ready_for_review"
        if not card.current: return 180, "unavailable"
        return 200, "informational"

    def _available_actions(self, target: BobaReviewTargetV1) -> list[str]:
        actions = build_fixed_review_action_registry()
        return [item.action_descriptor_id for item in actions.values() if item.allowed_in_v1 and item.availability == "available" and target.target_type in item.supported_target_types]

    def _action_descriptor(self, action_descriptor_id: str) -> BobaReviewActionDescriptorV1:
        _safe_id(action_descriptor_id, "action descriptor id")
        descriptor = build_fixed_review_action_registry().get(action_descriptor_id)
        if descriptor is None: raise ValidationError("Unknown fixed BOBA Review UI action descriptor.")
        return descriptor

    def _snapshot(self, project_id: str, snapshot_id: str) -> BobaReviewSnapshotV1:
        _safe_id(snapshot_id, "review snapshot id")
        raw = self.store.load_boba_review_ui_snapshot(project_id, snapshot_id)
        if not isinstance(raw, Mapping): raise ValidationError("BOBA Review UI snapshot is unavailable.")
        return BobaReviewSnapshotV1.model_validate(raw)

    def _action_request(self, project_id: str, request_id: str) -> BobaReviewActionRequestV1:
        _safe_id(request_id, "review action request id")
        raw = self.store.load_boba_review_ui_action(project_id, request_id)
        if not isinstance(raw, Mapping): raise ValidationError("BOBA Review UI action request is unavailable.")
        return BobaReviewActionRequestV1.model_validate(raw)

    def _sections(self, snapshot: BobaReviewSnapshotV1, cards: list[BobaReviewSourceCardV1]) -> list[BobaReviewSectionV1]:
        groups = [("overview", "Overview"), ("workflow", "Workflow"), ("rights", "Rights"), ("safety", "Safety"), ("artifacts", "Artifacts"), ("validation", "Technical validation"), ("quality", "Output quality"), ("final_decision", "Final Decision Bus"), ("timeline", "Timeline")]
        return [BobaReviewSectionV1(review_section_id=_stable_id("review_section", snapshot.review_snapshot_id, kind), review_snapshot_id=snapshot.review_snapshot_id, section_type=kind, title=title, source_card_ids=[card.source_card_id for card in cards if card.authority_domain == kind or kind == "overview"], empty=not any(card.authority_domain == kind for card in cards) and kind != "overview", bounded_empty_message="No canonical source record is available.") for kind, title in groups]

    def _event_rows(self, module_id: str, payload: Mapping[str, Any]) -> list[BobaReviewUiEventV1]:
        rows: list[Mapping[str, Any]] = []
        for key in ("events", "workflow_events", "validation_events", "report_events", "artifact_events"):
            value = payload.get(key)
            if isinstance(value, list): rows.extend(item for item in value[-_MAX_EVENTS:] if isinstance(item, Mapping))
        source_id = _record_id(payload, module_id)
        events: list[BobaReviewUiEventV1] = []
        for row in rows:
            safe = _as_mapping(_safe_payload(row))
            event_id = _first_text(safe, "event_id", "source_event_id", "id") or _stable_id("review_event", module_id, _digest(safe))
            sequence = safe.get("sequence") if isinstance(safe.get("sequence"), int) else None
            progress_current = safe.get("progress_current") if isinstance(safe.get("progress_current"), int) else None
            progress_total = safe.get("progress_total") if isinstance(safe.get("progress_total"), int) else None
            percent = (progress_current / progress_total * 100) if progress_current is not None and progress_total and progress_total > 0 else None
            events.append(BobaReviewUiEventV1(ui_event_id=_stable_id("review_event", module_id, event_id), project_id=str(payload.get("project_id") or ""), source_module_id=module_id, source_event_id=event_id, source_sequence=sequence, created_at=_first_text(safe, "created_at", "occurred_at", "timestamp") or None, event_type=_first_text(safe, "event_type", "type") or "canonical_event", severity=_first_text(safe, "severity") or "informational", technical_message=_first_text(safe, "technical_message", "message", "summary"), easy_message=_first_text(safe, "easy_message", "summary", "message"), confirmed_fact=_first_text(safe, "confirmed_fact"), assessment=_first_text(safe, "assessment"), progress_current=progress_current, progress_total=progress_total, progress_percent=percent, requires_attention=bool(safe.get("requires_attention")), canonical=True, replayed=bool(safe.get("replayed"))))
        return events

    @staticmethod
    def _timeline_entry(event: BobaReviewUiEventV1) -> BobaReviewTimelineEntryV1:
        return BobaReviewTimelineEntryV1(timeline_entry_id=_stable_id("review_timeline", event.ui_event_id), source_module_id=event.source_module_id, source_record_id=event.source_event_id or event.ui_event_id, source_event_id=event.source_event_id, event_type=event.event_type, occurred_at=event.created_at, timestamp_precision="exact" if event.created_at else "unknown", sequence=event.source_sequence, confirmed_order=event.source_sequence is not None, title=event.event_type.replace("_", " ").title(), bounded_summary=event.easy_message, confirmed_fact=event.confirmed_fact, source_assessment=event.assessment, review_ui_explanation=event.easy_message, severity=event.severity, current=not event.replayed, historical=event.replayed)

    def _notifications(self, project_id: str, cards: list[BobaReviewSourceCardV1]) -> list[BobaReviewNotificationV1]:
        notifications: list[BobaReviewNotificationV1] = []
        for card in cards:
            if not (card.blocking or card.human_review_required or card.stale): continue
            target = self._target_from_card(project_id, card, [card])
            notifications.append(BobaReviewNotificationV1(notification_id=_stable_id("review_notification", project_id, card.source_card_id, card.original_status), project_id=project_id, review_target_id=target.review_target_id, source_module_id=card.source_module_id, source_record_id=card.source_record_id, notification_type="blocking" if card.blocking else "human_review_required" if card.human_review_required else "stale", severity="critical" if card.display_category == "critical_attention" else "warning", title=card.title, bounded_message=card.bounded_summary, requires_attention=True, human_action_required=card.human_review_required, current=card.current))
        return notifications[:64]

    @staticmethod
    def _summary(queue_rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> BobaReviewUiSummaryV1:
        categories = [str(item.get("display_category") or "") for item in queue_rows]
        return BobaReviewUiSummaryV1(total_queue_item_count=len(queue_rows), critical_attention_count=categories.count("critical_attention"), blocked_count=categories.count("blocked"), human_review_required_count=categories.count("human_review_required"), ready_for_review_count=categories.count("ready_for_review"), awaiting_evidence_count=categories.count("awaiting_evidence"), latest_canonical_event_at=max((str(item.get("created_at") or "") for item in events), default="") or None, event_stream_connected=False, safest_next_review_action="Review the highest-priority canonical source record.")

"""Read-only BOBA Review UI projections and constrained action routing.

The review UI is deliberately a presentation layer.  It stores sessions,
preferences, and canonical-action receipts, but it never becomes the owner of
rights, safety, validation, quality, workflow, or final-decision state.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from pydantic import Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.memory import sanitize_memory_payload
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import NotFoundError, ValidationError

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


def _has_protection_incident(payload: Mapping[str, Any]) -> bool:
    """Detect source-media or accepted-output protection incidents."""
    for key in (
        "source_media_modified",
        "accepted_outputs_modified",
        "source_media_protection_incident",
        "accepted_output_protection_incident",
        "protected_asset_incident",
    ):
        if bool(payload.get(key)):
            return True
    incidents = payload.get("incidents")
    if isinstance(incidents, list):
        for item in incidents:
            if not isinstance(item, Mapping):
                continue
            kind = _safe_text(item.get("incident_type") or item.get("type"), 160).lower()
            if any(token in kind for token in ("source_media", "accepted_output", "protect")):
                return True
    return False


def _has_recovery_hold(payload: Mapping[str, Any]) -> bool:
    if bool(payload.get("recovery_hold_active")):
        return True
    for key in ("recovery_holds", "workflow_recovery_holds", "holds"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return True
    hold = payload.get("recovery_hold")
    if isinstance(hold, Mapping) and hold:
        return True
    return "recovery_hold" in _safe_text(payload.get("status"), 200).lower()


def _has_conflict(payload: Mapping[str, Any]) -> bool:
    if bool(payload.get("conflict_detected")):
        return True
    for key in ("conflicts", "detected_conflicts", "source_conflicts"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return True
    count = payload.get("conflict_count")
    return isinstance(count, int) and count > 0


def _requires_approval(payload: Mapping[str, Any]) -> bool:
    if bool(payload.get("approval_required") or payload.get("requires_approval")):
        return True
    for key in ("pending_approvals", "approval_requests", "required_approvals"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _active_workflow_run(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the most recently updated canonical workflow run, if present."""
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        return {}
    candidates = [_as_mapping(item) for item in runs if isinstance(item, Mapping)]
    if not candidates:
        return {}
    candidates.sort(
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("workflow_run_id") or ""),
        )
    )
    return candidates[-1]


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
    source_run_id: str | None = None
    source_stage_instance_id: str | None = None
    source_revision: int = Field(default=0, ge=0)
    protection_incident: bool = False
    recovery_hold: bool = False
    approval_required: bool = False
    conflict_detected: bool = False
    priority_tier: int = Field(default=0, ge=0, le=999)
    priority_reason: str = Field(default="", max_length=160)
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
    registry_snapshots: list[BobaReviewUiRegistrySnapshotV1] = Field(
        default_factory=list, max_length=8
    )
    view_descriptors: list[BobaReviewViewDescriptorV1] = Field(default_factory=list, max_length=32)
    action_descriptors: list[BobaReviewActionDescriptorV1] = Field(
        default_factory=list, max_length=32
    )
    review_sessions: list[BobaReviewSessionV1] = Field(default_factory=list, max_length=16)
    review_queue_items: list[BobaReviewQueueItemV1] = Field(
        default_factory=list, max_length=_MAX_QUEUE
    )
    review_snapshots: list[BobaReviewSnapshotV1] = Field(default_factory=list, max_length=32)
    source_cards: list[BobaReviewSourceCardV1] = Field(
        default_factory=list, max_length=_MAX_SOURCE_CARDS
    )
    review_sections: list[BobaReviewSectionV1] = Field(default_factory=list, max_length=32)
    review_actions: list[BobaReviewActionRequestV1] = Field(default_factory=list, max_length=64)
    action_receipts: list[BobaReviewActionReceiptV1] = Field(default_factory=list, max_length=64)
    timeline_entries: list[BobaReviewTimelineEntryV1] = Field(
        default_factory=list, max_length=_MAX_EVENTS
    )
    notifications: list[BobaReviewNotificationV1] = Field(default_factory=list, max_length=64)
    events: list[BobaReviewUiEventV1] = Field(default_factory=list, max_length=_MAX_EVENTS)
    preferences: list[BobaReviewUiPreferencesV1] = Field(default_factory=list, max_length=32)
    ui_summary: BobaReviewUiSummaryV1 = Field(default_factory=BobaReviewUiSummaryV1)
    signal_usage: BobaReviewUiSignalUsageV1 = Field(default_factory=BobaReviewUiSignalUsageV1)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


QUEUE_PRIORITY_TIERS: tuple[tuple[int, str, QueueCategory], ...] = (
    (10, "rights_or_safety_critical_block", "critical_attention"),
    (20, "protected_asset_incident", "critical_attention"),
    (30, "workflow_recovery_hold", "blocked"),
    (40, "required_human_approval", "human_review_required"),
    (50, "output_quality_human_review", "human_review_required"),
    (60, "final_decision_hold_or_conflict", "blocked"),
    (70, "missing_or_failed_technical_validation", "awaiting_evidence"),
    (80, "missing_or_stale_artifact", "awaiting_evidence"),
    (90, "recovery_incident", "ready_for_review"),
    (100, "candidate_or_output_review", "ready_for_review"),
    (110, "completed_informational", "informational"),
    (120, "historical_record", "historical"),
)

_VIEW_SECTION_IDS = (
    "overview",
    "workflow",
    "artifacts",
    "validation",
    "quality",
    "final_decision",
    "timeline",
)

_OPTIONAL_SOURCE_MODULES = (
    "rights_permission_gate",
    "safety_gate",
    "validator_runner",
    "output_quality_reviewer",
    "artifact_inspector",
    "report_reader",
    "final_decision_bus",
)

_EVENT_SOURCE_MODULES = (
    "workflow_controller",
    "validator_runner",
    "artifact_inspector",
    "report_reader",
    "final_decision_bus",
)


def build_fixed_review_view_registry() -> dict[str, BobaReviewViewDescriptorV1]:
    """Return the fixed, source-code-owned review view registry."""
    definitions: tuple[tuple[ReviewMode, str, list[ReviewTargetType], list[str]], ...] = (
        ("project_overview", "Project overview", ["project"], list(_VIEW_SECTION_IDS)),
        (
            "workflow_review",
            "Workflow review",
            ["project", "workflow_stage"],
            ["workflow", "timeline", "events"],
        ),
        (
            "clip_review",
            "Clip review",
            ["candidate_clip", "selected_clip"],
            ["overview", "creative_plan", "captions", "motion"],
        ),
        (
            "output_review",
            "Rendered output review",
            ["rendered_output", "accepted_output"],
            ["preview", "artifacts", "validation", "quality"],
        ),
        (
            "approval_review",
            "Approval review",
            ["approval_request"],
            ["approval", "rights", "safety"],
        ),
        (
            "quality_review",
            "Quality review",
            ["quality_review", "rendered_output"],
            ["quality", "artifacts", "validation"],
        ),
        (
            "validation_review",
            "Validation review",
            ["validation_run", "rendered_output"],
            ["validation", "artifacts"],
        ),
        (
            "artifact_review",
            "Artifact review",
            ["artifact", "rendered_output"],
            ["artifacts", "lineage"],
        ),
        (
            "recovery_review",
            "Recovery review",
            ["recovery_run", "incident"],
            ["recovery", "timeline"],
        ),
        (
            "incident_review",
            "Incident review",
            ["incident"],
            ["warnings", "timeline", "artifacts"],
        ),
        (
            "final_decision_review",
            "Final decision review",
            ["final_decision", "dispatch_envelope"],
            ["final_decision", "rights", "safety", "workflow"],
        ),
        (
            "comparison_review",
            "Comparison review",
            ["rendered_output", "candidate_clip"],
            ["comparison", "quality", "artifacts"],
        ),
        (
            "historical_review",
            "Historical review",
            ["project", "workflow_stage", "rendered_output"],
            ["timeline", "events"],
        ),
    )
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
            optional_source_modules=list(_OPTIONAL_SOURCE_MODULES),
            required_identity_fields=["project_id", "target_id", "target_digest"],
            section_ids=section_ids,
            supported_comparison_types=(
                ["candidate", "output"] if mode == "comparison_review" else []
            ),
            event_source_module_ids=list(_EVENT_SOURCE_MODULES),
        )
    return registry


def build_fixed_review_action_registry() -> dict[str, BobaReviewActionDescriptorV1]:
    """Return the fixed action registry.

    Every entry names an exact owning module and an exact owning operation.  The
    registry is source code: a browser request can never add a module, an
    operation, a URL, a filesystem path, or a command.
    """
    definitions = [
        BobaReviewActionDescriptorV1(
            action_descriptor_id="review_action_acknowledge_notification_v1",
            display_name="Acknowledge review notification",
            action_class="ui_metadata",
            owning_module_id="review_ui",
            owning_operation_id="acknowledge_notification",
            supported_review_modes=[
                "project_overview",
                "workflow_review",
                "incident_review",
                "historical_review",
            ],
            supported_target_types=["project", "incident", "workflow_stage"],
            requires_reason=False,
            requires_confirmation=True,
            requires_current_snapshot=False,
            requires_workflow_revision=False,
            requires_target_digest=False,
            requires_human_identity=False,
            allowed_in_v1=True,
            availability="available",
            limitations=[
                "Acknowledgement changes review-session metadata only.",
                "Acknowledgement does not resolve the canonical source issue.",
            ],
        ),
        BobaReviewActionDescriptorV1(
            action_descriptor_id="review_action_workflow_human_decision_v1",
            display_name="Submit workflow human decision",
            action_class="human_workflow_decision",
            owning_module_id="workflow_controller",
            owning_operation_id="record_human_workflow_decision",
            supported_review_modes=["workflow_review", "approval_review"],
            supported_target_types=["workflow_stage", "approval_request"],
            allowed_decision_values=["approve", "reject", "request_revision"],
            requires_reason=True,
            requires_confirmation=True,
            requires_current_snapshot=True,
            requires_workflow_revision=True,
            requires_target_digest=True,
            requires_approval_context=True,
            requires_human_identity=True,
            allowed_in_v1=True,
            availability="available",
            limitations=[
                "The Workflow Controller owns the decision record and the revision.",
                "The Review UI cannot skip a stage, override Rights, override Safety, "
                "authorise upload, or authorise publication.",
                "Unavailable unless an exact workflow run and revision are bound.",
            ],
        ),
        BobaReviewActionDescriptorV1(
            action_descriptor_id="review_action_output_quality_human_review_v1",
            display_name="Submit output quality decision",
            action_class="human_quality_decision",
            owning_module_id="output_quality_reviewer",
            owning_operation_id="record_boba_output_human_review",
            supported_review_modes=["output_review", "quality_review"],
            supported_target_types=["quality_review", "rendered_output"],
            allowed_decision_values=[
                "accept_for_next_internal_stage",
                "accept_with_disclosed_limitation",
                "reject_output",
                "send_back_to_tool_recovery",
                "send_back_to_repair_planner",
                "request_more_evidence",
            ],
            requires_reason=True,
            requires_approval_context=True,
            requires_safety_context=True,
            availability="unavailable",
            limitations=[
                "The Output Quality Reviewer owns the acceptance decision.",
                "Unavailable until an exact review case identifier is bound.",
            ],
        ),
        BobaReviewActionDescriptorV1(
            action_descriptor_id="review_action_safety_human_review_v1",
            display_name="Submit Safety review",
            action_class="human_safety_decision",
            owning_module_id="safety_gate",
            owning_operation_id="record_human_safety_review",
            supported_review_modes=["approval_review", "incident_review"],
            supported_target_types=["approval_request", "incident"],
            allowed_decision_values=[
                "approve_exact_medium_risk_action",
                "deny_action",
                "request_more_evidence",
                "acknowledge_disclosed_limitation",
                "approve_stricter_budget_reset",
                "select_safer_alternative",
                "keep_project_paused",
            ],
            requires_reason=True,
            requires_approval_context=True,
            requires_safety_context=True,
            availability="unavailable",
            limitations=[
                "The Safety Gate owns every safety decision.",
                "Unavailable until an exact Safety evaluation case is bound.",
                "The Review UI can never weaken or bypass the Safety Gate.",
            ],
        ),
    ]
    registry: dict[str, BobaReviewActionDescriptorV1] = {}
    for descriptor in definitions:
        if descriptor.action_descriptor_id in registry:
            raise ValidationError("Duplicate BOBA Review UI action descriptor.")
        if descriptor.upload_or_publication or descriptor.execution_capable:
            raise ValidationError(
                "Review UI V1 action registry cannot expose execution or publication."
            )
        if descriptor.destructive:
            raise ValidationError("Review UI V1 action registry cannot expose destruction.")
        registry[descriptor.action_descriptor_id] = descriptor
    return registry


_SOURCE_LOADERS: dict[str, tuple[str, str, Callable[[BobaMemoryStore, str], Any]]] = {
    "rights_permission_gate": (
        "Rights + Permission Gate",
        "rights",
        lambda store, project_id: store.load_rights_permission_gate(project_id),
    ),
    "safety_gate": (
        "Safety Gate",
        "safety",
        lambda store, project_id: store.load_boba_safety_gate(project_id),
    ),
    "workflow_controller": (
        "Workflow Controller",
        "workflow",
        lambda store, project_id: store.load_boba_workflow_controller(project_id),
    ),
    "validator_runner": (
        "Validator Runner",
        "validation",
        lambda store, project_id: store.load_boba_validator_runner(project_id),
    ),
    "output_quality_reviewer": (
        "Output Quality Reviewer",
        "quality",
        lambda store, project_id: store.load_boba_output_quality_reviewer(project_id),
    ),
    "artifact_inspector": (
        "Artifact Inspector",
        "artifacts",
        lambda store, project_id: store.load_boba_artifact_inspector(project_id),
    ),
    "report_reader": (
        "Report Reader",
        "reports",
        lambda store, project_id: store.load_boba_report_reader(project_id),
    ),
    "tool_recovery": (
        "Tool Recovery Brain",
        "recovery",
        lambda store, project_id: store.load_boba_tool_recovery(project_id),
    ),
    "autopilot_controller": (
        "Autopilot Controller",
        "autopilot",
        lambda store, project_id: store.load_boba_autopilot_controller(project_id),
    ),
    "integration_layer": (
        "Integration Layer",
        "integration",
        lambda store, project_id: store.load_boba_integration_layer(project_id),
    ),
    "final_decision_bus": (
        "Final Decision Bus",
        "final_decision",
        lambda store, project_id: store.load_boba_final_decision_bus(project_id),
    ),
}

_TARGET_TYPE_BY_MODULE: dict[str, ReviewTargetType] = {
    "workflow_controller": "workflow_stage",
    "output_quality_reviewer": "quality_review",
    "artifact_inspector": "artifact",
    "validator_runner": "validation_run",
    "tool_recovery": "recovery_run",
    "final_decision_bus": "final_decision",
    "report_reader": "report_bundle",
    "safety_gate": "approval_request",
    "rights_permission_gate": "approval_request",
}

_REVIEW_MODE_BY_MODULE: dict[str, ReviewMode] = {
    "workflow_controller": "workflow_review",
    "validator_runner": "validation_review",
    "output_quality_reviewer": "quality_review",
    "artifact_inspector": "artifact_review",
    "tool_recovery": "recovery_review",
    "final_decision_bus": "final_decision_review",
    "report_reader": "incident_review",
    "safety_gate": "approval_review",
    "rights_permission_gate": "approval_review",
}

_SECTION_GROUPS: tuple[tuple[str, str], ...] = (
    ("overview", "Overview"),
    ("workflow", "Workflow"),
    ("rights", "Rights"),
    ("safety", "Safety"),
    ("artifacts", "Artifacts"),
    ("validation", "Technical validation"),
    ("quality", "Output quality"),
    ("final_decision", "Final Decision Bus"),
    ("timeline", "Timeline"),
)


class BobaReviewUiV1:
    """Build bounded review projections from canonical BOBA source records.

    This class never becomes the owner of a decision.  It reads canonical owner
    records, projects them for presentation, and routes explicitly confirmed
    human actions back to the exact module that owns the authority.
    """

    def __init__(self, store: BobaMemoryStore, integration: BobaIntegration) -> None:
        self.store = store
        self.integration = integration

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def build_review_ui_registry(self, project_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        views = build_fixed_review_view_registry()
        actions = build_fixed_review_action_registry()
        view_rows = [item.model_dump(mode="json") for item in views.values()]
        action_rows = [item.model_dump(mode="json") for item in actions.values()]
        payload = {"views": view_rows, "actions": action_rows}
        registry_snapshot_id = _stable_id("review_registry", "v1", _digest(payload))
        stored = self.store.load_boba_review_ui_registry(project_id, registry_snapshot_id)
        if isinstance(stored, Mapping):
            return {
                "registry_snapshot": BobaReviewUiRegistrySnapshotV1.model_validate(
                    stored
                ).model_dump(mode="json"),
                "views": view_rows,
                "actions": action_rows,
            }
        registry = BobaReviewUiRegistrySnapshotV1(
            registry_snapshot_id=registry_snapshot_id,
            view_descriptor_ids=list(views),
            action_descriptor_ids=list(actions),
            available_review_modes=[
                item.review_mode for item in views.values() if item.availability == "available"
            ],
            unavailable_review_modes=[
                item.review_mode for item in views.values() if item.availability != "available"
            ],
            available_action_ids=[
                item.action_descriptor_id
                for item in actions.values()
                if item.allowed_in_v1 and item.availability == "available"
            ],
            unavailable_action_ids=[
                item.action_descriptor_id
                for item in actions.values()
                if not item.allowed_in_v1 or item.availability != "available"
            ],
            registry_digest=_digest(payload),
            limitations=[
                "The registry is fixed source code; browser requests cannot add "
                "modules, operations, URLs, filesystem paths, or commands.",
            ],
        )
        self.store.save_boba_review_ui_registry(
            project_id,
            registry.registry_snapshot_id,
            registry.model_dump(mode="json"),
        )
        return {
            "registry_snapshot": registry.model_dump(mode="json"),
            "views": view_rows,
            "actions": action_rows,
        }

    def inspect_review_ui_registry(self, project_id: str) -> dict[str, Any]:
        return self.build_review_ui_registry(project_id)

    # ------------------------------------------------------------------
    # Sessions and preferences
    # ------------------------------------------------------------------
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
        if _SENSITIVE_KEY.search(reviewer_context_id):
            raise ValidationError("Reviewer context cannot contain credentials.")
        session_id = f"review_session_{uuid4().hex}"
        now = datetime.now(UTC)
        session_payload = {
            "session_id": session_id,
            "project_id": project_id,
            "reviewer_context_id": reviewer_context_id,
            "review_mode": review_mode,
            "target_type": target_type,
            "target_id": target_id,
        }
        session = BobaReviewSessionV1(
            review_session_id=session_id,
            project_id=project_id,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(
                now + timedelta(seconds=max(60, min(expires_in_seconds, 28_800)))
            ).isoformat(),
            reviewer_context_id=reviewer_context_id,
            selected_review_mode=review_mode,
            selected_target_type=target_type,
            selected_target_id=_safe_text(target_id, 180),
            session_digest=_digest(session_payload),
            limitations=[
                "Review sessions hold only UI state; they are not approvals or "
                "source decisions.",
            ],
        )
        self.store.save_boba_review_ui_session(
            project_id, session_id, session.model_dump(mode="json")
        )
        return session

    def get_review_session(self, project_id: str, session_id: str) -> BobaReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(session_id, "review session id")
        raw = self.store.load_boba_review_ui_session(project_id, session_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA Review UI session is unavailable.")
        session = BobaReviewSessionV1.model_validate(raw)
        if session.project_id != project_id:
            raise ValidationError("Review session belongs to another project.")
        expires_at = _parse_time(session.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            raise ValidationError("BOBA Review UI session has expired.")
        return session

    def update_review_preferences(
        self,
        project_id: str,
        session_id: str,
        updates: Mapping[str, Any],
    ) -> BobaReviewSessionV1:
        session = self.get_review_session(project_id, session_id)
        allowed = {
            "selected_review_mode",
            "selected_target_type",
            "selected_target_id",
            "selected_clip_id",
            "selected_output_id",
            "selected_attempt_id",
            "comparison_target_ids",
            "active_filter_id",
            "active_sort",
            "active_tab",
            "evidence_drawer_open",
            "event_drawer_open",
            "compact_mode",
            "read_queue_item_ids",
            "acknowledged_notification_ids",
        }
        unsafe = set(updates) - allowed
        if unsafe:
            raise ValidationError("Review session update contains unsupported fields.")
        payload = session.model_dump(mode="json")
        payload.update(_as_mapping(_safe_payload(dict(updates))))
        payload["updated_at"] = now_iso()
        payload["session_digest"] = _digest(
            {key: value for key, value in payload.items() if key != "session_digest"}
        )
        updated = BobaReviewSessionV1.model_validate(payload)
        self.store.save_boba_review_ui_session(
            project_id, session_id, updated.model_dump(mode="json")
        )
        return updated

    # ------------------------------------------------------------------
    # Deterministic queue
    # ------------------------------------------------------------------
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
        items = [self._queue_item(project_id, card, cards) for card in cards]
        if not include_historical:
            items = [item for item in items if not item.historical]
        if category and category != "all":
            items = [item for item in items if item.display_category == category]
        if sort == "updated":
            items.sort(key=lambda item: (item.updated_at, item.queue_item_id), reverse=True)
        else:
            items.sort(key=lambda item: (item.priority, item.queue_sort_key, item.queue_item_id))
        safe_offset = max(0, offset)
        safe_limit = max(1, min(limit, _MAX_QUEUE))
        window = items[safe_offset : safe_offset + safe_limit]
        return {
            "schema_version": "boba_review_ui_queue_v1",
            "project_id": project_id,
            "total": len(items),
            "offset": safe_offset,
            "limit": safe_limit,
            "priority_tiers": [
                {"priority": priority, "reason": reason, "display_category": tier_category}
                for priority, reason, tier_category in QUEUE_PRIORITY_TIERS
            ],
            "items": [item.model_dump(mode="json") for item in window],
        }

    def inspect_review_queue(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.build_review_queue(project_id, **kwargs)

    # ------------------------------------------------------------------
    # Targets and snapshots
    # ------------------------------------------------------------------
    def inspect_review_target(self, project_id: str, review_target_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        _safe_id(review_target_id, "review target id")
        cards = self._source_cards(project_id)
        if review_target_id == self._project_target_id(project_id):
            target = self._project_target(project_id, cards)
            return {
                "target": target.model_dump(mode="json"),
                "source_cards": [card.model_dump(mode="json") for card in cards],
            }
        for card in cards:
            target = self._target_from_card(project_id, card, cards)
            if target.review_target_id == review_target_id:
                return {
                    "target": target.model_dump(mode="json"),
                    "source_cards": [card.model_dump(mode="json") for card in cards],
                }
        raise ValidationError(
            "BOBA Review UI target is unavailable or belongs to another project."
        )

    def build_review_snapshot(
        self,
        project_id: str,
        session_id: str,
        review_target_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.get_review_session(project_id, session_id)
        target_id = (
            review_target_id
            or session.selected_target_id
            or self._project_target_id(project_id)
        )
        target_payload = self.inspect_review_target(project_id, target_id)
        target = BobaReviewTargetV1.model_validate(target_payload["target"])
        cards = [
            BobaReviewSourceCardV1.model_validate(item)
            for item in target_payload["source_cards"]
        ]
        events = self.inspect_review_events(project_id, limit=_MAX_EVENTS)["events"]
        digests = {card.source_record_id: card.source_record_digest for card in cards}
        snapshot_payload = {
            "project": target.project_snapshot_digest,
            "target": target.target_digest,
            "revision": target.workflow_revision,
            "sources": digests,
            "session": session.review_session_id,
        }
        snapshot = BobaReviewSnapshotV1(
            review_snapshot_id=f"review_snapshot_{uuid4().hex}",
            review_session_id=session.review_session_id,
            review_target_id=target.review_target_id,
            project_id=project_id,
            project_snapshot_digest=target.project_snapshot_digest,
            workflow_revision=target.workflow_revision,
            target_digest=target.target_digest,
            source_record_references=[
                {"module_id": card.source_module_id, "record_id": card.source_record_id}
                for card in cards
            ],
            source_record_digests=digests,
            section_ids=[kind for kind, _ in _SECTION_GROUPS],
            source_card_ids=[card.source_card_id for card in cards],
            timeline_entry_ids=[
                str(item.get("ui_event_id") or "")
                for item in events
                if item.get("ui_event_id")
            ],
            available_action_descriptor_ids=self._available_actions(target),
            rights_status=self._status_for(cards, "rights_permission_gate"),
            safety_status=self._status_for(cards, "safety_gate"),
            approval_status=self._approval_status(cards),
            workflow_status=self._status_for(cards, "workflow_controller"),
            artifact_status=self._status_for(cards, "artifact_inspector"),
            validation_status=self._status_for(cards, "validator_runner"),
            quality_status=self._status_for(cards, "output_quality_reviewer"),
            recovery_status=self._status_for(cards, "tool_recovery"),
            final_decision_status=self._status_for(cards, "final_decision_bus"),
            missing_evidence_count=sum(
                1 for card in cards if card.original_status in {"unknown", "unavailable"}
            ),
            conflict_count=sum(1 for card in cards if card.conflict_detected),
            warning_count=sum(len(card.warnings) for card in cards),
            limitation_count=sum(len(card.limitations) for card in cards),
            human_action_required=any(card.human_review_required for card in cards),
            current=target.current,
            stale=target.stale,
            snapshot_digest=_digest(snapshot_payload),
            limitations=[
                "Snapshot status is display-only and links to canonical owner records.",
            ],
        )
        self.store.save_boba_review_ui_snapshot(
            project_id, snapshot.review_snapshot_id, snapshot.model_dump(mode="json")
        )
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "target": target.model_dump(mode="json"),
            "source_cards": [card.model_dump(mode="json") for card in cards],
            "sections": [
                section.model_dump(mode="json")
                for section in self._sections(snapshot, cards)
            ],
        }

    def refresh_review_snapshot(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = self._snapshot(project_id, snapshot_id)
        return self.build_review_snapshot(
            project_id, snapshot.review_session_id, snapshot.review_target_id
        )

    # ------------------------------------------------------------------
    # Canonical action routing
    # ------------------------------------------------------------------
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
        if snapshot.review_session_id != session.review_session_id:
            raise ValidationError("Review snapshot belongs to another review session.")
        descriptor = self._action_descriptor(action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            raise ValidationError("This BOBA Review UI action is unavailable in V1.")
        target = BobaReviewTargetV1.model_validate(
            self.inspect_review_target(project_id, snapshot.review_target_id)["target"]
        )
        if descriptor.action_descriptor_id not in self._available_actions(target):
            raise ValidationError("The action is unavailable for this exact review target.")
        if descriptor.requires_reason and not reason.strip():
            raise ValidationError("This review action requires a reason.")
        if len(reason) > descriptor.maximum_reason_length:
            raise ValidationError("Review action reason exceeds the allowed length.")
        if _SENSITIVE_KEY.search(reason):
            raise ValidationError("Review action reasons cannot contain credentials.")
        if descriptor.allowed_decision_values and decision_value not in (
            descriptor.allowed_decision_values
        ):
            raise ValidationError("Unsupported decision value for this fixed review action.")
        if not confirmed:
            raise ValidationError("Explicit review action confirmation is required.")
        expected_confirmation = self.build_confirmation_digest(snapshot, descriptor, target)
        if confirmation_context_digest != expected_confirmation:
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
        self.store.save_boba_review_ui_action(
            project_id, request.review_action_request_id, request.model_dump(mode="json")
        )
        return request

    @staticmethod
    def build_confirmation_digest(
        snapshot: BobaReviewSnapshotV1,
        descriptor: BobaReviewActionDescriptorV1,
        target: BobaReviewTargetV1,
    ) -> str:
        """Return the digest a reviewer must echo back to confirm an action."""
        return _digest(
            {
                "snapshot": snapshot.snapshot_digest,
                "action": descriptor.action_descriptor_id,
                "target": target.target_digest,
            }
        )

    def validate_review_action_request(
        self,
        project_id: str,
        action_request_id: str,
    ) -> dict[str, Any]:
        """Re-read canonical state and reject stale or drifted submissions."""
        request = self._action_request(project_id, action_request_id)
        expires_at = _parse_time(request.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            return {
                "valid": False,
                "code": "expired_snapshot",
                "message": "The review action expired before submission.",
            }
        descriptor = self._action_descriptor(request.action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "This review action is no longer available.",
            }
        try:
            payload = self.inspect_review_target(project_id, request.review_target_id)
        except ValidationError:
            return {
                "valid": False,
                "code": "target_removed",
                "message": "The review target is no longer available.",
            }
        current = BobaReviewTargetV1.model_validate(payload["target"])
        if current.project_snapshot_digest != request.expected_project_snapshot_digest:
            return {
                "valid": False,
                "code": "stale_project_snapshot",
                "message": "The project changed while this review was open.",
            }
        if current.workflow_revision != request.expected_workflow_revision:
            return {
                "valid": False,
                "code": "workflow_revision_mismatch",
                "message": "The workflow revision changed while this review was open.",
            }
        if current.target_digest != request.expected_target_digest:
            return {
                "valid": False,
                "code": "target_digest_mismatch",
                "message": "The review target changed while this review was open.",
            }
        cards = [
            BobaReviewSourceCardV1.model_validate(item) for item in payload["source_cards"]
        ]
        live = {card.source_record_id: card.source_record_digest for card in cards}
        for record_id, digest in request.expected_source_record_digests.items():
            if live.get(record_id) != digest:
                return {
                    "valid": False,
                    "code": "source_record_digest_mismatch",
                    "message": "A canonical source record changed while this review was open.",
                }
        if descriptor.action_descriptor_id not in self._available_actions(current):
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "The action is no longer available for this exact target.",
            }
        return {
            "valid": True,
            "code": "current",
            "message": "Exact review target remains current.",
        }

    async def submit_review_action_to_owner(
        self,
        project_id: str,
        action_request_id: str,
    ) -> BobaReviewActionReceiptV1:
        """Submit an action to its canonical owner and persist an immutable receipt."""
        request = self._action_request(project_id, action_request_id)
        existing = self.store.load_boba_review_ui_receipt_for_action(
            project_id, action_request_id
        )
        if isinstance(existing, Mapping):
            receipt = BobaReviewActionReceiptV1.model_validate(existing)
            return receipt.model_copy(update={"duplicate_request_reused": True})
        validation = self.validate_review_action_request(project_id, action_request_id)
        if not validation["valid"]:
            return self._persist_receipt(
                project_id,
                BobaReviewActionReceiptV1(
                    action_receipt_id=f"review_receipt_{uuid4().hex}",
                    review_action_request_id=request.review_action_request_id,
                    project_id=project_id,
                    owning_module_id=request.owning_module_id,
                    owning_operation_id=request.owning_operation_id,
                    completed_at=now_iso(),
                    canonical_status="rejected_stale_state",
                    accepted_by_owner=False,
                    authoritative_state_changed=False,
                    stale_state_rejected=True,
                    error_code=str(validation["code"]),
                    bounded_error_message=str(validation["message"]),
                    limitations=[
                        "No canonical owner was contacted; no authority changed.",
                    ],
                ),
            )
        if request.action_descriptor_id == "review_action_acknowledge_notification_v1":
            return self._submit_acknowledgement(project_id, request)
        if request.action_descriptor_id == "review_action_workflow_human_decision_v1":
            return self._submit_workflow_human_decision(project_id, request)
        return self._persist_receipt(
            project_id,
            BobaReviewActionReceiptV1(
                action_receipt_id=f"review_receipt_{uuid4().hex}",
                review_action_request_id=request.review_action_request_id,
                project_id=project_id,
                owning_module_id=request.owning_module_id,
                owning_operation_id=request.owning_operation_id,
                completed_at=now_iso(),
                canonical_status="owner_route_unavailable",
                accepted_by_owner=False,
                authoritative_state_changed=False,
                error_code="owner_route_unavailable",
                bounded_error_message=(
                    "No exact canonical owner route is available for this V1 action."
                ),
                limitations=["No authoritative state changed."],
            ),
        )

    def _submit_acknowledgement(
        self,
        project_id: str,
        request: BobaReviewActionRequestV1,
    ) -> BobaReviewActionReceiptV1:
        session = self.get_review_session(project_id, request.review_session_id)
        notification_id = request.target_id
        if notification_id not in session.acknowledged_notification_ids:
            self.update_review_preferences(
                project_id,
                session.review_session_id,
                {
                    "acknowledged_notification_ids": [
                        *session.acknowledged_notification_ids,
                        notification_id,
                    ]
                },
            )
        return self._persist_receipt(
            project_id,
            BobaReviewActionReceiptV1(
                action_receipt_id=f"review_receipt_{uuid4().hex}",
                review_action_request_id=request.review_action_request_id,
                project_id=project_id,
                owning_module_id="review_ui",
                owning_operation_id="acknowledge_notification",
                completed_at=now_iso(),
                canonical_request_id=request.review_action_request_id,
                canonical_record_id=notification_id,
                canonical_record_digest=_digest(
                    {
                        "notification_id": notification_id,
                        "session_id": session.review_session_id,
                    }
                ),
                canonical_status="acknowledged",
                accepted_by_owner=True,
                authoritative_state_changed=False,
                canonical_refresh_required=True,
                limitations=[
                    "Acknowledgement changes only review-session metadata; the "
                    "source issue remains visible until its owner resolves it.",
                ],
            ),
        )

    def _submit_workflow_human_decision(
        self,
        project_id: str,
        request: BobaReviewActionRequestV1,
    ) -> BobaReviewActionReceiptV1:
        """Route a confirmed human decision to the Workflow Controller."""
        workflow_run_id = request.workflow_run_id or ""
        if not workflow_run_id:
            return self._persist_receipt(
                project_id,
                BobaReviewActionReceiptV1(
                    action_receipt_id=f"review_receipt_{uuid4().hex}",
                    review_action_request_id=request.review_action_request_id,
                    project_id=project_id,
                    owning_module_id=request.owning_module_id,
                    owning_operation_id=request.owning_operation_id,
                    completed_at=now_iso(),
                    canonical_status="owner_route_unavailable",
                    error_code="workflow_run_unbound",
                    bounded_error_message=(
                        "No exact workflow run is bound to this review target."
                    ),
                    limitations=["No authoritative state changed."],
                ),
            )
        try:
            record = self.integration.workflow_controller.record_human_workflow_decision(
                project_id,
                workflow_run_id,
                expected_revision=request.expected_workflow_revision,
                decision_type="review_ui_human_decision",
                decision=str(request.decision_value or ""),
                reason=request.bounded_reason,
                reviewer_reference=request.reviewer_context_id,
                explicit_confirmation=True,
                stage_instance_id=request.stage_instance_id,
            )
        except ValidationError as error:
            return self._persist_receipt(
                project_id,
                BobaReviewActionReceiptV1(
                    action_receipt_id=f"review_receipt_{uuid4().hex}",
                    review_action_request_id=request.review_action_request_id,
                    project_id=project_id,
                    owning_module_id=request.owning_module_id,
                    owning_operation_id=request.owning_operation_id,
                    completed_at=now_iso(),
                    canonical_status="rejected_by_owner",
                    accepted_by_owner=False,
                    authoritative_state_changed=False,
                    error_code="owner_rejected",
                    bounded_error_message=_safe_text(str(error), 900),
                    limitations=[
                        "The Workflow Controller rejected the decision; no "
                        "authoritative state changed.",
                    ],
                ),
            )
        payload = _as_mapping(record)
        canonical_record_id = _safe_text(payload.get("human_decision_id"), 180)
        if not canonical_record_id:
            return self._persist_receipt(
                project_id,
                BobaReviewActionReceiptV1(
                    action_receipt_id=f"review_receipt_{uuid4().hex}",
                    review_action_request_id=request.review_action_request_id,
                    project_id=project_id,
                    owning_module_id=request.owning_module_id,
                    owning_operation_id=request.owning_operation_id,
                    completed_at=now_iso(),
                    canonical_status="malformed_owner_response",
                    accepted_by_owner=False,
                    authoritative_state_changed=False,
                    error_code="malformed_canonical_response",
                    bounded_error_message=(
                        "The owning module did not return a canonical record identifier."
                    ),
                    limitations=["No authoritative state changed."],
                ),
            )
        return self._persist_receipt(
            project_id,
            BobaReviewActionReceiptV1(
                action_receipt_id=f"review_receipt_{uuid4().hex}",
                review_action_request_id=request.review_action_request_id,
                project_id=project_id,
                owning_module_id="workflow_controller",
                owning_operation_id="record_human_workflow_decision",
                completed_at=now_iso(),
                canonical_request_id=request.review_action_request_id,
                canonical_record_id=canonical_record_id,
                canonical_record_digest=_digest(_safe_payload(payload)),
                canonical_status=_safe_text(payload.get("decision") or "recorded", 160),
                accepted_by_owner=True,
                authoritative_state_changed=True,
                canonical_refresh_required=True,
                limitations=[
                    "The Workflow Controller owns this decision record and its revision.",
                    "Recording a decision did not upload, publish, or run a stage.",
                ],
            ),
        )

    def _persist_receipt(
        self,
        project_id: str,
        receipt: BobaReviewActionReceiptV1,
    ) -> BobaReviewActionReceiptV1:
        if receipt.authoritative_state_changed and not (
            receipt.canonical_record_id and receipt.canonical_record_digest
        ):
            raise ValidationError(
                "Authoritative state cannot change without a canonical owner record."
            )
        self.store.save_boba_review_ui_receipt(
            project_id, receipt.action_receipt_id, receipt.model_dump(mode="json")
        )
        return receipt

    def inspect_review_action_receipt(
        self,
        project_id: str,
        action_request_id: str,
    ) -> dict[str, Any]:
        request = self._action_request(project_id, action_request_id)
        receipt = self.store.load_boba_review_ui_receipt_for_action(
            project_id, action_request_id
        )
        return {
            "request": request.model_dump(mode="json"),
            "receipt": _safe_payload(receipt) if receipt else None,
        }

    # ------------------------------------------------------------------
    # Truthful canonical events
    # ------------------------------------------------------------------
    def inspect_review_timeline(self, project_id: str, *, limit: int = 100) -> dict[str, Any]:
        events = self.inspect_review_events(project_id, limit=limit)["events"]
        entries = [
            self._timeline_entry(BobaReviewUiEventV1.model_validate(event)) for event in events
        ]
        return {
            "schema_version": "boba_review_ui_timeline_v1",
            "project_id": project_id,
            "entries": [item.model_dump(mode="json") for item in entries],
        }

    def inspect_review_events(
        self,
        project_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Project bounded, de-duplicated canonical events. No invented progress."""
        _safe_id(project_id, "project id")
        seen: set[tuple[str, str]] = set()
        events: list[BobaReviewUiEventV1] = []
        for module_id in _SOURCE_LOADERS:
            payload = self._source_payload(module_id, project_id)
            for event in self._event_rows(project_id, module_id, payload):
                if event.source_sequence is not None and event.source_sequence <= after_sequence:
                    continue
                key = (event.source_module_id, event.source_event_id or event.ui_event_id)
                if key in seen:
                    continue
                seen.add(key)
                events.append(event)
        events.sort(
            key=lambda item: (
                item.created_at or "",
                item.source_module_id,
                item.source_sequence or 0,
                item.ui_event_id,
            )
        )
        bounded = events[-max(1, min(limit, _MAX_EVENTS)) :]
        return {
            "schema_version": "boba_review_ui_events_v1",
            "project_id": project_id,
            "events": [item.model_dump(mode="json") for item in bounded],
            "has_more": len(events) > len(bounded),
            "latest_sequence": max(
                (item.source_sequence or 0 for item in bounded),
                default=after_sequence,
            ),
        }

    def record_review_event_cursor(
        self,
        project_id: str,
        session_id: str,
        *,
        last_sequence: int,
        last_event_id: str = "",
    ) -> dict[str, Any]:
        """Persist a bounded, project-scoped event cursor for safe replay."""
        session = self.get_review_session(project_id, session_id)
        cursor = {
            "schema_version": "boba_review_ui_event_cursor_v1",
            "project_id": project_id,
            "review_session_id": session.review_session_id,
            "last_sequence": max(0, min(int(last_sequence), 1_000_000_000)),
            "last_event_id": _safe_text(last_event_id, 180),
            "updated_at": now_iso(),
        }
        self.store.save_boba_review_ui_event_cursor(
            project_id, session.review_session_id, cursor
        )
        return cursor

    def acknowledge_review_notification(
        self,
        project_id: str,
        session_id: str,
        notification_id: str,
    ) -> BobaReviewSessionV1:
        _safe_id(notification_id, "notification id")
        session = self.get_review_session(project_id, session_id)
        return self.update_review_preferences(
            project_id,
            session_id,
            {
                "acknowledged_notification_ids": [
                    *session.acknowledged_notification_ids,
                    notification_id,
                ]
            },
        )

    # ------------------------------------------------------------------
    # Load, export, reset
    # ------------------------------------------------------------------
    def load_review_ui(self, project_id: str) -> dict[str, Any] | None:
        _safe_id(project_id, "project id")
        return self.store.load_boba_review_ui(project_id)

    def export_review_ui(
        self,
        project_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        cards = self._source_cards(project_id)
        payload: dict[str, Any] = {
            "schema_version": "boba_review_ui_export_v1",
            "project_id": project_id,
            "exported_at": now_iso(),
            "source_cards": [card.model_dump(mode="json") for card in cards],
            "queue": self.build_review_queue(project_id, limit=_MAX_QUEUE),
            "timeline": self.inspect_review_timeline(project_id, limit=50),
            "privacy": {
                "private_paths_excluded": True,
                "raw_media_excluded": True,
                "raw_reports_excluded": True,
                "raw_logs_excluded": True,
                "secrets_excluded": True,
                "source_media_modified": False,
                "accepted_outputs_modified": False,
                "upload_used": False,
                "publication_used": False,
            },
        }
        if session_id:
            payload["session"] = self.get_review_session(
                project_id, session_id
            ).model_dump(mode="json")
        return _as_mapping(_safe_payload(payload))

    def reset_review_ui_metadata(
        self,
        project_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        if session_id:
            _safe_id(session_id, "review session id")
            removed = self.store.delete_boba_review_ui_session(project_id, session_id)
            return {
                "schema_version": "boba_review_ui_reset_v1",
                "project_id": project_id,
                "session_removed": removed,
                "source_records_preserved": True,
                "workflow_history_preserved": True,
                "validation_history_preserved": True,
                "quality_history_preserved": True,
                "artifact_history_preserved": True,
                "final_decision_history_preserved": True,
                "action_receipt_history_preserved": True,
            }
        return self.store.reset_boba_review_ui_metadata(project_id)

    def build_review_ui(self, project_id: str) -> dict[str, Any]:
        registry = self.build_review_ui_registry(project_id)
        cards = self._source_cards(project_id)
        queue = self.build_review_queue(project_id, limit=_MAX_QUEUE)
        events = self.inspect_review_events(project_id, limit=_MAX_EVENTS)
        notifications = self._notifications(project_id, cards)
        summary = self._summary(queue["items"], events["events"], cards)
        result = BobaReviewUiSetV1(
            project_id=project_id,
            registry_snapshots=[
                BobaReviewUiRegistrySnapshotV1.model_validate(registry["registry_snapshot"])
            ],
            view_descriptors=[
                BobaReviewViewDescriptorV1.model_validate(item) for item in registry["views"]
            ],
            action_descriptors=[
                BobaReviewActionDescriptorV1.model_validate(item)
                for item in registry["actions"]
            ],
            review_queue_items=[
                BobaReviewQueueItemV1.model_validate(item) for item in queue["items"]
            ],
            source_cards=cards,
            notifications=notifications,
            events=[
                BobaReviewUiEventV1.model_validate(item) for item in events["events"]
            ],
            ui_summary=summary,
            signal_usage=self._signal_usage(cards),
            limitations=[
                "Review UI V1 is a presentation and routing layer. It does not "
                "create authoritative decisions.",
            ],
        )
        self.store.save_boba_review_ui(project_id, result.model_dump(mode="json"))
        return result.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Source projection
    # ------------------------------------------------------------------
    def _source_payload(self, module_id: str, project_id: str) -> dict[str, Any]:
        _, _, loader = _SOURCE_LOADERS[module_id]
        try:
            return _as_mapping(loader(self.store, project_id))
        except (ValidationError, NotFoundError, OSError):
            return {}

    def _source_cards(self, project_id: str) -> list[BobaReviewSourceCardV1]:
        _safe_id(project_id, "project id")
        cards: list[BobaReviewSourceCardV1] = []
        for module_id, (title, domain, _) in _SOURCE_LOADERS.items():
            payload = self._source_payload(module_id, project_id)
            if not payload:
                cards.append(self._unavailable_card(project_id, module_id, title, domain))
                continue
            cards.append(
                self._available_card(project_id, module_id, title, domain, payload)
            )
        return cards[:_MAX_SOURCE_CARDS]

    @staticmethod
    def _unavailable_card(
        project_id: str,
        module_id: str,
        title: str,
        domain: str,
    ) -> BobaReviewSourceCardV1:
        route = f"/api/v1/boba/projects/{project_id}/{module_id.replace('_', '-')}"
        return BobaReviewSourceCardV1(
            source_card_id=_stable_id("review_card", project_id, module_id, "unavailable"),
            source_module_id=module_id,
            authority_domain=domain,
            source_record_id=_stable_id("unavailable", project_id, module_id),
            source_record_digest=_digest({"module": module_id, "state": "unavailable"}),
            original_status="unavailable",
            display_category="unavailable",
            title=title,
            bounded_summary="No canonical record is currently available for this project.",
            easy_explanation=f"{title} has not supplied a current review record.",
            current=False,
            authoritative=True,
            details_route=route,
            priority_tier=110,
            priority_reason="completed_informational",
            limitations=[
                "An unavailable source record is never treated as a pass.",
            ],
        )

    def _available_card(
        self,
        project_id: str,
        module_id: str,
        title: str,
        domain: str,
        payload: Mapping[str, Any],
    ) -> BobaReviewSourceCardV1:
        safe = _as_mapping(_safe_payload(payload))
        status = _source_status(safe)
        stale = _is_stale(safe)
        blocking = _is_blocking(safe, status)
        human = _has_human_review(safe)
        source_id = _record_id(safe, module_id)
        run = _active_workflow_run(safe) if module_id == "workflow_controller" else {}
        revision = run.get("revision")
        summary = _first_text(safe, "summary", "reason", "message", "description", "result")
        card = BobaReviewSourceCardV1(
            source_card_id=_stable_id("review_card", project_id, module_id, source_id),
            source_module_id=module_id,
            authority_domain=domain,
            source_record_id=source_id,
            source_record_digest=_digest(safe),
            source_schema_id=_safe_text(
                safe.get("schema_version") or safe.get("schema_id") or "unknown", 180
            ),
            source_schema_version=_safe_text(safe.get("version") or "1", 80),
            original_status=status,
            original_decision=_source_decision(safe),
            display_category="unknown",
            title=title,
            bounded_summary=summary or f"Canonical {title} record is available.",
            easy_explanation=f"{title} reports {status}.",
            current=not stale,
            stale=stale,
            expired=bool(safe.get("expired")),
            invalidated=bool(safe.get("invalidated")),
            superseded=bool(safe.get("superseded")),
            authoritative=True,
            advisory_only=False,
            human_review_required=human,
            blocking=blocking,
            details_route=(
                f"/api/v1/boba/projects/{project_id}/{module_id.replace('_', '-')}"
            ),
            source_run_id=_safe_text(run.get("workflow_run_id"), 180) or None,
            source_stage_instance_id=(
                _safe_text(run.get("current_stage_instance_id"), 180) or None
            ),
            source_revision=revision if isinstance(revision, int) and revision >= 0 else 0,
            protection_incident=_has_protection_incident(safe),
            recovery_hold=_has_recovery_hold(safe),
            approval_required=_requires_approval(safe),
            conflict_detected=_has_conflict(safe),
            warnings=[
                _safe_text(item, 300) for item in safe.get("warnings", []) if isinstance(item, str)
            ][:16],
            limitations=[
                _safe_text(item, 300)
                for item in safe.get("limitations", [])
                if isinstance(item, str)
            ][:16],
        )
        priority, category, reason = self._priority(card)
        return card.model_copy(
            update={
                "priority_tier": priority,
                "priority_reason": reason,
                "display_category": category,
            }
        )

    @staticmethod
    def _priority(card: BobaReviewSourceCardV1) -> tuple[int, QueueCategory, str]:
        """Deterministic 12-tier priority derived only from canonical signals."""
        module_id = card.source_module_id
        if module_id in {"rights_permission_gate", "safety_gate"} and card.blocking:
            return 10, "critical_attention", "rights_or_safety_critical_block"
        if card.protection_incident:
            return 20, "critical_attention", "protected_asset_incident"
        if card.recovery_hold:
            return 30, "blocked", "workflow_recovery_hold"
        if card.approval_required and card.human_review_required:
            return 40, "human_review_required", "required_human_approval"
        if module_id == "output_quality_reviewer" and card.human_review_required:
            return 50, "human_review_required", "output_quality_human_review"
        if module_id == "final_decision_bus" and (card.blocking or card.conflict_detected):
            return 60, "blocked", "final_decision_hold_or_conflict"
        if module_id == "validator_runner" and (
            card.blocking or not card.current or card.original_status in {"unknown", "unavailable"}
        ):
            return 70, "awaiting_evidence", "missing_or_failed_technical_validation"
        if module_id == "artifact_inspector" and (
            card.blocking or card.stale or not card.current
        ):
            return 80, "awaiting_evidence", "missing_or_stale_artifact"
        if module_id == "tool_recovery" and (card.blocking or card.human_review_required):
            return 90, "ready_for_review", "recovery_incident"
        if card.human_review_required:
            return 40, "human_review_required", "required_human_approval"
        if module_id == "workflow_controller" and card.blocking:
            return 30, "blocked", "workflow_recovery_hold"
        if card.superseded:
            return 120, "historical", "historical_record"
        if module_id in {"output_quality_reviewer", "artifact_inspector", "validator_runner"}:
            return 100, "ready_for_review", "candidate_or_output_review"
        if not card.current:
            return 110, "unavailable", "completed_informational"
        return 110, "informational", "completed_informational"

    def _queue_item(
        self,
        project_id: str,
        card: BobaReviewSourceCardV1,
        all_cards: list[BobaReviewSourceCardV1],
    ) -> BobaReviewQueueItemV1:
        target = self._target_from_card(project_id, card, all_cards)
        missing_evidence = (
            1 if not card.current or card.original_status in {"unknown", "unavailable"} else 0
        )
        return BobaReviewQueueItemV1(
            queue_item_id=_stable_id(
                "review_queue", project_id, card.source_module_id, card.source_record_digest
            ),
            project_id=project_id,
            workflow_run_id=target.workflow_run_id,
            stage_instance_id=target.stage_instance_id,
            target_type=target.target_type,
            target_id=target.review_target_id,
            review_mode=_REVIEW_MODE_BY_MODULE.get(card.source_module_id, "project_overview"),
            priority=card.priority_tier,
            display_category=card.display_category,
            title=card.title,
            bounded_summary=card.bounded_summary,
            source_module_ids=[card.source_module_id],
            source_record_ids=[card.source_record_id],
            source_record_digests={card.source_record_id: card.source_record_digest},
            primary_reason=card.priority_reason or card.original_status,
            blocker_count=1 if card.blocking else 0,
            warning_count=len(card.warnings),
            missing_evidence_count=missing_evidence,
            conflict_count=1 if card.conflict_detected else 0,
            human_action_required=card.human_review_required,
            available_action_descriptor_ids=self._available_actions(target),
            current=card.current,
            stale=card.stale,
            historical=card.superseded,
            queue_sort_key=(
                f"{card.priority_tier:03d}:{card.source_module_id}:{card.source_record_id}"
            ),
            warnings=card.warnings,
            limitations=card.limitations,
        )

    @staticmethod
    def _project_target_id(project_id: str) -> str:
        return f"review_target_project_{project_id}"

    def _target_from_card(
        self,
        project_id: str,
        card: BobaReviewSourceCardV1,
        all_cards: list[BobaReviewSourceCardV1],
    ) -> BobaReviewTargetV1:
        target_type = _TARGET_TYPE_BY_MODULE.get(card.source_module_id, "project")
        digests = {item.source_record_id: item.source_record_digest for item in all_cards}
        return BobaReviewTargetV1(
            review_target_id=_stable_id(
                "review_target", project_id, card.source_module_id, card.source_record_id
            ),
            project_id=project_id,
            workflow_run_id=card.source_run_id,
            stage_instance_id=card.source_stage_instance_id,
            target_type=target_type,
            target_id=card.source_record_id,
            project_snapshot_digest=_digest(digests),
            workflow_revision=self._workflow_revision(all_cards),
            target_digest=card.source_record_digest,
            current=card.current,
            stale=card.stale,
            historical=card.superseded,
            source_module_ids=[card.source_module_id],
            source_record_ids=[card.source_record_id],
            warnings=card.warnings,
            limitations=card.limitations,
        )

    def _project_target(
        self,
        project_id: str,
        cards: list[BobaReviewSourceCardV1],
    ) -> BobaReviewTargetV1:
        digests = {card.source_record_id: card.source_record_digest for card in cards}
        digest = _digest(digests)
        workflow = next(
            (card for card in cards if card.source_module_id == "workflow_controller"),
            None,
        )
        return BobaReviewTargetV1(
            review_target_id=self._project_target_id(project_id),
            project_id=project_id,
            workflow_run_id=workflow.source_run_id if workflow else None,
            stage_instance_id=workflow.source_stage_instance_id if workflow else None,
            target_type="project",
            target_id=project_id,
            project_snapshot_digest=digest,
            workflow_revision=self._workflow_revision(cards),
            target_digest=digest,
            current=any(card.current for card in cards),
            stale=all(card.stale or not card.current for card in cards),
            source_module_ids=[card.source_module_id for card in cards],
            source_record_ids=[card.source_record_id for card in cards],
            limitations=[
                "The project target aggregates canonical references; it does not "
                "merge or override source decisions.",
            ],
        )

    @staticmethod
    def _workflow_revision(cards: list[BobaReviewSourceCardV1]) -> int:
        for card in cards:
            if card.source_module_id == "workflow_controller":
                return card.source_revision
        return 0

    @staticmethod
    def _status_for(cards: list[BobaReviewSourceCardV1], module_id: str) -> str:
        return next(
            (card.original_status for card in cards if card.source_module_id == module_id),
            "unavailable",
        )

    @staticmethod
    def _approval_status(cards: list[BobaReviewSourceCardV1]) -> str:
        pending = [card for card in cards if card.approval_required]
        if pending:
            return "human_approval_required"
        workflow = next(
            (card for card in cards if card.source_module_id == "workflow_controller"),
            None,
        )
        if workflow is None or not workflow.current:
            return "unavailable"
        return "no_pending_approval"

    def _available_actions(self, target: BobaReviewTargetV1) -> list[str]:
        available: list[str] = []
        for descriptor in build_fixed_review_action_registry().values():
            if not descriptor.allowed_in_v1 or descriptor.availability != "available":
                continue
            if target.target_type not in descriptor.supported_target_types:
                continue
            if descriptor.requires_workflow_revision and not target.workflow_run_id:
                continue
            if descriptor.requires_target_digest and not target.target_digest:
                continue
            if descriptor.requires_current_snapshot and (target.stale or not target.current):
                continue
            available.append(descriptor.action_descriptor_id)
        return available

    def _action_descriptor(self, action_descriptor_id: str) -> BobaReviewActionDescriptorV1:
        _safe_id(action_descriptor_id, "action descriptor id")
        descriptor = build_fixed_review_action_registry().get(action_descriptor_id)
        if descriptor is None:
            raise ValidationError("Unknown fixed BOBA Review UI action descriptor.")
        return descriptor

    def _snapshot(self, project_id: str, snapshot_id: str) -> BobaReviewSnapshotV1:
        _safe_id(project_id, "project id")
        _safe_id(snapshot_id, "review snapshot id")
        raw = self.store.load_boba_review_ui_snapshot(project_id, snapshot_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA Review UI snapshot is unavailable.")
        snapshot = BobaReviewSnapshotV1.model_validate(raw)
        if snapshot.project_id != project_id:
            raise ValidationError("Review snapshot belongs to another project.")
        return snapshot

    def _action_request(self, project_id: str, request_id: str) -> BobaReviewActionRequestV1:
        _safe_id(project_id, "project id")
        _safe_id(request_id, "review action request id")
        raw = self.store.load_boba_review_ui_action(project_id, request_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA Review UI action request is unavailable.")
        request = BobaReviewActionRequestV1.model_validate(raw)
        if request.project_id != project_id:
            raise ValidationError("Review action belongs to another project.")
        return request

    @staticmethod
    def _sections(
        snapshot: BobaReviewSnapshotV1,
        cards: list[BobaReviewSourceCardV1],
    ) -> list[BobaReviewSectionV1]:
        sections: list[BobaReviewSectionV1] = []
        for kind, title in _SECTION_GROUPS:
            matching = [card for card in cards if card.authority_domain == kind]
            visible_cards = cards if kind == "overview" else matching
            sections.append(
                BobaReviewSectionV1(
                    review_section_id=_stable_id(
                        "review_section", snapshot.review_snapshot_id, kind
                    ),
                    review_snapshot_id=snapshot.review_snapshot_id,
                    section_type=kind,
                    title=title,
                    source_card_ids=[card.source_card_id for card in visible_cards],
                    empty=not visible_cards,
                    bounded_empty_message="No canonical source record is available.",
                )
            )
        return sections

    def _event_rows(
        self,
        project_id: str,
        module_id: str,
        payload: Mapping[str, Any],
    ) -> list[BobaReviewUiEventV1]:
        rows: list[Mapping[str, Any]] = []
        for key in (
            "events",
            "workflow_events",
            "validation_events",
            "report_events",
            "artifact_events",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(item for item in value[-_MAX_EVENTS:] if isinstance(item, Mapping))
        events: list[BobaReviewUiEventV1] = []
        for row in rows:
            safe = _as_mapping(_safe_payload(row))
            event_id = _first_text(safe, "event_id", "source_event_id", "id") or _stable_id(
                "review_event", module_id, _digest(safe)
            )
            raw_sequence = safe.get("sequence")
            sequence = raw_sequence if isinstance(raw_sequence, int) and raw_sequence >= 0 else None
            raw_current = safe.get("progress_current")
            raw_total = safe.get("progress_total")
            current = raw_current if isinstance(raw_current, int) and raw_current >= 0 else None
            total = raw_total if isinstance(raw_total, int) and raw_total > 0 else None
            percent = (
                min(100.0, current / total * 100) if current is not None and total else None
            )
            events.append(
                BobaReviewUiEventV1(
                    ui_event_id=_stable_id("review_event", module_id, event_id),
                    project_id=project_id,
                    source_module_id=module_id,
                    source_event_id=event_id,
                    source_sequence=sequence,
                    created_at=(
                        _first_text(safe, "created_at", "occurred_at", "timestamp") or None
                    ),
                    event_type=_first_text(safe, "event_type", "type") or "canonical_event",
                    severity=_first_text(safe, "severity") or "informational",
                    technical_message=_first_text(
                        safe, "technical_message", "message", "summary"
                    ),
                    easy_message=_first_text(safe, "easy_message", "summary", "message"),
                    confirmed_fact=_first_text(safe, "confirmed_fact"),
                    assessment=_first_text(safe, "assessment"),
                    progress_current=current,
                    progress_total=total,
                    progress_percent=percent,
                    requires_attention=bool(safe.get("requires_attention")),
                    canonical=True,
                    replayed=bool(safe.get("replayed")),
                )
            )
        return events

    @staticmethod
    def _timeline_entry(event: BobaReviewUiEventV1) -> BobaReviewTimelineEntryV1:
        return BobaReviewTimelineEntryV1(
            timeline_entry_id=_stable_id("review_timeline", event.ui_event_id),
            source_module_id=event.source_module_id,
            source_record_id=event.source_event_id or event.ui_event_id,
            source_event_id=event.source_event_id,
            event_type=event.event_type,
            occurred_at=event.created_at,
            timestamp_precision="source" if event.created_at else "unknown",
            sequence=event.source_sequence,
            confirmed_order=event.source_sequence is not None,
            title=event.event_type.replace("_", " ").title() or "Canonical Event",
            bounded_summary=event.easy_message,
            confirmed_fact=event.confirmed_fact,
            source_assessment=event.assessment,
            review_ui_explanation=event.easy_message,
            severity=event.severity,
            current=not event.replayed,
            historical=event.replayed,
        )

    def _notifications(
        self,
        project_id: str,
        cards: list[BobaReviewSourceCardV1],
    ) -> list[BobaReviewNotificationV1]:
        notifications: list[BobaReviewNotificationV1] = []
        for card in cards:
            if not (card.blocking or card.human_review_required or card.stale):
                continue
            target = self._target_from_card(project_id, card, cards)
            notification_type = (
                "blocking"
                if card.blocking
                else "human_review_required"
                if card.human_review_required
                else "stale"
            )
            notifications.append(
                BobaReviewNotificationV1(
                    notification_id=_stable_id(
                        "review_notification",
                        project_id,
                        card.source_card_id,
                        card.original_status,
                    ),
                    project_id=project_id,
                    review_target_id=target.review_target_id,
                    source_module_id=card.source_module_id,
                    source_record_id=card.source_record_id,
                    notification_type=notification_type,
                    severity=(
                        "critical"
                        if card.display_category == "critical_attention"
                        else "warning"
                    ),
                    title=card.title,
                    bounded_message=card.bounded_summary,
                    requires_attention=True,
                    human_action_required=card.human_review_required,
                    current=card.current,
                    limitations=[
                        "Acknowledging this notice does not resolve the source issue.",
                    ],
                )
            )
        return notifications[:64]

    @staticmethod
    def _summary(
        queue_rows: list[dict[str, Any]],
        events: list[dict[str, Any]],
        cards: list[BobaReviewSourceCardV1],
    ) -> BobaReviewUiSummaryV1:
        categories = [str(item.get("display_category") or "") for item in queue_rows]
        top = queue_rows[0] if queue_rows else {}
        required = [
            f"{card.title}: {card.priority_reason}"
            for card in cards
            if card.human_review_required or card.blocking
        ]
        return BobaReviewUiSummaryV1(
            total_queue_item_count=len(queue_rows),
            critical_attention_count=categories.count("critical_attention"),
            blocked_count=categories.count("blocked"),
            human_review_required_count=categories.count("human_review_required"),
            ready_for_review_count=categories.count("ready_for_review"),
            awaiting_evidence_count=categories.count("awaiting_evidence"),
            current_target_id=_safe_text(top.get("target_id"), 180) or None,
            current_review_mode=_safe_text(top.get("review_mode"), 80) or None,
            current_blocker_count=sum(1 for card in cards if card.blocking),
            current_missing_evidence_count=sum(1 for card in cards if not card.current),
            current_conflict_count=sum(1 for card in cards if card.conflict_detected),
            latest_canonical_event_at=max(
                (str(item.get("created_at") or "") for item in events), default=""
            )
            or None,
            event_stream_connected=False,
            safest_next_review_action=(
                "Review the highest-priority canonical source record."
                if queue_rows
                else "No canonical review work is outstanding."
            ),
            required_human_actions=required[:24],
            limitations=[
                "Counts describe projected canonical records, not Review UI decisions.",
            ],
        )

    @staticmethod
    def _signal_usage(cards: list[BobaReviewSourceCardV1]) -> BobaReviewUiSignalUsageV1:
        def used(module_id: str) -> bool:
            return any(
                card.source_module_id == module_id and card.current for card in cards
            )

        return BobaReviewUiSignalUsageV1(
            workflow_controller_used=used("workflow_controller"),
            rights_gate_used=used("rights_permission_gate"),
            safety_gate_used=used("safety_gate"),
            validator_runner_used=used("validator_runner"),
            output_quality_reviewer_used=used("output_quality_reviewer"),
            artifact_inspector_used=used("artifact_inspector"),
            report_reader_used=used("report_reader"),
            autopilot_used=used("autopilot_controller"),
            final_decision_bus_used=used("final_decision_bus"),
            integration_layer_used=used("integration_layer"),
            unavailable_signals=[
                card.source_module_id for card in cards if not card.current
            ],
            limitations=[
                "Signal usage records which canonical owners were read, not who decided.",
            ],
        )

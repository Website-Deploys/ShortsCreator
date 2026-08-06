"""Read-only BOBA Error Doctor review projections and constrained action routing.

The Error Doctor Panel is a specialized mode of the BOBA Review UI. It is a
trusted incident projection, an evidence workspace, a diagnosis and root-cause
comparison surface, a recovery-history viewer and a safe canonical action router.

It never detects an error, creates an incident, diagnoses anything, determines a
root cause, creates a repair plan, executes a repair or recovery, restores a
checkpoint, transitions a workflow, modifies code, artifacts or media, runs a
command, shell, Git or FFmpeg, installs or downloads a tool, uploads or
publishes. Every value it shows is copied verbatim from the module that owns it.

Ownership chain discovered in this repository and preserved here:

    Observer finding            -> ``finding_id``
    Error Doctor case           -> ``diagnostic_case_id``      (the incident)
    Root Cause Analyzer case    -> ``analysis_case_id``        (``source_diagnostic_case_id``)
    Repair Planner case         -> ``repair_case_id``          (``source_analysis_case_id``)
    Tool Recovery case          -> ``recovery_case_id``        (``source_repair_case_id``)
    Code Surgeon case           -> ``code_repair_case_id``     (``source_repair_case_id``)
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from olympus.boba.contracts import BobaContract, now_iso

# Shared Review UI primitives. Reusing them keeps digest, sanitisation and
# private-path semantics byte-identical to Review UI V1, Candidate Review V1 and
# Clip Brief Review V1, which the confirmation tokens depend on.
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


# Incident identifiers are opaque, source-owned tokens.
_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,180}$")

# The one incident schema this panel understands, taken verbatim from
# ``BobaErrorDoctorSetV1.schema_version``. Anything else is unsupported.
SUPPORTED_INCIDENT_SCHEMA_ID = "boba_error_doctor_v1"

# Secret-value shapes, transcribed from the owning reliability modules
# (``tool_recovery._SECRET_VALUE`` and ``code_surgeon._SECRET_PATTERNS``) so the
# panel redacts exactly what those owners already treat as secret.
_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]+"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
        r"password|secret|authorization|cookie)\b\s*[:=]\s*\"?[^\s\"']+"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s/]+@", re.I),
    re.compile(r"(?i)\b[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|CREDENTIAL)[A-Z0-9_]*=\S+"),
)

MAX_COMPARISON_INCIDENTS = 4
MAX_LOADED_INCIDENTS = 500
MAX_QUEUE_PAGE_SIZE = 50
MAX_TIMELINE_ENTRIES = 100
MAX_ANNOTATIONS = 32
MAX_ANNOTATION_LENGTH = 4_000
MAX_TECHNICAL_MESSAGE_CHARS = 8_192
MAX_EASY_EXPLANATION_CHARS = 4_096
MAX_EXCERPT_CHARS = 16_384
MAX_EXCERPT_LINE_CHARS = 2_048
MAX_EVIDENCE_CARDS = 100
MAX_EXPANDED_SOURCE_CARDS = 20
MAX_EXPANDED_LOG_CARDS = 10

_MAX_EVENTS = 100
_MAX_SOURCE_CARDS = 24
_MAX_DIAGNOSIS_PROJECTIONS = 32
_MAX_ROOT_CAUSE_PROJECTIONS = 64
_MAX_REPAIR_PLAN_PROJECTIONS = 64
_MAX_RECOVERY_PROJECTIONS = 64
_MAX_CONFLICTS = 32
_MAX_REASON_LENGTH = 500

ErrorDoctorReviewFilter = Literal[
    "all_current",
    "critical",
    "workflow_blocking",
    "human_review_required",
    "missing_diagnosis",
    "missing_root_cause",
    "repair_plan_available",
    "failed_recovery",
    "unverified_recovery",
    "recurring",
    "conflicts",
    "missing_evidence",
    "stale",
    "recovered",
    "resolved",
    "historical",
    "superseded",
]
ErrorDoctorReviewSort = Literal[
    "review_priority",
    "source_severity",
    "first_seen",
    "last_seen",
    "affected_stage",
    "affected_module",
    "incident_id",
]
ErrorConflictType = Literal[
    "incident_identity_conflict",
    "workflow_identity_conflict",
    "stage_identity_conflict",
    "error_class_conflict",
    "error_code_conflict",
    "severity_conflict",
    "diagnosis_conflict",
    "root_cause_conflict",
    "repair_plan_conflict",
    "recovery_status_conflict",
    "validation_conflict",
    "artifact_state_conflict",
    "source_digest_conflict",
    "lifecycle_conflict",
    "unknown",
]
ErrorDoctorComparisonType = Literal[
    "side_by_side",
    "recurring_incidents",
    "current_vs_historical",
    "same_stage",
    "same_module",
    "diagnosis",
    "root_cause",
    "repair_plan",
    "recovery_attempt",
    "verification",
    "unknown",
]
EvidenceClassification = Literal[
    "confirmed_fact",
    "source_owned_assessment",
    "source_owned_hypothesis",
    "unresolved_claim",
    "unavailable",
]


# ----------------------------------------------------------------------
# Bounded, redacted text projection
# ----------------------------------------------------------------------
def _redact_secret_values(text: str) -> tuple[str, bool]:
    """Replace secret-shaped substrings. Returns (text, redacted)."""
    redacted = False
    for pattern in _SECRET_VALUE_PATTERNS:
        text, count = pattern.subn("[redacted]", text)
        redacted = redacted or bool(count)
    return (text, redacted)


# Whole-path shapes, transcribed from ``tool_recovery._PRIVATE_PATH`` and
# ``code_surgeon._PRIVATE_PATH``. Review UI's pattern matches only the prefix, so
# the owner-side pattern is applied first to remove the whole path including the
# local user directory name.
_FULL_PRIVATE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"']+|\\\\[^\\\s]+\\[^\s\"']+|"
    r"/(?:home|Users|root|private|tmp)/[^\s\"']+)"
)


def _redact_private_paths(text: str) -> tuple[str, bool]:
    redacted = False
    text, count = _FULL_PRIVATE_PATH.subn("[private-path]", text)
    redacted = bool(count)
    if _PRIVATE_PATH.search(text):
        text = _PRIVATE_PATH.sub("[private-path]", text)
        redacted = True
    return (text, redacted)


def bounded_excerpt(
    value: object,
    *,
    maximum: int = MAX_EXCERPT_CHARS,
    line_maximum: int = MAX_EXCERPT_LINE_CHARS,
) -> dict[str, Any]:
    """Project a log or stack-trace excerpt: line structure kept, secrets removed.

    Unlike ``_safe_text`` this keeps line breaks so a stack trace stays readable,
    while still bounding every line, redacting secret values and private paths,
    and reporting truncation explicitly instead of silently shortening.
    """
    raw = "" if value is None else str(value)
    raw = raw.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    line_truncated = False
    secrets = False
    paths = False
    for line in raw.split("\n")[:512]:
        collapsed = " ".join(line.split())
        collapsed, line_secret = _redact_secret_values(collapsed)
        collapsed, line_path = _redact_private_paths(collapsed)
        secrets = secrets or line_secret
        paths = paths or line_path
        if len(collapsed) > line_maximum:
            collapsed = collapsed[:line_maximum]
            line_truncated = True
        lines.append(collapsed)
    text = "\n".join(lines).strip()
    truncated = line_truncated or len(text) > maximum
    return {
        "text": text[:maximum],
        "truncated": truncated,
        "sensitive_values_redacted": secrets,
        "private_paths_redacted": paths,
    }


def bounded_technical_message(value: object) -> dict[str, Any]:
    return bounded_excerpt(value, maximum=MAX_TECHNICAL_MESSAGE_CHARS)


def bounded_easy_explanation(value: object) -> str:
    return _safe_text(value, MAX_EASY_EXPLANATION_CHARS)


def _seconds_text(value: object) -> str | None:
    text = _safe_text(value, 80)
    return text or None


# ----------------------------------------------------------------------
# Contracts
# ----------------------------------------------------------------------
class BobaErrorDoctorRegistrySnapshotV1(BobaContract):
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = "1"
    created_at: str = Field(default_factory=now_iso)
    incident_source_ids: list[str] = Field(default_factory=list, max_length=24)
    diagnosis_source_ids: list[str] = Field(default_factory=list, max_length=24)
    repair_source_ids: list[str] = Field(default_factory=list, max_length=24)
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


class BobaIncidentReferenceV1(BobaContract):
    incident_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    incident_id: str = Field(min_length=1, max_length=180)
    # The owner schema defines no incident revision identity, so this stays None.
    incident_revision_id: str | None = None
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    source_schema_id: str = Field(default="unknown", max_length=180)
    source_schema_version: str = Field(default="unknown", max_length=80)
    schema_supported: bool = False
    affected_module_id: str = Field(default="", max_length=180)
    affected_operation_id: str = Field(default="", max_length=240)
    affected_stage_id: str = Field(default="", max_length=180)
    error_class: str = Field(default="unknown", max_length=120)
    # Error Doctor defines no error code field, so it stays absent.
    error_code: str | None = None
    original_severity: str = Field(default="unknown", max_length=80)
    original_status: str = Field(default="unknown", max_length=120)
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    superseding_incident_id: str | None = None
    recovered: bool = False
    resolved: bool = False
    source_event_ids: list[str] = Field(default_factory=list, max_length=128)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaErrorDoctorReviewSessionV1(BobaContract):
    error_doctor_review_session_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    reviewer_context_id: str = Field(min_length=1, max_length=160)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    expires_at: str
    selected_incident_id: str | None = None
    comparison_incident_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_INCIDENTS
    )
    active_filter: ErrorDoctorReviewFilter = "all_current"
    active_sort: ErrorDoctorReviewSort = "review_priority"
    active_section_id: str = "overview"
    show_recovered: bool = True
    show_resolved: bool = False
    show_historical: bool = False
    show_technical_details: bool = False
    show_bounded_logs: bool = False
    show_repair_history: bool = True
    evidence_drawer_open: bool = False
    timeline_drawer_open: bool = False
    local_annotations: list[dict[str, str]] = Field(
        default_factory=list, max_length=MAX_ANNOTATIONS
    )
    read_incident_ids: list[str] = Field(default_factory=list, max_length=256)
    session_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaIncidentQueueItemV1(BobaContract):
    incident_queue_item_id: str = Field(min_length=1, max_length=180)
    incident_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    incident_id: str = Field(min_length=1, max_length=180)
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(default="", max_length=900)
    affected_module_id: str = Field(default="", max_length=180)
    affected_operation_id: str = Field(default="", max_length=240)
    affected_stage_id: str = Field(default="", max_length=180)
    original_error_class: str = Field(default="unknown", max_length=120)
    original_error_code: str | None = None
    original_severity: str = Field(default="unknown", max_length=80)
    original_status: str = Field(default="unknown", max_length=120)
    diagnosis_status: str = Field(default="unavailable", max_length=120)
    root_cause_status: str = Field(default="unavailable", max_length=120)
    repair_plan_status: str = Field(default="unavailable", max_length=120)
    recovery_status: str = Field(default="unavailable", max_length=120)
    validation_status: str = Field(default="unavailable", max_length=120)
    artifact_status: str = Field(default="unavailable", max_length=120)
    workflow_status: str = Field(default="unavailable", max_length=120)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    recovered: bool = False
    resolved: bool = False
    recurring: bool = False
    human_action_required: bool = False
    blocker_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    failed_recovery_attempt_count: int = Field(default=0, ge=0)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    source_module_ids: list[str] = Field(default_factory=list, max_length=24)
    source_record_ids: list[str] = Field(default_factory=list, max_length=24)
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=24)
    priority_tier: int = Field(default=0, ge=0, le=999)
    priority_reason: str = Field(default="", max_length=200)
    deterministic_sort_key: str = Field(min_length=1, max_length=240)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaIncidentSnapshotV1(BobaContract):
    incident_snapshot_id: str = Field(min_length=1, max_length=180)
    error_doctor_review_session_id: str = Field(min_length=1, max_length=180)
    incident_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    incident_id: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso)
    refreshed_at: str = Field(default_factory=now_iso)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    incident_digest: str = Field(min_length=64, max_length=64)
    source_record_references: list[dict[str, str]] = Field(
        default_factory=list, max_length=24
    )
    source_record_digests: dict[str, str] = Field(default_factory=dict, max_length=24)
    diagnosis_projection_ids: list[str] = Field(default_factory=list, max_length=32)
    root_cause_projection_ids: list[str] = Field(default_factory=list, max_length=64)
    evidence_card_ids: list[str] = Field(
        default_factory=list, max_length=MAX_EVIDENCE_CARDS
    )
    repair_plan_projection_ids: list[str] = Field(default_factory=list, max_length=64)
    recovery_attempt_projection_ids: list[str] = Field(default_factory=list, max_length=64)
    validation_evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    artifact_evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    conflict_record_ids: list[str] = Field(default_factory=list, max_length=32)
    comparison_ids: list[str] = Field(default_factory=list, max_length=8)
    incident_status: str = Field(default="unknown", max_length=120)
    diagnosis_status: str = Field(default="unavailable", max_length=120)
    root_cause_status: str = Field(default="unavailable", max_length=120)
    repair_plan_status: str = Field(default="unavailable", max_length=120)
    recovery_status: str = Field(default="unavailable", max_length=120)
    validation_status: str = Field(default="unavailable", max_length=120)
    artifact_status: str = Field(default="unavailable", max_length=120)
    workflow_status: str = Field(default="unavailable", max_length=120)
    rights_status: str = Field(default="unavailable", max_length=120)
    safety_status: str = Field(default="unavailable", max_length=120)
    final_decision_status: str = Field(default="unavailable", max_length=120)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    recovered: bool = False
    resolved: bool = False
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    limitation_count: int = Field(default=0, ge=0)
    available_action_descriptor_ids: list[str] = Field(default_factory=list, max_length=32)
    confirmation_context_digest: str = Field(min_length=64, max_length=64)
    snapshot_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaDiagnosisProjectionV1(BobaContract):
    diagnosis_projection_id: str = Field(min_length=1, max_length=180)
    incident_snapshot_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    diagnosis_id: str = Field(min_length=1, max_length=180)
    # Error Doctor defines no diagnosis revision identity.
    diagnosis_revision_id: str | None = None
    original_status: str = Field(default="unknown", max_length=120)
    original_category: str = Field(default="unknown", max_length=120)
    original_error_class: str = Field(default="unknown", max_length=120)
    original_error_code: str | None = None
    original_summary: str = Field(default="", max_length=900)
    bounded_technical_explanation: str = Field(
        default="", max_length=MAX_TECHNICAL_MESSAGE_CHARS
    )
    bounded_easy_explanation: str = Field(
        default="", max_length=MAX_EASY_EXPLANATION_CHARS
    )
    confirmed_fact_ids: list[str] = Field(default_factory=list, max_length=32)
    assessment_ids: list[str] = Field(default_factory=list, max_length=32)
    hypothesis_ids: list[str] = Field(default_factory=list, max_length=32)
    confidence_value: float | None = None
    confidence_name: str = Field(default="", max_length=120)
    confidence_definition: str = Field(default="", max_length=700)
    confidence_scale_min: float | None = None
    confidence_scale_max: float | None = None
    confidence_comparable_across_sources: bool = False
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    authoritative: bool = True
    advisory: bool = False
    sensitive_values_redacted: bool = False
    private_paths_redacted: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRootCauseProjectionV1(BobaContract):
    root_cause_projection_id: str = Field(min_length=1, max_length=180)
    incident_snapshot_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    root_cause_id: str = Field(min_length=1, max_length=180)
    root_cause_revision_id: str | None = None
    original_status: str = Field(default="unknown", max_length=120)
    original_classification: str = Field(default="unknown", max_length=120)
    original_summary: str = Field(default="", max_length=900)
    confirmed: bool = False
    hypothesis: bool = True
    evidence_record_ids: list[str] = Field(default_factory=list, max_length=64)
    contradictory_evidence_record_ids: list[str] = Field(
        default_factory=list, max_length=64
    )
    confidence_value: float | None = None
    confidence_name: str = Field(default="", max_length=120)
    confidence_definition: str = Field(default="", max_length=700)
    likelihood_value: float | None = None
    likelihood_name: str = Field(default="", max_length=120)
    evidence_quality: str = Field(default="unknown", max_length=120)
    repairability: str = Field(default="unknown", max_length=120)
    recommended_owner_module_id: str = Field(default="", max_length=180)
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    human_confirmation_required: bool = True
    bounded_explanation: str = Field(default="", max_length=MAX_EASY_EXPLANATION_CHARS)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_exclusive_confirmation(self) -> BobaRootCauseProjectionV1:
        if self.confirmed and self.hypothesis:
            raise ValueError(
                "A root cause cannot be both confirmed and a hypothesis."
            )
        return self


class BobaErrorEvidenceCardV1(BobaContract):
    evidence_card_id: str = Field(min_length=1, max_length=180)
    incident_snapshot_id: str | None = None
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
    classification: EvidenceClassification = "unavailable"
    confirmed_fact: str = Field(default="", max_length=900)
    assessment: str = Field(default="", max_length=900)
    hypothesis: str = Field(default="", max_length=900)
    bounded_summary: str = Field(default="", max_length=900)
    bounded_excerpt: str = Field(default="", max_length=MAX_EXCERPT_CHARS)
    excerpt_truncated: bool = False
    sensitive_values_redacted: bool = False
    private_paths_redacted: bool = False
    current: bool = False
    stale: bool = False
    historical: bool = False
    missing: bool = False
    authoritative: bool = True
    advisory_only: bool = False
    blocking: bool = False
    supports_diagnosis_ids: list[str] = Field(default_factory=list, max_length=16)
    supports_root_cause_ids: list[str] = Field(default_factory=list, max_length=32)
    supports_repair_plan_ids: list[str] = Field(default_factory=list, max_length=32)
    supports_recovery_attempt_ids: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRepairPlanProjectionV1(BobaContract):
    repair_plan_projection_id: str = Field(min_length=1, max_length=180)
    incident_snapshot_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    repair_plan_id: str = Field(min_length=1, max_length=180)
    repair_plan_revision_id: str | None = None
    original_status: str = Field(default="unknown", max_length=120)
    original_strategy: str = Field(default="unknown", max_length=120)
    original_summary: str = Field(default="", max_length=900)
    affected_module_ids: list[str] = Field(default_factory=list, max_length=32)
    affected_operation_ids: list[str] = Field(default_factory=list, max_length=32)
    proposed_step_count: int = Field(default=0, ge=0)
    proposed_step_summaries: list[str] = Field(default_factory=list, max_length=32)
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
    source_owned_rank: int | None = None
    source_owned_score: float | None = None
    source_owned_score_name: str = Field(default="", max_length=120)
    source_marked_recommended: bool = False
    current: bool = True
    stale: bool = False
    historical: bool = False
    superseded: bool = False
    # The panel never executes a repair. This is pinned by the contract.
    executable_by_panel: Literal[False] = False
    raw_command_exposed: Literal[False] = False
    bounded_explanation: str = Field(default="", max_length=MAX_EASY_EXPLANATION_CHARS)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaRecoveryAttemptProjectionV1(BobaContract):
    recovery_attempt_projection_id: str = Field(min_length=1, max_length=180)
    incident_snapshot_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    source_record_digest: str = Field(min_length=64, max_length=64)
    recovery_attempt_id: str = Field(min_length=1, max_length=180)
    repair_plan_id: str = Field(default="", max_length=180)
    attempt_number: int | None = None
    original_status: str = Field(default="unknown", max_length=120)
    started_at: str | None = None
    completed_at: str | None = None
    attempted: bool = False
    completed: bool = False
    succeeded_by_owner: bool = False
    verified: bool = False
    verification_source_ids: list[str] = Field(default_factory=list, max_length=16)
    changed_code: bool = False
    changed_artifacts: bool = False
    changed_workflow: bool = False
    invoked_tool: str = Field(default="", max_length=180)
    invoked_operation_id: str = Field(default="", max_length=240)
    rollback_attempted: bool = False
    rollback_status: str = Field(default="unavailable", max_length=120)
    original_error_code: str | None = None
    resulting_error_code: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    current: bool = True
    stale: bool = False
    historical: bool = False
    bounded_summary: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_recovery_claims(self) -> BobaRecoveryAttemptProjectionV1:
        if self.completed and not self.attempted:
            raise ValueError("A recovery attempt cannot complete without being attempted.")
        if self.succeeded_by_owner and not self.attempted:
            raise ValueError("Owner-reported success requires an attempt.")
        return self


class BobaErrorConflictV1(BobaContract):
    conflict_record_id: str = Field(min_length=1, max_length=180)
    incident_snapshot_id: str | None = None
    conflict_type: ErrorConflictType = "unknown"
    severity: str = Field(default="warning", max_length=80)
    source_record_ids: list[str] = Field(default_factory=list, max_length=16)
    source_record_digests: list[str] = Field(default_factory=list, max_length=16)
    diagnosis_projection_ids: list[str] = Field(default_factory=list, max_length=16)
    root_cause_projection_ids: list[str] = Field(default_factory=list, max_length=16)
    repair_plan_projection_ids: list[str] = Field(default_factory=list, max_length=16)
    recovery_attempt_projection_ids: list[str] = Field(default_factory=list, max_length=16)
    value_a: str = Field(default="", max_length=900)
    value_b: str = Field(default="", max_length=900)
    same_incident: bool = False
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
            "Conflicts are reported only between records that name the same exact "
            "identity, and are never resolved by comparing or averaging confidence.",
        ],
        max_length=16,
    )


class BobaErrorDoctorComparisonV1(BobaContract):
    comparison_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    incident_ids: list[str] = Field(min_length=2, max_length=MAX_COMPARISON_INCIDENTS)
    created_at: str = Field(default_factory=now_iso)
    comparison_type: ErrorDoctorComparisonType = "side_by_side"
    same_workflow_run: bool = False
    same_stage: bool = False
    same_affected_module: bool = False
    incident_snapshot_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_INCIDENTS
    )
    error_class_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    severity_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    diagnosis_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    root_cause_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    evidence_coverage_comparison: list[dict[str, Any]] = Field(
        default_factory=list, max_length=8
    )
    repair_plan_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    recovery_history_comparison: list[dict[str, Any]] = Field(
        default_factory=list, max_length=8
    )
    validation_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    artifact_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    warning_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    limitation_comparison: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    current_incident_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_INCIDENTS
    )
    historical_incident_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_INCIDENTS
    )
    no_automatic_winner: Literal[True] = True
    no_automatic_root_cause_selection: Literal[True] = True
    no_automatic_repair_selection: Literal[True] = True
    bounded_summary: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaErrorDoctorActionDescriptorV1(BobaContract):
    action_descriptor_id: str = Field(min_length=1, max_length=180)
    display_name: str = Field(min_length=1, max_length=160)
    action_class: str = Field(min_length=1, max_length=120)
    owning_module_id: str = Field(min_length=1, max_length=180)
    owning_operation_id: str = Field(min_length=1, max_length=240)
    supported_incident_states: list[str] = Field(default_factory=list, max_length=16)
    allowed_decision_values: list[str] = Field(default_factory=list, max_length=16)
    requires_reason: bool = False
    maximum_reason_length: int = Field(default=_MAX_REASON_LENGTH, ge=0, le=1_200)
    requires_confirmation: bool = True
    requires_current_snapshot: bool = True
    requires_workflow_revision: bool = False
    requires_incident_digest: bool = True
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
    upload_or_publication: bool = False
    allowed_in_v1: bool = False
    availability: Literal["available", "unavailable"] = "unavailable"
    consequences: list[str] = Field(default_factory=list, max_length=12)
    does_not_do: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaErrorDoctorActionRequestV1(BobaContract):
    error_doctor_action_request_id: str = Field(min_length=1, max_length=180)
    error_doctor_review_session_id: str = Field(min_length=1, max_length=180)
    incident_snapshot_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str | None = None
    stage_instance_id: str | None = None
    incident_id: str = Field(min_length=1, max_length=180)
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
    expected_incident_digest: str = Field(min_length=64, max_length=64)
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


class BobaErrorDoctorActionReceiptV1(BobaContract):
    error_doctor_action_receipt_id: str = Field(min_length=1, max_length=180)
    error_doctor_action_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    incident_id: str = Field(min_length=1, max_length=180)
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
    repair_executed: bool = False
    recovery_attempt_started: bool = False
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


class BobaErrorDoctorReviewEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    incident_id: str | None = None
    source_module_id: str = Field(min_length=1, max_length=180)
    source_event_id: str = Field(default="", max_length=180)
    source_sequence: int | None = None
    created_at: str | None = None
    received_at: str = Field(default_factory=now_iso)
    event_type: str = Field(default="canonical_event", max_length=160)
    severity: str = Field(default="informational", max_length=80)
    technical_message: str = Field(default="", max_length=MAX_TECHNICAL_MESSAGE_CHARS)
    easy_message: str = Field(default="", max_length=MAX_EASY_EXPLANATION_CHARS)
    confirmed_fact: str = Field(default="", max_length=900)
    assessment: str = Field(default="", max_length=900)
    progress_current: int | None = None
    progress_total: int | None = None
    progress_percent: float | None = None
    requires_attention: bool = False
    canonical: bool = True
    replayed: bool = False
    represents_work: bool = True
    sensitive_values_redacted: bool = False
    private_paths_redacted: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaErrorDoctorReviewTimelineEntryV1(BobaContract):
    timeline_entry_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    incident_id: str | None = None
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
    confirmed_fact: str = Field(default="", max_length=900)
    source_assessment: str = Field(default="", max_length=900)
    severity: str = Field(default="informational", max_length=80)
    current: bool = True
    historical: bool = False


class BobaErrorDoctorReviewNotificationV1(BobaContract):
    notification_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    incident_id: str = Field(min_length=1, max_length=180)
    source_module_id: str = Field(min_length=1, max_length=180)
    source_record_id: str = Field(min_length=1, max_length=180)
    notification_type: str = Field(default="warning", max_length=120)
    severity: str = Field(default="warning", max_length=80)
    title: str = Field(min_length=1, max_length=240)
    bounded_message: str = Field(default="", max_length=900)
    requires_attention: bool = True
    human_action_required: bool = False
    current: bool = True
    acknowledgeable: bool = True
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaErrorDoctorReviewSummaryV1(BobaContract):
    total_incident_count: int = Field(default=0, ge=0)
    current_incident_count: int = Field(default=0, ge=0)
    stale_incident_count: int = Field(default=0, ge=0)
    historical_incident_count: int = Field(default=0, ge=0)
    unresolved_incident_count: int = Field(default=0, ge=0)
    recovered_incident_count: int = Field(default=0, ge=0)
    resolved_incident_count: int = Field(default=0, ge=0)
    recurring_incident_count: int = Field(default=0, ge=0)
    critical_incident_count: int = Field(default=0, ge=0)
    incidents_missing_diagnosis_count: int = Field(default=0, ge=0)
    incidents_missing_root_cause_count: int = Field(default=0, ge=0)
    incidents_with_repair_plan_count: int = Field(default=0, ge=0)
    incidents_with_failed_recovery_count: int = Field(default=0, ge=0)
    incidents_requiring_human_review_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    current_selected_incident_id: str | None = None
    current_comparison_incident_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COMPARISON_INCIDENTS
    )
    safest_next_review_action: str = Field(default="", max_length=700)
    required_human_actions: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaErrorDoctorReviewSignalUsageV1(BobaContract):
    canonical_observer_records: bool = False
    canonical_error_doctor_records: bool = False
    canonical_root_cause_records: bool = False
    canonical_repair_plan_records: bool = False
    canonical_code_surgeon_records: bool = False
    canonical_tool_recovery_records: bool = False
    canonical_output_quality_records: bool = False
    canonical_workflow_records: bool = False
    canonical_validator_records: bool = False
    canonical_report_reader_records: bool = False
    canonical_artifact_records: bool = False
    canonical_safety_records: bool = False
    canonical_final_decision_records: bool = False
    review_ui_integration: bool = True
    exact_identity_validation: bool = True
    exact_digest_validation: bool = True
    stale_snapshot_protection: bool = True
    bounded_log_projection: bool = True
    sensitive_value_redaction: bool = True
    private_path_redaction: bool = True
    canonical_action_receipts: bool = True
    truthful_events: bool = True
    incident_created_by_panel: Literal[False] = False
    diagnosis_created_by_panel: Literal[False] = False
    root_cause_created_by_panel: Literal[False] = False
    repair_plan_created_by_panel: Literal[False] = False
    repair_executed_by_panel: Literal[False] = False
    recovery_executed_by_panel: Literal[False] = False
    checkpoint_restored_by_panel: Literal[False] = False
    workflow_changed_by_panel: Literal[False] = False
    code_modified_by_panel: Literal[False] = False
    artifact_modified_by_panel: Literal[False] = False
    hidden_incident_score_created: Literal[False] = False
    hidden_repair_score_created: Literal[False] = False
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
    upload_used: Literal[False] = False
    publication_used: Literal[False] = False
    external_analytics_used: Literal[False] = False
    rights_bypass_used: Literal[False] = False
    safety_bypass_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaErrorDoctorReviewSetV1(BobaContract):
    schema_version: Literal["boba_error_doctor_review_v1"] = "boba_error_doctor_review_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    registry_snapshots: list[BobaErrorDoctorRegistrySnapshotV1] = Field(
        default_factory=list, max_length=8
    )
    review_sessions: list[BobaErrorDoctorReviewSessionV1] = Field(
        default_factory=list, max_length=16
    )
    incident_references: list[BobaIncidentReferenceV1] = Field(
        default_factory=list, max_length=MAX_LOADED_INCIDENTS
    )
    incident_queue_items: list[BobaIncidentQueueItemV1] = Field(
        default_factory=list, max_length=MAX_LOADED_INCIDENTS
    )
    incident_snapshots: list[BobaIncidentSnapshotV1] = Field(
        default_factory=list, max_length=16
    )
    diagnosis_projections: list[BobaDiagnosisProjectionV1] = Field(
        default_factory=list, max_length=64
    )
    root_cause_projections: list[BobaRootCauseProjectionV1] = Field(
        default_factory=list, max_length=128
    )
    evidence_cards: list[BobaErrorEvidenceCardV1] = Field(
        default_factory=list, max_length=256
    )
    repair_plan_projections: list[BobaRepairPlanProjectionV1] = Field(
        default_factory=list, max_length=128
    )
    recovery_attempt_projections: list[BobaRecoveryAttemptProjectionV1] = Field(
        default_factory=list, max_length=128
    )
    validation_evidence: list[BobaErrorEvidenceCardV1] = Field(
        default_factory=list, max_length=128
    )
    artifact_evidence: list[BobaErrorEvidenceCardV1] = Field(
        default_factory=list, max_length=128
    )
    conflict_records: list[BobaErrorConflictV1] = Field(
        default_factory=list, max_length=128
    )
    comparisons: list[BobaErrorDoctorComparisonV1] = Field(
        default_factory=list, max_length=8
    )
    action_requests: list[BobaErrorDoctorActionRequestV1] = Field(
        default_factory=list, max_length=32
    )
    action_receipts: list[BobaErrorDoctorActionReceiptV1] = Field(
        default_factory=list, max_length=32
    )
    timeline_entries: list[BobaErrorDoctorReviewTimelineEntryV1] = Field(
        default_factory=list, max_length=MAX_TIMELINE_ENTRIES
    )
    events: list[BobaErrorDoctorReviewEventV1] = Field(
        default_factory=list, max_length=_MAX_EVENTS
    )
    notifications: list[BobaErrorDoctorReviewNotificationV1] = Field(
        default_factory=list, max_length=64
    )
    review_summary: BobaErrorDoctorReviewSummaryV1
    signal_usage: BobaErrorDoctorReviewSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


# ----------------------------------------------------------------------
# Fixed registries
# ----------------------------------------------------------------------
# (module_id, title, authority_domain, store loader, source class, advisory_only)
# Every loader name is a real ``BobaMemoryStore`` method verified during the
# audit. This table is source code: a request can never add a module, a loader,
# a URL, a path or a command.
_ERROR_SOURCES: tuple[tuple[str, str, str, str, str, bool], ...] = (
    (
        "error_doctor",
        "Error Doctor",
        "diagnosis",
        "load_boba_error_doctor",
        "incident",
        False,
    ),
    ("observer", "Observer", "observation", "load_observer_report", "incident", False),
    (
        "root_cause_analyzer",
        "Root Cause Analyzer",
        "root_cause",
        "load_boba_root_cause_analyzer",
        "diagnosis",
        False,
    ),
    (
        "repair_planner",
        "Repair Planner",
        "repair_plan",
        "load_boba_repair_planner",
        "repair",
        False,
    ),
    (
        "code_surgeon",
        "Code Surgeon",
        "code_repair",
        "load_boba_code_surgeon",
        "repair",
        False,
    ),
    (
        "tool_recovery",
        "Tool Recovery",
        "tool_recovery",
        "load_boba_tool_recovery",
        "repair",
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
        "workflow_controller",
        "Workflow Controller",
        "workflow",
        "load_boba_workflow_controller",
        "verification",
        False,
    ),
    ("safety_gate", "Safety Gate", "safety", "load_boba_safety_gate", "verification", False),
    (
        "final_decision_bus",
        "Final Decision Bus",
        "final_decision",
        "load_boba_final_decision_bus",
        "verification",
        False,
    ),
    (
        "autopilot_controller",
        "Autopilot Controller",
        "autopilot",
        "load_boba_autopilot_controller",
        "verification",
        True,
    ),
)

# Only the Error Doctor record is required: it owns the incident identity.
_REQUIRED_SOURCE_IDS = ("error_doctor",)

# Twelve deterministic presentation tiers. A tier is a display order, never a
# score, a danger ranking or a repair-success estimate.
INCIDENT_QUEUE_PRIORITY_TIERS: tuple[tuple[int, str], ...] = (
    (10, "current_critical_incident_with_safety_or_rights_implication"),
    (20, "current_incident_blocking_the_active_workflow"),
    (30, "current_incident_with_failed_or_partial_recovery"),
    (40, "current_incident_with_conflicting_records"),
    (50, "current_incident_without_a_diagnosis"),
    (60, "current_incident_without_a_root_cause_analysis"),
    (70, "current_incident_with_repair_plan_awaiting_human_approval"),
    (80, "current_incident_with_stale_validation_or_artifact_evidence"),
    (90, "current_recurring_incident"),
    (100, "other_unresolved_current_incident"),
    (110, "recovered_but_unverified_incident"),
    (120, "resolved_current_incident"),
    (130, "superseded_incident"),
    (140, "historical_incident"),
)

# Source-owned severity ordering, transcribed from
# ``error_doctor._SEVERITY_RANK`` semantics. Used only for the explicit
# "source severity" sort, never to build a score.
_SEVERITY_ORDER: tuple[str, ...] = (
    "blocker",
    "critical",
    "high",
    "medium",
    "low",
    "informational",
    "unknown",
)

_SECTION_DEFINITIONS: tuple[tuple[str, str, bool], ...] = (
    ("overview", "Incident Overview", False),
    ("diagnosis", "Diagnosis", False),
    ("root_cause", "Root Cause Findings", False),
    ("evidence", "Evidence", False),
    ("repair_plan", "Repair Plans", True),
    ("recovery", "Recovery History", True),
    ("validation", "Validation Evidence", True),
    ("artifacts", "Artifact Evidence", True),
    ("conflicts", "Conflicts", True),
    ("timeline", "Timeline", True),
)


def build_fixed_error_source_registry() -> dict[str, dict[str, Any]]:
    """Return the fixed reliability evidence source registry."""
    registry: dict[str, dict[str, Any]] = {}
    for module_id, title, domain, loader, source_class, advisory in _ERROR_SOURCES:
        if module_id in registry:
            raise ValidationError("Duplicate BOBA error doctor review source descriptor.")
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


def build_fixed_error_section_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for section_id, title, collapsed in _SECTION_DEFINITIONS:
        if section_id in registry:
            raise ValidationError("Duplicate BOBA error doctor review section descriptor.")
        registry[section_id] = {
            "section_id": section_id,
            "title": title,
            "collapsed_by_default": collapsed,
        }
    return registry


def build_fixed_error_doctor_action_registry() -> (
    dict[str, BobaErrorDoctorActionDescriptorV1]
):
    """Return the fixed action registry.

    Only one action is available in V1. The Review UI already owns an
    ``incident``-targeted acknowledgement operation
    (``review_action_acknowledge_notification_v1`` declares ``incident`` in
    ``supported_target_types`` and ``incident_review`` in
    ``supported_review_modes``), and that operation changes review-session
    metadata only.

    Every other action named in the panel brief is declared unavailable with the
    exact reason discovered during the audit. No substitute owner is invented.
    """
    definitions = [
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_acknowledge_incident_v1",
            display_name="Acknowledge incident",
            action_class="ui_metadata_acknowledgement",
            owning_module_id="review_ui",
            owning_operation_id="acknowledge_notification",
            supported_incident_states=["current", "stale", "recovered", "resolved"],
            allowed_decision_values=["acknowledged"],
            requires_reason=False,
            requires_confirmation=True,
            requires_current_snapshot=False,
            requires_incident_digest=True,
            requires_source_record_digests=False,
            requires_reviewer_context=True,
            authoritative=False,
            allowed_in_v1=True,
            availability="available",
            consequences=[
                "Records this incident identity in the Review UI session's "
                "acknowledged notification list, which Review UI owns.",
            ],
            does_not_do=[
                "Does not resolve, dismiss or close the incident.",
                "Does not change the diagnosis, root cause or repair plan.",
                "Does not start, approve or verify a recovery attempt.",
                "Does not restore a checkpoint or change the workflow.",
                "Does not modify code, artifacts or media.",
                "Does not grant Rights or Safety approval.",
                "Does not run a command, shell, Git or FFmpeg.",
                "Does not upload or publish anything.",
            ],
            limitations=[
                "Acknowledgement is review-session metadata. The incident stays "
                "visible until its owning module resolves it.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_request_diagnosis_refresh_v1",
            display_name="Request diagnosis refresh",
            action_class="diagnosis_refresh_request",
            owning_module_id="error_doctor",
            owning_operation_id="unavailable_no_per_incident_diagnosis_refresh",
            supported_incident_states=["current"],
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Error Doctor owns the diagnosis but exposes no operation that "
                "refreshes one exact diagnostic case.",
                "Its only entry point, error_doctor.generate, rebuilds the whole "
                "diagnostic set from Observer, which would make this panel "
                "trigger diagnosis for the entire project.",
                "Unavailable in V1. No substitute owner was invented.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_request_root_cause_review_v1",
            display_name="Request root-cause review",
            action_class="root_cause_review_request",
            owning_module_id="root_cause_analyzer",
            owning_operation_id="unavailable_no_per_incident_root_cause_review",
            supported_incident_states=["current"],
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Root Cause Analyzer exposes no operation that reviews one exact "
                "analysis case; root_cause_analyzer.generate rebuilds the whole set.",
                "Every analysis case already pins human_review_required=True, so "
                "the owner is already requesting human review.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_approve_repair_plan_v1",
            display_name="Approve repair plan",
            action_class="human_repair_approval",
            owning_module_id="repair_planner",
            owning_operation_id="unavailable_no_canonical_repair_approval_operation",
            supported_incident_states=["current"],
            allowed_decision_values=["approve"],
            requires_reason=True,
            requires_workflow_revision=True,
            requires_safety_gate=True,
            requires_final_decision_bus=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Repair Planner records an approval gate but exposes no operation "
                "that records a human approval decision for it.",
                "Its registered operations are load, generate, export and reset only.",
                "Approving a repair would also require a Safety Gate "
                "classification and Final Decision Bus authorisation that no "
                "existing operation binds to a repair plan.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_reject_repair_plan_v1",
            display_name="Reject repair plan",
            action_class="human_repair_rejection",
            owning_module_id="repair_planner",
            owning_operation_id="unavailable_no_canonical_repair_rejection_operation",
            supported_incident_states=["current"],
            allowed_decision_values=["reject"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "No owning operation records a human rejection for a repair plan.",
                "Repair plan status is recomputed by Repair Planner, not edited.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_request_repair_plan_revision_v1",
            display_name="Request repair-plan revision",
            action_class="human_revision_request",
            owning_module_id="repair_planner",
            owning_operation_id="unavailable_no_canonical_revision_request_operation",
            supported_incident_states=["current"],
            allowed_decision_values=["request_revision"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Repair plans carry no revision identity, so a revision request "
                "has nothing canonical to bind to.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_request_recovery_attempt_v1",
            display_name="Request recovery attempt",
            action_class="recovery_execution_request",
            owning_module_id="tool_recovery_brain",
            owning_operation_id="unavailable_execution_action_withheld_in_v1",
            supported_incident_states=["current"],
            requires_reason=True,
            requires_workflow_revision=True,
            requires_safety_gate=True,
            requires_final_decision_bus=True,
            authoritative=True,
            destructive=True,
            execution_capable=True,
            artifact_modifying=True,
            availability="unavailable",
            limitations=[
                "tool_recovery_brain.execute_approved is an approved_execution "
                "operation that starts real tool processes.",
                "Error Doctor Panel V1 exposes no execution action; recovery must "
                "be started through its own approval chain, not from a panel.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_request_tool_retry_v1",
            display_name="Request tool retry",
            action_class="tool_retry_request",
            owning_module_id="tool_recovery_brain",
            owning_operation_id="unavailable_execution_action_withheld_in_v1",
            supported_incident_states=["current"],
            requires_reason=True,
            requires_safety_gate=True,
            authoritative=True,
            execution_capable=True,
            availability="unavailable",
            limitations=[
                "A tool retry runs a real command through Tool Recovery's "
                "approved_execution path and is withheld from the panel.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_request_checkpoint_recovery_v1",
            display_name="Request checkpoint recovery",
            action_class="checkpoint_recovery_request",
            owning_module_id="workflow_controller",
            owning_operation_id="unavailable_resume_is_future_gated",
            supported_incident_states=["current"],
            requires_reason=True,
            requires_workflow_revision=True,
            authoritative=True,
            execution_capable=True,
            workflow_modifying=True,
            availability="unavailable",
            limitations=[
                "workflow_controller.resume is registered as future_gated, so no "
                "checkpoint restoration entry point is available at all.",
                "Restoring a checkpoint changes generated state and workflow "
                "position, which this panel must never do.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_escalate_incident_v1",
            display_name="Escalate incident",
            action_class="escalation_request",
            owning_module_id="error_doctor",
            owning_operation_id="unavailable_no_canonical_escalation_operation",
            supported_incident_states=["current"],
            requires_reason=True,
            authoritative=True,
            availability="unavailable",
            limitations=[
                "Error Doctor and Root Cause Analyzer record escalation handoff "
                "documents, but no module exposes an operation that creates one.",
                "The escalation_target already recorded on the diagnostic case is "
                "shown instead.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_submit_incident_feedback_v1",
            display_name="Submit incident feedback",
            action_class="advisory_creator_feedback",
            owning_module_id="creator_learning",
            owning_operation_id="unavailable_no_incident_feedback_target_type",
            supported_incident_states=["current", "stale", "historical"],
            requires_reason=True,
            availability="unavailable",
            limitations=[
                "Creator Learning owns advisory feedback, but its "
                "BobaCreatorFeedbackTargetType vocabulary is creative-artifact "
                "scoped and defines no incident, error, diagnosis or repair target.",
                "Recording incident feedback against the project target would "
                "misattribute the canonical record, so it is not offered.",
            ],
        ),
        BobaErrorDoctorActionDescriptorV1(
            action_descriptor_id="error_doctor_action_record_incident_review_note_v1",
            display_name="Record incident review note",
            action_class="advisory_reviewer_note",
            owning_module_id="creator_learning",
            owning_operation_id="unavailable_no_incident_note_target_type",
            supported_incident_states=["current", "stale", "historical"],
            requires_reason=True,
            availability="unavailable",
            limitations=[
                "No canonical owner accepts an incident-scoped reviewer note.",
                "Review-session annotations are offered instead and are always "
                "labelled as not part of the canonical incident record.",
            ],
        ),
    ]
    registry: dict[str, BobaErrorDoctorActionDescriptorV1] = {}
    for descriptor in definitions:
        if descriptor.action_descriptor_id in registry:
            raise ValidationError("Duplicate BOBA error doctor review action descriptor.")
        if descriptor.availability == "available" and descriptor.authoritative:
            raise ValidationError(
                "Error Doctor Review V1 exposes no authoritative incident action."
            )
        if descriptor.availability == "available" and (
            descriptor.execution_capable
            or descriptor.destructive
            or descriptor.code_modifying
            or descriptor.artifact_modifying
            or descriptor.workflow_modifying
            or descriptor.upload_or_publication
        ):
            raise ValidationError(
                "Error Doctor Review V1 cannot expose an execution, destructive, "
                "code-modifying, artifact-modifying, workflow-modifying, upload or "
                "publication action."
            )
        registry[descriptor.action_descriptor_id] = descriptor
    return registry


def descriptor_does_not_do(action_descriptor_id: str) -> list[str]:
    """Return the fixed non-consequence list for an action descriptor."""
    descriptor = build_fixed_error_doctor_action_registry().get(action_descriptor_id)
    return list(descriptor.does_not_do) if descriptor else []


def incident_queue_priority_tiers() -> tuple[tuple[int, str], ...]:
    return INCIDENT_QUEUE_PRIORITY_TIERS


def source_severity_order() -> tuple[str, ...]:
    return _SEVERITY_ORDER


class BobaErrorDoctorReviewV1:
    """Read-only reliability review projections and constrained action routing."""

    def __init__(self, store: BobaMemoryStore, integration: BobaIntegration) -> None:
        self.store = store
        self.integration = integration

    # ------------------------------------------------------------------
    # Trusted source access
    # ------------------------------------------------------------------
    def _source_payload(self, source_id: str, project_id: str) -> dict[str, Any]:
        """Read one fixed source through its fixed store loader."""
        descriptor = build_fixed_error_source_registry().get(source_id)
        if descriptor is None:
            raise ValidationError("Unknown BOBA error doctor review source.")
        loader = getattr(self.store, str(descriptor["loader"]), None)
        if loader is None:
            return {}
        try:
            return _as_mapping(loader(project_id))
        except (ValidationError, NotFoundError, OSError):
            return {}

    def _incident_rows(self, project_id: str) -> list[tuple[dict[str, Any], int]]:
        """Return (diagnostic case, creation index) in the owner's own order."""
        payload = self._source_payload("error_doctor", project_id)
        rows: list[tuple[dict[str, Any], int]] = []
        cases = payload.get("diagnostic_cases")
        if not isinstance(cases, list):
            return rows
        for index, entry in enumerate(cases[:MAX_LOADED_INCIDENTS]):
            if isinstance(entry, Mapping):
                rows.append((_as_mapping(entry), index))
        return rows

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

    def _analysis_cases_for(self, project_id: str, incident_id: str) -> list[dict[str, Any]]:
        return self._keyed_rows(
            "root_cause_analyzer", project_id, "analysis_cases", "source_diagnostic_case_id"
        ).get(incident_id, [])

    def _root_cause_candidates(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._keyed_rows(
            "root_cause_analyzer", project_id, "root_cause_candidates", "analysis_case_id"
        )

    def _repair_cases_for(
        self, project_id: str, analysis_case_ids: Sequence[str]
    ) -> list[dict[str, Any]]:
        grouped = self._keyed_rows(
            "repair_planner", project_id, "repair_cases", "source_analysis_case_id"
        )
        rows: list[dict[str, Any]] = []
        for analysis_case_id in analysis_case_ids:
            rows.extend(grouped.get(analysis_case_id, []))
        return rows

    def _repair_strategies(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._keyed_rows(
            "repair_planner", project_id, "repair_strategies", "repair_case_id"
        )

    def _recovery_cases_for(
        self, project_id: str, repair_case_ids: Sequence[str]
    ) -> list[dict[str, Any]]:
        grouped = self._keyed_rows(
            "tool_recovery", project_id, "recovery_cases", "source_repair_case_id"
        )
        rows: list[dict[str, Any]] = []
        for repair_case_id in repair_case_ids:
            rows.extend(grouped.get(repair_case_id, []))
        return rows

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
        self, project_id: str, repair_case_ids: Sequence[str]
    ) -> list[dict[str, Any]]:
        grouped = self._keyed_rows(
            "code_surgeon", project_id, "code_repair_cases", "source_repair_case_id"
        )
        rows: list[dict[str, Any]] = []
        for repair_case_id in repair_case_ids:
            rows.extend(grouped.get(repair_case_id, []))
        return rows

    def _observer_findings(self, project_id: str) -> dict[str, dict[str, Any]]:
        """Flatten Observer findings by finding_id across every observation list."""
        payload = self._source_payload("observer", project_id)
        found: dict[str, dict[str, Any]] = {}
        for key in (
            "artifact_observations",
            "module_health_observations",
            "workflow_observations",
            "dependency_observations",
            "validation_observations",
            "safety_observations",
        ):
            rows = payload.get(key)
            if not isinstance(rows, list):
                continue
            for observation in rows[:512]:
                if not isinstance(observation, Mapping):
                    continue
                findings = _as_mapping(observation).get("findings")
                if not isinstance(findings, list):
                    continue
                for finding in findings[:64]:
                    if not isinstance(finding, Mapping):
                        continue
                    mapped = _as_mapping(finding)
                    finding_id = _safe_text(mapped.get("finding_id"), 180)
                    if finding_id:
                        mapped["_observation_type"] = key
                        found[finding_id] = mapped
        return found

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
            for source_id in build_fixed_error_source_registry()
        }
        return _digest(digests)

    def _incident_digest(self, project_id: str, incident_id: str) -> str:
        try:
            record = self._incident_record(project_id, incident_id)
        except ValidationError:
            return _digest({"incident_id": incident_id, "state": "unavailable"})
        analysis = self._analysis_cases_for(project_id, incident_id)
        analysis_ids = [_safe_text(item.get("analysis_case_id"), 180) for item in analysis]
        repairs = self._repair_cases_for(project_id, analysis_ids)
        repair_ids = [_safe_text(item.get("repair_case_id"), 180) for item in repairs]
        return _digest(
            {
                "incident": _safe_payload(record),
                "analysis": _safe_payload(analysis),
                "repairs": _safe_payload(repairs),
                "recovery": _safe_payload(
                    self._recovery_cases_for(project_id, repair_ids)
                ),
            }
        )

    def _incident_record(self, project_id: str, incident_id: str) -> dict[str, Any]:
        for record, _index in self._incident_rows(project_id):
            if _safe_text(record.get("diagnostic_case_id"), 180) == incident_id:
                return record
        raise ValidationError("BOBA incident record is unavailable.")

    def _safety_record_digest(self, project_id: str) -> str:
        return _digest(_safe_payload(self._source_payload("safety_gate", project_id)))

    def _final_decision_record_digest(self, project_id: str) -> str:
        return _digest(_safe_payload(self._source_payload("final_decision_bus", project_id)))

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def build_error_doctor_review_registry(self, project_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        sources = build_fixed_error_source_registry()
        sections = build_fixed_error_section_registry()
        actions = build_fixed_error_doctor_action_registry()
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
        snapshot_id = _stable_id("error_doctor_registry", "v1", _digest(payload))
        stored = self.store.load_boba_error_doctor_review_registry(project_id, snapshot_id)
        registry = (
            BobaErrorDoctorRegistrySnapshotV1.model_validate(stored)
            if isinstance(stored, Mapping)
            else BobaErrorDoctorRegistrySnapshotV1(
                registry_snapshot_id=snapshot_id,
                incident_source_ids=[
                    key for key, row in sources.items() if row["source_class"] == "incident"
                ],
                diagnosis_source_ids=[
                    key for key, row in sources.items() if row["source_class"] == "diagnosis"
                ],
                repair_source_ids=[
                    key for key, row in sources.items() if row["source_class"] == "repair"
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
                    "Error Doctor Panel V1 exposes no execution, repair, recovery, "
                    "checkpoint or workflow action.",
                    "Incident identity is the Error Doctor diagnostic_case_id.",
                ],
            )
        )
        if not isinstance(stored, Mapping):
            self.store.save_boba_error_doctor_review_registry(
                project_id, snapshot_id, registry.model_dump(mode="json")
            )
        return {
            "registry_snapshot": registry.model_dump(mode="json"),
            "sources": source_rows,
            "sections": list(sections.values()),
            "actions": action_rows,
            "priority_tiers": [
                {"priority": priority, "reason": reason}
                for priority, reason in INCIDENT_QUEUE_PRIORITY_TIERS
            ],
            "source_severity_order": list(_SEVERITY_ORDER),
            "supported_incident_schema_id": SUPPORTED_INCIDENT_SCHEMA_ID,
        }

    def inspect_error_doctor_review_registry(self, project_id: str) -> dict[str, Any]:
        return self.build_error_doctor_review_registry(project_id)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_error_doctor_review_session(
        self,
        project_id: str,
        *,
        reviewer_context_id: str,
        selected_incident_id: str | None = None,
        expires_in_seconds: int = 3_600,
    ) -> BobaErrorDoctorReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(reviewer_context_id, "reviewer context id")
        if _SENSITIVE_KEY.search(reviewer_context_id):
            raise ValidationError("Reviewer context cannot contain credentials.")
        if selected_incident_id is not None:
            _safe_id(selected_incident_id, "incident id")
        session_id = f"error_doctor_review_session_{uuid4().hex}"
        now = datetime.now(UTC)
        session = BobaErrorDoctorReviewSessionV1(
            error_doctor_review_session_id=session_id,
            project_id=project_id,
            reviewer_context_id=reviewer_context_id,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(
                now + timedelta(seconds=max(60, min(expires_in_seconds, 28_800)))
            ).isoformat(),
            selected_incident_id=selected_incident_id,
            session_digest=_digest(
                {
                    "session_id": session_id,
                    "project_id": project_id,
                    "reviewer_context_id": reviewer_context_id,
                    "selected_incident_id": selected_incident_id,
                }
            ),
            limitations=[
                "Review sessions hold only UI state.",
                "local_annotations are review-session metadata and are never part "
                "of the canonical incident, diagnosis or repair record.",
            ],
        )
        self.store.save_boba_error_doctor_review_session(
            project_id, session_id, session.model_dump(mode="json")
        )
        return session

    def get_error_doctor_review_session(
        self, project_id: str, session_id: str
    ) -> BobaErrorDoctorReviewSessionV1:
        _safe_id(project_id, "project id")
        _safe_id(session_id, "error doctor review session id")
        raw = self.store.load_boba_error_doctor_review_session(project_id, session_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA error doctor review session is unavailable.")
        session = BobaErrorDoctorReviewSessionV1.model_validate(raw)
        if session.project_id != project_id:
            raise ValidationError(
                "Error doctor review session belongs to another project."
            )
        expires_at = _parse_time(session.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            raise ValidationError("BOBA error doctor review session has expired.")
        return session

    def update_error_doctor_review_session(
        self, project_id: str, session_id: str, updates: Mapping[str, Any]
    ) -> BobaErrorDoctorReviewSessionV1:
        session = self.get_error_doctor_review_session(project_id, session_id)
        allowed = {
            "selected_incident_id",
            "comparison_incident_ids",
            "active_filter",
            "active_sort",
            "active_section_id",
            "show_recovered",
            "show_resolved",
            "show_historical",
            "show_technical_details",
            "show_bounded_logs",
            "show_repair_history",
            "evidence_drawer_open",
            "timeline_drawer_open",
            "local_annotations",
            "read_incident_ids",
        }
        unsafe = set(updates) - allowed
        if unsafe:
            raise ValidationError(
                "Error doctor review session update contains unsupported fields."
            )
        comparison = updates.get("comparison_incident_ids")
        if isinstance(comparison, list) and len(comparison) > MAX_COMPARISON_INCIDENTS:
            raise ValidationError(
                f"At most {MAX_COMPARISON_INCIDENTS} incidents may be compared."
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
        updated = BobaErrorDoctorReviewSessionV1.model_validate(payload)
        self.store.save_boba_error_doctor_review_session(
            project_id, session_id, updated.model_dump(mode="json")
        )
        return updated

    @staticmethod
    def _bounded_annotations(value: object) -> list[dict[str, str]]:
        """Bound and sanitise reviewer annotations. Never canonical incident text."""
        if not isinstance(value, list):
            return []
        rows: list[dict[str, str]] = []
        for entry in value[:MAX_ANNOTATIONS]:
            if not isinstance(entry, Mapping):
                continue
            text = _safe_text(entry.get("text"), MAX_ANNOTATION_LENGTH)
            if not text:
                continue
            if _SENSITIVE_KEY.search(text):
                raise ValidationError("Review annotations cannot contain credentials.")
            for pattern in _SECRET_VALUE_PATTERNS:
                if pattern.search(text):
                    raise ValidationError(
                        "Review annotations cannot contain credentials."
                    )
            rows.append(
                {
                    "annotation_id": _safe_text(entry.get("annotation_id"), 120)
                    or _stable_id("error_doctor_annotation", text),
                    "incident_id": _safe_text(entry.get("incident_id"), 180),
                    "section_id": _safe_text(entry.get("section_id"), 120),
                    "text": text,
                    "notice": (
                        "Review-session annotation — not part of the canonical "
                        "incident, diagnosis or repair record."
                    ),
                }
            )
        return rows

    # ------------------------------------------------------------------
    # Incident references
    # ------------------------------------------------------------------
    def build_incident_references(self, project_id: str) -> list[BobaIncidentReferenceV1]:
        """Project every persisted Error Doctor diagnostic case as an incident."""
        _safe_id(project_id, "project id")
        payload = self._source_payload("error_doctor", project_id)
        if not payload:
            return []
        schema_id = _safe_text(payload.get("schema_version") or "unknown", 180)
        supported = schema_id == SUPPORTED_INCIDENT_SCHEMA_ID
        source_id = _safe_text(payload.get("source_id"), 512)
        record_digest = _digest(_safe_payload(payload))
        project_digest = self._project_snapshot_digest(project_id)
        run = self._workflow_run(project_id)
        run_id = _safe_text(run.get("workflow_run_id"), 180) or None
        stage_instance_id = _safe_text(run.get("current_stage_instance_id"), 180) or None
        revision = self._workflow_revision(project_id)
        recovery_attempts = self._recovery_attempts(project_id)

        references: list[BobaIncidentReferenceV1] = []
        for record, _index in self._incident_rows(project_id):
            incident_id = _safe_text(record.get("diagnostic_case_id"), 180)
            if not incident_id or not _SAFE_RECORD_ID.fullmatch(incident_id):
                continue
            warnings: list[str] = []
            if not supported:
                warnings.append(
                    f"Incident schema '{schema_id}' is not supported by this panel."
                )
            analysis = self._analysis_cases_for(project_id, incident_id)
            analysis_ids = [
                _safe_text(item.get("analysis_case_id"), 180) for item in analysis
            ]
            repairs = self._repair_cases_for(project_id, analysis_ids)
            repair_ids = [_safe_text(item.get("repair_case_id"), 180) for item in repairs]
            recovery_cases = self._recovery_cases_for(project_id, repair_ids)
            attempts = [
                attempt
                for case in recovery_cases
                for attempt in recovery_attempts.get(
                    _safe_text(case.get("recovery_case_id"), 180), []
                )
            ]
            # ``recovered`` means an owner reported a completed recovery attempt.
            # It never means resolved.
            recovered = any(
                _safe_text(item.get("status"), 120)
                in {"completed", "succeeded_pending_validation"}
                for item in attempts
            )
            # No owner records an incident resolution flag, so it stays False.
            resolved = False
            # Owner evidence timestamps are the only incident timing the owner
            # records; there is no first_seen_at or last_seen_at field.
            stamps = sorted(
                stamp
                for stamp in (
                    _seconds_text(item.get("timestamp"))
                    for item in record.get("evidence", [])
                    if isinstance(item, Mapping)
                )
                if stamp
            )
            references.append(
                BobaIncidentReferenceV1(
                    incident_reference_id=_stable_id(
                        "incident_reference", project_id, incident_id
                    ),
                    project_id=project_id,
                    source_id=source_id,
                    workflow_run_id=run_id,
                    stage_instance_id=stage_instance_id,
                    incident_id=incident_id,
                    # Error Doctor defines no incident revision identity, so it
                    # stays absent and is never inferred.
                    incident_revision_id=None,
                    source_record_id=schema_id,
                    source_record_digest=record_digest,
                    source_schema_id=schema_id,
                    source_schema_version=schema_id,
                    schema_supported=supported,
                    affected_module_id=_safe_text(record.get("primary_module"), 180),
                    affected_operation_id="",
                    affected_stage_id=_safe_text(record.get("workflow_stage"), 180),
                    error_class=_safe_text(record.get("error_category") or "unknown", 120),
                    # Error Doctor records no error code.
                    error_code=None,
                    original_severity=_safe_text(
                        record.get("severity") or "unknown", 80
                    ),
                    original_status=_safe_text(
                        record.get("diagnosis_status") or "unknown", 120
                    ),
                    first_seen_at=stamps[0] if stamps else None,
                    last_seen_at=stamps[-1] if stamps else None,
                    project_snapshot_digest=project_digest,
                    workflow_revision=revision,
                    current=True,
                    # The owner keeps no historical incident archive and records no
                    # supersession marker, so these stay explicitly false.
                    stale=False,
                    historical=False,
                    superseded=False,
                    superseding_incident_id=None,
                    recovered=recovered,
                    resolved=resolved,
                    source_event_ids=[
                        _safe_text(item, 180)
                        for item in record.get("related_finding_ids", [])
                        if isinstance(item, str)
                    ][:128],
                    warnings=warnings[:24],
                    limitations=[
                        "Error Doctor records no incident revision identity and no "
                        "supersession field, so both remain absent.",
                        "The owner stores one current diagnostic set; there is no "
                        "historical incident archive.",
                        "Error Doctor records no error code, so none is shown.",
                        "recovered means an owner reported a completed recovery "
                        "attempt. It does not mean the incident is resolved.",
                    ],
                )
            )
        return references[:MAX_LOADED_INCIDENTS]

    def _reference_for(self, project_id: str, incident_id: str) -> BobaIncidentReferenceV1:
        _safe_id(incident_id, "incident id")
        for reference in self.build_incident_references(project_id):
            if reference.incident_id == incident_id:
                return reference
        raise ValidationError(
            "BOBA incident is unknown, unavailable, or belongs to another project."
        )

    # ------------------------------------------------------------------
    # Diagnosis
    # ------------------------------------------------------------------
    def build_diagnosis_projections(
        self, project_id: str, incident_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaDiagnosisProjectionV1]:
        """Project the Error Doctor diagnosis without rewriting it."""
        reference = self._reference_for(project_id, incident_id)
        record = self._incident_record(project_id, incident_id)
        payload = self._source_payload("error_doctor", project_id)
        technical = bounded_technical_message(record.get("probable_cause_summary"))
        symptom = bounded_technical_message(record.get("symptom_summary"))
        hypotheses = [
            _safe_text(item.get("hypothesis_id"), 180)
            for item in record.get("hypotheses", [])
            if isinstance(item, Mapping)
        ]
        confirmed = [
            _stable_id("confirmed_fact", incident_id, str(index))
            for index, item in enumerate(record.get("confirmed_facts", []))
            if isinstance(item, str) and item.strip()
        ]
        assessments = [
            _stable_id("assessment", incident_id, str(index))
            for index, item in enumerate(record.get("recommended_investigation", []))
            if isinstance(item, str) and item.strip()
        ]
        confidence = record.get("confidence")
        return [
            BobaDiagnosisProjectionV1(
                diagnosis_projection_id=_stable_id(
                    "diagnosis_projection", project_id, incident_id
                ),
                incident_snapshot_id=snapshot_id,
                source_module_id="error_doctor",
                source_record_id=reference.source_record_id,
                source_record_digest=reference.source_record_digest,
                diagnosis_id=incident_id,
                # Error Doctor defines no diagnosis revision identity.
                diagnosis_revision_id=None,
                original_status=_safe_text(record.get("diagnosis_status"), 120)
                or "unknown",
                original_category=_safe_text(record.get("error_category"), 120)
                or "unknown",
                original_error_class=reference.error_class,
                original_error_code=None,
                original_summary=_safe_text(record.get("symptom_summary"), 900),
                bounded_technical_explanation=(
                    f"{symptom['text']}\n{technical['text']}".strip()
                )[:MAX_TECHNICAL_MESSAGE_CHARS],
                bounded_easy_explanation=bounded_easy_explanation(
                    record.get("probable_cause_summary")
                ),
                confirmed_fact_ids=confirmed[:32],
                assessment_ids=assessments[:32],
                hypothesis_ids=[item for item in hypotheses if item][:32],
                confidence_value=(
                    float(confidence) if isinstance(confidence, int | float) else None
                ),
                confidence_name="error_doctor_case_confidence",
                confidence_definition=(
                    "Error Doctor's own 0.0-1.0 confidence for this diagnostic case. "
                    "The owner does not define it as a probability, and it is not "
                    "comparable with any other module's confidence."
                ),
                confidence_scale_min=0.0,
                confidence_scale_max=1.0,
                confidence_comparable_across_sources=False,
                current=reference.current,
                stale=reference.stale,
                historical=reference.historical,
                superseded=reference.superseded,
                authoritative=True,
                advisory=False,
                sensitive_values_redacted=technical["sensitive_values_redacted"]
                or symptom["sensitive_values_redacted"],
                private_paths_redacted=technical["private_paths_redacted"]
                or symptom["private_paths_redacted"],
                warnings=[
                    _safe_text(item, 300)
                    for item in record.get("warnings", [])
                    if isinstance(item, str)
                ][:16],
                limitations=[
                    *[
                        _safe_text(item, 300)
                        for item in record.get("limitations", [])
                        if isinstance(item, str)
                    ][:12],
                    "Confidence is the owner's own value on its own scale. It is "
                    "not a probability and is never averaged or compared.",
                    *(
                        []
                        if payload
                        else ["No Error Doctor record is available for this project."]
                    ),
                ][:16],
            )
        ][:_MAX_DIAGNOSIS_PROJECTIONS]

    def inspect_diagnosis(self, project_id: str, incident_id: str) -> dict[str, Any]:
        record = self._incident_record(project_id, incident_id)
        projections = self.build_diagnosis_projections(project_id, incident_id)
        return {
            "schema_version": "boba_error_doctor_review_diagnosis_v1",
            "project_id": project_id,
            "incident_id": incident_id,
            "diagnosis_projections": [item.model_dump(mode="json") for item in projections],
            "confirmed_facts": [
                _safe_text(item, 700)
                for item in record.get("confirmed_facts", [])
                if isinstance(item, str)
            ][:32],
            "hypotheses": [
                {
                    "hypothesis_id": _safe_text(item.get("hypothesis_id"), 180),
                    "hypothesis": _safe_text(item.get("hypothesis"), 700),
                    "category": _safe_text(item.get("category"), 120),
                    "supporting_evidence_ids": [
                        _safe_text(row, 180)
                        for row in item.get("supporting_evidence_ids", [])
                        if isinstance(row, str)
                    ][:32],
                    "conflicting_evidence_ids": [
                        _safe_text(row, 180)
                        for row in item.get("conflicting_evidence_ids", [])
                        if isinstance(row, str)
                    ][:32],
                    "confidence": item.get("confidence"),
                    "verification_needed": bool(item.get("verification_needed", True)),
                    "suggested_check": _safe_text(item.get("suggested_check"), 700),
                    "classification": "source_owned_hypothesis",
                }
                for item in record.get("hypotheses", [])
                if isinstance(item, Mapping)
            ][:16],
            "missing_information": [
                _safe_text(item, 500)
                for item in record.get("missing_information", [])
                if isinstance(item, str)
            ][:32],
            "escalation_target": _safe_text(record.get("escalation_target"), 160),
            "processing_impact": _safe_text(record.get("processing_impact"), 120),
            "safety_impact": _safe_text(record.get("safety_impact"), 120),
            "limitations": [
                "A hypothesis is never presented as a confirmed fact.",
                "Confidence is the owner's own value and is not a probability "
                "unless the owner defines it as one.",
                "The panel does not diagnose; it projects Error Doctor's record.",
            ],
        }

    # ------------------------------------------------------------------
    # Root cause
    # ------------------------------------------------------------------
    def build_root_cause_projections(
        self, project_id: str, incident_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRootCauseProjectionV1]:
        """Project every Root Cause Analyzer candidate separately."""
        reference = self._reference_for(project_id, incident_id)
        payload = self._source_payload("root_cause_analyzer", project_id)
        record_digest = (
            _digest(_safe_payload(payload)) if payload else reference.source_record_digest
        )
        schema_id = _safe_text(payload.get("schema_version") or "unknown", 180)
        candidates_by_case = self._root_cause_candidates(project_id)
        projections: list[BobaRootCauseProjectionV1] = []
        for analysis in self._analysis_cases_for(project_id, incident_id):
            analysis_case_id = _safe_text(analysis.get("analysis_case_id"), 180)
            analysis_status = _safe_text(analysis.get("analysis_status"), 120) or "unknown"
            # Root Cause Analyzer pins human_review_required=True on every analysis
            # case and verification_required on every candidate, so the owner never
            # declares a root cause confirmed. The panel never promotes one.
            case_requires_review = bool(analysis.get("human_review_required", True))
            for candidate in candidates_by_case.get(analysis_case_id, []):
                candidate_id = _safe_text(candidate.get("root_cause_candidate_id"), 180)
                if not candidate_id:
                    continue
                verification_required = bool(candidate.get("verification_required", True))
                confirmed = (
                    analysis_status == "root_cause_supported"
                    and not verification_required
                    and not case_requires_review
                )
                likelihood = candidate.get("likelihood_score")
                confidence = candidate.get("confidence")
                explanation = bounded_excerpt(
                    candidate.get("candidate_summary"),
                    maximum=MAX_EASY_EXPLANATION_CHARS,
                )
                projections.append(
                    BobaRootCauseProjectionV1(
                        root_cause_projection_id=_stable_id(
                            "root_cause_projection", project_id, incident_id, candidate_id
                        ),
                        incident_snapshot_id=snapshot_id,
                        source_module_id="root_cause_analyzer",
                        source_record_id=schema_id,
                        source_record_digest=record_digest,
                        root_cause_id=candidate_id,
                        root_cause_revision_id=None,
                        original_status=analysis_status,
                        original_classification=_safe_text(candidate.get("category"), 120)
                        or "unknown",
                        original_summary=_safe_text(
                            candidate.get("candidate_summary"), 900
                        ),
                        confirmed=confirmed,
                        hypothesis=not confirmed,
                        evidence_record_ids=[
                            _safe_text(item, 180)
                            for item in candidate.get("supporting_evidence_ids", [])
                            if isinstance(item, str)
                        ][:64],
                        contradictory_evidence_record_ids=[
                            _safe_text(item, 180)
                            for item in candidate.get("conflicting_evidence_ids", [])
                            if isinstance(item, str)
                        ][:64],
                        confidence_value=(
                            float(confidence)
                            if isinstance(confidence, int | float)
                            else None
                        ),
                        confidence_name="root_cause_candidate_confidence",
                        confidence_definition=(
                            "Root Cause Analyzer's own 0.0-1.0 confidence for this "
                            "candidate. The owner does not define it as a "
                            "probability and it is not comparable with confidence "
                            "from any other module."
                        ),
                        likelihood_value=(
                            float(likelihood)
                            if isinstance(likelihood, int | float)
                            else None
                        ),
                        likelihood_name="root_cause_candidate_likelihood_score",
                        evidence_quality=_safe_text(candidate.get("evidence_quality"), 120)
                        or "unknown",
                        repairability=_safe_text(candidate.get("repairability"), 120)
                        or "unknown",
                        recommended_owner_module_id=_safe_text(
                            candidate.get("recommended_owner_module"), 180
                        ),
                        current=reference.current,
                        stale=reference.stale,
                        historical=reference.historical,
                        superseded=False,
                        human_confirmation_required=case_requires_review
                        or verification_required,
                        bounded_explanation=explanation["text"],
                        warnings=[
                            _safe_text(item, 300)
                            for item in candidate.get("warnings", [])
                            if isinstance(item, str)
                        ][:16],
                        limitations=[
                            *[
                                _safe_text(item, 300)
                                for item in candidate.get("limitations", [])
                                if isinstance(item, str)
                            ][:10],
                            "Root Cause Analyzer marks every analysis case as "
                            "requiring human review, so this panel never shows a "
                            "confirmed root cause.",
                            "likelihood_score and confidence are separate "
                            "owner-defined values and are never averaged.",
                        ][:16],
                    )
                )
        return projections[:_MAX_ROOT_CAUSE_PROJECTIONS]

    def inspect_root_cause(self, project_id: str, incident_id: str) -> dict[str, Any]:
        projections = self.build_root_cause_projections(project_id, incident_id)
        analysis_cases = self._analysis_cases_for(project_id, incident_id)
        return {
            "schema_version": "boba_error_doctor_review_root_cause_v1",
            "project_id": project_id,
            "incident_id": incident_id,
            "root_cause_projections": [
                item.model_dump(mode="json") for item in projections
            ],
            "analysis_cases": [
                {
                    "analysis_case_id": _safe_text(item.get("analysis_case_id"), 180),
                    "analysis_status": _safe_text(item.get("analysis_status"), 120),
                    "earliest_known_failure": _safe_text(
                        item.get("earliest_known_failure"), 700
                    ),
                    "most_likely_root_cause": _safe_text(
                        item.get("most_likely_root_cause"), 700
                    ),
                    "root_cause_confidence": item.get("root_cause_confidence"),
                    "confirmed_facts": [
                        _safe_text(row, 500)
                        for row in item.get("confirmed_facts", [])
                        if isinstance(row, str)
                    ][:32],
                    "probable_inferences": [
                        _safe_text(row, 500)
                        for row in item.get("probable_inferences", [])
                        if isinstance(row, str)
                    ][:32],
                    "unresolved_hypotheses": [
                        _safe_text(row, 500)
                        for row in item.get("unresolved_hypotheses", [])
                        if isinstance(row, str)
                    ][:32],
                    "human_review_required": bool(item.get("human_review_required", True)),
                }
                for item in analysis_cases
            ][:16],
            "confirmed_root_cause_count": sum(
                1 for item in projections if item.confirmed
            ),
            "hypothesis_count": sum(1 for item in projections if item.hypothesis),
            "limitations": [
                "Every candidate is shown separately with its own owner and "
                "evidence. No candidate is selected, ranked or averaged here.",
                "Root Cause Analyzer requires human review on every analysis case.",
            ],
        }

    # ------------------------------------------------------------------
    # Repair plans
    # ------------------------------------------------------------------
    def build_repair_plan_projections(
        self, project_id: str, incident_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRepairPlanProjectionV1]:
        """Project Repair Planner strategies without exposing anything executable."""
        reference = self._reference_for(project_id, incident_id)
        payload = self._source_payload("repair_planner", project_id)
        record_digest = (
            _digest(_safe_payload(payload)) if payload else reference.source_record_digest
        )
        schema_id = _safe_text(payload.get("schema_version") or "unknown", 180)
        analysis_ids = [
            _safe_text(item.get("analysis_case_id"), 180)
            for item in self._analysis_cases_for(project_id, incident_id)
        ]
        strategies_by_case = self._repair_strategies(project_id)
        rollback_plans = {
            _safe_text(item.get("rollback_plan_id"), 180): item
            for item in payload.get("rollback_plans", [])
            if isinstance(item, Mapping)
        }
        projections: list[BobaRepairPlanProjectionV1] = []
        for repair_case in self._repair_cases_for(project_id, analysis_ids):
            repair_case_id = _safe_text(repair_case.get("repair_case_id"), 180)
            planning_status = (
                _safe_text(repair_case.get("planning_status"), 120) or "unknown"
            )
            rollback_available = bool(
                rollback_plans.get(_safe_text(repair_case.get("rollback_plan_id"), 180))
            )
            for strategy in strategies_by_case.get(repair_case_id, []):
                strategy_id = _safe_text(strategy.get("repair_strategy_id"), 180)
                if not strategy_id:
                    continue
                steps = [
                    item
                    for item in strategy.get("proposed_steps", [])
                    if isinstance(item, Mapping)
                ]
                # Step summaries are descriptions only. Command text, targets and
                # any executable control are deliberately never projected.
                step_summaries = [
                    _safe_text(
                        f"{_safe_text(item.get('step_type'), 60)}: "
                        f"{_safe_text(item.get('description'), 400)}",
                        400,
                    )
                    for item in steps
                ][:32]
                destructiveness = _safe_text(strategy.get("destructiveness"), 120)
                reversibility = _safe_text(strategy.get("reversibility"), 120)
                rank = strategy.get("rank")
                score = strategy.get("strategy_score")
                explanation = bounded_excerpt(
                    strategy.get("easy_explanation"), maximum=MAX_EASY_EXPLANATION_CHARS
                )
                projections.append(
                    BobaRepairPlanProjectionV1(
                        repair_plan_projection_id=_stable_id(
                            "repair_plan_projection", project_id, incident_id, strategy_id
                        ),
                        incident_snapshot_id=snapshot_id,
                        source_module_id="repair_planner",
                        source_record_id=schema_id,
                        source_record_digest=record_digest,
                        repair_plan_id=strategy_id,
                        repair_plan_revision_id=None,
                        original_status=planning_status,
                        original_strategy=_safe_text(strategy.get("strategy_type"), 120)
                        or "unknown",
                        original_summary=_safe_text(strategy.get("description"), 900),
                        affected_module_ids=[
                            item
                            for item in [_safe_text(strategy.get("target_module"), 180)]
                            if item
                        ],
                        affected_operation_ids=[],
                        proposed_step_count=len(steps),
                        proposed_step_summaries=step_summaries,
                        requires_code_change=bool(strategy.get("requires_code_change")),
                        requires_artifact_change=_safe_text(
                            strategy.get("strategy_type"), 120
                        )
                        in {"regenerate_artifact", "repair_generated_state"},
                        requires_tool_execution=bool(
                            strategy.get("requires_command_execution")
                        )
                        or bool(strategy.get("requires_validator_execution"))
                        or bool(strategy.get("requires_tool_fallback")),
                        requires_process_restart=bool(
                            strategy.get("requires_service_restart")
                        ),
                        requires_checkpoint_restore=_safe_text(
                            strategy.get("strategy_type"), 120
                        )
                        in {"restore_checkpoint", "resume_from_checkpoint"},
                        requires_workflow_transition=_safe_text(
                            strategy.get("strategy_type"), 120
                        )
                        == "switch_safe_workflow_path",
                        requires_human_approval=bool(
                            strategy.get("human_approval_required", True)
                        ),
                        destructive=destructiveness
                        not in {"non_destructive", "", "unknown"},
                        reversible=reversibility
                        in {"fully_reversible", "reversible", "mostly_reversible"},
                        rollback_available=rollback_available,
                        verification_required=True,
                        source_owned_rank=(
                            int(rank) if isinstance(rank, int) and rank > 0 else None
                        ),
                        source_owned_score=(
                            float(score) if isinstance(score, int | float) else None
                        ),
                        source_owned_score_name=(
                            "repair_planner_strategy_score" if score is not None else ""
                        ),
                        source_marked_recommended=bool(strategy.get("recommended")),
                        current=reference.current,
                        stale=reference.stale,
                        historical=reference.historical,
                        superseded=False,
                        bounded_explanation=explanation["text"],
                        warnings=[
                            _safe_text(item, 300)
                            for item in strategy.get("warnings", [])
                            if isinstance(item, str)
                        ][:16],
                        limitations=[
                            *[
                                _safe_text(item, 300)
                                for item in strategy.get("limitations", [])
                                if isinstance(item, str)
                            ][:10],
                            "Repair execution is unavailable in Error Doctor Panel V1.",
                            "Step summaries are descriptions only; no command text "
                            "and no executable control is exposed.",
                            "rank, strategy_score and recommended belong to Repair "
                            "Planner. The panel adds no score of its own.",
                        ][:16],
                    )
                )
        return projections[:_MAX_REPAIR_PLAN_PROJECTIONS]

    def inspect_repair_plan(self, project_id: str, incident_id: str) -> dict[str, Any]:
        projections = self.build_repair_plan_projections(project_id, incident_id)
        analysis_ids = [
            _safe_text(item.get("analysis_case_id"), 180)
            for item in self._analysis_cases_for(project_id, incident_id)
        ]
        repair_cases = self._repair_cases_for(project_id, analysis_ids)
        repair_ids = [_safe_text(item.get("repair_case_id"), 180) for item in repair_cases]
        code_cases = self._code_repair_cases_for(project_id, repair_ids)
        return {
            "schema_version": "boba_error_doctor_review_repair_plan_v1",
            "project_id": project_id,
            "incident_id": incident_id,
            "repair_plan_projections": [
                item.model_dump(mode="json") for item in projections
            ],
            "repair_cases": [
                {
                    "repair_case_id": _safe_text(item.get("repair_case_id"), 180),
                    "planning_status": _safe_text(item.get("planning_status"), 120),
                    "repair_needed": bool(item.get("repair_needed")),
                    "repair_scope": _safe_text(item.get("repair_scope"), 120),
                    "blocked_reason": _safe_text(item.get("blocked_reason"), 700),
                    "recommended_strategy_id": _safe_text(
                        item.get("recommended_strategy_id"), 180
                    ),
                    "human_review_required": bool(item.get("human_review_required", True)),
                }
                for item in repair_cases
            ][:16],
            "code_repair_cases": [
                {
                    "code_repair_case_id": _safe_text(item.get("code_repair_case_id"), 180),
                    "code_change_justified": bool(item.get("code_change_justified")),
                    "evidence_strength": _safe_text(item.get("evidence_strength"), 120),
                    "execution_eligible": bool(item.get("execution_eligible")),
                    "approval_required": bool(item.get("approval_required", True)),
                    "affected_path_count": len(
                        [
                            row
                            for row in item.get("affected_paths", [])
                            if isinstance(row, str)
                        ]
                    ),
                    "blocked_reason": _safe_text(item.get("blocked_reason"), 700),
                }
                for item in code_cases
            ][:16],
            "repair_execution_available": False,
            "limitations": [
                "Repair execution is unavailable in Error Doctor Panel V1.",
                "Code Surgeon proposes patches; it never applies one from this panel.",
                "Affected code paths are counted, not listed, so private path "
                "material is never exposed.",
            ],
        }

    # ------------------------------------------------------------------
    # Recovery history
    # ------------------------------------------------------------------
    def build_recovery_attempt_projections(
        self, project_id: str, incident_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaRecoveryAttemptProjectionV1]:
        """Project every Tool Recovery attempt separately, including failures."""
        reference = self._reference_for(project_id, incident_id)
        payload = self._source_payload("tool_recovery", project_id)
        record_digest = (
            _digest(_safe_payload(payload)) if payload else reference.source_record_digest
        )
        schema_id = _safe_text(payload.get("schema_version") or "unknown", 180)
        analysis_ids = [
            _safe_text(item.get("analysis_case_id"), 180)
            for item in self._analysis_cases_for(project_id, incident_id)
        ]
        repair_ids = [
            _safe_text(item.get("repair_case_id"), 180)
            for item in self._repair_cases_for(project_id, analysis_ids)
        ]
        attempts_by_case = self._recovery_attempts(project_id)
        rollbacks = self._recovery_rollbacks(project_id)
        validations = self._recovery_validations(project_id)
        projections: list[BobaRecoveryAttemptProjectionV1] = []
        for case in self._recovery_cases_for(project_id, repair_ids):
            case_id = _safe_text(case.get("recovery_case_id"), 180)
            for attempt in attempts_by_case.get(case_id, []):
                attempt_id = _safe_text(attempt.get("recovery_attempt_id"), 180)
                if not attempt_id:
                    continue
                status = _safe_text(attempt.get("status"), 120) or "unknown"
                attempted = status != "not_started"
                completed = status in {"completed", "succeeded_pending_validation"}
                # ``succeeded_pending_validation`` is the owner saying the command
                # finished, not that the output is valid.
                succeeded_by_owner = status in {
                    "completed",
                    "succeeded_pending_validation",
                }
                attempt_validations = validations.get(attempt_id, [])
                verified = any(
                    bool(item.get("required_checks_passed"))
                    and bool(item.get("accepted_for_quality_review"))
                    for item in attempt_validations
                )
                attempt_rollbacks = rollbacks.get(attempt_id, [])
                exit_code = attempt.get("exit_code")
                summary = bounded_excerpt(
                    attempt.get("failure_summary") or attempt.get("stop_reason"),
                    maximum=900,
                )
                projections.append(
                    BobaRecoveryAttemptProjectionV1(
                        recovery_attempt_projection_id=_stable_id(
                            "recovery_attempt_projection",
                            project_id,
                            incident_id,
                            attempt_id,
                        ),
                        incident_snapshot_id=snapshot_id,
                        source_module_id="tool_recovery",
                        source_record_id=schema_id,
                        source_record_digest=record_digest,
                        recovery_attempt_id=attempt_id,
                        repair_plan_id=_safe_text(attempt.get("recovery_strategy_id"), 180),
                        attempt_number=(
                            int(attempt["attempt_number"])
                            if isinstance(attempt.get("attempt_number"), int)
                            else None
                        ),
                        original_status=status,
                        started_at=_seconds_text(attempt.get("execution_started_at")),
                        completed_at=_seconds_text(attempt.get("execution_completed_at")),
                        attempted=attempted,
                        completed=completed,
                        succeeded_by_owner=succeeded_by_owner,
                        verified=verified,
                        verification_source_ids=[
                            _safe_text(item.get("output_validation_id"), 180)
                            for item in attempt_validations
                        ][:16],
                        # Tool Recovery records what it did not touch. Code change
                        # is never inferred; only an explicit owner disclosure counts.
                        changed_code=False,
                        changed_artifacts=bool(attempt.get("output_artifact_refs"))
                        and not bool(attempt.get("completed_outputs_untouched", True)),
                        changed_workflow=False,
                        invoked_tool=_safe_text(attempt.get("tool_id"), 180),
                        invoked_operation_id=_safe_text(attempt.get("capability_id"), 240),
                        rollback_attempted=bool(attempt_rollbacks),
                        rollback_status=(
                            _safe_text(attempt_rollbacks[0].get("status"), 120)
                            if attempt_rollbacks
                            else "unavailable"
                        ),
                        original_error_code=None,
                        resulting_error_code=_safe_text(attempt.get("failure_class"), 120)
                        or None,
                        exit_code=(
                            int(exit_code) if isinstance(exit_code, int) else None
                        ),
                        timed_out=bool(attempt.get("timeout_occurred")),
                        current=reference.current,
                        stale=False,
                        historical=False,
                        bounded_summary=summary["text"],
                        warnings=[
                            _safe_text(item, 300)
                            for item in attempt.get("warnings", [])
                            if isinstance(item, str)
                        ][:16],
                        limitations=[
                            "Owner-reported success is not independent verification.",
                            "A recovered attempt does not mean the incident is "
                            "resolved.",
                            *(
                                []
                                if verified
                                else [
                                    "No Validator Runner or output validation record "
                                    "confirms this attempt."
                                ]
                            ),
                        ][:16],
                    )
                )
        return projections[:_MAX_RECOVERY_PROJECTIONS]

    def inspect_recovery_history(self, project_id: str, incident_id: str) -> dict[str, Any]:
        projections = self.build_recovery_attempt_projections(project_id, incident_id)
        failed = [
            item
            for item in projections
            if item.original_status in {"failed", "timed_out", "rejected", "blocked"}
        ]
        return {
            "schema_version": "boba_error_doctor_review_recovery_history_v1",
            "project_id": project_id,
            "incident_id": incident_id,
            "recovery_attempt_projections": [
                item.model_dump(mode="json") for item in projections
            ],
            "attempt_count": len(projections),
            "failed_attempt_count": len(failed),
            "owner_reported_success_count": sum(
                1 for item in projections if item.succeeded_by_owner
            ),
            "independently_verified_count": sum(1 for item in projections if item.verified),
            "rolled_back_count": sum(1 for item in projections if item.rollback_attempted),
            "limitations": [
                "Every attempt is listed separately. Failed attempts are never "
                "hidden or collapsed into a successful-looking record.",
                "Owner-reported success and independent verification are counted "
                "separately and are never merged.",
                "Recovered is never reported as resolved.",
            ],
        }

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------
    def _source_status(self, source_id: str, payload: Mapping[str, Any]) -> str:
        """Extract a module's own verbatim status word, never a panel judgement."""
        if not payload:
            return "unavailable"
        if source_id == "workflow_controller":
            run = _active_workflow_run(payload)
            return _safe_text(run.get("status") or "unknown", 160) or "unknown"
        for key in (
            "status",
            "decision",
            "overall_status",
            "health_status",
            "analysis_status",
            "planning_status",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _safe_text(value, 160)
        for summary_key in (
            "doctor_summary",
            "observer_summary",
            "runner_summary",
            "inspector_summary",
            "summary",
        ):
            summary = payload.get(summary_key)
            if isinstance(summary, Mapping):
                for key in ("status", "overall_status", "decision"):
                    value = summary.get(key)
                    if isinstance(value, str) and value.strip():
                        return _safe_text(value, 160)
        return "available"

    def build_evidence_cards(
        self, project_id: str, incident_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaErrorEvidenceCardV1]:
        """Build one bounded, redacted evidence card per canonical source."""
        reference = self._reference_for(project_id, incident_id)
        record = self._incident_record(project_id, incident_id)
        registry = build_fixed_error_source_registry()
        findings = self._observer_findings(project_id)
        diagnosis_ids = [incident_id]
        root_cause_ids = [
            item.root_cause_id
            for item in self.build_root_cause_projections(project_id, incident_id)
        ]
        repair_plan_ids = [
            item.repair_plan_id
            for item in self.build_repair_plan_projections(project_id, incident_id)
        ]
        attempt_ids = [
            item.recovery_attempt_id
            for item in self.build_recovery_attempt_projections(project_id, incident_id)
        ]
        cards: list[BobaErrorEvidenceCardV1] = []

        # Error Doctor's own evidence rows, classified exactly as the owner did.
        for item in record.get("evidence", [])[:64]:
            if not isinstance(item, Mapping):
                continue
            mapped = _as_mapping(item)
            evidence_id = _safe_text(mapped.get("evidence_id"), 180)
            if not evidence_id:
                continue
            excerpt = bounded_excerpt(mapped.get("evidence_summary"))
            cards.append(
                BobaErrorEvidenceCardV1(
                    evidence_card_id=_stable_id(
                        "error_evidence", project_id, incident_id, evidence_id
                    ),
                    incident_snapshot_id=snapshot_id,
                    evidence_type="error_doctor_evidence",
                    source_module_id="error_doctor",
                    authority_domain="diagnosis",
                    source_record_id=evidence_id,
                    source_record_digest=_digest(_safe_payload(mapped)),
                    source_schema_id=reference.source_schema_id,
                    source_schema_version=reference.source_schema_version,
                    title=_safe_text(mapped.get("source_type") or "evidence", 240)
                    or "evidence",
                    original_status=_safe_text(mapped.get("source_type"), 160)
                    or "unknown",
                    classification="confirmed_fact"
                    if _safe_text(mapped.get("observed_value"), 500)
                    else "source_owned_assessment",
                    confirmed_fact=_safe_text(mapped.get("observed_value"), 900),
                    assessment=_safe_text(mapped.get("evidence_summary"), 900),
                    bounded_summary=_safe_text(mapped.get("evidence_summary"), 900),
                    bounded_excerpt=excerpt["text"],
                    excerpt_truncated=excerpt["truncated"],
                    sensitive_values_redacted=excerpt["sensitive_values_redacted"],
                    private_paths_redacted=excerpt["private_paths_redacted"],
                    current=True,
                    authoritative=True,
                    supports_diagnosis_ids=diagnosis_ids,
                    warnings=[_safe_text(mapped.get("usage_warning"), 300)]
                    if mapped.get("usage_warning")
                    else [],
                    limitations=[
                        "Full records stay with the owning module; this is a "
                        "bounded excerpt.",
                    ],
                )
            )

        # Observer findings the diagnostic case explicitly references.
        for finding_id in reference.source_event_ids[:24]:
            finding = findings.get(finding_id)
            excerpt = bounded_excerpt(
                (finding or {}).get("message"), maximum=MAX_EXCERPT_CHARS
            )
            cards.append(
                BobaErrorEvidenceCardV1(
                    evidence_card_id=_stable_id(
                        "error_evidence", project_id, incident_id, "observer", finding_id
                    ),
                    incident_snapshot_id=snapshot_id,
                    evidence_type="observer_finding",
                    source_module_id="observer",
                    authority_domain="observation",
                    source_record_id=finding_id,
                    source_record_digest=_digest(_safe_payload(finding or {})),
                    title=f"Observer finding {finding_id}"[:240],
                    original_status=_safe_text((finding or {}).get("issue_level"), 160)
                    or "unavailable",
                    classification="confirmed_fact" if finding else "unavailable",
                    confirmed_fact=_safe_text((finding or {}).get("message"), 900),
                    bounded_summary=_safe_text((finding or {}).get("message"), 900)
                    or "No Observer finding with this identity is available.",
                    bounded_excerpt=excerpt["text"],
                    excerpt_truncated=excerpt["truncated"],
                    sensitive_values_redacted=excerpt["sensitive_values_redacted"],
                    private_paths_redacted=excerpt["private_paths_redacted"],
                    current=bool(finding),
                    missing=not finding,
                    authoritative=True,
                    supports_diagnosis_ids=diagnosis_ids,
                    limitations=[]
                    if finding
                    else ["Missing evidence is never treated as a pass."],
                )
            )

        # One card per fixed source module, present or explicitly missing.
        for source_id, descriptor in registry.items():
            if source_id in {"error_doctor", "observer"}:
                continue
            payload = self._source_payload(source_id, project_id)
            title = str(descriptor["title"])
            advisory = bool(descriptor["advisory_only"])
            status = self._source_status(source_id, payload)
            safe = _as_mapping(_safe_payload(payload))
            excerpt = bounded_excerpt(
                safe.get("summary") or safe.get("source_id") or "", maximum=2_048
            )
            cards.append(
                BobaErrorEvidenceCardV1(
                    evidence_card_id=_stable_id(
                        "error_evidence", project_id, incident_id, source_id
                    ),
                    incident_snapshot_id=snapshot_id,
                    evidence_type=f"{source_id}_record",
                    source_module_id=source_id,
                    authority_domain=str(descriptor["authority_domain"]),
                    source_record_id=_safe_text(
                        safe.get("schema_version") or source_id, 180
                    )
                    or source_id,
                    source_record_digest=_digest(safe) if payload else "",
                    source_schema_id=_safe_text(
                        safe.get("schema_version") or "unknown", 180
                    ),
                    source_schema_version=_safe_text(
                        safe.get("schema_version") or "unknown", 80
                    ),
                    title=title,
                    original_status=status,
                    classification="source_owned_assessment"
                    if payload
                    else "unavailable",
                    assessment=f"{title} reports {status.replace('_', ' ')}."
                    if payload
                    else "",
                    bounded_summary=(
                        f"{title} reports {status.replace('_', ' ')}."
                        if payload
                        else f"{title} has supplied no canonical record."
                    ),
                    bounded_excerpt=excerpt["text"],
                    excerpt_truncated=excerpt["truncated"],
                    sensitive_values_redacted=excerpt["sensitive_values_redacted"],
                    private_paths_redacted=excerpt["private_paths_redacted"],
                    current=bool(payload),
                    missing=not payload,
                    authoritative=not advisory,
                    advisory_only=advisory,
                    blocking=status in {"blocked", "failed", "denied", "rejected"},
                    supports_diagnosis_ids=diagnosis_ids
                    if source_id == "root_cause_analyzer"
                    else [],
                    supports_root_cause_ids=root_cause_ids
                    if source_id == "root_cause_analyzer"
                    else [],
                    supports_repair_plan_ids=repair_plan_ids
                    if source_id in {"repair_planner", "code_surgeon"}
                    else [],
                    supports_recovery_attempt_ids=attempt_ids
                    if source_id in {"tool_recovery", "validator_runner"}
                    else [],
                    limitations=(
                        ["This module's output is advisory, not a decision."]
                        if advisory
                        else []
                    )
                    + (
                        []
                        if payload
                        else ["An unavailable source record is never treated as a pass."]
                    ),
                )
            )
        return cards[:MAX_EVIDENCE_CARDS]

    def inspect_validation_evidence(self, project_id: str, incident_id: str) -> dict[str, Any]:
        """Project Validator Runner and Report Reader evidence by persisted identity."""
        self._reference_for(project_id, incident_id)
        validator = self._source_payload("validator_runner", project_id)
        reports = self._source_payload("report_reader", project_id)
        runs = [
            item
            for item in validator.get("validation_runs", [])
            if isinstance(item, Mapping)
        ]
        results = [
            item
            for item in validator.get("validation_results", [])
            if isinstance(item, Mapping)
        ]
        return {
            "schema_version": "boba_error_doctor_review_validation_v1",
            "project_id": project_id,
            "incident_id": incident_id,
            "validator_available": bool(validator),
            "report_reader_available": bool(reports),
            "validation_runs": [
                {
                    "validation_run_id": _safe_text(item.get("validation_run_id"), 180),
                    "original_status": _safe_text(item.get("status"), 160) or "unknown",
                    "checks_executed": item.get("executed_check_count"),
                    "passed": item.get("passed_check_count"),
                    "failed": item.get("failed_check_count"),
                    "skipped": item.get("skipped_check_count"),
                    "source_module_id": "validator_runner",
                }
                for item in runs
            ][:32],
            "validation_result_count": len(results),
            "missing_validation_evidence": not bool(runs),
            "limitations": [
                "Missing validation evidence stays missing. It never becomes a pass.",
                "A passing focused check is not full recovery and is not production "
                "readiness.",
                "Validator Runner owns every status shown here.",
            ],
        }

    def inspect_artifact_evidence(self, project_id: str, incident_id: str) -> dict[str, Any]:
        """Project Artifact Inspector evidence by persisted identity and digest."""
        record = self._incident_record(project_id, incident_id)
        payload = self._source_payload("artifact_inspector", project_id)
        references = {
            _safe_text(item.get("artifact_reference_id"), 180): _as_mapping(item)
            for item in payload.get("artifact_references", [])
            if isinstance(item, Mapping)
        }
        affected = [
            _safe_text(item, 180)
            for item in record.get("affected_artifacts", [])
            if isinstance(item, str)
        ][:64]
        rows: list[dict[str, Any]] = []
        for artifact_id in affected:
            reference = references.get(artifact_id, {})
            rows.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_reference_id": _safe_text(
                        reference.get("artifact_reference_id"), 180
                    ),
                    "artifact_digest": _safe_text(
                        reference.get("content_digest") or reference.get("digest"), 128
                    ),
                    "artifact_status": _safe_text(reference.get("status"), 160)
                    or "unavailable",
                    "present_in_inspector": bool(reference),
                    "missing": not bool(reference),
                    "source_module_id": "artifact_inspector",
                }
            )
        return {
            "schema_version": "boba_error_doctor_review_artifacts_v1",
            "project_id": project_id,
            "incident_id": incident_id,
            "artifact_inspector_available": bool(payload),
            "affected_artifacts": rows,
            "missing_artifact_evidence_count": sum(1 for item in rows if item["missing"]),
            "limitations": [
                "Artifact integrity is never inferred from the fact that a file "
                "exists; only Artifact Inspector's own assessment is shown.",
                "A missing inspector record stays missing and never becomes a pass.",
            ],
        }

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------
    def detect_incident_conflicts(
        self, project_id: str, incident_id: str, *, snapshot_id: str | None = None
    ) -> list[BobaErrorConflictV1]:
        """Report conflicts only between records naming the same exact identity."""
        reference = self._reference_for(project_id, incident_id)
        record = self._incident_record(project_id, incident_id)
        conflicts: list[BobaErrorConflictV1] = []

        def add(
            conflict_type: ErrorConflictType,
            severity: str,
            value_a: object,
            value_b: object,
            summary: str,
            *,
            blocks: bool = False,
            root_cause_ids: list[str] | None = None,
            repair_ids: list[str] | None = None,
            recovery_ids: list[str] | None = None,
        ) -> None:
            conflicts.append(
                BobaErrorConflictV1(
                    conflict_record_id=_stable_id(
                        "error_conflict", project_id, incident_id, conflict_type
                    ),
                    incident_snapshot_id=snapshot_id,
                    conflict_type=conflict_type,
                    severity=severity,
                    source_record_ids=[reference.source_record_id],
                    source_record_digests=[reference.source_record_digest],
                    diagnosis_projection_ids=[incident_id],
                    root_cause_projection_ids=root_cause_ids or [],
                    repair_plan_projection_ids=repair_ids or [],
                    recovery_attempt_projection_ids=recovery_ids or [],
                    value_a=_safe_text(value_a, 900),
                    value_b=_safe_text(value_b, 900),
                    same_incident=True,
                    same_workflow_run=reference.workflow_run_id is not None,
                    current_records=reference.current,
                    # No owner records a supersession marker for incidents.
                    explicit_supersession_found=False,
                    resolved=False,
                    blocks_action=blocks,
                    human_review_required=True,
                    bounded_summary=summary,
                )
            )

        analysis_cases = self._analysis_cases_for(project_id, incident_id)
        root_causes = self.build_root_cause_projections(project_id, incident_id)
        repairs = self.build_repair_plan_projections(project_id, incident_id)
        attempts = self.build_recovery_attempt_projections(project_id, incident_id)

        if not reference.schema_supported:
            add(
                "unknown",
                "warning",
                reference.source_schema_id,
                SUPPORTED_INCIDENT_SCHEMA_ID,
                "The incident schema is not supported by this panel.",
            )

        # Stage identity: Error Doctor versus Root Cause Analyzer for one incident.
        for analysis in analysis_cases:
            analysis_stage = _safe_text(analysis.get("workflow_stage"), 180)
            if analysis_stage and analysis_stage != reference.affected_stage_id:
                add(
                    "stage_identity_conflict",
                    "critical",
                    reference.affected_stage_id,
                    analysis_stage,
                    "Error Doctor and Root Cause Analyzer name different workflow "
                    "stages for the same incident.",
                    blocks=True,
                )
                break
            analysis_module = _safe_text(analysis.get("primary_module"), 180)
            if analysis_module and analysis_module != reference.affected_module_id:
                add(
                    "diagnosis_conflict",
                    "warning",
                    reference.affected_module_id,
                    analysis_module,
                    "Error Doctor and Root Cause Analyzer name different primary "
                    "modules for the same incident.",
                )
                break

        # More than one current root-cause candidate and no explicit supersession.
        competing = [item for item in root_causes if item.current]
        if len(competing) > 1:
            add(
                "root_cause_conflict",
                "warning",
                competing[0].root_cause_id,
                competing[1].root_cause_id,
                f"{len(competing)} current root-cause candidates exist for this "
                "incident and the owner records no supersession. They are shown "
                "side by side and are never resolved by comparing confidence.",
                root_cause_ids=[item.root_cause_id for item in competing][:16],
            )

        # Multiple competing causes declared by the owner itself.
        for analysis in analysis_cases:
            if _safe_text(analysis.get("analysis_status"), 120) in {
                "multiple_competing_causes",
                "conflicting_evidence",
            }:
                add(
                    "diagnosis_conflict",
                    "warning",
                    _safe_text(analysis.get("analysis_status"), 120),
                    "no single supported cause",
                    "Root Cause Analyzer itself reports competing or conflicting "
                    "causes for this incident.",
                )
                break

        # Recovery reported success while a later attempt failed.
        succeeded = [item for item in attempts if item.succeeded_by_owner]
        failed = [
            item
            for item in attempts
            if item.original_status in {"failed", "timed_out", "rejected"}
        ]
        if succeeded and failed:
            add(
                "recovery_status_conflict",
                "warning",
                f"owner reported success on {succeeded[0].recovery_attempt_id}",
                f"failure recorded on {failed[0].recovery_attempt_id}",
                "Tool Recovery records both an owner-reported success and a failed "
                "attempt for this incident. Both are shown.",
                recovery_ids=[item.recovery_attempt_id for item in attempts][:16],
            )

        # Owner reported success but nothing verified it.
        unverified = [
            item for item in attempts if item.succeeded_by_owner and not item.verified
        ]
        if unverified:
            add(
                "validation_conflict",
                "warning",
                "owner reported recovery success",
                "no output validation or validator record confirms it",
                "A recovery attempt reports success with no independent "
                "verification record. Recovered is not resolved.",
                recovery_ids=[item.recovery_attempt_id for item in unverified][:16],
            )

        # A repair plan claims no repair is needed while the incident blocks work.
        blocking_impact = _safe_text(record.get("processing_impact"), 120) in {
            "full_block",
            "unsafe_to_continue",
        }
        not_needed = [
            item
            for item in repairs
            if item.original_status in {"repair_not_required", "no_repair"}
        ]
        if blocking_impact and not_needed:
            add(
                "repair_plan_conflict",
                "warning",
                _safe_text(record.get("processing_impact"), 120),
                "repair not required",
                "Error Doctor reports blocking processing impact while Repair "
                "Planner reports that no repair is required.",
                repair_ids=[item.repair_plan_id for item in not_needed][:16],
            )

        # Severity conflict between the incident and its artifact evidence.
        artifact_payload = self._source_payload("artifact_inspector", project_id)
        artifact_incidents = [
            _as_mapping(item)
            for item in artifact_payload.get("incidents", [])
            if isinstance(item, Mapping)
        ]
        for artifact_incident in artifact_incidents:
            severity = _safe_text(artifact_incident.get("severity"), 80)
            if (
                severity == "critical"
                and reference.original_severity in {"low", "informational"}
            ):
                add(
                    "severity_conflict",
                    "warning",
                    reference.original_severity,
                    severity,
                    "Artifact Inspector records a critical artifact incident while "
                    "Error Doctor records a lower severity. Both are shown.",
                )
                break
        return conflicts[:_MAX_CONFLICTS]

    def inspect_incident_conflicts(self, project_id: str, incident_id: str) -> dict[str, Any]:
        conflicts = self.detect_incident_conflicts(project_id, incident_id)
        return {
            "schema_version": "boba_error_doctor_review_conflicts_v1",
            "project_id": project_id,
            "incident_id": incident_id,
            "conflict_records": [item.model_dump(mode="json") for item in conflicts],
            "blocking_conflict_count": sum(1 for item in conflicts if item.blocks_action),
            "unresolved_conflict_count": sum(
                1 for item in conflicts if not item.resolved
            ),
            "limitations": [
                "Conflicts are reported only between records naming the same exact "
                "identity, and are never resolved by comparing or averaging "
                "confidence.",
                "The panel never selects a winning record.",
            ],
        }

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------
    @staticmethod
    def _priority(
        *,
        critical_safety: bool,
        workflow_blocking: bool,
        failed_recovery: bool,
        conflicting: bool,
        missing_diagnosis: bool,
        missing_root_cause: bool,
        repair_awaiting_approval: bool,
        stale_verification: bool,
        recurring: bool,
        recovered_unverified: bool,
        resolved: bool,
        superseded: bool,
        historical: bool,
    ) -> tuple[int, str]:
        """Deterministic presentation tier. Never a score or a danger ranking."""
        tiers = dict(INCIDENT_QUEUE_PRIORITY_TIERS)
        if historical:
            return (140, tiers[140])
        if superseded:
            return (130, tiers[130])
        if critical_safety:
            return (10, tiers[10])
        if workflow_blocking:
            return (20, tiers[20])
        if failed_recovery:
            return (30, tiers[30])
        if conflicting:
            return (40, tiers[40])
        if missing_diagnosis:
            return (50, tiers[50])
        if missing_root_cause:
            return (60, tiers[60])
        if repair_awaiting_approval:
            return (70, tiers[70])
        if stale_verification:
            return (80, tiers[80])
        if recurring:
            return (90, tiers[90])
        if recovered_unverified:
            return (110, tiers[110])
        if resolved:
            return (120, tiers[120])
        return (100, tiers[100])

    def _queue_item(
        self, project_id: str, reference: BobaIncidentReferenceV1, creation_index: int
    ) -> BobaIncidentQueueItemV1:
        incident_id = reference.incident_id
        record = self._incident_record(project_id, incident_id)
        analysis_cases = self._analysis_cases_for(project_id, incident_id)
        root_causes = self.build_root_cause_projections(project_id, incident_id)
        repairs = self.build_repair_plan_projections(project_id, incident_id)
        attempts = self.build_recovery_attempt_projections(project_id, incident_id)
        conflicts = self.detect_incident_conflicts(project_id, incident_id)
        cards = self.build_evidence_cards(project_id, incident_id)
        validation = self.inspect_validation_evidence(project_id, incident_id)
        artifacts = self.inspect_artifact_evidence(project_id, incident_id)
        missing_evidence = sum(1 for item in cards if item.missing)
        failed_attempts = [
            item
            for item in attempts
            if item.original_status in {"failed", "timed_out", "rejected", "blocked"}
        ]
        safety_impact = _safe_text(record.get("safety_impact"), 120)
        processing_impact = _safe_text(record.get("processing_impact"), 120)
        severity = reference.original_severity
        recurring = len(analysis_cases) > 1 or any(
            _safe_text(item.get("occurrence_count"), 20) not in {"", "1"}
            for item in self._source_payload("artifact_inspector", project_id).get(
                "incidents", []
            )
            if isinstance(item, Mapping)
        )
        recovered_unverified = any(
            item.succeeded_by_owner and not item.verified for item in attempts
        )
        repair_awaiting_approval = any(item.requires_human_approval for item in repairs)
        warning_count = len(
            [item for item in record.get("warnings", []) if isinstance(item, str)]
        ) + len([item for item in record.get("limitations", []) if isinstance(item, str)])
        blocking_cards = [item for item in cards if item.blocking]

        priority, reason = self._priority(
            critical_safety=severity in {"critical", "blocker"}
            and safety_impact
            in {"safety_gate_blocked", "rights_gate_blocked", "destructive_risk"},
            workflow_blocking=processing_impact in {"full_block", "unsafe_to_continue"},
            failed_recovery=bool(failed_attempts),
            conflicting=bool(conflicts),
            missing_diagnosis=not bool(record.get("probable_cause_summary")),
            missing_root_cause=not bool(root_causes),
            repair_awaiting_approval=repair_awaiting_approval,
            stale_verification=validation["missing_validation_evidence"]
            or artifacts["missing_artifact_evidence_count"] > 0,
            recurring=recurring,
            recovered_unverified=recovered_unverified,
            resolved=reference.resolved,
            superseded=reference.superseded,
            historical=reference.historical,
        )
        digests = {
            item.source_module_id: item.source_record_digest
            for item in cards
            if item.source_record_digest
        }
        severity_rank = (
            _SEVERITY_ORDER.index(severity) if severity in _SEVERITY_ORDER else 99
        )
        return BobaIncidentQueueItemV1(
            incident_queue_item_id=_stable_id(
                "incident_queue", project_id, incident_id
            ),
            incident_reference_id=reference.incident_reference_id,
            project_id=project_id,
            workflow_run_id=reference.workflow_run_id,
            stage_instance_id=reference.stage_instance_id,
            incident_id=incident_id,
            title=_safe_text(record.get("title"), 240) or incident_id,
            bounded_summary=_safe_text(record.get("symptom_summary"), 900),
            affected_module_id=reference.affected_module_id,
            affected_operation_id=reference.affected_operation_id,
            affected_stage_id=reference.affected_stage_id,
            original_error_class=reference.error_class,
            original_error_code=None,
            original_severity=severity,
            original_status=reference.original_status,
            diagnosis_status=reference.original_status,
            root_cause_status=(
                _safe_text(analysis_cases[0].get("analysis_status"), 120)
                if analysis_cases
                else "unavailable"
            ),
            repair_plan_status=(
                repairs[0].original_status if repairs else "unavailable"
            ),
            recovery_status=(
                attempts[0].original_status if attempts else "unavailable"
            ),
            validation_status=(
                "available" if validation["validator_available"] else "unavailable"
            ),
            artifact_status=(
                "available" if artifacts["artifact_inspector_available"] else "unavailable"
            ),
            workflow_status=self._source_status(
                "workflow_controller",
                self._source_payload("workflow_controller", project_id),
            ),
            current=reference.current,
            stale=reference.stale,
            historical=reference.historical,
            superseded=reference.superseded,
            recovered=reference.recovered,
            resolved=reference.resolved,
            recurring=recurring,
            human_action_required=bool(conflicts)
            or repair_awaiting_approval
            or any(item.human_confirmation_required for item in root_causes),
            blocker_count=len(blocking_cards)
            + sum(1 for item in conflicts if item.blocks_action),
            warning_count=warning_count,
            missing_evidence_count=missing_evidence,
            conflict_count=len(conflicts),
            failed_recovery_attempt_count=len(failed_attempts),
            available_action_descriptor_ids=self._available_actions(reference),
            source_module_ids=[item.source_module_id for item in cards if item.current],
            source_record_ids=list(digests),
            source_record_digests=digests,
            priority_tier=priority,
            priority_reason=reason,
            deterministic_sort_key=(
                f"{priority:03d}:{severity_rank:02d}:{creation_index:04d}:{incident_id}"
            ),
            warnings=[
                _safe_text(item, 300)
                for item in record.get("warnings", [])
                if isinstance(item, str)
            ][:12],
            limitations=[
                "Priority is a deterministic display order, not a score, a danger "
                "ranking or a repair-success estimate.",
            ],
        )

    @staticmethod
    def _filter_queue(
        items: list[BobaIncidentQueueItemV1], review_filter: str
    ) -> list[BobaIncidentQueueItemV1]:
        if review_filter in {"all_current", "", "all"}:
            return [item for item in items if not item.historical]
        if review_filter == "critical":
            return [
                item
                for item in items
                if item.original_severity in {"critical", "blocker"}
            ]
        if review_filter == "workflow_blocking":
            return [item for item in items if item.priority_tier == 20]
        if review_filter == "human_review_required":
            return [item for item in items if item.human_action_required]
        if review_filter == "missing_diagnosis":
            return [item for item in items if item.priority_tier == 50]
        if review_filter == "missing_root_cause":
            return [item for item in items if item.root_cause_status == "unavailable"]
        if review_filter == "repair_plan_available":
            return [item for item in items if item.repair_plan_status != "unavailable"]
        if review_filter == "failed_recovery":
            return [item for item in items if item.failed_recovery_attempt_count > 0]
        if review_filter == "unverified_recovery":
            return [item for item in items if item.priority_tier == 110]
        if review_filter == "recurring":
            return [item for item in items if item.recurring]
        if review_filter == "conflicts":
            return [item for item in items if item.conflict_count > 0]
        if review_filter == "missing_evidence":
            return [item for item in items if item.missing_evidence_count > 0]
        if review_filter == "stale":
            return [item for item in items if item.stale]
        if review_filter == "recovered":
            return [item for item in items if item.recovered]
        if review_filter == "resolved":
            return [item for item in items if item.resolved]
        if review_filter == "historical":
            return [item for item in items if item.historical]
        if review_filter == "superseded":
            return [item for item in items if item.superseded]
        raise ValidationError("Unsupported error doctor review filter.")

    @staticmethod
    def _sort_queue(
        items: list[BobaIncidentQueueItemV1], sort: str
    ) -> list[BobaIncidentQueueItemV1]:
        rows = list(items)

        def severity_rank(item: BobaIncidentQueueItemV1) -> int:
            severity = item.original_severity
            return _SEVERITY_ORDER.index(severity) if severity in _SEVERITY_ORDER else 99

        if sort in {"review_priority", "", "priority"}:
            rows.sort(key=lambda item: (item.priority_tier, item.deterministic_sort_key))
        elif sort == "source_severity":
            rows.sort(key=lambda item: (severity_rank(item), item.incident_id))
        elif sort == "first_seen":
            rows.sort(key=lambda item: (item.deterministic_sort_key, item.incident_id))
        elif sort == "last_seen":
            rows.sort(
                key=lambda item: (item.deterministic_sort_key, item.incident_id),
                reverse=True,
            )
        elif sort == "affected_stage":
            rows.sort(key=lambda item: (item.affected_stage_id, item.incident_id))
        elif sort == "affected_module":
            rows.sort(key=lambda item: (item.affected_module_id, item.incident_id))
        elif sort == "incident_id":
            rows.sort(key=lambda item: item.incident_id)
        else:
            raise ValidationError("Unsupported error doctor review sort.")
        return rows

    def build_incident_queue(
        self,
        project_id: str,
        *,
        review_filter: str = "all_current",
        sort: str = "review_priority",
        offset: int = 0,
        limit: int = MAX_QUEUE_PAGE_SIZE,
    ) -> dict[str, Any]:
        references = self.build_incident_references(project_id)
        items = [
            self._queue_item(project_id, reference, index)
            for index, reference in enumerate(references)
        ]
        items = self._filter_queue(items, review_filter)
        items = self._sort_queue(items, sort)
        safe_offset = max(0, offset)
        safe_limit = max(1, min(limit, MAX_QUEUE_PAGE_SIZE))
        return {
            "schema_version": "boba_error_doctor_review_queue_v1",
            "project_id": project_id,
            "total": len(items),
            "offset": safe_offset,
            "limit": safe_limit,
            "active_filter": review_filter,
            "active_sort": sort,
            "priority_tiers": [
                {"priority": priority, "reason": reason}
                for priority, reason in INCIDENT_QUEUE_PRIORITY_TIERS
            ],
            "items": [
                item.model_dump(mode="json")
                for item in items[safe_offset : safe_offset + safe_limit]
            ],
        }

    def inspect_incident_queue(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.build_incident_queue(project_id, **kwargs)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    def _available_actions(
        self,
        reference: BobaIncidentReferenceV1,
        blocking_conflicts: list[BobaErrorConflictV1] | None = None,
    ) -> list[str]:
        state = (
            "superseded"
            if reference.superseded
            else "historical"
            if reference.historical
            else "resolved"
            if reference.resolved
            else "recovered"
            if reference.recovered
            else "stale"
            if reference.stale
            else "current"
        )
        available: list[str] = []
        for descriptor in build_fixed_error_doctor_action_registry().values():
            if not descriptor.allowed_in_v1 or descriptor.availability != "available":
                continue
            if descriptor.supported_incident_states and state not in (
                descriptor.supported_incident_states
            ):
                continue
            if descriptor.requires_current_snapshot and not reference.current:
                continue
            if descriptor.requires_current_snapshot and blocking_conflicts:
                continue
            available.append(descriptor.action_descriptor_id)
        return available

    def build_incident_snapshot(
        self, project_id: str, session_id: str, incident_id: str
    ) -> dict[str, Any]:
        session = self.get_error_doctor_review_session(project_id, session_id)
        reference = self._reference_for(project_id, incident_id)
        snapshot_id = f"incident_snapshot_{uuid4().hex}"
        diagnoses = self.build_diagnosis_projections(
            project_id, incident_id, snapshot_id=snapshot_id
        )
        root_causes = self.build_root_cause_projections(
            project_id, incident_id, snapshot_id=snapshot_id
        )
        cards = self.build_evidence_cards(
            project_id, incident_id, snapshot_id=snapshot_id
        )
        repairs = self.build_repair_plan_projections(
            project_id, incident_id, snapshot_id=snapshot_id
        )
        attempts = self.build_recovery_attempt_projections(
            project_id, incident_id, snapshot_id=snapshot_id
        )
        conflicts = self.detect_incident_conflicts(
            project_id, incident_id, snapshot_id=snapshot_id
        )
        validation = self.inspect_validation_evidence(project_id, incident_id)
        artifacts = self.inspect_artifact_evidence(project_id, incident_id)
        digests = {
            item.source_module_id: item.source_record_digest
            for item in cards
            if item.source_record_digest
        }
        project_digest = self._project_snapshot_digest(project_id)
        revision = self._workflow_revision(project_id)
        incident_digest = self._incident_digest(project_id, incident_id)
        blocking = [item for item in conflicts if item.blocks_action]
        confirmation = _digest(
            {
                "project": project_digest,
                "revision": revision,
                "incident": incident_digest,
                "incident_id": incident_id,
            }
        )

        def status_of(module_id: str) -> str:
            return next(
                (
                    item.original_status
                    for item in cards
                    if item.source_module_id == module_id
                ),
                "unavailable",
            )

        snapshot = BobaIncidentSnapshotV1(
            incident_snapshot_id=snapshot_id,
            error_doctor_review_session_id=session.error_doctor_review_session_id,
            incident_reference_id=reference.incident_reference_id,
            project_id=project_id,
            workflow_run_id=reference.workflow_run_id,
            stage_instance_id=reference.stage_instance_id,
            incident_id=incident_id,
            project_snapshot_digest=project_digest,
            workflow_revision=revision,
            incident_digest=incident_digest,
            source_record_references=[
                {"module_id": item.source_module_id, "record_id": item.source_record_id}
                for item in cards
            ][:24],
            source_record_digests=digests,
            diagnosis_projection_ids=[
                item.diagnosis_projection_id for item in diagnoses
            ],
            root_cause_projection_ids=[
                item.root_cause_projection_id for item in root_causes
            ],
            evidence_card_ids=[item.evidence_card_id for item in cards],
            repair_plan_projection_ids=[
                item.repair_plan_projection_id for item in repairs
            ],
            recovery_attempt_projection_ids=[
                item.recovery_attempt_projection_id for item in attempts
            ],
            validation_evidence_ids=[
                _safe_text(item["validation_run_id"], 180)
                for item in validation["validation_runs"]
            ][:64],
            artifact_evidence_ids=[
                _safe_text(item["artifact_id"], 180)
                for item in artifacts["affected_artifacts"]
            ][:64],
            conflict_record_ids=[item.conflict_record_id for item in conflicts],
            incident_status=reference.original_status,
            diagnosis_status=diagnoses[0].original_status if diagnoses else "unavailable",
            root_cause_status=(
                root_causes[0].original_status if root_causes else "unavailable"
            ),
            repair_plan_status=repairs[0].original_status if repairs else "unavailable",
            recovery_status=attempts[0].original_status if attempts else "unavailable",
            validation_status=status_of("validator_runner"),
            artifact_status=status_of("artifact_inspector"),
            workflow_status=status_of("workflow_controller"),
            rights_status=status_of("safety_gate"),
            safety_status=status_of("safety_gate"),
            final_decision_status=status_of("final_decision_bus"),
            current=reference.current,
            stale=reference.stale,
            historical=reference.historical,
            superseded=reference.superseded,
            recovered=reference.recovered,
            resolved=reference.resolved,
            missing_evidence_count=sum(1 for item in cards if item.missing),
            conflict_count=len(conflicts),
            warning_count=sum(len(item.warnings) for item in cards),
            limitation_count=sum(len(item.limitations) for item in cards),
            available_action_descriptor_ids=self._available_actions(reference, blocking),
            confirmation_context_digest=confirmation,
            snapshot_digest=_digest(
                {
                    "project": project_digest,
                    "revision": revision,
                    "incident": incident_digest,
                    "sources": digests,
                    "session": session.error_doctor_review_session_id,
                }
            ),
            limitations=[
                "Snapshot status is display-only and links to canonical owner records.",
                "Error Doctor Panel V1 exposes no repair, recovery, checkpoint or "
                "workflow action.",
                "Recovered is never reported as resolved.",
            ],
        )
        self.store.save_boba_error_doctor_review_snapshot(
            project_id, snapshot_id, snapshot.model_dump(mode="json")
        )
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "incident_reference": reference.model_dump(mode="json"),
            "diagnosis_projections": [item.model_dump(mode="json") for item in diagnoses],
            "root_cause_projections": [
                item.model_dump(mode="json") for item in root_causes
            ],
            "evidence_cards": [item.model_dump(mode="json") for item in cards],
            "repair_plan_projections": [item.model_dump(mode="json") for item in repairs],
            "recovery_attempt_projections": [
                item.model_dump(mode="json") for item in attempts
            ],
            "validation_evidence": validation,
            "artifact_evidence": artifacts,
            "conflict_records": [item.model_dump(mode="json") for item in conflicts],
            "action_confirmations": self._action_confirmations(snapshot),
        }

    def refresh_incident_snapshot(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = self._snapshot(project_id, snapshot_id)
        return self.build_incident_snapshot(
            project_id, snapshot.error_doctor_review_session_id, snapshot.incident_id
        )

    def _snapshot(self, project_id: str, snapshot_id: str) -> BobaIncidentSnapshotV1:
        _safe_id(project_id, "project id")
        _safe_id(snapshot_id, "incident snapshot id")
        raw = self.store.load_boba_error_doctor_review_snapshot(project_id, snapshot_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA incident snapshot is unavailable.")
        snapshot = BobaIncidentSnapshotV1.model_validate(raw)
        if snapshot.project_id != project_id:
            raise ValidationError("Incident snapshot belongs to another project.")
        return snapshot

    def _action_confirmations(self, snapshot: BobaIncidentSnapshotV1) -> dict[str, str]:
        registry = build_fixed_error_doctor_action_registry()
        tokens: dict[str, str] = {}
        for action_id in snapshot.available_action_descriptor_ids:
            descriptor = registry.get(action_id)
            if descriptor is None:
                continue
            tokens[action_id] = _digest(
                {
                    "snapshot": snapshot.snapshot_digest,
                    "action": descriptor.action_descriptor_id,
                    "incident": snapshot.incident_digest,
                }
            )
        return tokens

    def inspect_incident(self, project_id: str, incident_id: str) -> dict[str, Any]:
        reference = self._reference_for(project_id, incident_id)
        return {
            "schema_version": "boba_error_doctor_review_incident_v1",
            "project_id": project_id,
            "incident_id": incident_id,
            "incident_reference": reference.model_dump(mode="json"),
            "diagnosis_projections": [
                item.model_dump(mode="json")
                for item in self.build_diagnosis_projections(project_id, incident_id)
            ],
            "root_cause_projections": [
                item.model_dump(mode="json")
                for item in self.build_root_cause_projections(project_id, incident_id)
            ],
            "evidence_cards": [
                item.model_dump(mode="json")
                for item in self.build_evidence_cards(project_id, incident_id)
            ],
            "repair_plan_projections": [
                item.model_dump(mode="json")
                for item in self.build_repair_plan_projections(project_id, incident_id)
            ],
            "recovery_attempt_projections": [
                item.model_dump(mode="json")
                for item in self.build_recovery_attempt_projections(
                    project_id, incident_id
                )
            ],
            "conflict_records": [
                item.model_dump(mode="json")
                for item in self.detect_incident_conflicts(project_id, incident_id)
            ],
        }

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    def compare_incidents(
        self,
        project_id: str,
        incident_ids: list[str],
        *,
        comparison_type: str = "side_by_side",
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        unique: list[str] = []
        for incident_id in incident_ids:
            _safe_id(incident_id, "incident id")
            if incident_id not in unique:
                unique.append(incident_id)
        if len(unique) < 2:
            raise ValidationError("At least two distinct incidents are required.")
        if len(unique) > MAX_COMPARISON_INCIDENTS:
            raise ValidationError(
                f"At most {MAX_COMPARISON_INCIDENTS} incidents may be compared."
            )
        if comparison_type not in {
            "side_by_side",
            "recurring_incidents",
            "current_vs_historical",
            "same_stage",
            "same_module",
            "diagnosis",
            "root_cause",
            "repair_plan",
            "recovery_attempt",
            "verification",
            "unknown",
        }:
            raise ValidationError("Unsupported error doctor comparison type.")
        references = [self._reference_for(project_id, item) for item in unique]
        diagnoses = {
            item: self.build_diagnosis_projections(project_id, item) for item in unique
        }
        root_causes = {
            item: self.build_root_cause_projections(project_id, item) for item in unique
        }
        repairs = {
            item: self.build_repair_plan_projections(project_id, item) for item in unique
        }
        attempts = {
            item: self.build_recovery_attempt_projections(project_id, item)
            for item in unique
        }
        cards = {item: self.build_evidence_cards(project_id, item) for item in unique}
        validation = {
            item: self.inspect_validation_evidence(project_id, item) for item in unique
        }
        artifacts = {
            item: self.inspect_artifact_evidence(project_id, item) for item in unique
        }
        record = {item: self._incident_record(project_id, item) for item in unique}

        def rows(builder: Any) -> list[dict[str, Any]]:
            return [{"incident_id": item, **builder(item)} for item in unique]

        comparison = BobaErrorDoctorComparisonV1(
            comparison_id=_stable_id("error_doctor_comparison", project_id, *unique),
            project_id=project_id,
            incident_ids=unique,
            comparison_type=comparison_type,
            same_workflow_run=len({item.workflow_run_id for item in references}) == 1,
            same_stage=len({item.affected_stage_id for item in references}) == 1,
            same_affected_module=len({item.affected_module_id for item in references})
            == 1,
            error_class_comparison=rows(
                lambda item: {
                    "error_class": next(
                        row.error_class
                        for row in references
                        if row.incident_id == item
                    ),
                    "error_code": None,
                }
            ),
            severity_comparison=rows(
                lambda item: {
                    "original_severity": next(
                        row.original_severity
                        for row in references
                        if row.incident_id == item
                    ),
                    "original_status": next(
                        row.original_status
                        for row in references
                        if row.incident_id == item
                    ),
                }
            ),
            diagnosis_comparison=rows(
                lambda item: {
                    "diagnosis_status": (
                        diagnoses[item][0].original_status
                        if diagnoses[item]
                        else "unavailable"
                    ),
                    "original_category": (
                        diagnoses[item][0].original_category
                        if diagnoses[item]
                        else "unavailable"
                    ),
                    "confidence_value": (
                        diagnoses[item][0].confidence_value if diagnoses[item] else None
                    ),
                    "confidence_comparable_across_sources": False,
                }
            ),
            root_cause_comparison=rows(
                lambda item: {
                    "candidate_count": len(root_causes[item]),
                    "confirmed_count": sum(
                        1 for row in root_causes[item] if row.confirmed
                    ),
                    "hypothesis_count": sum(
                        1 for row in root_causes[item] if row.hypothesis
                    ),
                    "candidate_ids": [row.root_cause_id for row in root_causes[item]][:16],
                }
            ),
            evidence_coverage_comparison=rows(
                lambda item: {
                    "evidence_card_count": len(cards[item]),
                    "missing_evidence_count": sum(
                        1 for row in cards[item] if row.missing
                    ),
                }
            ),
            repair_plan_comparison=rows(
                lambda item: {
                    "plan_count": len(repairs[item]),
                    "requires_human_approval": any(
                        row.requires_human_approval for row in repairs[item]
                    ),
                    "destructive_plan_count": sum(
                        1 for row in repairs[item] if row.destructive
                    ),
                    "executable_by_panel": False,
                }
            ),
            recovery_history_comparison=rows(
                lambda item: {
                    "attempt_count": len(attempts[item]),
                    "failed_attempt_count": sum(
                        1
                        for row in attempts[item]
                        if row.original_status
                        in {"failed", "timed_out", "rejected", "blocked"}
                    ),
                    "owner_reported_success_count": sum(
                        1 for row in attempts[item] if row.succeeded_by_owner
                    ),
                    "independently_verified_count": sum(
                        1 for row in attempts[item] if row.verified
                    ),
                }
            ),
            validation_comparison=rows(
                lambda item: {
                    "validator_available": validation[item]["validator_available"],
                    "missing_validation_evidence": validation[item][
                        "missing_validation_evidence"
                    ],
                }
            ),
            artifact_comparison=rows(
                lambda item: {
                    "artifact_inspector_available": artifacts[item][
                        "artifact_inspector_available"
                    ],
                    "missing_artifact_evidence_count": artifacts[item][
                        "missing_artifact_evidence_count"
                    ],
                }
            ),
            warning_comparison=rows(
                lambda item: {
                    "warning_count": len(
                        [
                            row
                            for row in record[item].get("warnings", [])
                            if isinstance(row, str)
                        ]
                    )
                }
            ),
            limitation_comparison=rows(
                lambda item: {
                    "limitation_count": len(
                        [
                            row
                            for row in record[item].get("limitations", [])
                            if isinstance(row, str)
                        ]
                    )
                }
            ),
            current_incident_ids=[
                item.incident_id for item in references if item.current
            ],
            historical_incident_ids=[
                item.incident_id for item in references if item.historical
            ],
            bounded_summary=(
                f"Comparing {len(unique)} incidents side by side. No incident, root "
                "cause or repair plan is selected."
            ),
            limitations=[
                "Comparison shows differences only. It never selects a winning "
                "incident, a correct root cause or a best repair plan.",
                "Confidence values from different modules are never compared or "
                "averaged.",
                "Missing records are shown as missing rather than filled in.",
            ],
        )
        return {"comparison": comparison.model_dump(mode="json")}

    # ------------------------------------------------------------------
    # Canonical action routing
    # ------------------------------------------------------------------
    def _action_descriptor(self, action_id: str) -> BobaErrorDoctorActionDescriptorV1:
        _safe_id(action_id, "action descriptor id")
        descriptor = build_fixed_error_doctor_action_registry().get(action_id)
        if descriptor is None:
            raise ValidationError(
                "Unknown fixed BOBA error doctor review action descriptor."
            )
        return descriptor

    def create_error_doctor_action_request(
        self,
        project_id: str,
        *,
        error_doctor_review_session_id: str,
        incident_snapshot_id: str,
        action_descriptor_id: str,
        decision_value: str | None,
        reason: str,
        confirmation_context_digest: str,
        idempotency_key: str,
        confirmed: bool,
    ) -> BobaErrorDoctorActionRequestV1:
        session = self.get_error_doctor_review_session(
            project_id, error_doctor_review_session_id
        )
        snapshot = self._snapshot(project_id, incident_snapshot_id)
        if snapshot.error_doctor_review_session_id != (
            session.error_doctor_review_session_id
        ):
            raise ValidationError("Incident snapshot belongs to another review session.")
        descriptor = self._action_descriptor(action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            raise ValidationError(
                "This BOBA error doctor review action is unavailable in V1."
            )
        if descriptor.action_descriptor_id not in snapshot.available_action_descriptor_ids:
            raise ValidationError("The action is unavailable for this exact incident.")
        if descriptor.allowed_decision_values and decision_value not in (
            descriptor.allowed_decision_values
        ):
            raise ValidationError("Unsupported decision value for this fixed action.")
        if descriptor.requires_reason and not reason.strip():
            raise ValidationError("This error doctor review action requires a reason.")
        if len(reason) > descriptor.maximum_reason_length:
            raise ValidationError("Error doctor review reason exceeds the allowed length.")
        if _SENSITIVE_KEY.search(reason) or any(
            pattern.search(reason) for pattern in _SECRET_VALUE_PATTERNS
        ):
            raise ValidationError("Error doctor review reasons cannot contain credentials.")
        if _PRIVATE_PATH.search(reason):
            raise ValidationError(
                "Error doctor review reasons cannot contain private path material."
            )
        if not confirmed:
            raise ValidationError("Explicit error doctor review confirmation is required.")
        if descriptor.requires_reviewer_context and not session.reviewer_context_id:
            raise ValidationError("An exact reviewer context is required.")
        expected = self._action_confirmations(snapshot).get(descriptor.action_descriptor_id)
        if not expected or confirmation_context_digest != expected:
            raise ValidationError(
                "Error doctor review confirmation does not match the current incident."
            )
        _safe_id(idempotency_key, "idempotency key")
        request = BobaErrorDoctorActionRequestV1(
            error_doctor_action_request_id=f"error_doctor_action_{uuid4().hex}",
            error_doctor_review_session_id=session.error_doctor_review_session_id,
            incident_snapshot_id=snapshot.incident_snapshot_id,
            project_id=project_id,
            workflow_run_id=snapshot.workflow_run_id,
            stage_instance_id=snapshot.stage_instance_id,
            incident_id=snapshot.incident_id,
            expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            reviewer_context_id=session.reviewer_context_id,
            action_descriptor_id=descriptor.action_descriptor_id,
            owning_module_id=descriptor.owning_module_id,
            owning_operation_id=descriptor.owning_operation_id,
            decision_value=decision_value,
            bounded_reason=_safe_text(reason, descriptor.maximum_reason_length),
            expected_project_snapshot_digest=snapshot.project_snapshot_digest,
            expected_workflow_revision=snapshot.workflow_revision,
            expected_incident_digest=snapshot.incident_digest,
            expected_source_record_digests=snapshot.source_record_digests,
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
        self.store.save_boba_error_doctor_review_action(
            project_id,
            request.error_doctor_action_request_id,
            request.model_dump(mode="json"),
        )
        return request

    def validate_error_doctor_action_request(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        """Re-read canonical state and reject stale or drifted submissions."""
        request = self._action_request(project_id, request_id)
        expires_at = _parse_time(request.expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            return {
                "valid": False,
                "code": "expired_snapshot",
                "message": "The error doctor review action expired before submission.",
            }
        descriptor = self._action_descriptor(request.action_descriptor_id)
        if not descriptor.allowed_in_v1 or descriptor.availability != "available":
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "This error doctor review action is no longer available.",
            }
        try:
            reference = self._reference_for(project_id, request.incident_id)
        except ValidationError:
            return {
                "valid": False,
                "code": "incident_removed",
                "message": "The incident is no longer available.",
            }
        if reference.workflow_run_id != request.workflow_run_id:
            return {
                "valid": False,
                "code": "workflow_identity_mismatch",
                "message": "The incident now references a different workflow run.",
            }
        if reference.affected_stage_id and request.stage_instance_id is not None and (
            reference.stage_instance_id != request.stage_instance_id
        ):
            return {
                "valid": False,
                "code": "stage_identity_mismatch",
                "message": "The incident now references a different workflow stage.",
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
        if self._incident_digest(project_id, request.incident_id) != (
            request.expected_incident_digest
        ):
            return {
                "valid": False,
                "code": "incident_digest_mismatch",
                "message": "The incident changed while this review was open.",
            }
        live = {
            item.source_module_id: item.source_record_digest
            for item in self.build_evidence_cards(project_id, request.incident_id)
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
            for item in self.detect_incident_conflicts(project_id, request.incident_id)
            if item.blocks_action
        ]
        if descriptor.action_descriptor_id not in self._available_actions(
            reference, blocking
        ):
            return {
                "valid": False,
                "code": "action_unavailable",
                "message": "The action is no longer available for this exact incident.",
            }
        return {
            "valid": True,
            "code": "current",
            "message": "Exact incident state remains current.",
        }

    def _action_request(
        self, project_id: str, request_id: str
    ) -> BobaErrorDoctorActionRequestV1:
        _safe_id(project_id, "project id")
        _safe_id(request_id, "error doctor action request id")
        raw = self.store.load_boba_error_doctor_review_action(project_id, request_id)
        if not isinstance(raw, Mapping):
            raise ValidationError("BOBA error doctor review action request is unavailable.")
        request = BobaErrorDoctorActionRequestV1.model_validate(raw)
        if request.project_id != project_id:
            raise ValidationError("Error doctor action belongs to another project.")
        return request

    async def submit_error_doctor_action_to_owner(
        self, project_id: str, request_id: str
    ) -> BobaErrorDoctorActionReceiptV1:
        """Submit to the canonical owner and persist an immutable receipt."""
        request = self._action_request(project_id, request_id)
        existing = self.store.load_boba_error_doctor_review_receipt_for_action(
            project_id, request_id
        )
        if isinstance(existing, Mapping):
            receipt = BobaErrorDoctorActionReceiptV1.model_validate(existing)
            return receipt.model_copy(update={"duplicate_request_reused": True})
        validation = self.validate_error_doctor_action_request(project_id, request_id)
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
        request: BobaErrorDoctorActionRequestV1,
        *,
        canonical_status: str,
        stale_state_rejected: bool = False,
        error_code: str | None = None,
        message: str = "",
        limitations: list[str] | None = None,
    ) -> BobaErrorDoctorActionReceiptV1:
        return BobaErrorDoctorActionReceiptV1(
            error_doctor_action_receipt_id=f"error_doctor_receipt_{uuid4().hex}",
            error_doctor_action_request_id=request.error_doctor_action_request_id,
            project_id=request.project_id,
            incident_id=request.incident_id,
            owning_module_id=request.owning_module_id,
            owning_operation_id=request.owning_operation_id,
            completed_at=now_iso(),
            accepted_by_owner=False,
            canonical_status=canonical_status,
            authoritative_state_changed=False,
            repair_executed=False,
            recovery_attempt_started=False,
            workflow_changed=False,
            code_changed=False,
            artifact_changed=False,
            stale_state_rejected=stale_state_rejected,
            error_code=error_code,
            bounded_error_message=_safe_text(message, 900),
            limitations=limitations or [],
        )

    async def _submit_acknowledgement(
        self, project_id: str, request: BobaErrorDoctorActionRequestV1
    ) -> BobaErrorDoctorActionReceiptV1:
        """Route to Review UI, the owner of incident acknowledgement metadata."""
        try:
            session_payload = self.integration.create_boba_review_session(
                project_id,
                reviewer_context_id=request.reviewer_context_id,
                review_mode="incident_review",
                target_type="incident",
                target_id=request.incident_id,
            )
            review_session_id = _safe_text(
                _as_mapping(session_payload).get("review_session_id"), 180
            )
            if not review_session_id:
                raise ValidationError("Review UI returned no review session identity.")
            acknowledged = self.integration.acknowledge_boba_review_notification(
                project_id, review_session_id, request.incident_id
            )
        except (ValidationError, NotFoundError) as error:
            return self._persist_receipt(
                project_id,
                self._receipt(
                    request,
                    canonical_status="rejected_by_owner",
                    error_code="owner_rejected",
                    message=str(error),
                    limitations=["Review UI rejected the acknowledgement; nothing changed."],
                ),
            )
        payload = _as_mapping(acknowledged)
        acknowledged_ids = payload.get("acknowledged_notification_ids")
        if not isinstance(acknowledged_ids, list) or (
            request.incident_id not in [str(item) for item in acknowledged_ids]
        ):
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
                    "canonical_request_id": request.error_doctor_action_request_id,
                    "canonical_record_id": _safe_text(
                        payload.get("review_session_id"), 180
                    ),
                    "canonical_record_digest": _safe_text(
                        payload.get("session_digest"), 64
                    )
                    or _digest(_safe_payload(payload)),
                    "canonical_status": "acknowledged",
                    # Acknowledgement is Review-UI-session metadata. No incident,
                    # diagnosis, repair, recovery, workflow, code or artifact
                    # authority changes.
                    "authoritative_state_changed": False,
                    "canonical_refresh_required": True,
                    "limitations": [
                        "Acknowledgement changes Review UI session metadata only.",
                        "The incident stays visible until its owning module "
                        "resolves it.",
                        *descriptor_does_not_do(request.action_descriptor_id),
                    ][:16],
                }
            ),
        )

    def _persist_receipt(
        self, project_id: str, receipt: BobaErrorDoctorActionReceiptV1
    ) -> BobaErrorDoctorActionReceiptV1:
        if receipt.authoritative_state_changed and not (
            receipt.canonical_record_id and receipt.canonical_record_digest
        ):
            raise ValidationError(
                "Authoritative state cannot change without a canonical owner record."
            )
        for flag, label in (
            (receipt.repair_executed, "repair execution"),
            (receipt.recovery_attempt_started, "recovery start"),
            (receipt.workflow_changed, "workflow change"),
            (receipt.code_changed, "code change"),
            (receipt.artifact_changed, "artifact change"),
        ):
            if flag and not (receipt.canonical_record_id and receipt.canonical_record_digest):
                raise ValidationError(
                    f"A receipt cannot claim {label} without a canonical owner record."
                )
        self.store.save_boba_error_doctor_review_receipt(
            project_id,
            receipt.error_doctor_action_receipt_id,
            receipt.model_dump(mode="json"),
        )
        return receipt

    def inspect_error_doctor_action_receipt(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        request = self._action_request(project_id, request_id)
        receipt = self.store.load_boba_error_doctor_review_receipt_for_action(
            project_id, request_id
        )
        return {
            "request": request.model_dump(mode="json"),
            "receipt": _safe_payload(receipt) if receipt else None,
        }

    # ------------------------------------------------------------------
    # Events, timeline, build, export, reset
    # ------------------------------------------------------------------
    def inspect_incident_events(
        self, project_id: str, *, after_sequence: int = 0, limit: int = _MAX_EVENTS
    ) -> dict[str, Any]:
        """Project bounded, de-duplicated canonical events. No invented progress."""
        _safe_id(project_id, "project id")
        seen: set[tuple[str, str]] = set()
        events: list[BobaErrorDoctorReviewEventV1] = []
        truncated_at_source = False
        for source_id in (
            "error_doctor",
            "observer",
            "root_cause_analyzer",
            "repair_planner",
            "tool_recovery",
            "validator_runner",
            "artifact_inspector",
            "workflow_controller",
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
                ) or _stable_id("error_doctor_event", source_id, _digest(safe))
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
                technical = bounded_technical_message(
                    safe.get("technical_message") or safe.get("message")
                )
                events.append(
                    BobaErrorDoctorReviewEventV1(
                        event_id=_stable_id("error_doctor_event", source_id, event_id),
                        project_id=project_id,
                        incident_id=_safe_text(safe.get("diagnostic_case_id"), 180) or None,
                        source_module_id=source_id,
                        source_event_id=event_id,
                        source_sequence=sequence,
                        created_at=_safe_text(
                            safe.get("created_at") or safe.get("occurred_at"), 80
                        )
                        or None,
                        event_type=event_type,
                        severity=_safe_text(safe.get("severity") or "informational", 80),
                        technical_message=technical["text"],
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
                        sensitive_values_redacted=technical["sensitive_values_redacted"],
                        private_paths_redacted=technical["private_paths_redacted"],
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
            "schema_version": "boba_error_doctor_review_events_v1",
            "project_id": project_id,
            "events": [item.model_dump(mode="json") for item in bounded],
            "has_more": len(events) > len(bounded) or truncated_at_source,
            "latest_sequence": max(
                (item.source_sequence or 0 for item in bounded), default=after_sequence
            ),
        }

    def inspect_incident_timeline(
        self, project_id: str, *, limit: int = MAX_TIMELINE_ENTRIES
    ) -> dict[str, Any]:
        events = self.inspect_incident_events(project_id, limit=limit)["events"]
        entries = [
            BobaErrorDoctorReviewTimelineEntryV1(
                timeline_entry_id=_stable_id(
                    "error_doctor_timeline", str(event["event_id"])
                ),
                project_id=project_id,
                incident_id=event.get("incident_id"),
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
                confirmed_fact=str(event.get("confirmed_fact") or ""),
                source_assessment=str(event.get("assessment") or ""),
                severity=str(event.get("severity") or "informational"),
                current=not bool(event.get("replayed")),
                historical=bool(event.get("replayed")),
            ).model_dump(mode="json")
            for event in events
        ]
        return {
            "schema_version": "boba_error_doctor_review_timeline_v1",
            "project_id": project_id,
            "entries": entries[:MAX_TIMELINE_ENTRIES],
        }

    def _signal_usage(self, project_id: str) -> BobaErrorDoctorReviewSignalUsageV1:
        def present(source_id: str) -> bool:
            return bool(self._source_payload(source_id, project_id))

        return BobaErrorDoctorReviewSignalUsageV1(
            canonical_observer_records=present("observer"),
            canonical_error_doctor_records=present("error_doctor"),
            canonical_root_cause_records=present("root_cause_analyzer"),
            canonical_repair_plan_records=present("repair_planner"),
            canonical_code_surgeon_records=present("code_surgeon"),
            canonical_tool_recovery_records=present("tool_recovery"),
            canonical_output_quality_records=present("output_quality_reviewer"),
            canonical_workflow_records=present("workflow_controller"),
            canonical_validator_records=present("validator_runner"),
            canonical_report_reader_records=present("report_reader"),
            canonical_artifact_records=present("artifact_inspector"),
            canonical_safety_records=present("safety_gate"),
            canonical_final_decision_records=present("final_decision_bus"),
            unavailable_signals=[
                source_id
                for source_id in build_fixed_error_source_registry()
                if not present(source_id)
            ],
            limitations=[
                "Signal usage records which canonical owners were read, not who "
                "decided anything.",
            ],
        )

    def build_error_doctor_review(self, project_id: str) -> dict[str, Any]:
        registry = self.build_error_doctor_review_registry(project_id)
        references = self.build_incident_references(project_id)
        items = [
            self._queue_item(project_id, reference, index)
            for index, reference in enumerate(references)
        ]
        items.sort(key=lambda item: (item.priority_tier, item.deterministic_sort_key))
        events = self.inspect_incident_events(project_id)
        notifications = [
            BobaErrorDoctorReviewNotificationV1(
                notification_id=_stable_id(
                    "error_doctor_notification", project_id, item.incident_id
                ),
                project_id=project_id,
                incident_id=item.incident_id,
                source_module_id="error_doctor",
                source_record_id=item.source_record_ids[0]
                if item.source_record_ids
                else "error_doctor",
                notification_type=(
                    "blocking"
                    if item.blocker_count
                    else "conflict"
                    if item.conflict_count
                    else "failed_recovery"
                    if item.failed_recovery_attempt_count
                    else "warning"
                ),
                severity="critical" if item.blocker_count else "warning",
                title=item.title,
                bounded_message=item.bounded_summary or item.priority_reason,
                requires_attention=True,
                human_action_required=item.human_action_required,
                current=item.current,
                limitations=[
                    "Acknowledging this notice does not resolve the incident.",
                ],
            )
            for item in items
            if item.blocker_count
            or item.conflict_count
            or item.failed_recovery_attempt_count
            or item.warning_count
        ][:64]
        summary = BobaErrorDoctorReviewSummaryV1(
            total_incident_count=len(items),
            current_incident_count=sum(1 for item in items if item.current),
            stale_incident_count=sum(1 for item in items if item.stale),
            historical_incident_count=sum(1 for item in items if item.historical),
            unresolved_incident_count=sum(1 for item in items if not item.resolved),
            recovered_incident_count=sum(1 for item in items if item.recovered),
            resolved_incident_count=sum(1 for item in items if item.resolved),
            recurring_incident_count=sum(1 for item in items if item.recurring),
            critical_incident_count=sum(
                1
                for item in items
                if item.original_severity in {"critical", "blocker"}
            ),
            incidents_missing_diagnosis_count=sum(
                1 for item in items if item.priority_tier == 50
            ),
            incidents_missing_root_cause_count=sum(
                1 for item in items if item.root_cause_status == "unavailable"
            ),
            incidents_with_repair_plan_count=sum(
                1 for item in items if item.repair_plan_status != "unavailable"
            ),
            incidents_with_failed_recovery_count=sum(
                1 for item in items if item.failed_recovery_attempt_count > 0
            ),
            incidents_requiring_human_review_count=sum(
                1 for item in items if item.human_action_required
            ),
            missing_evidence_count=sum(item.missing_evidence_count for item in items),
            conflict_count=sum(item.conflict_count for item in items),
            safest_next_review_action=(
                "Review the highest-priority incident and its canonical evidence."
                if items
                else "No incident review work is outstanding."
            ),
            required_human_actions=[
                f"{item.incident_id}: {item.priority_reason}"
                for item in items
                if item.human_action_required
            ][:24],
            limitations=[
                "Counts describe projected canonical records, not panel decisions.",
                "Recovered counts are not resolved counts.",
            ],
        )
        result = BobaErrorDoctorReviewSetV1(
            project_id=project_id,
            source_id=_safe_text(
                self._source_payload("error_doctor", project_id).get("source_id"), 512
            ),
            registry_snapshots=[
                BobaErrorDoctorRegistrySnapshotV1.model_validate(
                    registry["registry_snapshot"]
                )
            ],
            incident_references=references,
            incident_queue_items=items,
            events=[
                BobaErrorDoctorReviewEventV1.model_validate(item)
                for item in events["events"]
            ],
            notifications=notifications,
            review_summary=summary,
            signal_usage=self._signal_usage(project_id),
            limitations=[
                "Error Doctor Panel V1 is a read-only incident projection, an "
                "evidence workspace, a comparison surface and a canonical routing "
                "layer. It does not detect errors, create incidents, diagnose, "
                "determine root causes, create repair plans or execute anything.",
                "A hypothesis is never presented as a confirmed fact.",
                "Owner-reported recovery success is not independent verification, "
                "and recovered is not resolved.",
                "Repair, recovery, checkpoint and workflow actions are unavailable "
                "in V1.",
            ],
        )
        self.store.save_boba_error_doctor_review(project_id, result.model_dump(mode="json"))
        return result.model_dump(mode="json")

    def load_error_doctor_review(self, project_id: str) -> dict[str, Any] | None:
        _safe_id(project_id, "project id")
        return self.store.load_boba_error_doctor_review(project_id)

    def export_error_doctor_review(
        self, project_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "boba_error_doctor_review_export_v1",
            "project_id": project_id,
            "exported_at": now_iso(),
            "queue": self.build_incident_queue(project_id, limit=MAX_QUEUE_PAGE_SIZE),
            "timeline": self.inspect_incident_timeline(project_id, limit=50),
            "privacy": {
                "private_paths_excluded": True,
                "sensitive_values_excluded": True,
                "raw_logs_excluded": True,
                "raw_stack_traces_excluded": True,
                "raw_patches_excluded": True,
                "source_code_excluded": True,
                "raw_media_excluded": True,
                "source_records_duplicated": False,
                "diagnosis_text_rewritten": False,
                "source_media_modified": False,
                "accepted_output_modified": False,
                "code_modified": False,
                "repair_executed": False,
                "recovery_executed": False,
                "upload_used": False,
                "publication_used": False,
            },
        }
        if session_id:
            payload["session"] = self.get_error_doctor_review_session(
                project_id, session_id
            ).model_dump(mode="json")
        return _as_mapping(_safe_payload(payload))

    def reset_error_doctor_review_metadata(
        self, project_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        if session_id:
            _safe_id(session_id, "error doctor review session id")
            removed = self.store.delete_boba_error_doctor_review_session(
                project_id, session_id
            )
            return {
                "schema_version": "boba_error_doctor_review_reset_v1",
                "project_id": project_id,
                "session_removed": removed,
                "incident_records_preserved": True,
                "diagnosis_records_preserved": True,
                "root_cause_records_preserved": True,
                "repair_plan_records_preserved": True,
                "recovery_history_preserved": True,
                "validator_history_preserved": True,
                "artifact_history_preserved": True,
                "workflow_history_preserved": True,
                "review_ui_history_preserved": True,
                "action_receipt_history_preserved": True,
            }
        return self.store.reset_boba_error_doctor_review_metadata(project_id)

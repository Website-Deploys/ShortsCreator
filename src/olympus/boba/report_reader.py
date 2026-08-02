"""Read-only, source-authority-preserving interpretation of BOBA reports.

Report Reader deliberately parses only source-declared project-scoped report
artifacts.  It persists bounded interpretations and references, never report
bodies, and never grants workflow, quality, safety, approval, or execution
authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore


BobaReportTypeV1 = Literal[
    "rights_permission",
    "observer_health",
    "error_diagnosis",
    "root_cause_analysis",
    "repair_plan",
    "code_surgeon",
    "tool_recovery",
    "output_quality",
    "autopilot",
    "safety_gate",
    "integration_transaction",
    "workflow_controller",
    "validator_runner",
    "rendering_manifest",
    "checkpoint_integrity",
    "technical_validation",
    "artifact_manifest",
    "content_understanding",
    "clip_selection",
    "creative_direction",
    "experiment",
    "performance_feedback",
    "unknown",
]
BobaReportFormatV1 = Literal[
    "json",
    "jsonl",
    "markdown",
    "plain_text",
    "unsupported",
    "unknown",
]
BobaReportAvailabilityV1 = Literal[
    "available",
    "unavailable",
    "future",
    "unknown",
]
BobaReportReadingModeV1 = Literal[
    "current_project_review",
    "historical_review",
    "recovery_review",
    "validation_review",
    "quality_review",
    "safety_review",
    "workflow_review",
    "integration_review",
    "code_repair_review",
    "comparison_review",
    "unknown",
]
BobaReportAuthorityDomainV1 = Literal[
    "rights",
    "observation",
    "diagnosis",
    "root_cause",
    "repair_planning",
    "code_repair",
    "tool_recovery",
    "technical_validation",
    "output_quality",
    "safety",
    "integration",
    "workflow",
    "content_analysis",
    "creative_planning",
    "performance",
    "informational",
    "unknown",
]
BobaReportReadStatusV1 = Literal[
    "created",
    "validating",
    "ready",
    "reading",
    "completed",
    "completed_with_limitations",
    "incomplete",
    "blocked",
    "unsupported",
    "malformed",
    "cancelled",
    "failed",
    "unknown",
]
BobaReportSectionTypeV1 = Literal[
    "identity",
    "status",
    "decision",
    "findings",
    "evidence",
    "incidents",
    "events",
    "warnings",
    "limitations",
    "handoffs",
    "summary",
    "metrics",
    "chronology",
    "unknown",
]
BobaReportTimestampPrecisionV1 = Literal[
    "exact",
    "second",
    "minute",
    "date",
    "sequence_only",
    "unknown",
]
BobaReportContradictionTypeV1 = Literal[
    "status_conflict",
    "decision_conflict",
    "artifact_digest_conflict",
    "project_identity_conflict",
    "workflow_identity_conflict",
    "timestamp_conflict",
    "validation_conflict",
    "rights_conflict",
    "safety_conflict",
    "quality_conflict",
    "lifecycle_conflict",
    "evidence_conflict",
    "unknown",
]
BobaReportCoverageStatusV1 = Literal[
    "complete",
    "complete_with_limitations",
    "incomplete",
    "blocked",
    "unsupported",
    "unknown",
]
BobaReportQuestionTypeV1 = Literal[
    "missing_evidence",
    "unsupported_schema",
    "stale_report",
    "conflicting_status",
    "conflicting_decision",
    "unclear_identity",
    "unclear_chronology",
    "human_judgment",
    "source_module_clarification",
    "unknown",
]
BobaReportIncidentTypeV1 = Literal[
    "unknown_source",
    "unsupported_format",
    "unsupported_schema",
    "digest_mismatch",
    "project_mismatch",
    "source_mismatch",
    "stale_required_report",
    "malformed_report",
    "duplicate_json_key",
    "oversized_report",
    "excessive_nesting",
    "excessive_record_count",
    "truncated_report",
    "private_path_detected",
    "secret_detected",
    "contradiction_detected",
    "missing_required_evidence",
    "unsafe_reference",
    "symlink_escape",
    "uncertain_state",
    "unknown",
]
BobaReportEventTypeV1 = Literal[
    "request_created",
    "reference_validated",
    "report_read_started",
    "report_read_completed",
    "report_stale",
    "report_unsupported",
    "report_malformed",
    "finding_extracted",
    "contradiction_detected",
    "chronology_created",
    "bundle_created",
    "evidence_missing",
    "reading_completed",
    "reading_incomplete",
    "reading_blocked",
    "unknown",
]
BobaReportHandoffTargetV1 = Literal[
    "validator_runner",
    "workflow_controller",
    "output_quality_reviewer",
    "autopilot_controller",
    "safety_gate",
    "rights_permission_gate",
    "observer",
    "error_doctor",
    "root_cause_analyzer",
    "repair_planner",
    "code_surgeon",
    "tool_recovery_brain",
    "integration_layer",
    "checkpoint_recovery_manager",
    "final_decision_bus",
    "live_companion",
    "human_operator",
    "unknown",
]

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,179}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_PRIVATE_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:\\[^\s\"']+")
_PRIVATE_POSIX_PATH = re.compile(r"(?<![\w/])/(?:home|users|var|tmp)/[^\s\"']+")
_SECRET_KEY = re.compile(
    r"(?i)(?:api[_-]?key|authorization|credential|password|secret|token|cookie)"
)
_MAX_REPORTS = 64
_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_MAX_REPORT_BYTES = 4 * 1024 * 1024
_MAX_RECORDS = 10_000
_MAX_DEPTH = 32
_MAX_ENTRIES = 10_000
_MAX_STRING = 64 * 1024
_MAX_FINDINGS = 2_000
_MAX_CONTRADICTIONS = 500
_MAX_CHRONOLOGY = 5_000
_MAX_QUESTIONS = 100


class DuplicateJsonKeyError(ValueError):
    """Raised when strict JSON sees a repeated object key."""


class UnsupportedReportError(ValueError):
    """Raised for a fixed source or format unavailable in V1."""


class UnsafeReportReferenceError(ValueError):
    """Raised when a reference leaves its exact registered project scope."""


class MalformedReportError(ValueError):
    """Raised for malformed, secret-bearing, or over-limit report content."""


def _bounded_text(value: object, *, maximum: int = 800) -> str:
    return str(value or "").strip().replace("\x00", " ")[:maximum]


def _unique_texts(value: object, *, limit: int = 64, maximum: int = 600) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw in value:
        text = _bounded_text(raw, maximum=maximum)
        if text and text not in seen:
            seen.add(text)
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return list(value)
    return []


def _digest(value: object) -> str:
    normalized = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    return f"{prefix}_{_digest([str(part) for part in parts])[:24]}"


def _path_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_time(value: object) -> datetime | None:
    text = _bounded_text(value, maximum=100)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _timestamp_precision(value: object) -> BobaReportTimestampPrecisionV1:
    text = _bounded_text(value, maximum=100)
    if not text:
        return "unknown"
    if "T" in text or " " in text:
        return "exact"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return "date"
    return "unknown"


def _validate_identifier(value: str) -> str:
    normalized = value.strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError("Report Reader identifiers use bounded safe characters only.")
    return normalized


def _validate_digest(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized and not _SHA256.fullmatch(normalized):
        raise ValueError("Expected report digests must be lowercase SHA-256 values.")
    return normalized


def _validate_storage_reference(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        raise ValueError("A project-scoped report reference is required.")
    if _URL.match(normalized):
        raise ValueError("External report URLs are unavailable.")
    if normalized.startswith("//") or _WINDOWS_ABSOLUTE.match(normalized):
        raise ValueError("Absolute and UNC report references are unavailable.")
    if normalized.startswith("/"):
        raise ValueError("Absolute report references are unavailable.")
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Traversal and malformed report references are unavailable.")
    return path.as_posix()


def _safe_text(value: object, *, maximum: int = 1_000) -> str:
    text = _bounded_text(value, maximum=maximum)
    text = _PRIVATE_WINDOWS_PATH.sub("[private-path-redacted]", text)
    return _PRIVATE_POSIX_PATH.sub("[private-path-redacted]", text)


def sanitize_report_export(value: Any) -> Any:
    """Return bounded export-safe metadata without raw reports or secrets."""

    sensitive_keys = {
        "raw_body",
        "raw_report",
        "content",
        "exact_local_target",
        "path",
        "stdout",
        "stderr",
        "traceback",
        "token",
        "secret",
        "password",
        "credential",
        "authorization",
        "cookie",
    }
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:512]:
            key = _bounded_text(raw_key, maximum=160)
            if not key:
                continue
            safe_signal_key = key.casefold() in {
                "quality_authorization_used",
                "safety_authorization_used",
            }
            if key.casefold() in sensitive_keys or (
                _SECRET_KEY.search(key) and not safe_signal_key
            ):
                safe[key] = "[redacted]"
            else:
                safe[key] = sanitize_report_export(raw_value)
        return safe
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [sanitize_report_export(item) for item in list(value)[:2_048]]
    if isinstance(value, str):
        return _safe_text(value, maximum=4_000)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _safe_text(value, maximum=900)


def _sanitize_report_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_report_export(value)
    if not isinstance(sanitized, dict):
        raise ValidationError("Report Reader export sanitizer returned an invalid mapping.")
    return {str(key): item for key, item in sanitized.items()}


class BobaReportRegistrySnapshotV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = Field(default="1", min_length=1, max_length=80)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    source_descriptor_ids: list[str] = Field(default_factory=list, max_length=128)
    producer_module_ids: list[str] = Field(default_factory=list, max_length=128)
    available_report_types: list[BobaReportTypeV1] = Field(default_factory=list)
    unavailable_report_types: list[BobaReportTypeV1] = Field(default_factory=list)
    future_report_types: list[BobaReportTypeV1] = Field(default_factory=list)
    registry_digest: str = Field(min_length=64, max_length=64)
    immutable: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    _digest_field = field_validator("registry_digest")(_validate_digest)


class BobaReportSourceDescriptorV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_descriptor_id: str = Field(min_length=1, max_length=180)
    producer_module_id: str = Field(min_length=1, max_length=160)
    report_type: BobaReportTypeV1
    display_name: str = Field(min_length=1, max_length=240)
    schema_id: str = Field(min_length=1, max_length=180)
    supported_schema_versions: list[str] = Field(default_factory=list, max_length=32)
    parser_id: str = Field(min_length=1, max_length=120)
    expected_format: BobaReportFormatV1
    authority_domain: BobaReportAuthorityDomainV1
    expected_storage_scope: str = Field(min_length=1, max_length=240)
    contains_decision: bool = False
    contains_events: bool = False
    contains_evidence: bool = False
    current_state_capable: bool = False
    historical_capable: bool = True
    rights_sensitive: bool = False
    safety_sensitive: bool = False
    quality_sensitive: bool = False
    workflow_sensitive: bool = False
    availability: BobaReportAvailabilityV1 = "available"
    maximum_bytes: int = Field(default=_MAX_REPORT_BYTES, ge=1_024, le=_MAX_REPORT_BYTES)
    maximum_records: int = Field(default=_MAX_RECORDS, ge=1, le=_MAX_RECORDS)
    maximum_depth: int = Field(default=_MAX_DEPTH, ge=1, le=_MAX_DEPTH)
    maximum_string_length: int = Field(default=_MAX_STRING, ge=128, le=_MAX_STRING)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("source_descriptor_id", "producer_module_id", "parser_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _validate_identifier(value)

    @model_validator(mode="after")
    def validate_descriptor(self) -> BobaReportSourceDescriptorV1:
        if self.availability == "available" and self.expected_format in {
            "unsupported",
            "unknown",
        }:
            raise ValueError("Available report sources require a fixed supported format.")
        return self


class BobaReportReferenceV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_reference_id: str = Field(min_length=1, max_length=180)
    source_descriptor_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    workflow_run_id: str = Field(default="", max_length=180)
    stage_instance_id: str = Field(default="", max_length=180)
    producer_module_id: str = Field(min_length=1, max_length=160)
    producer_record_id: str = Field(default="", max_length=180)
    report_type: BobaReportTypeV1
    schema_id: str = Field(min_length=1, max_length=180)
    schema_version: str = Field(default="1", min_length=1, max_length=80)
    expected_digest: str = Field(default="", max_length=64)
    sanitized_storage_reference: str = Field(min_length=1, max_length=500)
    format: BobaReportFormatV1
    immutable: bool = True
    historical: bool = False
    required: bool = True
    rights_relevant: bool = False
    safety_relevant: bool = False
    quality_relevant: bool = False
    workflow_relevant: bool = False
    created_at: str = Field(default_factory=now_iso, max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=64)

    _reference_field = field_validator("sanitized_storage_reference")(_validate_storage_reference)
    _digest_field = field_validator("expected_digest")(_validate_digest)

    @field_validator("report_reference_id", "source_descriptor_id", "producer_module_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _validate_identifier(value)


class BobaReportReadRequestV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    read_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    workflow_run_id: str = Field(default="", max_length=180)
    requested_at: str = Field(default_factory=now_iso, max_length=80)
    requested_by_module: str = Field(min_length=1, max_length=160)
    reading_mode: BobaReportReadingModeV1 = "unknown"
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    report_reference_ids: list[str] = Field(min_length=1, max_length=_MAX_REPORTS)
    current_project_snapshot_digest: str = Field(default="", max_length=64)
    maximum_total_bytes: int = Field(default=_MAX_TOTAL_BYTES, ge=1_024, le=_MAX_TOTAL_BYTES)
    maximum_total_records: int = Field(default=_MAX_RECORDS, ge=1, le=_MAX_RECORDS)
    include_chronology: bool = True
    include_contradictions: bool = True
    include_easy_summary: bool = True
    include_open_questions: bool = True
    request_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=180)
    expires_at: str = Field(
        default_factory=lambda: (datetime.now(UTC) + timedelta(days=1)).isoformat(), max_length=80
    )
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    _digest_fields = field_validator("current_project_snapshot_digest", "request_digest")(
        _validate_digest
    )


class BobaReportReadRunV1(BobaContract):
    read_run_id: str = Field(min_length=1, max_length=180)
    read_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str = Field(default="", max_length=180)
    correlation_id: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    started_at: str | None = Field(default=None, max_length=80)
    completed_at: str | None = Field(default=None, max_length=80)
    status: BobaReportReadStatusV1 = "created"
    report_document_ids: list[str] = Field(default_factory=list, max_length=_MAX_REPORTS)
    failed_reference_ids: list[str] = Field(default_factory=list, max_length=_MAX_REPORTS)
    unsupported_reference_ids: list[str] = Field(default_factory=list, max_length=_MAX_REPORTS)
    stale_reference_ids: list[str] = Field(default_factory=list, max_length=_MAX_REPORTS)
    contradiction_ids: list[str] = Field(default_factory=list, max_length=_MAX_CONTRADICTIONS)
    chronology_entry_ids: list[str] = Field(default_factory=list, max_length=_MAX_CHRONOLOGY)
    coverage_id: str = Field(default="", max_length=180)
    bundle_ids: list[str] = Field(default_factory=list, max_length=128)
    event_ids: list[str] = Field(default_factory=list, max_length=2_048)
    idempotency_key: str = Field(min_length=1, max_length=180)
    reused_existing_result: bool = False
    stop_reason: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaReportDocumentV1(BobaContract):
    report_document_id: str = Field(min_length=1, max_length=180)
    report_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str = Field(default="", max_length=180)
    producer_module_id: str = Field(min_length=1, max_length=160)
    producer_record_id: str = Field(default="", max_length=180)
    report_type: BobaReportTypeV1
    schema_id: str = Field(min_length=1, max_length=180)
    schema_version: str = Field(min_length=1, max_length=80)
    parser_id: str = Field(min_length=1, max_length=120)
    format: BobaReportFormatV1
    content_digest: str = Field(min_length=64, max_length=64)
    expected_digest_match: bool = True
    project_identity_match: bool = True
    source_identity_match: bool = True
    schema_supported: bool = True
    current_project_snapshot_match: bool = False
    historical: bool = False
    stale: bool = False
    malformed: bool = False
    truncated: bool = False
    source_decision_ids: list[str] = Field(default_factory=list, max_length=256)
    section_ids: list[str] = Field(default_factory=list, max_length=256)
    finding_ids: list[str] = Field(default_factory=list, max_length=_MAX_FINDINGS)
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=_MAX_FINDINGS)
    chronology_entry_ids: list[str] = Field(default_factory=list, max_length=_MAX_CHRONOLOGY)
    warning_count: int = Field(default=0, ge=0)
    limitation_count: int = Field(default=0, ge=0)
    read_status: BobaReportReadStatusV1 = "completed"
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    _digest_field = field_validator("content_digest")(_validate_digest)


class BobaReportSectionV1(BobaContract):
    report_section_id: str = Field(min_length=1, max_length=180)
    report_document_id: str = Field(min_length=1, max_length=180)
    section_type: BobaReportSectionTypeV1
    source_field_path: str = Field(min_length=1, max_length=360)
    title: str = Field(min_length=1, max_length=240)
    bounded_text: str = Field(default="", max_length=4_000)
    item_count: int = Field(default=0, ge=0, le=_MAX_ENTRIES)
    source_owned: bool = True
    decision_bearing: bool = False
    evidence_bearing: bool = False
    warning_bearing: bool = False
    limitation_bearing: bool = False
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaReportFindingV1(BobaContract):
    finding_id: str = Field(min_length=1, max_length=180)
    report_document_id: str = Field(min_length=1, max_length=180)
    producer_module_id: str = Field(min_length=1, max_length=160)
    authority_domain: BobaReportAuthorityDomainV1
    finding_type: str = Field(min_length=1, max_length=120)
    severity: Literal["info", "low", "medium", "high", "critical", "unknown"] = "unknown"
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(min_length=1, max_length=2_000)
    source_field_path: str = Field(min_length=1, max_length=360)
    source_status: str = Field(default="", max_length=180)
    source_decision: str = Field(default="", max_length=180)
    confirmed_fact: str = Field(default="", max_length=1_200)
    source_assessment: str = Field(default="", max_length=1_200)
    reader_interpretation: str = Field(default="", max_length=1_200)
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=128)
    related_artifact_ids: list[str] = Field(default_factory=list, max_length=128)
    related_clip_ids: list[str] = Field(default_factory=list, max_length=128)
    related_output_ids: list[str] = Field(default_factory=list, max_length=128)
    occurred_at: str = Field(default="", max_length=80)
    timestamp_precision: BobaReportTimestampPrecisionV1 = "unknown"
    current: bool = False
    stale: bool = False
    requires_human_interpretation: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaReportEvidenceReferenceV1(BobaContract):
    evidence_reference_id: str = Field(min_length=1, max_length=180)
    report_document_id: str = Field(min_length=1, max_length=180)
    source_module_id: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(default="", max_length=180)
    source_field_path: str = Field(min_length=1, max_length=360)
    artifact_id: str = Field(default="", max_length=180)
    artifact_digest: str = Field(default="", max_length=64)
    validator_id: str = Field(default="", max_length=180)
    validation_run_id: str = Field(default="", max_length=180)
    finding_id: str = Field(default="", max_length=180)
    evidence_type: str = Field(default="source_reference", max_length=120)
    bounded_summary: str = Field(default="", max_length=1_200)
    current: bool = False
    stale: bool = False
    available: bool = True
    verifiable: bool = False
    reliability: Literal["source_declared", "verified_digest", "unverified", "unknown"] = (
        "source_declared"
    )
    supports: Literal[
        "source_fact",
        "source_assessment",
        "decision",
        "contradiction",
        "chronology",
        "limitation",
        "none",
        "unknown",
    ] = "unknown"
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)

    _digest_field = field_validator("artifact_digest")(_validate_digest)


class BobaReportStatusInterpretationV1(BobaContract):
    status_interpretation_id: str = Field(min_length=1, max_length=180)
    report_document_id: str = Field(min_length=1, max_length=180)
    producer_module_id: str = Field(min_length=1, max_length=160)
    authority_domain: BobaReportAuthorityDomainV1
    original_status: str = Field(default="", max_length=180)
    original_decision: str = Field(default="", max_length=180)
    normalized_display_category: str = Field(default="unknown", max_length=120)
    source_authority_preserved: Literal[True] = True
    permits_current_action: Literal[False] = False
    current_action_type: str = Field(default="", max_length=160)
    stale: bool = False
    expired: bool = False
    invalidated: bool = False
    human_review_required: bool = False
    blocking: bool = False
    bounded_explanation: str = Field(min_length=1, max_length=1_200)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaReportChronologyEntryV1(BobaContract):
    chronology_entry_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str = Field(default="", max_length=180)
    report_document_id: str = Field(min_length=1, max_length=180)
    producer_module_id: str = Field(min_length=1, max_length=160)
    source_event_id: str = Field(default="", max_length=180)
    event_type: str = Field(default="source_timestamp", max_length=160)
    occurred_at: str = Field(default="", max_length=80)
    timestamp_precision: BobaReportTimestampPrecisionV1 = "unknown"
    timestamp_source: str = Field(default="", max_length=240)
    sequence: int | None = Field(default=None, ge=0)
    confirmed_order: bool = False
    bounded_summary: str = Field(min_length=1, max_length=1_200)
    related_finding_ids: list[str] = Field(default_factory=list, max_length=128)
    related_evidence_ids: list[str] = Field(default_factory=list, max_length=128)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaReportContradictionV1(BobaContract):
    contradiction_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    report_document_ids: list[str] = Field(min_length=2, max_length=8)
    finding_ids: list[str] = Field(default_factory=list, max_length=16)
    authority_domains: list[BobaReportAuthorityDomainV1] = Field(default_factory=list, max_length=8)
    contradiction_type: BobaReportContradictionTypeV1
    severity: Literal["info", "low", "medium", "high", "critical", "unknown"] = "unknown"
    bounded_summary: str = Field(min_length=1, max_length=1_600)
    value_a: str = Field(default="", max_length=500)
    value_b: str = Field(default="", max_length=500)
    source_a_reference: str = Field(default="", max_length=360)
    source_b_reference: str = Field(default="", max_length=360)
    same_target: bool = False
    same_snapshot: bool = False
    same_artifact_digest: bool = False
    temporal_explanation_possible: bool = False
    resolved: Literal[False] = False
    resolution_source: str = Field(default="", max_length=360)
    requires_human_review: bool = True
    recommended_handoff: BobaReportHandoffTargetV1 = "human_operator"
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaReportCoverageV1(BobaContract):
    coverage_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    reading_mode: BobaReportReadingModeV1
    expected_report_types: list[BobaReportTypeV1] = Field(default_factory=list, max_length=64)
    available_report_types: list[BobaReportTypeV1] = Field(default_factory=list, max_length=64)
    missing_report_types: list[BobaReportTypeV1] = Field(default_factory=list, max_length=64)
    unreadable_report_types: list[BobaReportTypeV1] = Field(default_factory=list, max_length=64)
    stale_report_types: list[BobaReportTypeV1] = Field(default_factory=list, max_length=64)
    unsupported_report_types: list[BobaReportTypeV1] = Field(default_factory=list, max_length=64)
    expected_authority_domains: list[BobaReportAuthorityDomainV1] = Field(
        default_factory=list, max_length=64
    )
    covered_authority_domains: list[BobaReportAuthorityDomainV1] = Field(
        default_factory=list, max_length=64
    )
    missing_authority_domains: list[BobaReportAuthorityDomainV1] = Field(
        default_factory=list, max_length=64
    )
    required_evidence_ids: list[str] = Field(default_factory=list, max_length=256)
    available_evidence_ids: list[str] = Field(default_factory=list, max_length=256)
    missing_evidence_ids: list[str] = Field(default_factory=list, max_length=256)
    coverage_status: BobaReportCoverageStatusV1 = "unknown"
    complete_for_requested_purpose: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaReportBundleV1(BobaContract):
    report_bundle_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str = Field(default="", max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    reading_mode: BobaReportReadingModeV1
    purpose: str = Field(min_length=1, max_length=600)
    report_document_ids: list[str] = Field(default_factory=list, max_length=_MAX_REPORTS)
    finding_ids: list[str] = Field(default_factory=list, max_length=_MAX_FINDINGS)
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=_MAX_FINDINGS)
    chronology_entry_ids: list[str] = Field(default_factory=list, max_length=_MAX_CHRONOLOGY)
    contradiction_ids: list[str] = Field(default_factory=list, max_length=_MAX_CONTRADICTIONS)
    coverage_id: str = Field(default="", max_length=180)
    source_decisions: list[str] = Field(default_factory=list, max_length=256)
    confirmed_facts: list[str] = Field(default_factory=list, max_length=256)
    source_assessments: list[str] = Field(default_factory=list, max_length=256)
    reader_interpretations: list[str] = Field(default_factory=list, max_length=256)
    blocking_findings: list[str] = Field(default_factory=list, max_length=256)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=_MAX_QUESTIONS)
    easy_summary: str = Field(default="", max_length=3_000)
    technical_summary: str = Field(default="", max_length=5_000)
    bundle_digest: str = Field(min_length=64, max_length=64)
    current: bool = False
    suitable_for_current_action: Literal[False] = False
    current_action_type: str = Field(default="", max_length=160)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)

    _digest_field = field_validator("bundle_digest")(_validate_digest)


class BobaReportOpenQuestionV1(BobaContract):
    open_question_id: str = Field(min_length=1, max_length=180)
    report_bundle_id: str = Field(default="", max_length=180)
    question_type: BobaReportQuestionTypeV1
    priority: int = Field(default=50, ge=0, le=100)
    bounded_question: str = Field(min_length=1, max_length=1_200)
    reason: str = Field(min_length=1, max_length=1_200)
    missing_report_types: list[BobaReportTypeV1] = Field(default_factory=list, max_length=64)
    missing_evidence_ids: list[str] = Field(default_factory=list, max_length=128)
    conflicting_finding_ids: list[str] = Field(default_factory=list, max_length=128)
    target_module_id: BobaReportHandoffTargetV1 = "human_operator"
    answer_required_before_action: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaReportIncidentV1(BobaContract):
    incident_id: str = Field(min_length=1, max_length=180)
    read_run_id: str = Field(default="", max_length=180)
    report_reference_id: str = Field(default="", max_length=180)
    incident_type: BobaReportIncidentTypeV1
    severity: Literal["info", "low", "medium", "high", "critical", "unknown"] = "unknown"
    title: str = Field(min_length=1, max_length=240)
    bounded_summary: str = Field(min_length=1, max_length=1_600)
    observed_at: str = Field(default_factory=now_iso, max_length=80)
    source_module_id: str = Field(default="", max_length=160)
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=128)
    repeated_fingerprint: str = Field(default="", max_length=180)
    occurrence_count: int = Field(default=1, ge=1)
    current_action_blocked: bool = False
    recommended_target_module: BobaReportHandoffTargetV1 = "human_operator"
    human_review_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaReportEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=180)
    read_run_id: str = Field(default="", max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    event_type: BobaReportEventTypeV1
    severity: Literal["info", "warning", "error", "critical", "unknown"] = "info"
    report_reference_id: str = Field(default="", max_length=180)
    report_document_id: str = Field(default="", max_length=180)
    technical_message: str = Field(min_length=1, max_length=1_200)
    easy_message: str = Field(min_length=1, max_length=1_200)
    confirmed_fact: str = Field(default="", max_length=1_200)
    assessment: str = Field(default="", max_length=1_200)
    progress_current: int | None = Field(default=None, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    progress_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    requires_attention: bool = False
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=128)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaReportHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=180)
    read_run_id: str = Field(default="", max_length=180)
    report_bundle_id: str = Field(default="", max_length=180)
    source_module_id: str = Field(default="report_reader", max_length=160)
    target_module_id: BobaReportHandoffTargetV1
    reason: str = Field(min_length=1, max_length=1_200)
    report_document_ids: list[str] = Field(default_factory=list, max_length=_MAX_REPORTS)
    finding_ids: list[str] = Field(default_factory=list, max_length=256)
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=256)
    contradiction_ids: list[str] = Field(default_factory=list, max_length=256)
    missing_evidence_ids: list[str] = Field(default_factory=list, max_length=256)
    satisfied_conditions: list[str] = Field(default_factory=list, max_length=64)
    blocking_conditions: list[str] = Field(default_factory=list, max_length=64)
    allowed_actions: list[str] = Field(default_factory=list, max_length=32)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False
    human_approval_required: bool = False
    priority: int = Field(default=50, ge=0, le=100)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaReportReaderSummaryV1(BobaContract):
    registry_snapshot_count: int = Field(default=0, ge=0)
    registered_source_count: int = Field(default=0, ge=0)
    available_source_count: int = Field(default=0, ge=0)
    unsupported_source_count: int = Field(default=0, ge=0)
    total_read_request_count: int = Field(default=0, ge=0)
    total_read_run_count: int = Field(default=0, ge=0)
    completed_read_count: int = Field(default=0, ge=0)
    incomplete_read_count: int = Field(default=0, ge=0)
    blocked_read_count: int = Field(default=0, ge=0)
    total_report_document_count: int = Field(default=0, ge=0)
    current_report_count: int = Field(default=0, ge=0)
    stale_report_count: int = Field(default=0, ge=0)
    malformed_report_count: int = Field(default=0, ge=0)
    unsupported_report_count: int = Field(default=0, ge=0)
    total_finding_count: int = Field(default=0, ge=0)
    blocking_finding_count: int = Field(default=0, ge=0)
    total_contradiction_count: int = Field(default=0, ge=0)
    unresolved_contradiction_count: int = Field(default=0, ge=0)
    total_bundle_count: int = Field(default=0, ge=0)
    total_open_question_count: int = Field(default=0, ge=0)
    highest_priority_incident: str = Field(default="", max_length=180)
    current_read_run_id: str = Field(default="", max_length=180)
    current_report_type: str = Field(default="", max_length=120)
    safest_next_action: str = Field(default="Inspect original source evidence.", max_length=600)
    required_human_actions: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaReportReaderSignalUsageV1(BobaContract):
    trusted_report_registry_used: bool = False
    project_identity_validation_used: bool = False
    source_identity_validation_used: bool = False
    schema_validation_used: bool = False
    digest_validation_used: bool = False
    json_parser_used: bool = False
    jsonl_parser_used: bool = False
    markdown_parser_used: bool = False
    plain_text_parser_used: bool = False
    chronology_analysis_used: bool = False
    contradiction_analysis_used: bool = False
    coverage_analysis_used: bool = False
    current_state_analysis_used: bool = False
    historical_analysis_used: bool = False
    integration_layer_used: bool = False
    validator_runner_evidence_used: bool = False
    workflow_controller_context_used: bool = False
    output_quality_context_used: bool = False
    safety_gate_context_used: bool = False
    autopilot_context_used: bool = False
    arbitrary_path_scanning_used: Literal[False] = False
    arbitrary_parser_loading_used: Literal[False] = False
    arbitrary_dynamic_import_used: Literal[False] = False
    arbitrary_function_invocation_used: Literal[False] = False
    command_execution_used: Literal[False] = False
    shell_execution_used: Literal[False] = False
    git_execution_used: Literal[False] = False
    ffmpeg_execution_used: Literal[False] = False
    report_modification_used: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_outputs_modified: Literal[False] = False
    checkpoint_restore_used: Literal[False] = False
    workflow_transition_used: Literal[False] = False
    quality_authorization_used: Literal[False] = False
    safety_authorization_used: Literal[False] = False
    approval_creation_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_access_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
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


class BobaReportReaderSetV1(BobaContract):
    schema_version: Literal["boba_report_reader_v1"] = "boba_report_reader_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    registry_snapshots: list[BobaReportRegistrySnapshotV1] = Field(
        default_factory=list, max_length=32
    )
    source_descriptors: list[BobaReportSourceDescriptorV1] = Field(
        default_factory=list, max_length=128
    )
    report_references: list[BobaReportReferenceV1] = Field(
        default_factory=list,
        max_length=2_048,
    )
    read_requests: list[BobaReportReadRequestV1] = Field(default_factory=list, max_length=512)
    read_runs: list[BobaReportReadRunV1] = Field(default_factory=list, max_length=512)
    report_documents: list[BobaReportDocumentV1] = Field(default_factory=list, max_length=2_048)
    report_sections: list[BobaReportSectionV1] = Field(default_factory=list, max_length=8_192)
    findings: list[BobaReportFindingV1] = Field(default_factory=list, max_length=_MAX_FINDINGS)
    evidence_references: list[BobaReportEvidenceReferenceV1] = Field(
        default_factory=list, max_length=_MAX_FINDINGS
    )
    status_interpretations: list[BobaReportStatusInterpretationV1] = Field(
        default_factory=list, max_length=2_048
    )
    chronology_entries: list[BobaReportChronologyEntryV1] = Field(
        default_factory=list, max_length=_MAX_CHRONOLOGY
    )
    contradictions: list[BobaReportContradictionV1] = Field(
        default_factory=list, max_length=_MAX_CONTRADICTIONS
    )
    coverage_records: list[BobaReportCoverageV1] = Field(default_factory=list, max_length=512)
    report_bundles: list[BobaReportBundleV1] = Field(default_factory=list, max_length=512)
    open_questions: list[BobaReportOpenQuestionV1] = Field(
        default_factory=list, max_length=_MAX_QUESTIONS
    )
    incidents: list[BobaReportIncidentV1] = Field(default_factory=list, max_length=2_048)
    events: list[BobaReportEventV1] = Field(default_factory=list, max_length=4_096)
    handoffs: list[BobaReportHandoffV1] = Field(default_factory=list, max_length=2_048)
    reader_summary: BobaReportReaderSummaryV1 = Field(default_factory=BobaReportReaderSummaryV1)
    signal_usage: BobaReportReaderSignalUsageV1 = Field(
        default_factory=BobaReportReaderSignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Report Reader is read-only and preserves source authority.",
            "A reader bundle is not an approval, quality decision, or workflow transition.",
        ],
        max_length=64,
    )


@dataclass(frozen=True)
class _SourceSpec:
    source_descriptor_id: str
    producer_module_id: str
    report_type: BobaReportTypeV1
    display_name: str
    schema_id: str
    parser_id: str
    expected_format: BobaReportFormatV1
    authority_domain: BobaReportAuthorityDomainV1
    expected_storage_scope: str
    availability: BobaReportAvailabilityV1 = "available"
    contains_decision: bool = False
    contains_events: bool = False
    contains_evidence: bool = False
    current_state_capable: bool = True
    historical_capable: bool = True
    rights_sensitive: bool = False
    safety_sensitive: bool = False
    quality_sensitive: bool = False
    workflow_sensitive: bool = False
    limitations: tuple[str, ...] = ()


_FIXED_PARSER_REGISTRY: dict[str, str] = {
    "typed_model_parser": "Typed BOBA model metadata parser",
    "strict_json_parser": "Strict bounded UTF-8 JSON parser",
    "strict_jsonl_parser": "Strict bounded UTF-8 JSONL parser",
    "bounded_markdown_parser": "Bounded inert Markdown text parser",
    "bounded_plain_text_parser": "Bounded inert plain-text parser",
}

_FIXED_SOURCE_SPECS: tuple[_SourceSpec, ...] = (
    _SourceSpec(
        "rights_permission_gate.index",
        "rights_permission_gate",
        "rights_permission",
        "Rights + Permission Gate",
        "boba_rights_permission_gate_v1",
        "typed_model_parser",
        "json",
        "rights",
        "rights_permission_gate/index.json",
        contains_decision=True,
        rights_sensitive=True,
    ),
    _SourceSpec(
        "observer.index",
        "observer",
        "observer_health",
        "Observer",
        "boba_observer_v1",
        "typed_model_parser",
        "json",
        "observation",
        "observer/index.json",
        contains_evidence=True,
    ),
    _SourceSpec(
        "error_doctor.index",
        "error_doctor",
        "error_diagnosis",
        "Error Doctor",
        "boba_error_doctor_v1",
        "typed_model_parser",
        "json",
        "diagnosis",
        "error_doctor/index.json",
        contains_decision=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "root_cause_analyzer.index",
        "root_cause_analyzer",
        "root_cause_analysis",
        "Root Cause Analyzer",
        "boba_root_cause_analyzer_v1",
        "typed_model_parser",
        "json",
        "root_cause",
        "root_cause_analyzer/index.json",
        contains_decision=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "repair_planner.index",
        "repair_planner",
        "repair_plan",
        "Repair Planner",
        "boba_repair_planner_v1",
        "typed_model_parser",
        "json",
        "repair_planning",
        "repair_planner/index.json",
        contains_decision=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "code_surgeon.index",
        "code_surgeon",
        "code_surgeon",
        "Code Surgeon",
        "boba_code_surgeon_v1",
        "typed_model_parser",
        "json",
        "code_repair",
        "code_surgeon/index.json",
        contains_decision=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "code_surgeon.run",
        "code_surgeon",
        "code_surgeon",
        "Code Surgeon Run",
        "boba_code_surgeon_run_v1",
        "typed_model_parser",
        "json",
        "code_repair",
        "code_surgeon/runs/*/index.json",
        contains_decision=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "tool_recovery.index",
        "tool_recovery_brain",
        "tool_recovery",
        "Tool Recovery Brain",
        "boba_tool_recovery_brain_v1",
        "typed_model_parser",
        "json",
        "tool_recovery",
        "tool_recovery/index.json",
        contains_decision=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "tool_recovery.run",
        "tool_recovery_brain",
        "tool_recovery",
        "Tool Recovery Run",
        "boba_tool_recovery_run_v1",
        "typed_model_parser",
        "json",
        "tool_recovery",
        "tool_recovery/runs/*/index.json",
        contains_decision=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "output_quality.index",
        "output_quality_reviewer",
        "output_quality",
        "Output Quality Reviewer",
        "boba_output_quality_reviewer_v1",
        "typed_model_parser",
        "json",
        "output_quality",
        "output_quality_reviewer/index.json",
        contains_decision=True,
        contains_evidence=True,
        quality_sensitive=True,
    ),
    _SourceSpec(
        "autopilot.index",
        "autopilot_controller",
        "autopilot",
        "Autopilot Controller",
        "boba_autopilot_controller_v1",
        "typed_model_parser",
        "json",
        "integration",
        "autopilot_controller/index.json",
        contains_decision=True,
        contains_evidence=True,
        workflow_sensitive=True,
    ),
    _SourceSpec(
        "autopilot.run",
        "autopilot_controller",
        "autopilot",
        "Autopilot Run",
        "boba_autopilot_run_v1",
        "typed_model_parser",
        "json",
        "integration",
        "autopilot_controller/runs/*/index.json",
        contains_decision=True,
        contains_evidence=True,
        workflow_sensitive=True,
    ),
    _SourceSpec(
        "autopilot.events",
        "autopilot_controller",
        "autopilot",
        "Autopilot Events",
        "boba_autopilot_event_v1",
        "strict_jsonl_parser",
        "jsonl",
        "integration",
        "autopilot_controller/runs/*/events.jsonl",
        contains_events=True,
        historical_capable=True,
        workflow_sensitive=True,
    ),
    _SourceSpec(
        "safety_gate.index",
        "safety_gate",
        "safety_gate",
        "Safety Gate",
        "boba_safety_gate_v1",
        "typed_model_parser",
        "json",
        "safety",
        "safety_gate/index.json",
        contains_decision=True,
        contains_evidence=True,
        safety_sensitive=True,
    ),
    _SourceSpec(
        "integration_layer.index",
        "integration_layer",
        "integration_transaction",
        "Integration Layer",
        "boba_integration_layer_v1",
        "typed_model_parser",
        "json",
        "integration",
        "integration_layer/index.json",
        contains_events=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "integration_layer.events",
        "integration_layer",
        "integration_transaction",
        "Integration Events",
        "boba_integration_event_v1",
        "strict_jsonl_parser",
        "jsonl",
        "integration",
        "integration_layer/events.jsonl",
        contains_events=True,
    ),
    _SourceSpec(
        "workflow_controller.index",
        "workflow_controller",
        "workflow_controller",
        "Workflow Controller",
        "boba_workflow_controller_v1",
        "typed_model_parser",
        "json",
        "workflow",
        "workflow_controller/index.json",
        contains_decision=True,
        contains_events=True,
        contains_evidence=True,
        workflow_sensitive=True,
    ),
    _SourceSpec(
        "workflow_controller.run",
        "workflow_controller",
        "workflow_controller",
        "Workflow Run",
        "boba_workflow_run_record_v1",
        "typed_model_parser",
        "json",
        "workflow",
        "workflow_controller/runs/*/index.json",
        contains_decision=True,
        contains_events=True,
        contains_evidence=True,
        workflow_sensitive=True,
    ),
    _SourceSpec(
        "workflow_controller.events",
        "workflow_controller",
        "workflow_controller",
        "Workflow Events",
        "boba_workflow_event_v1",
        "strict_jsonl_parser",
        "jsonl",
        "workflow",
        "workflow_controller/runs/*/events.jsonl",
        contains_events=True,
        workflow_sensitive=True,
    ),
    _SourceSpec(
        "validator_runner.index",
        "validator_runner",
        "validator_runner",
        "Validator Runner",
        "boba_validator_runner_v1",
        "typed_model_parser",
        "json",
        "technical_validation",
        "validator_runner/index.json",
        contains_decision=True,
        contains_events=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "validator_runner.run",
        "validator_runner",
        "technical_validation",
        "Validator Runner Run",
        "boba_validation_run_record_v1",
        "typed_model_parser",
        "json",
        "technical_validation",
        "validator_runner/runs/*/index.json",
        contains_decision=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "validator_runner.events",
        "validator_runner",
        "validator_runner",
        "Validator Runner Events",
        "boba_validation_event_v1",
        "strict_jsonl_parser",
        "jsonl",
        "technical_validation",
        "validator_runner/runs/*/events.jsonl",
        contains_events=True,
        contains_evidence=True,
    ),
    _SourceSpec(
        "rendering_manifest.future",
        "olympus_rendering",
        "rendering_manifest",
        "Rendering Manifest",
        "render_manifest_v2",
        "strict_json_parser",
        "json",
        "informational",
        "rendering manifest scope is not registered by Report Reader V1",
        "unavailable",
        limitations=(
            "Rendering manifests are not registered for direct reading until "
            "their project scope is fixed.",
        ),
    ),
    _SourceSpec(
        "checkpoint_integrity.future",
        "checkpoint_recovery_manager",
        "checkpoint_integrity",
        "Checkpoint Integrity",
        "checkpoint_integrity_v1",
        "strict_json_parser",
        "json",
        "technical_validation",
        "checkpoint scope is future-gated",
        "future",
        limitations=("Checkpoint report parsing remains future-gated in V1.",),
    ),
)


def build_fixed_report_parser_registry() -> dict[str, str]:
    """Return the source-declared parser map; request data never changes it."""

    return dict(_FIXED_PARSER_REGISTRY)


def build_fixed_report_source_registry() -> tuple[
    BobaReportRegistrySnapshotV1,
    list[BobaReportSourceDescriptorV1],
]:
    """Build the deterministic fixed Report Reader source registry."""

    descriptors = [
        BobaReportSourceDescriptorV1(
            source_descriptor_id=spec.source_descriptor_id,
            producer_module_id=spec.producer_module_id,
            report_type=spec.report_type,
            display_name=spec.display_name,
            schema_id=spec.schema_id,
            supported_schema_versions=["1", spec.schema_id],
            parser_id=spec.parser_id,
            expected_format=spec.expected_format,
            authority_domain=spec.authority_domain,
            expected_storage_scope=spec.expected_storage_scope,
            contains_decision=spec.contains_decision,
            contains_events=spec.contains_events,
            contains_evidence=spec.contains_evidence,
            current_state_capable=spec.current_state_capable,
            historical_capable=spec.historical_capable,
            rights_sensitive=spec.rights_sensitive,
            safety_sensitive=spec.safety_sensitive,
            quality_sensitive=spec.quality_sensitive,
            workflow_sensitive=spec.workflow_sensitive,
            availability=spec.availability,
            limitations=list(spec.limitations),
        )
        for spec in _FIXED_SOURCE_SPECS
    ]
    if len({item.source_descriptor_id for item in descriptors}) != len(descriptors):
        raise ValidationError("Fixed Report Reader source IDs must be unique.")
    if len({item.parser_id for item in descriptors if item.availability == "available"}) > len(
        _FIXED_PARSER_REGISTRY
    ):
        raise ValidationError("Fixed Report Reader parser IDs are invalid.")
    payload = [item.model_dump(mode="json") for item in descriptors]
    registry_digest = _digest(payload)
    available = sorted(
        {item.report_type for item in descriptors if item.availability == "available"}
    )
    unavailable = sorted(
        {item.report_type for item in descriptors if item.availability == "unavailable"}
    )
    future = sorted({item.report_type for item in descriptors if item.availability == "future"})
    snapshot = BobaReportRegistrySnapshotV1(
        registry_snapshot_id=f"report_registry_{registry_digest[:24]}",
        source_descriptor_ids=[item.source_descriptor_id for item in descriptors],
        producer_module_ids=sorted({item.producer_module_id for item in descriptors}),
        available_report_types=available,
        unavailable_report_types=unavailable,
        future_report_types=future,
        registry_digest=registry_digest,
        warnings=["Availability reflects only source-declared local report producers."],
        limitations=["No report producer, parser, or storage scope is discovered dynamically."],
    )
    return snapshot, descriptors


def calculate_report_request_digest(value: Mapping[str, Any]) -> str:
    excluded = {"read_request_id", "requested_at", "warnings", "limitations"}
    normalized = {
        key: sanitize_report_export(item) for key, item in value.items() if key not in excluded
    }
    references = normalized.get("report_references")
    if isinstance(references, list):
        normalized["report_references"] = [
            {key: item for key, item in reference.items() if key not in {"created_at", "warnings"}}
            if isinstance(reference, Mapping)
            else reference
            for reference in references
        ]
    return _digest(normalized)


def calculate_report_bundle_digest(value: Mapping[str, Any]) -> str:
    excluded = {"report_bundle_id", "created_at", "warnings", "limitations"}
    return _digest(
        {key: sanitize_report_export(item) for key, item in value.items() if key not in excluded}
    )


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise DuplicateJsonKeyError(f"Duplicate JSON key: {key}")
        parsed[key] = value
    return parsed


def _reject_nonfinite(value: str) -> None:
    raise MalformedReportError(f"Non-finite JSON number: {value}")


def _validate_json_limits(
    value: Any,
    *,
    maximum_depth: int,
    maximum_entries: int,
    maximum_string_length: int,
    depth: int = 0,
) -> None:
    if depth > maximum_depth:
        raise MalformedReportError("Report JSON exceeds the registered nesting limit.")
    if isinstance(value, str):
        if len(value) > maximum_string_length:
            raise MalformedReportError("Report JSON contains an over-limit string.")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise MalformedReportError("Report JSON contains a non-finite number.")
    if isinstance(value, Mapping):
        if len(value) > maximum_entries:
            raise MalformedReportError("Report JSON object exceeds the registered entry limit.")
        for key, child in value.items():
            if len(str(key)) > maximum_string_length:
                raise MalformedReportError("Report JSON contains an over-limit key.")
            _validate_json_limits(
                child,
                maximum_depth=maximum_depth,
                maximum_entries=maximum_entries,
                maximum_string_length=maximum_string_length,
                depth=depth + 1,
            )
        return
    if isinstance(value, list):
        if len(value) > maximum_entries:
            raise MalformedReportError("Report JSON list exceeds the registered entry limit.")
        for child in value:
            _validate_json_limits(
                child,
                maximum_depth=maximum_depth,
                maximum_entries=maximum_entries,
                maximum_string_length=maximum_string_length,
                depth=depth + 1,
            )


def _contains_secret(value: Any, *, key: str = "") -> bool:
    if key and _SECRET_KEY.search(key):
        return value is not None and value != "" and value != [] and value != {}
    if isinstance(value, Mapping):
        return any(
            _contains_secret(child, key=str(child_key)) for child_key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret(child) for child in value)
    return False


def _contains_private_path(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_PRIVATE_WINDOWS_PATH.search(value) or _PRIVATE_POSIX_PATH.search(value))
    if isinstance(value, Mapping):
        return any(_contains_private_path(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_private_path(child) for child in value)
    return False


def _strict_json_parse(raw: bytes, descriptor: BobaReportSourceDescriptorV1) -> Any:
    if len(raw) > descriptor.maximum_bytes:
        raise MalformedReportError("Report exceeds the registered byte limit.")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise MalformedReportError("Report is not valid UTF-8.") from exc
    try:
        parsed = json.loads(text, object_pairs_hook=_json_pairs, parse_constant=_reject_nonfinite)
    except DuplicateJsonKeyError:
        raise
    except (json.JSONDecodeError, MalformedReportError) as exc:
        raise MalformedReportError(f"Malformed JSON report: {exc}") from exc
    _validate_json_limits(
        parsed,
        maximum_depth=descriptor.maximum_depth,
        maximum_entries=_MAX_ENTRIES,
        maximum_string_length=descriptor.maximum_string_length,
    )
    if _contains_secret(parsed):
        raise MalformedReportError("Report contains a secret-bearing field and was not persisted.")
    return parsed


def _strict_jsonl_parse(
    raw: bytes, descriptor: BobaReportSourceDescriptorV1
) -> list[dict[str, Any]]:
    if len(raw) > descriptor.maximum_bytes:
        raise MalformedReportError("Report exceeds the registered byte limit.")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise MalformedReportError("Report is not valid UTF-8.") from exc
    lines = text.splitlines()
    if len(lines) > descriptor.maximum_records:
        raise MalformedReportError("JSONL report exceeds the registered record limit.")
    parsed: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if len(line.encode("utf-8")) > descriptor.maximum_string_length:
            raise MalformedReportError("JSONL report contains an over-limit line.")
        item = _strict_json_parse(line.encode("utf-8"), descriptor)
        if not isinstance(item, Mapping):
            raise MalformedReportError(f"JSONL record {line_number} is not an object.")
        parsed.append({"_line_number": line_number, **dict(item)})
    return parsed


def _bounded_text_parse(raw: bytes, descriptor: BobaReportSourceDescriptorV1) -> str:
    if len(raw) > descriptor.maximum_bytes:
        raise MalformedReportError("Report exceeds the registered byte limit.")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise MalformedReportError("Report is not valid UTF-8.") from exc
    if _SECRET_KEY.search(text):
        raise MalformedReportError(
            "Text report contains a secret-bearing field and was not persisted."
        )
    return _safe_text(text, maximum=descriptor.maximum_bytes)


def _source_schema_version(payload: Any, fallback: str) -> str:
    mapped = _mapping(payload)
    return _bounded_text(mapped.get("schema_version") or fallback, maximum=80) or fallback


def _source_project_id(payload: Any) -> str:
    mapped = _mapping(payload)
    return _bounded_text(mapped.get("project_id"), maximum=128)


def _source_workflow_id(payload: Any) -> str:
    mapped = _mapping(payload)
    return _bounded_text(mapped.get("workflow_run_id"), maximum=180)


def _source_snapshot_digest(payload: Any) -> str:
    mapped = _mapping(payload)
    for key in ("project_snapshot_digest", "current_project_snapshot_digest"):
        value = _bounded_text(mapped.get(key), maximum=64).casefold()
        if _SHA256.fullmatch(value):
            return value
    return ""


def _source_confidence(payload: Any) -> float | None:
    value = _mapping(payload).get("confidence")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    confidence = float(value)
    return confidence if math.isfinite(confidence) and 0.0 <= confidence <= 1.0 else None


def _find_values(value: Any, *, path: str = "", limit: int = 2_000) -> list[tuple[str, str, Any]]:
    values: list[tuple[str, str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in list(value.items())[:_MAX_ENTRIES]:
            child_path = f"{path}.{key}" if path else str(key)
            values.append((child_path, str(key), child))
            if len(values) >= limit:
                return values
            values.extend(_find_values(child, path=child_path, limit=limit - len(values)))
            if len(values) >= limit:
                return values
    elif isinstance(value, list):
        for index, child in enumerate(value[:_MAX_ENTRIES]):
            child_path = f"{path}[{index}]"
            values.append((child_path, "", child))
            if len(values) >= limit:
                return values
            values.extend(_find_values(child, path=child_path, limit=limit - len(values)))
            if len(values) >= limit:
                return values
    return values


def _severity_for(value: object) -> Literal["info", "low", "medium", "high", "critical", "unknown"]:
    text = _bounded_text(value, maximum=120).casefold()
    if "critical" in text:
        return "critical"
    if any(word in text for word in ("blocked", "failed", "denied", "error", "invalid")):
        return "high"
    if any(word in text for word in ("warning", "stale", "incomplete", "review")):
        return "medium"
    if text:
        return "info"
    return "unknown"


def _expected_types(mode: BobaReportReadingModeV1) -> list[BobaReportTypeV1]:
    mapping: dict[BobaReportReadingModeV1, list[BobaReportTypeV1]] = {
        "recovery_review": [
            "observer_health",
            "error_diagnosis",
            "root_cause_analysis",
            "repair_plan",
            "tool_recovery",
            "validator_runner",
            "output_quality",
            "safety_gate",
            "workflow_controller",
        ],
        "validation_review": ["validator_runner"],
        "quality_review": ["validator_runner", "output_quality"],
        "safety_review": ["rights_permission", "safety_gate"],
        "workflow_review": ["workflow_controller"],
        "integration_review": ["integration_transaction"],
        "code_repair_review": ["code_surgeon", "validator_runner"],
        "comparison_review": [],
        "current_project_review": [],
        "historical_review": [],
        "unknown": [],
    }
    return mapping[mode]


class BobaReportReaderV1:
    """Read only fixed registered BOBA report sources and persist interpretations."""

    def __init__(self, store: BobaMemoryStore) -> None:
        self.store = store
        self.project_root = (store.root / "projects").resolve()

    def _reader(self, project_id: str, *, source_id: str | None = None) -> BobaReportReaderSetV1:
        existing = self.store.load_boba_report_reader(project_id)
        if existing is not None:
            return existing
        if not source_id:
            raise NotFoundError("BOBA Report Reader is unavailable for this project.")
        created = BobaReportReaderSetV1(project_id=project_id, source_id=source_id)
        self.store.save_boba_report_reader(created)
        return created

    def build_report_source_registry(
        self, project_id: str, *, source_id: str
    ) -> BobaReportRegistrySnapshotV1:
        reader = self._reader(project_id, source_id=source_id)
        snapshot, descriptors = build_fixed_report_source_registry()
        existing = next(
            (
                item
                for item in reader.registry_snapshots
                if item.registry_snapshot_id == snapshot.registry_snapshot_id
            ),
            None,
        )
        if existing is not None:
            return existing
        reader.registry_snapshots.append(snapshot)
        known = {item.source_descriptor_id for item in reader.source_descriptors}
        reader.source_descriptors.extend(
            item for item in descriptors if item.source_descriptor_id not in known
        )
        reader.signal_usage.trusted_report_registry_used = True
        self._refresh_summary(reader)
        self.store.save_boba_report_reader(reader)
        return snapshot

    def inspect_report_source_registry(
        self, project_id: str, *, source_id: str | None = None
    ) -> dict[str, Any]:
        reader = self._reader(project_id, source_id=source_id)
        if not reader.registry_snapshots:
            snapshot = self.build_report_source_registry(project_id, source_id=reader.source_id)
            reader = self._reader(project_id)
        else:
            snapshot = reader.registry_snapshots[-1]
        descriptors = [
            item
            for item in reader.source_descriptors
            if item.source_descriptor_id in snapshot.source_descriptor_ids
        ]
        return {
            "schema_version": "boba_report_reader_registry_inspection_v1",
            "project_id": project_id,
            "registry_snapshot": snapshot.model_dump(mode="json"),
            "sources": [
                item.model_dump(mode="json")
                for item in sorted(descriptors, key=lambda value: value.source_descriptor_id)
            ],
            "fixed_registry": True,
            "dynamic_parser_loading_used": False,
            "arbitrary_path_scanning_used": False,
            "network_used": False,
        }

    def create_report_read_request(
        self,
        project_id: str,
        *,
        source_id: str,
        requested_by_module: str,
        reading_mode: BobaReportReadingModeV1,
        report_references: Sequence[Mapping[str, Any]],
        workflow_run_id: str = "",
        current_project_snapshot_digest: str = "",
        maximum_total_bytes: int = _MAX_TOTAL_BYTES,
        maximum_total_records: int = _MAX_RECORDS,
        include_chronology: bool = True,
        include_contradictions: bool = True,
        include_easy_summary: bool = True,
        include_open_questions: bool = True,
        expires_in_seconds: int = 86_400,
    ) -> BobaReportReadRequestV1:
        if not report_references:
            raise ValidationError("At least one exact registered report reference is required.")
        if len(report_references) > _MAX_REPORTS:
            raise ValidationError("Report Reader requests support at most 64 references.")
        reader = self._reader(project_id, source_id=source_id)
        snapshot = self.build_report_source_registry(project_id, source_id=reader.source_id)
        reader = self._reader(project_id)
        descriptors = {item.source_descriptor_id: item for item in reader.source_descriptors}
        references = self._build_references(
            project_id,
            source_id=source_id,
            workflow_run_id=workflow_run_id,
            supplied=report_references,
            descriptors=descriptors,
        )
        reference_ids = [item.report_reference_id for item in references]
        request_payload = {
            "project_id": project_id,
            "source_id": source_id,
            "workflow_run_id": workflow_run_id,
            "requested_by_module": requested_by_module,
            "reading_mode": reading_mode,
            "registry_snapshot_id": snapshot.registry_snapshot_id,
            "report_references": [item.model_dump(mode="json") for item in references],
            "current_project_snapshot_digest": current_project_snapshot_digest,
            "maximum_total_bytes": min(maximum_total_bytes, _MAX_TOTAL_BYTES),
            "maximum_total_records": min(maximum_total_records, _MAX_RECORDS),
            "include_chronology": include_chronology,
            "include_contradictions": include_contradictions,
            "include_easy_summary": include_easy_summary,
            "include_open_questions": include_open_questions,
        }
        request_digest = calculate_report_request_digest(request_payload)
        request = BobaReportReadRequestV1(
            read_request_id=f"report_read_request_{request_digest[:24]}",
            project_id=project_id,
            source_id=source_id,
            workflow_run_id=workflow_run_id,
            requested_by_module=_validate_identifier(requested_by_module),
            reading_mode=reading_mode,
            registry_snapshot_id=snapshot.registry_snapshot_id,
            report_reference_ids=reference_ids,
            current_project_snapshot_digest=current_project_snapshot_digest,
            maximum_total_bytes=min(maximum_total_bytes, _MAX_TOTAL_BYTES),
            maximum_total_records=min(maximum_total_records, _MAX_RECORDS),
            include_chronology=include_chronology,
            include_contradictions=include_contradictions,
            include_easy_summary=include_easy_summary,
            include_open_questions=include_open_questions,
            request_digest=request_digest,
            idempotency_key=_stable_id(
                "report_read_idempotency", project_id, snapshot.registry_digest, request_digest
            ),
            expires_at=(
                datetime.now(UTC) + timedelta(seconds=max(60, min(expires_in_seconds, 604_800)))
            ).isoformat(),
        )
        existing = next(
            (
                item
                for item in reader.read_requests
                if item.read_request_id == request.read_request_id
            ),
            None,
        )
        if existing is not None:
            return existing
        known_reference_ids = {item.report_reference_id for item in reader.report_references}
        reader.report_references.extend(
            item for item in references if item.report_reference_id not in known_reference_ids
        )
        reader.read_requests.append(request)
        reader.signal_usage.project_identity_validation_used = True
        reader.signal_usage.source_identity_validation_used = True
        reader.signal_usage.schema_validation_used = True
        self._append_event(
            reader,
            read_run_id="",
            event_type="request_created",
            technical_message="A fixed Report Reader request was created without reading reports.",
            easy_message="BOBA is ready to inspect the selected registered reports.",
            confirmed_fact="No report body was read while the request was created.",
        )
        self._refresh_summary(reader)
        self.store.save_boba_report_reader(reader)
        return request

    def validate_report_references(self, project_id: str, read_request_id: str) -> dict[str, Any]:
        reader = self._reader(project_id)
        request = self._request(reader, read_request_id)
        if self._request_expired(request):
            raise ValidationError("The Report Reader request has expired.")
        references = self._references(reader, request)
        descriptors = self._descriptor_map(reader)
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        for reference in references:
            try:
                descriptor = self._descriptor_for_reference(descriptors, reference)
                if descriptor.availability != "available":
                    raise UnsupportedReportError(
                        "This fixed report source is unavailable or future-gated in V1."
                    )
                path = self._resolve_reference(reference, descriptor)
                digest = _path_digest(path)
                if reference.expected_digest and reference.expected_digest != digest:
                    raise UnsafeReportReferenceError(
                        "Report digest does not match the exact reference."
                    )
                results.append(
                    {
                        "report_reference_id": reference.report_reference_id,
                        "valid": True,
                        "content_digest": digest,
                        "format": descriptor.expected_format,
                        "availability": descriptor.availability,
                    }
                )
                self._append_event(
                    reader,
                    read_run_id="",
                    event_type="reference_validated",
                    report_reference_id=reference.report_reference_id,
                    technical_message=(
                        "Registered report reference, scope, and digest were validated."
                    ),
                    easy_message="BOBA confirmed this report is the exact selected local record.",
                    confirmed_fact=(
                        "The report reference remained inside the registered project scope."
                    ),
                )
            except (UnsafeReportReferenceError, UnsupportedReportError, OSError, ValueError) as exc:
                errors.append(f"{reference.report_reference_id}: {exc}")
                results.append(
                    {
                        "report_reference_id": reference.report_reference_id,
                        "valid": False,
                        "error": _safe_text(exc),
                    }
                )
        self.store.save_boba_report_reader(reader)
        return {
            "schema_version": "boba_report_reference_validation_v1",
            "project_id": project_id,
            "read_request_id": read_request_id,
            "valid": not errors,
            "results": results,
            "errors": errors,
            "read_bodies": False,
        }

    def read_registered_reports(self, project_id: str, read_request_id: str) -> dict[str, Any]:
        reader = self._reader(project_id)
        request = self._request(reader, read_request_id)
        validation = self.validate_report_references(project_id, read_request_id)
        if not validation["valid"]:
            raise ValidationError(
                "Report Reader cannot read invalid exact references.",
                details={"errors": validation["errors"]},
            )
        reader = self._reader(project_id)
        request = self._request(reader, read_request_id)
        existing = self._reusable_run(reader, request)
        if existing is not None:
            existing.reused_existing_result = True
            self.store.save_boba_report_reader(reader)
            return self.inspect_report_read_run(project_id, existing.read_run_id)
        run = BobaReportReadRunV1(
            read_run_id=f"report_read_run_{uuid4().hex}",
            read_request_id=request.read_request_id,
            project_id=project_id,
            workflow_run_id=request.workflow_run_id,
            correlation_id=_stable_id(
                "report_read_correlation", project_id, request.request_digest, now_iso()
            ),
            started_at=now_iso(),
            status="reading",
            idempotency_key=request.idempotency_key,
        )
        reader.read_runs.append(run)
        references = self._references(reader, request)
        descriptors = self._descriptor_map(reader)
        total_bytes = 0
        for index, reference in enumerate(references, start=1):
            self._append_event(
                reader,
                read_run_id=run.read_run_id,
                event_type="report_read_started",
                report_reference_id=reference.report_reference_id,
                technical_message="Reading one exact registered report with its fixed parser.",
                easy_message="BOBA is reading the selected report without changing it.",
                confirmed_fact="Only the registered report reference is being inspected.",
                progress_current=index - 1,
                progress_total=len(references),
            )
            try:
                descriptor = self._descriptor_for_reference(descriptors, reference)
                self._record_parser_usage(reader, descriptor)
                if descriptor.availability != "available":
                    raise UnsupportedReportError(
                        "This fixed report source is unavailable or future-gated in V1."
                    )
                path = self._resolve_reference(reference, descriptor)
                size = path.stat().st_size
                total_bytes += size
                if total_bytes > request.maximum_total_bytes:
                    raise MalformedReportError("Report request exceeds its total byte budget.")
                raw = path.read_bytes()
                content = self._parse_registered_content(raw, descriptor)
                document, sections, findings, evidence, interpretation, chronology = (
                    self._materialize_document(
                        request=request,
                        run=run,
                        reference=reference,
                        descriptor=descriptor,
                        content=content,
                        content_digest=_path_digest(path),
                        include_chronology=request.include_chronology,
                    )
                )
                reader.report_documents.append(document)
                reader.report_sections.extend(sections)
                reader.findings.extend(findings)
                reader.evidence_references.extend(evidence)
                reader.status_interpretations.append(interpretation)
                reader.chronology_entries.extend(chronology)
                self._record_source_usage(reader, descriptor, document, chronology)
                run.report_document_ids.append(document.report_document_id)
                run.chronology_entry_ids.extend(item.chronology_entry_id for item in chronology)
                if document.stale:
                    run.stale_reference_ids.append(reference.report_reference_id)
                    self._append_event(
                        reader,
                        read_run_id=run.read_run_id,
                        event_type="report_stale",
                        report_reference_id=reference.report_reference_id,
                        report_document_id=document.report_document_id,
                        technical_message=(
                            "The report is readable but cannot establish "
                            "the requested current state."
                        ),
                        easy_message=(
                            "This report is historical or stale for the current project review."
                        ),
                        confirmed_fact="The source report remains visible for history and context.",
                        requires_attention=reference.required,
                    )
                self._append_event(
                    reader,
                    read_run_id=run.read_run_id,
                    event_type="report_read_completed",
                    report_reference_id=reference.report_reference_id,
                    report_document_id=document.report_document_id,
                    technical_message=(
                        "Registered report parsing and bounded finding extraction completed."
                    ),
                    easy_message="BOBA preserved the source report's findings and limits.",
                    confirmed_fact="No source decision or report body was changed.",
                    progress_current=index,
                    progress_total=len(references),
                )
            except UnsupportedReportError as exc:
                run.unsupported_reference_ids.append(reference.report_reference_id)
                self._append_incident(
                    reader,
                    run,
                    reference,
                    "unsupported_format",
                    "medium",
                    "Registered report source unavailable",
                    str(exc),
                    blocked=reference.required,
                )
                self._append_event(
                    reader,
                    read_run_id=run.read_run_id,
                    event_type="report_unsupported",
                    report_reference_id=reference.report_reference_id,
                    technical_message=(
                        "The report was not read because its registered "
                        "source or format is unavailable."
                    ),
                    easy_message=(
                        "BOBA cannot honestly read this report with the current safe reader."
                    ),
                    confirmed_fact="No unsupported content was parsed.",
                    requires_attention=reference.required,
                    progress_current=index,
                    progress_total=len(references),
                )
            except DuplicateJsonKeyError as exc:
                run.failed_reference_ids.append(reference.report_reference_id)
                self._append_incident(
                    reader,
                    run,
                    reference,
                    "duplicate_json_key",
                    "high",
                    "Duplicate JSON key",
                    str(exc),
                    blocked=reference.required,
                )
                self._append_event(
                    reader,
                    read_run_id=run.read_run_id,
                    event_type="report_malformed",
                    report_reference_id=reference.report_reference_id,
                    technical_message="The JSON report had duplicate keys and was rejected.",
                    easy_message="BOBA could not trust this report because a field was repeated.",
                    confirmed_fact="No duplicate-key report content was persisted.",
                    requires_attention=reference.required,
                    progress_current=index,
                    progress_total=len(references),
                )
            except (MalformedReportError, UnsafeReportReferenceError, OSError, ValueError) as exc:
                run.failed_reference_ids.append(reference.report_reference_id)
                incident_type = self._incident_type_for_error(exc)
                self._append_incident(
                    reader,
                    run,
                    reference,
                    incident_type,
                    "high" if reference.required else "medium",
                    "Report Reader could not safely read a report",
                    str(exc),
                    blocked=reference.required,
                )
                self._append_event(
                    reader,
                    read_run_id=run.read_run_id,
                    event_type="report_malformed",
                    report_reference_id=reference.report_reference_id,
                    technical_message=(
                        "A registered report failed structure, scope, or bounds validation."
                    ),
                    easy_message="BOBA left this report unread because it was unsafe or malformed.",
                    confirmed_fact="No unsafe report content was used.",
                    requires_attention=reference.required,
                    progress_current=index,
                    progress_total=len(references),
                )
        contradictions: list[BobaReportContradictionV1] = []
        if request.include_contradictions:
            contradictions = self._detect_contradictions(reader, run)
            reader.contradictions.extend(contradictions)
            run.contradiction_ids.extend(item.contradiction_id for item in contradictions)
            if contradictions:
                self._append_event(
                    reader,
                    read_run_id=run.read_run_id,
                    event_type="contradiction_detected",
                    technical_message=(
                        "Conflicting source findings were retained without resolving them."
                    ),
                    easy_message=(
                        "BOBA found reports that disagree and needs "
                        "the responsible source or a person to resolve them."
                    ),
                    confirmed_fact="The conflicting source decisions remain unchanged.",
                    requires_attention=True,
                )
        coverage = self._build_coverage(reader, request, run)
        reader.coverage_records.append(coverage)
        run.coverage_id = coverage.coverage_id
        questions = (
            self._build_open_questions(run, coverage, contradictions)
            if request.include_open_questions
            else []
        )
        reader.open_questions.extend(questions)
        if questions:
            self._append_event(
                reader,
                read_run_id=run.read_run_id,
                event_type="evidence_missing",
                technical_message="Open questions preserve missing or conflicting source evidence.",
                easy_message="BOBA needs more source evidence or a responsible reviewer.",
                confirmed_fact="Report Reader did not fill in missing evidence.",
                requires_attention=True,
            )
        self._append_unique_handoffs(
            reader,
            self._build_handoffs(run, coverage, questions, contradictions),
        )
        if (
            run.failed_reference_ids
            or run.unsupported_reference_ids
            or coverage.coverage_status in {"incomplete", "blocked", "unsupported"}
        ):
            run.status = "incomplete"
            run.stop_reason = (
                "Required report evidence is missing, unsupported, stale, or unreadable."
            )
        elif run.stale_reference_ids:
            run.status = "completed_with_limitations"
        else:
            run.status = "completed"
        run.completed_at = now_iso()
        self._append_event(
            reader,
            read_run_id=run.read_run_id,
            event_type="reading_completed"
            if run.status in {"completed", "completed_with_limitations"}
            else "reading_incomplete",
            technical_message=f"Report Reader run completed with status {run.status}.",
            easy_message=(
                "BOBA finished the report explanation."
                if run.status == "completed"
                else (
                    "BOBA finished reading, but important report evidence "
                    "is still missing or limited."
                )
            ),
            confirmed_fact=(
                "Report Reader did not change any source decision or authorize an action."
            ),
            requires_attention=run.status != "completed",
            progress_current=len(references),
            progress_total=len(references),
        )
        self._refresh_summary(reader)
        self.store.save_boba_report_reader(reader)
        return self.inspect_report_read_run(project_id, run.read_run_id)

    def inspect_report_read_run(self, project_id: str, read_run_id: str) -> dict[str, Any]:
        reader = self._reader(project_id)
        run = self._run(reader, read_run_id)
        document_ids = set(run.report_document_ids)
        return _sanitize_report_mapping(
            {
                "schema_version": "boba_report_read_run_inspection_v1",
                "project_id": project_id,
                "run": run.model_dump(mode="json"),
                "documents": [
                    item.model_dump(mode="json")
                    for item in reader.report_documents
                    if item.report_document_id in document_ids
                ],
                "findings": [
                    item.model_dump(mode="json")
                    for item in reader.findings
                    if item.report_document_id in document_ids
                ],
                "evidence": [
                    item.model_dump(mode="json")
                    for item in reader.evidence_references
                    if item.report_document_id in document_ids
                ],
                "interpretations": [
                    item.model_dump(mode="json")
                    for item in reader.status_interpretations
                    if item.report_document_id in document_ids
                ],
                "chronology": [
                    item.model_dump(mode="json")
                    for item in reader.chronology_entries
                    if item.chronology_entry_id in set(run.chronology_entry_ids)
                ],
                "contradictions": [
                    item.model_dump(mode="json")
                    for item in reader.contradictions
                    if item.contradiction_id in set(run.contradiction_ids)
                ],
                "coverage": next(
                    (
                        item.model_dump(mode="json")
                        for item in reversed(reader.coverage_records)
                        if item.coverage_id == run.coverage_id
                    ),
                    None,
                ),
                "open_questions": [item.model_dump(mode="json") for item in reader.open_questions],
                "handoffs": [
                    item.model_dump(mode="json")
                    for item in reader.handoffs
                    if item.read_run_id == read_run_id
                ],
            }
        )

    def compare_registered_reports(self, project_id: str, *, read_run_id: str) -> dict[str, Any]:
        reader = self._reader(project_id)
        run = self._run(reader, read_run_id)
        existing_ids = set(run.contradiction_ids)
        detected = self._detect_contradictions(reader, run)
        new = [item for item in detected if item.contradiction_id not in existing_ids]
        if new:
            reader.contradictions.extend(new)
            run.contradiction_ids.extend(item.contradiction_id for item in new)
            self._refresh_summary(reader)
            self.store.save_boba_report_reader(reader)
        return _sanitize_report_mapping(
            {
                "schema_version": "boba_report_comparison_v1",
                "project_id": project_id,
                "read_run_id": read_run_id,
                "contradictions": [
                    item.model_dump(mode="json")
                    for item in reader.contradictions
                    if item.contradiction_id in set(run.contradiction_ids)
                ],
                "resolved_by_reader": False,
            }
        )

    def build_report_bundle(
        self, project_id: str, *, read_run_id: str, purpose: str
    ) -> BobaReportBundleV1:
        reader = self._reader(project_id)
        run = self._run(reader, read_run_id)
        request = self._request(reader, run.read_request_id)
        document_ids = list(run.report_document_ids)
        findings = [
            item for item in reader.findings if item.report_document_id in set(document_ids)
        ]
        evidence = [
            item
            for item in reader.evidence_references
            if item.report_document_id in set(document_ids)
        ]
        chronology = [
            item
            for item in reader.chronology_entries
            if item.chronology_entry_id in set(run.chronology_entry_ids)
        ]
        contradictions = [
            item
            for item in reader.contradictions
            if item.contradiction_id in set(run.contradiction_ids)
        ]
        coverage = next(
            (
                item
                for item in reversed(reader.coverage_records)
                if item.coverage_id == run.coverage_id
            ),
            None,
        )
        if coverage is None:
            coverage = self._build_coverage(reader, request, run)
            reader.coverage_records.append(coverage)
        questions = [item for item in reader.open_questions if not item.report_bundle_id]
        facts = _unique_texts(
            [item.confirmed_fact for item in findings if item.confirmed_fact],
            limit=128,
            maximum=800,
        )
        assessments = _unique_texts(
            [item.source_assessment for item in findings if item.source_assessment],
            limit=128,
            maximum=800,
        )
        decisions = _unique_texts(
            [item.source_decision for item in findings if item.source_decision],
            limit=128,
            maximum=180,
        )
        interpretations = _unique_texts(
            [item.reader_interpretation for item in findings if item.reader_interpretation],
            limit=128,
            maximum=800,
        )
        blocking = [
            item.finding_id
            for item in findings
            if item.severity in {"high", "critical"} or item.stale
        ]
        technical_summary = self._technical_summary(run, coverage, contradictions, findings)
        easy_summary = self._easy_summary(run, coverage, contradictions, findings)
        bundle_payload = {
            "project_id": project_id,
            "workflow_run_id": run.workflow_run_id,
            "reading_mode": request.reading_mode,
            "purpose": _bounded_text(purpose, maximum=600),
            "report_document_ids": document_ids,
            "finding_ids": [item.finding_id for item in findings],
            "evidence_reference_ids": [item.evidence_reference_id for item in evidence],
            "chronology_entry_ids": [item.chronology_entry_id for item in chronology],
            "contradiction_ids": [item.contradiction_id for item in contradictions],
            "coverage_id": coverage.coverage_id,
            "source_decisions": decisions,
            "confirmed_facts": facts,
            "source_assessments": assessments,
            "reader_interpretations": interpretations,
            "blocking_findings": blocking,
            "unresolved_questions": [item.open_question_id for item in questions],
            "easy_summary": easy_summary,
            "technical_summary": technical_summary,
            "current": run.status == "completed"
            and not any(
                item.stale
                for item in reader.report_documents
                if item.report_document_id in set(document_ids)
            ),
        }
        bundle_digest = calculate_report_bundle_digest(bundle_payload)
        bundle = BobaReportBundleV1(
            report_bundle_id=f"report_bundle_{bundle_digest[:24]}",
            bundle_digest=bundle_digest,
            **bundle_payload,
        )
        existing = next(
            (
                item
                for item in reader.report_bundles
                if item.report_bundle_id == bundle.report_bundle_id
            ),
            None,
        )
        if existing is not None:
            return existing
        reader.report_bundles.append(bundle)
        run.bundle_ids.append(bundle.report_bundle_id)
        for question in questions:
            question.report_bundle_id = bundle.report_bundle_id
        self._append_unique_handoffs(
            reader,
            self._build_handoffs(
                run,
                coverage,
                questions,
                contradictions,
                bundle=bundle,
            ),
        )
        self._append_event(
            reader,
            read_run_id=run.read_run_id,
            event_type="bundle_created",
            technical_message="A read-only report bundle was created from exact source references.",
            easy_message="BOBA grouped the report explanations without changing their decisions.",
            confirmed_fact=(
                "The bundle is not an approval, quality decision, or workflow transition."
            ),
        )
        self._refresh_summary(reader)
        self.store.save_boba_report_reader(reader)
        return bundle

    def inspect_report_bundle(self, project_id: str, bundle_id: str) -> dict[str, Any]:
        reader = self._reader(project_id)
        bundle = next(
            (item for item in reader.report_bundles if item.report_bundle_id == bundle_id), None
        )
        if bundle is None:
            raise NotFoundError("BOBA Report Reader bundle was not found.")
        return _sanitize_report_mapping(bundle.model_dump(mode="json"))

    def inspect_report_events(self, project_id: str, read_run_id: str) -> list[BobaReportEventV1]:
        reader = self._reader(project_id)
        self._run(reader, read_run_id)
        return [item for item in reader.events if item.read_run_id == read_run_id]

    def export_report_reader(self, project_id: str) -> dict[str, Any]:
        reader = self._reader(project_id)
        return _sanitize_report_mapping(
            {
                "schema_version": "boba_report_reader_export_v1",
                "project_id": project_id,
                "reader": reader.model_dump(mode="json"),
                "raw_report_bodies_included": False,
                "raw_logs_included": False,
                "source_media_included": False,
            }
        )

    def reset_report_reader_metadata(self, project_id: str) -> dict[str, Any]:
        reader = self._reader(project_id)
        self._refresh_summary(reader)
        self.store.save_boba_report_reader(reader)
        return {
            "schema_version": "boba_report_reader_reset_v1",
            "project_id": project_id,
            "active_metadata_removed": False,
            "completed_read_history_preserved": True,
            "source_reports_preserved": True,
            "workflow_history_preserved": True,
            "validator_history_preserved": True,
            "safety_decisions_preserved": True,
            "integration_transactions_preserved": True,
            "reason": "V1 reset is non-destructive and preserves immutable report history.",
        }

    def _build_references(
        self,
        project_id: str,
        *,
        source_id: str,
        workflow_run_id: str,
        supplied: Sequence[Mapping[str, Any]],
        descriptors: Mapping[str, BobaReportSourceDescriptorV1],
    ) -> list[BobaReportReferenceV1]:
        allowed = {
            "source_descriptor_id",
            "producer_module_id",
            "producer_record_id",
            "report_type",
            "schema_id",
            "schema_version",
            "expected_digest",
            "sanitized_storage_reference",
            "format",
            "immutable",
            "historical",
            "required",
            "rights_relevant",
            "safety_relevant",
            "quality_relevant",
            "workflow_relevant",
            "workflow_run_id",
            "stage_instance_id",
            "warnings",
        }
        references: list[BobaReportReferenceV1] = []
        for index, raw in enumerate(supplied):
            unexpected = sorted(set(raw) - allowed)
            if unexpected:
                raise ValidationError(
                    (
                        "Report references cannot provide parsers, commands, "
                        "paths, or unsupported fields."
                    ),
                    details={"fields": unexpected},
                )
            descriptor_id = _bounded_text(raw.get("source_descriptor_id"), maximum=180)
            descriptor = descriptors.get(descriptor_id)
            if descriptor is None:
                raise ValidationError(
                    "Report reference requested an unknown fixed source descriptor.",
                    details={"source_descriptor_id": descriptor_id},
                )
            producer = _bounded_text(
                raw.get("producer_module_id") or descriptor.producer_module_id, maximum=160
            )
            if producer != descriptor.producer_module_id:
                raise ValidationError(
                    "Report reference producer does not match its fixed source descriptor."
                )
            report_type = cast(BobaReportTypeV1, raw.get("report_type") or descriptor.report_type)
            if report_type != descriptor.report_type:
                raise ValidationError(
                    "Report reference type does not match its fixed source descriptor."
                )
            schema_id = _bounded_text(raw.get("schema_id") or descriptor.schema_id, maximum=180)
            if schema_id != descriptor.schema_id:
                raise ValidationError(
                    "Report reference schema does not match its fixed source descriptor."
                )
            report_format = cast(
                BobaReportFormatV1, raw.get("format") or descriptor.expected_format
            )
            if report_format != descriptor.expected_format:
                raise ValidationError(
                    "Report reference format does not match its fixed source descriptor."
                )
            reference = BobaReportReferenceV1(
                report_reference_id=_stable_id(
                    "report_reference",
                    project_id,
                    descriptor_id,
                    raw.get("producer_record_id"),
                    raw.get("sanitized_storage_reference"),
                    raw.get("expected_digest"),
                    index,
                ),
                project_id=project_id,
                source_id=source_id,
                workflow_run_id=_bounded_text(
                    raw.get("workflow_run_id") or workflow_run_id, maximum=180
                ),
                stage_instance_id=_bounded_text(raw.get("stage_instance_id"), maximum=180),
                producer_module_id=producer,
                source_descriptor_id=descriptor_id,
                producer_record_id=_bounded_text(raw.get("producer_record_id"), maximum=180),
                report_type=report_type,
                schema_id=schema_id,
                schema_version=_bounded_text(raw.get("schema_version") or "1", maximum=80),
                expected_digest=_bounded_text(raw.get("expected_digest"), maximum=64),
                sanitized_storage_reference=_bounded_text(
                    raw.get("sanitized_storage_reference"), maximum=500
                ),
                format=report_format,
                immutable=bool(raw.get("immutable", True)),
                historical=bool(raw.get("historical", False)),
                required=bool(raw.get("required", True)),
                rights_relevant=bool(raw.get("rights_relevant", descriptor.rights_sensitive)),
                safety_relevant=bool(raw.get("safety_relevant", descriptor.safety_sensitive)),
                quality_relevant=bool(raw.get("quality_relevant", descriptor.quality_sensitive)),
                workflow_relevant=bool(raw.get("workflow_relevant", descriptor.workflow_sensitive)),
                warnings=_unique_texts(raw.get("warnings")),
            )
            references.append(reference)
        if len({item.report_reference_id for item in references}) != len(references):
            raise ValidationError("Report Reader references must be unique.")
        return references

    def _resolve_reference(
        self, reference: BobaReportReferenceV1, descriptor: BobaReportSourceDescriptorV1
    ) -> Path:
        expected_prefix = f"projects/{reference.project_id}/"
        if not reference.sanitized_storage_reference.startswith(expected_prefix):
            raise UnsafeReportReferenceError("Report reference is outside its exact project scope.")
        relative = PurePosixPath(reference.sanitized_storage_reference)
        suffix = "/".join(relative.parts[2:])
        if not self._scope_matches(suffix, descriptor.expected_storage_scope):
            raise UnsafeReportReferenceError(
                "Report reference is outside the registered source storage scope."
            )
        path = (self.store.root / Path(*relative.parts)).resolve()
        project_root = (self.project_root / reference.project_id).resolve()
        if project_root not in path.parents or path == project_root:
            raise UnsafeReportReferenceError(
                "Report reference escaped the allowed project directory."
            )
        if not path.exists() or not path.is_file():
            raise UnsafeReportReferenceError("Registered report artifact is missing.")
        if path.suffix.casefold() not in {".json", ".jsonl", ".md", ".txt"}:
            raise UnsafeReportReferenceError("Report artifact format is not allowed.")
        return path

    @staticmethod
    def _scope_matches(suffix: str, pattern: str) -> bool:
        actual = PurePosixPath(suffix)
        expected = PurePosixPath(pattern)
        if len(actual.parts) != len(expected.parts):
            return False
        return all(
            expected_part == "*" or actual_part == expected_part
            for actual_part, expected_part in zip(actual.parts, expected.parts, strict=True)
        )

    def _parse_registered_content(
        self, raw: bytes, descriptor: BobaReportSourceDescriptorV1
    ) -> Any:
        if descriptor.parser_id not in _FIXED_PARSER_REGISTRY:
            raise UnsupportedReportError("The report source selected an unregistered parser.")
        if descriptor.expected_format == "json":
            self._reader_signal(descriptor, "json")
            return _strict_json_parse(raw, descriptor)
        if descriptor.expected_format == "jsonl":
            self._reader_signal(descriptor, "jsonl")
            return _strict_jsonl_parse(raw, descriptor)
        if descriptor.expected_format == "markdown":
            self._reader_signal(descriptor, "markdown")
            return _bounded_text_parse(raw, descriptor)
        if descriptor.expected_format == "plain_text":
            self._reader_signal(descriptor, "plain_text")
            return _bounded_text_parse(raw, descriptor)
        raise UnsupportedReportError("The fixed report format is unsupported in V1.")

    def _reader_signal(
        self,
        descriptor: BobaReportSourceDescriptorV1,
        parser: str,
    ) -> None:
        del descriptor, parser

    @staticmethod
    def _record_parser_usage(
        reader: BobaReportReaderSetV1,
        descriptor: BobaReportSourceDescriptorV1,
    ) -> None:
        if descriptor.expected_format == "json":
            reader.signal_usage.json_parser_used = True
        elif descriptor.expected_format == "jsonl":
            reader.signal_usage.jsonl_parser_used = True
        elif descriptor.expected_format == "markdown":
            reader.signal_usage.markdown_parser_used = True
        elif descriptor.expected_format == "plain_text":
            reader.signal_usage.plain_text_parser_used = True

    @staticmethod
    def _record_source_usage(
        reader: BobaReportReaderSetV1,
        descriptor: BobaReportSourceDescriptorV1,
        document: BobaReportDocumentV1,
        chronology: Sequence[BobaReportChronologyEntryV1],
    ) -> None:
        reader.signal_usage.chronology_analysis_used |= bool(chronology)
        reader.signal_usage.current_state_analysis_used |= not document.historical
        reader.signal_usage.historical_analysis_used |= document.historical
        if descriptor.producer_module_id == "integration_layer":
            reader.signal_usage.integration_layer_used = True
        elif descriptor.producer_module_id == "validator_runner":
            reader.signal_usage.validator_runner_evidence_used = True
        elif descriptor.producer_module_id == "workflow_controller":
            reader.signal_usage.workflow_controller_context_used = True
        elif descriptor.producer_module_id == "output_quality_reviewer":
            reader.signal_usage.output_quality_context_used = True
        elif descriptor.producer_module_id == "safety_gate":
            reader.signal_usage.safety_gate_context_used = True
        elif descriptor.producer_module_id == "autopilot_controller":
            reader.signal_usage.autopilot_context_used = True

    def _materialize_document(
        self,
        *,
        request: BobaReportReadRequestV1,
        run: BobaReportReadRunV1,
        reference: BobaReportReferenceV1,
        descriptor: BobaReportSourceDescriptorV1,
        content: Any,
        content_digest: str,
        include_chronology: bool,
    ) -> tuple[
        BobaReportDocumentV1,
        list[BobaReportSectionV1],
        list[BobaReportFindingV1],
        list[BobaReportEvidenceReferenceV1],
        BobaReportStatusInterpretationV1,
        list[BobaReportChronologyEntryV1],
    ]:
        schema_version = _source_schema_version(content, reference.schema_version)
        if schema_version not in descriptor.supported_schema_versions:
            raise UnsupportedReportError(
                "Report schema version is not supported by its fixed source descriptor."
            )
        project_identity = _source_project_id(content)
        project_match = not project_identity or project_identity == reference.project_id
        if not project_match:
            raise UnsafeReportReferenceError(
                "Report payload project identity does not match its reference."
            )
        source_identity = _bounded_text(_mapping(content).get("source_id"), maximum=512)
        source_match = not source_identity or source_identity == reference.source_id
        if not source_match:
            raise UnsafeReportReferenceError(
                "Report payload source identity does not match its reference."
            )
        source_snapshot = _source_snapshot_digest(content)
        snapshot_match = bool(
            request.current_project_snapshot_digest
            and source_snapshot == request.current_project_snapshot_digest
        )
        historical = reference.historical or request.reading_mode == "historical_review"
        stale = (
            request.reading_mode == "current_project_review"
            and (not request.current_project_snapshot_digest or not snapshot_match)
        ) or historical
        document_id = _stable_id(
            "report_document", run.read_run_id, reference.report_reference_id, content_digest
        )
        findings, evidence = self._extract_findings_and_evidence(
            document_id, descriptor, content, stale=stale
        )
        sections = self._extract_sections(document_id, descriptor, content, findings, evidence)
        chronology = (
            self._extract_chronology(
                document_id,
                reference,
                descriptor,
                content,
                findings,
                evidence,
            )
            if include_chronology
            else []
        )
        status, decision = self._source_status_decision(content)
        interpretation = BobaReportStatusInterpretationV1(
            status_interpretation_id=_stable_id(
                "report_status_interpretation", document_id, status, decision
            ),
            report_document_id=document_id,
            producer_module_id=descriptor.producer_module_id,
            authority_domain=descriptor.authority_domain,
            original_status=status,
            original_decision=decision,
            normalized_display_category=self._display_category(status, decision),
            stale=stale,
            expired=bool(_mapping(content).get("expired", False)),
            invalidated=bool(_mapping(content).get("invalidated", False)),
            human_review_required=bool(_mapping(content).get("human_review_required", False)),
            blocking=_severity_for(f"{status} {decision}") in {"high", "critical"},
            bounded_explanation=(
                "Report Reader preserved the source status and decision; "
                "it did not grant any current action authority."
            ),
            warnings=(
                ["Historical or stale evidence cannot prove the requested current state."]
                if stale
                else []
            ),
        )
        document = BobaReportDocumentV1(
            report_document_id=document_id,
            report_reference_id=reference.report_reference_id,
            project_id=reference.project_id,
            workflow_run_id=reference.workflow_run_id or _source_workflow_id(content),
            producer_module_id=descriptor.producer_module_id,
            producer_record_id=reference.producer_record_id,
            report_type=reference.report_type,
            schema_id=reference.schema_id,
            schema_version=schema_version,
            parser_id=descriptor.parser_id,
            format=descriptor.expected_format,
            content_digest=content_digest,
            expected_digest_match=not reference.expected_digest
            or reference.expected_digest == content_digest,
            project_identity_match=project_match,
            source_identity_match=source_match,
            schema_supported=True,
            current_project_snapshot_match=snapshot_match,
            historical=historical,
            stale=stale,
            source_decision_ids=([interpretation.status_interpretation_id] if decision else []),
            section_ids=[item.report_section_id for item in sections],
            finding_ids=[item.finding_id for item in findings],
            evidence_reference_ids=[item.evidence_reference_id for item in evidence],
            chronology_entry_ids=[item.chronology_entry_id for item in chronology],
            warning_count=sum(1 for item in findings if item.finding_type == "warning"),
            limitation_count=sum(1 for item in findings if item.finding_type == "limitation"),
            read_status="completed_with_limitations" if stale else "completed",
            warnings=(
                ["Private paths were redacted from extracted metadata."]
                if _contains_private_path(content)
                else []
            ),
            limitations=["Raw report content is not persisted by Report Reader."],
        )
        for finding in findings:
            finding.current = not stale
            finding.stale = stale
        for item in evidence:
            item.current = not stale
            item.stale = stale
        return document, sections, findings, evidence, interpretation, chronology

    def _extract_findings_and_evidence(
        self,
        document_id: str,
        descriptor: BobaReportSourceDescriptorV1,
        content: Any,
        *,
        stale: bool,
    ) -> tuple[list[BobaReportFindingV1], list[BobaReportEvidenceReferenceV1]]:
        findings: list[BobaReportFindingV1] = []
        evidence: list[BobaReportEvidenceReferenceV1] = []
        values = _find_values(content)
        status, decision = self._source_status_decision(content)
        source_confidence = _source_confidence(content)
        identity = _mapping(content)
        related_artifacts = _unique_texts(
            [identity.get("artifact_id"), identity.get("output_id")], limit=8, maximum=180
        )
        related_clips = _unique_texts([identity.get("clip_id")], limit=8, maximum=180)
        related_outputs = _unique_texts([identity.get("output_id")], limit=8, maximum=180)
        if status or decision:
            findings.append(
                BobaReportFindingV1(
                    finding_id=_stable_id(
                        "report_finding", document_id, "status", status, decision
                    ),
                    report_document_id=document_id,
                    producer_module_id=descriptor.producer_module_id,
                    authority_domain=descriptor.authority_domain,
                    finding_type="source_status",
                    severity=_severity_for(f"{status} {decision}"),
                    title="Source status and decision",
                    bounded_summary=_safe_text(
                        f"Source status: {status or 'not stated'}; "
                        f"source decision: {decision or 'not stated'}.",
                        maximum=1_600,
                    ),
                    source_field_path="status/decision",
                    source_status=status,
                    source_decision=decision,
                    confirmed_fact=(
                        f"The source report states status '{status}'." if status else ""
                    ),
                    source_assessment=(
                        f"The source report states decision '{decision}'." if decision else ""
                    ),
                    reader_interpretation=(
                        "Report Reader preserved this source-owned status "
                        "without granting authority."
                    ),
                    related_artifact_ids=related_artifacts,
                    related_clip_ids=related_clips,
                    related_output_ids=related_outputs,
                    confidence=source_confidence,
                    stale=stale,
                    requires_human_interpretation=stale,
                )
            )
        for path, key, value in values:
            key_lower = key.casefold()
            if len(findings) >= _MAX_FINDINGS or len(evidence) >= _MAX_FINDINGS:
                break
            if key_lower in {
                "warning",
                "warnings",
                "limitation",
                "limitations",
                "incident",
                "incidents",
                "failure",
                "failures",
                "error",
                "errors",
            }:
                for index, item in enumerate(_sequence(value) or [value]):
                    summary = _safe_text(item, maximum=1_200)
                    if not summary:
                        continue
                    kind = (
                        "limitation"
                        if "limitation" in key_lower
                        else "warning"
                        if "warning" in key_lower
                        else "incident"
                    )
                    findings.append(
                        BobaReportFindingV1(
                            finding_id=_stable_id(
                                "report_finding", document_id, path, index, summary
                            ),
                            report_document_id=document_id,
                            producer_module_id=descriptor.producer_module_id,
                            authority_domain=descriptor.authority_domain,
                            finding_type=kind,
                            severity=_severity_for(summary),
                            title=kind.replace("_", " ").title(),
                            bounded_summary=summary,
                            source_field_path=path,
                            source_status=status,
                            source_decision=decision,
                            confirmed_fact=f"The source report contains this {kind}.",
                            source_assessment=summary,
                            reader_interpretation=(
                                "Report Reader retained the source wording and did not resolve it."
                            ),
                            related_artifact_ids=related_artifacts,
                            related_clip_ids=related_clips,
                            related_output_ids=related_outputs,
                            confidence=source_confidence,
                            stale=stale,
                            requires_human_interpretation=kind in {"incident", "limitation"},
                        )
                    )
            if key_lower in {
                "artifact_id",
                "artifact_digest",
                "evidence_id",
                "validation_run_id",
                "validator_id",
                "output_id",
                "clip_id",
                "report_reference_id",
            }:
                item_text = _safe_text(value, maximum=180)
                if not item_text:
                    continue
                artifact_digest = (
                    item_text
                    if key_lower == "artifact_digest" and _SHA256.fullmatch(item_text.casefold())
                    else ""
                )
                evidence.append(
                    BobaReportEvidenceReferenceV1(
                        evidence_reference_id=_stable_id(
                            "report_evidence", document_id, path, item_text
                        ),
                        report_document_id=document_id,
                        source_module_id=descriptor.producer_module_id,
                        source_field_path=path,
                        artifact_id=(
                            item_text
                            if key_lower in {"artifact_id", "output_id", "clip_id"}
                            else ""
                        ),
                        artifact_digest=artifact_digest,
                        validator_id=(item_text if key_lower == "validator_id" else ""),
                        validation_run_id=(item_text if key_lower == "validation_run_id" else ""),
                        evidence_type=key_lower,
                        bounded_summary=f"Source-declared {key_lower}: {item_text}.",
                        stale=stale,
                        verifiable=bool(artifact_digest),
                        reliability="verified_digest" if artifact_digest else "source_declared",
                        supports="source_fact",
                    )
                )
        return findings[:_MAX_FINDINGS], evidence[:_MAX_FINDINGS]

    def _extract_sections(
        self,
        document_id: str,
        descriptor: BobaReportSourceDescriptorV1,
        content: Any,
        findings: Sequence[BobaReportFindingV1],
        evidence: Sequence[BobaReportEvidenceReferenceV1],
    ) -> list[BobaReportSectionV1]:
        mapped = _mapping(content)
        sections: list[BobaReportSectionV1] = []
        section_specs: list[tuple[BobaReportSectionTypeV1, str, str, bool, bool, bool, bool]] = [
            ("identity", "project_id", "Identity", False, False, False, False),
            ("status", "status", "Source status", True, False, False, False),
            ("decision", "decision", "Source decision", True, False, False, False),
            ("findings", "findings", "Extracted findings", False, False, False, False),
            ("evidence", "evidence", "Source evidence", False, True, False, False),
            ("warnings", "warnings", "Source warnings", False, False, True, False),
            ("limitations", "limitations", "Source limitations", False, False, False, True),
            ("handoffs", "handoffs", "Source handoffs", False, False, False, False),
            ("events", "events", "Source events", False, False, False, False),
        ]
        for (
            section_type,
            field,
            title,
            decision_bearing,
            evidence_bearing,
            warning_bearing,
            limitation_bearing,
        ) in section_specs:
            if field == "findings":
                value: Any = [item.bounded_summary for item in findings]
            elif field == "evidence":
                value = [item.bounded_summary for item in evidence]
            else:
                value = mapped.get(field)
            if value is None or value == "" or value == [] or value == {}:
                continue
            text = _safe_text(
                json.dumps(sanitize_report_export(value), ensure_ascii=True, default=str),
                maximum=4_000,
            )
            sections.append(
                BobaReportSectionV1(
                    report_section_id=_stable_id("report_section", document_id, field),
                    report_document_id=document_id,
                    section_type=section_type,
                    source_field_path=field,
                    title=title,
                    bounded_text=text,
                    item_count=len(_sequence(value)) if isinstance(value, list) else 1,
                    source_owned=True,
                    decision_bearing=decision_bearing,
                    evidence_bearing=evidence_bearing,
                    warning_bearing=warning_bearing,
                    limitation_bearing=limitation_bearing,
                )
            )
        if not sections:
            sections.append(
                BobaReportSectionV1(
                    report_section_id=_stable_id("report_section", document_id, "summary"),
                    report_document_id=document_id,
                    section_type="summary",
                    source_field_path="root",
                    title=descriptor.display_name,
                    bounded_text=(
                        "The registered report contained no extractable public summary fields."
                    ),
                    source_owned=True,
                )
            )
        return sections

    def _extract_chronology(
        self,
        document_id: str,
        reference: BobaReportReferenceV1,
        descriptor: BobaReportSourceDescriptorV1,
        content: Any,
        findings: Sequence[BobaReportFindingV1],
        evidence: Sequence[BobaReportEvidenceReferenceV1],
    ) -> list[BobaReportChronologyEntryV1]:
        entries: list[BobaReportChronologyEntryV1] = []
        timestamp_keys = {
            "created_at",
            "updated_at",
            "completed_at",
            "occurred_at",
            "requested_at",
            "started_at",
            "ended_at",
            "timestamp",
        }
        for path, key, value in _find_values(content, limit=_MAX_CHRONOLOGY):
            if key.casefold() not in timestamp_keys or not _bounded_text(value, maximum=100):
                continue
            if _parse_time(value) is None:
                continue
            entries.append(
                BobaReportChronologyEntryV1(
                    chronology_entry_id=_stable_id("report_chronology", document_id, path, value),
                    project_id=reference.project_id,
                    workflow_run_id=reference.workflow_run_id,
                    report_document_id=document_id,
                    producer_module_id=descriptor.producer_module_id,
                    event_type=key.casefold(),
                    occurred_at=_bounded_text(value, maximum=80),
                    timestamp_precision=_timestamp_precision(value),
                    timestamp_source=path,
                    confirmed_order=True,
                    bounded_summary=f"Source-declared {key}: {_safe_text(value, maximum=120)}.",
                    related_finding_ids=[item.finding_id for item in findings[:8]],
                    related_evidence_ids=[item.evidence_reference_id for item in evidence[:8]],
                )
            )
        return entries[:_MAX_CHRONOLOGY]

    @staticmethod
    def _source_status_decision(content: Any) -> tuple[str, str]:
        mapped = _mapping(content)
        status = ""
        decision = ""
        for key in ("status", "run_status", "state", "health_status", "availability_status"):
            value = _bounded_text(mapped.get(key), maximum=180)
            if value:
                status = value
                break
        for key in ("decision", "decision_value", "suite_decision", "outcome", "quality_decision"):
            decision_value: Any = mapped.get(key)
            if isinstance(decision_value, Mapping):
                decision_value = decision_value.get("decision") or decision_value.get("status")
            text = _bounded_text(decision_value, maximum=180)
            if text:
                decision = text
                break
        return status, decision

    @staticmethod
    def _display_category(status: str, decision: str) -> str:
        combined = f"{status} {decision}".casefold()
        if any(word in combined for word in ("failed", "blocked", "denied", "rejected", "invalid")):
            return "blocking_source_state"
        if any(word in combined for word in ("warning", "stale", "incomplete", "review")):
            return "limited_source_state"
        if any(
            word in combined for word in ("passed", "accepted", "allowed", "completed", "ready")
        ):
            return "source_reported_positive_state"
        return "source_state_not_interpreted"

    def _detect_contradictions(
        self,
        reader: BobaReportReaderSetV1,
        run: BobaReportReadRunV1,
    ) -> list[BobaReportContradictionV1]:
        document_ids = set(run.report_document_ids)
        documents = [
            item for item in reader.report_documents if item.report_document_id in document_ids
        ]
        findings = [item for item in reader.findings if item.report_document_id in document_ids]
        evidence = [
            item for item in reader.evidence_references if item.report_document_id in document_ids
        ]
        findings_by_document: dict[str, list[BobaReportFindingV1]] = {}
        for finding in findings:
            findings_by_document.setdefault(finding.report_document_id, []).append(finding)
        evidence_by_document: dict[str, list[BobaReportEvidenceReferenceV1]] = {}
        for item in evidence:
            evidence_by_document.setdefault(item.report_document_id, []).append(item)

        contradictions: list[BobaReportContradictionV1] = []
        for index, left in enumerate(documents):
            for right in documents[index + 1 :]:
                if len(contradictions) >= _MAX_CONTRADICTIONS:
                    return contradictions
                if left.project_id != right.project_id:
                    continue
                if (
                    left.workflow_run_id
                    and right.workflow_run_id
                    and left.workflow_run_id != right.workflow_run_id
                ):
                    continue
                left_evidence = evidence_by_document.get(left.report_document_id, [])
                right_evidence = evidence_by_document.get(right.report_document_id, [])
                left_targets = {item.artifact_id for item in left_evidence if item.artifact_id}
                right_targets = {item.artifact_id for item in right_evidence if item.artifact_id}
                shared_targets = left_targets & right_targets
                same_record = bool(
                    left.producer_record_id and left.producer_record_id == right.producer_record_id
                )
                if not shared_targets and not same_record:
                    continue

                left_status, left_decision = self._document_status(
                    findings_by_document.get(left.report_document_id, [])
                )
                right_status, right_decision = self._document_status(
                    findings_by_document.get(right.report_document_id, [])
                )
                left_digests = {
                    item.artifact_digest for item in left_evidence if item.artifact_digest
                }
                right_digests = {
                    item.artifact_digest for item in right_evidence if item.artifact_digest
                }
                conflict_type: BobaReportContradictionTypeV1 | None = None
                value_a = ""
                value_b = ""
                if left_decision and right_decision and left_decision != right_decision:
                    conflict_type = self._contradiction_type_for_documents(
                        left,
                        right,
                        "decision_conflict",
                    )
                    value_a, value_b = left_decision, right_decision
                elif left_status and right_status and left_status != right_status:
                    conflict_type = self._contradiction_type_for_documents(
                        left,
                        right,
                        "status_conflict",
                    )
                    value_a, value_b = left_status, right_status
                elif left_digests and right_digests and left_digests != right_digests:
                    conflicting_pair = next(
                        (
                            (left_digest, right_digest)
                            for left_digest in sorted(left_digests)
                            for right_digest in sorted(right_digests)
                            if left_digest != right_digest
                        ),
                        None,
                    )
                    if conflicting_pair is not None:
                        conflict_type = "artifact_digest_conflict"
                        value_a, value_b = conflicting_pair
                if conflict_type is None:
                    continue
                contradiction_id = _stable_id(
                    "report_contradiction",
                    run.read_run_id,
                    left.report_document_id,
                    right.report_document_id,
                    conflict_type,
                    value_a,
                    value_b,
                )
                contradictions.append(
                    BobaReportContradictionV1(
                        contradiction_id=contradiction_id,
                        project_id=left.project_id,
                        report_document_ids=[
                            left.report_document_id,
                            right.report_document_id,
                        ],
                        finding_ids=[
                            item.finding_id
                            for item in findings_by_document.get(
                                left.report_document_id,
                                [],
                            )[:2]
                        ]
                        + [
                            item.finding_id
                            for item in findings_by_document.get(
                                right.report_document_id,
                                [],
                            )[:2]
                        ],
                        authority_domains=[
                            self._authority_for_document(reader, left),
                            self._authority_for_document(reader, right),
                        ],
                        contradiction_type=conflict_type,
                        severity="high",
                        bounded_summary=(
                            "Source reports disagree for one exact target: "
                            f"'{_safe_text(value_a, maximum=180)}' versus "
                            f"'{_safe_text(value_b, maximum=180)}'."
                        ),
                        value_a=_safe_text(value_a, maximum=500),
                        value_b=_safe_text(value_b, maximum=500),
                        source_a_reference=left.report_reference_id,
                        source_b_reference=right.report_reference_id,
                        same_target=bool(shared_targets or same_record),
                        same_snapshot=(
                            left.current_project_snapshot_match
                            and right.current_project_snapshot_match
                        ),
                        same_artifact_digest=bool(left_digests & right_digests),
                        requires_human_review=True,
                    )
                )
        return contradictions

    @staticmethod
    def _document_status(findings: Sequence[BobaReportFindingV1]) -> tuple[str, str]:
        status = next((item.source_status for item in findings if item.source_status), "")
        decision = next((item.source_decision for item in findings if item.source_decision), "")
        return status, decision

    @staticmethod
    def _contradiction_type_for_documents(
        left: BobaReportDocumentV1,
        right: BobaReportDocumentV1,
        fallback: BobaReportContradictionTypeV1,
    ) -> BobaReportContradictionTypeV1:
        pair = {left.report_type, right.report_type}
        if "safety_gate" in pair:
            return "safety_conflict"
        if "rights_permission" in pair:
            return "rights_conflict"
        if "output_quality" in pair:
            return "quality_conflict"
        if "validator_runner" in pair or "technical_validation" in pair:
            return "validation_conflict"
        if "workflow_controller" in pair:
            return "lifecycle_conflict"
        return fallback

    @staticmethod
    def _authority_for_document(
        reader: BobaReportReaderSetV1, document: BobaReportDocumentV1
    ) -> BobaReportAuthorityDomainV1:
        descriptor = next(
            (
                item
                for item in reader.source_descriptors
                if item.producer_module_id == document.producer_module_id
                and item.report_type == document.report_type
            ),
            None,
        )
        return descriptor.authority_domain if descriptor else "unknown"

    def _build_coverage(
        self,
        reader: BobaReportReaderSetV1,
        request: BobaReportReadRequestV1,
        run: BobaReportReadRunV1,
    ) -> BobaReportCoverageV1:
        documents = [
            item
            for item in reader.report_documents
            if item.report_document_id in set(run.report_document_ids)
        ]
        available = sorted({item.report_type for item in documents})
        expected = _expected_types(request.reading_mode)
        missing = [item for item in expected if item not in available]
        stale = sorted({item.report_type for item in documents if item.stale})
        unsupported = sorted(
            {
                item.report_type
                for item in self._references(reader, request)
                if item.report_reference_id in set(run.unsupported_reference_ids)
            }
        )
        unreadable = sorted(
            {
                item.report_type
                for item in self._references(reader, request)
                if item.report_reference_id in set(run.failed_reference_ids)
            }
        )
        domains = sorted({self._authority_for_document(reader, item) for item in documents})
        expected_domains = sorted(
            {
                self._descriptor_for_reference(self._descriptor_map(reader), ref).authority_domain
                for ref in self._references(reader, request)
            }
        )
        missing_domains = [item for item in expected_domains if item not in domains]
        if missing or unreadable:
            status: BobaReportCoverageStatusV1 = "incomplete"
        elif unsupported:
            status = "unsupported"
        elif stale:
            status = "complete_with_limitations"
        else:
            status = "complete"
        reader.signal_usage.coverage_analysis_used = True
        return BobaReportCoverageV1(
            coverage_id=_stable_id(
                "report_coverage", run.read_run_id, request.reading_mode, available, missing, stale
            ),
            project_id=request.project_id,
            reading_mode=request.reading_mode,
            expected_report_types=expected,
            available_report_types=available,
            missing_report_types=missing,
            unreadable_report_types=unreadable,
            stale_report_types=stale,
            unsupported_report_types=unsupported,
            expected_authority_domains=expected_domains,
            covered_authority_domains=domains,
            missing_authority_domains=missing_domains,
            coverage_status=status,
            complete_for_requested_purpose=status == "complete",
            warnings=(
                [
                    "Historical or stale reports remain visible but "
                    "cannot support a current exact action."
                ]
                if stale
                else []
            ),
            limitations=(
                ["Required report categories are missing or unreadable."]
                if missing or unreadable
                else []
            ),
        )

    def _build_open_questions(
        self,
        run: BobaReportReadRunV1,
        coverage: BobaReportCoverageV1,
        contradictions: Sequence[BobaReportContradictionV1],
    ) -> list[BobaReportOpenQuestionV1]:
        questions: list[BobaReportOpenQuestionV1] = []
        if coverage.missing_report_types or coverage.unreadable_report_types:
            questions.append(
                BobaReportOpenQuestionV1(
                    open_question_id=_stable_id(
                        "report_question",
                        run.read_run_id,
                        "missing",
                        coverage.missing_report_types,
                        coverage.unreadable_report_types,
                    ),
                    question_type="missing_evidence",
                    priority=90,
                    bounded_question=(
                        "Which responsible module can provide the missing "
                        "or unreadable report evidence?"
                    ),
                    reason="The requested review lacks required source evidence.",
                    missing_report_types=coverage.missing_report_types
                    + coverage.unreadable_report_types,
                    target_module_id="human_operator",
                )
            )
        if coverage.stale_report_types:
            questions.append(
                BobaReportOpenQuestionV1(
                    open_question_id=_stable_id(
                        "report_question", run.read_run_id, "stale", coverage.stale_report_types
                    ),
                    question_type="stale_report",
                    priority=80,
                    bounded_question=(
                        "Can the responsible producer provide current report "
                        "evidence for this project snapshot?"
                    ),
                    reason=(
                        "Historical or stale reports cannot establish the current project state."
                    ),
                    missing_report_types=coverage.stale_report_types,
                    target_module_id="human_operator",
                )
            )
        for contradiction in contradictions[: max(0, _MAX_QUESTIONS - len(questions))]:
            questions.append(
                BobaReportOpenQuestionV1(
                    open_question_id=_stable_id(
                        "report_question",
                        run.read_run_id,
                        "contradiction",
                        contradiction.contradiction_id,
                    ),
                    question_type="conflicting_decision"
                    if contradiction.contradiction_type.endswith("decision_conflict")
                    else "conflicting_status",
                    priority=95,
                    bounded_question=(
                        "Which source owner or human reviewer should resolve "
                        "this conflicting report evidence?"
                    ),
                    reason=contradiction.bounded_summary,
                    conflicting_finding_ids=contradiction.finding_ids,
                    target_module_id="human_operator",
                )
            )
        return questions[:_MAX_QUESTIONS]

    def _build_handoffs(
        self,
        run: BobaReportReadRunV1,
        coverage: BobaReportCoverageV1,
        questions: Sequence[BobaReportOpenQuestionV1],
        contradictions: Sequence[BobaReportContradictionV1],
        *,
        bundle: BobaReportBundleV1 | None = None,
    ) -> list[BobaReportHandoffV1]:
        handoffs: list[BobaReportHandoffV1] = []
        if run.failed_reference_ids or run.unsupported_reference_ids:
            handoffs.append(
                BobaReportHandoffV1(
                    handoff_id=_stable_id(
                        "report_handoff",
                        run.read_run_id,
                        "malformed_report",
                        run.failed_reference_ids,
                        run.unsupported_reference_ids,
                    ),
                    read_run_id=run.read_run_id,
                    report_bundle_id=bundle.report_bundle_id if bundle else "",
                    target_module_id="validator_runner",
                    reason=(
                        "A registered report was malformed, unsupported, unsafe, "
                        "or failed digest validation."
                    ),
                    blocking_conditions=[
                        "The affected source report was not used by Report Reader."
                    ],
                    prohibited_actions=[
                        "Do not treat an unreadable report as successful validation."
                    ],
                    human_approval_required=True,
                    priority=90,
                )
            )
        if run.stale_reference_ids:
            handoffs.append(
                BobaReportHandoffV1(
                    handoff_id=_stable_id(
                        "report_handoff",
                        run.read_run_id,
                        "stale_state",
                        run.stale_reference_ids,
                    ),
                    read_run_id=run.read_run_id,
                    report_bundle_id=bundle.report_bundle_id if bundle else "",
                    target_module_id="workflow_controller",
                    reason=(
                        "Historical or stale report evidence cannot establish "
                        "the current workflow state."
                    ),
                    blocking_conditions=[
                        "Current-state evidence must come from the responsible producer."
                    ],
                    prohibited_actions=[
                        "Do not authorize workflow continuation from stale evidence."
                    ],
                    human_approval_required=True,
                    priority=80,
                )
            )
        if coverage.missing_report_types or coverage.unreadable_report_types:
            handoffs.append(
                BobaReportHandoffV1(
                    handoff_id=_stable_id("report_handoff", run.read_run_id, "missing_evidence"),
                    read_run_id=run.read_run_id,
                    report_bundle_id=bundle.report_bundle_id if bundle else "",
                    target_module_id="human_operator",
                    reason="Required report evidence is missing, unreadable, or unsupported.",
                    missing_evidence_ids=coverage.missing_evidence_ids,
                    blocking_conditions=["Required source evidence is incomplete."],
                    prohibited_actions=[
                        "Do not treat the bundle as a current-action authorization."
                    ],
                    human_approval_required=True,
                    priority=90,
                )
            )
        if contradictions:
            handoffs.append(
                BobaReportHandoffV1(
                    handoff_id=_stable_id(
                        "report_handoff",
                        run.read_run_id,
                        "contradictions",
                        [item.contradiction_id for item in contradictions],
                    ),
                    read_run_id=run.read_run_id,
                    report_bundle_id=bundle.report_bundle_id if bundle else "",
                    target_module_id="human_operator",
                    reason=(
                        "Source reports conflict; Report Reader retained them "
                        "without resolving them."
                    ),
                    contradiction_ids=[item.contradiction_id for item in contradictions],
                    blocking_conditions=[
                        "Contradictory source evidence requires owner or human resolution."
                    ],
                    prohibited_actions=["Do not average conflicting decisions into a pass."],
                    human_approval_required=True,
                    priority=95,
                )
            )
        if bundle is not None:
            handoffs.append(
                BobaReportHandoffV1(
                    handoff_id=_stable_id(
                        "report_handoff", run.read_run_id, bundle.report_bundle_id, "live_companion"
                    ),
                    read_run_id=run.read_run_id,
                    report_bundle_id=bundle.report_bundle_id,
                    target_module_id="live_companion",
                    reason=(
                        "The bundle contains bounded facts, source assessments, "
                        "interpretations, and open questions for explanation only."
                    ),
                    report_document_ids=bundle.report_document_ids,
                    finding_ids=bundle.finding_ids,
                    evidence_reference_ids=bundle.evidence_reference_ids,
                    contradiction_ids=bundle.contradiction_ids,
                    prohibited_actions=[
                        "Do not execute, approve, resume, upload, or publish from this handoff."
                    ],
                    priority=30,
                )
            )
        return handoffs

    @staticmethod
    def _append_unique_handoffs(
        reader: BobaReportReaderSetV1,
        handoffs: Sequence[BobaReportHandoffV1],
    ) -> None:
        known_handoff_ids = {item.handoff_id for item in reader.handoffs}
        reader.handoffs.extend(
            item for item in handoffs if item.handoff_id not in known_handoff_ids
        )

    @staticmethod
    def _technical_summary(
        run: BobaReportReadRunV1,
        coverage: BobaReportCoverageV1,
        contradictions: Sequence[BobaReportContradictionV1],
        findings: Sequence[BobaReportFindingV1],
    ) -> str:
        return _safe_text(
            f"Read run {run.status}: {len(findings)} source-grounded findings, "
            f"coverage {coverage.coverage_status}, and "
            f"{len(contradictions)} unresolved contradictions. "
            "This is a read-only interpretation and not an "
            "approval, validation pass, or workflow transition.",
            maximum=5_000,
        )

    @staticmethod
    def _easy_summary(
        run: BobaReportReadRunV1,
        coverage: BobaReportCoverageV1,
        contradictions: Sequence[BobaReportContradictionV1],
        findings: Sequence[BobaReportFindingV1],
    ) -> str:
        if contradictions:
            return (
                "BOBA found reports that disagree. Their source owners "
                "or a human reviewer must resolve the conflict."
            )
        if coverage.coverage_status in {"incomplete", "blocked", "unsupported"}:
            return (
                "BOBA read what it safely could, but important report "
                "evidence is missing or unavailable."
            )
        if run.status == "completed_with_limitations":
            return (
                "BOBA read the reports, but some evidence is historical "
                "or stale and cannot prove the current project state."
            )
        if any(item.source_decision == "passed" for item in findings):
            return (
                "A source technical report may have passed its exact check, "
                "but that is not quality approval or workflow permission."
            )
        return "BOBA explained the selected reports without changing their source decisions."

    def _append_incident(
        self,
        reader: BobaReportReaderSetV1,
        run: BobaReportReadRunV1,
        reference: BobaReportReferenceV1,
        incident_type: BobaReportIncidentTypeV1,
        severity: Literal["info", "low", "medium", "high", "critical", "unknown"],
        title: str,
        summary: str,
        *,
        blocked: bool,
    ) -> None:
        fingerprint = _stable_id(
            "report_incident_fingerprint", reference.report_reference_id, incident_type, summary
        )
        existing = next(
            (item for item in reader.incidents if item.repeated_fingerprint == fingerprint), None
        )
        if existing is not None:
            existing.occurrence_count += 1
            return
        reader.incidents.append(
            BobaReportIncidentV1(
                incident_id=_stable_id("report_incident", run.read_run_id, fingerprint),
                read_run_id=run.read_run_id,
                report_reference_id=reference.report_reference_id,
                incident_type=incident_type,
                severity=severity,
                title=_bounded_text(title, maximum=240),
                bounded_summary=_safe_text(summary, maximum=1_600),
                source_module_id=reference.producer_module_id,
                repeated_fingerprint=fingerprint,
                current_action_blocked=blocked,
                recommended_target_module="validator_runner"
                if incident_type in {"malformed_report", "digest_mismatch", "duplicate_json_key"}
                else "human_operator",
                human_review_required=blocked,
            )
        )

    @staticmethod
    def _incident_type_for_error(exc: BaseException) -> BobaReportIncidentTypeV1:
        message = str(exc).casefold()
        if "digest" in message:
            return "digest_mismatch"
        if "project" in message:
            return "project_mismatch"
        if "symlink" in message or "escaped" in message:
            return "symlink_escape"
        if "byte" in message or "over-limit" in message:
            return "oversized_report"
        if "secret" in message:
            return "secret_detected"
        if "scope" in message or "reference" in message:
            return "unsafe_reference"
        return "malformed_report"

    def _append_event(
        self,
        reader: BobaReportReaderSetV1,
        *,
        read_run_id: str,
        event_type: BobaReportEventTypeV1,
        technical_message: str,
        easy_message: str,
        confirmed_fact: str,
        report_reference_id: str = "",
        report_document_id: str = "",
        severity: Literal["info", "warning", "error", "critical", "unknown"] = "info",
        assessment: str = "",
        requires_attention: bool = False,
        progress_current: int | None = None,
        progress_total: int | None = None,
    ) -> BobaReportEventV1:
        sequence = len(reader.events) + 1
        percent = None
        if progress_current is not None and progress_total is not None and progress_total > 0:
            percent = round((progress_current / progress_total) * 100.0, 2)
        event = BobaReportEventV1(
            event_id=_stable_id(
                "report_event", reader.project_id, sequence, read_run_id, event_type
            ),
            read_run_id=read_run_id,
            project_id=reader.project_id,
            sequence=sequence,
            event_type=event_type,
            severity=severity,
            report_reference_id=report_reference_id,
            report_document_id=report_document_id,
            technical_message=_safe_text(technical_message, maximum=1_200),
            easy_message=_safe_text(easy_message, maximum=1_200),
            confirmed_fact=_safe_text(confirmed_fact, maximum=1_200),
            assessment=_safe_text(assessment, maximum=1_200),
            progress_current=progress_current,
            progress_total=progress_total,
            progress_percent=percent,
            requires_attention=requires_attention,
        )
        reader.events.append(event)
        if read_run_id:
            run = next((item for item in reader.read_runs if item.read_run_id == read_run_id), None)
            if run is not None:
                run.event_ids.append(event.event_id)
        return event

    @staticmethod
    def _request_expired(request: BobaReportReadRequestV1) -> bool:
        expires_at = _parse_time(request.expires_at)
        return expires_at is None or expires_at <= datetime.now(UTC)

    def _reusable_run(
        self, reader: BobaReportReaderSetV1, request: BobaReportReadRequestV1
    ) -> BobaReportReadRunV1 | None:
        for run in reversed(reader.read_runs):
            if run.idempotency_key != request.idempotency_key or run.status not in {
                "completed",
                "completed_with_limitations",
            }:
                continue
            documents = [
                item
                for item in reader.report_documents
                if item.report_document_id in set(run.report_document_ids)
            ]
            if not documents:
                continue
            current_digests: list[str] = []
            try:
                for document in documents:
                    reference = self._reference(reader, document)
                    descriptor = self._descriptor_for_reference(
                        self._descriptor_map(reader), reference
                    )
                    current_digests.append(
                        _path_digest(self._resolve_reference(reference, descriptor))
                    )
            except (OSError, ValueError):
                continue
            if current_digests == [item.content_digest for item in documents]:
                return run
        return None

    @staticmethod
    def _descriptor_map(reader: BobaReportReaderSetV1) -> dict[str, BobaReportSourceDescriptorV1]:
        return {item.source_descriptor_id: item for item in reader.source_descriptors}

    @staticmethod
    def _descriptor_for_reference(
        descriptors: Mapping[str, BobaReportSourceDescriptorV1],
        reference: BobaReportReferenceV1,
    ) -> BobaReportSourceDescriptorV1:
        descriptor = descriptors.get(reference.source_descriptor_id)
        if descriptor is None:
            raise UnsafeReportReferenceError(
                "Report reference does not select exactly one fixed source descriptor."
            )
        if (
            descriptor.producer_module_id != reference.producer_module_id
            or descriptor.report_type != reference.report_type
            or descriptor.schema_id != reference.schema_id
            or descriptor.expected_format != reference.format
        ):
            raise UnsafeReportReferenceError(
                "Report reference does not match its fixed source descriptor."
            )
        return descriptor

    @staticmethod
    def _request(reader: BobaReportReaderSetV1, request_id: str) -> BobaReportReadRequestV1:
        request = next(
            (item for item in reader.read_requests if item.read_request_id == request_id), None
        )
        if request is None:
            raise NotFoundError("BOBA Report Reader request was not found.")
        return request

    @staticmethod
    def _run(reader: BobaReportReaderSetV1, run_id: str) -> BobaReportReadRunV1:
        run = next((item for item in reader.read_runs if item.read_run_id == run_id), None)
        if run is None:
            raise NotFoundError("BOBA Report Reader run was not found.")
        return run

    @staticmethod
    def _references(
        reader: BobaReportReaderSetV1, request: BobaReportReadRequestV1
    ) -> list[BobaReportReferenceV1]:
        references: list[BobaReportReferenceV1] = []
        for reference_id in request.report_reference_ids:
            reference = next(
                (
                    item
                    for item in reader.report_references
                    if item.report_reference_id == reference_id
                ),
                None,
            )
            if reference is not None:
                references.append(reference)
        if len(references) != len(request.report_reference_ids):
            raise ValidationError("Report Reader request references are not persisted.")
        return references

    @staticmethod
    def _reference(
        reader: BobaReportReaderSetV1, document: BobaReportDocumentV1
    ) -> BobaReportReferenceV1:
        reference = next(
            (
                item
                for item in reader.report_references
                if item.report_reference_id == document.report_reference_id
            ),
            None,
        )
        if reference is None:
            raise NotFoundError("Report Reader document reference was not found.")
        return reference

    @staticmethod
    def _refresh_summary(reader: BobaReportReaderSetV1) -> None:
        counts = Counter(item.status for item in reader.read_runs)
        incident = max(
            reader.incidents,
            key=lambda item: {
                "critical": 4,
                "high": 3,
                "medium": 2,
                "low": 1,
                "info": 0,
                "unknown": 0,
            }[item.severity],
            default=None,
        )
        reader.reader_summary = BobaReportReaderSummaryV1(
            registry_snapshot_count=len(reader.registry_snapshots),
            registered_source_count=len(reader.source_descriptors),
            available_source_count=sum(
                item.availability == "available" for item in reader.source_descriptors
            ),
            unsupported_source_count=sum(
                item.availability != "available" for item in reader.source_descriptors
            ),
            total_read_request_count=len(reader.read_requests),
            total_read_run_count=len(reader.read_runs),
            completed_read_count=counts["completed"] + counts["completed_with_limitations"],
            incomplete_read_count=counts["incomplete"],
            blocked_read_count=counts["blocked"],
            total_report_document_count=len(reader.report_documents),
            current_report_count=sum(not item.stale for item in reader.report_documents),
            stale_report_count=sum(item.stale for item in reader.report_documents),
            malformed_report_count=sum(
                item.incident_type in {"malformed_report", "duplicate_json_key"}
                for item in reader.incidents
            ),
            unsupported_report_count=sum(
                item.incident_type == "unsupported_format" for item in reader.incidents
            ),
            total_finding_count=len(reader.findings),
            blocking_finding_count=sum(
                item.severity in {"high", "critical"} for item in reader.findings
            ),
            total_contradiction_count=len(reader.contradictions),
            unresolved_contradiction_count=len(reader.contradictions),
            total_bundle_count=len(reader.report_bundles),
            total_open_question_count=len(reader.open_questions),
            highest_priority_incident=incident.incident_id if incident else "",
            current_read_run_id=reader.read_runs[-1].read_run_id if reader.read_runs else "",
            current_report_type=reader.report_documents[-1].report_type
            if reader.report_documents
            else "",
            safest_next_action=(
                "Ask the responsible source module or a human reviewer "
                "to address missing or conflicting evidence."
                if reader.contradictions
                or any(item.status == "incomplete" for item in reader.read_runs)
                else "Inspect original source evidence before any external action."
            ),
            required_human_actions=_unique_texts(
                [
                    item.bounded_question
                    for item in reader.open_questions
                    if item.answer_required_before_action
                ],
                limit=32,
                maximum=600,
            ),
            limitations=[
                "Report Reader does not grant action authority or replace original source evidence."
            ],
        )

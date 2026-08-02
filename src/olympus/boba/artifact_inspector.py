"""Read-only, project-scoped inspection of registered Olympus and BOBA artifacts.

Artifact Inspector intentionally observes exact typed references only.  It does
not discover paths, modify storage, execute validators, decode media, or grant
workflow, quality, safety, or recovery authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from itertools import islice
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore
    from olympus.domain.contracts.storage import StoragePort


BobaArtifactStorageKindV1 = Literal[
    "file",
    "directory",
    "structured_record",
    "event_stream",
    "manifest",
    "virtual_reference",
    "unknown",
]
BobaArtifactAvailabilityV1 = Literal["available", "degraded", "unavailable", "future", "unknown"]
BobaArtifactInspectionModeV1 = Literal[
    "exact_artifact",
    "artifact_group",
    "project_inventory",
    "workflow_stage",
    "selected_clip",
    "rendered_output",
    "recovery_output",
    "accepted_output",
    "report_artifact",
    "validation_evidence",
    "checkpoint_preflight",
    "code_worktree",
    "internal_completion_preflight",
    "historical_inventory",
    "comparison",
    "unknown",
]
BobaArtifactIntegrityStatusV1 = Literal[
    "verified",
    "verified_with_limitations",
    "missing",
    "inaccessible",
    "digest_mismatch",
    "wrong_type",
    "malformed",
    "partial",
    "deeper_validation_required",
    "rights_blocked",
    "unknown",
]
BobaArtifactFreshnessStatusV1 = Literal["current", "historical", "stale", "unknown"]
BobaArtifactProtectionStatusV1 = Literal["protected", "at_risk", "not_applicable", "unknown"]

_DIGEST = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$", re.IGNORECASE)
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[/\\]")
_MAX_REFERENCE_COUNT = 128
_MAX_FILE_BYTES = 32 * 1024 * 1024
_MAX_DIRECTORY_ENTRIES = 256
_MAX_EVENTS = 4096


def _stable_digest(namespace: str, value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{namespace}:{payload}".encode()).hexdigest()


def _stable_id(namespace: str, *parts: object) -> str:
    return f"{namespace}_{_stable_digest(namespace, list(parts))[:24]}"


def _safe_text(value: object, maximum: int = 1_200) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = re.sub(r"[A-Za-z]:\\[^\s\"']+", "[private-path-redacted]", text)
    text = re.sub(r"/(?:home|Users|var|tmp)/[^\s\"']+", "[private-path-redacted]", text)
    return text[:maximum]


def _normalize_reference(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    lowered = normalized.casefold()
    if not normalized or lowered.startswith(("http://", "https://", "file:")):
        raise ValidationError("Artifact references must be registered local relative paths.")
    if (
        normalized.startswith("//")
        or normalized.startswith("/")
        or _WINDOWS_ABSOLUTE.match(normalized)
    ):
        raise ValidationError("Absolute and UNC artifact paths are unavailable.")
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError("Traversal and malformed artifact references are unavailable.")
    if any("*" in part or "?" in part or "[" in part for part in path.parts):
        raise ValidationError("Artifact references cannot include glob syntax.")
    return path.as_posix()


def sanitize_artifact_export(value: Any) -> Any:
    """Return bounded metadata only; raw media, logs, secrets, and paths stay hidden."""

    blocked = {
        "raw_body",
        "content",
        "data",
        "path",
        "absolute_path",
        "resolved_path",
        "stdout",
        "stderr",
        "traceback",
        "token",
        "secret",
        "password",
        "credential",
        "authorization",
        "cookie",
        "media_bytes",
        "source_code",
    }
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:512]:
            key = _safe_text(raw_key, 120)
            if not key:
                continue
            if key.casefold() in blocked or re.search(
                r"token|secret|password|credential", key, re.I
            ):
                result[key] = "[redacted]"
            else:
                result[key] = sanitize_artifact_export(raw_value)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_artifact_export(item) for item in list(value)[:2048]]
    if isinstance(value, str):
        return _safe_text(value, 4000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value, 800)


def _sanitized_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_artifact_export(value)
    if not isinstance(sanitized, dict):
        raise ValidationError("Artifact Inspector export must remain a JSON object.")
    return {str(key): item for key, item in sanitized.items()}


class BobaArtifactRegistrySnapshotV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    registry_version: str = Field(default="1", min_length=1, max_length=80)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    artifact_type_ids: list[str] = Field(default_factory=list, max_length=128)
    owner_module_ids: list[str] = Field(default_factory=list, max_length=128)
    available_artifact_type_ids: list[str] = Field(default_factory=list, max_length=128)
    degraded_artifact_type_ids: list[str] = Field(default_factory=list, max_length=128)
    unavailable_artifact_type_ids: list[str] = Field(default_factory=list, max_length=128)
    future_artifact_type_ids: list[str] = Field(default_factory=list, max_length=128)
    registry_digest: str = Field(min_length=64, max_length=64)
    immutable: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaArtifactTypeDescriptorV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_type_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)
    owner_module_id: str = Field(min_length=1, max_length=160)
    artifact_category: str = Field(min_length=1, max_length=100)
    storage_kind: BobaArtifactStorageKindV1
    expected_formats: list[str] = Field(default_factory=list, max_length=16)
    expected_storage_scopes: list[str] = Field(default_factory=list, max_length=16)
    expected_schema_ids: list[str] = Field(default_factory=list, max_length=16)
    supported_schema_versions: list[str] = Field(default_factory=lambda: ["1"], max_length=16)
    identity_fields: list[str] = Field(default_factory=list, max_length=24)
    required_digest_type: str = Field(default="sha256", max_length=32)
    mutable_during_creation: bool = False
    immutable_after_completion: bool = True
    source_media: bool = False
    generated_media: bool = False
    accepted_output_capable: bool = False
    report_artifact: bool = False
    checkpoint_artifact: bool = False
    code_artifact: bool = False
    rights_sensitive: bool = False
    safety_sensitive: bool = False
    quality_sensitive: bool = False
    workflow_sensitive: bool = False
    content_read_allowed: bool = True
    lightweight_signature_check_allowed: bool = True
    full_digest_recomputation_allowed: bool = True
    directory_inventory_allowed: bool = False
    required_deeper_validator_ids: list[str] = Field(default_factory=list, max_length=16)
    maximum_file_bytes: int = Field(default=_MAX_FILE_BYTES, ge=0, le=_MAX_FILE_BYTES)
    maximum_directory_entries: int = Field(default=_MAX_DIRECTORY_ENTRIES, ge=0, le=4096)
    availability: BobaArtifactAvailabilityV1 = "available"
    storage_domain: Literal["boba", "project_storage", "unknown"] = "unknown"
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaArtifactReferenceV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    source_id: str = Field(min_length=1, max_length=512)
    workflow_run_id: str = Field(default="", max_length=180)
    stage_instance_id: str = Field(default="", max_length=180)
    clip_id: str = Field(default="", max_length=180)
    output_id: str = Field(default="", max_length=180)
    owner_module_id: str = Field(min_length=1, max_length=160)
    producer_record_id: str = Field(default="", max_length=180)
    artifact_type_id: str = Field(min_length=1, max_length=160)
    schema_id: str = Field(default="", max_length=180)
    schema_version: str = Field(default="1", max_length=80)
    expected_digest: str = Field(default="", max_length=72)
    expected_digest_type: str = Field(default="sha256", max_length=32)
    expected_size_bytes: int | None = Field(default=None, ge=0, le=_MAX_FILE_BYTES)
    sanitized_storage_reference: str = Field(min_length=1, max_length=500)
    storage_kind: BobaArtifactStorageKindV1
    immutable: bool = True
    source_media: bool = False
    source_media_read_only: bool = True
    accepted_output: bool = False
    generated_output: bool = False
    required: bool = True
    historical: bool = False
    rights_status: str = Field(default="unknown", max_length=120)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    completed_at: str = Field(default="", max_length=80)
    declared_lineage: list[dict[str, str]] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("sanitized_storage_reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        return _normalize_reference(value)

    @field_validator("expected_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if value and not _DIGEST.fullmatch(value):
            raise ValueError("Expected artifact digest must be SHA-256 hex.")
        return value.casefold()


class BobaArtifactInspectionRequestV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inspection_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    source_id: str = Field(min_length=1, max_length=512)
    requested_by_module: str = Field(min_length=1, max_length=160)
    inspection_mode: BobaArtifactInspectionModeV1 = "exact_artifact"
    artifact_reference_ids: list[str] = Field(min_length=1, max_length=_MAX_REFERENCE_COUNT)
    workflow_run_id: str = Field(default="", max_length=180)
    project_snapshot_digest: str = Field(default="", max_length=72)
    maximum_total_bytes: int = Field(default=_MAX_FILE_BYTES, ge=1024, le=_MAX_FILE_BYTES)
    maximum_artifact_count: int = Field(
        default=_MAX_REFERENCE_COUNT,
        ge=1,
        le=_MAX_REFERENCE_COUNT,
    )
    inspect_content: bool = False
    recompute_digests: bool = True
    include_inventory: bool = True
    include_lineage: bool = True
    expires_at: str = Field(
        default_factory=lambda: (datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    request_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=180)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaArtifactInspectionRunV1(BobaContract):
    model_config = ConfigDict(extra="forbid")

    inspection_run_id: str = Field(min_length=1, max_length=180)
    inspection_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    status: Literal["pending", "running", "completed", "completed_with_limitations", "failed"] = (
        "pending"
    )
    started_at: str = Field(default_factory=now_iso, max_length=80)
    completed_at: str = Field(default="", max_length=80)
    artifact_snapshot_ids: list[str] = Field(default_factory=list, max_length=512)
    observation_ids: list[str] = Field(default_factory=list, max_length=512)
    integrity_assessment_ids: list[str] = Field(default_factory=list, max_length=512)
    freshness_assessment_ids: list[str] = Field(default_factory=list, max_length=512)
    protection_assessment_ids: list[str] = Field(default_factory=list, max_length=512)
    finding_ids: list[str] = Field(default_factory=list, max_length=1024)
    incident_ids: list[str] = Field(default_factory=list, max_length=512)
    handoff_ids: list[str] = Field(default_factory=list, max_length=512)
    coverage_id: str = Field(default="", max_length=180)
    reused_existing_result: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=128)


class BobaArtifactSnapshotV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_snapshot_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    artifact_reference_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    exists: bool
    accessible: bool
    observed_storage_kind: BobaArtifactStorageKindV1 = "unknown"
    observed_format: str = Field(default="unknown", max_length=80)
    observed_size_bytes: int | None = Field(default=None, ge=0)
    observed_modified_at: str = Field(default="", max_length=80)
    persisted_digest: str = Field(default="", max_length=72)
    recomputed_digest: str = Field(default="", max_length=72)
    recomputed_digest_used: bool = False
    changed_during_read: bool = False
    partial_write_suspected: bool = False
    lightweight_structure: Literal["valid", "malformed", "not_checked", "unknown"] = "unknown"
    bounded_directory_entries: list[str] = Field(
        default_factory=list, max_length=_MAX_DIRECTORY_ENTRIES
    )
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaArtifactObservationV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    artifact_reference_id: str = Field(min_length=1, max_length=180)
    observation_type: str = Field(min_length=1, max_length=120)
    confirmed_fact: str = Field(default="", max_length=1600)
    source_assessment: str = Field(default="", max_length=1600)
    inspector_interpretation: str = Field(default="", max_length=1600)
    created_at: str = Field(default_factory=now_iso, max_length=80)


class BobaArtifactIntegrityAssessmentV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    integrity_assessment_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    artifact_reference_id: str = Field(min_length=1, max_length=180)
    status: BobaArtifactIntegrityStatusV1
    persisted_digest_status: Literal["match", "mismatch", "missing", "not_checked"] = "not_checked"
    recomputed_digest_status: Literal["match", "mismatch", "not_recomputed", "blocked"] = (
        "not_recomputed"
    )
    requires_deeper_validation: bool = False
    bounded_explanation: str = Field(default="", max_length=1600)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaArtifactFreshnessAssessmentV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    freshness_assessment_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    artifact_reference_id: str = Field(min_length=1, max_length=180)
    status: BobaArtifactFreshnessStatusV1
    current_project_snapshot: bool | None = None
    current_workflow_revision: bool | None = None
    current_producer_record: bool | None = None
    bounded_explanation: str = Field(default="", max_length=1200)


class BobaArtifactProtectionAssessmentV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protection_assessment_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    artifact_reference_id: str = Field(min_length=1, max_length=180)
    source_media_status: BobaArtifactProtectionStatusV1 = "not_applicable"
    accepted_output_status: BobaArtifactProtectionStatusV1 = "not_applicable"
    immutable_status: BobaArtifactProtectionStatusV1 = "unknown"
    bounded_explanation: str = Field(default="", max_length=1200)


class BobaArtifactLineageEdgeV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lineage_edge_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    parent_artifact_reference_id: str = Field(min_length=1, max_length=180)
    child_artifact_reference_id: str = Field(min_length=1, max_length=180)
    relationship: Literal[
        "produced_from",
        "transformed_from",
        "recovered_from",
        "validated_by",
        "supersedes",
        "unknown",
    ] = "unknown"
    source_declared: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=16)


class BobaArtifactInventoryV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    artifact_reference_ids: list[str] = Field(default_factory=list, max_length=512)
    present_reference_ids: list[str] = Field(default_factory=list, max_length=512)
    missing_required_reference_ids: list[str] = Field(default_factory=list, max_length=512)
    missing_optional_reference_ids: list[str] = Field(default_factory=list, max_length=512)
    orphan_candidate_reference_ids: list[str] = Field(default_factory=list, max_length=512)
    inventory_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaArtifactComparisonV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    comparison_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    left_artifact_reference_id: str = Field(min_length=1, max_length=180)
    right_artifact_reference_id: str = Field(min_length=1, max_length=180)
    comparison_kind: Literal[
        "digest", "identity", "recovery", "checkpoint", "accepted_output", "unknown"
    ] = "unknown"
    result: Literal["match", "different", "inconclusive", "conflict"] = "inconclusive"
    bounded_explanation: str = Field(default="", max_length=1200)


class BobaArtifactFindingV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    artifact_reference_id: str = Field(default="", max_length=180)
    category: str = Field(min_length=1, max_length=120)
    severity: Literal["info", "low", "medium", "high", "critical", "unknown"] = "info"
    confirmed_fact: str = Field(default="", max_length=1600)
    assessment: str = Field(default="", max_length=1600)
    requires_attention: bool = False


class BobaArtifactCoverageV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    coverage_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    status: Literal["complete", "complete_with_limitations", "incomplete", "blocked"]
    requested_artifact_count: int = Field(ge=0)
    inspected_artifact_count: int = Field(ge=0)
    missing_required_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaArtifactIncidentV1(BobaContract):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    artifact_reference_id: str = Field(default="", max_length=180)
    incident_type: str = Field(min_length=1, max_length=120)
    severity: Literal["info", "low", "medium", "high", "critical", "unknown"] = "medium"
    bounded_summary: str = Field(default="", max_length=1600)
    repeated_fingerprint: str = Field(min_length=1, max_length=180)
    occurrence_count: int = Field(default=1, ge=1)
    created_at: str = Field(default_factory=now_iso, max_length=80)


class BobaArtifactEventV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(default="", max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=120)
    technical_message: str = Field(default="", max_length=1600)
    easy_message: str = Field(default="", max_length=1600)
    confirmed_fact: str = Field(default="", max_length=1600)
    severity: Literal["info", "warning", "error", "critical", "unknown"] = "info"
    requires_attention: bool = False
    progress_current: int | None = Field(default=None, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    progress_percent: float | None = Field(default=None, ge=0, le=100)
    created_at: str = Field(default_factory=now_iso, max_length=80)


class BobaArtifactHandoffV1(BobaContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    handoff_id: str = Field(min_length=1, max_length=180)
    inspection_run_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=180)
    target_module_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(default="", max_length=1600)
    artifact_reference_ids: list[str] = Field(default_factory=list, max_length=128)
    artifact_snapshot_ids: list[str] = Field(default_factory=list, max_length=128)
    observed_digests: list[str] = Field(default_factory=list, max_length=128)
    required_validator_ids: list[str] = Field(default_factory=list, max_length=32)
    blocking_conditions: list[str] = Field(default_factory=list, max_length=32)
    protected_state_requirements: list[str] = Field(default_factory=list, max_length=32)
    automatic_execution: Literal[False] = False
    requires_human_or_owner_review: bool = False


class BobaArtifactInspectorSummaryV1(BobaContract):
    model_config = ConfigDict(extra="forbid")

    registered_artifact_type_count: int = 0
    available_artifact_type_count: int = 0
    total_reference_count: int = 0
    total_run_count: int = 0
    verified_count: int = 0
    missing_count: int = 0
    partial_count: int = 0
    protected_count: int = 0
    current_inventory_id: str = Field(default="", max_length=180)
    safest_next_action: str = Field(
        default="Inspect exact source evidence without changing it.", max_length=1200
    )
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaArtifactInspectorSignalUsageV1(BobaContract):
    model_config = ConfigDict(extra="forbid")

    trusted_artifact_registry_used: bool = False
    exact_reference_validation_used: bool = False
    local_metadata_inspection_used: bool = False
    streaming_digest_used: bool = False
    directory_inventory_used: bool = False
    arbitrary_path_scanning_used: Literal[False] = False
    arbitrary_glob_used: Literal[False] = False
    dynamic_resolver_loading_used: Literal[False] = False
    arbitrary_function_invocation_used: Literal[False] = False
    artifact_modification_used: Literal[False] = False
    artifact_move_used: Literal[False] = False
    artifact_copy_used: Literal[False] = False
    artifact_deletion_used: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_outputs_modified: Literal[False] = False
    command_execution_used: Literal[False] = False
    shell_execution_used: Literal[False] = False
    git_execution_used: Literal[False] = False
    ffmpeg_execution_used: Literal[False] = False
    media_decoding_used: Literal[False] = False
    ocr_used: Literal[False] = False
    validator_execution_used: Literal[False] = False
    workflow_transition_used: Literal[False] = False
    quality_authorization_used: Literal[False] = False
    safety_authorization_used: Literal[False] = False
    checkpoint_restore_used: Literal[False] = False
    approval_creation_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_used: Literal[False] = False
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


class BobaArtifactInspectorSetV1(BobaContract):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=180)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    registry_snapshots: list[BobaArtifactRegistrySnapshotV1] = Field(
        default_factory=list, max_length=32
    )
    artifact_type_descriptors: list[BobaArtifactTypeDescriptorV1] = Field(
        default_factory=list, max_length=128
    )
    artifact_references: list[BobaArtifactReferenceV1] = Field(
        default_factory=list, max_length=2048
    )
    inspection_requests: list[BobaArtifactInspectionRequestV1] = Field(
        default_factory=list, max_length=512
    )
    inspection_runs: list[BobaArtifactInspectionRunV1] = Field(default_factory=list, max_length=512)
    artifact_snapshots: list[BobaArtifactSnapshotV1] = Field(default_factory=list, max_length=4096)
    observations: list[BobaArtifactObservationV1] = Field(default_factory=list, max_length=4096)
    integrity_assessments: list[BobaArtifactIntegrityAssessmentV1] = Field(
        default_factory=list, max_length=4096
    )
    freshness_assessments: list[BobaArtifactFreshnessAssessmentV1] = Field(
        default_factory=list, max_length=4096
    )
    protection_assessments: list[BobaArtifactProtectionAssessmentV1] = Field(
        default_factory=list, max_length=4096
    )
    lineage_edges: list[BobaArtifactLineageEdgeV1] = Field(default_factory=list, max_length=4096)
    inventories: list[BobaArtifactInventoryV1] = Field(default_factory=list, max_length=512)
    comparisons: list[BobaArtifactComparisonV1] = Field(default_factory=list, max_length=2048)
    findings: list[BobaArtifactFindingV1] = Field(default_factory=list, max_length=4096)
    coverage_records: list[BobaArtifactCoverageV1] = Field(default_factory=list, max_length=512)
    incidents: list[BobaArtifactIncidentV1] = Field(default_factory=list, max_length=2048)
    events: list[BobaArtifactEventV1] = Field(default_factory=list, max_length=_MAX_EVENTS)
    handoffs: list[BobaArtifactHandoffV1] = Field(default_factory=list, max_length=2048)
    inspector_summary: BobaArtifactInspectorSummaryV1 = Field(
        default_factory=BobaArtifactInspectorSummaryV1
    )
    signal_usage: BobaArtifactInspectorSignalUsageV1 = Field(
        default_factory=BobaArtifactInspectorSignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Artifact Inspector is read-only and never authorizes workflow, "
            "quality, safety, validation, or recovery actions.",
            "Matching bytes establish equality only; they do not establish media "
            "quality or workflow permission.",
        ],
        max_length=64,
    )


def _descriptor(
    artifact_type_id: str,
    display_name: str,
    owner_module_id: str,
    artifact_category: str,
    storage_kind: BobaArtifactStorageKindV1,
    scope: str,
    *,
    storage_domain: Literal["boba", "project_storage", "unknown"],
    formats: Sequence[str] = (),
    availability: BobaArtifactAvailabilityV1 = "available",
    generated_media: bool = False,
    report_artifact: bool = False,
    checkpoint_artifact: bool = False,
    source_media: bool = False,
    accepted_output_capable: bool = False,
    rights_sensitive: bool = False,
    content_read_allowed: bool = True,
    digest_allowed: bool = True,
    validators: Sequence[str] = (),
) -> BobaArtifactTypeDescriptorV1:
    return BobaArtifactTypeDescriptorV1(
        artifact_type_id=artifact_type_id,
        display_name=display_name,
        owner_module_id=owner_module_id,
        artifact_category=artifact_category,
        storage_kind=storage_kind,
        expected_formats=list(formats),
        expected_storage_scopes=[scope],
        expected_schema_ids=[],
        identity_fields=["project_id", "owner_module_id", "producer_record_id", "artifact_type_id"],
        generated_media=generated_media,
        report_artifact=report_artifact,
        checkpoint_artifact=checkpoint_artifact,
        source_media=source_media,
        accepted_output_capable=accepted_output_capable,
        rights_sensitive=rights_sensitive,
        content_read_allowed=content_read_allowed,
        full_digest_recomputation_allowed=digest_allowed,
        required_deeper_validator_ids=list(validators),
        availability=availability,
        storage_domain=storage_domain,
        limitations=["Descriptor is source-code fixed; request data cannot add paths or types."],
    )


def build_fixed_artifact_type_registry() -> tuple[
    BobaArtifactRegistrySnapshotV1, list[BobaArtifactTypeDescriptorV1]
]:
    """Build the deterministic registry from real current Olympus artifact paths."""

    descriptors = [
        _descriptor(
            "render_manifest",
            "Render Manifest",
            "rendering",
            "rendering_manifest",
            "manifest",
            "render/{project_id}/run/index.json",
            storage_domain="project_storage",
            formats=("json",),
            validators=("render_manifest_contract",),
        ),
        _descriptor(
            "rendered_output",
            "Rendered MP4",
            "rendering",
            "rendered_output",
            "file",
            "render/{project_id}/clips/{clip_id}.mp4",
            storage_domain="project_storage",
            formats=("mp4",),
            generated_media=True,
            accepted_output_capable=True,
            validators=("rendered_output_media",),
        ),
        _descriptor(
            "report_reader_state",
            "Report Reader State",
            "report_reader",
            "report",
            "structured_record",
            "projects/{project_id}/report_reader/index.json",
            storage_domain="boba",
            formats=("json",),
            report_artifact=True,
        ),
        _descriptor(
            "validator_runner_state",
            "Validator Runner State",
            "validator_runner",
            "validation_result",
            "structured_record",
            "projects/{project_id}/validator_runner/index.json",
            storage_domain="boba",
            formats=("json",),
            validators=("validator_runner_contract",),
        ),
        _descriptor(
            "workflow_controller_state",
            "Workflow Controller State",
            "workflow_controller",
            "workflow_state",
            "structured_record",
            "projects/{project_id}/workflow_controller/index.json",
            storage_domain="boba",
            formats=("json",),
            validators=("workflow_state_contract",),
        ),
        _descriptor(
            "safety_decision",
            "Safety Decision",
            "safety_gate",
            "safety_decision",
            "structured_record",
            "projects/{project_id}/safety_gate/index.json",
            storage_domain="boba",
            formats=("json",),
            content_read_allowed=False,
        ),
        _descriptor(
            "validation_event_stream",
            "Validation Event Stream",
            "validator_runner",
            "event_stream",
            "event_stream",
            "projects/{project_id}/validator_runner/runs/{producer_record_id}/events.jsonl",
            storage_domain="boba",
            formats=("jsonl",),
        ),
        _descriptor(
            "report_event_stream",
            "Report Reader Event Stream",
            "report_reader",
            "event_stream",
            "event_stream",
            "projects/{project_id}/report_reader/runs/{producer_record_id}/events.jsonl",
            storage_domain="boba",
            formats=("jsonl",),
            report_artifact=True,
        ),
        _descriptor(
            "source_media",
            "Source Media",
            "ingestion",
            "source_media",
            "file",
            "projects/{project_id}/source/{producer_record_id}.mp4",
            storage_domain="project_storage",
            formats=("mp4", "mov", "webm"),
            availability="degraded",
            source_media=True,
            rights_sensitive=True,
            content_read_allowed=False,
            digest_allowed=False,
        ),
        _descriptor(
            "accepted_output",
            "Accepted Output",
            "output_quality_reviewer",
            "accepted_output",
            "file",
            "render/{project_id}/clips/{clip_id}.mp4",
            storage_domain="project_storage",
            formats=("mp4",),
            availability="degraded",
            generated_media=True,
            accepted_output_capable=True,
            validators=("rendered_output_media",),
        ),
        _descriptor(
            "checkpoint_manifest",
            "Checkpoint Manifest",
            "checkpoint_recovery_manager",
            "checkpoint_manifest",
            "manifest",
            "checkpoints/{project_id}/{producer_record_id}/index.json",
            storage_domain="project_storage",
            formats=("json",),
            availability="future",
            checkpoint_artifact=True,
        ),
        _descriptor(
            "code_worktree_manifest",
            "Code Worktree Manifest",
            "code_surgeon",
            "code_worktree_manifest",
            "manifest",
            "projects/{project_id}/code_surgeon/{producer_record_id}/index.json",
            storage_domain="boba",
            formats=("json",),
            availability="future",
            checkpoint_artifact=False,
        ),
    ]
    ids = [item.artifact_type_id for item in descriptors]
    if len(ids) != len(set(ids)):
        raise ValidationError("Duplicate Artifact Inspector artifact-type descriptor.")
    digest = _stable_digest(
        "boba_artifact_registry_v1", [item.model_dump(mode="json") for item in descriptors]
    )
    snapshot = BobaArtifactRegistrySnapshotV1(
        registry_snapshot_id=_stable_id("artifact_registry", digest),
        artifact_type_ids=ids,
        owner_module_ids=sorted({item.owner_module_id for item in descriptors}),
        available_artifact_type_ids=[
            item.artifact_type_id for item in descriptors if item.availability == "available"
        ],
        degraded_artifact_type_ids=[
            item.artifact_type_id for item in descriptors if item.availability == "degraded"
        ],
        unavailable_artifact_type_ids=[
            item.artifact_type_id for item in descriptors if item.availability == "unavailable"
        ],
        future_artifact_type_ids=[
            item.artifact_type_id for item in descriptors if item.availability == "future"
        ],
        registry_digest=digest,
        limitations=[
            "Future and degraded descriptors remain unavailable for unsupported inspections."
        ],
    )
    return snapshot, descriptors


def build_fixed_artifact_resolver_registry() -> dict[str, str]:
    return {"boba_project_store": "boba", "project_storage": "project_storage"}


class BobaArtifactInspectorV1:
    """Inspect only fixed, exact project-scoped artifact references."""

    def __init__(self, store: BobaMemoryStore, storage: StoragePort | None = None) -> None:
        self.store = store
        self.storage = storage

    def _inspector(
        self, project_id: str, *, source_id: str | None = None
    ) -> BobaArtifactInspectorSetV1:
        existing = self.store.load_boba_artifact_inspector(project_id)
        if existing is not None:
            return existing
        if not source_id:
            raise NotFoundError("BOBA Artifact Inspector is unavailable for this project.")
        created = BobaArtifactInspectorSetV1(project_id=project_id, source_id=source_id)
        self.store.save_boba_artifact_inspector(created)
        return created

    def build_artifact_registry(
        self, project_id: str, *, source_id: str
    ) -> BobaArtifactRegistrySnapshotV1:
        inspector = self._inspector(project_id, source_id=source_id)
        snapshot, descriptors = build_fixed_artifact_type_registry()
        if not any(
            item.registry_digest == snapshot.registry_digest
            for item in inspector.registry_snapshots
        ):
            inspector.registry_snapshots.append(snapshot)
            inspector.artifact_type_descriptors = descriptors
        inspector.signal_usage.trusted_artifact_registry_used = True
        self._refresh_summary(inspector)
        self.store.save_boba_artifact_inspector(inspector)
        return snapshot

    def inspect_artifact_registry(
        self, project_id: str, *, source_id: str | None = None
    ) -> dict[str, Any]:
        inspector = self._inspector(project_id, source_id=source_id)
        if not inspector.registry_snapshots:
            self.build_artifact_registry(project_id, source_id=inspector.source_id)
            inspector = self._inspector(project_id)
        snapshot = inspector.registry_snapshots[-1]
        return {
            "schema_version": "boba_artifact_inspector_registry_v1",
            "project_id": project_id,
            "registry_snapshot": snapshot.model_dump(mode="json"),
            "artifact_types": [
                item.model_dump(mode="json") for item in inspector.artifact_type_descriptors
            ],
            "resolver_registry": build_fixed_artifact_resolver_registry(),
            "arbitrary_path_scanning_used": False,
            "dynamic_resolver_loading_used": False,
            "network_used": False,
        }

    def create_inspection_request(
        self,
        project_id: str,
        *,
        source_id: str,
        requested_by_module: str,
        inspection_mode: BobaArtifactInspectionModeV1,
        artifact_references: Sequence[Mapping[str, Any]],
        workflow_run_id: str = "",
        project_snapshot_digest: str = "",
        inspect_content: bool = False,
        recompute_digests: bool = True,
        include_inventory: bool = True,
        include_lineage: bool = True,
    ) -> BobaArtifactInspectionRequestV1:
        if not artifact_references or len(artifact_references) > _MAX_REFERENCE_COUNT:
            raise ValidationError("Inspection requires one to 128 exact artifact references.")
        inspector = self._inspector(project_id, source_id=source_id)
        if not inspector.registry_snapshots:
            self.build_artifact_registry(project_id, source_id=source_id)
            inspector = self._inspector(project_id)
        references = self._build_references(inspector, project_id, source_id, artifact_references)
        digest_payload = {
            "project_id": project_id,
            "mode": inspection_mode,
            "workflow_run_id": workflow_run_id,
            "project_snapshot_digest": project_snapshot_digest,
            "references": [
                item.model_dump(mode="json", exclude={"created_at", "warnings"})
                for item in references
            ],
            "inspect_content": inspect_content,
            "recompute_digests": recompute_digests,
            "include_inventory": include_inventory,
            "include_lineage": include_lineage,
        }
        digest = _stable_digest("artifact_inspection_request", digest_payload)
        existing = next(
            (item for item in inspector.inspection_requests if item.request_digest == digest), None
        )
        if existing is not None:
            return existing
        request = BobaArtifactInspectionRequestV1(
            inspection_request_id=_stable_id("artifact_inspection_request", project_id, digest),
            project_id=project_id,
            source_id=source_id,
            requested_by_module=requested_by_module,
            inspection_mode=inspection_mode,
            artifact_reference_ids=[item.artifact_reference_id for item in references],
            workflow_run_id=workflow_run_id,
            project_snapshot_digest=project_snapshot_digest,
            inspect_content=inspect_content,
            recompute_digests=recompute_digests,
            include_inventory=include_inventory,
            include_lineage=include_lineage,
            request_digest=digest,
            idempotency_key=_stable_id("artifact_inspection_idempotency", project_id, digest),
        )
        inspector.artifact_references.extend(
            item
            for item in references
            if item.artifact_reference_id
            not in {existing.artifact_reference_id for existing in inspector.artifact_references}
        )
        inspector.inspection_requests.append(request)
        self._event(
            inspector,
            "request_created",
            "Exact artifact inspection request created.",
            "BOBA will inspect only the registered artifacts.",
        )
        self._refresh_summary(inspector)
        self.store.save_boba_artifact_inspector(inspector)
        return request

    def validate_artifact_references(
        self, project_id: str, inspection_request_id: str
    ) -> dict[str, Any]:
        inspector = self._inspector(project_id)
        request = self._request(inspector, inspection_request_id)
        references = self._references(inspector, request)
        results: list[dict[str, Any]] = []
        for reference in references:
            try:
                descriptor = self._descriptor(inspector, reference.artifact_type_id)
                path = self._resolve(reference, descriptor)
                results.append(
                    {
                        "artifact_reference_id": reference.artifact_reference_id,
                        "valid": True,
                        "storage_kind": descriptor.storage_kind,
                        "exists": path.exists(),
                    }
                )
            except (OSError, ValidationError, ValueError) as exc:
                results.append(
                    {
                        "artifact_reference_id": reference.artifact_reference_id,
                        "valid": False,
                        "reason": _safe_text(exc),
                    }
                )
        inspector.signal_usage.exact_reference_validation_used = True
        self._event(
            inspector,
            "references_validated",
            "Registered artifact references were scope checked.",
            "BOBA confirmed which exact local artifacts are safe to inspect.",
        )
        self.store.save_boba_artifact_inspector(inspector)
        return {
            "project_id": project_id,
            "inspection_request_id": inspection_request_id,
            "references": results,
        }

    def inspect_artifacts(
        self, project_id: str, inspection_request_id: str
    ) -> BobaArtifactInspectionRunV1:
        inspector = self._inspector(project_id)
        request = self._request(inspector, inspection_request_id)
        reusable = next(
            (
                item
                for item in reversed(inspector.inspection_runs)
                if item.inspection_request_id == request.inspection_request_id
                and item.status in {"completed", "completed_with_limitations"}
                and self._run_is_current(inspector, item)
            ),
            None,
        )
        if reusable is not None:
            return reusable.model_copy(update={"reused_existing_result": True})
        run = BobaArtifactInspectionRunV1(
            inspection_run_id=_stable_id(
                "artifact_inspection_run", project_id, request.idempotency_key, str(uuid4())
            ),
            inspection_request_id=request.inspection_request_id,
            project_id=project_id,
            status="running",
        )
        inspector.inspection_runs.append(run)
        references = self._references(inspector, request)
        remaining_digest_bytes = request.maximum_total_bytes
        for position, reference in enumerate(references, start=1):
            snapshot, integrity, freshness, protection, findings, incidents = (
                self._inspect_reference(
                    inspector,
                    run,
                    request,
                    reference,
                    remaining_digest_bytes,
                )
            )
            if snapshot.recomputed_digest_used and snapshot.observed_size_bytes is not None:
                remaining_digest_bytes = max(
                    0,
                    remaining_digest_bytes - snapshot.observed_size_bytes,
                )
            inspector.artifact_snapshots.append(snapshot)
            inspector.integrity_assessments.append(integrity)
            inspector.freshness_assessments.append(freshness)
            inspector.protection_assessments.append(protection)
            inspector.findings.extend(findings)
            inspector.incidents.extend(incidents)
            run.artifact_snapshot_ids.append(snapshot.artifact_snapshot_id)
            run.integrity_assessment_ids.append(integrity.integrity_assessment_id)
            run.freshness_assessment_ids.append(freshness.freshness_assessment_id)
            run.protection_assessment_ids.append(protection.protection_assessment_id)
            run.finding_ids.extend(item.finding_id for item in findings)
            run.incident_ids.extend(item.incident_id for item in incidents)
            observation = BobaArtifactObservationV1(
                observation_id=_stable_id(
                    "artifact_observation", run.inspection_run_id, reference.artifact_reference_id
                ),
                inspection_run_id=run.inspection_run_id,
                artifact_reference_id=reference.artifact_reference_id,
                observation_type="artifact_snapshot",
                confirmed_fact=(
                    "Artifact presence is "
                    f"{snapshot.exists}; observed storage kind is "
                    f"{snapshot.observed_storage_kind}."
                ),
                source_assessment=integrity.bounded_explanation,
                inspector_interpretation=(
                    "Artifact Inspector recorded the observation without changing the "
                    "artifact or its owner decision."
                ),
            )
            inspector.observations.append(observation)
            run.observation_ids.append(observation.observation_id)
            self._event(
                inspector,
                "artifact_inspected",
                "Registered artifact inspection completed.",
                "BOBA inspected one registered artifact without changing it.",
                run.inspection_run_id,
                position,
                len(references),
            )
        if request.include_lineage:
            edges = self._lineage(inspector, run, references)
            inspector.lineage_edges.extend(edges)
        if request.include_inventory:
            inventory = self._inventory(inspector, run, references)
            inspector.inventories.append(inventory)
        coverage = self._coverage(run, references, inspector)
        inspector.coverage_records.append(coverage)
        run.coverage_id = coverage.coverage_id
        handoffs = self._handoffs(inspector, run, references)
        inspector.handoffs.extend(handoffs)
        run.handoff_ids.extend(item.handoff_id for item in handoffs)
        run.status = "completed" if coverage.status == "complete" else "completed_with_limitations"
        run.completed_at = now_iso()
        self._event(
            inspector,
            "inspection_completed",
            "Read-only artifact inspection completed.",
            "BOBA finished checking the registered artifacts without changing them.",
            run.inspection_run_id,
            len(references),
            len(references),
        )
        self._refresh_summary(inspector)
        self.store.save_boba_artifact_inspector(inspector)
        return run

    def inspect_run(self, project_id: str, inspection_run_id: str) -> dict[str, Any]:
        inspector = self._inspector(project_id)
        run = self._run(inspector, inspection_run_id)
        snapshot_ids = set(run.artifact_snapshot_ids)
        reference_ids = {
            item.artifact_reference_id
            for item in inspector.artifact_snapshots
            if item.artifact_snapshot_id in snapshot_ids
        }
        return _sanitized_mapping(
            {
                "schema_version": "boba_artifact_inspection_run_v1",
                "project_id": project_id,
                "run": run.model_dump(mode="json"),
                "snapshots": [
                    item.model_dump(mode="json")
                    for item in inspector.artifact_snapshots
                    if item.artifact_snapshot_id in snapshot_ids
                ],
                "integrity": [
                    item.model_dump(mode="json")
                    for item in inspector.integrity_assessments
                    if item.integrity_assessment_id in set(run.integrity_assessment_ids)
                ],
                "freshness": [
                    item.model_dump(mode="json")
                    for item in inspector.freshness_assessments
                    if item.freshness_assessment_id in set(run.freshness_assessment_ids)
                ],
                "protection": [
                    item.model_dump(mode="json")
                    for item in inspector.protection_assessments
                    if item.protection_assessment_id in set(run.protection_assessment_ids)
                ],
                "findings": [
                    item.model_dump(mode="json")
                    for item in inspector.findings
                    if item.finding_id in set(run.finding_ids)
                ],
                "coverage": next(
                    (
                        item.model_dump(mode="json")
                        for item in inspector.coverage_records
                        if item.coverage_id == run.coverage_id
                    ),
                    None,
                ),
                "observations": [
                    item.model_dump(mode="json")
                    for item in inspector.observations
                    if item.observation_id in set(run.observation_ids)
                ],
                "incidents": [
                    item.model_dump(mode="json")
                    for item in inspector.incidents
                    if item.incident_id in set(run.incident_ids)
                ],
                "inventory": next(
                    (
                        item.model_dump(mode="json")
                        for item in inspector.inventories
                        if item.inspection_run_id == run.inspection_run_id
                    ),
                    None,
                ),
                "lineage": [
                    item.model_dump(mode="json")
                    for item in inspector.lineage_edges
                    if item.parent_artifact_reference_id in reference_ids
                    or item.child_artifact_reference_id in reference_ids
                ],
                "comparisons": [
                    item.model_dump(mode="json")
                    for item in inspector.comparisons
                    if item.inspection_run_id == run.inspection_run_id
                ],
                "events": [
                    item.model_dump(mode="json")
                    for item in inspector.events
                    if item.inspection_run_id == run.inspection_run_id
                ],
                "handoffs": [
                    item.model_dump(mode="json")
                    for item in inspector.handoffs
                    if item.handoff_id in set(run.handoff_ids)
                ],
            }
        )

    def compare_artifacts(
        self,
        project_id: str,
        *,
        inspection_run_id: str,
        left_reference_id: str,
        right_reference_id: str,
    ) -> BobaArtifactComparisonV1:
        inspector = self._inspector(project_id)
        run = self._run(inspector, inspection_run_id)
        left = self._reference(inspector, left_reference_id)
        right = self._reference(inspector, right_reference_id)
        left_snapshot = self._latest_snapshot(inspector, run, left.artifact_reference_id)
        right_snapshot = self._latest_snapshot(inspector, run, right.artifact_reference_id)
        if not left_snapshot or not right_snapshot:
            result: Literal["match", "different", "inconclusive", "conflict"] = "inconclusive"
            explanation = "Both artifacts require completed inspection snapshots before comparison."
        elif (
            left_snapshot.recomputed_digest
            and left_snapshot.recomputed_digest == right_snapshot.recomputed_digest
        ):
            result = "match"
            explanation = (
                "Observed SHA-256 bytes match; this is not a quality or workflow decision."
            )
        elif (
            left.expected_digest
            and right.expected_digest
            and left.expected_digest != right.expected_digest
            and left.output_id
            and left.output_id == right.output_id
        ):
            result = "conflict"
            explanation = (
                "Immutable artifact identities share an output identity but declare "
                "conflicting digests."
            )
        else:
            result = "different"
            explanation = "The selected artifacts do not have the same observed digest."
        comparison = BobaArtifactComparisonV1(
            comparison_id=_stable_id(
                "artifact_comparison", run.inspection_run_id, left_reference_id, right_reference_id
            ),
            inspection_run_id=run.inspection_run_id,
            left_artifact_reference_id=left_reference_id,
            right_artifact_reference_id=right_reference_id,
            comparison_kind="digest",
            result=result,
            bounded_explanation=explanation,
        )
        if not any(
            item.comparison_id == comparison.comparison_id for item in inspector.comparisons
        ):
            inspector.comparisons.append(comparison)
            self.store.save_boba_artifact_inspector(inspector)
        return comparison

    def build_project_inventory(
        self, project_id: str, *, inspection_run_id: str
    ) -> BobaArtifactInventoryV1:
        inspector = self._inspector(project_id)
        run = self._run(inspector, inspection_run_id)
        inventory = self._inventory(
            inspector,
            run,
            self._references(inspector, self._request(inspector, run.inspection_request_id)),
        )
        if not any(item.inventory_id == inventory.inventory_id for item in inspector.inventories):
            inspector.inventories.append(inventory)
            self.store.save_boba_artifact_inspector(inspector)
        return inventory

    def inspect_lineage(
        self,
        project_id: str,
        *,
        inspection_run_id: str,
    ) -> dict[str, Any]:
        inspector = self._inspector(project_id)
        run = self._run(inspector, inspection_run_id)
        requested = self._references(
            inspector,
            self._request(inspector, run.inspection_request_id),
        )
        reference_ids = {item.artifact_reference_id for item in requested}
        edges = [
            item
            for item in inspector.lineage_edges
            if item.project_id == project_id
            and (
                item.parent_artifact_reference_id in reference_ids
                or item.child_artifact_reference_id in reference_ids
            )
        ]
        return _sanitized_mapping(
            {
                "schema_version": "boba_artifact_lineage_v1",
                "project_id": project_id,
                "inspection_run_id": run.inspection_run_id,
                "lineage": [item.model_dump(mode="json") for item in edges],
                "source_declared_only": True,
                "filename_or_timestamp_inference_used": False,
            }
        )
    def inspect_events(self, project_id: str, inspection_run_id: str) -> list[BobaArtifactEventV1]:
        self._run(self._inspector(project_id), inspection_run_id)
        return [
            item
            for item in self._inspector(project_id).events
            if item.inspection_run_id == inspection_run_id
        ]

    def export_artifact_inspection(self, project_id: str) -> dict[str, Any]:
        inspector = self._inspector(project_id)
        return _sanitized_mapping(
            {
                "schema_version": "boba_artifact_inspector_export_v1",
                "project_id": project_id,
                "inspector": inspector.model_dump(mode="json"),
                "raw_media_included": False,
                "source_code_included": False,
                "complete_logs_included": False,
            }
        )

    def reset_artifact_inspector_metadata(self, project_id: str) -> dict[str, Any]:
        self._inspector(project_id)
        return self.store.reset_boba_artifact_inspector(project_id)

    def _build_references(
        self,
        inspector: BobaArtifactInspectorSetV1,
        project_id: str,
        source_id: str,
        raw_references: Sequence[Mapping[str, Any]],
    ) -> list[BobaArtifactReferenceV1]:
        result: list[BobaArtifactReferenceV1] = []
        for raw in raw_references:
            allowed = {
                "workflow_run_id",
                "stage_instance_id",
                "clip_id",
                "output_id",
                "owner_module_id",
                "producer_record_id",
                "artifact_type_id",
                "schema_id",
                "schema_version",
                "expected_digest",
                "expected_digest_type",
                "expected_size_bytes",
                "sanitized_storage_reference",
                "storage_kind",
                "immutable",
                "source_media",
                "source_media_read_only",
                "accepted_output",
                "generated_output",
                "required",
                "historical",
                "rights_status",
                "created_at",
                "completed_at",
                "declared_lineage",
                "warnings",
            }
            unexpected = set(raw) - allowed
            if unexpected:
                raise ValidationError(
                    "Artifact references cannot define roots, resolvers, commands, "
                    "parsers, or unsupported fields.",
                    details={"fields": sorted(unexpected)},
                )
            artifact_type_id = _safe_text(raw.get("artifact_type_id"), 160)
            descriptor = self._descriptor(inspector, artifact_type_id)
            reference = BobaArtifactReferenceV1(
                artifact_reference_id=_stable_id(
                    "artifact_reference",
                    project_id,
                    artifact_type_id,
                    raw.get("producer_record_id", ""),
                    raw.get("sanitized_storage_reference", ""),
                    raw.get("expected_digest", ""),
                ),
                project_id=project_id,
                source_id=source_id,
                **dict(raw),
            )
            self._validate_reference(reference, descriptor, project_id)
            result.append(reference)
        return result

    def _validate_reference(
        self,
        reference: BobaArtifactReferenceV1,
        descriptor: BobaArtifactTypeDescriptorV1,
        project_id: str,
    ) -> None:
        if reference.project_id != project_id:
            raise ValidationError("Cross-project artifact reference blocked.")
        if reference.owner_module_id != descriptor.owner_module_id:
            raise ValidationError("Artifact owner does not match the fixed descriptor.")
        if reference.storage_kind != descriptor.storage_kind:
            raise ValidationError("Artifact storage kind does not match the fixed descriptor.")
        if reference.source_media and reference.generated_output:
            raise ValidationError("Source media cannot be presented as generated output.")
        if reference.accepted_output and not reference.immutable:
            raise ValidationError("Accepted outputs must remain immutable and read-only.")
        if descriptor.availability in {"future", "unavailable"}:
            raise ValidationError("The selected artifact type is not available for V1 inspection.")
        self._scope_matches(reference, descriptor)

    def _scope_matches(
        self, reference: BobaArtifactReferenceV1, descriptor: BobaArtifactTypeDescriptorV1
    ) -> None:
        values = {
            "project_id": reference.project_id,
            "workflow_run_id": reference.workflow_run_id,
            "stage_instance_id": reference.stage_instance_id,
            "clip_id": reference.clip_id,
            "output_id": reference.output_id,
            "producer_record_id": reference.producer_record_id,
        }
        candidates = []
        for pattern in descriptor.expected_storage_scopes:
            if any(not values.get(name, "") for name in re.findall(r"\{([^}]+)\}", pattern)):
                continue
            candidates.append(pattern.format(**values))
        if reference.sanitized_storage_reference not in candidates:
            raise ValidationError(
                "Artifact reference is outside the fixed project-scoped descriptor path."
            )

    def _resolve(
        self, reference: BobaArtifactReferenceV1, descriptor: BobaArtifactTypeDescriptorV1
    ) -> Path:
        self._scope_matches(reference, descriptor)
        if descriptor.storage_domain == "boba":
            root = self.store.root.resolve()
        elif descriptor.storage_domain == "project_storage" and self.storage is not None:
            local_root = self.storage.local_path("")
            if not local_root:
                raise ValidationError("Configured project storage has no local inspection root.")
            root = Path(local_root).resolve()
        else:
            raise ValidationError("Artifact storage domain is not locally inspectable.")
        candidate = (root / reference.sanitized_storage_reference).resolve(strict=False)
        if candidate != root and root not in candidate.parents:
            raise ValidationError("Artifact reference escapes its approved storage root.")
        if candidate.exists() and candidate.is_symlink():
            target = candidate.resolve()
            if target != root and root not in target.parents:
                raise ValidationError("Artifact symlink escapes its approved storage root.")
        return candidate

    def _run_is_current(
        self,
        inspector: BobaArtifactInspectorSetV1,
        run: BobaArtifactInspectionRunV1,
    ) -> bool:
        request = self._request(inspector, run.inspection_request_id)
        snapshots = {
            item.artifact_reference_id: item
            for item in inspector.artifact_snapshots
            if item.inspection_run_id == run.inspection_run_id
        }
        for reference in self._references(inspector, request):
            snapshot = snapshots.get(reference.artifact_reference_id)
            if snapshot is None:
                return False
            try:
                path = self._resolve(
                    reference,
                    self._descriptor(inspector, reference.artifact_type_id),
                )
                if path.exists() != snapshot.exists:
                    return False
                if not path.exists():
                    continue
                observed_kind = "directory" if path.is_dir() else "file"
                if snapshot.observed_storage_kind != observed_kind:
                    return False
                if path.is_file():
                    stat = path.stat()
                    if stat.st_size != snapshot.observed_size_bytes:
                        return False
                    modified_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
                    if modified_at != snapshot.observed_modified_at:
                        return False
            except (OSError, ValidationError, ValueError):
                return False
        return True
    def _inspect_reference(
        self,
        inspector: BobaArtifactInspectorSetV1,
        run: BobaArtifactInspectionRunV1,
        request: BobaArtifactInspectionRequestV1,
        reference: BobaArtifactReferenceV1,
        remaining_digest_bytes: int,
    ) -> tuple[
        BobaArtifactSnapshotV1,
        BobaArtifactIntegrityAssessmentV1,
        BobaArtifactFreshnessAssessmentV1,
        BobaArtifactProtectionAssessmentV1,
        list[BobaArtifactFindingV1],
        list[BobaArtifactIncidentV1],
    ]:
        descriptor = self._descriptor(inspector, reference.artifact_type_id)
        warnings: list[str] = []
        findings: list[BobaArtifactFindingV1] = []
        incidents: list[BobaArtifactIncidentV1] = []
        exists = accessible = False
        observed_kind: BobaArtifactStorageKindV1 = "unknown"
        observed_format = "unknown"
        size: int | None = None
        mtime = ""
        persisted = reference.expected_digest
        recomputed = ""
        recomputed_used = False
        changed = partial = False
        structure: Literal["valid", "malformed", "not_checked", "unknown"] = "not_checked"
        entries: list[str] = []
        status: BobaArtifactIntegrityStatusV1 = "unknown"
        persisted_status: Literal["match", "mismatch", "missing", "not_checked"] = (
            "missing" if not persisted else "not_checked"
        )
        recomputed_status: Literal["match", "mismatch", "not_recomputed", "blocked"] = (
            "not_recomputed"
        )
        try:
            path = self._resolve(reference, descriptor)
            exists = path.exists()
            if not exists:
                status = "missing"
                warnings.append("Registered artifact is missing.")
            elif descriptor.storage_kind in {"directory"} and not path.is_dir():
                status = "wrong_type"
                warnings.append("A file was found where a directory was registered.")
            elif (
                descriptor.storage_kind in {"file", "manifest", "structured_record", "event_stream"}
                and not path.is_file()
            ):
                status = "wrong_type"
                warnings.append("A directory was found where a file-like artifact was registered.")
            else:
                accessible = True
                observed_kind = "directory" if path.is_dir() else "file"
                before = path.stat()
                size = None
                mtime = datetime.fromtimestamp(before.st_mtime, UTC).isoformat()
                if path.is_dir():
                    if descriptor.directory_inventory_allowed:
                        entries = sorted(
                            item.name
                            for item in islice(
                                path.iterdir(),
                                descriptor.maximum_directory_entries,
                            )
                        )
                        inspector.signal_usage.directory_inventory_used = True
                    status = "verified_with_limitations"
                else:
                    size = before.st_size
                    if (
                        reference.source_media
                        and reference.rights_status
                        != "allowed_for_local_content_processing"
                    ):
                        observed_format = path.suffix.casefold().lstrip(".") or "unknown"
                        structure = "not_checked"
                    else:
                        observed_format, structure = self._format_and_structure(
                            path,
                            descriptor,
                            request.inspect_content,
                        )
                    if (
                        descriptor.expected_formats
                        and observed_format not in descriptor.expected_formats
                    ):
                        status = "wrong_type"
                        warnings.append(
                            "Observed format is incompatible with the fixed artifact descriptor."
                        )
                    elif (
                        reference.expected_size_bytes is not None
                        and size != reference.expected_size_bytes
                    ):
                        partial = True
                        status = "partial"
                        warnings.append(
                            "Observed artifact size does not match the persisted expected size."
                        )
                    elif size == 0:
                        partial = True
                        status = "partial"
                        warnings.append("Artifact is zero-length and may be incomplete.")
                    elif size > descriptor.maximum_file_bytes:
                        status = "deeper_validation_required"
                        warnings.append(
                            "Artifact exceeds the descriptor's bounded inspection size."
                        )
                    elif (
                        reference.source_media
                        and reference.rights_status
                        != "allowed_for_local_content_processing"
                    ):
                        status = "rights_blocked"
                        recomputed_status = "blocked"
                        warnings.append(
                            "Source-media digest recomputation is blocked by persisted "
                            "rights state."
                        )
                    elif (
                        request.recompute_digests
                        and descriptor.full_digest_recomputation_allowed
                    ):
                        if size > remaining_digest_bytes:
                            status = "deeper_validation_required"
                            warnings.append(
                                "The request's total bounded digest budget is exhausted."
                            )
                        else:
                            try:
                                recomputed = self._stream_digest(
                                    path,
                                    remaining_digest_bytes,
                                )
                            except ValidationError:
                                partial = True
                                status = "partial"
                                warnings.append(
                                    "Artifact exceeded its digest budget while it was read."
                                )
                            else:
                                recomputed_used = True
                                inspector.signal_usage.streaming_digest_used = True
                                recomputed_status = (
                                    "match"
                                    if not persisted
                                    or self._digest_equal(persisted, recomputed)
                                    else "mismatch"
                                )
                                persisted_status = (
                                    "match"
                                    if recomputed_status == "match" and persisted
                                    else persisted_status
                                )
                    after = path.stat()
                    changed = (before.st_size, before.st_mtime_ns) != (
                        after.st_size,
                        after.st_mtime_ns,
                    )
                    if changed:
                        partial = True
                        status = "partial"
                        warnings.append(
                            "Artifact changed during inspection and cannot be marked verified."
                        )
                    elif structure == "malformed" and status == "unknown":
                        status = "malformed"
                    elif recomputed_status == "mismatch":
                        status = "digest_mismatch"
                    elif status == "unknown":
                        status = (
                            "deeper_validation_required"
                            if descriptor.required_deeper_validator_ids
                            else "verified_with_limitations"
                        )
        except (OSError, ValidationError, ValueError) as exc:
            status = "inaccessible"
            warnings.append(_safe_text(exc))
        snapshot = BobaArtifactSnapshotV1(
            artifact_snapshot_id=_stable_id(
                "artifact_snapshot", run.inspection_run_id, reference.artifact_reference_id
            ),
            inspection_run_id=run.inspection_run_id,
            artifact_reference_id=reference.artifact_reference_id,
            project_id=reference.project_id,
            exists=exists,
            accessible=accessible,
            observed_storage_kind=observed_kind,
            observed_format=observed_format,
            observed_size_bytes=size,
            observed_modified_at=mtime,
            persisted_digest=persisted,
            recomputed_digest=recomputed,
            recomputed_digest_used=recomputed_used,
            changed_during_read=changed,
            partial_write_suspected=partial,
            lightweight_structure=structure,
            bounded_directory_entries=entries,
            warnings=warnings,
        )
        integrity = BobaArtifactIntegrityAssessmentV1(
            integrity_assessment_id=_stable_id(
                "artifact_integrity", run.inspection_run_id, reference.artifact_reference_id
            ),
            inspection_run_id=run.inspection_run_id,
            artifact_reference_id=reference.artifact_reference_id,
            status=status,
            persisted_digest_status=persisted_status,
            recomputed_digest_status=recomputed_status,
            requires_deeper_validation=bool(descriptor.required_deeper_validator_ids),
            bounded_explanation=self._integrity_text(status, descriptor),
            warnings=warnings,
        )
        freshness_status: BobaArtifactFreshnessStatusV1 = (
            "historical" if reference.historical else "current"
        )
        if (
            request.project_snapshot_digest
            and reference.expected_digest
            and request.project_snapshot_digest != reference.expected_digest
        ):
            freshness_status = "stale"
        freshness = BobaArtifactFreshnessAssessmentV1(
            freshness_assessment_id=_stable_id(
                "artifact_freshness", run.inspection_run_id, reference.artifact_reference_id
            ),
            inspection_run_id=run.inspection_run_id,
            artifact_reference_id=reference.artifact_reference_id,
            status=freshness_status,
            current_project_snapshot=None
            if not request.project_snapshot_digest
            else freshness_status == "current",
            current_workflow_revision=None
            if not request.workflow_run_id
            else reference.workflow_run_id == request.workflow_run_id,
            current_producer_record=None
            if not reference.producer_record_id
            else not reference.historical,
            bounded_explanation=(
                "Historical artifacts remain visible but cannot establish a current "
                "action."
            )
            if freshness_status != "current"
            else (
                "The reference is current only for this exact registered inspection "
                "context."
            ),
        )
        protection = BobaArtifactProtectionAssessmentV1(
            protection_assessment_id=_stable_id(
                "artifact_protection", run.inspection_run_id, reference.artifact_reference_id
            ),
            inspection_run_id=run.inspection_run_id,
            artifact_reference_id=reference.artifact_reference_id,
            source_media_status="protected" if reference.source_media else "not_applicable",
            accepted_output_status="protected" if reference.accepted_output else "not_applicable",
            immutable_status="protected"
            if reference.immutable and status not in {"digest_mismatch", "partial"}
            else ("at_risk" if reference.immutable else "not_applicable"),
            bounded_explanation=(
                "Source media and accepted outputs remain read-only; Artifact Inspector "
                "never modifies them."
            ),
        )
        severity: Literal["info", "low", "medium", "high", "critical", "unknown"] = "info"
        if status in {"missing", "inaccessible", "digest_mismatch", "partial", "malformed"}:
            severity = "high" if reference.required else "medium"
            findings.append(
                BobaArtifactFindingV1(
                    finding_id=_stable_id(
                        "artifact_finding",
                        run.inspection_run_id,
                        reference.artifact_reference_id,
                        status,
                    ),
                    inspection_run_id=run.inspection_run_id,
                    artifact_reference_id=reference.artifact_reference_id,
                    category=status,
                    severity=severity,
                    confirmed_fact=self._integrity_text(status, descriptor),
                    assessment=(
                        "This is a read-only artifact observation, not a validator, "
                        "quality, or workflow decision."
                    ),
                    requires_attention=True,
                )
            )
            incidents.append(
                self._incident(
                    run, reference, status, severity, self._integrity_text(status, descriptor)
                )
            )
        return snapshot, integrity, freshness, protection, findings, incidents

    @staticmethod
    def _digest_equal(left: str, right: str) -> bool:
        return left.removeprefix("sha256:").casefold() == right.removeprefix("sha256:").casefold()

    @staticmethod
    def _stream_digest(path: Path, maximum_bytes: int) -> str:
        total = 0
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(64 * 1024):
                total += len(chunk)
                if total > maximum_bytes:
                    raise ValidationError("Artifact exceeds the request's bounded digest budget.")
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _format_and_structure(
        path: Path, descriptor: BobaArtifactTypeDescriptorV1, inspect_content: bool
    ) -> tuple[str, Literal["valid", "malformed", "not_checked", "unknown"]]:
        suffix = path.suffix.casefold().lstrip(".")
        if not descriptor.lightweight_signature_check_allowed:
            return suffix or "unknown", "not_checked"
        if suffix in {"json", "jsonl"} and (
            inspect_content or descriptor.content_read_allowed
        ):
            with path.open("rb") as handle:
                raw = handle.read(1_048_576)
            try:
                if suffix == "json":
                    parsed = json.loads(raw)
                    return suffix, "valid" if isinstance(parsed, (dict, list)) else "malformed"
                for line in raw.decode("utf-8").splitlines()[:10_000]:
                    if line.strip():
                        json.loads(line)
                return suffix, "valid"
            except (UnicodeDecodeError, json.JSONDecodeError):
                return suffix, "malformed"
        if suffix == "mp4":
            with path.open("rb") as handle:
                head = handle.read(32)
            return "mp4", "valid" if b"ftyp" in head else "malformed"
        return suffix or "unknown", "not_checked"

    def _lineage(
        self,
        inspector: BobaArtifactInspectorSetV1,
        run: BobaArtifactInspectionRunV1,
        references: Sequence[BobaArtifactReferenceV1],
    ) -> list[BobaArtifactLineageEdgeV1]:
        known = {item.artifact_reference_id for item in inspector.artifact_references}
        edges: list[BobaArtifactLineageEdgeV1] = []
        for child in references:
            for declaration in child.declared_lineage:
                parent_id = _safe_text(declaration.get("parent_artifact_reference_id"), 180)
                relationship = _safe_text(declaration.get("relationship"), 40)
                if (
                    not parent_id
                    or parent_id not in known
                    or parent_id == child.artifact_reference_id
                ):
                    continue
                if relationship not in {
                    "produced_from",
                    "transformed_from",
                    "recovered_from",
                    "validated_by",
                    "supersedes",
                }:
                    relationship = "unknown"
                edges.append(
                    BobaArtifactLineageEdgeV1(
                        lineage_edge_id=_stable_id(
                            "artifact_lineage",
                            run.inspection_run_id,
                            parent_id,
                            child.artifact_reference_id,
                            relationship,
                        ),
                        project_id=child.project_id,
                        parent_artifact_reference_id=parent_id,
                        child_artifact_reference_id=child.artifact_reference_id,
                        relationship=relationship,
                    )
                )
        return [
            item
            for item in edges
            if not any(
                existing.lineage_edge_id == item.lineage_edge_id
                for existing in inspector.lineage_edges
            )
        ]

    def _inventory(
        self,
        inspector: BobaArtifactInspectorSetV1,
        run: BobaArtifactInspectionRunV1,
        references: Sequence[BobaArtifactReferenceV1],
    ) -> BobaArtifactInventoryV1:
        snapshots = {
            item.artifact_reference_id: item
            for item in inspector.artifact_snapshots
            if item.inspection_run_id == run.inspection_run_id
        }
        present = [
            item.artifact_reference_id
            for item in references
            if snapshots.get(item.artifact_reference_id)
            and snapshots[item.artifact_reference_id].exists
        ]
        missing_required = [
            item.artifact_reference_id
            for item in references
            if item.required and item.artifact_reference_id not in present
        ]
        missing_optional = [
            item.artifact_reference_id
            for item in references
            if not item.required and item.artifact_reference_id not in present
        ]
        orphaned = [
            item.artifact_reference_id
            for item in references
            if item.historical is False and not item.producer_record_id
        ]
        digest = _stable_digest(
            "artifact_inventory",
            {
                "references": sorted(item.artifact_reference_id for item in references),
                "present": sorted(present),
            },
        )
        return BobaArtifactInventoryV1(
            inventory_id=_stable_id("artifact_inventory", run.inspection_run_id, digest),
            inspection_run_id=run.inspection_run_id,
            project_id=run.project_id,
            artifact_reference_ids=[item.artifact_reference_id for item in references],
            present_reference_ids=present,
            missing_required_reference_ids=missing_required,
            missing_optional_reference_ids=missing_optional,
            orphan_candidate_reference_ids=orphaned,
            inventory_digest=digest,
            warnings=[
                "Inventory contains exact registered references only; it does not "
                "recursively scan project storage."
            ],
        )

    def _coverage(
        self,
        run: BobaArtifactInspectionRunV1,
        references: Sequence[BobaArtifactReferenceV1],
        inspector: BobaArtifactInspectorSetV1,
    ) -> BobaArtifactCoverageV1:
        snapshots = [
            item
            for item in inspector.artifact_snapshots
            if item.inspection_run_id == run.inspection_run_id
        ]
        missing = sum(1 for item in snapshots if not item.exists)
        blocked = sum(
            1
            for item in inspector.integrity_assessments
            if item.inspection_run_id == run.inspection_run_id
            and item.status in {"inaccessible", "rights_blocked", "partial"}
        )
        required_missing = sum(
            1
            for item in references
            if item.required
            and item.artifact_reference_id
            not in {snapshot.artifact_reference_id for snapshot in snapshots if snapshot.exists}
        )
        status: Literal["complete", "complete_with_limitations", "incomplete", "blocked"]
        if blocked:
            status = "blocked"
        elif required_missing:
            status = "incomplete"
        elif missing:
            status = "complete_with_limitations"
        else:
            status = "complete"
        return BobaArtifactCoverageV1(
            coverage_id=_stable_id(
                "artifact_coverage", run.inspection_run_id, status, str(missing), str(blocked)
            ),
            inspection_run_id=run.inspection_run_id,
            status=status,
            requested_artifact_count=len(references),
            inspected_artifact_count=len(snapshots),
            missing_required_count=required_missing,
            blocked_count=blocked,
        )

    def _handoffs(
        self,
        inspector: BobaArtifactInspectorSetV1,
        run: BobaArtifactInspectionRunV1,
        references: Sequence[BobaArtifactReferenceV1],
    ) -> list[BobaArtifactHandoffV1]:
        handoffs: list[BobaArtifactHandoffV1] = []
        snapshots = {
            item.artifact_reference_id: item
            for item in inspector.artifact_snapshots
            if item.inspection_run_id == run.inspection_run_id
        }
        for reference in references:
            descriptor = self._descriptor(inspector, reference.artifact_type_id)
            snapshot = snapshots.get(reference.artifact_reference_id)
            if descriptor.required_deeper_validator_ids:
                handoffs.append(
                    self._handoff(
                        run,
                        "validator_runner",
                        "Artifact existence and digest do not replace deep technical validation.",
                        [reference.artifact_reference_id],
                        descriptor.required_deeper_validator_ids,
                        reference=reference,
                        snapshot=snapshot,
                        blocking_conditions=["deeper_validation_required"],
                    )
                )
            if descriptor.report_artifact:
                handoffs.append(
                    self._handoff(
                        run,
                        "report_reader",
                        "Report meaning remains owned by Report Reader and the original producer.",
                        [reference.artifact_reference_id],
                        reference=reference,
                        snapshot=snapshot,
                    )
                )
            if reference.required and snapshot and not snapshot.exists:
                handoffs.append(
                    self._handoff(
                        run,
                        "workflow_controller",
                        "A required registered artifact is missing; Inspector does not "
                        "authorize workflow continuation.",
                        [reference.artifact_reference_id],
                        reference=reference,
                        snapshot=snapshot,
                        blocking_conditions=["required_artifact_missing"],
                    )
                )
            if snapshot and snapshot.partial_write_suspected:
                handoffs.append(
                    self._handoff(
                        run,
                        "autopilot_controller",
                        "Artifact changed during inspection and may still be writing; "
                        "no recovery action was executed.",
                        [reference.artifact_reference_id],
                        reference=reference,
                        snapshot=snapshot,
                        blocking_conditions=["partial_write_suspected"],
                    )
                )
        unique: dict[str, BobaArtifactHandoffV1] = {item.handoff_id: item for item in handoffs}
        return [
            item
            for item in unique.values()
            if not any(existing.handoff_id == item.handoff_id for existing in inspector.handoffs)
        ]

    @staticmethod
    def _handoff(
        run: BobaArtifactInspectionRunV1,
        target: str,
        reason: str,
        references: list[str],
        validators: list[str] | None = None,
        *,
        reference: BobaArtifactReferenceV1 | None = None,
        snapshot: BobaArtifactSnapshotV1 | None = None,
        blocking_conditions: list[str] | None = None,
    ) -> BobaArtifactHandoffV1:
        protected_state_requirements: list[str] = []
        if reference is not None:
            if reference.source_media:
                protected_state_requirements.append("source_media_read_only")
            if reference.accepted_output:
                protected_state_requirements.append("accepted_output_read_only")
            if reference.immutable:
                protected_state_requirements.append("immutable_artifact")
        observed_digest = ""
        if snapshot is not None:
            observed_digest = snapshot.recomputed_digest or snapshot.persisted_digest
        return BobaArtifactHandoffV1(
            handoff_id=_stable_id(
                "artifact_handoff", run.inspection_run_id, target, reason, references
            ),
            inspection_run_id=run.inspection_run_id,
            project_id=run.project_id,
            target_module_id=target,
            reason=reason,
            artifact_reference_ids=references,
            artifact_snapshot_ids=[snapshot.artifact_snapshot_id] if snapshot else [],
            observed_digests=[observed_digest] if observed_digest else [],
            required_validator_ids=validators or [],
            blocking_conditions=blocking_conditions or [],
            protected_state_requirements=protected_state_requirements,
            requires_human_or_owner_review=True,
        )

    @staticmethod
    def _integrity_text(
        status: BobaArtifactIntegrityStatusV1, descriptor: BobaArtifactTypeDescriptorV1
    ) -> str:
        messages = {
            "verified": "The exact registered artifact matched the requested integrity checks.",
            "verified_with_limitations": (
                "The registered artifact exists, but only bounded inspection was "
                "performed."
            ),
            "missing": (
                "The registered artifact is missing from its expected project-scoped "
                "location."
            ),
            "inaccessible": "The registered artifact could not be safely accessed.",
            "digest_mismatch": "The artifact does not match its persisted SHA-256 digest.",
            "wrong_type": (
                "The registered artifact has a different file or directory type than "
                "expected."
            ),
            "malformed": "The bounded structured artifact check detected malformed content.",
            "partial": "The artifact changed during inspection or appears incomplete.",
            "deeper_validation_required": (
                "The artifact exists, but Validator Runner owns deeper technical "
                "checks."
            ),
            "rights_blocked": "Persisted rights state blocks source-media content hashing.",
            "unknown": (
                "Artifact integrity could not be established from bounded local "
                "observation."
            ),
        }
        return messages[status] + (
            " Matching bytes do not prove quality or workflow permission."
            if descriptor.generated_media
            else ""
        )

    def _incident(
        self,
        run: BobaArtifactInspectionRunV1,
        reference: BobaArtifactReferenceV1,
        incident_type: str,
        severity: Literal["info", "low", "medium", "high", "critical", "unknown"],
        summary: str,
    ) -> BobaArtifactIncidentV1:
        fingerprint = _stable_id(
            "artifact_incident", reference.artifact_reference_id, incident_type, summary
        )
        return BobaArtifactIncidentV1(
            incident_id=_stable_id("artifact_incident_record", run.inspection_run_id, fingerprint),
            inspection_run_id=run.inspection_run_id,
            artifact_reference_id=reference.artifact_reference_id,
            incident_type=incident_type,
            severity=severity,
            bounded_summary=summary,
            repeated_fingerprint=fingerprint,
        )

    def _event(
        self,
        inspector: BobaArtifactInspectorSetV1,
        event_type: str,
        technical: str,
        easy: str,
        run_id: str = "",
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        sequence = len(inspector.events) + 1
        percent = round((current / total) * 100, 2) if current is not None and total else None
        inspector.events.append(
            BobaArtifactEventV1(
                event_id=_stable_id(
                    "artifact_event", inspector.project_id, sequence, run_id, event_type
                ),
                inspection_run_id=run_id,
                project_id=inspector.project_id,
                sequence=sequence,
                event_type=event_type,
                technical_message=technical,
                easy_message=easy,
                confirmed_fact="Artifact Inspector performed bounded read-only observation only.",
                progress_current=current,
                progress_total=total,
                progress_percent=percent,
            )
        )

    @staticmethod
    def _descriptor(
        inspector: BobaArtifactInspectorSetV1, artifact_type_id: str
    ) -> BobaArtifactTypeDescriptorV1:
        descriptor = next(
            (
                item
                for item in inspector.artifact_type_descriptors
                if item.artifact_type_id == artifact_type_id
            ),
            None,
        )
        if descriptor is None:
            raise ValidationError("Artifact type is not registered for Artifact Inspector V1.")
        return descriptor

    @staticmethod
    def _request(
        inspector: BobaArtifactInspectorSetV1, inspection_request_id: str
    ) -> BobaArtifactInspectionRequestV1:
        request = next(
            (
                item
                for item in inspector.inspection_requests
                if item.inspection_request_id == inspection_request_id
            ),
            None,
        )
        if request is None:
            raise NotFoundError("Artifact Inspector request was not found.")
        return request

    @staticmethod
    def _run(
        inspector: BobaArtifactInspectorSetV1, inspection_run_id: str
    ) -> BobaArtifactInspectionRunV1:
        run = next(
            (
                item
                for item in inspector.inspection_runs
                if item.inspection_run_id == inspection_run_id
            ),
            None,
        )
        if run is None:
            raise NotFoundError("Artifact Inspector run was not found.")
        return run

    @staticmethod
    def _reference(
        inspector: BobaArtifactInspectorSetV1, reference_id: str
    ) -> BobaArtifactReferenceV1:
        reference = next(
            (
                item
                for item in inspector.artifact_references
                if item.artifact_reference_id == reference_id
            ),
            None,
        )
        if reference is None:
            raise NotFoundError("Artifact Inspector reference was not found.")
        return reference

    def _references(
        self, inspector: BobaArtifactInspectorSetV1, request: BobaArtifactInspectionRequestV1
    ) -> list[BobaArtifactReferenceV1]:
        return [
            self._reference(inspector, reference_id)
            for reference_id in request.artifact_reference_ids
        ]

    @staticmethod
    def _latest_snapshot(
        inspector: BobaArtifactInspectorSetV1, run: BobaArtifactInspectionRunV1, reference_id: str
    ) -> BobaArtifactSnapshotV1 | None:
        return next(
            (
                item
                for item in reversed(inspector.artifact_snapshots)
                if item.inspection_run_id == run.inspection_run_id
                and item.artifact_reference_id == reference_id
            ),
            None,
        )

    @staticmethod
    def _refresh_summary(inspector: BobaArtifactInspectorSetV1) -> None:
        descriptors = inspector.artifact_type_descriptors
        assessments = inspector.integrity_assessments
        inspector.inspector_summary = BobaArtifactInspectorSummaryV1(
            registered_artifact_type_count=len(descriptors),
            available_artifact_type_count=sum(
                item.availability == "available" for item in descriptors
            ),
            total_reference_count=len(inspector.artifact_references),
            total_run_count=len(inspector.inspection_runs),
            verified_count=sum(
                item.status in {"verified", "verified_with_limitations"} for item in assessments
            ),
            missing_count=sum(item.status == "missing" for item in assessments),
            partial_count=sum(item.status == "partial" for item in assessments),
            protected_count=sum(
                item.source_media_status == "protected"
                or item.accepted_output_status == "protected"
                for item in inspector.protection_assessments
            ),
            current_inventory_id=inspector.inventories[-1].inventory_id
            if inspector.inventories
            else "",
            safest_next_action=(
                "Ask the responsible producer, Validator Runner, or a human reviewer "
                "for deeper evidence; Artifact Inspector will not modify or authorize "
                "anything."
            ),
        )


__all__ = [
    "BobaArtifactComparisonV1",
    "BobaArtifactCoverageV1",
    "BobaArtifactEventV1",
    "BobaArtifactFindingV1",
    "BobaArtifactFreshnessAssessmentV1",
    "BobaArtifactHandoffV1",
    "BobaArtifactIncidentV1",
    "BobaArtifactInspectionRequestV1",
    "BobaArtifactInspectionRunV1",
    "BobaArtifactInspectorSetV1",
    "BobaArtifactInspectorSignalUsageV1",
    "BobaArtifactInspectorSummaryV1",
    "BobaArtifactInspectorV1",
    "BobaArtifactIntegrityAssessmentV1",
    "BobaArtifactInventoryV1",
    "BobaArtifactLineageEdgeV1",
    "BobaArtifactObservationV1",
    "BobaArtifactProtectionAssessmentV1",
    "BobaArtifactReferenceV1",
    "BobaArtifactRegistrySnapshotV1",
    "BobaArtifactSnapshotV1",
    "BobaArtifactTypeDescriptorV1",
    "build_fixed_artifact_resolver_registry",
    "build_fixed_artifact_type_registry",
    "sanitize_artifact_export",
]

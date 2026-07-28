"""Read-only technical and creative review of generated Olympus outputs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError
from olympus.rendering.command import build_ffprobe_command
from olympus.validation.real_video import parse_probe

BobaOutputReviewSourceTypeV1 = Literal[
    "normal_render",
    "tool_recovery_output",
    "code_surgeon_behavior_validation",
    "checkpoint_restored_output",
    "rerendered_output",
    "fallback_output",
    "imported_local_output",
    "unknown",
]
BobaOutputReviewModeV1 = Literal[
    "artifact_only",
    "local_technical_review",
    "full_available_evidence_review",
    "baseline_comparison",
    "human_review_preparation",
    "unknown",
]
BobaOutputReviewStatusV1 = Literal[
    "not_started",
    "reviewing",
    "technically_failed",
    "technically_passed",
    "creative_review_incomplete",
    "quality_regression_detected",
    "ready_for_decision",
    "completed",
    "blocked",
    "unknown",
]
BobaReviewedArtifactTypeV1 = Literal[
    "video",
    "audio",
    "caption",
    "JSON",
    "image",
    "manifest",
    "multi_artifact_bundle",
    "unknown",
]
BobaQualityEvidenceSourceTypeV1 = Literal[
    "render_manifest",
    "tool_recovery_validation",
    "code_surgeon_validation",
    "ffprobe",
    "decode_check",
    "checksum",
    "caption_artifact",
    "source_window",
    "clip_brief",
    "hook_retention",
    "caption_motion",
    "music_mood",
    "creative_direction",
    "editorial_decision",
    "boundary_quality",
    "face_motion_validation",
    "multi_speaker_validation",
    "analysis_signal",
    "bounded_manual_review",
    "unknown",
]
BobaQualityEvidenceReliabilityV1 = Literal[
    "high",
    "medium",
    "low",
    "conflicting",
    "unavailable",
    "unknown",
]
BobaTechnicalQualityStatusV1 = Literal[
    "passed",
    "failed",
    "degraded",
    "unavailable",
    "not_required",
    "unknown",
]
BobaTechnicalQualityCategoryV1 = Literal[
    "artifact_exists",
    "artifact_non_empty",
    "checksum",
    "manifest",
    "schema",
    "media_probe",
    "decode",
    "video_stream",
    "audio_stream",
    "duration",
    "resolution",
    "aspect_ratio",
    "frame_rate",
    "frame_count",
    "audio_sample_rate",
    "audio_channels",
    "audio_presence",
    "audio_video_sync",
    "source_window",
    "truncation",
    "duplicate_segment",
    "missing_segment",
    "caption_presence",
    "caption_timing",
    "caption_bounds",
    "framing",
    "subject_visibility",
    "face_tracking",
    "multi_speaker_layout",
    "unknown",
]
BobaCreativeQualityDimensionNameV1 = Literal[
    "hook_strength",
    "hook_delivery",
    "story_completeness",
    "payoff_preservation",
    "pacing",
    "clarity",
    "emotional_continuity",
    "caption_readability",
    "caption_timing",
    "vertical_framing",
    "subject_visibility",
    "face_tracking",
    "multi_speaker_layout",
    "motion_balance",
    "transition_quality",
    "audio_clarity",
    "dialogue_intelligibility",
    "music_mood_fit",
    "music_dialogue_balance",
    "repetition",
    "source_meaning_preservation",
    "platform_format_fit",
    "accessibility",
    "unknown",
]
BobaCreativeQualityStatusV1 = Literal[
    "strong",
    "acceptable",
    "weak",
    "failed",
    "unavailable",
    "conflicting",
    "not_required",
    "unknown",
]
BobaOutputComparisonBasisV1 = Literal[
    "original_render",
    "expected_render_specification",
    "repair_planner_quality_plan",
    "tool_recovery_quality_requirements",
    "last_accepted_output",
    "code_surgeon_behavior_baseline",
    "manual_baseline",
    "unknown",
]
BobaOutputQualityRegressionCategoryV1 = Literal[
    "resolution",
    "frame_rate",
    "duration",
    "source_window",
    "audio_presence",
    "audio_quality",
    "audio_video_sync",
    "caption_presence",
    "caption_timing",
    "framing",
    "subject_visibility",
    "story_completeness",
    "hook",
    "payoff",
    "pacing",
    "motion",
    "music_fit",
    "encoding",
    "file_integrity",
    "accessibility",
    "unknown",
]
BobaOutputQualitySeverityV1 = Literal[
    "negligible",
    "minor",
    "moderate",
    "major",
    "critical",
    "unknown",
]
BobaOutputRegressionAcceptanceImpactV1 = Literal[
    "none",
    "disclose",
    "human_review",
    "reject",
    "blocked",
    "unknown",
]
BobaOutputQualityOwnerV1 = Literal[
    "tool_recovery_brain",
    "repair_planner",
    "root_cause_analyzer",
    "code_surgeon",
    "checkpoint_recovery_manager",
    "validator_runner",
    "workflow_controller",
    "safety_gate",
    "rights_permission_gate",
    "human_operator",
    "unknown",
]
BobaOutputAcceptanceDecisionValueV1 = Literal[
    "accepted_for_next_internal_stage",
    "accepted_with_disclosed_limitations",
    "needs_human_review",
    "needs_more_evidence",
    "rejected_technical",
    "rejected_quality",
    "rejected_regression",
    "blocked_rights",
    "blocked_safety",
    "not_reviewable",
    "unknown",
]
BobaOutputQualityHandoffTargetV1 = Literal[
    "workflow_controller",
    "safety_gate",
    "tool_recovery_brain",
    "repair_planner",
    "root_cause_analyzer",
    "code_surgeon",
    "checkpoint_recovery_manager",
    "validator_runner",
    "rights_permission_gate",
    "human_operator",
    "final_decision_bus",
    "unknown",
]
BobaOutputQualityPriorityV1 = Literal["low", "medium", "high", "critical"]

JsonMapping: TypeAlias = Mapping[str, Any] | BobaContract | None

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_SHELL_TOKEN = re.compile(r"(?:\|\||&&|[|;&><`$]|\$\(|\r|\n)")
_SECRET_KEY = re.compile(
    r"(?i)(?:api[_-]?key|authorization|cookie|credential|password|secret|token)"
)
_ABSOLUTE_TEXT = re.compile(r"(?i)(?:[A-Z]:[\\/]|^\\\\|^/)")
_MEDIA_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})
_AUDIO_SUFFIXES = frozenset({".wav", ".m4a", ".mp3", ".aac", ".flac"})
_CAPTION_SUFFIXES = frozenset({".ass", ".srt", ".vtt"})
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_RIGHTS_ALLOWED = frozenset(
    {
        "owned",
        "licensed",
        "permission_granted",
        "approved",
        "cleared",
        "confirmed",
        "ready_for_processing",
    }
)
_RIGHTS_BLOCKED = frozenset(
    {"blocked", "permission_denied", "not_allowed", "do_not_process"}
)
_SAFETY_ALLOWED = frozenset(
    {"safe", "approved", "cleared", "passed", "eligible", "ready_for_processing"}
)
_SAFETY_BLOCKED = frozenset({"blocked", "unsafe", "rejected", "do_not_process"})
_DURATION_TOLERANCE_SECONDS = 0.15
_STREAM_START_TOLERANCE_SECONDS = 0.04
_FRAME_RATE_TOLERANCE = 0.1
_DEFAULT_TIMEOUT_SECONDS = 60.0
_MAX_TIMEOUT_SECONDS = 120.0
_DEFAULT_OUTPUT_LIMIT_BYTES = 64_000
_MAX_OUTPUT_LIMIT_BYTES = 128_000
_MAX_DECODE_SECONDS = 120.0
_MIN_CREATIVE_EVIDENCE_COVERAGE = 0.65


def _mapping(value: JsonMapping | Any) -> dict[str, Any]:
    if isinstance(value, BobaContract):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: Any, *, maximum: int = 700) -> str:
    text = " ".join(str(value or "").split())
    return text[:maximum]


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unit(value: Any, default: float = 0.0) -> float:
    parsed = _float(value, default)
    assert parsed is not None
    if parsed > 1.0:
        parsed /= 100.0
    return round(min(1.0, max(0.0, parsed)), 4)


def _unique(values: Sequence[Any], *, limit: int = 64, maximum: int = 700) -> list[str]:
    result: list[str] = []
    for value in values:
        item = _text(value, maximum=maximum)
        if item and item not in result:
            result.append(item)
        if len(result) >= limit:
            break
    return result


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        "\x1f".join(str(part) for part in parts).encode("utf-8", "replace")
    ).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _safe_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[bounded]"
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return value.name
    if isinstance(value, str):
        return _text(value, maximum=1_000)
    if isinstance(value, BobaContract):
        return _safe_json_value(value.model_dump(mode="json"), depth=depth + 1)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 64:
                break
            safe_key = _text(key, maximum=120)
            if not safe_key or _SECRET_KEY.search(safe_key):
                continue
            result[safe_key] = _safe_json_value(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [_safe_json_value(item, depth=depth + 1) for item in list(value)[:64]]
    return _text(value, maximum=500)


class BobaOutputQualityEvidenceV1(BobaContract):
    evidence_id: str = Field(min_length=1, max_length=160)
    source_type: BobaQualityEvidenceSourceTypeV1
    source_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=160)
    bounded_summary: str = Field(min_length=1, max_length=900)
    observed_value: Any = None
    expected_value: Any = None
    reliability: BobaQualityEvidenceReliabilityV1 = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    supports_acceptance: bool = False
    supports_rejection: bool = False
    requires_human_interpretation: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaTechnicalQualityCheckV1(BobaContract):
    technical_check_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    category: BobaTechnicalQualityCategoryV1
    name: str = Field(min_length=1, max_length=240)
    required: bool
    status: BobaTechnicalQualityStatusV1
    observed_value: Any = None
    expected_value: Any = None
    tolerance: Any = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    blocks_acceptance: bool = False
    failure_summary: str = Field(default="", max_length=900)
    human_review_needed: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaTechnicalQualityAssessmentV1(BobaContract):
    technical_assessment_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    checks: list[BobaTechnicalQualityCheckV1] = Field(
        default_factory=list, max_length=128
    )
    artifact_integrity_status: BobaTechnicalQualityStatusV1 = "unknown"
    decode_status: BobaTechnicalQualityStatusV1 = "unknown"
    stream_status: BobaTechnicalQualityStatusV1 = "unknown"
    timing_status: BobaTechnicalQualityStatusV1 = "unknown"
    video_status: BobaTechnicalQualityStatusV1 = "unknown"
    audio_status: BobaTechnicalQualityStatusV1 = "unknown"
    caption_status: BobaTechnicalQualityStatusV1 = "unknown"
    framing_status: BobaTechnicalQualityStatusV1 = "unknown"
    source_window_status: BobaTechnicalQualityStatusV1 = "unknown"
    synchronization_status: BobaTechnicalQualityStatusV1 = "unknown"
    technical_score: float = Field(default=0.0, ge=0.0, le=1.0)
    required_checks_passed: bool = False
    failed_required_checks: list[str] = Field(default_factory=list, max_length=64)
    unavailable_required_checks: list[str] = Field(default_factory=list, max_length=64)
    technical_acceptance_eligible: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaCreativeQualityDimensionV1(BobaContract):
    creative_dimension_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    dimension: BobaCreativeQualityDimensionNameV1
    status: BobaCreativeQualityStatusV1
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    positive_findings: list[str] = Field(default_factory=list, max_length=32)
    negative_findings: list[str] = Field(default_factory=list, max_length=32)
    uncertainty: str = Field(default="", max_length=900)
    requires_human_review: bool = False
    blocking: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCreativeQualityAssessmentV1(BobaContract):
    creative_assessment_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    dimensions: list[BobaCreativeQualityDimensionV1] = Field(
        default_factory=list, max_length=64
    )
    hook_status: BobaCreativeQualityStatusV1 = "unknown"
    story_completeness_status: BobaCreativeQualityStatusV1 = "unknown"
    payoff_status: BobaCreativeQualityStatusV1 = "unknown"
    pacing_status: BobaCreativeQualityStatusV1 = "unknown"
    clarity_status: BobaCreativeQualityStatusV1 = "unknown"
    caption_readability_status: BobaCreativeQualityStatusV1 = "unknown"
    framing_quality_status: BobaCreativeQualityStatusV1 = "unknown"
    subject_visibility_status: BobaCreativeQualityStatusV1 = "unknown"
    motion_quality_status: BobaCreativeQualityStatusV1 = "unknown"
    audio_balance_status: BobaCreativeQualityStatusV1 = "unknown"
    music_fit_status: BobaCreativeQualityStatusV1 = "unknown"
    repetition_status: BobaCreativeQualityStatusV1 = "unknown"
    platform_fit_status: BobaCreativeQualityStatusV1 = "unknown"
    creative_score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    subjective_uncertainty: list[str] = Field(default_factory=list, max_length=64)
    creative_acceptance_eligible: bool = False
    human_review_required: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaOutputBaselineComparisonV1(BobaContract):
    baseline_comparison_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    baseline_artifact_id: str = Field(default="", max_length=160)
    reviewed_artifact_id: str = Field(min_length=1, max_length=160)
    comparison_basis: BobaOutputComparisonBasisV1 = "unknown"
    technical_differences: list[dict[str, Any]] = Field(
        default_factory=list, max_length=64
    )
    creative_differences: list[dict[str, Any]] = Field(
        default_factory=list, max_length=64
    )
    quality_requirement_differences: list[dict[str, Any]] = Field(
        default_factory=list, max_length=64
    )
    preserved_properties: list[str] = Field(default_factory=list, max_length=64)
    improved_properties: list[str] = Field(default_factory=list, max_length=64)
    degraded_properties: list[str] = Field(default_factory=list, max_length=64)
    unknown_properties: list[str] = Field(default_factory=list, max_length=64)
    non_negotiable_regressions: list[str] = Field(default_factory=list, max_length=64)
    acceptable_disclosed_regressions: list[str] = Field(
        default_factory=list, max_length=64
    )
    comparison_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    equivalent_for_required_capability: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaOutputQualityRegressionV1(BobaContract):
    quality_regression_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    category: BobaOutputQualityRegressionCategoryV1
    baseline_value: Any = None
    reviewed_value: Any = None
    severity: BobaOutputQualitySeverityV1 = "unknown"
    non_negotiable: bool = False
    disclosed: bool = False
    approved: bool = False
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    acceptance_impact: BobaOutputRegressionAcceptanceImpactV1 = "unknown"
    recommended_action: str = Field(default="", max_length=700)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaOutputQualityIssueV1(BobaContract):
    quality_issue_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=900)
    severity: BobaOutputQualitySeverityV1 = "unknown"
    confirmed: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    affected_requirements: list[str] = Field(default_factory=list, max_length=32)
    blocks_acceptance: bool = False
    repairable: bool = False
    recommended_owner_module: BobaOutputQualityOwnerV1 = "unknown"
    recommended_action: str = Field(default="", max_length=700)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaOutputAcceptanceDecisionV1(BobaContract):
    acceptance_decision_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    decision: BobaOutputAcceptanceDecisionValueV1
    decision_summary: str = Field(min_length=1, max_length=900)
    technical_eligible: bool = False
    creative_eligible: bool = False
    baseline_equivalent: bool | None = None
    required_checks_complete: bool = False
    rights_clear_for_processing: bool = False
    safety_clear_for_processing: bool = False
    human_review_required: bool = True
    acceptance_conditions: list[str] = Field(default_factory=list, max_length=32)
    rejection_reasons: list[str] = Field(default_factory=list, max_length=64)
    disclosed_limitations: list[str] = Field(default_factory=list, max_length=64)
    next_allowed_stage: str = Field(default="", max_length=160)
    workflow_resume_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaOutputHumanReviewPackageV1(BobaContract):
    human_review_package_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=900)
    sanitized_output_reference: str = Field(min_length=1, max_length=500)
    comparison_reference: str = Field(default="", max_length=500)
    reviewer_questions: list[str] = Field(default_factory=list, max_length=16)
    critical_items: list[str] = Field(default_factory=list, max_length=32)
    optional_items: list[str] = Field(default_factory=list, max_length=32)
    technical_summary: str = Field(default="", max_length=1_200)
    creative_summary: str = Field(default="", max_length=1_200)
    regression_summary: str = Field(default="", max_length=1_200)
    unavailable_evidence: list[str] = Field(default_factory=list, max_length=64)
    acceptance_options: list[str] = Field(default_factory=list, max_length=16)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaOutputQualityHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=160)
    review_case_id: str = Field(min_length=1, max_length=160)
    acceptance_decision_id: str = Field(min_length=1, max_length=160)
    target_module: BobaOutputQualityHandoffTargetV1
    reason: str = Field(min_length=1, max_length=700)
    required_inputs: list[str] = Field(default_factory=list, max_length=32)
    quality_issues: list[str] = Field(default_factory=list, max_length=64)
    failed_checks: list[str] = Field(default_factory=list, max_length=64)
    unavailable_checks: list[str] = Field(default_factory=list, max_length=64)
    constraints: list[str] = Field(default_factory=list, max_length=32)
    blocked_actions: list[str] = Field(default_factory=list, max_length=32)
    allowed_advisory_actions: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False
    human_approval_required: Literal[True] = True
    priority: BobaOutputQualityPriorityV1 = "medium"
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaOutputQualityReviewerSummaryV1(BobaContract):
    total_review_cases: int = Field(default=0, ge=0)
    accepted_internal_count: int = Field(default=0, ge=0)
    accepted_with_limitations_count: int = Field(default=0, ge=0)
    human_review_count: int = Field(default=0, ge=0)
    needs_more_evidence_count: int = Field(default=0, ge=0)
    technical_rejection_count: int = Field(default=0, ge=0)
    quality_rejection_count: int = Field(default=0, ge=0)
    regression_rejection_count: int = Field(default=0, ge=0)
    rights_block_count: int = Field(default=0, ge=0)
    safety_block_count: int = Field(default=0, ge=0)
    technical_pass_count: int = Field(default=0, ge=0)
    technical_failure_count: int = Field(default=0, ge=0)
    creative_eligible_count: int = Field(default=0, ge=0)
    creative_uncertain_count: int = Field(default=0, ge=0)
    non_negotiable_regression_count: int = Field(default=0, ge=0)
    highest_priority_issue: str = Field(default="", max_length=700)
    strongest_output: str = Field(default="", max_length=500)
    weakest_output: str = Field(default="", max_length=500)
    safest_next_action: str = Field(default="", max_length=700)
    required_human_actions: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaOutputQualitySignalUsageV1(BobaContract):
    tool_recovery_used: bool = False
    tool_recovery_artifact_read: bool = False
    code_surgeon_used: bool = False
    render_manifest_used: bool = False
    repair_planner_quality_requirements_used: bool = False
    clip_brief_used: bool = False
    hook_retention_used: bool = False
    caption_motion_used: bool = False
    music_mood_used: bool = False
    creative_direction_used: bool = False
    editorial_decision_used: bool = False
    boundary_quality_used: bool = False
    face_motion_validation_used: bool = False
    multi_speaker_validation_used: bool = False
    local_ffprobe_used: bool = False
    local_decode_check_used: bool = False
    checksum_validation_used: bool = False
    caption_validation_used: bool = False
    source_window_validation_used: bool = False
    baseline_comparison_used: bool = False
    bounded_frame_samples_used: bool = False
    bounded_audio_analysis_used: bool = False
    bounded_manual_review_used: bool = False
    output_modified: Literal[False] = False
    source_media_modified: Literal[False] = False
    workflow_resume_used: Literal[False] = False
    rendering_used: Literal[False] = False
    fallback_execution_used: Literal[False] = False
    code_modification_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_access_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    uploading_used: Literal[False] = False
    publication_used: Literal[False] = False
    rights_bypass_used: Literal[False] = False
    safety_bypass_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaReviewedOutputArtifactV1(BobaContract):
    output_artifact_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(default="", max_length=160)
    sanitized_artifact_reference: str = Field(min_length=1, max_length=500)
    artifact_type: BobaReviewedArtifactTypeV1
    origin_module: str = Field(default="", max_length=160)
    origin_run_id: str = Field(default="", max_length=160)
    origin_attempt_id: str = Field(default="", max_length=160)
    generated_at: str | None = Field(default=None, max_length=80)
    expected_source_window: dict[str, float] = Field(default_factory=dict, max_length=8)
    expected_duration_seconds: float | None = Field(default=None, ge=0.0)
    expected_resolution: dict[str, int] = Field(default_factory=dict, max_length=4)
    expected_frame_rate: float | None = Field(default=None, ge=0.0)
    expected_audio: bool | None = None
    expected_captions: bool | None = None
    checksum: str = Field(default="", max_length=160)
    file_size_bytes: int | None = Field(default=None, ge=0)
    accepted_output_protected: bool = True
    source_media_reference: str = Field(default="", max_length=500)
    source_media_read_only: Literal[True] = True
    rights_status: str = Field(default="unknown", max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaOutputReviewCaseV1(BobaContract):
    review_case_id: str = Field(min_length=1, max_length=160)
    source_type: BobaOutputReviewSourceTypeV1
    source_module: str = Field(default="", max_length=160)
    source_record_id: str = Field(default="", max_length=160)
    output_artifact_id: str = Field(min_length=1, max_length=160)
    baseline_artifact_id: str = Field(default="", max_length=160)
    title: str = Field(min_length=1, max_length=240)
    clip_id: str = Field(default="", max_length=160)
    workflow_stage: str = Field(default="unknown", max_length=160)
    review_mode: BobaOutputReviewModeV1
    review_status: BobaOutputReviewStatusV1
    rights_status: str = Field(default="unknown", max_length=80)
    safety_status: str = Field(default="unknown", max_length=80)
    technical_assessment_id: str = Field(default="", max_length=160)
    creative_assessment_id: str = Field(default="", max_length=160)
    baseline_comparison_id: str = Field(default="", max_length=160)
    quality_issue_ids: list[str] = Field(default_factory=list, max_length=64)
    quality_regression_ids: list[str] = Field(default_factory=list, max_length=64)
    acceptance_decision_id: str = Field(default="", max_length=160)
    human_review_package_id: str = Field(default="", max_length=160)
    required_quality_properties: list[str] = Field(default_factory=list, max_length=64)
    non_negotiable_requirements: list[str] = Field(default_factory=list, max_length=64)
    unavailable_required_evidence: list[str] = Field(
        default_factory=list, max_length=64
    )
    human_review_required: bool = True
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaOutputQualityReviewerSetV1(BobaContract):
    schema_version: Literal["boba_output_quality_reviewer_v1"] = (
        "boba_output_quality_reviewer_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    review_cases: list[BobaOutputReviewCaseV1] = Field(
        default_factory=list, max_length=256
    )
    output_artifacts: list[BobaReviewedOutputArtifactV1] = Field(
        default_factory=list, max_length=256
    )
    quality_evidence: list[BobaOutputQualityEvidenceV1] = Field(
        default_factory=list, max_length=1_024
    )
    technical_assessments: list[BobaTechnicalQualityAssessmentV1] = Field(
        default_factory=list, max_length=256
    )
    creative_assessments: list[BobaCreativeQualityAssessmentV1] = Field(
        default_factory=list, max_length=256
    )
    baseline_comparisons: list[BobaOutputBaselineComparisonV1] = Field(
        default_factory=list, max_length=256
    )
    quality_regressions: list[BobaOutputQualityRegressionV1] = Field(
        default_factory=list, max_length=512
    )
    quality_issues: list[BobaOutputQualityIssueV1] = Field(
        default_factory=list, max_length=512
    )
    acceptance_decisions: list[BobaOutputAcceptanceDecisionV1] = Field(
        default_factory=list, max_length=256
    )
    human_review_packages: list[BobaOutputHumanReviewPackageV1] = Field(
        default_factory=list, max_length=256
    )
    review_handoffs: list[BobaOutputQualityHandoffV1] = Field(
        default_factory=list, max_length=512
    )
    reviewer_summary: BobaOutputQualityReviewerSummaryV1 = Field(
        default_factory=BobaOutputQualityReviewerSummaryV1
    )
    signal_usage: BobaOutputQualitySignalUsageV1 = Field(
        default_factory=BobaOutputQualitySignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=128)


@dataclass(frozen=True, slots=True)
class BobaReadOnlyQualityValidatorV1:
    validator_id: str
    executable: str | None
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    output_limit_bytes: int = _DEFAULT_OUTPUT_LIMIT_BYTES

    @property
    def available(self) -> bool:
        return bool(self.executable)


@dataclass(frozen=True, slots=True)
class ResolvedReviewedOutputV1:
    artifact: BobaReviewedOutputArtifactV1
    path: Path
    metadata: dict[str, Any]
    source_type: BobaOutputReviewSourceTypeV1
    path_scope: str


@dataclass(frozen=True, slots=True)
class _BoundedCommandResult:
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    stdout: str
    stderr: str
    output_truncated: bool


def build_read_only_quality_validator_registry(
    *,
    ffprobe_binary: str = "ffprobe",
    ffmpeg_binary: str = "ffmpeg",
) -> dict[str, BobaReadOnlyQualityValidatorV1]:
    """Build the fixed local-only validator registry used by V1."""

    def resolve(binary: str) -> str | None:
        candidate = Path(binary)
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate.resolve())
        return shutil.which(binary)

    return {
        "ffprobe_media": BobaReadOnlyQualityValidatorV1(
            validator_id="ffprobe_media",
            executable=resolve(ffprobe_binary),
        ),
        "ffmpeg_decode": BobaReadOnlyQualityValidatorV1(
            validator_id="ffmpeg_decode",
            executable=resolve(ffmpeg_binary),
            timeout_seconds=_MAX_TIMEOUT_SECONDS,
        ),
        "checksum": BobaReadOnlyQualityValidatorV1(
            validator_id="checksum",
            executable=None,
        ),
        "json_schema": BobaReadOnlyQualityValidatorV1(
            validator_id="json_schema",
            executable=None,
        ),
        "caption_timing": BobaReadOnlyQualityValidatorV1(
            validator_id="caption_timing",
            executable=None,
        ),
        "face_motion_artifact": BobaReadOnlyQualityValidatorV1(
            validator_id="face_motion_artifact",
            executable=None,
        ),
        "multi_speaker_artifact": BobaReadOnlyQualityValidatorV1(
            validator_id="multi_speaker_artifact",
            executable=None,
        ),
    }


def _build_quality_ffprobe_command(*, binary: str, path: Path) -> list[str]:
    base = build_ffprobe_command(binary=binary, path=str(path))
    base[4] = (
        "format=duration,start_time,bit_rate,size,format_name:"
        "stream=index,codec_type,codec_name,width,height,sample_rate,channels,"
        "avg_frame_rate,r_frame_rate,nb_frames,duration,start_time"
    )
    return base


def _build_quality_decode_command(
    *,
    binary: str,
    path: Path,
    expected_duration_seconds: float | None,
) -> list[str]:
    duration = min(
        _MAX_DECODE_SECONDS,
        max(0.1, expected_duration_seconds or _MAX_DECODE_SECONDS),
    )
    return [
        binary,
        "-v",
        "error",
        "-nostdin",
        "-xerror",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(path),
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-f",
        "null",
        os.devnull,
    ]


def validate_quality_command_safety(
    *,
    validator_id: str,
    command: Sequence[str],
    registry: Mapping[str, BobaReadOnlyQualityValidatorV1],
    reviewed_path: Path,
    working_directory: Path,
) -> list[str]:
    """Reject every command that is not the exact bounded read-only shape."""

    errors: list[str] = []
    validator = registry.get(validator_id)
    if validator is None or validator_id not in {"ffprobe_media", "ffmpeg_decode"}:
        return ["The validator is not registered for local command execution."]
    if not command:
        return ["The command is empty."]
    if validator.executable is None:
        errors.append("The registered validator executable is unavailable.")
    else:
        supplied = Path(command[0]).resolve(strict=False)
        expected = Path(validator.executable).resolve(strict=False)
        if supplied != expected:
            errors.append("The command executable does not match the registry.")
    executable_name = Path(command[0]).name.casefold()
    expected_names = (
        {"ffprobe", "ffprobe.exe"}
        if validator_id == "ffprobe_media"
        else {"ffmpeg", "ffmpeg.exe"}
    )
    if executable_name not in expected_names:
        errors.append("Only the registered FFprobe or FFmpeg executable is allowed.")
    reviewed = reviewed_path.resolve(strict=False)
    working = working_directory.resolve(strict=False)
    if not reviewed.is_file():
        errors.append("The exact reviewed output is unavailable.")
    if not working.is_dir():
        errors.append("The fixed review working directory is unavailable.")
    reviewed_matches = 0
    for argument in command[1:]:
        if _CONTROL.search(argument) or _SHELL_TOKEN.search(argument):
            errors.append("Shell metacharacters, chaining, redirects, or substitution are blocked.")
            break
        if _URL_SCHEME.match(argument.strip()):
            errors.append("Network or URL arguments are blocked.")
            break
        try:
            if Path(argument).resolve(strict=False) == reviewed:
                reviewed_matches += 1
        except OSError:
            pass
    if reviewed_matches != 1:
        errors.append("The command must reference the exact reviewed output once.")
    forbidden = {
        "-y",
        "-update",
        "-attach",
        "-dump_attachment",
        "-shortest",
        "-protocol_whitelist",
    }
    if any(argument.casefold() in forbidden for argument in command):
        errors.append("A write-capable or unsafe FFmpeg/FFprobe option is blocked.")
    if validator_id == "ffprobe_media":
        expected_command = _build_quality_ffprobe_command(
            binary=str(validator.executable or command[0]),
            path=reviewed,
        )
        if list(command) != expected_command:
            errors.append("FFprobe arguments do not match the fixed read-only command.")
    else:
        allowed_tail = ["-f", "null", os.devnull]
        if list(command[-3:]) != allowed_tail:
            errors.append("FFmpeg decode must terminate in the platform null sink.")
        if "-i" not in command or "-t" not in command or "-nostdin" not in command:
            errors.append("FFmpeg decode is missing bounded read-only arguments.")
    return _unique(errors, limit=32)


def _sanitized_environment(workspace: Path) -> dict[str, str]:
    allowed_names = {"SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed_names and not _SECRET_KEY.search(key)
    }
    environment["TEMP"] = str(workspace)
    environment["TMP"] = str(workspace)
    environment["NO_PROXY"] = "*"
    return environment


def _bounded_file_text(handle: Any, limit: int) -> tuple[str, bool]:
    handle.flush()
    handle.seek(0, 2)
    size = int(handle.tell())
    offset = max(0, size - limit)
    handle.seek(offset)
    data = handle.read(limit)
    if offset and b"\n" in data:
        data = data.split(b"\n", 1)[1]
    return _text(data.decode("utf-8", "replace"), maximum=4_000), size > limit


def execute_read_only_quality_command(
    *,
    validator_id: str,
    command: Sequence[str],
    registry: Mapping[str, BobaReadOnlyQualityValidatorV1],
    reviewed_path: Path,
    working_directory: Path,
) -> _BoundedCommandResult:
    """Execute one fixed validator command without shell or unbounded capture."""

    errors = validate_quality_command_safety(
        validator_id=validator_id,
        command=command,
        registry=registry,
        reviewed_path=reviewed_path,
        working_directory=working_directory,
    )
    if errors:
        raise ValidationError(
            "Unsafe Output Quality Reviewer command was rejected.",
            details={"errors": errors},
        )
    validator = registry[validator_id]
    timeout = min(_MAX_TIMEOUT_SECONDS, max(1.0, validator.timeout_seconds))
    output_limit = min(
        _MAX_OUTPUT_LIMIT_BYTES,
        max(1_024, validator.output_limit_bytes),
    )
    started = time.monotonic()
    with (
        tempfile.TemporaryFile(
            prefix="boba-quality-stdout-", dir=working_directory
        ) as stdout,
        tempfile.TemporaryFile(
            prefix="boba-quality-stderr-", dir=working_directory
        ) as stderr,
    ):
        try:
            completed = subprocess.run(
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
                shell=False,
                cwd=working_directory,
                env=_sanitized_environment(working_directory),
                timeout=timeout,
            )
            exit_code: int | None = completed.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            exit_code = None
            timed_out = True
        except OSError as exc:
            exit_code = None
            timed_out = False
            stderr.write(str(exc).encode("utf-8", "replace"))
        stdout_text, stdout_truncated = _bounded_file_text(stdout, output_limit)
        stderr_text, stderr_truncated = _bounded_file_text(stderr, output_limit)
    return _BoundedCommandResult(
        exit_code=exit_code,
        timed_out=timed_out,
        duration_seconds=round(max(0.0, time.monotonic() - started), 3),
        stdout=stdout_text,
        stderr=stderr_text,
        output_truncated=stdout_truncated or stderr_truncated,
    )


def _clean_reference(value: str) -> str:
    text = value.strip().replace("\\", "/")
    if not text or _CONTROL.search(text):
        raise ValidationError("The reviewed output reference is missing or invalid.")
    if _URL_SCHEME.match(text):
        raise ValidationError("External URLs cannot be reviewed.")
    if _WINDOWS_ABSOLUTE.match(text) or text.startswith(("/", "//")):
        raise ValidationError("Absolute output paths are not accepted.")
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError("The reviewed output reference contains path traversal.")
    return path.as_posix()


def _artifact_type(reference: str) -> BobaReviewedArtifactTypeV1:
    suffix = Path(reference).suffix.casefold()
    if suffix in _MEDIA_SUFFIXES:
        return "video"
    if suffix in _AUDIO_SUFFIXES:
        return "audio"
    if suffix in _CAPTION_SUFFIXES:
        return "caption"
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix == ".json":
        return "JSON"
    return "unknown"


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_root_path(root: Path, reference: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*PurePosixPath(reference).parts)).resolve(
        strict=False
    )
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValidationError("The reviewed output escaped its approved local root.")
    return candidate


def _source_window(metadata: Mapping[str, Any]) -> dict[str, float]:
    explicit = _mapping(metadata.get("expected_source_window"))
    timeline = _mapping(
        metadata.get("timeline")
        or _mapping(metadata.get("metadata")).get("timeline")
        or _mapping(metadata.get("manifest_entry")).get("metadata", {})
    )
    if "timeline" in timeline:
        timeline = _mapping(timeline.get("timeline"))
    start = _float(
        explicit.get("start_seconds"),
        _float(
            timeline.get("repaired_start_seconds"),
            _float(
                timeline.get("source_start"),
                _float(timeline.get("requested_start_seconds")),
            ),
        ),
    )
    end = _float(
        explicit.get("end_seconds"),
        _float(
            timeline.get("repaired_end_seconds"),
            _float(
                timeline.get("source_end"),
                _float(timeline.get("requested_end_seconds")),
            ),
        ),
    )
    if start is None or end is None or end < start:
        return {}
    return {"start_seconds": round(start, 3), "end_seconds": round(end, 3)}


def _expected_from_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    entry = _mapping(metadata.get("manifest_entry") or metadata.get("render_entry"))
    merged = {**entry, **dict(metadata)}
    expected_resolution = _mapping(merged.get("expected_resolution"))
    width = _int(expected_resolution.get("width"), _int(merged.get("width")))
    height = _int(expected_resolution.get("height"), _int(merged.get("height")))
    expected_duration = _float(
        merged.get("expected_duration_seconds"),
        _float(merged.get("duration")),
    )
    expected_fps = _float(
        merged.get("expected_frame_rate"),
        _float(merged.get("fps")),
    )
    expected_audio = merged.get("expected_audio")
    if not isinstance(expected_audio, bool):
        expected_audio = (
            bool(merged.get("has_audio"))
            if merged.get("has_audio") is not None
            else None
        )
    expected_captions = merged.get("expected_captions")
    if not isinstance(expected_captions, bool):
        expected_captions = (
            bool(merged.get("subtitles_included"))
            if merged.get("subtitles_included") is not None
            else None
        )
    checksum = _text(merged.get("expected_checksum") or merged.get("checksum"), maximum=160)
    return {
        "expected_source_window": _source_window(merged),
        "expected_duration_seconds": expected_duration,
        "expected_resolution": (
            {"width": width, "height": height}
            if width is not None and height is not None
            else {}
        ),
        "expected_frame_rate": expected_fps,
        "expected_audio": expected_audio,
        "expected_captions": expected_captions,
        "expected_audio_sample_rate": _int(
            merged.get("expected_audio_sample_rate"),
            _int(merged.get("audio_sample_rate")),
        ),
        "expected_audio_channels": _int(merged.get("expected_audio_channels")),
        "checksum": checksum,
        "generated_at": _text(merged.get("generated_at") or merged.get("rendered_at"), maximum=80)
        or None,
        "file_size_bytes": _int(merged.get("size_bytes")),
        "clip_id": _text(merged.get("clip_id"), maximum=160),
    }


def resolve_review_output(
    *,
    project_id: str,
    output_reference: str,
    known_output_artifacts: Sequence[Mapping[str, Any]],
    repository_root: Path,
    storage_root: Path,
    source_media_reference: str = "",
    rights_status: str = "unknown",
) -> ResolvedReviewedOutputV1:
    """Resolve one exact allowlisted generated output without directory scanning."""

    if not _PROJECT_ID.fullmatch(project_id):
        raise ValidationError("Invalid Output Quality Reviewer project id.")
    reference = _clean_reference(output_reference)
    source_reference = (
        _clean_reference(source_media_reference) if source_media_reference else ""
    )
    candidates: list[dict[str, Any]] = []
    for raw in known_output_artifacts:
        candidate = dict(raw)
        raw_reference = candidate.get("reference") or candidate.get(
            "sanitized_artifact_reference"
        )
        if not raw_reference:
            continue
        try:
            candidate_reference = _clean_reference(str(raw_reference))
        except ValidationError:
            continue
        candidate_id = _text(
            candidate.get("artifact_id") or candidate.get("output_artifact_id"),
            maximum=160,
        )
        if reference in {candidate_reference, candidate_id}:
            candidate["reference"] = candidate_reference
            candidates.append(candidate)
    if not candidates:
        raise ValidationError(
            "The reviewed output is not a known generated artifact for this project."
        )
    unique_references = {str(item["reference"]) for item in candidates}
    if len(unique_references) != 1:
        raise ValidationError("The reviewed output identity is ambiguous.")
    candidate = candidates[0]
    candidate_reference = str(candidate["reference"])
    candidate_project = _text(candidate.get("project_id"), maximum=128)
    if candidate_project and candidate_project != project_id:
        raise ValidationError("The reviewed output belongs to another project.")
    if candidate.get("is_source_media") is True or (
        source_reference and candidate_reference == source_reference
    ):
        raise ValidationError("Source media cannot be reviewed as generated output.")
    path_scope = _text(candidate.get("path_scope"), maximum=32) or "storage"
    if path_scope == "storage":
        path = _safe_root_path(storage_root, candidate_reference)
        approved_root = storage_root.resolve()
    elif path_scope == "repository":
        allowed_prefixes = (
            "work/boba/tool_recovery/workspaces/",
            f"work/boba/projects/{project_id}/code_surgeon/",
            f"work/boba/projects/{project_id}/output_quality_reviewer/",
        )
        if not candidate_reference.startswith(allowed_prefixes):
            raise ValidationError("Repository output is outside approved BOBA output roots.")
        path = _safe_root_path(repository_root, candidate_reference)
        approved_root = repository_root.resolve()
    else:
        raise ValidationError("The reviewed output path scope is unsupported.")
    if path.exists():
        resolved_existing = path.resolve()
        if (
            resolved_existing != approved_root
            and approved_root not in resolved_existing.parents
        ):
            raise ValidationError("The reviewed output uses an external symlink.")
    artifact_kind = _artifact_type(candidate_reference)
    supplied_kind = candidate.get("artifact_type")
    if supplied_kind in {
        "video",
        "audio",
        "caption",
        "JSON",
        "image",
        "manifest",
        "multi_artifact_bundle",
        "unknown",
    }:
        artifact_kind = supplied_kind
    if artifact_kind == "unknown":
        raise ValidationError("The reviewed output type is unsupported.")
    expected = _expected_from_metadata(candidate)
    artifact_id = _text(
        candidate.get("artifact_id") or candidate.get("output_artifact_id"),
        maximum=160,
    ) or _stable_id("output_artifact", project_id, candidate_reference)
    artifact = BobaReviewedOutputArtifactV1(
        output_artifact_id=artifact_id,
        project_id=project_id,
        clip_id=expected["clip_id"],
        sanitized_artifact_reference=candidate_reference,
        artifact_type=artifact_kind,
        origin_module=_text(candidate.get("origin_module"), maximum=160),
        origin_run_id=_text(candidate.get("origin_run_id"), maximum=160),
        origin_attempt_id=_text(candidate.get("origin_attempt_id"), maximum=160),
        generated_at=expected["generated_at"],
        expected_source_window=expected["expected_source_window"],
        expected_duration_seconds=expected["expected_duration_seconds"],
        expected_resolution=expected["expected_resolution"],
        expected_frame_rate=expected["expected_frame_rate"],
        expected_audio=expected["expected_audio"],
        expected_captions=expected["expected_captions"],
        checksum=expected["checksum"],
        file_size_bytes=expected["file_size_bytes"],
        accepted_output_protected=bool(candidate.get("accepted_output_protected", True)),
        source_media_reference=source_reference,
        source_media_read_only=True,
        rights_status=_text(rights_status, maximum=80) or "unknown",
        warnings=_unique(_list(candidate.get("warnings")), limit=64),
    )
    source_types: dict[str, BobaOutputReviewSourceTypeV1] = {
        "normal_render": "normal_render",
        "tool_recovery_output": "tool_recovery_output",
        "code_surgeon_behavior_validation": (
            "code_surgeon_behavior_validation"
        ),
        "checkpoint_restored_output": "checkpoint_restored_output",
        "rerendered_output": "rerendered_output",
        "fallback_output": "fallback_output",
        "imported_local_output": "imported_local_output",
        "unknown": "unknown",
    }
    source_type = source_types.get(str(candidate.get("source_type")), "unknown")
    return ResolvedReviewedOutputV1(
        artifact=artifact,
        path=path,
        metadata=dict(candidate),
        source_type=source_type,
        path_scope=path_scope,
    )


def _nested_values(
    value: Any,
    names: set[str],
    *,
    depth: int = 0,
    limit: int = 32,
) -> list[Any]:
    if depth > 7:
        return []
    values: list[Any] = []
    if isinstance(value, BobaContract):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in names:
                values.append(item)
                if len(values) >= limit:
                    return values
            values.extend(
                _nested_values(item, names, depth=depth + 1, limit=limit - len(values))
            )
            if len(values) >= limit:
                return values
    elif isinstance(value, list | tuple):
        for item in value[:64]:
            values.extend(
                _nested_values(item, names, depth=depth + 1, limit=limit - len(values))
            )
            if len(values) >= limit:
                return values
    return values[:limit]


def _first_nested(value: Any, *names: str) -> Any:
    values = _nested_values(value, {name.casefold() for name in names}, limit=1)
    return values[0] if values else None


def _status_from_bool(value: Any) -> BobaTechnicalQualityStatusV1:
    if value is True:
        return "passed"
    if value is False:
        return "failed"
    return "unavailable"


def _actual_source_window(metadata: Mapping[str, Any]) -> dict[str, float]:
    entry = _mapping(metadata.get("manifest_entry") or metadata.get("render_entry"))
    entry_metadata = _mapping(entry.get("metadata"))
    timeline = _mapping(
        metadata.get("actual_source_window")
        or metadata.get("timeline")
        or entry_metadata.get("timeline")
    )
    start = _float(
        timeline.get("start_seconds"),
        _float(
            timeline.get("repaired_start_seconds"),
            _float(
                timeline.get("source_start"),
                _float(timeline.get("requested_start_seconds")),
            ),
        ),
    )
    end = _float(
        timeline.get("end_seconds"),
        _float(
            timeline.get("repaired_end_seconds"),
            _float(
                timeline.get("source_end"),
                _float(timeline.get("requested_end_seconds")),
            ),
        ),
    )
    if start is None or end is None or end < start:
        return {}
    return {"start_seconds": round(start, 3), "end_seconds": round(end, 3)}


def _render_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    entry = _mapping(metadata.get("manifest_entry") or metadata.get("render_entry"))
    return _mapping(entry.get("metadata") or metadata.get("render_metadata"))


def _recovery_validation(
    tool_recovery: JsonMapping,
    *,
    output_reference: str,
    origin_attempt_id: str,
) -> dict[str, Any]:
    report = _mapping(tool_recovery)
    for raw in reversed(_list(report.get("output_validations"))):
        item = _mapping(raw)
        if (
            output_reference
            and _text(item.get("output_artifact_ref"), maximum=500) == output_reference
        ) or (
            origin_attempt_id
            and _text(item.get("recovery_attempt_id"), maximum=160)
            == origin_attempt_id
        ):
            return item
    return {}


def _quality_requirements(
    *,
    artifact: BobaReviewedOutputArtifactV1,
    explicit_required: Sequence[str],
    explicit_non_negotiable: Sequence[str],
    repair_planner: JsonMapping,
    tool_recovery: JsonMapping,
) -> tuple[list[str], list[str], bool, bool]:
    required = [
        "Exact generated output identity remains unchanged.",
        "Artifact integrity and expected media streams remain valid.",
        "Expected source window and duration remain preserved.",
        "Required validation evidence remains truthful and available.",
    ]
    if artifact.expected_audio is True:
        required.append("Required audio remains present and synchronized.")
    if artifact.expected_captions is True:
        required.append("Required captions remain present, bounded, and synchronized.")
    required.extend(explicit_required)
    non_negotiable = [
        "Source media remains unchanged.",
        "Reviewed output remains unchanged.",
        "No missing, duplicated, or truncated required content.",
        "Expected duration, resolution, frame rate, and required streams remain valid.",
        "A/V synchronization stays within the accepted tolerance.",
        "Correct source section and complete story meaning are preserved.",
    ]
    if artifact.expected_captions is True:
        non_negotiable.append("Required captions remain complete and synchronized.")
    non_negotiable.extend(explicit_non_negotiable)
    repair_used = False
    planner = _mapping(repair_planner)
    for raw in _list(planner.get("quality_preservation_plans")):
        plan = _mapping(raw)
        required.extend(_list(plan.get("original_requirements")))
        required.extend(_list(plan.get("technical_quality_checks")))
        required.extend(_list(plan.get("creative_quality_checks")))
        non_negotiable.extend(_list(plan.get("non_negotiable_requirements")))
        repair_used = True
    recovery_used = False
    recovery = _mapping(tool_recovery)
    for raw in [
        *_list(recovery.get("recovery_cases")),
        *_list(recovery.get("recovery_plans")),
    ]:
        item = _mapping(raw)
        values = _list(item.get("quality_requirements"))
        if values:
            required.extend(values)
            recovery_used = True
    return (
        _unique(required, limit=64),
        _unique(non_negotiable, limit=64),
        repair_used,
        recovery_used,
    )


def validate_caption_events(
    events: Sequence[Mapping[str, Any]],
    *,
    clip_duration_seconds: float | None,
) -> dict[str, Any]:
    """Validate bounded caption timing without modifying caption artifacts."""

    normalized: list[tuple[float, float, str]] = []
    warnings: list[str] = []
    errors: list[str] = []
    previous_start = -1.0
    previous_end = -1.0
    for index, raw in enumerate(list(events)[:1_000]):
        event = _mapping(raw)
        start = _float(event.get("start"), _float(event.get("start_seconds")))
        end = _float(event.get("end"), _float(event.get("end_seconds")))
        text = _text(event.get("text"), maximum=500)
        if start is None or end is None or start < 0 or end <= start:
            errors.append(f"Caption {index + 1} has invalid timestamps.")
            continue
        if start + 0.001 < previous_start:
            errors.append(f"Caption {index + 1} is not monotonic.")
        if previous_end > start + 0.01:
            errors.append(f"Caption {index + 1} overlaps the prior caption.")
        if clip_duration_seconds is not None and end > clip_duration_seconds + 0.01:
            errors.append(f"Caption {index + 1} ends after the output.")
        if not text:
            warnings.append(f"Caption {index + 1} has no readable text.")
        normalized.append((start, end, text))
        previous_start = start
        previous_end = end
    return {
        "event_count": len(normalized),
        "monotonic": not any("monotonic" in item for item in errors),
        "inside_bounds": not any("after the output" in item for item in errors),
        "overlap_corruption": any("overlaps" in item for item in errors),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _probe_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    parsed = parse_probe(dict(raw))
    streams = [_mapping(item) for item in _list(raw.get("streams"))]
    video = next(
        (item for item in streams if item.get("codec_type") == "video"),
        {},
    )
    audio = next(
        (item for item in streams if item.get("codec_type") == "audio"),
        {},
    )
    parsed.update(
        {
            "video_start_time": _float(video.get("start_time")),
            "audio_start_time": _float(audio.get("start_time")),
            "audio_channels": _int(audio.get("channels")),
            "frame_count": _int(video.get("nb_frames")),
            "format_name": _mapping(raw.get("format")).get("format_name"),
        }
    )
    return parsed


def _saved_probe(metadata: Mapping[str, Any]) -> dict[str, Any]:
    entry = _mapping(metadata.get("manifest_entry") or metadata.get("render_entry"))
    if not entry:
        return {}
    render_metadata = _mapping(entry.get("metadata"))
    sync = _mapping(
        render_metadata.get("sync_validation")
        or _mapping(render_metadata.get("timeline")).get("sync_validation")
    )
    return {
        "container_duration": _float(entry.get("duration")),
        "video_duration": _float(
            sync.get("actual_video_duration"),
            _float(entry.get("duration")),
        ),
        "audio_duration": _float(
            sync.get("actual_audio_duration"),
            _float(entry.get("duration")) if entry.get("has_audio") else None,
        ),
        "width": _int(entry.get("width")),
        "height": _int(entry.get("height")),
        "video_codec": entry.get("video_codec"),
        "audio_codec": entry.get("audio_codec"),
        "audio_sample_rate": _int(entry.get("audio_sample_rate")),
        "audio_channels": _int(entry.get("audio_channels")),
        "fps": _float(entry.get("fps")),
        "has_audio": bool(entry.get("has_audio")),
        "stream_count": 2 if entry.get("has_audio") else 1,
        "file_size_bytes": _int(entry.get("size_bytes")),
        "video_start_time": _float(sync.get("actual_video_start_time")),
        "audio_start_time": _float(sync.get("actual_audio_start_time")),
        "frame_count": _int(entry.get("frame_count")),
        "format_name": entry.get("container"),
        "saved_sync_validation": sync,
    }


class _EvidenceCollector:
    def __init__(
        self,
        *,
        review_case_id: str,
        output_reference: str,
    ) -> None:
        self.review_case_id = review_case_id
        self.output_reference = output_reference
        self.items: list[BobaOutputQualityEvidenceV1] = []

    def add(
        self,
        *,
        source_type: BobaQualityEvidenceSourceTypeV1,
        source_id: str,
        category: str,
        summary: str,
        observed: Any = None,
        expected: Any = None,
        reliability: BobaQualityEvidenceReliabilityV1 = "unknown",
        confidence: float = 0.0,
        supports_acceptance: bool = False,
        supports_rejection: bool = False,
        human: bool = False,
        warnings: Sequence[str] = (),
    ) -> str:
        evidence_id = _stable_id(
            "quality_evidence",
            self.review_case_id,
            source_type,
            category,
            len(self.items),
        )
        self.items.append(
            BobaOutputQualityEvidenceV1(
                evidence_id=evidence_id,
                source_type=source_type,
                source_id=_text(source_id, maximum=200) or "unknown",
                category=_text(category, maximum=160) or "unknown",
                bounded_summary=_text(summary, maximum=900) or "Evidence unavailable.",
                observed_value=_safe_json_value(observed),
                expected_value=_safe_json_value(expected),
                reliability=reliability,
                confidence=_unit(confidence),
                supports_acceptance=supports_acceptance,
                supports_rejection=supports_rejection,
                requires_human_interpretation=human,
                warnings=_unique(warnings, limit=32),
            )
        )
        return evidence_id


def _check_status(
    checks: Sequence[BobaTechnicalQualityCheckV1],
    categories: set[str],
) -> BobaTechnicalQualityStatusV1:
    selected = [item for item in checks if item.category in categories]
    if not selected:
        return "not_required"
    statuses = {item.status for item in selected}
    if "failed" in statuses:
        return "failed"
    if "unavailable" in statuses or "unknown" in statuses:
        return "unavailable"
    if "degraded" in statuses:
        return "degraded"
    if statuses <= {"not_required"}:
        return "not_required"
    return "passed"


def build_technical_quality_checks(
    *,
    resolved: ResolvedReviewedOutputV1,
    review_case_id: str,
    review_mode: BobaOutputReviewModeV1,
    registry: Mapping[str, BobaReadOnlyQualityValidatorV1],
    evidence_workspace: Path,
    collector: _EvidenceCollector,
    tool_recovery_validation: Mapping[str, Any],
    validation_artifacts: Mapping[str, Any],
    required_quality_properties: Sequence[str],
    signal_usage: BobaOutputQualitySignalUsageV1,
) -> BobaTechnicalQualityAssessmentV1:
    """Build technical checks from exact local bytes and saved validation truth."""

    artifact = resolved.artifact
    path = resolved.path
    metadata = resolved.metadata
    checks: list[BobaTechnicalQualityCheckV1] = []
    warnings: list[str] = []
    limitations: list[str] = []

    def add_check(
        category: BobaTechnicalQualityCategoryV1,
        name: str,
        *,
        required: bool,
        status: BobaTechnicalQualityStatusV1,
        observed: Any = None,
        expected: Any = None,
        tolerance: Any = None,
        source_type: BobaQualityEvidenceSourceTypeV1 = "unknown",
        reliability: BobaQualityEvidenceReliabilityV1 = "unknown",
        summary: str = "",
        failure: str = "",
        human: bool = False,
        check_warnings: Sequence[str] = (),
    ) -> BobaTechnicalQualityCheckV1:
        evidence_id = collector.add(
            source_type=source_type,
            source_id=artifact.output_artifact_id,
            category=category,
            summary=summary
            or (
                f"{name} passed."
                if status == "passed"
                else f"{name} did not pass."
            ),
            observed=observed,
            expected=expected,
            reliability=reliability,
            confidence=1.0 if reliability == "high" else 0.75 if reliability == "medium" else 0.4,
            supports_acceptance=status == "passed",
            supports_rejection=status == "failed",
            human=human,
            warnings=check_warnings,
        )
        check = BobaTechnicalQualityCheckV1(
            technical_check_id=_stable_id(
                "technical_check", review_case_id, category, len(checks)
            ),
            review_case_id=review_case_id,
            category=category,
            name=name,
            required=required,
            status=status,
            observed_value=_safe_json_value(observed),
            expected_value=_safe_json_value(expected),
            tolerance=_safe_json_value(tolerance),
            evidence_ids=[evidence_id],
            blocks_acceptance=required and status in {"failed", "unavailable", "unknown"},
            failure_summary=_text(failure, maximum=900),
            human_review_needed=human or status in {"degraded", "unavailable"},
            warnings=_unique(check_warnings, limit=32),
        )
        checks.append(check)
        return check

    exists = path.is_file()
    add_check(
        "artifact_exists",
        "Generated output exists",
        required=True,
        status="passed" if exists else "failed",
        observed=exists,
        expected=True,
        source_type="render_manifest"
        if resolved.source_type == "normal_render"
        else "tool_recovery_validation"
        if resolved.source_type == "tool_recovery_output"
        else "unknown",
        reliability="high",
        summary=(
            "The exact allowlisted generated output exists."
            if exists
            else "The exact allowlisted generated output is missing."
        ),
        failure="Checkpoint or review target exists in metadata but its output file is missing.",
    )
    size = path.stat().st_size if exists else 0
    add_check(
        "artifact_non_empty",
        "Generated output is non-empty",
        required=True,
        status="passed" if size > 0 else "failed",
        observed=size,
        expected="greater than zero bytes",
        source_type="checksum",
        reliability="high",
        summary=(
            f"The exact output contains {size} bytes."
            if size > 0
            else "The exact output is empty or unavailable."
        ),
        failure="The generated artifact has no bytes.",
    )

    actual_checksum = ""
    checksum_before = ""
    if exists and size > 0:
        checksum_before = _checksum(path)
        actual_checksum = checksum_before
        signal_usage.checksum_validation_used = True
    checksum_required = bool(artifact.checksum)
    checksum_status: BobaTechnicalQualityStatusV1
    if not checksum_required:
        checksum_status = "not_required"
    elif not actual_checksum:
        checksum_status = "failed"
    else:
        checksum_status = "passed" if actual_checksum == artifact.checksum else "failed"
    add_check(
        "checksum",
        "Output checksum matches",
        required=checksum_required,
        status=checksum_status,
        observed=actual_checksum or None,
        expected=artifact.checksum or None,
        source_type="checksum",
        reliability="high" if actual_checksum else "unavailable",
        summary=(
            "The local output checksum matches the saved identity."
            if checksum_status == "passed"
            else "No saved checksum was required."
            if checksum_status == "not_required"
            else "The local output checksum does not match the saved identity."
        ),
        failure="The exact output bytes differ from the saved artifact checksum.",
    )

    manifest_entry = _mapping(
        metadata.get("manifest_entry") or metadata.get("render_entry")
    )
    manifest_required = resolved.source_type in {
        "normal_render",
        "checkpoint_restored_output",
        "rerendered_output",
        "fallback_output",
    }
    manifest_matches = bool(
        manifest_entry
        and _text(manifest_entry.get("storage_key"), maximum=500)
        == artifact.sanitized_artifact_reference
        and (
            not manifest_entry.get("checksum")
            or not actual_checksum
            or manifest_entry.get("checksum") == actual_checksum
        )
    )
    add_check(
        "manifest",
        "Render manifest identity matches",
        required=manifest_required,
        status=(
            "passed"
            if manifest_matches
            else "failed"
            if manifest_required
            else "not_required"
        ),
        observed={
            "storage_key": manifest_entry.get("storage_key"),
            "checksum": manifest_entry.get("checksum"),
        }
        if manifest_entry
        else None,
        expected={
            "storage_key": artifact.sanitized_artifact_reference,
            "checksum": actual_checksum or artifact.checksum,
        },
        source_type="render_manifest",
        reliability="high" if manifest_entry else "unavailable",
        summary=(
            "The canonical render manifest identifies the exact reviewed bytes."
            if manifest_matches
            else "No render manifest is required for this artifact."
            if not manifest_required
            else "The render manifest does not identify the exact reviewed bytes."
        ),
        failure="The manifest storage key or checksum does not match the output.",
    )

    schema_required = artifact.artifact_type in {"JSON", "manifest"}
    schema_valid: bool | None = None
    if schema_required and exists and size > 0:
        try:
            schema_valid = isinstance(
                json.loads(path.read_text(encoding="utf-8-sig")), dict
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            schema_valid = False
    add_check(
        "schema",
        "Artifact schema is readable",
        required=schema_required,
        status=(
            _status_from_bool(schema_valid) if schema_required else "not_required"
        ),
        observed=schema_valid,
        expected=True if schema_required else None,
        source_type="code_surgeon_validation"
        if resolved.source_type == "code_surgeon_behavior_validation"
        else "unknown",
        reliability="high" if schema_valid is not None else "unavailable",
        failure="The JSON artifact cannot be parsed as an object.",
    )

    is_media = artifact.artifact_type in {"video", "audio"}
    local_mode = review_mode in {
        "local_technical_review",
        "full_available_evidence_review",
        "baseline_comparison",
    }
    probe: dict[str, Any] = {}
    probe_status: BobaTechnicalQualityStatusV1 = "not_required"
    probe_failure = ""
    if is_media:
        if local_mode and exists and size > 0:
            validator = registry.get("ffprobe_media")
            if validator and validator.available:
                evidence_workspace.mkdir(parents=True, exist_ok=True)
                command = _build_quality_ffprobe_command(
                    binary=str(validator.executable),
                    path=path.resolve(),
                )
                result = execute_read_only_quality_command(
                    validator_id="ffprobe_media",
                    command=command,
                    registry=registry,
                    reviewed_path=path,
                    working_directory=evidence_workspace,
                )
                signal_usage.local_ffprobe_used = True
                if result.exit_code == 0 and not result.timed_out:
                    try:
                        raw_probe = json.loads(result.stdout or "{}")
                        if isinstance(raw_probe, dict):
                            probe = _probe_payload(raw_probe)
                            probe_status = "passed"
                        else:
                            probe_status = "failed"
                            probe_failure = "FFprobe output was not a JSON object."
                    except json.JSONDecodeError:
                        probe_status = "failed"
                        probe_failure = "FFprobe returned malformed bounded JSON."
                else:
                    probe_status = "failed"
                    probe_failure = (
                        "FFprobe timed out."
                        if result.timed_out
                        else result.stderr or f"FFprobe exited {result.exit_code}."
                    )
                if result.output_truncated:
                    warnings.append("FFprobe output was bounded and truncated.")
            else:
                probe_status = "unavailable"
                probe_failure = "Registered FFprobe is unavailable."
                signal_usage.unavailable_signals.append("local_ffprobe")
        elif review_mode == "artifact_only":
            saved = _saved_probe(metadata)
            if saved:
                probe = saved
                probe_status = "passed"
                limitations.append(
                    "Media properties came from the saved render manifest; FFprobe was not rerun."
                )
            elif tool_recovery_validation.get("media_probe_valid") is True:
                probe_status = "degraded"
                limitations.append(
                    "Tool Recovery reported a valid probe, but detailed stream "
                    "values were unavailable."
                )
            else:
                probe_status = "unavailable"
        else:
            probe_status = "failed"
            probe_failure = "The media artifact is missing or empty."
    add_check(
        "media_probe",
        "Media probe succeeds",
        required=is_media,
        status=probe_status,
        observed=probe or tool_recovery_validation.get("media_probe_valid"),
        expected="readable local media metadata" if is_media else None,
        source_type=(
            "ffprobe"
            if signal_usage.local_ffprobe_used
            else "render_manifest"
            if probe
            else "tool_recovery_validation"
        ),
        reliability=(
            "high"
            if signal_usage.local_ffprobe_used and probe_status == "passed"
            else "medium"
            if probe_status in {"passed", "degraded"}
            else "unavailable"
        ),
        summary=(
            "FFprobe read the exact local output."
            if signal_usage.local_ffprobe_used and probe_status == "passed"
            else "Saved bounded media-probe evidence was reused."
            if probe_status in {"passed", "degraded"}
            else "Required media-probe evidence is unavailable or failed."
        ),
        failure=probe_failure,
        human=probe_status == "degraded",
    )

    decode_required = is_media and local_mode
    decode_status: BobaTechnicalQualityStatusV1 = (
        "not_required" if not decode_required else "unavailable"
    )
    decode_failure = ""
    if decode_required and exists and size > 0:
        validator = registry.get("ffmpeg_decode")
        if validator and validator.available:
            evidence_workspace.mkdir(parents=True, exist_ok=True)
            command = _build_quality_decode_command(
                binary=str(validator.executable),
                path=path.resolve(),
                expected_duration_seconds=artifact.expected_duration_seconds,
            )
            result = execute_read_only_quality_command(
                validator_id="ffmpeg_decode",
                command=command,
                registry=registry,
                reviewed_path=path,
                working_directory=evidence_workspace,
            )
            signal_usage.local_decode_check_used = True
            decode_status = (
                "passed"
                if result.exit_code == 0 and not result.timed_out
                else "failed"
            )
            decode_failure = (
                ""
                if decode_status == "passed"
                else "Bounded decode timed out."
                if result.timed_out
                else result.stderr or f"FFmpeg decode exited {result.exit_code}."
            )
            if result.output_truncated:
                warnings.append("Decode output was bounded and truncated.")
        else:
            signal_usage.unavailable_signals.append("local_decode_check")
            decode_failure = "Registered FFmpeg decode validator is unavailable."
    add_check(
        "decode",
        "Bounded media decode succeeds",
        required=decode_required,
        status=decode_status,
        observed=decode_status,
        expected="bounded decode exits successfully" if decode_required else None,
        source_type="decode_check",
        reliability="high" if signal_usage.local_decode_check_used else "unavailable",
        summary=(
            "A bounded decode of the exact output succeeded."
            if decode_status == "passed"
            else "Decode was not required in artifact-only review."
            if decode_status == "not_required"
            else "Required bounded decode evidence is unavailable or failed."
        ),
        failure=decode_failure,
    )

    saved_probe = _saved_probe(metadata)
    effective_probe = probe or saved_probe
    if not effective_probe and tool_recovery_validation:
        effective_probe = {
            "has_audio": (
                True
                if tool_recovery_validation.get("audio_presence_valid") is True
                else None
            )
        }
    video_present = bool(effective_probe.get("video_codec")) or (
        artifact.artifact_type == "video"
        and tool_recovery_validation.get("media_probe_valid") is True
    )
    video_required = artifact.artifact_type == "video"
    add_check(
        "video_stream",
        "Required video stream is present",
        required=video_required,
        status=(
            "passed"
            if video_present
            else "failed"
            if video_required and probe_status == "passed"
            else "unavailable"
            if video_required
            else "not_required"
        ),
        observed=effective_probe.get("video_codec"),
        expected="video stream" if video_required else None,
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if effective_probe else "unavailable",
        failure="The required video stream is missing.",
    )

    has_audio = effective_probe.get("has_audio")
    audio_required = artifact.expected_audio is True
    audio_disallowed = artifact.expected_audio is False
    audio_status: BobaTechnicalQualityStatusV1
    if audio_required:
        audio_status = (
            "passed"
            if has_audio is True
            else "failed"
            if has_audio is False
            else "unavailable"
        )
    elif audio_disallowed:
        audio_status = (
            "passed"
            if has_audio is False
            else "failed"
            if has_audio is True
            else "unavailable"
        )
    else:
        audio_status = "not_required"
    add_check(
        "audio_presence",
        "Audio presence matches the requirement",
        required=audio_required or audio_disallowed,
        status=audio_status,
        observed=has_audio,
        expected=artifact.expected_audio,
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if has_audio is not None else "unavailable",
        failure=(
            "Required audio is missing."
            if audio_required
            else "Audio is present even though this output forbids it."
            if audio_disallowed
            else ""
        ),
    )
    add_check(
        "audio_stream",
        "Required audio stream decodes",
        required=audio_required,
        status=audio_status if audio_required else "not_required",
        observed=effective_probe.get("audio_codec"),
        expected="audio stream" if audio_required else None,
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if has_audio is not None else "unavailable",
        failure="The required audio stream is missing.",
    )

    actual_duration = _float(effective_probe.get("container_duration"))
    expected_duration = artifact.expected_duration_seconds
    duration_required = expected_duration is not None and is_media
    duration_delta = (
        actual_duration - expected_duration
        if actual_duration is not None and expected_duration is not None
        else None
    )
    duration_status: BobaTechnicalQualityStatusV1
    if not duration_required:
        duration_status = "not_required"
    elif duration_delta is None:
        duration_status = "unavailable"
    else:
        duration_status = (
            "passed"
            if abs(duration_delta) <= _DURATION_TOLERANCE_SECONDS
            else "failed"
        )
    add_check(
        "duration",
        "Output duration matches",
        required=duration_required,
        status=duration_status,
        observed=actual_duration,
        expected=expected_duration,
        tolerance={"seconds": _DURATION_TOLERANCE_SECONDS},
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if actual_duration is not None else "unavailable",
        failure=(
            f"Output duration differs by {abs(duration_delta):.3f}s."
            if duration_delta is not None and duration_status == "failed"
            else "Required output duration could not be measured."
            if duration_status == "unavailable"
            else ""
        ),
    )

    expected_resolution = artifact.expected_resolution
    resolution_required = bool(expected_resolution) and artifact.artifact_type == "video"
    actual_resolution = {
        "width": _int(effective_probe.get("width")),
        "height": _int(effective_probe.get("height")),
    }
    actual_width = actual_resolution["width"]
    actual_height = actual_resolution["height"]
    resolution_known = all(value is not None for value in actual_resolution.values())
    resolution_matches = resolution_known and all(
        actual_resolution[key] == expected_resolution.get(key)
        for key in ("width", "height")
    )
    add_check(
        "resolution",
        "Output resolution matches",
        required=resolution_required,
        status=(
            "passed"
            if resolution_required and resolution_matches
            else "failed"
            if resolution_required and resolution_known
            else "unavailable"
            if resolution_required
            else "not_required"
        ),
        observed=actual_resolution if resolution_known else None,
        expected=expected_resolution or None,
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if resolution_known else "unavailable",
        failure="The rendered resolution does not match the approved specification.",
    )

    expected_width = _int(expected_resolution.get("width"))
    expected_height = _int(expected_resolution.get("height"))
    expected_aspect = (
        expected_width / expected_height
        if expected_width is not None
        and expected_height is not None
        and expected_height > 0
        else None
    )
    actual_aspect = (
        actual_width / actual_height
        if actual_width is not None
        and actual_height is not None
        and actual_height > 0
        else None
    )
    aspect_required = resolution_required
    aspect_delta = (
        abs(actual_aspect - expected_aspect)
        if actual_aspect is not None and expected_aspect is not None
        else None
    )
    add_check(
        "aspect_ratio",
        "Output aspect ratio matches",
        required=aspect_required,
        status=(
            "passed"
            if aspect_required and aspect_delta is not None and aspect_delta <= 0.01
            else "failed"
            if aspect_required and aspect_delta is not None
            else "unavailable"
            if aspect_required
            else "not_required"
        ),
        observed=round(actual_aspect, 4) if actual_aspect is not None else None,
        expected=round(expected_aspect, 4) if expected_aspect is not None else None,
        tolerance=0.01,
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if actual_aspect is not None else "unavailable",
        failure="The rendered aspect ratio does not match the approved specification.",
    )

    actual_fps = _float(effective_probe.get("fps"))
    expected_fps = artifact.expected_frame_rate
    fps_required = expected_fps is not None and artifact.artifact_type == "video"
    fps_delta = (
        abs(actual_fps - expected_fps)
        if actual_fps is not None and expected_fps is not None
        else None
    )
    add_check(
        "frame_rate",
        "Output frame rate matches",
        required=fps_required,
        status=(
            "passed"
            if fps_required and fps_delta is not None and fps_delta <= _FRAME_RATE_TOLERANCE
            else "failed"
            if fps_required and fps_delta is not None
            else "unavailable"
            if fps_required
            else "not_required"
        ),
        observed=actual_fps,
        expected=expected_fps,
        tolerance=_FRAME_RATE_TOLERANCE,
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if actual_fps is not None else "unavailable",
        failure="The output frame rate is outside the accepted tolerance.",
    )

    frame_count = _int(effective_probe.get("frame_count"))
    expected_frames = (
        round(actual_duration * actual_fps)
        if actual_duration is not None and actual_fps is not None
        else None
    )
    frame_anomaly = bool(
        frame_count is not None
        and expected_frames is not None
        and abs(frame_count - expected_frames) > max(2, round(actual_fps or 1.0))
    )
    add_check(
        "frame_count",
        "Frame count is plausible",
        required=False,
        status=(
            "degraded"
            if frame_anomaly
            else "passed"
            if frame_count is not None and expected_frames is not None
            else "unavailable"
        ),
        observed=frame_count,
        expected=expected_frames,
        tolerance={"frames": max(2, round(actual_fps or 1.0))},
        source_type="ffprobe",
        reliability="high" if frame_count is not None else "unavailable",
        summary=(
            "The reported frame count is plausible."
            if not frame_anomaly and frame_count is not None
            else "The reported frame count is anomalous."
            if frame_anomaly
            else "Frame count was not reported."
        ),
        human=frame_anomaly,
    )

    expected_sample_rate = _int(metadata.get("expected_audio_sample_rate"))
    if expected_sample_rate is None:
        expected_sample_rate = _int(
            _mapping(metadata.get("manifest_entry")).get("audio_sample_rate")
        )
    actual_sample_rate = _int(effective_probe.get("audio_sample_rate"))
    sample_required = audio_required and expected_sample_rate is not None
    add_check(
        "audio_sample_rate",
        "Audio sample rate matches",
        required=sample_required,
        status=(
            "passed"
            if sample_required and actual_sample_rate == expected_sample_rate
            else "failed"
            if sample_required and actual_sample_rate is not None
            else "unavailable"
            if sample_required
            else "not_required"
        ),
        observed=actual_sample_rate,
        expected=expected_sample_rate,
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if actual_sample_rate is not None else "unavailable",
        failure="The audio sample rate differs from the approved requirement.",
    )

    expected_channels = _int(metadata.get("expected_audio_channels"))
    actual_channels = _int(effective_probe.get("audio_channels"))
    channels_required = audio_required and expected_channels is not None
    add_check(
        "audio_channels",
        "Audio channels match",
        required=channels_required,
        status=(
            "passed"
            if channels_required and actual_channels == expected_channels
            else "failed"
            if channels_required and actual_channels is not None
            else "unavailable"
            if channels_required
            else "not_required"
        ),
        observed=actual_channels,
        expected=expected_channels,
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if actual_channels is not None else "unavailable",
        failure="The required audio channel count is missing or different.",
    )

    video_duration = _float(effective_probe.get("video_duration"), actual_duration)
    audio_duration = _float(effective_probe.get("audio_duration"))
    av_delta = (
        audio_duration - video_duration
        if audio_required
        and audio_duration is not None
        and video_duration is not None
        else None
    )
    video_start = _float(effective_probe.get("video_start_time"))
    audio_start = _float(effective_probe.get("audio_start_time"))
    stream_start_delta = (
        audio_start - video_start
        if audio_required and audio_start is not None and video_start is not None
        else None
    )
    saved_sync = _mapping(effective_probe.get("saved_sync_validation"))
    sync_required = audio_required and artifact.artifact_type == "video"
    sync_pass = bool(
        sync_required
        and (
            (
                av_delta is not None
                and abs(av_delta) <= _DURATION_TOLERANCE_SECONDS
                and (
                    stream_start_delta is None
                    or abs(stream_start_delta) <= _STREAM_START_TOLERANCE_SECONDS
                )
            )
            or (
                av_delta is None
                and saved_sync.get("passed") is True
                and tool_recovery_validation.get("audio_video_sync_valid") is not False
            )
        )
    )
    sync_known = (
        av_delta is not None
        or saved_sync.get("passed") is not None
        or tool_recovery_validation.get("audio_video_sync_valid") is not None
    )
    add_check(
        "audio_video_sync",
        "Audio and video timing match",
        required=sync_required,
        status=(
            "passed"
            if sync_pass
            else "failed"
            if sync_required and sync_known
            else "unavailable"
            if sync_required
            else "not_required"
        ),
        observed={
            "audio_video_delta": av_delta,
            "stream_start_delta": stream_start_delta,
            "saved_validation": saved_sync.get("passed"),
        },
        expected={
            "maximum_duration_delta_seconds": _DURATION_TOLERANCE_SECONDS,
            "maximum_start_delta_seconds": _STREAM_START_TOLERANCE_SECONDS,
        },
        tolerance={
            "duration_seconds": _DURATION_TOLERANCE_SECONDS,
            "start_seconds": _STREAM_START_TOLERANCE_SECONDS,
        },
        source_type="ffprobe" if signal_usage.local_ffprobe_used else "render_manifest",
        reliability="high" if av_delta is not None else "medium" if sync_known else "unavailable",
        failure="Audio/video stream timing is outside the accepted tolerance.",
    )

    expected_window = artifact.expected_source_window
    actual_window = _actual_source_window(metadata)
    source_window_required = bool(expected_window)
    source_window_matches = bool(
        expected_window
        and actual_window
        and all(
            abs(actual_window[key] - expected_window[key])
            <= _DURATION_TOLERANCE_SECONDS
            for key in ("start_seconds", "end_seconds")
        )
    )
    source_proxy_pass = (
        tool_recovery_validation.get("source_window_status") == "passed"
        and duration_status == "passed"
    )
    if source_window_required and source_window_matches:
        source_window_status: BobaTechnicalQualityStatusV1 = "passed"
    elif source_window_required and actual_window:
        source_window_status = "failed"
    elif source_window_required and source_proxy_pass:
        source_window_status = "degraded"
        limitations.append(
            "Tool Recovery source-window evidence is duration-based and does not "
            "prove content identity."
        )
    elif source_window_required:
        source_window_status = "unavailable"
    else:
        source_window_status = "not_required"
    signal_usage.source_window_validation_used = (
        source_window_status != "not_required"
    )
    add_check(
        "source_window",
        "Approved source window is preserved",
        required=source_window_required,
        status=source_window_status,
        observed=actual_window or {"duration_proxy": source_proxy_pass},
        expected=expected_window or None,
        tolerance={"seconds": _DURATION_TOLERANCE_SECONDS},
        source_type="source_window",
        reliability=(
            "high"
            if actual_window
            else "medium"
            if source_proxy_pass
            else "unavailable"
        ),
        summary=(
            "The persisted source start and end match the approved window."
            if source_window_matches
            else "Only a duration-based source-window proxy is available."
            if source_proxy_pass
            else "The approved source window is different or unavailable."
        ),
        failure="The reviewed output does not preserve the approved source window.",
        human=source_window_status == "degraded",
    )

    boundary = _mapping(
        validation_artifacts.get("boundary_quality")
        or _first_nested(metadata, "boundary_quality")
    )
    boundary_validation = _mapping(
        validation_artifacts.get("boundary_validation")
        or _first_nested(metadata, "boundary_validation")
    )
    truncation_flag = bool(
        validation_artifacts.get("truncation_detected")
        or boundary_validation.get("passed") is False
        or _list(boundary_validation.get("missing_final_words"))
        or (
            duration_delta is not None
            and duration_delta < -_DURATION_TOLERANCE_SECONDS
        )
        or _unit(boundary.get("abrupt_end_risk")) >= 0.75
    )
    add_check(
        "truncation",
        "Required content is not truncated",
        required=True,
        status="failed" if truncation_flag else "passed",
        observed={
            "truncation_detected": truncation_flag,
            "missing_final_words": _list(boundary_validation.get("missing_final_words")),
            "abrupt_end_risk": boundary.get("abrupt_end_risk"),
        },
        expected=False,
        source_type="boundary_quality",
        reliability="high" if boundary_validation else "medium",
        failure="The clip is shorter than planned or boundary evidence indicates truncation.",
    )

    requirements_text = " ".join(required_quality_properties).casefold()
    duplicate_required = "duplicat" in requirements_text
    missing_required = "missing" in requirements_text or "segment" in requirements_text
    duplicate_value = validation_artifacts.get("duplicate_segment_detected")
    if duplicate_value is None and boundary:
        duplicate_value = _unit(boundary.get("duplicate_risk")) >= 0.75
    missing_value = validation_artifacts.get("missing_segment_detected")
    add_check(
        "duplicate_segment",
        "No duplicate segment is present",
        required=duplicate_required,
        status=(
            "failed"
            if duplicate_value is True
            else "passed"
            if duplicate_value is False
            else "unavailable"
            if duplicate_required
            else "not_required"
        ),
        observed=duplicate_value,
        expected=False,
        source_type="boundary_quality",
        reliability="medium" if duplicate_value is not None else "unavailable",
        failure="Duplicate content evidence was detected.",
    )
    add_check(
        "missing_segment",
        "No required segment is missing",
        required=missing_required,
        status=(
            "failed"
            if missing_value is True
            else "passed"
            if missing_value is False
            else "unavailable"
            if missing_required
            else "not_required"
        ),
        observed=missing_value,
        expected=False,
        source_type="boundary_quality",
        reliability="medium" if missing_value is not None else "unavailable",
        failure="Required segment evidence indicates missing content.",
    )

    render_metadata = _render_metadata(metadata)
    caption_render = _mapping(
        validation_artifacts.get("caption_render_validation")
        or render_metadata.get("caption_render_validation")
        or _first_nested(metadata, "caption_render_validation")
    )
    caption_readability = _mapping(
        validation_artifacts.get("caption_readability_validation")
        or render_metadata.get("caption_readability_validation")
        or _first_nested(metadata, "caption_readability_validation")
    )
    raw_events = (
        validation_artifacts.get("caption_events")
        or metadata.get("caption_events")
        or _first_nested(metadata, "caption_events", "captions")
    )
    caption_events = [
        _mapping(item) for item in _list(raw_events) if isinstance(item, Mapping)
    ]
    caption_events_validation = (
        validate_caption_events(
            caption_events,
            clip_duration_seconds=actual_duration or expected_duration,
        )
        if caption_events
        else {}
    )
    captions_required = artifact.expected_captions is True
    caption_present = bool(
        caption_events
        or caption_render.get("passed") is True
        or manifest_entry.get("subtitles_included") is True
    )
    signal_usage.caption_validation_used = bool(
        captions_required or caption_render or caption_events_validation
    )
    add_check(
        "caption_presence",
        "Required captions are present",
        required=captions_required,
        status=(
            "passed"
            if captions_required and caption_present
            else "failed"
            if captions_required
            else "not_required"
        ),
        observed={
            "events": len(caption_events),
            "render_validation": caption_render.get("passed"),
            "manifest_included": manifest_entry.get("subtitles_included"),
        },
        expected=True if captions_required else None,
        source_type="caption_artifact",
        reliability="high" if caption_render else "medium" if caption_present else "unavailable",
        failure="Required captions are not proven present in the rendered output.",
    )
    caption_timing_status: BobaTechnicalQualityStatusV1
    if not captions_required:
        caption_timing_status = "not_required"
    elif caption_events_validation:
        caption_timing_status = (
            "passed" if caption_events_validation.get("passed") else "failed"
        )
    elif caption_readability.get("passed") is True and caption_render.get("passed") is True:
        caption_timing_status = "degraded"
        limitations.append(
            "Saved caption validation lacks the exact bounded event list for "
            "independent timing review."
        )
    else:
        caption_timing_status = "unavailable"
    add_check(
        "caption_timing",
        "Caption timestamps are monotonic",
        required=captions_required,
        status=caption_timing_status,
        observed=caption_events_validation or caption_readability or None,
        expected={"monotonic": True, "overlap_corruption": False},
        source_type="caption_artifact",
        reliability=(
            "high"
            if caption_events_validation
            else "medium"
            if caption_readability
            else "unavailable"
        ),
        failure="Caption timestamps are invalid, non-monotonic, or overlap.",
        human=caption_timing_status == "degraded",
    )
    add_check(
        "caption_bounds",
        "Captions remain inside output bounds",
        required=captions_required,
        status=(
            "passed"
            if captions_required
            and caption_events_validation.get("inside_bounds") is True
            else "failed"
            if captions_required
            and caption_events_validation
            and caption_events_validation.get("inside_bounds") is False
            else "degraded"
            if captions_required and caption_render.get("passed") is True
            else "unavailable"
            if captions_required
            else "not_required"
        ),
        observed=caption_events_validation or caption_render or None,
        expected={"inside_bounds": True},
        source_type="caption_artifact",
        reliability=(
            "high"
            if caption_events_validation
            else "medium"
            if caption_render
            else "unavailable"
        ),
        failure="A required caption extends beyond the reviewed output.",
        human=bool(captions_required and not caption_events_validation),
    )

    face_validation = _mapping(
        validation_artifacts.get("face_motion_validation")
        or _first_nested(metadata, "face_motion_validation_result_v1")
    )
    multi_validation = _mapping(
        validation_artifacts.get("multi_speaker_validation")
        or render_metadata.get("multi_speaker_validation")
        or _first_nested(metadata, "multi_speaker_layout_validation_result_v1")
    )
    face_expected = bool(
        _first_nested(metadata, "face_tracking_applied")
        or _first_nested(metadata, "face_tracking_plan")
    )
    multi_mode = _text(
        multi_validation.get("layout_strategy")
        or multi_validation.get("planned_mode")
        or _first_nested(metadata, "layout_strategy"),
        maximum=80,
    )
    multi_expected = multi_mode in {"two_speaker_stack", "active_speaker_focus"}
    if face_validation:
        signal_usage.face_motion_validation_used = True
    if multi_validation:
        signal_usage.multi_speaker_validation_used = True
    face_status: BobaTechnicalQualityStatusV1 = (
        _status_from_bool(face_validation.get("passed"))
        if face_validation
        else "unavailable"
        if face_expected
        else "not_required"
    )
    multi_status: BobaTechnicalQualityStatusV1 = (
        _status_from_bool(multi_validation.get("passed"))
        if multi_validation
        else "unavailable"
        if multi_expected
        else "not_required"
    )
    add_check(
        "face_tracking",
        "Face tracking validation passes",
        required=face_expected,
        status=face_status,
        observed=face_validation or None,
        expected={"passed": True} if face_expected else None,
        source_type="face_motion_validation",
        reliability="high" if face_validation else "unavailable",
        failure="Required face tracking validation failed or is unavailable.",
        human=face_status == "unavailable",
    )
    add_check(
        "multi_speaker_layout",
        "Multi-speaker layout validation passes",
        required=multi_expected,
        status=multi_status,
        observed=multi_validation or None,
        expected={"passed": True, "mode": multi_mode} if multi_expected else None,
        source_type="multi_speaker_validation",
        reliability="high" if multi_validation else "unavailable",
        failure="Required multi-speaker layout validation failed or is unavailable.",
        human=multi_status == "unavailable",
    )
    dimensions_vertical = bool(
        actual_width is not None
        and actual_height is not None
        and actual_height > actual_width
    )
    framing_required = artifact.artifact_type == "video"
    framing_status: BobaTechnicalQualityStatusV1 = (
        "failed"
        if framing_required and resolution_known and not dimensions_vertical
        else "failed"
        if face_status == "failed" or multi_status == "failed"
        else "passed"
        if framing_required
        and dimensions_vertical
        and face_status not in {"failed"}
        and multi_status not in {"failed"}
        else "unavailable"
        if framing_required
        else "not_required"
    )
    add_check(
        "framing",
        "Vertical framing evidence is acceptable",
        required=framing_required,
        status=framing_status,
        observed={
            "vertical_dimensions": dimensions_vertical,
            "face_validation": face_status,
            "multi_speaker_validation": multi_status,
        },
        expected={"vertical": True},
        source_type="face_motion_validation"
        if face_validation
        else "multi_speaker_validation"
        if multi_validation
        else "render_manifest",
        reliability=(
            "high"
            if face_validation or multi_validation
            else "medium"
            if resolution_known
            else "unavailable"
        ),
        failure="The output is not vertical or required framing validation failed.",
        human=not bool(face_validation or multi_validation),
    )
    subject_required = face_expected or multi_expected
    subject_status: BobaTechnicalQualityStatusV1 = (
        "failed"
        if face_validation.get("face_cutoff_detected") is True
        or multi_validation.get("subject_cutoff_detected") is True
        else "passed"
        if subject_required
        and (
            face_validation.get("face_crop_safety_evaluated") is True
            or multi_validation.get("subject_region_safety_evaluated") is True
        )
        else "unavailable"
        if subject_required
        else "not_required"
    )
    add_check(
        "subject_visibility",
        "Intended subject remains visible",
        required=subject_required,
        status=subject_status,
        observed={
            "face_cutoff": face_validation.get("face_cutoff_detected"),
            "subject_cutoff": multi_validation.get("subject_cutoff_detected"),
        },
        expected={"subject_cutoff": False},
        source_type="face_motion_validation"
        if face_validation
        else "multi_speaker_validation",
        reliability="high" if face_validation or multi_validation else "unavailable",
        failure="Subject-region evidence indicates cutoff or is unavailable.",
        human=subject_status == "unavailable",
    )

    if exists and size > 0:
        checksum_after = _checksum(path)
        if checksum_before and checksum_after != checksum_before:
            mutation_evidence_id = collector.add(
                source_type="checksum",
                source_id=artifact.output_artifact_id,
                category="artifact_integrity",
                summary="The reviewed output changed while read-only validation was running.",
                observed=checksum_after,
                expected=checksum_before,
                reliability="high",
                confidence=1.0,
                supports_rejection=True,
            )
            checks.append(
                BobaTechnicalQualityCheckV1(
                    technical_check_id=_stable_id(
                        "technical_check", review_case_id, "artifact_integrity_after"
                    ),
                    review_case_id=review_case_id,
                    category="checksum",
                    name="Output remains unchanged during review",
                    required=True,
                    status="failed",
                    observed_value=checksum_after,
                    expected_value=checksum_before,
                    evidence_ids=[mutation_evidence_id],
                    blocks_acceptance=True,
                    failure_summary="Output bytes changed during the review window.",
                    human_review_needed=True,
                    warnings=[
                        "The reviewer did not write the output; an external mutation was detected."
                    ],
                )
            )

    failed_required = [
        item.name
        for item in checks
        if item.required and item.status == "failed"
    ]
    unavailable_required = [
        item.name
        for item in checks
        if item.required and item.status in {"unavailable", "unknown"}
    ]
    required_checks = [item for item in checks if item.required]
    required_passed = not failed_required and not unavailable_required
    passed_count = sum(item.status == "passed" for item in required_checks)
    technical_score = (
        round(passed_count / len(required_checks), 4) if required_checks else 0.0
    )
    return BobaTechnicalQualityAssessmentV1(
        technical_assessment_id=_stable_id(
            "technical_assessment", review_case_id
        ),
        review_case_id=review_case_id,
        checks=checks,
        artifact_integrity_status=_check_status(
            checks,
            {"artifact_exists", "artifact_non_empty", "checksum", "manifest", "schema"},
        ),
        decode_status=_check_status(checks, {"media_probe", "decode"}),
        stream_status=_check_status(
            checks, {"video_stream", "audio_stream", "audio_presence"}
        ),
        timing_status=_check_status(
            checks, {"duration", "audio_video_sync", "source_window", "truncation"}
        ),
        video_status=_check_status(
            checks,
            {"video_stream", "resolution", "aspect_ratio", "frame_rate", "frame_count"},
        ),
        audio_status=_check_status(
            checks,
            {
                "audio_stream",
                "audio_presence",
                "audio_sample_rate",
                "audio_channels",
            },
        ),
        caption_status=_check_status(
            checks, {"caption_presence", "caption_timing", "caption_bounds"}
        ),
        framing_status=_check_status(
            checks,
            {
                "framing",
                "subject_visibility",
                "face_tracking",
                "multi_speaker_layout",
            },
        ),
        source_window_status=_check_status(
            checks, {"source_window", "truncation", "missing_segment", "duplicate_segment"}
        ),
        synchronization_status=_check_status(checks, {"audio_video_sync"}),
        technical_score=technical_score,
        required_checks_passed=required_passed,
        failed_required_checks=_unique(failed_required, limit=64),
        unavailable_required_checks=_unique(unavailable_required, limit=64),
        technical_acceptance_eligible=required_passed,
        warnings=_unique(warnings, limit=64),
        limitations=_unique(limitations, limit=64),
    )


def _technical_check(
    assessment: BobaTechnicalQualityAssessmentV1,
    category: str,
) -> BobaTechnicalQualityCheckV1 | None:
    return next((item for item in assessment.checks if item.category == category), None)


def _creative_artifact(
    artifacts: Mapping[str, Any],
    name: str,
) -> dict[str, Any]:
    return _mapping(artifacts.get(name))


def build_creative_quality_dimensions(
    *,
    review_case_id: str,
    artifact: BobaReviewedOutputArtifactV1,
    technical: BobaTechnicalQualityAssessmentV1,
    creative_artifacts: Mapping[str, Any],
    collector: _EvidenceCollector,
    signal_usage: BobaOutputQualitySignalUsageV1,
) -> BobaCreativeQualityAssessmentV1:
    """Review saved creative evidence without converting plans into visual proof."""

    hook = _creative_artifact(creative_artifacts, "hook_retention")
    brief = _creative_artifact(creative_artifacts, "clip_brief")
    caption_motion = _creative_artifact(creative_artifacts, "caption_motion")
    music_mood = _creative_artifact(creative_artifacts, "music_mood")
    creative_direction = _creative_artifact(
        creative_artifacts, "creative_direction"
    )
    editorial = _creative_artifact(creative_artifacts, "editorial_decision")
    boundary = _creative_artifact(creative_artifacts, "boundary_quality")
    face = _creative_artifact(creative_artifacts, "face_motion_validation")
    multi = _creative_artifact(creative_artifacts, "multi_speaker_validation")
    render = _creative_artifact(creative_artifacts, "render_metadata")
    analysis = _creative_artifact(creative_artifacts, "analysis_signal")
    manual = _creative_artifact(creative_artifacts, "bounded_manual_review")

    signal_usage.hook_retention_used = bool(hook)
    signal_usage.clip_brief_used = bool(brief)
    signal_usage.caption_motion_used = bool(caption_motion)
    signal_usage.music_mood_used = bool(music_mood)
    signal_usage.creative_direction_used = bool(creative_direction)
    signal_usage.editorial_decision_used = bool(editorial)
    signal_usage.boundary_quality_used = bool(boundary)
    signal_usage.face_motion_validation_used = (
        signal_usage.face_motion_validation_used or bool(face)
    )
    signal_usage.multi_speaker_validation_used = (
        signal_usage.multi_speaker_validation_used or bool(multi)
    )
    signal_usage.bounded_manual_review_used = bool(manual)

    dimensions: list[BobaCreativeQualityDimensionV1] = []

    def evidence(
        *,
        source_type: BobaQualityEvidenceSourceTypeV1,
        category: str,
        summary: str,
        observed: Any,
        reliability: BobaQualityEvidenceReliabilityV1,
        acceptance: bool = False,
        rejection: bool = False,
        human: bool = False,
    ) -> str:
        return collector.add(
            source_type=source_type,
            source_id=artifact.clip_id or artifact.output_artifact_id,
            category=category,
            summary=summary,
            observed=observed,
            reliability=reliability,
            confidence=0.9 if reliability == "high" else 0.7 if reliability == "medium" else 0.35,
            supports_acceptance=acceptance,
            supports_rejection=rejection,
            human=human,
        )

    def add_dimension(
        name: BobaCreativeQualityDimensionNameV1,
        *,
        status: BobaCreativeQualityStatusV1,
        score: float,
        evidence_ids: Sequence[str] = (),
        positive: Sequence[str] = (),
        negative: Sequence[str] = (),
        uncertainty: str = "",
        human: bool = False,
        blocking: bool = False,
        warnings: Sequence[str] = (),
    ) -> BobaCreativeQualityDimensionV1:
        manual_dimensions = _mapping(manual.get("dimensions"))
        manual_value = _mapping(manual_dimensions.get(name))
        if manual_value:
            manual_status = manual_value.get("status")
            if manual_status in {
                "strong",
                "acceptable",
                "weak",
                "failed",
                "unavailable",
                "conflicting",
                "not_required",
                "unknown",
            }:
                status = manual_status
            score = _unit(manual_value.get("score"), score)
            positive = [
                *positive,
                *_list(manual_value.get("positive_findings")),
            ]
            negative = [
                *negative,
                *_list(manual_value.get("negative_findings")),
            ]
            human = status in {"unavailable", "conflicting", "unknown"}
            blocking = blocking or bool(manual_value.get("blocking"))
            manual_evidence = evidence(
                source_type="bounded_manual_review",
                category=name,
                summary="A bounded human review supplied evidence for this dimension.",
                observed=manual_value,
                reliability="high",
                acceptance=status in {"strong", "acceptable"},
                rejection=status == "failed",
            )
            evidence_ids = [*evidence_ids, manual_evidence]
        dimension = BobaCreativeQualityDimensionV1(
            creative_dimension_id=_stable_id(
                "creative_dimension", review_case_id, name
            ),
            review_case_id=review_case_id,
            dimension=name,
            status=status,
            score=_unit(score),
            evidence_ids=list(dict.fromkeys(evidence_ids))[:32],
            positive_findings=_unique(positive, limit=32),
            negative_findings=_unique(negative, limit=32),
            uncertainty=_text(uncertainty, maximum=900),
            requires_human_review=human,
            blocking=blocking,
            warnings=_unique(warnings, limit=32),
        )
        dimensions.append(dimension)
        return dimension

    hook_score_raw = _first_nested(
        hook or editorial or creative_direction,
        "hook_score",
        "hook_strength_score",
        "score",
    )
    hook_score = _unit(hook_score_raw)
    hook_line = _text(
        _first_nested(
            hook or brief or editorial,
            "hook_line",
            "hook_text",
            "primary_hook",
            "recommended_hook",
        ),
        maximum=500,
    )
    weak_hook = bool(_first_nested(hook or editorial, "weak_hook"))
    hook_has_evidence = bool(
        hook_line
        and (
            _first_nested(hook, "evidence", "evidence_ids", "reasoning")
            or brief
            or editorial
        )
    )
    hook_evidence_ids: list[str] = []
    if hook:
        hook_evidence_ids.append(
            evidence(
                source_type="hook_retention",
                category="hook_strength",
                summary=(
                    "Hook evidence includes a bounded opening line and supporting context."
                    if hook_has_evidence
                    else "A hook score exists without enough supporting delivery evidence."
                ),
                observed={"score": hook_score_raw, "hook_line": hook_line},
                reliability="medium" if hook_has_evidence else "low",
                acceptance=hook_has_evidence and hook_score >= 0.65 and not weak_hook,
                rejection=weak_hook or hook_score < 0.4,
                human=not hook_has_evidence,
            )
        )
    hook_status: BobaCreativeQualityStatusV1
    if not hook:
        hook_status = "unavailable"
    elif weak_hook or hook_score < 0.4:
        hook_status = "weak"
    elif hook_has_evidence and hook_score >= 0.75:
        hook_status = "strong"
    elif hook_has_evidence:
        hook_status = "acceptable"
    else:
        hook_status = "conflicting"
    add_dimension(
        "hook_strength",
        status=hook_status,
        score=hook_score,
        evidence_ids=hook_evidence_ids,
        positive=[f"Opening evidence: {hook_line}"] if hook_line else [],
        negative=["The saved hook is marked weak."] if weak_hook else [],
        uncertainty=(
            ""
            if hook_has_evidence
            else "A numeric hook score alone does not prove that the rendered opening works."
        ),
        human=hook_status in {"unavailable", "conflicting", "weak"},
    )

    hook_delivery_rendered = bool(
        _first_nested(render, "hook_editing")
        or _first_nested(render, "hook_motion_treatment")
    )
    add_dimension(
        "hook_delivery",
        status="acceptable" if hook_delivery_rendered else "unavailable",
        score=0.7 if hook_delivery_rendered else 0.0,
        evidence_ids=(
            [
                evidence(
                    source_type="render_manifest",
                    category="hook_delivery",
                    summary="The render manifest records a hook treatment plan as applied.",
                    observed=_first_nested(render, "hook_editing"),
                    reliability="medium",
                    acceptance=True,
                    human=True,
                )
            ]
            if hook_delivery_rendered
            else []
        ),
        positive=["Rendered metadata records a first-three-second hook treatment."]
        if hook_delivery_rendered
        else [],
        uncertainty=(
            "Metadata does not visually prove the quality of hook delivery."
            if hook_delivery_rendered
            else "No applied hook-delivery evidence is available."
        ),
        human=True,
    )

    completeness_raw = _first_nested(
        boundary or brief or editorial,
        "completeness_score",
        "story_completeness_score",
        "story_completion_score",
    )
    completeness = _unit(completeness_raw)
    payoff_present_value = _first_nested(
        boundary or brief or hook or editorial,
        "payoff_present",
        "payoff_preserved",
        "payoff_reached",
    )
    payoff_score_raw = _first_nested(
        boundary or hook or editorial,
        "payoff_score",
        "payoff_strength",
    )
    payoff_score = _unit(payoff_score_raw)
    weak_payoff = bool(_first_nested(hook or editorial, "weak_payoff"))
    payoff_end = _float(
        _first_nested(boundary or brief, "payoff_end_seconds", "payoff_time")
    )
    expected_end = artifact.expected_source_window.get("end_seconds")
    payoff_before_end = bool(
        payoff_end is not None
        and expected_end is not None
        and payoff_end <= expected_end + _DURATION_TOLERANCE_SECONDS
    )
    payoff_explicitly_missing = payoff_present_value is False or weak_payoff
    story_complete = bool(
        not payoff_explicitly_missing
        and completeness >= 0.65
        and (
            payoff_present_value is True
            or payoff_before_end
            or payoff_score >= 0.65
        )
    )
    story_evidence_ids: list[str] = []
    if boundary or brief or editorial:
        story_evidence_ids.append(
            evidence(
                source_type="boundary_quality" if boundary else "clip_brief",
                category="story_completeness",
                summary=(
                    "Saved source-boundary evidence reaches the planned payoff."
                    if story_complete
                    else "Saved evidence does not prove a complete setup-to-payoff arc."
                ),
                observed={
                    "completeness_score": completeness_raw,
                    "payoff_present": payoff_present_value,
                    "payoff_end_seconds": payoff_end,
                    "expected_end_seconds": expected_end,
                },
                reliability="high" if payoff_end is not None else "medium",
                acceptance=story_complete,
                rejection=payoff_explicitly_missing,
                human=not story_complete and not payoff_explicitly_missing,
            )
        )
    story_status: BobaCreativeQualityStatusV1 = (
        "failed"
        if payoff_explicitly_missing
        else "strong"
        if story_complete and completeness >= 0.8
        else "acceptable"
        if story_complete
        else "unavailable"
        if not (boundary or brief or editorial)
        else "weak"
    )
    add_dimension(
        "story_completeness",
        status=story_status,
        score=completeness,
        evidence_ids=story_evidence_ids,
        positive=["The planned source window includes a complete story arc."]
        if story_complete
        else [],
        negative=["The saved evidence says the payoff is missing."]
        if payoff_explicitly_missing
        else ["Story completeness is not sufficiently proven."]
        if story_status == "weak"
        else [],
        uncertainty=(
            "Story evidence is unavailable."
            if story_status == "unavailable"
            else ""
        ),
        human=story_status in {"weak", "unavailable"},
        blocking=story_status == "failed",
    )
    payoff_status: BobaCreativeQualityStatusV1 = (
        "failed"
        if payoff_explicitly_missing
        else "strong"
        if payoff_before_end and payoff_score >= 0.75
        else "acceptable"
        if payoff_before_end or payoff_present_value is True or payoff_score >= 0.65
        else "unavailable"
    )
    add_dimension(
        "payoff_preservation",
        status=payoff_status,
        score=payoff_score if payoff_score_raw is not None else completeness,
        evidence_ids=story_evidence_ids,
        positive=["Payoff evidence remains inside the approved clip window."]
        if payoff_status in {"strong", "acceptable"}
        else [],
        negative=["The planned payoff is absent or outside the output."]
        if payoff_status == "failed"
        else [],
        uncertainty="Payoff timing is not available." if payoff_status == "unavailable" else "",
        human=payoff_status == "unavailable",
        blocking=payoff_status == "failed",
    )

    abrupt_risk = _unit(
        _first_nested(boundary, "abrupt_end_risk", "abrupt_cut_risk")
    )
    pacing_score_raw = _first_nested(
        boundary or hook or creative_direction,
        "pacing_score",
        "retention_score",
    )
    pacing_score = _unit(pacing_score_raw)
    motion_overload = bool(
        _first_nested(caption_motion, "motion_overload", "excessive_motion")
        or "overload" in json.dumps(_safe_json_value(caption_motion)).casefold()
    )
    pacing_status: BobaCreativeQualityStatusV1 = (
        "failed"
        if abrupt_risk >= 0.75
        else "weak"
        if pacing_score_raw is not None and pacing_score < 0.4
        else "acceptable"
        if pacing_score_raw is not None
        else "unavailable"
    )
    pacing_evidence_ids: list[str] = []
    if boundary or hook:
        pacing_evidence_ids.append(
            evidence(
                source_type="boundary_quality" if boundary else "hook_retention",
                category="pacing",
                summary=(
                    "Pacing evidence is acceptable without assuming faster is better."
                    if pacing_status == "acceptable"
                    else "Pacing evidence is weak, abrupt, or incomplete."
                ),
                observed={
                    "pacing_score": pacing_score_raw,
                    "abrupt_end_risk": abrupt_risk,
                },
                reliability="medium",
                acceptance=pacing_status == "acceptable",
                rejection=pacing_status == "failed",
                human=pacing_status in {"weak", "unavailable"},
            )
        )
    add_dimension(
        "pacing",
        status=pacing_status,
        score=pacing_score,
        evidence_ids=pacing_evidence_ids,
        positive=["Pacing evidence avoids an abrupt ending."]
        if pacing_status == "acceptable"
        else [],
        negative=["Boundary evidence indicates an abrupt ending."]
        if pacing_status == "failed"
        else [],
        uncertainty=(
            "Pacing remains subjective; speed alone is not treated as quality."
        ),
        human=pacing_status in {"weak", "unavailable"},
        blocking=pacing_status == "failed",
    )

    clarity_available = bool(
        _first_nested(brief or editorial or analysis, "clarity", "clarity_score")
        or brief
    )
    clarity_score = _unit(
        _first_nested(brief or editorial or analysis, "clarity_score"),
        0.7 if clarity_available else 0.0,
    )
    add_dimension(
        "clarity",
        status="acceptable" if clarity_available else "unavailable",
        score=clarity_score,
        evidence_ids=(
            [
                evidence(
                    source_type="clip_brief",
                    category="clarity",
                    summary="The clip brief provides bounded context and meaning guidance.",
                    observed={
                        "context": _first_nested(brief, "context_caption", "story_summary"),
                        "clarity_score": clarity_score,
                    },
                    reliability="medium",
                    acceptance=True,
                    human=True,
                )
            ]
            if clarity_available
            else []
        ),
        uncertainty="Rendered meaning still requires human interpretation.",
        human=True,
    )

    emotion_available = bool(
        _first_nested(
            creative_direction or editorial or analysis,
            "emotional_arc",
            "emotional_beats",
            "emotion_score",
        )
    )
    add_dimension(
        "emotional_continuity",
        status="acceptable" if emotion_available else "unavailable",
        score=0.7 if emotion_available else 0.0,
        evidence_ids=(
            [
                evidence(
                    source_type="creative_direction",
                    category="emotional_continuity",
                    summary="Saved creative direction describes an emotional arc.",
                    observed=_first_nested(
                        creative_direction or editorial or analysis,
                        "emotional_arc",
                        "emotional_beats",
                    ),
                    reliability="medium",
                    human=True,
                )
            ]
            if emotion_available
            else []
        ),
        uncertainty="An emotional plan does not prove the rendered emotional effect.",
        human=True,
    )

    caption_presence_check = _technical_check(technical, "caption_presence")
    caption_timing_check = _technical_check(technical, "caption_timing")
    caption_bounds_check = _technical_check(technical, "caption_bounds")
    readability = _mapping(
        _first_nested(render or caption_motion, "caption_readability_validation")
    )
    caption_not_required = artifact.expected_captions is not True
    if caption_not_required:
        caption_status: BobaCreativeQualityStatusV1 = "not_required"
    elif readability.get("passed") is True and not readability.get("blocking"):
        caption_status = "acceptable"
    elif readability.get("blocking") is True or (
        caption_presence_check and caption_presence_check.status == "failed"
    ):
        caption_status = "failed"
    else:
        caption_status = "unavailable"
    caption_evidence_ids = list(
        dict.fromkeys(
            [
                *(caption_presence_check.evidence_ids if caption_presence_check else []),
                *(caption_timing_check.evidence_ids if caption_timing_check else []),
                *(caption_bounds_check.evidence_ids if caption_bounds_check else []),
            ]
        )
    )
    add_dimension(
        "caption_readability",
        status=caption_status,
        score=0.75 if caption_status == "acceptable" else 0.0,
        evidence_ids=caption_evidence_ids,
        positive=["Saved readability checks passed."] if caption_status == "acceptable" else [],
        negative=["Required caption readability evidence failed."]
        if caption_status == "failed"
        else [],
        uncertainty=(
            "No bounded visual frame evidence proves caption readability."
            if caption_status in {"acceptable", "unavailable"}
            and not manual
            else ""
        ),
        human=caption_status == "unavailable" or (caption_status == "acceptable" and not manual),
        blocking=caption_status == "failed",
    )
    caption_timing_status: BobaCreativeQualityStatusV1 = (
        "not_required"
        if caption_not_required
        else "acceptable"
        if caption_timing_check
        and caption_timing_check.status in {"passed", "degraded"}
        and caption_bounds_check
        and caption_bounds_check.status in {"passed", "degraded"}
        else "failed"
        if (
            caption_timing_check
            and caption_timing_check.status == "failed"
        )
        or (
            caption_bounds_check
            and caption_bounds_check.status == "failed"
        )
        else "unavailable"
    )
    add_dimension(
        "caption_timing",
        status=caption_timing_status,
        score=0.8 if caption_timing_status == "acceptable" else 0.0,
        evidence_ids=caption_evidence_ids,
        negative=["Caption timing or bounds failed."]
        if caption_timing_status == "failed"
        else [],
        uncertainty=(
            "Exact caption events are incomplete."
            if caption_timing_status == "unavailable"
            else ""
        ),
        human=caption_timing_status == "unavailable",
        blocking=caption_timing_status == "failed",
    )

    framing_check = _technical_check(technical, "framing")
    subject_check = _technical_check(technical, "subject_visibility")
    face_check = _technical_check(technical, "face_tracking")
    multi_check = _technical_check(technical, "multi_speaker_layout")

    def technical_creative_status(
        check: BobaTechnicalQualityCheckV1 | None,
        *,
        not_required: bool = False,
    ) -> BobaCreativeQualityStatusV1:
        if not_required:
            return "not_required"
        if check is None or check.status in {"unavailable", "unknown"}:
            return "unavailable"
        if check.status == "failed":
            return "failed"
        if check.status == "degraded":
            return "weak"
        return "acceptable"

    framing_status = technical_creative_status(framing_check)
    add_dimension(
        "vertical_framing",
        status=framing_status,
        score=0.8 if framing_status == "acceptable" else 0.35 if framing_status == "weak" else 0.0,
        evidence_ids=framing_check.evidence_ids if framing_check else [],
        positive=["Vertical dimensions and available framing checks passed."]
        if framing_status == "acceptable"
        else [],
        negative=["Required framing validation failed."] if framing_status == "failed" else [],
        uncertainty=(
            "Vertical dimensions alone do not prove visually pleasing framing."
            if framing_status == "acceptable" and not (face or multi or manual)
            else "Framing evidence is unavailable."
            if framing_status == "unavailable"
            else ""
        ),
        human=framing_status in {"weak", "unavailable"}
        or (framing_status == "acceptable" and not (face or multi or manual)),
        blocking=framing_status == "failed",
    )
    subject_status = technical_creative_status(
        subject_check,
        not_required=bool(subject_check and subject_check.status == "not_required"),
    )
    add_dimension(
        "subject_visibility",
        status=subject_status,
        score=0.8 if subject_status == "acceptable" else 0.0,
        evidence_ids=subject_check.evidence_ids if subject_check else [],
        negative=["Subject cutoff evidence failed."] if subject_status == "failed" else [],
        uncertainty="Subject visibility requires bounded visual evidence."
        if subject_status == "unavailable"
        else "",
        human=subject_status == "unavailable",
        blocking=subject_status == "failed",
    )
    face_status = technical_creative_status(
        face_check,
        not_required=bool(face_check and face_check.status == "not_required"),
    )
    add_dimension(
        "face_tracking",
        status=face_status,
        score=0.8 if face_status == "acceptable" else 0.0,
        evidence_ids=face_check.evidence_ids if face_check else [],
        negative=["Face tracking validation failed."] if face_status == "failed" else [],
        uncertainty="Face tracking was not required or could not be visually proven."
        if face_status in {"unavailable", "not_required"}
        else "",
        human=face_status == "unavailable",
        blocking=face_status == "failed",
    )
    multi_status = technical_creative_status(
        multi_check,
        not_required=bool(multi_check and multi_check.status == "not_required"),
    )
    add_dimension(
        "multi_speaker_layout",
        status=multi_status,
        score=0.8 if multi_status == "acceptable" else 0.0,
        evidence_ids=multi_check.evidence_ids if multi_check else [],
        negative=["Multi-speaker layout validation failed."] if multi_status == "failed" else [],
        uncertainty="Multi-speaker layout evidence is uncertain or not required."
        if multi_status in {"unavailable", "not_required"}
        else "",
        human=multi_status == "unavailable",
        blocking=multi_status == "failed",
    )

    motion_validation = _mapping(
        _first_nested(render, "motion_render_validation", "motion_safety_validation")
    )
    motion_status: BobaCreativeQualityStatusV1 = (
        "failed"
        if motion_overload or motion_validation.get("passed") is False
        else "acceptable"
        if motion_validation.get("passed") is True
        else "unavailable"
    )
    motion_evidence_ids: list[str] = []
    if caption_motion or motion_validation:
        motion_evidence_ids.append(
            evidence(
                source_type="caption_motion",
                category="motion_balance",
                summary=(
                    "Applied motion validation is available."
                    if motion_validation
                    else "Motion guidance exists, but applied visual quality is unproven."
                ),
                observed={
                    "validation": motion_validation,
                    "overload": motion_overload,
                },
                reliability="high" if motion_validation else "low",
                acceptance=motion_status == "acceptable",
                rejection=motion_status == "failed",
                human=not bool(motion_validation),
            )
        )
    add_dimension(
        "motion_balance",
        status=motion_status,
        score=0.75 if motion_status == "acceptable" else 0.0,
        evidence_ids=motion_evidence_ids,
        negative=["Motion overload or render validation failure was detected."]
        if motion_status == "failed"
        else [],
        uncertainty="Motion recommendations alone do not prove rendered balance."
        if not motion_validation
        else "",
        human=motion_status == "unavailable",
        blocking=motion_status == "failed",
    )
    transition_available = bool(
        _first_nested(render or creative_direction, "transitions", "transition_quality")
    )
    add_dimension(
        "transition_quality",
        status="acceptable" if transition_available else "unavailable",
        score=0.7 if transition_available else 0.0,
        uncertainty="Transition quality requires visual judgment.",
        human=True,
    )

    audio_check = _technical_check(technical, "audio_presence")
    sync_check = _technical_check(technical, "audio_video_sync")
    audio_required = artifact.expected_audio is True
    if not audio_required:
        audio_quality_status: BobaCreativeQualityStatusV1 = "not_required"
    elif audio_check and audio_check.status == "failed":
        audio_quality_status = "failed"
    elif (
        audio_check
        and audio_check.status == "passed"
        and sync_check
        and sync_check.status == "passed"
    ):
        audio_quality_status = "acceptable"
    else:
        audio_quality_status = "unavailable"
    audio_evidence_ids = list(
        dict.fromkeys(
            [
                *(audio_check.evidence_ids if audio_check else []),
                *(sync_check.evidence_ids if sync_check else []),
            ]
        )
    )
    add_dimension(
        "audio_clarity",
        status=audio_quality_status,
        score=0.7 if audio_quality_status == "acceptable" else 0.0,
        evidence_ids=audio_evidence_ids,
        uncertainty=(
            "Stream presence and timing do not prove dialogue clarity."
            if audio_quality_status == "acceptable"
            else "Audio clarity evidence is unavailable."
            if audio_quality_status == "unavailable"
            else ""
        ),
        human=audio_quality_status in {"acceptable", "unavailable"} and audio_required,
        blocking=audio_quality_status == "failed",
    )
    dialogue_evidence = _mapping(
        _first_nested(
            render or creative_artifacts,
            "speech_clarity_validation",
            "dialogue_intelligibility",
            "loudness_summary",
        )
    )
    dialogue_pass = bool(
        dialogue_evidence.get("passed") is True
        or dialogue_evidence.get("speech_clarity_passed") is True
    )
    dialogue_fail = bool(
        dialogue_evidence
        and (
            dialogue_evidence.get("passed") is False
            or dialogue_evidence.get("speech_clarity_passed") is False
        )
    )
    add_dimension(
        "dialogue_intelligibility",
        status=(
            "not_required"
            if not audio_required
            else "acceptable"
            if dialogue_pass
            else "failed"
            if dialogue_fail
            else "unavailable"
        ),
        score=0.8 if dialogue_pass else 0.0,
        evidence_ids=(
            [
                evidence(
                    source_type="analysis_signal",
                    category="dialogue_intelligibility",
                    summary="Bounded dialogue-clarity evidence is available.",
                    observed=dialogue_evidence,
                    reliability="medium",
                    acceptance=dialogue_pass,
                    rejection=dialogue_fail,
                    human=True,
                )
            ]
            if dialogue_evidence
            else []
        ),
        uncertainty="No bounded listening evidence proves dialogue intelligibility."
        if audio_required and not dialogue_evidence
        else "",
        human=audio_required and not dialogue_evidence,
        blocking=dialogue_fail,
    )

    music_validation = _mapping(
        _first_nested(render, "music_validation")
    )
    music_planned = bool(
        _first_nested(music_mood, "should_use_music", "music_required")
        or _first_nested(render, "music_mixed")
    )
    actual_music_evidence = bool(
        music_validation
        and (
            music_validation.get("mixed") is not None
            or music_validation.get("audible") is not None
        )
    )
    music_audible = music_validation.get("audible") is True
    speech_clear = music_validation.get("speech_clarity_passed") is True
    music_failed = bool(
        music_planned
        and actual_music_evidence
        and (
            music_validation.get("mixed") is False
            or music_validation.get("audible") is False
            or music_validation.get("speech_clarity_passed") is False
        )
    )
    music_status: BobaCreativeQualityStatusV1 = (
        "not_required"
        if not music_planned
        else "failed"
        if music_failed
        else "acceptable"
        if actual_music_evidence and music_audible and speech_clear
        else "unavailable"
    )
    music_evidence_ids: list[str] = []
    if music_mood:
        music_evidence_ids.append(
            evidence(
                source_type="music_mood",
                category="music_mood_fit",
                summary="Music Mood Brain supplies intent, not proof of the actual mix.",
                observed=_safe_json_value(music_mood),
                reliability="low",
                human=True,
            )
        )
    if actual_music_evidence:
        music_evidence_ids.append(
            evidence(
                source_type="render_manifest",
                category="music_dialogue_balance",
                summary="The render manifest contains bounded actual-mix validation.",
                observed=music_validation,
                reliability="medium",
                acceptance=music_status == "acceptable",
                rejection=music_status == "failed",
                human=True,
            )
        )
    add_dimension(
        "music_mood_fit",
        status=music_status,
        score=0.75 if music_status == "acceptable" else 0.0,
        evidence_ids=music_evidence_ids,
        positive=["Actual mix evidence reports audible music and preserved speech clarity."]
        if music_status == "acceptable"
        else [],
        negative=["Required music or speech-balance evidence failed."]
        if music_status == "failed"
        else [],
        uncertainty=(
            "Music mood metadata alone cannot prove that the rendered music fits."
            if music_planned and not actual_music_evidence
            else "Music fit remains a subjective listening judgment."
            if music_status == "acceptable"
            else ""
        ),
        human=music_planned and music_status in {"acceptable", "unavailable"},
        blocking=music_status == "failed",
    )
    add_dimension(
        "music_dialogue_balance",
        status=music_status,
        score=0.8 if music_status == "acceptable" else 0.0,
        evidence_ids=music_evidence_ids,
        uncertainty=(
            "No bounded actual-mix evidence is available."
            if music_planned and not actual_music_evidence
            else "Automated levels do not replace listening."
            if music_status == "acceptable"
            else ""
        ),
        human=music_planned and music_status in {"acceptable", "unavailable"},
        blocking=music_status == "failed",
    )

    duplicate_check = _technical_check(technical, "duplicate_segment")
    duplicate_risk = _unit(
        _first_nested(boundary or creative_artifacts, "duplicate_risk")
    )
    repetition_detected = bool(
        duplicate_check and duplicate_check.status == "failed"
    ) or duplicate_risk >= 0.75
    repetition_status: BobaCreativeQualityStatusV1 = (
        "failed"
        if repetition_detected
        else "acceptable"
        if duplicate_check and duplicate_check.status == "passed"
        else "unavailable"
    )
    add_dimension(
        "repetition",
        status=repetition_status,
        score=0.8 if repetition_status == "acceptable" else 0.0,
        evidence_ids=duplicate_check.evidence_ids if duplicate_check else [],
        negative=["Repeated or duplicated content evidence was detected."]
        if repetition_detected
        else [],
        uncertainty="Cross-clip repetition evidence is unavailable."
        if repetition_status == "unavailable"
        else "",
        human=repetition_status == "unavailable",
        blocking=repetition_status == "failed",
    )

    source_check = _technical_check(technical, "source_window")
    truncation_check = _technical_check(technical, "truncation")
    meaning_status: BobaCreativeQualityStatusV1 = (
        "failed"
        if story_status == "failed"
        or payoff_status == "failed"
        or (source_check and source_check.status == "failed")
        or (truncation_check and truncation_check.status == "failed")
        else "acceptable"
        if story_status in {"strong", "acceptable"}
        and payoff_status in {"strong", "acceptable"}
        and source_check
        and source_check.status in {"passed", "degraded"}
        else "unavailable"
    )
    add_dimension(
        "source_meaning_preservation",
        status=meaning_status,
        score=0.85 if meaning_status == "acceptable" else 0.0,
        evidence_ids=list(
            dict.fromkeys(
                [
                    *story_evidence_ids,
                    *(source_check.evidence_ids if source_check else []),
                    *(truncation_check.evidence_ids if truncation_check else []),
                ]
            )
        ),
        positive=["Source window, story, and payoff evidence remain aligned."]
        if meaning_status == "acceptable"
        else [],
        negative=["The output loses required source meaning or payoff."]
        if meaning_status == "failed"
        else [],
        uncertainty="Meaning preservation lacks complete source-linked evidence."
        if meaning_status == "unavailable"
        else "",
        human=meaning_status == "unavailable",
        blocking=meaning_status == "failed",
    )

    resolution_check = _technical_check(technical, "resolution")
    aspect_check = _technical_check(technical, "aspect_ratio")
    platform_status: BobaCreativeQualityStatusV1 = (
        "failed"
        if any(
            item and item.status == "failed"
            for item in (resolution_check, aspect_check)
        )
        else "acceptable"
        if all(
            item and item.status == "passed"
            for item in (resolution_check, aspect_check)
        )
        else "unavailable"
    )
    add_dimension(
        "platform_format_fit",
        status=platform_status,
        score=0.9 if platform_status == "acceptable" else 0.0,
        evidence_ids=list(
            dict.fromkeys(
                [
                    *(resolution_check.evidence_ids if resolution_check else []),
                    *(aspect_check.evidence_ids if aspect_check else []),
                ]
            )
        ),
        negative=["Output dimensions do not match the required vertical format."]
        if platform_status == "failed"
        else [],
        human=False,
        blocking=platform_status == "failed",
    )
    accessibility_status: BobaCreativeQualityStatusV1 = (
        "not_required"
        if artifact.expected_captions is not True
        else "acceptable"
        if caption_status == "acceptable"
        and caption_timing_status == "acceptable"
        else "failed"
        if "failed" in {caption_status, caption_timing_status}
        else "unavailable"
    )
    add_dimension(
        "accessibility",
        status=accessibility_status,
        score=0.75 if accessibility_status == "acceptable" else 0.0,
        evidence_ids=caption_evidence_ids,
        uncertainty="Caption accessibility requires visual confirmation."
        if accessibility_status == "acceptable" and not manual
        else "",
        human=accessibility_status in {"acceptable", "unavailable"}
        and artifact.expected_captions is True,
        blocking=accessibility_status == "failed",
    )

    available = [
        item
        for item in dimensions
        if item.status not in {"unavailable", "unknown", "not_required"}
    ]
    applicable = [item for item in dimensions if item.status != "not_required"]
    evidence_coverage = (
        round(len(available) / len(applicable), 4) if applicable else 0.0
    )
    scored = [item.score for item in available]
    creative_score = round(sum(scored) / len(scored), 4) if scored else 0.0
    blocking = [item for item in dimensions if item.blocking or item.status == "failed"]
    uncertainties = _unique(
        [
            item.uncertainty
            for item in dimensions
            if item.uncertainty
        ],
        limit=64,
    )
    human_required = bool(
        blocking
        or evidence_coverage < _MIN_CREATIVE_EVIDENCE_COVERAGE
        or any(item.requires_human_review for item in dimensions)
    )
    creative_eligible = bool(
        not blocking
        and evidence_coverage >= _MIN_CREATIVE_EVIDENCE_COVERAGE
        and not any(
            item.status in {"conflicting", "unknown"}
            for item in dimensions
        )
    )
    by_name = {item.dimension: item.status for item in dimensions}
    return BobaCreativeQualityAssessmentV1(
        creative_assessment_id=_stable_id(
            "creative_assessment", review_case_id
        ),
        review_case_id=review_case_id,
        dimensions=dimensions,
        hook_status=by_name.get("hook_strength", "unknown"),
        story_completeness_status=by_name.get("story_completeness", "unknown"),
        payoff_status=by_name.get("payoff_preservation", "unknown"),
        pacing_status=by_name.get("pacing", "unknown"),
        clarity_status=by_name.get("clarity", "unknown"),
        caption_readability_status=by_name.get("caption_readability", "unknown"),
        framing_quality_status=by_name.get("vertical_framing", "unknown"),
        subject_visibility_status=by_name.get("subject_visibility", "unknown"),
        motion_quality_status=by_name.get("motion_balance", "unknown"),
        audio_balance_status=by_name.get("music_dialogue_balance", "unknown"),
        music_fit_status=by_name.get("music_mood_fit", "unknown"),
        repetition_status=by_name.get("repetition", "unknown"),
        platform_fit_status=by_name.get("platform_format_fit", "unknown"),
        creative_score=creative_score,
        evidence_coverage=evidence_coverage,
        subjective_uncertainty=uncertainties,
        creative_acceptance_eligible=creative_eligible,
        human_review_required=human_required,
        warnings=(
            ["Automated creative review cannot replace every human visual judgment."]
            if human_required
            else []
        ),
        limitations=[
            "Creative scores summarize available evidence; they are not objective proof.",
            "No virality or production-performance guarantee is made.",
        ],
    )


def _assessment_observed(
    assessment: BobaTechnicalQualityAssessmentV1,
    category: str,
) -> Any:
    check = _technical_check(assessment, category)
    return check.observed_value if check else None


def _dimension_status(
    assessment: BobaCreativeQualityAssessmentV1,
    dimension: str,
) -> str | None:
    item = next(
        (value for value in assessment.dimensions if value.dimension == dimension),
        None,
    )
    return item.status if item else None


def _snapshot(
    *,
    resolved: ResolvedReviewedOutputV1,
    technical: BobaTechnicalQualityAssessmentV1 | None = None,
    creative: BobaCreativeQualityAssessmentV1 | None = None,
) -> dict[str, Any]:
    artifact = resolved.artifact
    metadata = resolved.metadata
    entry = _mapping(metadata.get("manifest_entry") or metadata.get("render_entry"))

    def observed(category: str, fallback: Any) -> Any:
        value = _assessment_observed(technical, category) if technical else None
        return fallback if value is None else value

    def technical_status(category: BobaTechnicalQualityCategoryV1) -> str | None:
        check = _technical_check(technical, category) if technical else None
        return check.status if check else None

    def persisted_status(*names: str) -> str | None:
        raw = _first_nested(metadata, *names)
        if isinstance(raw, Mapping):
            status = raw.get("status")
            if isinstance(status, str):
                raw = status
            elif isinstance(raw.get("passed"), bool):
                raw = "passed" if raw["passed"] else "failed"
            else:
                return None
        if isinstance(raw, bool):
            return "passed" if raw else "failed"
        if isinstance(raw, str):
            normalized = raw.strip().casefold().replace(" ", "_")
            if normalized in {
                "passed",
                "failed",
                "degraded",
                "unavailable",
                "not_required",
                "unknown",
                "strong",
                "acceptable",
                "weak",
                "conflicting",
            }:
                return normalized
        return None

    return {
        "resolution": observed(
            "resolution",
            {
                "width": _int(entry.get("width"))
                or artifact.expected_resolution.get("width"),
                "height": _int(entry.get("height"))
                or artifact.expected_resolution.get("height"),
            },
        ),
        "frame_rate": observed(
            "frame_rate",
            _float(entry.get("fps"), artifact.expected_frame_rate),
        ),
        "duration": observed(
            "duration",
            _float(entry.get("duration"), artifact.expected_duration_seconds),
        ),
        "source_window": observed(
            "source_window",
            _actual_source_window(metadata) or artifact.expected_source_window,
        ),
        "audio_presence": observed(
            "audio_presence",
            entry.get("has_audio")
            if entry.get("has_audio") is not None
            else artifact.expected_audio,
        ),
        "audio_video_sync": (
            technical_status("audio_video_sync")
            or persisted_status(
                "sync_validation",
                "audio_video_sync_status",
                "synchronization_status",
            )
        ),
        "caption_presence": observed(
            "caption_presence",
            entry.get("subtitles_included")
            if entry.get("subtitles_included") is not None
            else artifact.expected_captions,
        ),
        "caption_timing": technical_status("caption_timing")
        or persisted_status(
            "caption_timing_status",
            "caption_timing_validation",
        ),
        "framing": technical_status("framing")
        or persisted_status(
            "framing_status",
            "framing_validation",
        ),
        "story_completeness": (
            _dimension_status(creative, "story_completeness")
            if creative
            else persisted_status(
                "story_completeness_status",
                "story_completeness",
            )
        ),
        "hook": (
            _dimension_status(creative, "hook_strength")
            if creative
            else persisted_status("hook_status", "hook_strength_status")
        ),
        "payoff": (
            _dimension_status(creative, "payoff_preservation")
            if creative
            else persisted_status(
                "payoff_status",
                "payoff_preservation_status",
            )
        ),
        "pacing": (
            _dimension_status(creative, "pacing")
            if creative
            else persisted_status("pacing_status")
        ),
        "motion": (
            _dimension_status(creative, "motion_balance")
            if creative
            else persisted_status("motion_status", "motion_balance_status")
        ),
        "music_fit": (
            _dimension_status(creative, "music_mood_fit")
            if creative
            else persisted_status("music_fit_status", "music_mood_fit_status")
        ),
        "encoding": {
            "video_codec": entry.get("video_codec"),
            "audio_codec": entry.get("audio_codec"),
            "container": entry.get("container"),
        },
        "file_integrity": {
            "checksum": artifact.checksum,
            "size_bytes": artifact.file_size_bytes,
        },
    }


def _comparison_equal(category: str, baseline: Any, reviewed: Any) -> bool | None:
    if baseline is None or reviewed is None:
        return None
    if category == "duration":
        left = _float(baseline)
        right = _float(reviewed)
        return (
            None
            if left is None or right is None
            else abs(left - right) <= _DURATION_TOLERANCE_SECONDS
        )
    if category == "frame_rate":
        left = _float(baseline)
        right = _float(reviewed)
        return (
            None
            if left is None or right is None
            else abs(left - right) <= _FRAME_RATE_TOLERANCE
        )
    if category == "source_window":
        left_window = _mapping(baseline)
        right_window = _mapping(reviewed)
        if not left_window or not right_window:
            return None
        return all(
            abs(
                (_float(left_window.get(key), 0.0) or 0.0)
                - (_float(right_window.get(key), 0.0) or 0.0)
            )
            <= _DURATION_TOLERANCE_SECONDS
            for key in ("start_seconds", "end_seconds")
        )
    return bool(_safe_json_value(baseline) == _safe_json_value(reviewed))


def _regression_severity(
    category: str,
    baseline: Any,
    reviewed: Any,
) -> BobaOutputQualitySeverityV1:
    if category in {
        "audio_presence",
        "audio_video_sync",
        "source_window",
        "file_integrity",
        "story_completeness",
        "payoff",
    }:
        return "critical"
    if category in {"duration", "caption_presence", "caption_timing", "encoding"}:
        return "major"
    if category in {"resolution", "frame_rate", "framing", "hook"}:
        return "major"
    if category in {"pacing", "motion", "music_fit"}:
        return "moderate"
    return "minor"


def compare_output_to_baseline(
    *,
    review_case_id: str,
    reviewed: ResolvedReviewedOutputV1,
    baseline: ResolvedReviewedOutputV1,
    technical: BobaTechnicalQualityAssessmentV1,
    creative: BobaCreativeQualityAssessmentV1,
    collector: _EvidenceCollector,
    comparison_basis: BobaOutputComparisonBasisV1,
    non_negotiable_requirements: Sequence[str],
) -> tuple[BobaOutputBaselineComparisonV1, list[BobaOutputQualityRegressionV1]]:
    """Compare exact output identities and reject silent required-quality loss."""

    reviewed_snapshot = _snapshot(
        resolved=reviewed,
        technical=technical,
        creative=creative,
    )
    baseline_snapshot = _snapshot(resolved=baseline)
    technical_categories = {
        "resolution",
        "frame_rate",
        "duration",
        "source_window",
        "audio_presence",
        "audio_video_sync",
        "caption_presence",
        "caption_timing",
        "framing",
        "encoding",
        "file_integrity",
    }
    creative_categories = {
        "story_completeness",
        "hook",
        "payoff",
        "pacing",
        "motion",
        "music_fit",
    }
    default_non_negotiable = {
        "resolution",
        "frame_rate",
        "duration",
        "source_window",
        "audio_presence",
        "audio_video_sync",
        "caption_presence",
        "file_integrity",
        "story_completeness",
        "payoff",
    }
    requirement_text = " ".join(non_negotiable_requirements).casefold()
    preserved: list[str] = []
    improved: list[str] = []
    degraded: list[str] = []
    unknown: list[str] = []
    technical_differences: list[dict[str, Any]] = []
    creative_differences: list[dict[str, Any]] = []
    regressions: list[BobaOutputQualityRegressionV1] = []
    non_negotiable_regressions: list[str] = []
    disclosed_minor: list[str] = []
    disclosed_values = {
        _text(item, maximum=160).casefold()
        for item in _list(reviewed.metadata.get("disclosed_regressions"))
    }
    approved_values = {
        _text(item, maximum=160).casefold()
        for item in _list(reviewed.metadata.get("approved_regressions"))
    }

    for category, baseline_value in baseline_snapshot.items():
        reviewed_value = reviewed_snapshot.get(category)
        equal = _comparison_equal(category, baseline_value, reviewed_value)
        difference = {
            "category": category,
            "baseline": _safe_json_value(baseline_value),
            "reviewed": _safe_json_value(reviewed_value),
            "equivalent": equal,
        }
        if category in technical_categories:
            technical_differences.append(difference)
        elif category in creative_categories:
            creative_differences.append(difference)
        if equal is None:
            unknown.append(category)
            continue
        if equal:
            preserved.append(category)
            continue

        severity = _regression_severity(category, baseline_value, reviewed_value)
        words = category.replace("_", " ")
        explicit_non_negotiable = any(
            token in requirement_text
            for token in {
                category.casefold(),
                words.casefold(),
                "caption" if category.startswith("caption") else "",
                "audio" if category.startswith("audio") else "",
            }
            if token
        )
        non_negotiable = category in default_non_negotiable or explicit_non_negotiable
        disclosed = category.casefold() in disclosed_values
        approved = category.casefold() in approved_values
        impact: BobaOutputRegressionAcceptanceImpactV1 = (
            "reject"
            if non_negotiable or severity in {"major", "critical"}
            else "human_review"
            if severity == "moderate"
            else "disclose"
        )
        if approved and disclosed and severity in {"negligible", "minor"}:
            impact = "disclose"
        evidence_id = collector.add(
            source_type="render_manifest",
            source_id=baseline.artifact.output_artifact_id,
            category=f"baseline_{category}",
            summary=f"Baseline comparison found a {words} difference.",
            observed=reviewed_value,
            expected=baseline_value,
            reliability="high"
            if category in technical_categories
            else "medium",
            confidence=0.95 if category in technical_categories else 0.7,
            supports_rejection=impact == "reject",
            human=category in creative_categories or impact == "human_review",
        )
        regression = BobaOutputQualityRegressionV1(
            quality_regression_id=_stable_id(
                "quality_regression", review_case_id, category
            ),
            review_case_id=review_case_id,
            category=category,
            baseline_value=_safe_json_value(baseline_value),
            reviewed_value=_safe_json_value(reviewed_value),
            severity=severity,
            non_negotiable=non_negotiable,
            disclosed=disclosed,
            approved=approved,
            evidence_ids=[evidence_id],
            acceptance_impact=impact,
            recommended_action=(
                "Reject this output and return to diagnosis or repair planning."
                if impact == "reject"
                else "Require explicit human review of the disclosed difference."
                if impact == "human_review"
                else "Preserve this approved minor limitation in downstream metadata."
            ),
            warnings=[],
        )
        regressions.append(regression)
        degraded.append(category)
        if non_negotiable:
            non_negotiable_regressions.append(category)
        elif disclosed and approved:
            disclosed_minor.append(category)

    required_unknown = [
        item
        for item in unknown
        if item in default_non_negotiable
    ]
    blocking_regressions = [
        item
        for item in regressions
        if item.non_negotiable or item.acceptance_impact in {"reject", "blocked"}
    ]
    equivalent = not blocking_regressions and not required_unknown
    comparison = BobaOutputBaselineComparisonV1(
        baseline_comparison_id=_stable_id(
            "baseline_comparison",
            review_case_id,
            baseline.artifact.output_artifact_id,
        ),
        review_case_id=review_case_id,
        baseline_artifact_id=baseline.artifact.output_artifact_id,
        reviewed_artifact_id=reviewed.artifact.output_artifact_id,
        comparison_basis=comparison_basis,
        technical_differences=technical_differences,
        creative_differences=creative_differences,
        quality_requirement_differences=[],
        preserved_properties=_unique(preserved, limit=64),
        improved_properties=_unique(improved, limit=64),
        degraded_properties=_unique(degraded, limit=64),
        unknown_properties=_unique(unknown, limit=64),
        non_negotiable_regressions=_unique(
            non_negotiable_regressions, limit=64
        ),
        acceptable_disclosed_regressions=_unique(disclosed_minor, limit=64),
        comparison_confidence=round(
            len(preserved) / max(1, len(baseline_snapshot)), 4
        ),
        equivalent_for_required_capability=equivalent,
        warnings=(
            ["Required baseline properties are unavailable: " + ", ".join(required_unknown)]
            if required_unknown
            else []
        ),
        limitations=[
            "Creative baseline differences use persisted evidence and may require human judgment."
        ],
    )
    return comparison, regressions


def build_quality_issues(
    *,
    review_case_id: str,
    source_type: BobaOutputReviewSourceTypeV1,
    technical: BobaTechnicalQualityAssessmentV1,
    creative: BobaCreativeQualityAssessmentV1,
    regressions: Sequence[BobaOutputQualityRegressionV1],
    required_quality_properties: Sequence[str],
) -> list[BobaOutputQualityIssueV1]:
    """Normalize failed, unavailable, and regressed evidence into owner handoffs."""

    issues: list[BobaOutputQualityIssueV1] = []
    for check in technical.checks:
        if check.status not in {"failed", "unavailable", "degraded"}:
            continue
        if check.status == "degraded" and not check.required:
            continue
        if check.status == "unavailable":
            owner: BobaOutputQualityOwnerV1 = "validator_runner"
            severity: BobaOutputQualitySeverityV1 = (
                "major" if check.required else "minor"
            )
            action = "Run or restore the missing registered read-only validation."
        elif check.category in {"media_probe", "decode"} and source_type == "tool_recovery_output":
            owner = "tool_recovery_brain"
            severity = "critical"
            action = "Return the exact recovery output to Tool Recovery diagnosis."
        elif check.category in {
            "source_window",
            "truncation",
            "missing_segment",
            "duplicate_segment",
            "caption_timing",
            "caption_bounds",
            "framing",
            "subject_visibility",
            "face_tracking",
            "multi_speaker_layout",
        }:
            owner = "repair_planner"
            severity = "critical" if check.required else "moderate"
            action = "Return the failed requirement to Repair Planner."
        else:
            owner = "root_cause_analyzer"
            severity = "critical" if check.required else "moderate"
            action = "Diagnose why the exact output contradicts its expected specification."
        issues.append(
            BobaOutputQualityIssueV1(
                quality_issue_id=_stable_id(
                    "quality_issue",
                    review_case_id,
                    check.technical_check_id,
                ),
                review_case_id=review_case_id,
                category=check.category,
                title=f"{check.name}: {check.status.replace('_', ' ')}",
                summary=check.failure_summary
                or (
                    "Required evidence is unavailable."
                    if check.status == "unavailable"
                    else "The check produced degraded evidence."
                    if check.status == "degraded"
                    else "The required technical check failed."
                ),
                severity=severity,
                confirmed=check.status == "failed",
                confidence=1.0 if check.status == "failed" else 0.7,
                evidence_ids=check.evidence_ids,
                affected_requirements=_unique(required_quality_properties, limit=12),
                blocks_acceptance=check.required
                and check.status in {"failed", "unavailable"},
                repairable=owner
                in {
                    "tool_recovery_brain",
                    "repair_planner",
                    "root_cause_analyzer",
                },
                recommended_owner_module=owner,
                recommended_action=action,
                warnings=check.warnings,
            )
        )

    for dimension in creative.dimensions:
        if dimension.status not in {"failed", "weak", "conflicting"}:
            continue
        severity = (
            "critical"
            if dimension.blocking
            and dimension.dimension
            in {
                "story_completeness",
                "payoff_preservation",
                "source_meaning_preservation",
            }
            else "major"
            if dimension.blocking
            else "moderate"
        )
        issues.append(
            BobaOutputQualityIssueV1(
                quality_issue_id=_stable_id(
                    "quality_issue",
                    review_case_id,
                    dimension.creative_dimension_id,
                ),
                review_case_id=review_case_id,
                category=dimension.dimension,
                title=f"{dimension.dimension.replace('_', ' ').title()} needs attention",
                summary=(
                    "; ".join(dimension.negative_findings)
                    or dimension.uncertainty
                    or "Creative evidence is weak or conflicting."
                ),
                severity=severity,
                confirmed=dimension.status == "failed",
                confidence=0.9 if dimension.status == "failed" else 0.6,
                evidence_ids=dimension.evidence_ids,
                affected_requirements=_unique(required_quality_properties, limit=12),
                blocks_acceptance=dimension.blocking,
                repairable=True,
                recommended_owner_module="repair_planner",
                recommended_action=(
                    "Preserve the source meaning and revise the quality plan before another output."
                    if dimension.blocking
                    else "Require human creative review before proceeding."
                ),
                warnings=dimension.warnings,
            )
        )

    for regression in regressions:
        issues.append(
            BobaOutputQualityIssueV1(
                quality_issue_id=_stable_id(
                    "quality_issue",
                    review_case_id,
                    regression.quality_regression_id,
                ),
                review_case_id=review_case_id,
                category=regression.category,
                title=f"{regression.category.replace('_', ' ').title()} regression",
                summary=(
                    f"Baseline value {_safe_json_value(regression.baseline_value)!r} "
                    f"changed to {_safe_json_value(regression.reviewed_value)!r}."
                )[:900],
                severity=regression.severity,
                confirmed=True,
                confidence=0.95
                if regression.category
                in {
                    "resolution",
                    "frame_rate",
                    "duration",
                    "audio_presence",
                    "file_integrity",
                }
                else 0.7,
                evidence_ids=regression.evidence_ids,
                affected_requirements=_unique(required_quality_properties, limit=12),
                blocks_acceptance=regression.acceptance_impact
                in {"reject", "blocked"},
                repairable=True,
                recommended_owner_module=(
                    "tool_recovery_brain"
                    if source_type == "tool_recovery_output"
                    else "repair_planner"
                ),
                recommended_action=regression.recommended_action,
                warnings=regression.warnings,
            )
        )
    return issues[:512]


def make_output_acceptance_decision(
    *,
    review_case_id: str,
    rights_status: str,
    safety_status: str,
    technical: BobaTechnicalQualityAssessmentV1,
    creative: BobaCreativeQualityAssessmentV1,
    comparison: BobaOutputBaselineComparisonV1 | None,
    regressions: Sequence[BobaOutputQualityRegressionV1],
    issues: Sequence[BobaOutputQualityIssueV1],
    baseline_required: bool,
) -> BobaOutputAcceptanceDecisionV1:
    """Apply the conservative V1 decision policy without authorizing action."""

    rights = rights_status.casefold()
    safety = safety_status.casefold()
    rights_clear = rights in _RIGHTS_ALLOWED
    safety_clear = safety in _SAFETY_ALLOWED
    non_negotiable_regressions = [
        item
        for item in regressions
        if item.non_negotiable or item.acceptance_impact in {"reject", "blocked"}
    ]
    creative_failures = [
        item
        for item in creative.dimensions
        if item.blocking or item.status == "failed"
    ]
    approved_minor_regressions = [
        item
        for item in regressions
        if item.disclosed
        and item.approved
        and item.severity in {"negligible", "minor"}
        and not item.non_negotiable
    ]
    reasons: list[str] = []
    limitations = [
        *technical.limitations,
        *creative.limitations,
        *(comparison.limitations if comparison else []),
    ]
    next_stage = ""
    confidence = min(
        technical.technical_score,
        creative.evidence_coverage,
    )
    if rights in _RIGHTS_BLOCKED or not rights_clear:
        decision: BobaOutputAcceptanceDecisionValueV1 = "blocked_rights"
        reasons.append(
            "Rights state is blocked or not explicitly clear for local processing."
        )
        next_stage = "rights_permission_gate"
        confidence = 1.0 if rights in _RIGHTS_BLOCKED else 0.6
    elif safety in _SAFETY_BLOCKED:
        decision = "blocked_safety"
        reasons.append("Safety state blocks review continuation.")
        next_stage = "safety_gate"
        confidence = 1.0
    elif not safety_clear:
        decision = "needs_more_evidence"
        reasons.append("Safety eligibility is unknown or incomplete.")
        next_stage = "safety_gate"
        confidence = 0.5
    elif technical.failed_required_checks:
        decision = "rejected_technical"
        reasons.extend(technical.failed_required_checks)
        next_stage = "root_cause_analyzer"
    elif technical.unavailable_required_checks:
        decision = "needs_more_evidence"
        reasons.extend(technical.unavailable_required_checks)
        next_stage = "validator_runner"
    elif baseline_required and comparison is None:
        decision = "needs_more_evidence"
        reasons.append("The required exact baseline could not be resolved.")
        next_stage = "validator_runner"
    elif non_negotiable_regressions:
        decision = "rejected_regression"
        reasons.extend(
            f"{item.category} regression" for item in non_negotiable_regressions
        )
        next_stage = "repair_planner"
    elif comparison is not None and not comparison.equivalent_for_required_capability:
        decision = "needs_more_evidence"
        reasons.extend(
            [
                *comparison.unknown_properties,
                *comparison.non_negotiable_regressions,
            ]
        )
        next_stage = "validator_runner"
    elif creative_failures:
        decision = "rejected_quality"
        reasons.extend(item.dimension for item in creative_failures)
        next_stage = "repair_planner"
    elif creative.human_review_required or any(
        item.status in {"unavailable", "conflicting", "weak"}
        for item in creative.dimensions
        if item.status != "not_required"
    ):
        decision = "needs_human_review"
        reasons.extend(creative.subjective_uncertainty[:8])
        next_stage = "human_operator"
    elif approved_minor_regressions:
        decision = "accepted_with_disclosed_limitations"
        limitations.extend(
            f"Approved disclosed {item.category} regression."
            for item in approved_minor_regressions
        )
        next_stage = "workflow_controller"
    elif technical.technical_acceptance_eligible and creative.creative_acceptance_eligible:
        decision = "accepted_for_next_internal_stage"
        next_stage = "workflow_controller"
    else:
        decision = "needs_more_evidence"
        reasons.append("Available evidence does not support a complete quality decision.")
        next_stage = "validator_runner"

    summaries: dict[BobaOutputAcceptanceDecisionValueV1, str] = {
        "accepted_for_next_internal_stage": (
            "The output passed required checks and no important quality loss was found. "
            "It is eligible for the next internal safety and workflow decision."
        ),
        "accepted_with_disclosed_limitations": (
            "The output passed every non-negotiable check with approved minor limitations "
            "preserved in its review record."
        ),
        "needs_human_review": (
            "Technical checks passed, but subjective visual or audio quality still needs "
            "bounded human review."
        ),
        "needs_more_evidence": (
            "BOBA cannot complete review because required non-destructive evidence is missing."
        ),
        "rejected_technical": (
            "The output failed a required technical check and was rejected. "
            "Olympus remains paused."
        ),
        "rejected_quality": (
            "The output is not acceptable because required story meaning or creative quality "
            "was not preserved."
        ),
        "rejected_regression": (
            "The reviewed output is materially worse than its required baseline."
        ),
        "blocked_rights": (
            "Rights are blocked or unconfirmed, so BOBA did not inspect or advance the output."
        ),
        "blocked_safety": (
            "Safety state blocks review and no bypass is recommended."
        ),
        "not_reviewable": "The exact output cannot be reviewed safely.",
        "unknown": "No quality decision is available.",
    }
    required_complete = bool(
        technical.required_checks_passed
        and (not baseline_required or comparison is not None)
    )
    human_review_required = decision in {
        "needs_human_review",
        "accepted_with_disclosed_limitations",
        "accepted_for_next_internal_stage",
    }
    return BobaOutputAcceptanceDecisionV1(
        acceptance_decision_id=_stable_id(
            "acceptance_decision", review_case_id, decision
        ),
        review_case_id=review_case_id,
        decision=decision,
        decision_summary=summaries[decision],
        technical_eligible=technical.technical_acceptance_eligible,
        creative_eligible=creative.creative_acceptance_eligible,
        baseline_equivalent=(
            comparison.equivalent_for_required_capability
            if comparison is not None
            else None
        ),
        required_checks_complete=required_complete,
        rights_clear_for_processing=rights_clear,
        safety_clear_for_processing=safety_clear,
        human_review_required=human_review_required,
        acceptance_conditions=[
            "Safety Gate independently reviews the exact next action.",
            "Workflow Controller independently evaluates continuation.",
            "Human approval remains required in V1.",
        ]
        if decision.startswith("accepted_")
        else [],
        rejection_reasons=_unique(reasons, limit=64),
        disclosed_limitations=_unique(limitations, limit=64),
        next_allowed_stage=next_stage,
        workflow_resume_authorized=False,
        publication_authorized=False,
        confidence=_unit(confidence),
        warnings=[
            "Acceptance does not authorize workflow resume, upload, or publication."
        ],
    )


_HUMAN_REVIEW_QUESTIONS = [
    "Does the opening immediately make sense?",
    "Does the clip reach a complete payoff?",
    "Does any cut feel abrupt?",
    "Are captions readable without blocking the subject?",
    "Is the subject framed correctly throughout?",
    "Does motion improve the clip rather than distract?",
    "Can dialogue be clearly understood?",
    "Does music support rather than overpower the message?",
    "Does the output preserve the original meaning?",
    "Is the fallback visibly or audibly worse?",
]


def build_human_review_package(
    *,
    review_case_id: str,
    artifact: BobaReviewedOutputArtifactV1,
    baseline: BobaReviewedOutputArtifactV1 | None,
    technical: BobaTechnicalQualityAssessmentV1,
    creative: BobaCreativeQualityAssessmentV1,
    comparison: BobaOutputBaselineComparisonV1 | None,
    decision: BobaOutputAcceptanceDecisionV1,
) -> BobaOutputHumanReviewPackageV1:
    """Create a bounded checklist with no publish or resume option."""

    critical = [
        *technical.failed_required_checks,
        *technical.unavailable_required_checks,
        *(
            [
                item.dimension.replace("_", " ")
                for item in creative.dimensions
                if item.blocking or item.status in {"failed", "conflicting"}
            ]
        ),
        *(comparison.non_negotiable_regressions if comparison else []),
    ]
    optional = [
        item.dimension.replace("_", " ")
        for item in creative.dimensions
        if item.requires_human_review and not item.blocking
    ]
    return BobaOutputHumanReviewPackageV1(
        human_review_package_id=_stable_id(
            "human_review_package", review_case_id
        ),
        review_case_id=review_case_id,
        reason=decision.decision_summary,
        sanitized_output_reference=artifact.sanitized_artifact_reference,
        comparison_reference=(
            baseline.sanitized_artifact_reference if baseline else ""
        ),
        reviewer_questions=_HUMAN_REVIEW_QUESTIONS,
        critical_items=_unique(critical, limit=32),
        optional_items=_unique(optional, limit=32),
        technical_summary=(
            f"Required checks passed: {technical.required_checks_passed}. "
            f"Failed: {', '.join(technical.failed_required_checks) or 'none'}. "
            f"Unavailable: {', '.join(technical.unavailable_required_checks) or 'none'}."
        ),
        creative_summary=(
            f"Evidence coverage: {creative.evidence_coverage:.0%}. "
            f"Subjective uncertainty: "
            f"{'; '.join(creative.subjective_uncertainty[:6]) or 'none recorded'}."
        ),
        regression_summary=(
            f"Degraded properties: {', '.join(comparison.degraded_properties) or 'none'}. "
            f"Unknown properties: {', '.join(comparison.unknown_properties) or 'none'}."
            if comparison
            else "No exact baseline comparison was requested."
        ),
        unavailable_evidence=_unique(
            [
                *technical.unavailable_required_checks,
                *[
                    item.dimension.replace("_", " ")
                    for item in creative.dimensions
                    if item.status == "unavailable"
                ],
                *(comparison.unknown_properties if comparison else []),
            ],
            limit=64,
        ),
        acceptance_options=[
            "accept for next internal stage",
            "accept with disclosed limitation",
            "reject output",
            "send back to Tool Recovery",
            "send back to Repair Planner",
            "request more evidence",
        ],
        prohibited_actions=[
            "Do not publish or upload from this review.",
            "Do not resume Olympus from this review.",
            "Do not modify, rerender, repair, replace, or delete reviewed media.",
            "Do not bypass Rights or Safety gates.",
        ],
        warnings=[
            "Automated creative review cannot replace every human visual judgment."
        ],
    )


def build_output_quality_handoffs(
    *,
    review_case_id: str,
    source_type: BobaOutputReviewSourceTypeV1,
    decision: BobaOutputAcceptanceDecisionV1,
    technical: BobaTechnicalQualityAssessmentV1,
    issues: Sequence[BobaOutputQualityIssueV1],
) -> list[BobaOutputQualityHandoffV1]:
    """Build advisory handoffs only; no target is invoked by this module."""

    targets: list[
        tuple[BobaOutputQualityHandoffTargetV1, str, BobaOutputQualityPriorityV1]
    ] = []
    if decision.decision in {
        "accepted_for_next_internal_stage",
        "accepted_with_disclosed_limitations",
    }:
        targets.extend(
            [
                (
                    "workflow_controller",
                    "Consider the quality decision while keeping resume separate.",
                    "high",
                ),
                (
                    "safety_gate",
                    "Confirm the exact proposed next action remains safe.",
                    "high",
                ),
                (
                    "final_decision_bus",
                    "Combine quality, rights, safety, and workflow evidence.",
                    "medium",
                ),
                (
                    "human_operator",
                    "Provide the V1 human approval required before continuation.",
                    "high",
                ),
            ]
        )
    elif decision.decision == "blocked_rights":
        targets.append(
            (
                "rights_permission_gate",
                "Resolve rights evidence without bypassing permission requirements.",
                "critical",
            )
        )
    elif decision.decision == "blocked_safety":
        targets.append(
            ("safety_gate", "Review the blocking safety state.", "critical")
        )
    elif decision.decision == "needs_human_review":
        targets.append(
            (
                "human_operator",
                "Review subjective framing, audio, story, and regression questions.",
                "high",
            )
        )
    elif decision.decision == "needs_more_evidence":
        target: BobaOutputQualityHandoffTargetV1 = (
            "safety_gate"
            if decision.next_allowed_stage == "safety_gate"
            else "validator_runner"
        )
        targets.append(
            (
                target,
                "Supply the missing registered read-only evidence.",
                "high",
            )
        )
    elif decision.decision == "rejected_technical":
        targets.append(
            (
                "tool_recovery_brain"
                if source_type == "tool_recovery_output"
                else "root_cause_analyzer",
                "Diagnose the failed required technical checks.",
                "critical",
            )
        )
    elif decision.decision in {"rejected_quality", "rejected_regression"}:
        targets.append(
            (
                "tool_recovery_brain"
                if source_type == "tool_recovery_output"
                else "repair_planner",
                "Restore the failed quality requirement or baseline equivalence.",
                "critical",
            )
        )
    if any(
        item.recommended_owner_module == "checkpoint_recovery_manager"
        for item in issues
    ):
        targets.append(
            (
                "checkpoint_recovery_manager",
                "Inspect the checkpoint-specific output contradiction.",
                "high",
            )
        )
    handoffs: list[BobaOutputQualityHandoffV1] = []
    for target, reason, priority in targets:
        if any(item.target_module == target for item in handoffs):
            continue
        handoffs.append(
            BobaOutputQualityHandoffV1(
                handoff_id=_stable_id(
                    "quality_handoff", review_case_id, target
                ),
                review_case_id=review_case_id,
                acceptance_decision_id=decision.acceptance_decision_id,
                target_module=target,
                reason=reason,
                required_inputs=[
                    "Exact output artifact identity",
                    "Output Quality Reviewer decision",
                    "Failed and unavailable check identifiers",
                ],
                quality_issues=[item.quality_issue_id for item in issues[:64]],
                failed_checks=technical.failed_required_checks,
                unavailable_checks=technical.unavailable_required_checks,
                constraints=[
                    "Keep the workflow paused.",
                    "Preserve source media and accepted outputs.",
                    "Do not silently lower quality requirements.",
                ],
                blocked_actions=[
                    "automatic workflow resume",
                    "automatic repair or fallback",
                    "output modification or rerender",
                    "upload or publication",
                    "rights or safety bypass",
                ],
                allowed_advisory_actions=[
                    "inspect linked bounded evidence",
                    "prepare a human-reviewed next decision",
                ],
                apply_automatically=False,
                human_approval_required=True,
                priority=priority,
                warnings=[],
            )
        )
    return handoffs


def summarize_output_quality_reviewer(
    report: BobaOutputQualityReviewerSetV1,
) -> BobaOutputQualityReviewerSummaryV1:
    decisions = report.acceptance_decisions
    technical = report.technical_assessments
    creative = report.creative_assessments
    issues = sorted(
        report.quality_issues,
        key=lambda item: (
            {
                "critical": 5,
                "major": 4,
                "moderate": 3,
                "minor": 2,
                "negligible": 1,
                "unknown": 0,
            }[item.severity],
            item.confidence,
        ),
        reverse=True,
    )
    accepted_artifacts = {
        item.review_case_id
        for item in decisions
        if item.decision
        in {
            "accepted_for_next_internal_stage",
            "accepted_with_disclosed_limitations",
        }
    }
    rejected_artifacts = {
        item.review_case_id
        for item in decisions
        if item.decision.startswith("rejected_")
    }
    return BobaOutputQualityReviewerSummaryV1(
        total_review_cases=len(report.review_cases),
        accepted_internal_count=sum(
            item.decision == "accepted_for_next_internal_stage"
            for item in decisions
        ),
        accepted_with_limitations_count=sum(
            item.decision == "accepted_with_disclosed_limitations"
            for item in decisions
        ),
        human_review_count=sum(
            item.decision == "needs_human_review" for item in decisions
        ),
        needs_more_evidence_count=sum(
            item.decision == "needs_more_evidence" for item in decisions
        ),
        technical_rejection_count=sum(
            item.decision == "rejected_technical" for item in decisions
        ),
        quality_rejection_count=sum(
            item.decision == "rejected_quality" for item in decisions
        ),
        regression_rejection_count=sum(
            item.decision == "rejected_regression" for item in decisions
        ),
        rights_block_count=sum(
            item.decision == "blocked_rights" for item in decisions
        ),
        safety_block_count=sum(
            item.decision == "blocked_safety" for item in decisions
        ),
        technical_pass_count=sum(
            item.technical_acceptance_eligible for item in technical
        ),
        technical_failure_count=sum(
            not item.technical_acceptance_eligible for item in technical
        ),
        creative_eligible_count=sum(
            item.creative_acceptance_eligible for item in creative
        ),
        creative_uncertain_count=sum(
            item.human_review_required for item in creative
        ),
        non_negotiable_regression_count=sum(
            item.non_negotiable for item in report.quality_regressions
        ),
        highest_priority_issue=issues[0].title if issues else "",
        strongest_output=next(iter(sorted(accepted_artifacts)), ""),
        weakest_output=next(iter(sorted(rejected_artifacts)), ""),
        safest_next_action=(
            "Keep Olympus paused and follow the highest-priority advisory handoff."
            if decisions
            else "Select one exact generated output for read-only review."
        ),
        required_human_actions=_unique(
            [
                handoff.reason
                for handoff in report.review_handoffs
                if handoff.human_approval_required
            ],
            limit=32,
        ),
        limitations=_unique(
            [
                *report.limitations,
                *[
                    limitation
                    for item in report.creative_assessments
                    for limitation in item.limitations
                ],
            ],
            limit=64,
        ),
    )


def _empty_technical_assessment(
    review_case_id: str,
    *,
    limitation: str,
) -> BobaTechnicalQualityAssessmentV1:
    return BobaTechnicalQualityAssessmentV1(
        technical_assessment_id=_stable_id(
            "technical_assessment", review_case_id
        ),
        review_case_id=review_case_id,
        checks=[],
        technical_score=0.0,
        required_checks_passed=False,
        technical_acceptance_eligible=False,
        limitations=[limitation],
    )


def _empty_creative_assessment(
    review_case_id: str,
    *,
    limitation: str,
) -> BobaCreativeQualityAssessmentV1:
    return BobaCreativeQualityAssessmentV1(
        creative_assessment_id=_stable_id(
            "creative_assessment", review_case_id
        ),
        review_case_id=review_case_id,
        dimensions=[],
        creative_score=0.0,
        evidence_coverage=0.0,
        subjective_uncertainty=[limitation],
        creative_acceptance_eligible=False,
        human_review_required=True,
        limitations=[limitation],
    )


def _append_unavailable_validator_check(
    *,
    technical: BobaTechnicalQualityAssessmentV1,
    collector: _EvidenceCollector,
    validator_name: str,
    category: BobaTechnicalQualityCategoryV1,
) -> None:
    evidence_id = collector.add(
        source_type="unknown",
        source_id=technical.review_case_id,
        category=category,
        summary=f"Requested registered validator is unavailable: {validator_name}.",
        reliability="unavailable",
        confidence=1.0,
        human=True,
    )
    technical.checks.append(
        BobaTechnicalQualityCheckV1(
            technical_check_id=_stable_id(
                "technical_check",
                technical.review_case_id,
                "unavailable",
                validator_name,
            ),
            review_case_id=technical.review_case_id,
            category=category,
            name=f"Requested {validator_name}",
            required=True,
            status="unavailable",
            observed_value=None,
            expected_value="registered local read-only validator",
            evidence_ids=[evidence_id],
            blocks_acceptance=True,
            failure_summary=f"{validator_name} is unavailable.",
            human_review_needed=True,
            warnings=[],
        )
    )
    technical.unavailable_required_checks = _unique(
        [*technical.unavailable_required_checks, f"Requested {validator_name}"],
        limit=64,
    )
    technical.required_checks_passed = False
    technical.technical_acceptance_eligible = False
    required = [item for item in technical.checks if item.required]
    technical.technical_score = round(
        sum(item.status == "passed" for item in required) / max(1, len(required)),
        4,
    )
    technical.decode_status = "unavailable"


class BobaOutputQualityReviewerV1:
    """Review exact generated outputs without modifying or advancing them."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        storage_root: str | Path | None = None,
        evidence_root: str | Path | None = None,
        ffprobe_binary: str = "ffprobe",
        ffmpeg_binary: str = "ffmpeg",
        trusted_read_only_validator_registry: Mapping[
            str, BobaReadOnlyQualityValidatorV1
        ]
        | None = None,
    ) -> None:
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.storage_root = (
            Path(storage_root).expanduser().resolve()
            if storage_root is not None
            else (self.repository_root / "storage_data").resolve()
        )
        self.evidence_root = (
            Path(evidence_root).expanduser().resolve()
            if evidence_root is not None
            else (
                self.repository_root
                / "work"
                / "boba"
                / "output_quality_reviewer"
                / "samples"
            ).resolve()
        )
        default_registry = build_read_only_quality_validator_registry(
            ffprobe_binary=ffprobe_binary,
            ffmpeg_binary=ffmpeg_binary,
        )
        if trusted_read_only_validator_registry is None:
            self.validator_registry = default_registry
        else:
            extra = set(trusted_read_only_validator_registry) - set(default_registry)
            if extra:
                raise ValidationError(
                    "Output Quality Reviewer received an unregistered validator.",
                    details={"validator_ids": sorted(extra)},
                )
            self.validator_registry = {
                key: trusted_read_only_validator_registry.get(key, value)
                for key, value in default_registry.items()
            }

    def review(
        self,
        *,
        project_id: str,
        output_reference: str,
        known_output_artifacts: Sequence[Mapping[str, Any]],
        source_id: str | None = None,
        baseline_reference: str | None = None,
        source_media_reference: str = "",
        review_mode: BobaOutputReviewModeV1 = "full_available_evidence_review",
        rights_status: str = "unknown",
        safety_status: str = "unknown",
        workflow_stage: str = "quality_review",
        tool_recovery_report: JsonMapping = None,
        code_surgeon_report: JsonMapping = None,
        repair_planner_report: JsonMapping = None,
        creative_artifacts: Mapping[str, Any] | None = None,
        validation_artifacts: Mapping[str, Any] | None = None,
        required_quality_properties: Sequence[str] = (),
        non_negotiable_requirements: Sequence[str] = (),
        comparison_basis: BobaOutputComparisonBasisV1 = "unknown",
        existing_report: BobaOutputQualityReviewerSetV1 | None = None,
        output_modification_requested: bool = False,
        source_modification_requested: bool = False,
        network_review_requested: bool = False,
    ) -> BobaOutputQualityReviewerSetV1:
        """Run one read-only review case over exact allowlisted local evidence."""

        if output_modification_requested or source_modification_requested:
            raise ValidationError("Output Quality Reviewer cannot modify media.")
        if network_review_requested:
            raise ValidationError("Output Quality Reviewer cannot use network review.")
        if review_mode == "unknown":
            review_mode = "artifact_only"
        if review_mode == "baseline_comparison" and not baseline_reference:
            raise ValidationError(
                "Baseline comparison requires an exact known baseline artifact."
            )
        resolved = resolve_review_output(
            project_id=project_id,
            output_reference=output_reference,
            known_output_artifacts=known_output_artifacts,
            repository_root=self.repository_root,
            storage_root=self.storage_root,
            source_media_reference=source_media_reference,
            rights_status=rights_status,
        )
        baseline: ResolvedReviewedOutputV1 | None = None
        if baseline_reference:
            baseline = resolve_review_output(
                project_id=project_id,
                output_reference=baseline_reference,
                known_output_artifacts=known_output_artifacts,
                repository_root=self.repository_root,
                storage_root=self.storage_root,
                source_media_reference=source_media_reference,
                rights_status=rights_status,
            )
        review_case_id = _stable_id(
            "output_review",
            project_id,
            resolved.artifact.output_artifact_id,
            uuid4().hex,
        )
        collector = _EvidenceCollector(
            review_case_id=review_case_id,
            output_reference=resolved.artifact.sanitized_artifact_reference,
        )
        (
            required,
            non_negotiable,
            repair_used,
            recovery_requirements_used,
        ) = _quality_requirements(
            artifact=resolved.artifact,
            explicit_required=required_quality_properties,
            explicit_non_negotiable=non_negotiable_requirements,
            repair_planner=repair_planner_report,
            tool_recovery=tool_recovery_report,
        )
        signal_usage = BobaOutputQualitySignalUsageV1(
            tool_recovery_used=bool(_mapping(tool_recovery_report)),
            tool_recovery_artifact_read=bool(_mapping(tool_recovery_report)),
            code_surgeon_used=bool(_mapping(code_surgeon_report)),
            render_manifest_used=bool(
                _mapping(
                    resolved.metadata.get("manifest_entry")
                    or resolved.metadata.get("render_entry")
                )
            ),
            repair_planner_quality_requirements_used=repair_used,
        )
        signal_usage.tool_recovery_used = (
            signal_usage.tool_recovery_used or recovery_requirements_used
        )
        requested_mode = review_mode
        effective_mode = review_mode
        mode_warnings: list[str] = []
        unavailable_requested_validators: list[
            tuple[str, BobaTechnicalQualityCategoryV1]
        ] = []
        is_media = resolved.artifact.artifact_type in {"video", "audio"}
        if (
            is_media
            and requested_mode
            in {
                "local_technical_review",
                "full_available_evidence_review",
                "baseline_comparison",
            }
        ):
            local_validators: tuple[
                tuple[str, BobaTechnicalQualityCategoryV1],
                ...,
            ] = (
                ("ffprobe_media", "media_probe"),
                ("ffmpeg_decode", "decode"),
            )
            for validator_id, category in local_validators:
                validator = self.validator_registry.get(validator_id)
                if validator is None or not validator.available:
                    unavailable_requested_validators.append((validator_id, category))
            if unavailable_requested_validators:
                effective_mode = "artifact_only"
                mode_warnings.append(
                    "Requested local review degraded to artifact-only because a registered "
                    "read-only validator is unavailable."
                )
        elif requested_mode == "human_review_preparation":
            effective_mode = "artifact_only"

        case = BobaOutputReviewCaseV1(
            review_case_id=review_case_id,
            source_type=resolved.source_type,
            source_module=_text(
                resolved.metadata.get("origin_module"), maximum=160
            ),
            source_record_id=_text(
                resolved.metadata.get("source_record_id")
                or resolved.metadata.get("origin_attempt_id")
                or resolved.metadata.get("origin_run_id"),
                maximum=160,
            ),
            output_artifact_id=resolved.artifact.output_artifact_id,
            baseline_artifact_id=(
                baseline.artifact.output_artifact_id if baseline else ""
            ),
            title=_text(
                resolved.metadata.get("title")
                or f"Quality review for {resolved.artifact.clip_id or Path(output_reference).name}",
                maximum=240,
            ),
            clip_id=resolved.artifact.clip_id,
            workflow_stage=_text(workflow_stage, maximum=160) or "quality_review",
            review_mode=effective_mode,
            review_status="reviewing",
            rights_status=_text(rights_status, maximum=80) or "unknown",
            safety_status=_text(safety_status, maximum=80) or "unknown",
            required_quality_properties=required,
            non_negotiable_requirements=non_negotiable,
            human_review_required=True,
            confidence=0.0,
            warnings=mode_warnings,
            limitations=[],
        )

        rights = case.rights_status.casefold()
        safety = case.safety_status.casefold()
        rights_clear = rights in _RIGHTS_ALLOWED
        safety_clear = safety in _SAFETY_ALLOWED
        blocked_before_review = not rights_clear or not safety_clear
        if blocked_before_review:
            reason = (
                "Rights are blocked or unknown; local output inspection did not run."
                if not rights_clear
                else (
                    "Safety eligibility is blocked or unknown; local output "
                    "inspection did not run."
                )
            )
            technical = _empty_technical_assessment(
                review_case_id,
                limitation=reason,
            )
            creative = _empty_creative_assessment(
                review_case_id,
                limitation=reason,
            )
            comparison = None
            regressions: list[BobaOutputQualityRegressionV1] = []
            issues: list[BobaOutputQualityIssueV1] = []
            decision = make_output_acceptance_decision(
                review_case_id=review_case_id,
                rights_status=case.rights_status,
                safety_status=case.safety_status,
                technical=technical,
                creative=creative,
                comparison=None,
                regressions=[],
                issues=[],
                baseline_required=bool(baseline_reference),
            )
            case.review_status = "blocked"
        else:
            recovery_validation = _recovery_validation(
                tool_recovery_report,
                output_reference=resolved.artifact.sanitized_artifact_reference,
                origin_attempt_id=resolved.artifact.origin_attempt_id,
            )
            technical = build_technical_quality_checks(
                resolved=resolved,
                review_case_id=review_case_id,
                review_mode=effective_mode,
                registry=self.validator_registry,
                evidence_workspace=self.evidence_root / review_case_id,
                collector=collector,
                tool_recovery_validation=recovery_validation,
                validation_artifacts=dict(validation_artifacts or {}),
                required_quality_properties=[*required, *non_negotiable],
                signal_usage=signal_usage,
            )
            for validator_id, category in unavailable_requested_validators:
                _append_unavailable_validator_check(
                    technical=technical,
                    collector=collector,
                    validator_name=validator_id,
                    category=category,
                )
                signal_usage.unavailable_signals.append(validator_id)
            combined_creative = dict(creative_artifacts or {})
            if "boundary_quality" not in combined_creative:
                boundary_value = _first_nested(
                    resolved.metadata, "boundary_quality"
                )
                if isinstance(boundary_value, Mapping):
                    combined_creative["boundary_quality"] = dict(boundary_value)
            if "render_metadata" not in combined_creative:
                combined_creative["render_metadata"] = _render_metadata(
                    resolved.metadata
                )
            if validation_artifacts:
                combined_creative.setdefault(
                    "face_motion_validation",
                    validation_artifacts.get("face_motion_validation"),
                )
                combined_creative.setdefault(
                    "multi_speaker_validation",
                    validation_artifacts.get("multi_speaker_validation"),
                )
            creative = build_creative_quality_dimensions(
                review_case_id=review_case_id,
                artifact=resolved.artifact,
                technical=technical,
                creative_artifacts=combined_creative,
                collector=collector,
                signal_usage=signal_usage,
            )
            comparison = None
            regressions = []
            if baseline is not None:
                signal_usage.baseline_comparison_used = True
                if baseline.path.is_file():
                    comparison, regressions = compare_output_to_baseline(
                        review_case_id=review_case_id,
                        reviewed=resolved,
                        baseline=baseline,
                        technical=technical,
                        creative=creative,
                        collector=collector,
                        comparison_basis=comparison_basis,
                        non_negotiable_requirements=non_negotiable,
                    )
                else:
                    comparison = BobaOutputBaselineComparisonV1(
                        baseline_comparison_id=_stable_id(
                            "baseline_comparison",
                            review_case_id,
                            baseline.artifact.output_artifact_id,
                        ),
                        review_case_id=review_case_id,
                        baseline_artifact_id=baseline.artifact.output_artifact_id,
                        reviewed_artifact_id=resolved.artifact.output_artifact_id,
                        comparison_basis=comparison_basis,
                        unknown_properties=[
                            "baseline artifact integrity",
                            "baseline technical properties",
                            "baseline creative properties",
                        ],
                        comparison_confidence=0.0,
                        equivalent_for_required_capability=False,
                        warnings=["The exact baseline artifact is missing."],
                        limitations=[
                            "No comparison conclusion is possible without the exact baseline."
                        ],
                    )
            issues = build_quality_issues(
                review_case_id=review_case_id,
                source_type=resolved.source_type,
                technical=technical,
                creative=creative,
                regressions=regressions,
                required_quality_properties=[*required, *non_negotiable],
            )
            decision = make_output_acceptance_decision(
                review_case_id=review_case_id,
                rights_status=case.rights_status,
                safety_status=case.safety_status,
                technical=technical,
                creative=creative,
                comparison=comparison,
                regressions=regressions,
                issues=issues,
                baseline_required=bool(baseline_reference),
            )
            review_status_by_decision: dict[
                BobaOutputAcceptanceDecisionValueV1,
                BobaOutputReviewStatusV1,
            ] = {
                "rejected_technical": "technically_failed",
                "rejected_quality": "completed",
                "rejected_regression": "quality_regression_detected",
                "needs_human_review": "creative_review_incomplete",
                "needs_more_evidence": "blocked",
                "accepted_for_next_internal_stage": "completed",
                "accepted_with_disclosed_limitations": "completed",
                "blocked_rights": "blocked",
                "blocked_safety": "blocked",
                "not_reviewable": "blocked",
                "unknown": "unknown",
            }
            case.review_status = review_status_by_decision[decision.decision]

        human_package = (
            build_human_review_package(
                review_case_id=review_case_id,
                artifact=resolved.artifact,
                baseline=baseline.artifact if baseline else None,
                technical=technical,
                creative=creative,
                comparison=comparison,
                decision=decision,
            )
            if decision.decision
            in {
                "needs_human_review",
                "needs_more_evidence",
                "accepted_with_disclosed_limitations",
            }
            else None
        )
        handoffs = build_output_quality_handoffs(
            review_case_id=review_case_id,
            source_type=resolved.source_type,
            decision=decision,
            technical=technical,
            issues=issues,
        )
        case.technical_assessment_id = technical.technical_assessment_id
        case.creative_assessment_id = creative.creative_assessment_id
        case.baseline_comparison_id = (
            comparison.baseline_comparison_id if comparison else ""
        )
        case.quality_issue_ids = [item.quality_issue_id for item in issues]
        case.quality_regression_ids = [
            item.quality_regression_id for item in regressions
        ]
        case.acceptance_decision_id = decision.acceptance_decision_id
        case.human_review_package_id = (
            human_package.human_review_package_id if human_package else ""
        )
        case.unavailable_required_evidence = _unique(
            [
                *technical.unavailable_required_checks,
                *(
                    comparison.unknown_properties
                    if comparison is not None
                    else []
                ),
            ],
            limit=64,
        )
        case.human_review_required = decision.human_review_required
        case.confidence = decision.confidence
        case.limitations = _unique(
            [
                *technical.limitations,
                *creative.limitations,
                *(comparison.limitations if comparison else []),
            ],
            limit=64,
        )
        case.warnings = _unique(
            [
                *case.warnings,
                *technical.warnings,
                *creative.warnings,
                *(comparison.warnings if comparison else []),
            ],
            limit=64,
        )

        if existing_report is not None:
            if existing_report.project_id != project_id:
                raise ValidationError(
                    "Existing Output Quality Reviewer report belongs to another project."
                )
            report = existing_report.model_copy(deep=True)
        else:
            report = BobaOutputQualityReviewerSetV1(
                project_id=project_id,
                source_id=_text(source_id or project_id, maximum=512)
                or project_id,
            )
        report.review_cases.append(case)
        for output in [
            resolved.artifact,
            *( [baseline.artifact] if baseline else [] ),
        ]:
            if not any(
                item.output_artifact_id == output.output_artifact_id
                for item in report.output_artifacts
            ):
                report.output_artifacts.append(output)
        report.quality_evidence.extend(collector.items)
        report.technical_assessments.append(technical)
        report.creative_assessments.append(creative)
        if comparison is not None:
            report.baseline_comparisons.append(comparison)
        report.quality_regressions.extend(regressions)
        report.quality_issues.extend(issues)
        report.acceptance_decisions.append(decision)
        if human_package is not None:
            report.human_review_packages.append(human_package)
        report.review_handoffs.extend(handoffs)
        report.signal_usage = BobaOutputQualitySignalUsageV1.model_validate(
            {
                key: (
                    list(
                        dict.fromkeys(
                            [
                                *_list(
                                    report.signal_usage.model_dump(mode="json").get(
                                        key
                                    )
                                ),
                                *_list(
                                    signal_usage.model_dump(mode="json").get(key)
                                ),
                            ]
                        )
                    )
                    if key in {"unavailable_signals", "warnings"}
                    else bool(
                        report.signal_usage.model_dump(mode="json").get(key)
                        or signal_usage.model_dump(mode="json").get(key)
                    )
                )
                for key in BobaOutputQualitySignalUsageV1.model_fields
            }
        )
        report.warnings = _unique(
            [
                *report.warnings,
                *case.warnings,
                "Output Quality Reviewer did not modify or rerender the reviewed output.",
            ],
            limit=128,
        )
        report.limitations = _unique(
            [
                *report.limitations,
                "Automated creative review cannot replace every human visual or "
                "listening judgment.",
                "Acceptance does not authorize workflow resume, upload, or publication.",
                "No copyright-safety or virality guarantee is made.",
            ],
            limit=128,
        )
        report.reviewer_summary = summarize_output_quality_reviewer(report)
        json.dumps(report.model_dump(mode="json"))
        return report


def generate_boba_output_quality_review(
    *,
    reviewer: BobaOutputQualityReviewerV1,
    **kwargs: Any,
) -> BobaOutputQualityReviewerSetV1:
    return reviewer.review(**kwargs)


def run_boba_output_technical_review(
    *,
    reviewer: BobaOutputQualityReviewerV1,
    **kwargs: Any,
) -> BobaOutputQualityReviewerSetV1:
    kwargs["review_mode"] = "local_technical_review"
    return reviewer.review(**kwargs)


def compare_boba_output_quality_baseline(
    *,
    reviewer: BobaOutputQualityReviewerV1,
    **kwargs: Any,
) -> BobaOutputQualityReviewerSetV1:
    kwargs["review_mode"] = "baseline_comparison"
    return reviewer.review(**kwargs)


_HUMAN_DECISIONS = frozenset(
    {
        "accept_for_next_internal_stage",
        "accept_with_disclosed_limitation",
        "reject_output",
        "send_back_to_tool_recovery",
        "send_back_to_repair_planner",
        "request_more_evidence",
    }
)


def record_boba_output_human_review(
    report: BobaOutputQualityReviewerSetV1,
    *,
    review_case_id: str,
    reviewer_identity: str,
    review_decision: str,
    answers: Mapping[str, Any] | None = None,
    notes: str = "",
) -> BobaOutputQualityReviewerSetV1:
    """Record bounded human judgment without storing authentication material."""

    if review_decision not in _HUMAN_DECISIONS:
        raise ValidationError("Unsupported Output Quality Reviewer human decision.")
    identity = _text(reviewer_identity, maximum=160)
    if not identity:
        raise ValidationError("A bounded reviewer identity is required.")
    case = next(
        (item for item in report.review_cases if item.review_case_id == review_case_id),
        None,
    )
    if case is None:
        raise ValidationError("Output review case was not found.")
    decision = next(
        (
            item
            for item in report.acceptance_decisions
            if item.acceptance_decision_id == case.acceptance_decision_id
        ),
        None,
    )
    technical = next(
        (
            item
            for item in report.technical_assessments
            if item.technical_assessment_id == case.technical_assessment_id
        ),
        None,
    )
    creative = next(
        (
            item
            for item in report.creative_assessments
            if item.creative_assessment_id == case.creative_assessment_id
        ),
        None,
    )
    if decision is None or technical is None or creative is None:
        raise ValidationError("Output review evidence is incomplete.")
    safe_answers = {
        _text(key, maximum=160): _safe_json_value(value)
        for key, value in list((answers or {}).items())[:16]
        if _text(key, maximum=160)
    }
    reviewer_reference = "reviewer_" + hashlib.sha256(
        identity.encode("utf-8", "replace")
    ).hexdigest()[:16]
    evidence_id = _stable_id(
        "quality_evidence",
        review_case_id,
        "bounded_manual_review",
        len(report.quality_evidence),
    )
    report.quality_evidence.append(
        BobaOutputQualityEvidenceV1(
            evidence_id=evidence_id,
            source_type="bounded_manual_review",
            source_id=reviewer_reference,
            category="human_review_decision",
            bounded_summary=_text(
                notes or f"Human reviewer selected {review_decision}.",
                maximum=900,
            ),
            observed_value={
                "decision": review_decision,
                "answers": safe_answers,
            },
            expected_value="bounded internal quality judgment",
            reliability="high",
            confidence=1.0,
            supports_acceptance=review_decision.startswith("accept_"),
            supports_rejection=review_decision
            in {
                "reject_output",
                "send_back_to_tool_recovery",
                "send_back_to_repair_planner",
            },
            requires_human_interpretation=True,
            warnings=[],
        )
    )
    blocking_regression = any(
        item.review_case_id == review_case_id
        and (
            item.non_negotiable
            or item.acceptance_impact in {"reject", "blocked"}
        )
        for item in report.quality_regressions
    )
    if review_decision.startswith("accept_") and (
        not technical.technical_acceptance_eligible or blocking_regression
    ):
        raise ValidationError(
            "Human review cannot override failed technical or non-negotiable requirements."
        )
    target: BobaOutputQualityHandoffTargetV1
    if review_decision == "accept_for_next_internal_stage":
        decision.decision = "accepted_for_next_internal_stage"
        decision.decision_summary = (
            "Bounded human review accepted the output for the next internal safety "
            "and workflow decision."
        )
        decision.creative_eligible = True
        decision.next_allowed_stage = "workflow_controller"
        target = "workflow_controller"
        case.review_status = "completed"
    elif review_decision == "accept_with_disclosed_limitation":
        decision.decision = "accepted_with_disclosed_limitations"
        decision.decision_summary = (
            "Bounded human review accepted the output with disclosed minor limitations."
        )
        decision.creative_eligible = True
        decision.next_allowed_stage = "workflow_controller"
        target = "workflow_controller"
        case.review_status = "completed"
    elif review_decision == "request_more_evidence":
        decision.decision = "needs_more_evidence"
        decision.decision_summary = "Human review requested more bounded evidence."
        decision.next_allowed_stage = "validator_runner"
        target = "validator_runner"
        case.review_status = "blocked"
    else:
        decision.decision = "rejected_quality"
        decision.decision_summary = (
            "Bounded human review rejected the output for internal quality reasons."
        )
        decision.next_allowed_stage = (
            "tool_recovery_brain"
            if review_decision == "send_back_to_tool_recovery"
            else "repair_planner"
        )
        target = (
            "tool_recovery_brain"
            if review_decision == "send_back_to_tool_recovery"
            else "repair_planner"
        )
        case.review_status = "completed"
    decision.human_review_required = True
    decision.workflow_resume_authorized = False
    decision.publication_authorized = False
    decision.warnings = _unique(
        [
            *decision.warnings,
            "Human quality review does not authorize publication or workflow resume.",
        ],
        limit=64,
    )
    case.human_review_required = True
    case.confidence = max(case.confidence, 0.9)
    report.review_handoffs = [
        item
        for item in report.review_handoffs
        if item.review_case_id != review_case_id
    ]
    report.review_handoffs.append(
        BobaOutputQualityHandoffV1(
            handoff_id=_stable_id(
                "quality_handoff", review_case_id, target, evidence_id
            ),
            review_case_id=review_case_id,
            acceptance_decision_id=decision.acceptance_decision_id,
            target_module=target,
            reason=decision.decision_summary,
            required_inputs=[
                "Bounded human review evidence",
                "Exact output artifact identity",
                "Existing technical and creative assessments",
            ],
            quality_issues=case.quality_issue_ids,
            failed_checks=technical.failed_required_checks,
            unavailable_checks=technical.unavailable_required_checks,
            constraints=[
                "Keep the workflow paused.",
                "Preserve outputs and source media.",
            ],
            blocked_actions=[
                "automatic workflow resume",
                "upload or publication",
                "output modification or rerender",
            ],
            allowed_advisory_actions=[
                "consider the recorded internal quality judgment"
            ],
            apply_automatically=False,
            human_approval_required=True,
            priority="high",
            warnings=[],
        )
    )
    report.signal_usage.bounded_manual_review_used = True
    report.reviewer_summary = summarize_output_quality_reviewer(report)
    json.dumps(report.model_dump(mode="json"))
    return report


def sanitize_review_export(value: Any) -> Any:
    """Remove private paths, secrets, logs, and unbounded evidence from exports."""

    if isinstance(value, BobaContract):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = _text(key, maximum=160)
            if not safe_key or _SECRET_KEY.search(safe_key):
                continue
            if safe_key.casefold() in {
                "stdout",
                "stderr",
                "raw_log",
                "raw_logs",
                "command_output",
                "frame_bytes",
                "raw_frames",
                "source_media_bytes",
            }:
                continue
            result[safe_key] = sanitize_review_export(item)
        return result
    if isinstance(value, list | tuple):
        return [sanitize_review_export(item) for item in list(value)[:1_024]]
    if isinstance(value, str):
        text = _text(value, maximum=2_000)
        if _URL_SCHEME.match(text):
            return "[external reference excluded]"
        if _ABSOLUTE_TEXT.search(text):
            return "[private path excluded]"
        return text
    return _safe_json_value(value)


__all__ = [
    "BobaCreativeQualityAssessmentV1",
    "BobaCreativeQualityDimensionV1",
    "BobaOutputAcceptanceDecisionV1",
    "BobaOutputBaselineComparisonV1",
    "BobaOutputHumanReviewPackageV1",
    "BobaOutputQualityEvidenceV1",
    "BobaOutputQualityHandoffV1",
    "BobaOutputQualityIssueV1",
    "BobaOutputQualityRegressionV1",
    "BobaOutputQualityReviewerSetV1",
    "BobaOutputQualityReviewerSummaryV1",
    "BobaOutputQualityReviewerV1",
    "BobaOutputQualitySignalUsageV1",
    "BobaOutputReviewCaseV1",
    "BobaReadOnlyQualityValidatorV1",
    "BobaReviewedOutputArtifactV1",
    "BobaTechnicalQualityAssessmentV1",
    "BobaTechnicalQualityCheckV1",
    "build_creative_quality_dimensions",
    "build_human_review_package",
    "build_output_quality_handoffs",
    "build_quality_issues",
    "build_read_only_quality_validator_registry",
    "build_technical_quality_checks",
    "compare_boba_output_quality_baseline",
    "compare_output_to_baseline",
    "execute_read_only_quality_command",
    "generate_boba_output_quality_review",
    "make_output_acceptance_decision",
    "record_boba_output_human_review",
    "resolve_review_output",
    "run_boba_output_technical_review",
    "sanitize_review_export",
    "summarize_output_quality_reviewer",
    "validate_caption_events",
    "validate_quality_command_safety",
]

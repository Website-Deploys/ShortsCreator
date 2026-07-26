"""Advisory diagnosis of saved BOBA Observer findings."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal, TypeAlias, cast

from pydantic import Field
from pydantic import ValidationError as PydanticValidationError

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.observer import (
    BobaArtifactObservationV1,
    BobaArtifactRegistryEntryV1,
    BobaDependencyObservationV1,
    BobaModuleHealthObservationV1,
    BobaNextActionRecommendationV1,
    BobaObserverFindingV1,
    BobaObserverSetV1,
    BobaSafetyObservationV1,
    BobaValidationObservationV1,
    BobaWorkflowObservationV1,
    build_boba_artifact_registry,
)
from olympus.platform.errors import ValidationError

BobaErrorCategoryV1 = Literal[
    "missing_artifact",
    "stale_artifact",
    "corrupt_artifact",
    "unreadable_artifact",
    "schema_mismatch",
    "broken_dependency",
    "missing_dependency",
    "configuration",
    "environment",
    "validation_failure",
    "validation_missing",
    "validation_stale",
    "rendering",
    "audio_video_sync",
    "media_probe",
    "storage",
    "permission",
    "rights_safety",
    "ingestion",
    "external_tool",
    "timeout",
    "resource_exhaustion",
    "data_quality",
    "frontend",
    "api",
    "unknown",
]
BobaDiagnosticSeverityV1 = Literal[
    "informational",
    "low",
    "medium",
    "high",
    "critical",
    "blocker",
    "unknown",
]
BobaDiagnosticUrgencyV1 = Literal[
    "later",
    "normal",
    "soon",
    "immediate",
    "blocked",
    "unknown",
]
BobaDiagnosisStatusV1 = Literal[
    "observed_fact",
    "probable",
    "possible",
    "insufficient_evidence",
    "conflicting_evidence",
    "unknown",
]
BobaProcessingImpactV1 = Literal[
    "none",
    "degraded",
    "partial_block",
    "full_block",
    "unsafe_to_continue",
    "unknown",
]
BobaSafetyImpactV1 = Literal[
    "none_known",
    "human_review_needed",
    "safety_gate_blocked",
    "rights_gate_blocked",
    "destructive_risk",
    "unknown",
]
BobaFindingSourceObservationTypeV1 = Literal[
    "artifact",
    "module_health",
    "workflow",
    "dependency",
    "validation",
    "safety",
    "next_action",
    "unknown",
]
BobaDiagnosticEvidenceSourceTypeV1 = Literal[
    "observer_finding",
    "artifact_observation",
    "module_health_observation",
    "dependency_observation",
    "validation_observation",
    "safety_observation",
    "workflow_observation",
    "manual_context",
    "unknown",
]
BobaDiagnosticHypothesisCategoryV1 = Literal[
    "direct_cause",
    "contributing_factor",
    "downstream_effect",
    "environment_factor",
    "data_factor",
    "configuration_factor",
    "safety_factor",
    "unknown",
]
BobaInvestigationActionCategoryV1 = Literal[
    "inspect_artifact",
    "inspect_dependency",
    "inspect_configuration",
    "inspect_environment",
    "inspect_validation_report",
    "run_future_validator",
    "collect_missing_information",
    "human_rights_review",
    "compare_timestamps",
    "compare_schema",
    "inspect_logs",
    "reproduce_manually",
    "do_not_continue",
    "escalate",
    "unknown",
]
BobaErrorDoctorEscalationTargetV1 = Literal[
    "root_cause_analyzer",
    "repair_planner",
    "tool_recovery_brain",
    "output_quality_reviewer",
    "safety_gate",
    "validator_runner",
    "rights_permission_gate",
    "human_operator",
    "unknown",
]
BobaErrorDoctorPriorityV1 = Literal["low", "medium", "high", "urgent"]

JsonObject: TypeAlias = dict[str, Any]

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SPACE = re.compile(r"\s+")
_WINDOWS_ABSOLUTE = re.compile(r"\b[A-Za-z]:[\\/][^\s;,]+")
_SEVERITY_RANK: dict[BobaDiagnosticSeverityV1, int] = {
    "informational": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
    "blocker": 5,
    "unknown": -1,
}
_WORKFLOW_CHAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "content_discovery",
        (
            "content_scout_v2",
            "research_brain",
            "trend_topic_watcher",
            "candidate_video_scorer",
            "rights_permission_gate",
        ),
    ),
    (
        "video_intelligence",
        (
            "whole_video",
            "candidate_clip_discovery",
            "clip_ranking",
            "editorial_decision",
            "explanation",
            "creative_direction_v2",
            "clip_briefs",
        ),
    ),
    (
        "creative_refinement",
        ("clip_briefs", "hook_retention", "caption_motion", "music_mood"),
    ),
    (
        "learning",
        (
            "creator_learning",
            "approval_rejection_learning",
            "experimentation",
            "performance_feedback",
        ),
    ),
    ("self_healing", ("observer", "error_doctor")),
)


def _text(value: Any, *, maximum: int = 700) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _safe_text(value: Any, *, maximum: int = 700) -> str:
    text = _text(value, maximum=maximum)
    return _WINDOWS_ABSOLUTE.sub("[private path]", text)


def _unique(
    values: Sequence[Any],
    *,
    limit: int = 64,
    maximum: int = 700,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _safe_text(value, maximum=maximum)
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("|".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _severity_max(
    values: Sequence[BobaDiagnosticSeverityV1],
) -> BobaDiagnosticSeverityV1:
    return max(values or ["unknown"], key=lambda value: _SEVERITY_RANK[value])


def _priority_for(
    severity: BobaDiagnosticSeverityV1,
) -> BobaErrorDoctorPriorityV1:
    if severity in {"blocker", "critical"}:
        return "urgent"
    if severity == "high":
        return "high"
    if severity in {"medium", "unknown"}:
        return "medium"
    return "low"


def _urgency_for(
    severity: BobaDiagnosticSeverityV1,
) -> BobaDiagnosticUrgencyV1:
    if severity == "blocker":
        return "blocked"
    if severity == "critical":
        return "immediate"
    if severity == "high":
        return "soon"
    if severity in {"medium", "low"}:
        return "normal"
    if severity == "informational":
        return "later"
    return "unknown"


def _workflow_for(module_name: str) -> str:
    for workflow, modules in _WORKFLOW_CHAINS:
        if module_name in modules:
            return workflow
    return "unknown"


def _downstream_modules(
    artifact_id: str,
    registry: Sequence[BobaArtifactRegistryEntryV1],
) -> list[str]:
    specs = {item.artifact_id: item for item in registry}
    queue = [artifact_id]
    visited = {artifact_id}
    result: list[str] = []
    while queue:
        upstream = queue.pop(0)
        for spec in registry:
            if upstream not in spec.required_dependencies:
                continue
            if spec.artifact_id in visited:
                continue
            visited.add(spec.artifact_id)
            queue.append(spec.artifact_id)
            result.append(specs[spec.artifact_id].module_name)
    return result


class BobaDiagnosticEvidenceV1(BobaContract):
    evidence_id: str = Field(min_length=1, max_length=128)
    source_type: BobaDiagnosticEvidenceSourceTypeV1
    source_id: str = Field(min_length=1, max_length=160)
    module_name: str = Field(default="", max_length=120)
    artifact_id: str = Field(default="", max_length=120)
    evidence_summary: str = Field(min_length=1, max_length=700)
    observed_value: str = Field(default="", max_length=500)
    expected_value: str = Field(default="", max_length=500)
    timestamp: str = Field(default="", max_length=80)
    confidence: float = Field(ge=0.0, le=1.0)
    usage_warning: str = Field(default="", max_length=500)


class BobaDiagnosticHypothesisV1(BobaContract):
    hypothesis_id: str = Field(min_length=1, max_length=128)
    hypothesis: str = Field(min_length=1, max_length=700)
    category: BobaDiagnosticHypothesisCategoryV1
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    conflicting_evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    confidence: float = Field(ge=0.0, le=1.0)
    verification_needed: bool = True
    suggested_check: str = Field(min_length=1, max_length=700)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaDiagnosticCaseV1(BobaContract):
    diagnostic_case_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=240)
    primary_module: str = Field(default="", max_length=120)
    primary_artifact: str = Field(default="", max_length=120)
    workflow_stage: str = Field(default="unknown", max_length=120)
    error_category: BobaErrorCategoryV1
    severity: BobaDiagnosticSeverityV1
    urgency: BobaDiagnosticUrgencyV1
    diagnosis_status: BobaDiagnosisStatusV1
    symptom_summary: str = Field(min_length=1, max_length=700)
    probable_cause_summary: str = Field(min_length=1, max_length=700)
    confirmed_facts: list[str] = Field(default_factory=list, max_length=32)
    hypotheses: list[BobaDiagnosticHypothesisV1] = Field(
        default_factory=list,
        max_length=16,
    )
    affected_modules: list[str] = Field(default_factory=list, max_length=64)
    affected_artifacts: list[str] = Field(default_factory=list, max_length=64)
    related_finding_ids: list[str] = Field(default_factory=list, max_length=128)
    evidence: list[BobaDiagnosticEvidenceV1] = Field(
        default_factory=list,
        max_length=64,
    )
    missing_information: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    processing_impact: BobaProcessingImpactV1
    safety_impact: BobaSafetyImpactV1
    recommended_investigation: list[str] = Field(
        default_factory=list,
        max_length=24,
    )
    escalation_target: BobaErrorDoctorEscalationTargetV1
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaClassifiedFindingV1(BobaContract):
    classified_finding_id: str = Field(min_length=1, max_length=128)
    observer_finding_id: str = Field(min_length=1, max_length=160)
    source_observation_type: BobaFindingSourceObservationTypeV1
    module_name: str = Field(default="", max_length=120)
    artifact_id: str = Field(default="", max_length=120)
    original_issue_level: str = Field(default="unknown", max_length=40)
    classified_category: BobaErrorCategoryV1
    severity: BobaDiagnosticSeverityV1
    is_primary_symptom: bool = False
    is_secondary_symptom: bool = False
    is_possible_cause: bool = False
    is_downstream_effect: bool = False
    duplicate_group_id: str = Field(default="", max_length=128)
    cascade_group_id: str = Field(default="", max_length=128)
    explanation: str = Field(min_length=1, max_length=700)
    evidence: list[BobaDiagnosticEvidenceV1] = Field(
        default_factory=list,
        max_length=32,
    )
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaCascadingImpactV1(BobaContract):
    cascade_id: str = Field(min_length=1, max_length=128)
    originating_case_id: str = Field(min_length=1, max_length=128)
    originating_module: str = Field(default="", max_length=120)
    impacted_modules: list[str] = Field(default_factory=list, max_length=64)
    impacted_artifacts: list[str] = Field(default_factory=list, max_length=64)
    impact_chain: list[str] = Field(default_factory=list, max_length=64)
    blocked_workflow_stages: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    severity: BobaDiagnosticSeverityV1
    explanation: str = Field(min_length=1, max_length=700)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaInvestigationRecommendationV1(BobaContract):
    recommendation_id: str = Field(min_length=1, max_length=128)
    diagnostic_case_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=700)
    action_category: BobaInvestigationActionCategoryV1
    safe: bool = True
    read_only: bool = True
    requires_command_execution: bool = False
    requires_code_change: bool = False
    requires_human_review: bool = True
    prerequisite: list[str] = Field(default_factory=list, max_length=32)
    expected_information_gain: str = Field(min_length=1, max_length=700)
    stop_condition: str = Field(min_length=1, max_length=700)
    suggested_owner_module: str = Field(default="", max_length=160)
    priority: BobaErrorDoctorPriorityV1
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaErrorDoctorEscalationHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=128)
    diagnostic_case_id: str = Field(min_length=1, max_length=128)
    target_module: BobaErrorDoctorEscalationTargetV1
    reason: str = Field(min_length=1, max_length=700)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=32)
    required_inputs: list[str] = Field(default_factory=list, max_length=32)
    blocked_actions: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False
    human_approval_required: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaErrorDoctorSummaryV1(BobaContract):
    total_observer_findings: int = Field(default=0, ge=0)
    total_diagnostic_cases: int = Field(default=0, ge=0)
    informational_count: int = Field(default=0, ge=0)
    low_count: int = Field(default=0, ge=0)
    medium_count: int = Field(default=0, ge=0)
    high_count: int = Field(default=0, ge=0)
    critical_count: int = Field(default=0, ge=0)
    blocker_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    primary_problem_count: int = Field(default=0, ge=0)
    cascading_problem_count: int = Field(default=0, ge=0)
    blocked_workflow_count: int = Field(default=0, ge=0)
    highest_priority_case: str = Field(default="", max_length=240)
    safest_next_investigation: str = Field(default="", max_length=700)
    unresolved_information: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)


class BobaErrorDoctorSignalUsageV1(BobaContract):
    observer_used: bool = False
    observer_artifact_read: bool = False
    validation_observations_used: bool = False
    dependency_observations_used: bool = False
    safety_observations_used: bool = False
    manual_context_used: bool = False
    raw_logs_read: bool = False
    external_api_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    command_execution_used: Literal[False] = False
    validator_execution_used: Literal[False] = False
    code_modification_used: Literal[False] = False
    artifact_modification_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaErrorDoctorSetV1(BobaContract):
    schema_version: Literal["boba_error_doctor_v1"] = "boba_error_doctor_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    observer_source: str = Field(min_length=1, max_length=160)
    diagnostic_cases: list[BobaDiagnosticCaseV1] = Field(
        default_factory=list,
        max_length=256,
    )
    classified_findings: list[BobaClassifiedFindingV1] = Field(
        default_factory=list,
        max_length=1024,
    )
    cascading_impacts: list[BobaCascadingImpactV1] = Field(
        default_factory=list,
        max_length=256,
    )
    investigation_recommendations: list[
        BobaInvestigationRecommendationV1
    ] = Field(default_factory=list, max_length=512)
    escalation_handoffs: list[BobaErrorDoctorEscalationHandoffV1] = Field(
        default_factory=list,
        max_length=512,
    )
    doctor_summary: BobaErrorDoctorSummaryV1
    signal_usage: BobaErrorDoctorSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


@dataclass(frozen=True, slots=True)
class _DiagnosticSeed:
    finding: BobaClassifiedFindingV1
    case_key: str
    workflow_stage: str
    diagnosis_status: BobaDiagnosisStatusV1
    processing_impact: BobaProcessingImpactV1
    safety_impact: BobaSafetyImpactV1
    missing_information: tuple[str, ...] = ()
    include_case: bool = True


def _evidence(
    *,
    source_type: BobaDiagnosticEvidenceSourceTypeV1,
    source_id: str,
    module_name: str,
    artifact_id: str,
    summary: str,
    observed: str,
    expected: str,
    timestamp: str = "",
    confidence: float = 0.9,
    warning: str = "",
) -> BobaDiagnosticEvidenceV1:
    return BobaDiagnosticEvidenceV1(
        evidence_id=_stable_id(
            "doctor_evidence",
            source_type,
            source_id,
            module_name,
            artifact_id,
            summary,
        ),
        source_type=source_type,
        source_id=_safe_text(source_id, maximum=160) or "unknown",
        module_name=_safe_text(module_name, maximum=120),
        artifact_id=_safe_text(artifact_id, maximum=120),
        evidence_summary=_safe_text(summary, maximum=700)
        or "Bounded local evidence was unavailable.",
        observed_value=_safe_text(observed, maximum=500),
        expected_value=_safe_text(expected, maximum=500),
        timestamp=_safe_text(timestamp, maximum=80),
        confidence=max(0.0, min(1.0, confidence)),
        usage_warning=_safe_text(warning, maximum=500),
    )


def _finding(
    *,
    source_id: str,
    source_type: BobaFindingSourceObservationTypeV1,
    module_name: str,
    artifact_id: str,
    original_issue_level: str,
    category: BobaErrorCategoryV1,
    severity: BobaDiagnosticSeverityV1,
    primary: bool,
    secondary: bool,
    possible_cause: bool,
    downstream: bool,
    duplicate_key: str,
    cascade_key: str,
    explanation: str,
    evidence: Sequence[BobaDiagnosticEvidenceV1],
    confidence: float,
    warnings: Sequence[str] = (),
) -> BobaClassifiedFindingV1:
    return BobaClassifiedFindingV1(
        classified_finding_id=_stable_id(
            "classified_finding",
            source_type,
            source_id,
            module_name,
            artifact_id,
            category,
        ),
        observer_finding_id=_safe_text(source_id, maximum=160) or "unknown",
        source_observation_type=source_type,
        module_name=_safe_text(module_name, maximum=120),
        artifact_id=_safe_text(artifact_id, maximum=120),
        original_issue_level=_safe_text(
            original_issue_level,
            maximum=40,
        )
        or "unknown",
        classified_category=category,
        severity=severity,
        is_primary_symptom=primary,
        is_secondary_symptom=secondary,
        is_possible_cause=possible_cause,
        is_downstream_effect=downstream,
        duplicate_group_id=_stable_id("duplicate_group", duplicate_key),
        cascade_group_id=(
            _stable_id("cascade_group", cascade_key) if cascade_key else ""
        ),
        explanation=_safe_text(explanation, maximum=700)
        or "The saved observation requires review.",
        evidence=list(evidence)[:32],
        confidence=max(0.0, min(1.0, confidence)),
        warnings=_unique(warnings, limit=24),
    )


def _artifact_category(
    artifact: BobaArtifactObservationV1,
    observer_finding: BobaObserverFindingV1 | None,
) -> BobaErrorCategoryV1:
    text = " ".join(
        [
            observer_finding.category if observer_finding else "",
            observer_finding.message if observer_finding else "",
            *artifact.warnings,
        ]
    ).casefold()
    if not artifact.exists:
        return "missing_artifact"
    if not artifact.readable:
        if "corrupt" in text or "json" in text:
            return "corrupt_artifact"
        return "unreadable_artifact"
    if artifact.freshness_status == "stale":
        return "stale_artifact"
    if "schema" in text:
        return "schema_mismatch"
    return "data_quality" if artifact.issue_level != "ok" else "unknown"


def _artifact_severity(
    artifact: BobaArtifactObservationV1,
    category: BobaErrorCategoryV1,
) -> BobaDiagnosticSeverityV1:
    if category in {"corrupt_artifact", "unreadable_artifact"}:
        return "blocker" if artifact.dependency_status != "not_applicable" else "high"
    if category == "missing_artifact":
        if artifact.dependency_status == "missing_upstream":
            return "high"
        return "medium"
    if category in {"stale_artifact", "schema_mismatch"}:
        return "medium"
    if artifact.issue_level == "blocker":
        return "high"
    if artifact.issue_level == "warning":
        return "low"
    if artifact.issue_level == "unknown":
        return "unknown"
    return "informational"


def _artifact_seed(
    artifact: BobaArtifactObservationV1,
    observer_finding: BobaObserverFindingV1 | None,
    dependencies: Sequence[BobaDependencyObservationV1],
) -> _DiagnosticSeed:
    source_id = (
        observer_finding.finding_id
        if observer_finding is not None
        else _stable_id("observer_artifact", artifact.artifact_id)
    )
    category = _artifact_category(artifact, observer_finding)
    severity = _artifact_severity(artifact, category)
    missing_upstream = [
        item.upstream_artifact
        for item in dependencies
        if item.downstream_artifact == artifact.artifact_id
        and item.status in {"broken", "missing"}
        and "upstream" in item.reason.casefold()
    ]
    upstream = missing_upstream[0] if missing_upstream else ""
    downstream = artifact.dependency_status == "missing_upstream"
    possible_cause = category in {
        "missing_artifact",
        "corrupt_artifact",
        "unreadable_artifact",
        "stale_artifact",
        "schema_mismatch",
    } and not downstream
    diagnosis: BobaDiagnosisStatusV1
    if category in {"corrupt_artifact", "unreadable_artifact"}:
        diagnosis = "observed_fact"
    elif category in {"missing_artifact", "stale_artifact"}:
        diagnosis = "probable" if not downstream else "possible"
    else:
        diagnosis = "insufficient_evidence"
    case_root = upstream or artifact.artifact_id
    case_key = f"{category if not upstream else 'missing_dependency'}:{case_root}"
    observed = (
        f"exists={artifact.exists}; readable={artifact.readable}; "
        f"freshness={artifact.freshness_status}; "
        f"dependency={artifact.dependency_status}"
    )
    evidence = _evidence(
        source_type=(
            "observer_finding"
            if observer_finding is not None
            else "artifact_observation"
        ),
        source_id=source_id,
        module_name=artifact.module_name,
        artifact_id=artifact.artifact_id,
        summary=(
            observer_finding.message
            if observer_finding is not None
            else f"{artifact.artifact_id} has an observed artifact issue."
        ),
        observed=observed,
        expected="Present, readable, current artifact with satisfied dependencies.",
        timestamp=artifact.created_at,
        confidence=0.96 if category != "unknown" else 0.5,
        warning="Artifact content was not copied into the diagnosis.",
    )
    processing: BobaProcessingImpactV1
    if severity == "blocker":
        processing = "full_block"
    elif severity == "high":
        processing = "partial_block"
    elif severity in {"medium", "low"}:
        processing = "degraded"
    else:
        processing = "none"
    missing_information = (
        "Why the artifact is absent or unreadable.",
        "Whether the normal artifact-generation step completed.",
    )
    return _DiagnosticSeed(
        finding=_finding(
            source_id=source_id,
            source_type="artifact",
            module_name=artifact.module_name,
            artifact_id=artifact.artifact_id,
            original_issue_level=artifact.issue_level,
            category=category,
            severity=severity,
            primary=not downstream,
            secondary=downstream,
            possible_cause=possible_cause,
            downstream=downstream,
            duplicate_key=f"{category}:{artifact.module_name}:{artifact.artifact_id}",
            cascade_key=case_root,
            explanation=(
                f"{artifact.module_name} has a direct saved-artifact symptom."
                if not downstream
                else (
                    f"{artifact.module_name} appears affected by unavailable "
                    f"upstream artifact {upstream or 'unknown'}."
                )
            ),
            evidence=[evidence],
            confidence=evidence.confidence,
            warnings=[
                "Artifact state is observed; the underlying root cause is not proven.",
            ],
        ),
        case_key=case_key,
        workflow_stage=_workflow_for(artifact.module_name),
        diagnosis_status=diagnosis,
        processing_impact=processing,
        safety_impact="none_known",
        missing_information=missing_information,
    )


def _module_seed(
    module: BobaModuleHealthObservationV1,
    observer_finding: BobaObserverFindingV1 | None,
) -> _DiagnosticSeed:
    source_id = (
        observer_finding.finding_id
        if observer_finding is not None
        else _stable_id("observer_module", module.module_name)
    )
    primary_artifact = module.expected_artifacts[0] if module.expected_artifacts else ""
    missing_upstream = module.missing_inputs[0] if module.missing_inputs else ""
    if module.health_status == "blocked" and missing_upstream:
        category: BobaErrorCategoryV1 = "missing_dependency"
        severity: BobaDiagnosticSeverityV1 = "high"
        downstream = True
        possible_cause = False
        case_key = f"missing_dependency:{missing_upstream}"
    elif module.health_status == "blocked":
        category = (
            "corrupt_artifact"
            if "unreadable" in module.blocked_reason.casefold()
            else "broken_dependency"
        )
        severity = "blocker"
        downstream = False
        possible_cause = True
        case_key = f"{category}:{primary_artifact or module.module_name}"
    elif module.health_status == "stale":
        category = "stale_artifact"
        severity = "medium"
        downstream = False
        possible_cause = True
        case_key = f"stale_artifact:{primary_artifact or module.module_name}"
    elif module.health_status in {"missing", "partial"}:
        category = "missing_artifact"
        severity = "medium" if module.required_dependencies else "low"
        downstream = bool(module.missing_inputs)
        possible_cause = not downstream
        case_key = (
            f"missing_dependency:{missing_upstream}"
            if missing_upstream
            else f"missing_artifact:{primary_artifact or module.module_name}"
        )
    else:
        category = "data_quality"
        severity = "unknown"
        downstream = False
        possible_cause = False
        case_key = f"data_quality:{module.module_name}"
    summary = (
        observer_finding.message
        if observer_finding is not None
        else (
            f"{module.module_name} health is {module.health_status}; "
            f"missing inputs={', '.join(module.missing_inputs) or 'none'}."
        )
    )
    evidence = _evidence(
        source_type=(
            "observer_finding"
            if observer_finding is not None
            else "module_health_observation"
        ),
        source_id=source_id,
        module_name=module.module_name,
        artifact_id=primary_artifact,
        summary=summary,
        observed=(
            f"health={module.health_status}; "
            f"missing_inputs={','.join(module.missing_inputs)}; "
            f"missing_outputs={','.join(module.missing_outputs)}"
        ),
        expected="Healthy module with required inputs and outputs.",
        confidence=module.confidence,
        warning="Module health is derived from saved Observer evidence.",
    )
    return _DiagnosticSeed(
        finding=_finding(
            source_id=source_id,
            source_type="module_health",
            module_name=module.module_name,
            artifact_id=primary_artifact,
            original_issue_level=(
                observer_finding.issue_level
                if observer_finding is not None
                else module.health_status
            ),
            category=category,
            severity=severity,
            primary=not downstream,
            secondary=downstream,
            possible_cause=possible_cause,
            downstream=downstream,
            duplicate_key=f"{category}:{module.module_name}:{primary_artifact}",
            cascade_key=missing_upstream or primary_artifact,
            explanation=summary,
            evidence=[evidence],
            confidence=module.confidence,
            warnings=module.warnings,
        ),
        case_key=case_key,
        workflow_stage=_workflow_for(module.module_name),
        diagnosis_status=(
            "probable"
            if possible_cause
            else "possible" if downstream else "insufficient_evidence"
        ),
        processing_impact=(
            "full_block"
            if module.health_status == "blocked"
            else "degraded"
        ),
        safety_impact="none_known",
        missing_information=(
            "The module execution record and bounded failure reason.",
        ),
    )


def _dependency_seed(
    dependency: BobaDependencyObservationV1,
    registry: Sequence[BobaArtifactRegistryEntryV1],
) -> _DiagnosticSeed | None:
    if dependency.status == "satisfied":
        return None
    downstream_spec = next(
        (
            item
            for item in registry
            if item.artifact_id == dependency.downstream_artifact
        ),
        None,
    )
    required = bool(
        downstream_spec
        and dependency.upstream_artifact
        in downstream_spec.required_dependencies
    )
    reason = dependency.reason.casefold()
    if dependency.status == "stale":
        category: BobaErrorCategoryV1 = "stale_artifact"
        severity: BobaDiagnosticSeverityV1 = "medium" if required else "low"
        primary = False
        downstream = True
        possible_cause = True
        diagnosis: BobaDiagnosisStatusV1 = "probable"
        case_key = f"stale_artifact:{dependency.downstream_artifact}"
    elif dependency.status == "missing" and "upstream output exists" in reason:
        category = "missing_artifact"
        severity = "medium" if required else "informational"
        primary = True
        downstream = False
        possible_cause = True
        diagnosis = "probable"
        case_key = f"missing_artifact:{dependency.downstream_artifact}"
    elif dependency.status in {"missing", "broken"}:
        category = "missing_dependency" if "missing" in reason else "broken_dependency"
        severity = "high" if required else "low"
        primary = False
        downstream = True
        possible_cause = False
        diagnosis = "possible"
        case_key = f"missing_dependency:{dependency.upstream_artifact}"
    else:
        category = "broken_dependency"
        severity = "unknown"
        primary = False
        downstream = True
        possible_cause = False
        diagnosis = "insufficient_evidence"
        case_key = f"broken_dependency:{dependency.upstream_artifact}"
    source_id = dependency.dependency_id
    evidence = _evidence(
        source_type="dependency_observation",
        source_id=source_id,
        module_name=dependency.downstream_module,
        artifact_id=dependency.downstream_artifact,
        summary=dependency.reason,
        observed=(
            f"status={dependency.status}; "
            f"upstream={dependency.upstream_artifact}; "
            f"downstream={dependency.downstream_artifact}"
        ),
        expected="Required upstream available before downstream output.",
        confidence=0.93 if dependency.status != "unknown" else 0.5,
        warning="Dependency direction is known; causal failure is not proven.",
    )
    return _DiagnosticSeed(
        finding=_finding(
            source_id=source_id,
            source_type="dependency",
            module_name=dependency.downstream_module,
            artifact_id=dependency.downstream_artifact,
            original_issue_level=dependency.issue_level,
            category=category,
            severity=severity,
            primary=primary,
            secondary=downstream,
            possible_cause=possible_cause,
            downstream=downstream,
            duplicate_key=(
                f"{category}:{dependency.upstream_artifact}:"
                f"{dependency.downstream_artifact}"
            ),
            cascade_key=dependency.upstream_artifact,
            explanation=dependency.reason,
            evidence=[evidence],
            confidence=evidence.confidence,
            warnings=[
                *dependency.warnings,
                (
                    "This is an optional dependency and is not a blocking fault."
                    if not required
                    else ""
                ),
            ],
        ),
        case_key=case_key,
        workflow_stage=_workflow_for(dependency.downstream_module),
        diagnosis_status=diagnosis,
        processing_impact=(
            "partial_block"
            if required and dependency.status in {"missing", "broken"}
            else "degraded" if severity in {"medium", "low"} else "none"
        ),
        safety_impact="none_known",
        missing_information=(
            "Whether the normal upstream and downstream module steps ran.",
        ),
    )


def _validation_seed(
    validation: BobaValidationObservationV1,
) -> _DiagnosticSeed | None:
    if (
        validation.latest_status == "passed"
        and validation.freshness_status == "fresh"
    ):
        return None
    if validation.latest_status == "failed":
        category: BobaErrorCategoryV1 = "validation_failure"
        severity: BobaDiagnosticSeverityV1 = "high"
        diagnosis: BobaDiagnosisStatusV1 = "observed_fact"
        explanation = (
            f"{validation.validator_name} reports failure; this confirms a "
            "validation failure but not its software root cause."
        )
    elif validation.latest_status == "missing":
        category = "validation_missing"
        severity = "low"
        diagnosis = "insufficient_evidence"
        explanation = (
            f"{validation.validator_name} has no saved report. Absence of a "
            "report is not proof of software failure."
        )
    elif validation.freshness_status == "stale":
        category = "validation_stale"
        severity = "low"
        diagnosis = "probable"
        explanation = (
            f"{validation.validator_name} report is timestamp-stale and needs "
            "manual review."
        )
    elif validation.latest_status == "partial":
        category = "validation_failure"
        severity = "medium"
        diagnosis = "possible"
        explanation = (
            f"{validation.validator_name} reports a partial result requiring "
            "manual inspection."
        )
    else:
        category = "unknown"
        severity = "unknown"
        diagnosis = "insufficient_evidence"
        explanation = (
            f"{validation.validator_name} report format does not expose a "
            "recognized status."
        )
    source_id = _stable_id(
        "observer_validation",
        validation.validator_name,
        validation.latest_status,
        validation.report_created_at,
    )
    evidence = _evidence(
        source_type="validation_observation",
        source_id=source_id,
        module_name=validation.validator_name,
        artifact_id="",
        summary=explanation,
        observed=(
            f"status={validation.latest_status}; "
            f"freshness={validation.freshness_status}; "
            f"report_exists={validation.report_exists}"
        ),
        expected="Fresh recognized validation report.",
        timestamp=validation.report_created_at,
        confidence=0.96 if validation.latest_status != "unknown" else 0.45,
        warning="Error Doctor did not execute this validator.",
    )
    return _DiagnosticSeed(
        finding=_finding(
            source_id=source_id,
            source_type="validation",
            module_name=validation.validator_name,
            artifact_id="",
            original_issue_level=validation.issue_level,
            category=category,
            severity=severity,
            primary=True,
            secondary=False,
            possible_cause=False,
            downstream=False,
            duplicate_key=f"{category}:{validation.validator_name}",
            cascade_key="",
            explanation=explanation,
            evidence=[evidence],
            confidence=evidence.confidence,
            warnings=validation.warnings,
        ),
        case_key=f"{category}:{validation.validator_name}",
        workflow_stage="validation",
        diagnosis_status=diagnosis,
        processing_impact=(
            "partial_block"
            if validation.latest_status == "failed"
            else "degraded"
        ),
        safety_impact="human_review_needed",
        missing_information=(
            "The bounded validator failure details or a current report.",
        ),
    )


def _safety_seed(
    safety: BobaSafetyObservationV1,
) -> _DiagnosticSeed | None:
    if safety.status == "safe_to_review":
        return None
    if safety.safety_area == "rights_permission":
        category: BobaErrorCategoryV1 = "rights_safety"
        severity: BobaDiagnosticSeverityV1 = "blocker"
        processing: BobaProcessingImpactV1 = "unsafe_to_continue"
        safety_impact: BobaSafetyImpactV1 = "rights_gate_blocked"
        include_case = True
        diagnosis: BobaDiagnosisStatusV1 = "observed_fact"
    elif safety.safety_area == "ingestion":
        category = "ingestion"
        severity = "blocker"
        processing = "unsafe_to_continue"
        safety_impact = "safety_gate_blocked"
        include_case = True
        diagnosis = "observed_fact"
    elif safety.safety_area == "rendering":
        category = "rendering"
        severity = "high" if safety.status == "blocked" else "medium"
        processing = "full_block" if safety.status == "blocked" else "degraded"
        safety_impact = "human_review_needed"
        include_case = True
        diagnosis = "possible"
    elif safety.safety_area == "validation_gap":
        category = "validation_missing"
        severity = "low"
        processing = "degraded"
        safety_impact = "human_review_needed"
        include_case = True
        diagnosis = "insufficient_evidence"
    elif safety.safety_area == "destructive_action":
        category = "unknown"
        severity = "informational"
        processing = "none"
        safety_impact = "none_known"
        include_case = False
        diagnosis = "observed_fact"
    else:
        category = "unknown"
        severity = "informational"
        processing = "none"
        safety_impact = "none_known"
        include_case = False
        diagnosis = "observed_fact"
    source_id = safety.safety_id
    evidence = _evidence(
        source_type="safety_observation",
        source_id=source_id,
        module_name=safety.safety_area,
        artifact_id=(safety.related_artifacts[0] if safety.related_artifacts else ""),
        summary=safety.reason,
        observed=f"status={safety.status}",
        expected="Human-reviewed safety state before consequential processing.",
        confidence=0.98,
        warning="Safety state is intentional policy evidence, not proof of a code defect.",
    )
    cascade_key = (
        "rights_permission_gate"
        if safety.safety_area in {"rights_permission", "ingestion"}
        else safety.safety_area
    )
    return _DiagnosticSeed(
        finding=_finding(
            source_id=source_id,
            source_type="safety",
            module_name=safety.safety_area,
            artifact_id=(safety.related_artifacts[0] if safety.related_artifacts else ""),
            original_issue_level=safety.status,
            category=category,
            severity=severity,
            primary=safety.safety_area == "rights_permission",
            secondary=safety.safety_area == "ingestion",
            possible_cause=False,
            downstream=safety.safety_area == "ingestion",
            duplicate_key=f"{category}:{safety.safety_area}",
            cascade_key=cascade_key,
            explanation=(
                f"{safety.reason} This is an intentional safety state, not "
                "automatically a software defect."
            ),
            evidence=[evidence],
            confidence=evidence.confidence,
            warnings=safety.warnings,
        ),
        case_key=(
            "rights_safety:rights_permission_gate"
            if safety.safety_area in {"rights_permission", "ingestion"}
            else f"{category}:{safety.safety_area}"
        ),
        workflow_stage=(
            "content_discovery"
            if safety.safety_area in {"rights_permission", "ingestion"}
            else safety.safety_area
        ),
        diagnosis_status=diagnosis,
        processing_impact=processing,
        safety_impact=safety_impact,
        missing_information=(
            "Human rights, permission, or safety review outcome.",
        ),
        include_case=include_case,
    )


def _workflow_seed(
    workflow: BobaWorkflowObservationV1,
    observer_finding: BobaObserverFindingV1,
) -> _DiagnosticSeed:
    category: BobaErrorCategoryV1 = (
        "broken_dependency" if workflow.blocked_modules else "data_quality"
    )
    severity: BobaDiagnosticSeverityV1 = (
        "high" if workflow.blocked_modules else "low"
    )
    source_id = observer_finding.finding_id
    evidence = _evidence(
        source_type="observer_finding",
        source_id=source_id,
        module_name=workflow.workflow_stage,
        artifact_id="",
        summary=observer_finding.message,
        observed=f"blocked_modules={','.join(workflow.blocked_modules)}",
        expected="Workflow modules ready or complete.",
        confidence=0.85,
        warning="Workflow state is inferred from saved module observations.",
    )
    return _DiagnosticSeed(
        finding=_finding(
            source_id=source_id,
            source_type="workflow",
            module_name=workflow.workflow_stage,
            artifact_id="",
            original_issue_level=observer_finding.issue_level,
            category=category,
            severity=severity,
            primary=False,
            secondary=True,
            possible_cause=False,
            downstream=True,
            duplicate_key=f"{category}:{workflow.workflow_stage}",
            cascade_key=workflow.workflow_stage,
            explanation=observer_finding.message,
            evidence=[evidence],
            confidence=0.85,
            warnings=workflow.warnings,
        ),
        case_key=f"workflow:{workflow.workflow_stage}",
        workflow_stage=workflow.workflow_stage,
        diagnosis_status="possible",
        processing_impact=(
            "partial_block" if workflow.blocked_modules else "degraded"
        ),
        safety_impact="none_known",
        missing_information=(
            "The nearest specific upstream artifact responsible for the workflow block.",
        ),
    )


def _next_action_seed(
    recommendation: BobaNextActionRecommendationV1,
) -> _DiagnosticSeed | None:
    if recommendation.safe:
        return None
    source_id = recommendation.recommendation_id
    category: BobaErrorCategoryV1 = (
        "rights_safety"
        if "rights" in recommendation.action.casefold()
        else "unknown"
    )
    evidence = _evidence(
        source_type="manual_context",
        source_id=source_id,
        module_name=recommendation.suggested_owner_module,
        artifact_id="",
        summary=recommendation.reason,
        observed=recommendation.action,
        expected="Unsafe action remains blocked pending human review.",
        confidence=0.9,
        warning="The recommendation is advisory and was not applied.",
    )
    return _DiagnosticSeed(
        finding=_finding(
            source_id=source_id,
            source_type="next_action",
            module_name=recommendation.suggested_owner_module,
            artifact_id="",
            original_issue_level=recommendation.priority,
            category=category,
            severity="informational",
            primary=False,
            secondary=True,
            possible_cause=False,
            downstream=True,
            duplicate_key=f"unsafe_action:{recommendation.action}",
            cascade_key="",
            explanation=(
                f"Observer marked this next action unsafe: "
                f"{recommendation.action}"
            ),
            evidence=[evidence],
            confidence=0.9,
            warnings=recommendation.warnings,
        ),
        case_key=f"unsafe_action:{recommendation.recommendation_id}",
        workflow_stage="self_healing",
        diagnosis_status="observed_fact",
        processing_impact="none",
        safety_impact="human_review_needed",
        include_case=False,
    )


def _manual_category(
    summary: str,
    explicit: str,
) -> BobaErrorCategoryV1:
    allowed = {
        "missing_artifact",
        "stale_artifact",
        "corrupt_artifact",
        "unreadable_artifact",
        "schema_mismatch",
        "broken_dependency",
        "missing_dependency",
        "configuration",
        "environment",
        "validation_failure",
        "validation_missing",
        "validation_stale",
        "rendering",
        "audio_video_sync",
        "media_probe",
        "storage",
        "permission",
        "rights_safety",
        "ingestion",
        "external_tool",
        "timeout",
        "resource_exhaustion",
        "data_quality",
        "frontend",
        "api",
        "unknown",
    }
    normalized = explicit.casefold().strip()
    if normalized in allowed:
        return cast(BobaErrorCategoryV1, normalized)
    text = summary.casefold()
    if "resource" in text and (
        "exhaust" in text or "winerror 1450" in text or "memory" in text
    ):
        return "resource_exhaustion"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "ffprobe" in text or "media probe" in text:
        return "media_probe"
    if "sync" in text and ("audio" in text or "video" in text):
        return "audio_video_sync"
    if "ffmpeg" in text or "executable" in text or "tool" in text:
        return "external_tool"
    if "configuration" in text or "config" in text:
        return "configuration"
    if "environment" in text or "path" in text:
        return "environment"
    if "storage" in text or "write" in text:
        return "storage"
    if "render" in text:
        return "rendering"
    if "api" in text:
        return "api"
    if "frontend" in text or "ui" in text:
        return "frontend"
    return "unknown"


def _manual_seed(
    value: str | Mapping[str, Any],
    *,
    index: int,
) -> _DiagnosticSeed | None:
    if isinstance(value, str):
        summary = _safe_text(value, maximum=500)
        payload: Mapping[str, Any] = {}
    else:
        payload = value
        summary = _safe_text(
            payload.get("summary")
            or payload.get("message")
            or payload.get("error"),
            maximum=500,
        )
    if not summary:
        return None
    category = _manual_category(
        summary,
        _text(payload.get("category"), maximum=80),
    )
    module_name = _safe_text(
        payload.get("module_name") or payload.get("module"),
        maximum=120,
    )
    artifact_id = _safe_text(payload.get("artifact_id"), maximum=120)
    severity_value = _text(payload.get("severity"), maximum=40).casefold()
    severity: BobaDiagnosticSeverityV1
    if severity_value in _SEVERITY_RANK:
        severity = severity_value
    elif category == "resource_exhaustion":
        severity = "critical"
    elif category in {
        "audio_video_sync",
        "timeout",
        "external_tool",
        "media_probe",
        "rendering",
        "configuration",
        "environment",
        "storage",
    }:
        severity = "high"
    else:
        severity = "unknown"
    source_id = _stable_id("manual_error_summary", str(index), summary)
    evidence = _evidence(
        source_type="manual_context",
        source_id=source_id,
        module_name=module_name,
        artifact_id=artifact_id,
        summary="Bounded local diagnostic summary was provided.",
        observed=summary,
        expected="Additional local evidence is needed before causal claims.",
        timestamp=_safe_text(payload.get("timestamp"), maximum=80),
        confidence=0.55,
        warning="This text was user-provided and was not independently verified.",
    )
    conflicting = bool(payload.get("conflicting")) or "conflict" in summary.casefold()
    return _DiagnosticSeed(
        finding=_finding(
            source_id=source_id,
            source_type="unknown",
            module_name=module_name,
            artifact_id=artifact_id,
            original_issue_level="manual_context",
            category=category,
            severity=severity,
            primary=True,
            secondary=False,
            possible_cause=True,
            downstream=False,
            duplicate_key=f"manual:{category}:{module_name}:{artifact_id}",
            cascade_key=artifact_id or module_name,
            explanation=(
                "Bounded manual context suggests a possible issue; it is not "
                "confirmed by Observer."
            ),
            evidence=[evidence],
            confidence=0.45 if conflicting else 0.55,
            warnings=[
                "Manual diagnostic context is unverified.",
                "Conflicting evidence was declared." if conflicting else "",
            ],
        ),
        case_key=f"manual:{category}:{module_name or artifact_id or index}",
        workflow_stage=_workflow_for(module_name),
        diagnosis_status=(
            "conflicting_evidence" if conflicting else "possible"
        ),
        processing_impact=(
            "full_block"
            if severity in {"blocker", "critical"}
            else "partial_block" if severity == "high" else "unknown"
        ),
        safety_impact="unknown",
        missing_information=(
            "A bounded local error record from the responsible module.",
            "Independent Observer or validation evidence.",
        ),
    )


def _normalized_seeds(
    observer: BobaObserverSetV1,
    *,
    registry: Sequence[BobaArtifactRegistryEntryV1],
    manual_context: Mapping[str, Any] | None,
    error_summaries: Sequence[str | Mapping[str, Any]] | None,
) -> list[_DiagnosticSeed]:
    seeds: list[_DiagnosticSeed] = []
    dependencies = observer.dependency_observations
    for artifact in observer.artifact_observations:
        if artifact.issue_level == "ok" and not artifact.findings:
            continue
        artifact_findings: Sequence[BobaObserverFindingV1 | None] = (
            artifact.findings if artifact.findings else (None,)
        )
        seeds.extend(
            _artifact_seed(artifact, item, dependencies)
            for item in artifact_findings
        )
    for module in observer.module_health_observations:
        if module.health_status == "healthy" and not module.findings:
            continue
        module_findings: Sequence[BobaObserverFindingV1 | None] = (
            module.findings if module.findings else (None,)
        )
        seeds.extend(_module_seed(module, item) for item in module_findings)
    for workflow in observer.workflow_observations:
        seeds.extend(
            _workflow_seed(workflow, finding)
            for finding in workflow.findings
        )
    for dependency in dependencies:
        seed = _dependency_seed(dependency, registry)
        if seed is not None:
            seeds.append(seed)
    for validation in observer.validation_observations:
        seed = _validation_seed(validation)
        if seed is not None:
            seeds.append(seed)
    for safety in observer.safety_observations:
        seed = _safety_seed(safety)
        if seed is not None:
            seeds.append(seed)
    for recommendation in observer.next_action_recommendations:
        seed = _next_action_seed(recommendation)
        if seed is not None:
            seeds.append(seed)
    for index, value in enumerate(list(error_summaries or ())[:32]):
        seed = _manual_seed(value, index=index)
        if seed is not None:
            seeds.append(seed)
    if manual_context:
        for key, category in (
            ("configuration_issue", "configuration"),
            ("environment_issue", "environment"),
        ):
            context_value = manual_context.get(key)
            if context_value:
                seed = _manual_seed(
                    {
                        "summary": context_value,
                        "category": category,
                        "module_name": manual_context.get("module_name", ""),
                    },
                    index=len(seeds),
                )
                if seed is not None:
                    seeds.append(seed)
    return seeds[:1024]


def normalize_observer_findings(
    observer: BobaObserverSetV1,
    *,
    registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
    manual_context: Mapping[str, Any] | None = None,
    error_summaries: Sequence[str | Mapping[str, Any]] | None = None,
) -> list[BobaClassifiedFindingV1]:
    """Normalize saved Observer records without mutating the source report."""

    effective_registry = tuple(registry or build_boba_artifact_registry())
    return [
        seed.finding
        for seed in _normalized_seeds(
            observer,
            registry=effective_registry,
            manual_context=manual_context,
            error_summaries=error_summaries,
        )
    ]


def _hypotheses_for(
    category: BobaErrorCategoryV1,
    evidence: Sequence[BobaDiagnosticEvidenceV1],
    *,
    conflicting: bool,
) -> list[BobaDiagnosticHypothesisV1]:
    evidence_ids = [item.evidence_id for item in evidence][:16]
    values: list[
        tuple[str, BobaDiagnosticHypothesisCategoryV1, str, float]
    ]
    if category in {"missing_artifact", "missing_dependency"}:
        values = [
            (
                "The normal artifact-generation step may not have completed.",
                "direct_cause",
                "Inspect the saved workflow/module record and upstream artifact.",
                0.66,
            ),
            (
                "A local artifact write may not have completed or persisted.",
                "contributing_factor",
                "Inspect bounded storage status and artifact metadata.",
                0.42,
            ),
        ]
    elif category in {"corrupt_artifact", "unreadable_artifact"}:
        values = [
            (
                "The local JSON write may have been interrupted.",
                "data_factor",
                "Preserve the file and inspect bounded JSON/readability evidence.",
                0.58,
            ),
            (
                "The saved artifact may use an unsupported or malformed schema.",
                "data_factor",
                "Compare the schema field with the current contract.",
                0.52,
            ),
        ]
    elif category == "stale_artifact":
        values = [
            (
                "The downstream artifact may have been generated before an upstream change.",
                "downstream_effect",
                "Compare upstream and downstream timestamps.",
                0.74,
            )
        ]
    elif category in {"validation_missing", "validation_stale"}:
        values = [
            (
                "Current validation evidence may not have been generated.",
                "contributing_factor",
                "A human may run the relevant validator later.",
                0.7,
            )
        ]
    elif category == "validation_failure":
        values = [
            (
                "The validator report may identify a narrower artifact or environment fault.",
                "contributing_factor",
                "Inspect the bounded validation report details.",
                0.6,
            )
        ]
    elif category in {"rights_safety", "permission", "ingestion"}:
        values = [
            (
                "Rights or permission evidence may be incomplete or intentionally blocked.",
                "safety_factor",
                "Perform human rights and permission review.",
                0.82,
            )
        ]
    elif category in {
        "environment",
        "external_tool",
        "timeout",
        "resource_exhaustion",
        "media_probe",
        "rendering",
    }:
        values = [
            (
                "The local environment or required executable may be unavailable or constrained.",
                "environment_factor",
                "Inspect bounded environment/tool availability evidence manually.",
                0.5,
            )
        ]
    elif category == "configuration":
        values = [
            (
                "Required local configuration may be incomplete.",
                "configuration_factor",
                "Inspect the relevant non-secret configuration keys.",
                0.5,
            )
        ]
    else:
        values = [
            (
                "Additional local evidence may reveal a more specific cause.",
                "unknown",
                "Collect bounded evidence without changing the project.",
                0.35,
            )
        ]
    results: list[BobaDiagnosticHypothesisV1] = []
    for hypothesis, hypothesis_category, suggested_check, confidence in values:
        effective_confidence = max(0.1, confidence - (0.2 if conflicting else 0.0))
        results.append(
            BobaDiagnosticHypothesisV1(
                hypothesis_id=_stable_id(
                    "doctor_hypothesis",
                    category,
                    hypothesis,
                    *evidence_ids,
                ),
                hypothesis=hypothesis,
                category=hypothesis_category,
                supporting_evidence_ids=evidence_ids,
                conflicting_evidence_ids=(evidence_ids[:1] if conflicting else []),
                confidence=effective_confidence,
                verification_needed=True,
                suggested_check=suggested_check,
                warnings=[
                    "This is a hypothesis, not a proven root cause.",
                    "Conflicting evidence lowers confidence." if conflicting else "",
                ],
            )
        )
    return results


def _probable_summary(category: BobaErrorCategoryV1) -> str:
    summaries = {
        "missing_artifact": (
            "The artifact absence is confirmed. The normal generation step may "
            "be incomplete, but the reason it is absent is not proven."
        ),
        "missing_dependency": (
            "A required upstream artifact appears unavailable. This is a "
            "probable cause of downstream symptoms, not a proven code defect."
        ),
        "broken_dependency": (
            "The saved dependency chain is broken or inconsistent. Deeper "
            "causal analysis is still required."
        ),
        "corrupt_artifact": (
            "The artifact-level readability fault is confirmed; an interrupted "
            "write or schema problem remains hypothetical."
        ),
        "unreadable_artifact": (
            "The artifact cannot be read. The underlying storage, encoding, or "
            "schema cause is not proven."
        ),
        "stale_artifact": (
            "Timestamp ordering suggests the downstream output predates an "
            "upstream change."
        ),
        "validation_missing": (
            "Validation evidence is absent. This is a gap, not proof that the "
            "software failed."
        ),
        "validation_stale": (
            "Validation evidence is old enough to require manual refresh."
        ),
        "validation_failure": (
            "A failed validation status is confirmed, while the technical root "
            "cause remains unresolved."
        ),
        "rights_safety": (
            "The Rights Gate state intentionally blocks or limits processing; "
            "this is a safety decision, not automatically a software defect."
        ),
        "ingestion": (
            "Ingestion is intentionally blocked until safety prerequisites and "
            "human approval are satisfied."
        ),
        "configuration": (
            "Bounded context suggests configuration uncertainty, but no setting "
            "was inspected or changed."
        ),
        "environment": (
            "Bounded context suggests an environment issue that requires manual "
            "verification."
        ),
        "external_tool": (
            "Bounded context suggests a local tool problem; availability and "
            "failure details remain unverified."
        ),
        "resource_exhaustion": (
            "Bounded context suggests resource exhaustion, but Error Doctor did "
            "not reproduce or measure the failure."
        ),
        "timeout": (
            "Bounded context suggests a timeout; the slow or blocked operation "
            "has not been reproduced."
        ),
    }
    return summaries.get(
        category,
        "Saved evidence identifies a symptom, but a specific root cause is not proven.",
    )


def _investigation_steps(category: BobaErrorCategoryV1) -> list[str]:
    if category in {"missing_artifact", "corrupt_artifact", "unreadable_artifact"}:
        return [
            "Inspect the saved artifact metadata without modifying it.",
            "Compare its schema and timestamp with the expected contract.",
            "Inspect the nearest required upstream artifact.",
        ]
    if category in {"missing_dependency", "broken_dependency"}:
        return [
            "Inspect the nearest missing or unreadable upstream artifact.",
            "Compare required dependency state across the affected modules.",
        ]
    if category == "stale_artifact":
        return [
            "Compare upstream and downstream artifact timestamps.",
            "Review whether approved regeneration is needed outside Error Doctor.",
        ]
    if category in {"validation_missing", "validation_stale"}:
        return [
            "Inspect validation report presence and timestamp.",
            "A human may run the relevant validator later.",
        ]
    if category == "validation_failure":
        return [
            "Inspect the bounded failed validation report.",
            "Escalate unresolved causes to Root Cause Analyzer.",
        ]
    if category in {"rights_safety", "permission", "ingestion"}:
        return [
            "Perform human rights and permission review.",
            "Do not continue processing until the safety gate permits review.",
        ]
    if category == "configuration":
        return [
            "Inspect required non-secret configuration values manually.",
        ]
    if category in {
        "environment",
        "external_tool",
        "timeout",
        "resource_exhaustion",
        "media_probe",
        "rendering",
    }:
        return [
            "Inspect bounded local environment and tool evidence manually.",
            "Do not retry, install, restart, or render automatically.",
        ]
    return ["Collect bounded missing information and escalate for human review."]


def _target_for(
    category: BobaErrorCategoryV1,
) -> BobaErrorDoctorEscalationTargetV1:
    if category in {"validation_missing", "validation_stale"}:
        return "validator_runner"
    if category in {"rights_safety", "permission", "ingestion"}:
        return "rights_permission_gate"
    if category in {
        "external_tool",
        "timeout",
        "resource_exhaustion",
        "environment",
        "media_probe",
    }:
        return "tool_recovery_brain"
    if category in {"rendering", "audio_video_sync"}:
        return "output_quality_reviewer"
    return "root_cause_analyzer"


def _build_cases(
    seeds: Sequence[_DiagnosticSeed],
    *,
    registry: Sequence[BobaArtifactRegistryEntryV1],
    conflicting: bool,
) -> list[BobaDiagnosticCaseV1]:
    grouped: dict[str, list[_DiagnosticSeed]] = defaultdict(list)
    for seed in seeds:
        if seed.include_case:
            grouped[seed.case_key].append(seed)
    spec_by_artifact = {item.artifact_id: item for item in registry}
    cases: list[BobaDiagnosticCaseV1] = []
    for case_key, values in sorted(grouped.items()):
        ordered = sorted(
            values,
            key=lambda seed: (
                not seed.finding.is_possible_cause,
                seed.finding.is_downstream_effect,
                -_SEVERITY_RANK[seed.finding.severity],
                seed.finding.classified_finding_id,
            ),
        )
        primary = ordered[0]
        category = primary.finding.classified_category
        severity = _severity_max([item.finding.severity for item in ordered])
        evidence_by_id = {
            evidence.evidence_id: evidence
            for item in ordered
            for evidence in item.finding.evidence
        }
        evidence = list(evidence_by_id.values())[:64]
        related_ids = _unique(
            [item.finding.classified_finding_id for item in ordered],
            limit=128,
            maximum=128,
        )
        cascade_root = next(
            (
                item.finding.cascade_group_id
                for item in ordered
                if item.finding.is_possible_cause
                and item.finding.cascade_group_id
            ),
            "",
        )
        primary_artifact = primary.finding.artifact_id
        primary_module = primary.finding.module_name
        if case_key.startswith("missing_dependency:"):
            root_artifact = case_key.split(":", 1)[1]
            spec = spec_by_artifact.get(root_artifact)
            if spec is not None:
                primary_artifact = root_artifact
                primary_module = spec.module_name
        affected_modules = _unique(
            [
                primary_module,
                *[item.finding.module_name for item in ordered],
                *(
                    _downstream_modules(primary_artifact, registry)
                    if cascade_root and primary_artifact
                    else []
                ),
            ],
            limit=64,
            maximum=120,
        )
        affected_artifacts = _unique(
            [
                primary_artifact,
                *[item.finding.artifact_id for item in ordered],
            ],
            limit=64,
            maximum=120,
        )
        status = primary.diagnosis_status
        if conflicting:
            status = "conflicting_evidence"
        elif any(
            item.diagnosis_status == "observed_fact" for item in ordered
        ):
            status = "observed_fact"
        elif any(item.diagnosis_status == "probable" for item in ordered):
            status = "probable"
        confidence = sum(item.finding.confidence for item in ordered) / len(ordered)
        if conflicting:
            confidence = max(0.1, confidence - 0.2)
        hypotheses = _hypotheses_for(
            category,
            evidence,
            conflicting=conflicting,
        )
        case_id = _stable_id("diagnostic_case", case_key)
        processing_values = [item.processing_impact for item in ordered]
        if "unsafe_to_continue" in processing_values:
            processing: BobaProcessingImpactV1 = "unsafe_to_continue"
        elif "full_block" in processing_values:
            processing = "full_block"
        elif "partial_block" in processing_values:
            processing = "partial_block"
        elif "degraded" in processing_values:
            processing = "degraded"
        elif "unknown" in processing_values:
            processing = "unknown"
        else:
            processing = "none"
        safety_values = [item.safety_impact for item in ordered]
        if "rights_gate_blocked" in safety_values:
            safety: BobaSafetyImpactV1 = "rights_gate_blocked"
        elif "safety_gate_blocked" in safety_values:
            safety = "safety_gate_blocked"
        elif "destructive_risk" in safety_values:
            safety = "destructive_risk"
        elif "human_review_needed" in safety_values:
            safety = "human_review_needed"
        elif "unknown" in safety_values:
            safety = "unknown"
        else:
            safety = "none_known"
        confirmed = _unique(
            [item.evidence_summary for item in evidence],
            limit=32,
        )
        missing_information = _unique(
            [
                *(
                    item
                    for seed in ordered
                    for item in seed.missing_information
                ),
                *(
                    ["Conflicting evidence must be reconciled."]
                    if conflicting
                    else []
                ),
            ],
            limit=32,
        )
        cases.append(
            BobaDiagnosticCaseV1(
                diagnostic_case_id=case_id,
                title=(
                    f"{category.replace('_', ' ').title()}: "
                    f"{primary_artifact or primary_module or 'project state'}"
                ),
                primary_module=primary_module,
                primary_artifact=primary_artifact,
                workflow_stage=primary.workflow_stage,
                error_category=category,
                severity=severity,
                urgency=_urgency_for(severity),
                diagnosis_status=status,
                symptom_summary=_unique(
                    [item.finding.explanation for item in ordered],
                    limit=4,
                )[0],
                probable_cause_summary=_probable_summary(category),
                confirmed_facts=confirmed,
                hypotheses=hypotheses,
                affected_modules=affected_modules,
                affected_artifacts=affected_artifacts,
                related_finding_ids=related_ids,
                evidence=evidence,
                missing_information=missing_information,
                processing_impact=processing,
                safety_impact=safety,
                recommended_investigation=_investigation_steps(category),
                escalation_target=_target_for(category),
                confidence=round(confidence, 4),
                warnings=_unique(
                    [
                        warning
                        for item in ordered
                        for warning in item.finding.warnings
                    ],
                    limit=32,
                ),
                limitations=[
                    "A probable cause is not a proven root cause.",
                    "Error Doctor used saved bounded evidence only.",
                ],
            )
        )
    return sorted(
        cases,
        key=lambda case: (
            -_SEVERITY_RANK[case.severity],
            case.title,
        ),
    )[:256]


def group_diagnostic_cases(
    observer: BobaObserverSetV1,
    *,
    registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
    manual_context: Mapping[str, Any] | None = None,
    error_summaries: Sequence[str | Mapping[str, Any]] | None = None,
) -> list[BobaDiagnosticCaseV1]:
    """Group duplicate and causally related Observer symptoms conservatively."""

    effective_registry = tuple(registry or build_boba_artifact_registry())
    seeds = _normalized_seeds(
        observer,
        registry=effective_registry,
        manual_context=manual_context,
        error_summaries=error_summaries,
    )
    return _build_cases(
        seeds,
        registry=effective_registry,
        conflicting=bool(
            manual_context and manual_context.get("conflicting_evidence")
        ),
    )


def analyze_cascading_impacts(
    cases: Sequence[BobaDiagnosticCaseV1],
    findings: Sequence[BobaClassifiedFindingV1],
) -> list[BobaCascadingImpactV1]:
    """Create conservative cascades only where multiple modules share a root."""

    finding_by_id = {
        item.classified_finding_id: item for item in findings
    }
    groups: dict[str, list[BobaClassifiedFindingV1]] = defaultdict(list)
    for finding in findings:
        if finding.cascade_group_id:
            groups[finding.cascade_group_id].append(finding)
    results: list[BobaCascadingImpactV1] = []
    for cascade_group, grouped_findings in groups.items():
        modules = _unique(
            [item.module_name for item in grouped_findings],
            limit=64,
            maximum=120,
        )
        artifacts = _unique(
            [item.artifact_id for item in grouped_findings],
            limit=64,
            maximum=120,
        )
        downstream = [
            item for item in grouped_findings if item.is_downstream_effect
        ]
        if len(modules) < 2 and not downstream:
            continue
        originating_case = next(
            (
                case
                for case in cases
                if any(
                    finding_by_id.get(finding_id)
                    and finding_by_id[finding_id].cascade_group_id
                    == cascade_group
                    and finding_by_id[finding_id].is_possible_cause
                    for finding_id in case.related_finding_ids
                )
            ),
            next(
                (
                    case
                    for case in cases
                    if any(
                        finding_by_id.get(finding_id)
                        and finding_by_id[finding_id].cascade_group_id
                        == cascade_group
                        for finding_id in case.related_finding_ids
                    )
                ),
                None,
            ),
        )
        if originating_case is None:
            continue
        blocked_stages = _unique(
            [
                _workflow_for(item.module_name)
                for item in grouped_findings
                if item.severity in {"high", "critical", "blocker"}
            ],
            limit=32,
            maximum=120,
        )
        severity = _severity_max(
            [item.severity for item in grouped_findings]
        )
        results.append(
            BobaCascadingImpactV1(
                cascade_id=_stable_id(
                    "diagnostic_cascade",
                    cascade_group,
                    originating_case.diagnostic_case_id,
                ),
                originating_case_id=originating_case.diagnostic_case_id,
                originating_module=originating_case.primary_module,
                impacted_modules=modules,
                impacted_artifacts=artifacts,
                impact_chain=_unique(
                    [
                        f"{originating_case.primary_module or 'upstream'} -> "
                        f"{module}"
                        for module in modules
                        if module != originating_case.primary_module
                    ],
                    limit=64,
                ),
                blocked_workflow_stages=blocked_stages,
                severity=severity,
                explanation=(
                    "Multiple saved observations share an upstream or safety "
                    "group. They may be cascading effects; exact causality is "
                    "not proven."
                ),
                confidence=0.76,
                warnings=[
                    "Cascade inference uses known dependency direction only.",
                ],
            )
        )
    return results[:256]


def generate_investigation_recommendations(
    cases: Sequence[BobaDiagnosticCaseV1],
) -> list[BobaInvestigationRecommendationV1]:
    """Build advisory investigation steps without executing any action."""

    recommendations: list[BobaInvestigationRecommendationV1] = []

    def add(
        case: BobaDiagnosticCaseV1,
        action: str,
        category: BobaInvestigationActionCategoryV1,
        *,
        command: bool = False,
        read_only: bool = True,
        owner: str,
        gain: str,
        stop: str,
        warnings: Sequence[str] = (),
    ) -> None:
        value = BobaInvestigationRecommendationV1(
            recommendation_id=_stable_id(
                "doctor_recommendation",
                case.diagnostic_case_id,
                category,
                action,
            ),
            diagnostic_case_id=case.diagnostic_case_id,
            action=action,
            action_category=category,
            safe=True,
            read_only=read_only,
            requires_command_execution=command,
            requires_code_change=False,
            requires_human_review=True,
            prerequisite=[
                "Preserve Observer and source artifacts.",
                "Human authorizes any action outside read-only inspection.",
            ],
            expected_information_gain=gain,
            stop_condition=stop,
            suggested_owner_module=owner,
            priority=_priority_for(case.severity),
            warnings=_unique(
                [
                    *warnings,
                    "Error Doctor did not execute this recommendation.",
                ],
                limit=24,
            ),
        )
        if all(
            existing.recommendation_id != value.recommendation_id
            for existing in recommendations
        ):
            recommendations.append(value)

    for case in cases:
        if case.error_category in {
            "missing_artifact",
            "corrupt_artifact",
            "unreadable_artifact",
            "schema_mismatch",
        }:
            add(
                case,
                "Inspect the saved artifact and compare its bounded schema metadata.",
                "inspect_artifact",
                owner="human_operator",
                gain="Clarifies whether the artifact is absent, malformed, or incompatible.",
                stop="Stop if inspection would expose secrets or require modification.",
            )
        if case.error_category in {
            "missing_dependency",
            "broken_dependency",
            "stale_artifact",
        }:
            add(
                case,
                "Inspect required upstream dependencies and compare timestamps.",
                (
                    "compare_timestamps"
                    if case.error_category == "stale_artifact"
                    else "inspect_dependency"
                ),
                owner="root_cause_analyzer",
                gain="Identifies the nearest observable break in the dependency chain.",
                stop="Stop before regeneration, retry, or repair.",
            )
        if case.error_category in {
            "validation_missing",
            "validation_stale",
        }:
            add(
                case,
                "A human may run the relevant validator later.",
                "run_future_validator",
                command=True,
                read_only=False,
                owner="validator_runner",
                gain="Produces current validation evidence.",
                stop="Do not run automatically or if validator safety is unclear.",
                warnings=["A future validator run may write a new report."],
            )
        if case.error_category == "validation_failure":
            add(
                case,
                "Inspect the bounded failed validation report.",
                "inspect_validation_report",
                owner="root_cause_analyzer",
                gain="May identify a narrower failed check without rerunning it.",
                stop="Stop before changing code or hiding the failure.",
            )
        if case.error_category in {
            "rights_safety",
            "permission",
            "ingestion",
        }:
            add(
                case,
                "Perform human rights and permission review before processing.",
                "human_rights_review",
                owner="rights_permission_gate",
                gain="Determines whether human review may proceed safely.",
                stop="Do not continue while rights remain unknown or blocked.",
            )
            add(
                case,
                "Do not continue processing while the safety gate is blocked.",
                "do_not_continue",
                owner="safety_gate",
                gain="Prevents unsafe ingestion or processing.",
                stop="Resume only after explicit human approval and acceptable rights.",
            )
        if case.error_category == "configuration":
            add(
                case,
                "Inspect required non-secret configuration values.",
                "inspect_configuration",
                owner="human_operator",
                gain="Confirms whether expected configuration is present.",
                stop="Stop before editing settings or exposing secrets.",
            )
        if case.error_category in {
            "environment",
            "external_tool",
            "timeout",
            "resource_exhaustion",
            "media_probe",
            "rendering",
            "audio_video_sync",
        }:
            add(
                case,
                "Inspect bounded local environment and tool evidence manually.",
                "inspect_environment",
                owner="tool_recovery_brain",
                gain="Distinguishes availability, timeout, and resource symptoms.",
                stop="Do not install, restart, retry, probe, or render automatically.",
            )
        add(
            case,
            "Escalate unresolved diagnosis with bounded evidence.",
            "escalate",
            owner=case.escalation_target,
            gain="Provides a structured case for deeper approved analysis.",
            stop="No downstream module may apply changes automatically.",
        )
    return recommendations[:512]


def generate_error_doctor_handoffs(
    cases: Sequence[BobaDiagnosticCaseV1],
    cascades: Sequence[BobaCascadingImpactV1],
) -> list[BobaErrorDoctorEscalationHandoffV1]:
    """Create non-applying, human-approved future-module handoffs."""

    cascades_by_case = {
        item.originating_case_id: item for item in cascades
    }
    handoffs: list[BobaErrorDoctorEscalationHandoffV1] = []

    def add(
        case: BobaDiagnosticCaseV1,
        target: BobaErrorDoctorEscalationTargetV1,
        reason: str,
    ) -> None:
        value = BobaErrorDoctorEscalationHandoffV1(
            handoff_id=_stable_id(
                "doctor_handoff",
                case.diagnostic_case_id,
                target,
            ),
            diagnostic_case_id=case.diagnostic_case_id,
            target_module=target,
            reason=reason,
            evidence_ids=[item.evidence_id for item in case.evidence][:64],
            unresolved_questions=case.missing_information[:32],
            required_inputs=[
                "Saved Error Doctor case",
                "Saved Observer evidence",
                "Explicit human approval",
            ],
            blocked_actions=[
                "Automatic repair",
                "Automatic command or validator execution",
                "Automatic deletion, retry, ingestion, download, or render",
            ],
            apply_automatically=False,
            human_approval_required=True,
            warnings=[
                "Handoff is advisory and was not invoked by Error Doctor.",
            ],
        )
        if all(existing.handoff_id != value.handoff_id for existing in handoffs):
            handoffs.append(value)

    for case in cases:
        if (
            case.diagnosis_status
            in {
                "possible",
                "insufficient_evidence",
                "conflicting_evidence",
                "unknown",
            }
            or case.diagnostic_case_id in cascades_by_case
        ):
            add(
                case,
                "root_cause_analyzer",
                "Deeper causal analysis is needed before any repair planning.",
            )
        if (
            case.error_category
            in {
                "missing_artifact",
                "corrupt_artifact",
                "unreadable_artifact",
                "schema_mismatch",
                "stale_artifact",
                "broken_dependency",
            }
            and case.confidence >= 0.65
        ):
            add(
                case,
                "repair_planner",
                "The bounded problem shape may support future approved planning.",
            )
        if case.error_category in {
            "external_tool",
            "timeout",
            "resource_exhaustion",
            "environment",
            "media_probe",
        }:
            add(
                case,
                "tool_recovery_brain",
                "A local tool or environment symptom needs approved recovery analysis.",
            )
        if case.error_category in {"rendering", "audio_video_sync"}:
            add(
                case,
                "output_quality_reviewer",
                "Output behavior needs bounded quality review without rerendering.",
            )
        if case.error_category in {"validation_missing", "validation_stale"}:
            add(
                case,
                "validator_runner",
                "Current validation evidence is absent or stale.",
            )
        if case.error_category in {"rights_safety", "permission", "ingestion"}:
            add(
                case,
                "rights_permission_gate",
                "Rights or permission state requires dedicated human review.",
            )
            add(
                case,
                "safety_gate",
                "Unsafe processing must remain blocked.",
            )
            add(
                case,
                "human_operator",
                "Legal, rights, and safety decisions require a human.",
            )
        elif case.safety_impact in {
            "safety_gate_blocked",
            "destructive_risk",
        }:
            add(
                case,
                "safety_gate",
                "Safety policy must remain enforced before any action.",
            )
        if case.diagnosis_status == "conflicting_evidence":
            add(
                case,
                "human_operator",
                "Conflicting evidence requires human reconciliation.",
            )
    return handoffs[:512]


def _summary(
    findings: Sequence[BobaClassifiedFindingV1],
    cases: Sequence[BobaDiagnosticCaseV1],
    cascades: Sequence[BobaCascadingImpactV1],
    recommendations: Sequence[BobaInvestigationRecommendationV1],
) -> BobaErrorDoctorSummaryV1:
    counts = {
        severity: sum(case.severity == severity for case in cases)
        for severity in _SEVERITY_RANK
    }
    highest = cases[0] if cases else None
    blocked_stages = {
        stage
        for cascade in cascades
        for stage in cascade.blocked_workflow_stages
    }
    return BobaErrorDoctorSummaryV1(
        total_observer_findings=len(findings),
        total_diagnostic_cases=len(cases),
        informational_count=counts["informational"],
        low_count=counts["low"],
        medium_count=counts["medium"],
        high_count=counts["high"],
        critical_count=counts["critical"],
        blocker_count=counts["blocker"],
        unknown_count=counts["unknown"],
        primary_problem_count=sum(
            any(
                finding.is_possible_cause
                and finding.classified_finding_id
                in case.related_finding_ids
                for finding in findings
            )
            for case in cases
        ),
        cascading_problem_count=len(cascades),
        blocked_workflow_count=len(blocked_stages),
        highest_priority_case=(
            f"{highest.diagnostic_case_id}: {highest.title}" if highest else ""
        ),
        safest_next_investigation=(
            recommendations[0].action
            if recommendations
            else "Generate or inspect a saved Observer report manually."
        ),
        unresolved_information=_unique(
            [
                item
                for case in cases
                for item in case.missing_information
            ],
            limit=64,
        ),
        human_review_notes=[
            "Error Doctor diagnoses saved observations but applies no fix.",
            "A probable cause is not a proven root cause.",
            "Human approval is required before repair or destructive action.",
        ],
    )


def _insufficient_report(
    project_id: str,
    *,
    source_id: str,
    observer_source: str,
    observer_used: bool,
    warnings: Sequence[str],
    manual_context_used: bool,
) -> BobaErrorDoctorSetV1:
    case = BobaDiagnosticCaseV1(
        diagnostic_case_id=_stable_id(
            "diagnostic_case",
            project_id,
            "observer_unavailable",
        ),
        title="Observer evidence is unavailable",
        primary_module="observer",
        primary_artifact="observer",
        workflow_stage="self_healing",
        error_category="missing_artifact",
        severity="medium",
        urgency="normal",
        diagnosis_status="insufficient_evidence",
        symptom_summary=(
            "A usable saved BOBA Observer report was not available."
        ),
        probable_cause_summary=(
            "Error Doctor cannot determine why Observer evidence is absent and "
            "does not fabricate project findings."
        ),
        confirmed_facts=[
            "No usable Observer findings were supplied to Error Doctor.",
        ],
        hypotheses=[],
        affected_modules=["observer", "error_doctor"],
        affected_artifacts=["observer"],
        related_finding_ids=[],
        evidence=[],
        missing_information=[
            "A saved BOBA Observer V1 report.",
            "Current local artifact and validation observations.",
        ],
        processing_impact="degraded",
        safety_impact="human_review_needed",
        recommended_investigation=[
            "Generate BOBA Observer V1 manually through its approved API or UI.",
            "Do not infer project faults until Observer evidence exists.",
        ],
        escalation_target="human_operator",
        confidence=0.99,
        warnings=["No project findings were fabricated."],
        limitations=["No diagnosis is possible without Observer evidence."],
    )
    recommendation = BobaInvestigationRecommendationV1(
        recommendation_id=_stable_id(
            "doctor_recommendation",
            case.diagnostic_case_id,
            "collect_observer",
        ),
        diagnostic_case_id=case.diagnostic_case_id,
        action="Generate BOBA Observer V1 manually, then rerun Error Doctor.",
        action_category="collect_missing_information",
        safe=True,
        read_only=False,
        requires_command_execution=False,
        requires_code_change=False,
        requires_human_review=True,
        prerequisite=["Human chooses the approved Observer workflow."],
        expected_information_gain="Provides the required local observation evidence.",
        stop_condition="Stop if Observer generation is unavailable or unsafe.",
        suggested_owner_module="observer",
        priority="medium",
        warnings=["Error Doctor did not generate Observer automatically."],
    )
    handoff = BobaErrorDoctorEscalationHandoffV1(
        handoff_id=_stable_id(
            "doctor_handoff",
            case.diagnostic_case_id,
            "human_operator",
        ),
        diagnostic_case_id=case.diagnostic_case_id,
        target_module="human_operator",
        reason="A human must generate or locate the missing Observer report.",
        evidence_ids=[],
        unresolved_questions=case.missing_information,
        required_inputs=["Saved BOBA Observer V1 report"],
        blocked_actions=[
            "Root-cause claims",
            "Repair planning",
            "Automatic commands, validation, code changes, or destructive actions",
        ],
        apply_automatically=False,
        human_approval_required=True,
        warnings=["No future module was invoked."],
    )
    return BobaErrorDoctorSetV1(
        project_id=project_id,
        source_id=source_id,
        observer_source=observer_source,
        diagnostic_cases=[case],
        classified_findings=[],
        cascading_impacts=[],
        investigation_recommendations=[recommendation],
        escalation_handoffs=[handoff],
        doctor_summary=_summary([], [case], [], [recommendation]),
        signal_usage=BobaErrorDoctorSignalUsageV1(
            observer_used=observer_used,
            observer_artifact_read=observer_used,
            manual_context_used=manual_context_used,
            fallback_used=True,
            unavailable_signals=["observer_findings"],
            warnings=[
                "Error Doctor did not regenerate Observer.",
            ],
        ),
        warnings=_unique(warnings, limit=64),
        limitations=[
            "No diagnostic classification was fabricated without Observer findings.",
            "Error Doctor did not execute commands, validators, repairs, or external calls.",
        ],
    )


class BobaErrorDoctorV1:
    """Interpret Observer evidence without fixing, executing, or mutating."""

    def __init__(
        self,
        *,
        registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
    ) -> None:
        self.registry = tuple(registry or build_boba_artifact_registry())

    def analyze(
        self,
        project_id: str,
        observer: BobaObserverSetV1 | Mapping[str, Any] | None,
        *,
        source_id: str | None = None,
        manual_context: Mapping[str, Any] | None = None,
        error_summaries: Sequence[str | Mapping[str, Any]] | None = None,
        dry_run: bool = False,
    ) -> BobaErrorDoctorSetV1:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError(
                "Invalid BOBA Error Doctor project id.",
                details={"project_id": project_id},
            )
        source = _safe_text(source_id or project_id, maximum=512) or project_id
        observer_warning = ""
        parsed_observer: BobaObserverSetV1 | None
        if isinstance(observer, BobaObserverSetV1):
            parsed_observer = observer.model_copy(deep=True)
        elif isinstance(observer, Mapping):
            try:
                parsed_observer = BobaObserverSetV1.model_validate(observer)
            except PydanticValidationError:
                parsed_observer = None
                observer_warning = (
                    "Saved Observer report was malformed and could not be used."
                )
        else:
            parsed_observer = None
        if parsed_observer is None:
            return _insufficient_report(
                project_id,
                source_id=source,
                observer_source=(
                    "malformed_observer_v1"
                    if observer_warning
                    else "missing_observer_v1"
                ),
                observer_used=False,
                warnings=[
                    observer_warning
                    or "Saved BOBA Observer V1 report is unavailable.",
                    "Error Doctor did not run Observer automatically.",
                ],
                manual_context_used=bool(manual_context or error_summaries),
            )
        has_observations = any(
            (
                parsed_observer.artifact_observations,
                parsed_observer.module_health_observations,
                parsed_observer.dependency_observations,
                parsed_observer.validation_observations,
                parsed_observer.safety_observations,
            )
        )
        if not has_observations:
            return _insufficient_report(
                project_id,
                source_id=source,
                observer_source="saved_observer_v1_empty",
                observer_used=True,
                warnings=[
                    "Saved Observer report contains no diagnostic observations.",
                ],
                manual_context_used=bool(manual_context or error_summaries),
            )
        seeds = _normalized_seeds(
            parsed_observer,
            registry=self.registry,
            manual_context=manual_context,
            error_summaries=error_summaries,
        )
        conflicting = bool(
            manual_context and manual_context.get("conflicting_evidence")
        )
        findings = [seed.finding for seed in seeds]
        cases = _build_cases(
            seeds,
            registry=self.registry,
            conflicting=conflicting,
        )
        cascades = analyze_cascading_impacts(cases, findings)
        recommendations = generate_investigation_recommendations(cases)
        handoffs = generate_error_doctor_handoffs(cases, cascades)
        warnings = [
            "BOBA Error Doctor V1 diagnoses saved Observer evidence only.",
            "A probable cause is not a proven root cause.",
            "Human review is required before repair or destructive action.",
            "Error Doctor did not fix files, edit code, run commands, run "
            "validators, install tools, restart services, delete files, fetch "
            "URLs, call external APIs, download media, ingest media, or render.",
        ]
        if dry_run:
            warnings.append("Dry run: the Error Doctor artifact was not persisted.")
        return BobaErrorDoctorSetV1(
            project_id=project_id,
            source_id=source,
            observer_source="saved_observer_v1",
            diagnostic_cases=cases,
            classified_findings=findings,
            cascading_impacts=cascades,
            investigation_recommendations=recommendations,
            escalation_handoffs=handoffs,
            doctor_summary=_summary(
                findings,
                cases,
                cascades,
                recommendations,
            ),
            signal_usage=BobaErrorDoctorSignalUsageV1(
                observer_used=True,
                observer_artifact_read=True,
                validation_observations_used=bool(
                    parsed_observer.validation_observations
                ),
                dependency_observations_used=bool(
                    parsed_observer.dependency_observations
                ),
                safety_observations_used=bool(
                    parsed_observer.safety_observations
                ),
                manual_context_used=bool(manual_context or error_summaries),
                raw_logs_read=False,
                external_api_used=False,
                url_fetching_used=False,
                scraping_used=False,
                downloading_used=False,
                command_execution_used=False,
                validator_execution_used=False,
                code_modification_used=False,
                artifact_modification_used=False,
                destructive_action_used=False,
                fallback_used=bool(
                    parsed_observer.signal_usage.fallback_used
                    or conflicting
                    or error_summaries
                ),
                unavailable_signals=_unique(
                    parsed_observer.signal_usage.unavailable_signals,
                    limit=64,
                    maximum=160,
                ),
                warnings=[
                    "Bounded manual summaries are not raw logs."
                    if error_summaries
                    else "",
                    "No action was executed by Error Doctor.",
                ],
            ),
            warnings=warnings,
            limitations=[
                "V1 classifies observations but does not prove every root cause.",
                "V1 does not inspect source code, full logs, raw artifacts, media, or secrets.",
                "V1 does not invoke Root Cause Analyzer, Repair Planner, Tool "
                "Recovery Brain, Validator Runner, Safety Gate, or Rights Gate.",
                "V1 does not claim production readiness.",
            ],
        )


def generate_boba_error_doctor(
    project_id: str,
    observer: BobaObserverSetV1 | Mapping[str, Any] | None,
    **kwargs: Any,
) -> BobaErrorDoctorSetV1:
    """Convenience wrapper for deterministic local diagnosis."""

    return BobaErrorDoctorV1().analyze(project_id, observer, **kwargs)

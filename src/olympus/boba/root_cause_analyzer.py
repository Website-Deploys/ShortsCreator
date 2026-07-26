"""Evidence-bounded causal analysis of saved BOBA Error Doctor reports."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, TypeAlias, cast

from pydantic import Field
from pydantic import ValidationError as PydanticValidationError

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.error_doctor import (
    BobaCascadingImpactV1,
    BobaClassifiedFindingV1,
    BobaDiagnosticCaseV1,
    BobaDiagnosticHypothesisV1,
    BobaErrorDoctorSetV1,
    BobaErrorDoctorSignalUsageV1,
    BobaErrorDoctorSummaryV1,
    BobaInvestigationRecommendationV1,
)
from olympus.boba.observer import (
    BobaArtifactRegistryEntryV1,
    build_boba_artifact_registry,
)
from olympus.platform.errors import ValidationError

BobaRootCauseAnalysisStatusV1 = Literal[
    "root_cause_supported",
    "probable_root_cause",
    "multiple_competing_causes",
    "insufficient_evidence",
    "conflicting_evidence",
    "intentional_safety_block",
    "no_defect_detected",
    "unknown",
]
BobaRootCauseProcessingImpactV1 = Literal[
    "none",
    "degraded",
    "partial_block",
    "full_block",
    "unsafe_to_continue",
    "unknown",
]
BobaRootCauseSafetyImpactV1 = Literal[
    "none_known",
    "human_review_needed",
    "safety_gate_blocked",
    "rights_gate_blocked",
    "destructive_risk",
    "unknown",
]
BobaFailureTimelineEventTypeV1 = Literal[
    "artifact_created",
    "artifact_updated",
    "artifact_missing",
    "artifact_corrupt",
    "artifact_unreadable",
    "dependency_missing",
    "dependency_stale",
    "module_blocked",
    "validation_passed",
    "validation_failed",
    "validation_missing",
    "tool_unavailable",
    "tool_failed",
    "timeout",
    "resource_exhaustion",
    "configuration_missing",
    "environment_missing",
    "safety_blocked",
    "rights_blocked",
    "workflow_stopped",
    "unknown",
]
BobaCausalRelevanceV1 = Literal[
    "possible_origin",
    "contributing_event",
    "downstream_effect",
    "unrelated",
    "unknown",
]
BobaCausalNodeTypeV1 = Literal[
    "observed_failure",
    "missing_input",
    "corrupt_artifact",
    "stale_artifact",
    "configuration_factor",
    "environment_factor",
    "tool_failure",
    "resource_factor",
    "validation_gap",
    "safety_block",
    "rights_block",
    "contributing_factor",
    "downstream_symptom",
    "root_cause_candidate",
    "unknown",
]
BobaCausalRelationshipV1 = Literal[
    "caused",
    "probably_caused",
    "may_have_caused",
    "contributed_to",
    "blocked",
    "depended_on",
    "preceded",
    "correlated_with",
    "contradicted_by",
    "unrelated",
    "unknown",
]
BobaRootCauseCategoryV1 = Literal[
    "missing_artifact",
    "corrupt_artifact",
    "stale_artifact",
    "schema_mismatch",
    "dependency_order",
    "configuration",
    "environment",
    "storage",
    "code_defect",
    "data_quality",
    "validation_failure",
    "validation_gap",
    "tool_unavailable",
    "tool_failure",
    "timeout",
    "resource_exhaustion",
    "checkpoint_failure",
    "rendering",
    "audio_video_sync",
    "media_probe",
    "rights_safety",
    "permission",
    "intentional_safety_block",
    "user_input",
    "external_service",
    "unknown",
]
BobaRootCauseEvidenceQualityV1 = Literal[
    "strong",
    "moderate",
    "weak",
    "conflicting",
    "insufficient",
    "unknown",
]
BobaRootCauseRepairabilityV1 = Literal[
    "likely_recoverable",
    "recoverable_with_approval",
    "requires_tool_fallback",
    "requires_code_change",
    "requires_configuration_change",
    "requires_human_decision",
    "not_a_defect",
    "blocked",
    "unknown",
]
BobaContributingFactorCategoryV1 = Literal[
    "resource_pressure",
    "stale_state",
    "incomplete_configuration",
    "optional_dependency_missing",
    "weak_input_data",
    "incompatible_format",
    "environment_difference",
    "retry_exhaustion",
    "checkpoint_gap",
    "validation_gap",
    "user_decision_required",
    "rights_constraint",
    "safety_constraint",
    "unknown",
]
BobaRootCauseEvidenceSourceTypeV1 = Literal[
    "error_doctor_fact",
    "error_doctor_hypothesis",
    "observer_finding",
    "artifact_observation",
    "dependency_observation",
    "validation_observation",
    "safety_observation",
    "bounded_manual_context",
    "unknown",
]
BobaRootCauseEvidenceReliabilityV1 = Literal[
    "high",
    "medium",
    "low",
    "conflicting",
    "unknown",
]
BobaEvidenceCollectionMethodV1 = Literal[
    "inspect_saved_artifact",
    "inspect_bounded_log",
    "inspect_configuration",
    "inspect_environment",
    "compare_timestamps",
    "compare_schema",
    "run_future_validator",
    "reproduce_manually",
    "check_tool_health",
    "collect_user_input",
    "human_rights_review",
    "unavailable",
    "unknown",
]
BobaRootCauseVerificationCheckTypeV1 = Literal[
    "inspect_artifact",
    "inspect_dependency",
    "inspect_timestamp",
    "inspect_schema",
    "inspect_configuration",
    "inspect_environment",
    "inspect_validation_report",
    "check_tool_availability",
    "check_resource_history",
    "reproduce_failure",
    "compare_successful_run",
    "verify_rights_state",
    "stop_processing",
    "unknown",
]
BobaRootCauseHandoffTargetV1 = Literal[
    "repair_planner",
    "tool_recovery_brain",
    "validator_runner",
    "artifact_inspector",
    "report_reader",
    "safety_gate",
    "rights_permission_gate",
    "workflow_controller",
    "code_surgeon",
    "human_operator",
    "unknown",
]
BobaRootCausePriorityV1 = Literal["low", "medium", "high", "urgent"]

JsonObject: TypeAlias = dict[str, Any]

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SPACE = re.compile(r"\s+")
_WINDOWS_ABSOLUTE = re.compile(r"\b[A-Za-z]:[\\/][^\s;,]+")
_UNC_PATH = re.compile(r"\\\\[^\\\s]+\\[^\\\s]+(?:\\[^\s;,]+)*")
_UNIX_PRIVATE_PATH = re.compile(
    r"(?<![A-Za-z0-9])/(?:home|Users|root|var|tmp|private|opt)/[^\s;,]+"
)
_TIMESTAMP_SUFFIX = re.compile(r"Z$")

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
    (
        "self_healing",
        (
            "observer",
            "error_doctor",
            "root_cause_analyzer",
            "repair_planner",
            "tool_recovery_brain",
        ),
    ),
)
_CATEGORY_COMPLEXITY: dict[BobaRootCauseCategoryV1, int] = {
    "missing_artifact": 0,
    "corrupt_artifact": 0,
    "stale_artifact": 0,
    "validation_failure": 0,
    "intentional_safety_block": 0,
    "permission": 0,
    "tool_unavailable": 1,
    "resource_exhaustion": 1,
    "timeout": 1,
    "checkpoint_failure": 1,
    "schema_mismatch": 1,
    "dependency_order": 1,
    "data_quality": 1,
    "validation_gap": 2,
    "configuration": 2,
    "environment": 2,
    "storage": 2,
    "tool_failure": 2,
    "rendering": 2,
    "audio_video_sync": 2,
    "media_probe": 2,
    "rights_safety": 2,
    "user_input": 2,
    "external_service": 3,
    "code_defect": 4,
    "unknown": 5,
}


class BobaRootCauseEvidenceV1(BobaContract):
    evidence_id: str = Field(min_length=1, max_length=160)
    source_type: BobaRootCauseEvidenceSourceTypeV1
    source_id: str = Field(min_length=1, max_length=180)
    module_name: str = Field(default="", max_length=120)
    artifact_id: str = Field(default="", max_length=120)
    evidence_summary: str = Field(min_length=1, max_length=700)
    observed_value: str = Field(default="", max_length=500)
    expected_value: str = Field(default="", max_length=500)
    observed_at: str = Field(default="", max_length=80)
    reliability: BobaRootCauseEvidenceReliabilityV1
    confidence: float = Field(ge=0.0, le=1.0)
    usage_warning: str = Field(default="", max_length=500)


class BobaFailureTimelineEventV1(BobaContract):
    event_id: str = Field(min_length=1, max_length=160)
    event_type: BobaFailureTimelineEventTypeV1
    module_name: str = Field(default="", max_length=120)
    artifact_id: str = Field(default="", max_length=120)
    observed_at: str = Field(default="", max_length=80)
    source_type: str = Field(default="unknown", max_length=80)
    source_id: str = Field(default="", max_length=180)
    event_summary: str = Field(min_length=1, max_length=700)
    status_before: str = Field(default="", max_length=120)
    status_after: str = Field(default="", max_length=120)
    confirmed: bool = False
    causal_relevance: BobaCausalRelevanceV1
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaFailureTimelineV1(BobaContract):
    timeline_id: str = Field(min_length=1, max_length=160)
    analysis_case_id: str = Field(min_length=1, max_length=160)
    events: list[BobaFailureTimelineEventV1] = Field(
        default_factory=list,
        max_length=96,
    )
    earliest_event_id: str = Field(default="", max_length=160)
    first_failure_event_id: str = Field(default="", max_length=160)
    first_confirmed_failure_event_id: str = Field(default="", max_length=160)
    latest_observed_event_id: str = Field(default="", max_length=160)
    ordering_confidence: float = Field(ge=0.0, le=1.0)
    conflicting_timestamps: bool = False
    missing_time_information: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCausalNodeV1(BobaContract):
    node_id: str = Field(min_length=1, max_length=160)
    node_type: BobaCausalNodeTypeV1
    module_name: str = Field(default="", max_length=120)
    artifact_id: str = Field(default="", max_length=120)
    label: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=700)
    confirmed: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaCausalEdgeV1(BobaContract):
    edge_id: str = Field(min_length=1, max_length=160)
    from_node_id: str = Field(min_length=1, max_length=160)
    to_node_id: str = Field(min_length=1, max_length=160)
    relationship: BobaCausalRelationshipV1
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)
    confirmed: bool = False
    verification_needed: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaCausalGraphV1(BobaContract):
    causal_graph_id: str = Field(min_length=1, max_length=160)
    analysis_case_id: str = Field(min_length=1, max_length=160)
    nodes: list[BobaCausalNodeV1] = Field(default_factory=list, max_length=96)
    edges: list[BobaCausalEdgeV1] = Field(default_factory=list, max_length=192)
    root_candidate_node_ids: list[str] = Field(default_factory=list, max_length=24)
    symptom_node_ids: list[str] = Field(default_factory=list, max_length=64)
    contributing_node_ids: list[str] = Field(default_factory=list, max_length=32)
    blocked_stage_node_ids: list[str] = Field(default_factory=list, max_length=32)
    graph_confidence: float = Field(ge=0.0, le=1.0)
    cycles_detected: bool = False
    unresolved_links: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRootCauseCandidateV1(BobaContract):
    root_cause_candidate_id: str = Field(min_length=1, max_length=160)
    analysis_case_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    category: BobaRootCauseCategoryV1
    candidate_summary: str = Field(min_length=1, max_length=700)
    earliest_failure_relationship: str = Field(min_length=1, max_length=500)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    conflicting_evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    explains_symptom_ids: list[str] = Field(default_factory=list, max_length=128)
    unexplained_symptom_ids: list[str] = Field(default_factory=list, max_length=128)
    likelihood_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_quality: BobaRootCauseEvidenceQualityV1
    verification_required: bool = True
    confirmation_checks: list[str] = Field(default_factory=list, max_length=24)
    rejection_checks: list[str] = Field(default_factory=list, max_length=24)
    repairability: BobaRootCauseRepairabilityV1
    safety_constraints: list[str] = Field(default_factory=list, max_length=24)
    recommended_owner_module: str = Field(default="", max_length=160)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaContributingFactorV1(BobaContract):
    contributing_factor_id: str = Field(min_length=1, max_length=160)
    analysis_case_id: str = Field(min_length=1, max_length=160)
    factor_category: BobaContributingFactorCategoryV1
    factor_summary: str = Field(min_length=1, max_length=700)
    related_root_cause_candidate_ids: list[str] = Field(
        default_factory=list,
        max_length=24,
    )
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    impact: str = Field(min_length=1, max_length=500)
    necessary_for_failure: bool = False
    sufficient_for_failure: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    verification_needed: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaDownstreamSymptomV1(BobaContract):
    downstream_symptom_id: str = Field(min_length=1, max_length=160)
    analysis_case_id: str = Field(min_length=1, max_length=160)
    source_finding_id: str = Field(default="", max_length=180)
    module_name: str = Field(default="", max_length=120)
    artifact_id: str = Field(default="", max_length=120)
    symptom_summary: str = Field(min_length=1, max_length=700)
    originating_candidate_ids: list[str] = Field(default_factory=list, max_length=24)
    cascade_depth: int = Field(default=0, ge=0, le=64)
    processing_impact: BobaRootCauseProcessingImpactV1
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaEvidenceGapV1(BobaContract):
    evidence_gap_id: str = Field(min_length=1, max_length=160)
    analysis_case_id: str = Field(min_length=1, max_length=160)
    missing_information: str = Field(min_length=1, max_length=700)
    why_needed: str = Field(min_length=1, max_length=700)
    affected_candidate_ids: list[str] = Field(default_factory=list, max_length=24)
    collection_method: BobaEvidenceCollectionMethodV1
    requires_command_execution: bool = False
    requires_validator: bool = False
    requires_external_access: bool = False
    requires_human_review: bool = True
    safe_to_collect: bool = True
    priority: BobaRootCausePriorityV1
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRootCauseVerificationCheckV1(BobaContract):
    check_id: str = Field(min_length=1, max_length=160)
    order: int = Field(ge=1, le=64)
    check_type: BobaRootCauseVerificationCheckTypeV1
    description: str = Field(min_length=1, max_length=700)
    prerequisite: str = Field(default="", max_length=500)
    expected_information_gain: str = Field(min_length=1, max_length=700)
    safe: bool = True
    read_only: bool = True
    requires_human_review: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRootCauseVerificationPlanV1(BobaContract):
    verification_plan_id: str = Field(min_length=1, max_length=160)
    analysis_case_id: str = Field(min_length=1, max_length=160)
    root_cause_candidate_id: str = Field(default="", max_length=160)
    objective: str = Field(min_length=1, max_length=700)
    checks: list[BobaRootCauseVerificationCheckV1] = Field(
        default_factory=list,
        max_length=32,
    )
    expected_confirmation_evidence: list[str] = Field(
        default_factory=list,
        max_length=24,
    )
    expected_rejection_evidence: list[str] = Field(
        default_factory=list,
        max_length=24,
    )
    safe: bool = True
    read_only: bool = True
    requires_command_execution: bool = False
    requires_validator_execution: bool = False
    requires_code_modification: Literal[False] = False
    requires_external_access: bool = False
    requires_human_approval: Literal[True] = True
    stop_conditions: list[str] = Field(default_factory=list, max_length=24)
    rollback_requirement: str = Field(default="", max_length=500)
    suggested_owner_module: str = Field(default="", max_length=160)
    priority: BobaRootCausePriorityV1
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaWorkflowImpactAnalysisV1(BobaContract):
    workflow_impact_id: str = Field(min_length=1, max_length=160)
    analysis_case_id: str = Field(min_length=1, max_length=160)
    originating_module: str = Field(default="", max_length=120)
    impacted_modules: list[str] = Field(default_factory=list, max_length=64)
    impacted_artifacts: list[str] = Field(default_factory=list, max_length=64)
    blocked_stages: list[str] = Field(default_factory=list, max_length=32)
    degraded_stages: list[str] = Field(default_factory=list, max_length=32)
    safe_stages: list[str] = Field(default_factory=list, max_length=32)
    unsafe_next_actions: list[str] = Field(default_factory=list, max_length=32)
    conditionally_safe_actions: list[str] = Field(default_factory=list, max_length=32)
    resume_requirements: list[str] = Field(default_factory=list, max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRootCauseEscalationHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=160)
    analysis_case_id: str = Field(min_length=1, max_length=160)
    root_cause_candidate_ids: list[str] = Field(default_factory=list, max_length=24)
    target_module: BobaRootCauseHandoffTargetV1
    reason: str = Field(min_length=1, max_length=700)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=32)
    required_inputs: list[str] = Field(default_factory=list, max_length=32)
    blocked_actions: list[str] = Field(default_factory=list, max_length=32)
    allowed_advisory_actions: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False
    human_approval_required: Literal[True] = True
    priority: BobaRootCausePriorityV1
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRootCauseAnalysisCaseV1(BobaContract):
    analysis_case_id: str = Field(min_length=1, max_length=160)
    source_diagnostic_case_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    primary_module: str = Field(default="", max_length=120)
    primary_artifact: str = Field(default="", max_length=120)
    workflow_stage: str = Field(default="unknown", max_length=120)
    analysis_status: BobaRootCauseAnalysisStatusV1
    earliest_known_failure: str = Field(min_length=1, max_length=700)
    most_likely_root_cause: str = Field(min_length=1, max_length=700)
    root_cause_confidence: float = Field(ge=0.0, le=1.0)
    confirmed_facts: list[str] = Field(default_factory=list, max_length=32)
    probable_inferences: list[str] = Field(default_factory=list, max_length=32)
    unresolved_hypotheses: list[str] = Field(default_factory=list, max_length=32)
    contributing_factor_ids: list[str] = Field(default_factory=list, max_length=32)
    downstream_symptom_ids: list[str] = Field(default_factory=list, max_length=128)
    affected_modules: list[str] = Field(default_factory=list, max_length=64)
    affected_artifacts: list[str] = Field(default_factory=list, max_length=64)
    failure_timeline_id: str = Field(default="", max_length=160)
    causal_graph_id: str = Field(default="", max_length=160)
    evidence_gap_ids: list[str] = Field(default_factory=list, max_length=64)
    verification_plan_ids: list[str] = Field(default_factory=list, max_length=32)
    processing_impact: BobaRootCauseProcessingImpactV1
    safety_impact: BobaRootCauseSafetyImpactV1
    recommended_handoff: BobaRootCauseHandoffTargetV1
    human_review_required: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaRootCauseAnalyzerSummaryV1(BobaContract):
    total_diagnostic_cases: int = Field(default=0, ge=0)
    total_analysis_cases: int = Field(default=0, ge=0)
    supported_root_cause_count: int = Field(default=0, ge=0)
    probable_root_cause_count: int = Field(default=0, ge=0)
    competing_cause_count: int = Field(default=0, ge=0)
    insufficient_evidence_count: int = Field(default=0, ge=0)
    intentional_safety_block_count: int = Field(default=0, ge=0)
    critical_case_count: int = Field(default=0, ge=0)
    blocked_workflow_count: int = Field(default=0, ge=0)
    strongest_root_cause_candidate: str = Field(default="", max_length=700)
    weakest_evidence_area: str = Field(default="", max_length=700)
    safest_next_verification: str = Field(default="", max_length=700)
    highest_priority_handoff: str = Field(default="", max_length=700)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=64)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)


class BobaRootCauseSignalUsageV1(BobaContract):
    error_doctor_used: bool = False
    error_doctor_artifact_read: bool = False
    observer_references_used: bool = False
    validation_evidence_used: bool = False
    dependency_evidence_used: bool = False
    safety_evidence_used: bool = False
    bounded_manual_context_used: bool = False
    raw_logs_read: bool = False
    external_api_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    command_execution_used: Literal[False] = False
    validator_execution_used: Literal[False] = False
    code_modification_used: Literal[False] = False
    artifact_modification_used: Literal[False] = False
    repair_execution_used: Literal[False] = False
    tool_fallback_execution_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRootCauseAnalyzerSetV1(BobaContract):
    schema_version: Literal[
        "boba_root_cause_analyzer_v1"
    ] = "boba_root_cause_analyzer_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    error_doctor_source: str = Field(min_length=1, max_length=160)
    analysis_cases: list[BobaRootCauseAnalysisCaseV1] = Field(
        default_factory=list,
        max_length=256,
    )
    failure_timelines: list[BobaFailureTimelineV1] = Field(
        default_factory=list,
        max_length=256,
    )
    causal_graphs: list[BobaCausalGraphV1] = Field(
        default_factory=list,
        max_length=256,
    )
    root_cause_candidates: list[BobaRootCauseCandidateV1] = Field(
        default_factory=list,
        max_length=1024,
    )
    contributing_factors: list[BobaContributingFactorV1] = Field(
        default_factory=list,
        max_length=512,
    )
    downstream_symptoms: list[BobaDownstreamSymptomV1] = Field(
        default_factory=list,
        max_length=2048,
    )
    evidence: list[BobaRootCauseEvidenceV1] = Field(
        default_factory=list,
        max_length=4096,
    )
    evidence_gaps: list[BobaEvidenceGapV1] = Field(
        default_factory=list,
        max_length=1024,
    )
    verification_plans: list[BobaRootCauseVerificationPlanV1] = Field(
        default_factory=list,
        max_length=1024,
    )
    workflow_impacts: list[BobaWorkflowImpactAnalysisV1] = Field(
        default_factory=list,
        max_length=256,
    )
    escalation_handoffs: list[BobaRootCauseEscalationHandoffV1] = Field(
        default_factory=list,
        max_length=1024,
    )
    analyzer_summary: BobaRootCauseAnalyzerSummaryV1
    signal_usage: BobaRootCauseSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


def _text(value: Any, *, maximum: int = 700) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _safe_text(value: Any, *, maximum: int = 700) -> str:
    text = _text(value, maximum=maximum)
    text = _WINDOWS_ABSOLUTE.sub("[private path]", text)
    text = _UNC_PATH.sub("[private path]", text)
    return _UNIX_PRIVATE_PATH.sub("[private path]", text)


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


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _parse_timestamp(value: str) -> datetime | None:
    text = _text(value, maximum=80)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(_TIMESTAMP_SUFFIX.sub("+00:00", text))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _priority(
    likelihood: float,
    processing_impact: BobaRootCauseProcessingImpactV1,
) -> BobaRootCausePriorityV1:
    if processing_impact in {"unsafe_to_continue", "full_block"} or likelihood >= 0.85:
        return "urgent"
    if processing_impact == "partial_block" or likelihood >= 0.65:
        return "high"
    if likelihood >= 0.35:
        return "medium"
    return "low"


def _workflow_for(module_name: str) -> str:
    for workflow, modules in _WORKFLOW_CHAINS:
        if module_name in modules:
            return workflow
    return "unknown"


def _all_modules() -> list[str]:
    return _unique(
        [module for _, modules in _WORKFLOW_CHAINS for module in modules],
        limit=64,
        maximum=120,
    )


def _downstream_modules(
    module_name: str,
    registry: Sequence[BobaArtifactRegistryEntryV1],
) -> list[str]:
    artifact_by_module = {item.module_name: item.artifact_id for item in registry}
    artifact_id = artifact_by_module.get(module_name, module_name)
    visited = {artifact_id}
    queue = [artifact_id]
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
            result.append(spec.module_name)
    if result:
        return result
    for _, modules in _WORKFLOW_CHAINS:
        if module_name not in modules:
            continue
        index = modules.index(module_name)
        return list(modules[index + 1 :])
    return []


def _source_type(value: str) -> BobaRootCauseEvidenceSourceTypeV1:
    mapping: dict[str, BobaRootCauseEvidenceSourceTypeV1] = {
        "observer_finding": "observer_finding",
        "artifact_observation": "artifact_observation",
        "module_health_observation": "artifact_observation",
        "dependency_observation": "dependency_observation",
        "validation_observation": "validation_observation",
        "safety_observation": "safety_observation",
        "workflow_observation": "observer_finding",
        "manual_context": "bounded_manual_context",
    }
    return mapping.get(value, "unknown")


def _coerce_enum(
    value: Any,
    allowed: set[str],
    *,
    fallback: str = "unknown",
) -> str:
    text = _text(value, maximum=120)
    return text if text in allowed else fallback


def _coerce_diagnostic_case(
    raw: Mapping[str, Any],
) -> tuple[BobaDiagnosticCaseV1 | None, list[str]]:
    warnings: list[str] = []
    payload = dict(raw)
    fields: tuple[tuple[str, set[str]], ...] = (
        (
            "error_category",
            {
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
            },
        ),
        (
            "severity",
            {
                "informational",
                "low",
                "medium",
                "high",
                "critical",
                "blocker",
                "unknown",
            },
        ),
        (
            "urgency",
            {"later", "normal", "soon", "immediate", "blocked", "unknown"},
        ),
        (
            "diagnosis_status",
            {
                "observed_fact",
                "probable",
                "possible",
                "insufficient_evidence",
                "conflicting_evidence",
                "unknown",
            },
        ),
        (
            "processing_impact",
            {
                "none",
                "degraded",
                "partial_block",
                "full_block",
                "unsafe_to_continue",
                "unknown",
            },
        ),
        (
            "safety_impact",
            {
                "none_known",
                "human_review_needed",
                "safety_gate_blocked",
                "rights_gate_blocked",
                "destructive_risk",
                "unknown",
            },
        ),
        (
            "escalation_target",
            {
                "root_cause_analyzer",
                "repair_planner",
                "tool_recovery_brain",
                "output_quality_reviewer",
                "safety_gate",
                "validator_runner",
                "rights_permission_gate",
                "human_operator",
                "unknown",
            },
        ),
    )
    for field, allowed in fields:
        original = payload.get(field)
        coerced = _coerce_enum(original, allowed)
        if original != coerced:
            payload[field] = coerced
            warnings.append(f"Unsupported {field} was normalized to unknown.")
    hypotheses = payload.get("hypotheses")
    if isinstance(hypotheses, list):
        normalized_hypotheses: list[Any] = []
        allowed_hypotheses = {
            "direct_cause",
            "contributing_factor",
            "downstream_effect",
            "environment_factor",
            "data_factor",
            "configuration_factor",
            "safety_factor",
            "unknown",
        }
        for item in hypotheses:
            if not isinstance(item, Mapping):
                continue
            normalized = dict(item)
            normalized["category"] = _coerce_enum(
                normalized.get("category"),
                allowed_hypotheses,
            )
            normalized_hypotheses.append(normalized)
        payload["hypotheses"] = normalized_hypotheses
    try:
        return BobaDiagnosticCaseV1.model_validate(payload), warnings
    except PydanticValidationError:
        return None, [*warnings, "Malformed diagnostic case was skipped."]


def _coerce_error_doctor(
    value: BobaErrorDoctorSetV1 | Mapping[str, Any] | None,
) -> tuple[BobaErrorDoctorSetV1 | None, list[str]]:
    if isinstance(value, BobaErrorDoctorSetV1):
        return value.model_copy(deep=True), []
    if not isinstance(value, Mapping):
        return None, []
    try:
        return BobaErrorDoctorSetV1.model_validate(value), []
    except PydanticValidationError:
        pass
    cases: list[BobaDiagnosticCaseV1] = []
    warnings = ["Saved Error Doctor report required bounded compatibility parsing."]
    raw_cases = value.get("diagnostic_cases")
    if isinstance(raw_cases, list):
        for raw_case in raw_cases[:256]:
            if not isinstance(raw_case, Mapping):
                warnings.append("Non-object diagnostic case was skipped.")
                continue
            case, case_warnings = _coerce_diagnostic_case(raw_case)
            warnings.extend(case_warnings)
            if case is not None:
                cases.append(case)
    if not cases:
        return None, _unique(warnings, limit=32)
    findings: list[BobaClassifiedFindingV1] = []
    for item in value.get("classified_findings", []):
        if not isinstance(item, Mapping):
            continue
        try:
            findings.append(BobaClassifiedFindingV1.model_validate(item))
        except PydanticValidationError:
            warnings.append("Malformed classified finding was skipped.")
    cascades: list[BobaCascadingImpactV1] = []
    for item in value.get("cascading_impacts", []):
        if not isinstance(item, Mapping):
            continue
        try:
            cascades.append(BobaCascadingImpactV1.model_validate(item))
        except PydanticValidationError:
            warnings.append("Malformed cascading impact was skipped.")
    recommendations: list[BobaInvestigationRecommendationV1] = []
    for item in value.get("investigation_recommendations", []):
        if not isinstance(item, Mapping):
            continue
        try:
            recommendations.append(BobaInvestigationRecommendationV1.model_validate(item))
        except PydanticValidationError:
            warnings.append("Malformed investigation recommendation was skipped.")
    report = BobaErrorDoctorSetV1(
        project_id=_safe_text(value.get("project_id") or "unknown", maximum=128),
        source_id=_safe_text(value.get("source_id") or "unknown", maximum=512),
        observer_source=_safe_text(
            value.get("observer_source") or "compatibility_error_doctor_v1",
            maximum=160,
        ),
        diagnostic_cases=cases,
        classified_findings=findings,
        cascading_impacts=cascades,
        investigation_recommendations=recommendations,
        escalation_handoffs=[],
        doctor_summary=BobaErrorDoctorSummaryV1(
            total_diagnostic_cases=len(cases),
        ),
        signal_usage=BobaErrorDoctorSignalUsageV1(fallback_used=True),
        warnings=_unique(
            [*warnings, *cast(Sequence[Any], value.get("warnings") or [])],
            limit=64,
        ),
        limitations=_unique(
            cast(Sequence[Any], value.get("limitations") or []),
            limit=64,
        ),
    )
    return report, _unique(warnings, limit=32)


def _manual_items(
    manual_context: Mapping[str, Any] | None,
    *,
    limit: int = 16,
) -> list[tuple[str, str]]:
    if not manual_context:
        return []
    items: list[tuple[str, str]] = []
    for key, value in list(manual_context.items())[:limit]:
        if key in {
            "raw_log",
            "raw_logs",
            "complete_artifact",
            "secret",
            "token",
            "conflicting_timestamps",
            "timestamp_conflict",
            "force_cycle_for_validation",
            "direct_causal_evidence",
            "conflicting_evidence",
            "contradictory_evidence",
        }:
            continue
        if isinstance(value, Mapping):
            summary = value.get("summary") or value.get("value") or value.get("status")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            summary = "; ".join(_safe_text(item, maximum=180) for item in value[:8])
        else:
            summary = value
        safe = _safe_text(summary, maximum=500)
        if safe:
            items.append((_safe_text(key, maximum=120), safe))
    return items


def normalize_error_doctor_case(
    case: BobaDiagnosticCaseV1,
    *,
    manual_context: Mapping[str, Any] | None = None,
) -> list[BobaRootCauseEvidenceV1]:
    """Convert one diagnostic case into bounded evidence records."""

    evidence: list[BobaRootCauseEvidenceV1] = []
    seen: set[str] = set()

    def add(item: BobaRootCauseEvidenceV1) -> None:
        if item.evidence_id not in seen and len(evidence) < 96:
            evidence.append(item)
            seen.add(item.evidence_id)

    for index, fact in enumerate(case.confirmed_facts[:32]):
        summary = _safe_text(fact)
        if not summary:
            continue
        add(
            BobaRootCauseEvidenceV1(
                evidence_id=_stable_id(
                    "root_evidence",
                    case.diagnostic_case_id,
                    "fact",
                    str(index),
                    summary,
                ),
                source_type="error_doctor_fact",
                source_id=case.diagnostic_case_id,
                module_name=case.primary_module,
                artifact_id=case.primary_artifact,
                evidence_summary=summary,
                reliability="high",
                confidence=_clamp(max(0.75, case.confidence)),
                usage_warning="A confirmed Error Doctor fact is evidence, not causal proof.",
            )
        )
    for item in case.evidence[:64]:
        add(
            BobaRootCauseEvidenceV1(
                evidence_id=item.evidence_id,
                source_type=_source_type(item.source_type),
                source_id=item.source_id,
                module_name=item.module_name or case.primary_module,
                artifact_id=item.artifact_id or case.primary_artifact,
                evidence_summary=_safe_text(item.evidence_summary),
                observed_value=_safe_text(item.observed_value, maximum=500),
                expected_value=_safe_text(item.expected_value, maximum=500),
                observed_at=_safe_text(item.timestamp, maximum=80),
                reliability=(
                    "high"
                    if item.confidence >= 0.8
                    else "medium"
                    if item.confidence >= 0.5
                    else "low"
                ),
                confidence=item.confidence,
                usage_warning=_safe_text(
                    item.usage_warning
                    or "Source evidence is preserved without asserting causation.",
                    maximum=500,
                ),
            )
        )
    for hypothesis in case.hypotheses[:16]:
        summary = _safe_text(hypothesis.hypothesis)
        if not summary:
            continue
        add(
            BobaRootCauseEvidenceV1(
                evidence_id=_stable_id(
                    "root_evidence",
                    case.diagnostic_case_id,
                    hypothesis.hypothesis_id,
                ),
                source_type="error_doctor_hypothesis",
                source_id=hypothesis.hypothesis_id,
                module_name=case.primary_module,
                artifact_id=case.primary_artifact,
                evidence_summary=summary,
                reliability=(
                    "conflicting"
                    if hypothesis.conflicting_evidence_ids
                    else "low"
                ),
                confidence=_clamp(min(hypothesis.confidence, 0.65)),
                usage_warning=(
                    "Error Doctor hypothesis; verification is required and "
                    "correlation is not causation."
                ),
            )
        )
    for key, summary in _manual_items(manual_context):
        add(
            BobaRootCauseEvidenceV1(
                evidence_id=_stable_id(
                    "root_evidence",
                    case.diagnostic_case_id,
                    "manual",
                    key,
                    summary,
                ),
                source_type="bounded_manual_context",
                source_id=f"manual_context:{key}",
                module_name=case.primary_module,
                artifact_id=case.primary_artifact,
                evidence_summary=f"{key}: {summary}",
                reliability=(
                    "conflicting" if "conflict" in key.casefold() else "low"
                ),
                confidence=0.35,
                usage_warning=(
                    "Bounded manual context is unverified and is not a complete log."
                ),
            )
        )
    if not evidence:
        add(
            BobaRootCauseEvidenceV1(
                evidence_id=_stable_id(
                    "root_evidence",
                    case.diagnostic_case_id,
                    "case_summary",
                ),
                source_type="unknown",
                source_id=case.diagnostic_case_id,
                module_name=case.primary_module,
                artifact_id=case.primary_artifact,
                evidence_summary=_safe_text(case.symptom_summary),
                reliability="low",
                confidence=_clamp(min(case.confidence, 0.45)),
                usage_warning="Diagnostic summary has no independently referenced evidence.",
            )
        )
    return evidence


def _event_type(
    case: BobaDiagnosticCaseV1,
    evidence: BobaRootCauseEvidenceV1,
) -> BobaFailureTimelineEventTypeV1:
    text = " ".join(
        (
            case.error_category,
            case.symptom_summary,
            case.probable_cause_summary,
            evidence.evidence_summary,
            evidence.observed_value,
        )
    ).casefold()
    if "rights" in text or "permission gate" in text:
        return "rights_blocked"
    if "safety" in text or "human approval" in text:
        return "safety_blocked"
    if "resource exhaustion" in text or "resource exhausted" in text or "winerror 1450" in text:
        return "resource_exhaustion"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if (
        "executable" in text
        and ("missing" in text or "unavailable" in text or "not found" in text)
    ):
        return "tool_unavailable"
    if "tool" in text and ("failed" in text or "crash" in text):
        return "tool_failed"
    if "validation" in text and ("failed" in text or "invalid" in text):
        return "validation_failed"
    if "validation" in text and ("missing" in text or "not available" in text):
        return "validation_missing"
    if "configuration" in text or "config" in text:
        return "configuration_missing"
    if "environment" in text:
        return "environment_missing"
    if "stale" in text and ("dependency" in text or "upstream" in text):
        return "dependency_stale"
    if "missing" in text and ("dependency" in text or "upstream" in text):
        return "dependency_missing"
    if "unreadable" in text:
        return "artifact_unreadable"
    if "corrupt" in text or "malformed" in text:
        return "artifact_corrupt"
    if "missing" in text or case.error_category == "missing_artifact":
        return "artifact_missing"
    if "stale" in text or case.error_category == "stale_artifact":
        return "artifact_updated"
    if "blocked" in text:
        return "module_blocked"
    if "workflow stopped" in text:
        return "workflow_stopped"
    return "unknown"


def _causal_relevance(
    case: BobaDiagnosticCaseV1,
    evidence: BobaRootCauseEvidenceV1,
) -> BobaCausalRelevanceV1:
    if evidence.source_type == "error_doctor_hypothesis":
        return "contributing_event"
    summary = evidence.evidence_summary.casefold()
    if "downstream" in summary or "secondary symptom" in summary:
        return "downstream_effect"
    if case.diagnosis_status in {"observed_fact", "probable"}:
        return "possible_origin"
    if case.diagnosis_status == "possible":
        return "contributing_event"
    return "unknown"


def build_failure_timeline(
    case: BobaDiagnosticCaseV1,
    evidence: Sequence[BobaRootCauseEvidenceV1],
    *,
    manual_context: Mapping[str, Any] | None = None,
) -> BobaFailureTimelineV1:
    """Order bounded evidence conservatively without inventing timestamps."""

    analysis_case_id = _stable_id("root_analysis_case", case.diagnostic_case_id)
    events: list[BobaFailureTimelineEventV1] = []
    for item in evidence[:96]:
        relevance = _causal_relevance(case, item)
        events.append(
            BobaFailureTimelineEventV1(
                event_id=_stable_id(
                    "root_timeline_event",
                    case.diagnostic_case_id,
                    item.evidence_id,
                ),
                event_type=_event_type(case, item),
                module_name=item.module_name or case.primary_module,
                artifact_id=item.artifact_id or case.primary_artifact,
                observed_at=item.observed_at,
                source_type=item.source_type,
                source_id=item.source_id,
                event_summary=item.evidence_summary,
                status_before="unknown",
                status_after=(
                    "blocked"
                    if case.processing_impact
                    in {"full_block", "unsafe_to_continue"}
                    else case.processing_impact
                ),
                confirmed=(
                    item.source_type == "error_doctor_fact"
                    or (
                        item.reliability == "high"
                        and item.source_type != "error_doctor_hypothesis"
                    )
                ),
                causal_relevance=relevance,
                confidence=item.confidence,
                warnings=(
                    ["Timestamp is absent or invalid; order was not invented."]
                    if _parse_timestamp(item.observed_at) is None
                    else []
                ),
            )
        )
    indexed = list(enumerate(events))
    parsed = [(index, event, _parse_timestamp(event.observed_at)) for index, event in indexed]
    ordered = sorted(
        parsed,
        key=lambda item: (
            item[2] is None,
            item[2] or datetime.max.replace(tzinfo=UTC),
            item[0],
        ),
    )
    events = [item[1] for item in ordered]
    timestamped: list[tuple[BobaFailureTimelineEventV1, datetime]] = []
    for event in events:
        parsed_timestamp = _parse_timestamp(event.observed_at)
        if parsed_timestamp is not None:
            timestamped.append((event, parsed_timestamp))
    conflicting = bool(
        manual_context
        and (
            manual_context.get("conflicting_timestamps")
            or manual_context.get("timestamp_conflict")
        )
    ) or any(
        "conflicting timestamp" in text.casefold()
        for text in (*case.warnings, *case.limitations)
    )
    origins = [
        (event, stamp)
        for event, stamp in timestamped
        if event.causal_relevance == "possible_origin"
    ]
    downstream = [
        (event, stamp)
        for event, stamp in timestamped
        if event.causal_relevance == "downstream_effect"
    ]
    if origins and downstream:
        earliest_origin = min(stamp for _, stamp in origins)
        if any(stamp < earliest_origin for _, stamp in downstream):
            conflicting = True
    missing_time = len(timestamped) != len(events)
    if not events:
        confidence = 0.0
    elif not timestamped:
        confidence = 0.2
    elif missing_time:
        confidence = 0.52
    else:
        confidence = 0.78
    if conflicting:
        confidence -= 0.28
    earliest = timestamped[0][0].event_id if timestamped else ""
    latest = timestamped[-1][0].event_id if timestamped else ""
    failures = [
        event
        for event in events
        if event.event_type
        not in {"artifact_created", "artifact_updated", "validation_passed", "unknown"}
    ]
    confirmed_failures = [event for event in failures if event.confirmed]
    warnings = []
    if missing_time:
        warnings.append("Some events lack reliable time information.")
    if conflicting:
        warnings.append("Conflicting timestamps lowered ordering confidence.")
    warnings.append(
        "Earliest known failure is an observation boundary, not automatic root-cause proof."
    )
    return BobaFailureTimelineV1(
        timeline_id=_stable_id("root_failure_timeline", case.diagnostic_case_id),
        analysis_case_id=analysis_case_id,
        events=events,
        earliest_event_id=earliest,
        first_failure_event_id=failures[0].event_id if failures else "",
        first_confirmed_failure_event_id=(
            confirmed_failures[0].event_id if confirmed_failures else ""
        ),
        latest_observed_event_id=latest,
        ordering_confidence=_clamp(confidence),
        conflicting_timestamps=conflicting,
        missing_time_information=missing_time,
        warnings=warnings,
    )


def _category_from_text(
    case: BobaDiagnosticCaseV1,
    text: str,
) -> BobaRootCauseCategoryV1:
    lowered = text.casefold()
    if "unknown validation format" in lowered:
        return "unknown"
    if (
        case.safety_impact in {"rights_gate_blocked", "safety_gate_blocked"}
        or "unknown rights" in lowered
        or "rights blocked" in lowered
        or "permission required" in lowered
        or "human approval" in lowered
    ):
        return "intentional_safety_block"
    if "resource exhaustion" in lowered or "resource exhausted" in lowered:
        return "resource_exhaustion"
    if "checkpoint" in lowered:
        return "checkpoint_failure"
    if "audio" in lowered and "video" in lowered and "sync" in lowered:
        return "audio_video_sync"
    if "ffprobe" in lowered or "media probe" in lowered:
        return "media_probe"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    tool_unavailable_phrases = (
        "missing executable",
        "executable is missing",
        "executable unavailable",
        "executable is unavailable",
        "executable not found",
        "tool unavailable",
        "tool is unavailable",
        "required tool is missing",
        "ffmpeg unavailable",
        "ffmpeg is unavailable",
        "ffmpeg not found",
    )
    if any(phrase in lowered for phrase in tool_unavailable_phrases):
        return "tool_unavailable"
    if ("tool" in lowered or "ffmpeg" in lowered) and (
        "failed" in lowered or "crash" in lowered
    ):
        return "tool_failure"
    if "code defect" in lowered or "software bug" in lowered:
        return "code_defect"
    mapping: dict[str, BobaRootCauseCategoryV1] = {
        "missing_artifact": "missing_artifact",
        "corrupt_artifact": "corrupt_artifact",
        "unreadable_artifact": "corrupt_artifact",
        "stale_artifact": "stale_artifact",
        "schema_mismatch": "schema_mismatch",
        "broken_dependency": "dependency_order",
        "missing_dependency": "missing_artifact",
        "configuration": "configuration",
        "environment": "environment",
        "validation_failure": "validation_failure",
        "validation_missing": "validation_gap",
        "validation_stale": "validation_gap",
        "rendering": "rendering",
        "audio_video_sync": "audio_video_sync",
        "media_probe": "media_probe",
        "storage": "storage",
        "permission": "permission",
        "rights_safety": "intentional_safety_block",
        "ingestion": "data_quality",
        "external_tool": "tool_failure",
        "timeout": "timeout",
        "resource_exhaustion": "resource_exhaustion",
        "data_quality": "data_quality",
        "frontend": "unknown",
        "api": "unknown",
        "unknown": "unknown",
    }
    return mapping.get(case.error_category, "unknown")


def _candidate_title(
    category: BobaRootCauseCategoryV1,
    case: BobaDiagnosticCaseV1,
) -> str:
    labels: dict[BobaRootCauseCategoryV1, str] = {
        "missing_artifact": "Required artifact may be missing",
        "corrupt_artifact": "Artifact may be corrupt or unreadable",
        "stale_artifact": "Downstream artifact may be stale",
        "schema_mismatch": "Artifact schema may be incompatible",
        "dependency_order": "Dependency ordering may be incomplete",
        "configuration": "Configuration may be incomplete",
        "environment": "Runtime environment may differ",
        "storage": "Storage state may have interrupted processing",
        "code_defect": "A code defect remains a possible explanation",
        "data_quality": "Input data quality may be insufficient",
        "validation_failure": "Required validation failed",
        "validation_gap": "Required validation evidence is missing",
        "tool_unavailable": "Required tool may be unavailable",
        "tool_failure": "Required tool may have failed",
        "timeout": "A bounded operation timed out",
        "resource_exhaustion": "System resources may have been exhausted",
        "checkpoint_failure": "Checkpoint state may be invalid",
        "rendering": "Rendering stage may have failed",
        "audio_video_sync": "Audio/video timing may be invalid",
        "media_probe": "Media probe evidence may be invalid",
        "rights_safety": "Rights or safety evidence requires review",
        "permission": "Permission state may be incomplete",
        "intentional_safety_block": "Processing is intentionally safety-blocked",
        "user_input": "Required human input is missing",
        "external_service": "An external dependency may be unavailable",
        "unknown": "Cause remains unknown",
    }
    return _safe_text(
        f"{labels[category]}: {case.primary_module or case.workflow_stage}",
        maximum=240,
    )


def _candidate_base(category: BobaRootCauseCategoryV1) -> float:
    scores: dict[BobaRootCauseCategoryV1, float] = {
        "missing_artifact": 0.72,
        "corrupt_artifact": 0.76,
        "stale_artifact": 0.62,
        "schema_mismatch": 0.6,
        "dependency_order": 0.64,
        "configuration": 0.42,
        "environment": 0.4,
        "storage": 0.48,
        "code_defect": 0.24,
        "data_quality": 0.5,
        "validation_failure": 0.78,
        "validation_gap": 0.25,
        "tool_unavailable": 0.7,
        "tool_failure": 0.56,
        "timeout": 0.55,
        "resource_exhaustion": 0.7,
        "checkpoint_failure": 0.64,
        "rendering": 0.46,
        "audio_video_sync": 0.52,
        "media_probe": 0.54,
        "rights_safety": 0.7,
        "permission": 0.58,
        "intentional_safety_block": 0.92,
        "user_input": 0.62,
        "external_service": 0.4,
        "unknown": 0.18,
    }
    return scores[category]


def _candidate_checks(
    category: BobaRootCauseCategoryV1,
) -> tuple[list[str], list[str]]:
    checks: dict[
        BobaRootCauseCategoryV1,
        tuple[list[str], list[str]],
    ] = {
        "missing_artifact": (
            [
                "Confirm the expected artifact is absent from the saved project state.",
                "Confirm the artifact is required by the nearest blocked downstream stage.",
            ],
            [
                "Reject this candidate if the expected artifact exists, is readable, "
                "and matches the required schema."
            ],
        ),
        "corrupt_artifact": (
            [
                "Inspect the saved artifact structure with an approved read-only inspector.",
                "Compare its schema and parse result with a known valid artifact.",
            ],
            [
                "Reject this candidate if the artifact parses completely and passes "
                "its required validation."
            ],
        ),
        "stale_artifact": (
            [
                "Compare saved upstream and downstream timestamps without treating "
                "modification time alone as proof.",
                "Confirm the downstream artifact references the current upstream version.",
            ],
            [
                "Reject this candidate if version references and semantic inputs match "
                "despite timestamp differences."
            ],
        ),
        "schema_mismatch": (
            [
                "Inspect the saved schema/version fields.",
                "Compare the producer schema with the consumer's declared compatibility.",
            ],
            [
                "Reject this candidate if both sides declare and validate a compatible schema."
            ],
        ),
        "dependency_order": (
            [
                "Inspect the nearest required dependency and its saved completion state.",
                "Compare causal order with the registered BOBA dependency chain.",
            ],
            [
                "Reject this candidate if every required dependency completed before "
                "the downstream stage."
            ],
        ),
        "configuration": (
            [
                "Inspect bounded non-secret configuration presence and effective defaults.",
            ],
            [
                "Reject this candidate if required non-secret configuration is present "
                "and matches a successful run."
            ],
        ),
        "environment": (
            [
                "Inspect bounded environment capability metadata without exposing secrets.",
                "Compare relevant platform and dependency versions with a successful run.",
            ],
            [
                "Reject this candidate if the relevant environment matches a successful run."
            ],
        ),
        "validation_failure": (
            [
                "Inspect the saved required validation report and its bounded failure fields.",
            ],
            [
                "Reject this candidate if a current required validation report passed "
                "for the same artifact."
            ],
        ),
        "validation_gap": (
            [
                "Confirm whether a current validation report exists.",
            ],
            [
                "Do not infer a software defect solely from missing validation evidence."
            ],
        ),
        "tool_unavailable": (
            [
                "Inspect saved tool-availability metadata.",
                "Confirm which capability and output properties are required.",
            ],
            [
                "Reject this candidate if the required executable was available and "
                "successfully produced compatible output."
            ],
        ),
        "tool_failure": (
            [
                "Inspect the bounded tool failure category and output status.",
                "Compare with a successful local run using the same input class.",
            ],
            [
                "Reject this candidate if the tool completed successfully and its output "
                "passed validation."
            ],
        ),
        "timeout": (
            [
                "Inspect the bounded timeout category and configured deadline.",
                "Compare elapsed-time evidence with a successful run.",
            ],
            [
                "Reject this candidate if no timeout occurred or an earlier confirmed "
                "failure explains the stop."
            ],
        ),
        "resource_exhaustion": (
            [
                "Inspect the bounded resource-exhaustion category and stage name.",
                "Review saved resource-history evidence if available.",
                "Compare resource settings with a successful synthetic run.",
            ],
            [
                "Reject this candidate if the same failure reproduces without resource "
                "pressure or a prior confirmed defect explains it."
            ],
        ),
        "checkpoint_failure": (
            [
                "Inspect the saved checkpoint path, parse status, and referenced artifact state.",
                "Compare checkpoint time with its producing stage.",
            ],
            [
                "Reject this candidate if the canonical checkpoint and all referenced "
                "artifacts validate."
            ],
        ),
        "data_quality": (
            [
                "Inspect bounded input-quality status and required fields.",
            ],
            [
                "Reject this candidate if the same input passes the required data validator."
            ],
        ),
        "code_defect": (
            [
                "Exclude missing data, configuration, environment, dependency, tool, "
                "validation, and safety causes first.",
                "Compare the failure with a known successful run at the same code revision.",
            ],
            [
                "Reject this candidate if a simpler supported operational cause explains "
                "the symptoms."
            ],
        ),
        "intentional_safety_block": (
            [
                "Inspect the saved rights or safety decision and required human checks.",
            ],
            [
                "Do not reject or bypass an intentional block without approved rights "
                "or safety evidence."
            ],
        ),
    }
    return checks.get(
        category,
        (
            ["Inspect the nearest bounded saved evidence and dependency state."],
            ["Reject this candidate if a better-supported earlier cause explains the case."],
        ),
    )


def _repairability(
    category: BobaRootCauseCategoryV1,
) -> BobaRootCauseRepairabilityV1:
    if category in {"intentional_safety_block", "rights_safety", "permission"}:
        return "not_a_defect"
    if category in {"tool_unavailable", "tool_failure", "resource_exhaustion", "timeout"}:
        return "requires_tool_fallback"
    if category == "code_defect":
        return "requires_code_change"
    if category in {"configuration", "environment"}:
        return "requires_configuration_change"
    if category in {"user_input"}:
        return "requires_human_decision"
    if category in {"unknown", "validation_gap"}:
        return "unknown"
    return "recoverable_with_approval"


def _owner(category: BobaRootCauseCategoryV1) -> str:
    if category in {"tool_unavailable", "tool_failure", "resource_exhaustion", "timeout"}:
        return "tool_recovery_brain"
    if category in {"validation_failure", "validation_gap"}:
        return "validator_runner"
    if category in {
        "missing_artifact",
        "corrupt_artifact",
        "stale_artifact",
        "schema_mismatch",
        "dependency_order",
        "checkpoint_failure",
        "storage",
    }:
        return "artifact_inspector"
    if category in {"intentional_safety_block", "rights_safety", "permission"}:
        return "rights_permission_gate"
    if category == "code_defect":
        return "code_surgeon"
    return "repair_planner"


def _direct_causal_support(
    case: BobaDiagnosticCaseV1,
    evidence: Sequence[BobaRootCauseEvidenceV1],
    manual_context: Mapping[str, Any] | None,
) -> bool:
    if manual_context and manual_context.get("direct_causal_evidence") is True:
        return True
    if case.diagnosis_status != "observed_fact":
        return False
    causal_text = " ".join(
        [case.probable_cause_summary, *case.confirmed_facts]
    ).casefold()
    return (
        ("caused by" in causal_text or "directly caused" in causal_text)
        and any(item.reliability == "high" for item in evidence)
    )


def _hypothesis_category(
    hypothesis: BobaDiagnosticHypothesisV1,
    case: BobaDiagnosticCaseV1,
) -> BobaRootCauseCategoryV1:
    text = f"{hypothesis.category} {hypothesis.hypothesis}"
    category = _category_from_text(case, text)
    if category != _category_from_text(case, case.probable_cause_summary):
        return category
    if hypothesis.category == "environment_factor":
        return "environment"
    if hypothesis.category == "configuration_factor":
        return "configuration"
    if hypothesis.category == "data_factor":
        return "data_quality"
    if hypothesis.category == "safety_factor":
        return "intentional_safety_block"
    return category


def _candidate_evidence_quality(
    supporting: Sequence[BobaRootCauseEvidenceV1],
    conflicting_ids: Sequence[str],
    *,
    category: BobaRootCauseCategoryV1,
) -> BobaRootCauseEvidenceQualityV1:
    if conflicting_ids:
        return "conflicting"
    if not supporting:
        return "insufficient"
    if category == "validation_gap":
        return "insufficient"
    if any(item.reliability == "high" for item in supporting) and len(supporting) >= 2:
        return "strong"
    if any(item.reliability in {"high", "medium"} for item in supporting):
        return "moderate"
    return "weak"


def identify_downstream_symptoms(
    case: BobaDiagnosticCaseV1,
    report: BobaErrorDoctorSetV1,
) -> list[BobaDownstreamSymptomV1]:
    """Map secondary findings and known cascades to bounded symptoms."""

    result: list[BobaDownstreamSymptomV1] = []
    seen: set[tuple[str, str, str]] = set()

    def add(
        *,
        finding_id: str,
        module_name: str,
        artifact_id: str,
        summary: str,
        depth: int,
        confidence: float,
    ) -> None:
        key = (module_name, artifact_id, summary.casefold())
        if key in seen or len(result) >= 128:
            return
        seen.add(key)
        result.append(
            BobaDownstreamSymptomV1(
                downstream_symptom_id=_stable_id(
                    "root_downstream_symptom",
                    case.diagnostic_case_id,
                    finding_id,
                    module_name,
                    artifact_id,
                    summary,
                ),
                analysis_case_id=_stable_id(
                    "root_analysis_case",
                    case.diagnostic_case_id,
                ),
                source_finding_id=finding_id,
                module_name=module_name,
                artifact_id=artifact_id,
                symptom_summary=_safe_text(summary),
                originating_candidate_ids=[],
                cascade_depth=depth,
                processing_impact=case.processing_impact,
                confidence=_clamp(confidence),
                warnings=["Downstream mapping is advisory until causal links are verified."],
            )
        )

    for finding in report.classified_findings:
        if finding.classified_finding_id not in case.related_finding_ids:
            continue
        if not (
            finding.is_downstream_effect
            or finding.is_secondary_symptom
            or finding.module_name != case.primary_module
        ):
            continue
        add(
            finding_id=finding.classified_finding_id,
            module_name=finding.module_name,
            artifact_id=finding.artifact_id,
            summary=finding.explanation,
            depth=1,
            confidence=finding.confidence,
        )
    for cascade in report.cascading_impacts:
        if cascade.originating_case_id != case.diagnostic_case_id:
            continue
        for depth, module_name in enumerate(cascade.impacted_modules, start=1):
            artifact_id = (
                cascade.impacted_artifacts[depth - 1]
                if depth - 1 < len(cascade.impacted_artifacts)
                else ""
            )
            add(
                finding_id=cascade.cascade_id,
                module_name=module_name,
                artifact_id=artifact_id,
                summary=(
                    f"{module_name} is a downstream effect in the saved "
                    f"{case.workflow_stage} cascade."
                ),
                depth=depth,
                confidence=cascade.confidence,
            )
    for module_name in case.affected_modules:
        if module_name == case.primary_module:
            continue
        add(
            finding_id=case.diagnostic_case_id,
            module_name=module_name,
            artifact_id="",
            summary=f"{module_name} is affected downstream of the primary diagnostic case.",
            depth=1,
            confidence=min(case.confidence, 0.65),
        )
    return result


def generate_root_cause_candidates(
    case: BobaDiagnosticCaseV1,
    evidence: Sequence[BobaRootCauseEvidenceV1],
    symptoms: Sequence[BobaDownstreamSymptomV1],
    timeline: BobaFailureTimelineV1,
    *,
    manual_context: Mapping[str, Any] | None = None,
) -> list[BobaRootCauseCandidateV1]:
    """Generate and rank bounded candidates without treating ranking as proof."""

    combined = " ".join(
        (
            case.symptom_summary,
            case.probable_cause_summary,
            *case.confirmed_facts,
        )
    )
    categories: list[BobaRootCauseCategoryV1] = [
        _category_from_text(case, combined)
    ]
    hypothesis_by_category: dict[
        BobaRootCauseCategoryV1,
        list[BobaDiagnosticHypothesisV1],
    ] = defaultdict(list)
    for hypothesis in case.hypotheses[:16]:
        category = _hypothesis_category(hypothesis, case)
        hypothesis_by_category[category].append(hypothesis)
        if category not in categories:
            categories.append(category)
    for key, summary in _manual_items(manual_context):
        lowered = f"{key} {summary}".casefold()
        if any(
            token in lowered
            for token in (
                "configuration",
                "environment",
                "resource",
                "timeout",
                "code defect",
                "tool",
                "checkpoint",
            )
        ):
            category = _category_from_text(case, lowered)
            if category not in categories:
                categories.append(category)
    candidates: list[BobaRootCauseCandidateV1] = []
    direct = _direct_causal_support(case, evidence, manual_context)
    conflict_context = bool(
        manual_context
        and (
            manual_context.get("conflicting_evidence")
            or manual_context.get("contradictory_evidence")
        )
    )
    for category in categories[:8]:
        hypotheses = hypothesis_by_category.get(category, [])
        hypothesis_evidence_ids = {
            _stable_id(
                "root_evidence",
                case.diagnostic_case_id,
                hypothesis.hypothesis_id,
            )
            for hypothesis in hypotheses
        }
        supporting = [
            item
            for item in evidence
            if item.source_type != "error_doctor_hypothesis"
            or item.evidence_id in hypothesis_evidence_ids
        ]
        conflicts = _unique(
            [
                evidence_id
                for hypothesis in hypotheses
                for evidence_id in hypothesis.conflicting_evidence_ids
            ],
            limit=64,
            maximum=160,
        )
        conflicts.extend(
            item.evidence_id
            for item in evidence
            if item.reliability == "conflicting" and item.evidence_id not in conflicts
        )
        if conflict_context and supporting:
            conflicts.append(supporting[-1].evidence_id)
        conflicts = _unique(conflicts, limit=64, maximum=160)
        score = _candidate_base(category)
        if case.diagnosis_status == "observed_fact":
            score += 0.1
        elif case.diagnosis_status == "probable":
            score += 0.05
        elif case.diagnosis_status in {"possible", "insufficient_evidence", "unknown"}:
            score -= 0.1
        if direct:
            score += 0.08
        if case.severity == "informational":
            score -= 0.3
        elif case.severity == "low":
            score -= 0.12
        if case.processing_impact == "none":
            score -= 0.08
        if timeline.first_confirmed_failure_event_id:
            score += 0.05
        if timeline.conflicting_timestamps:
            score -= 0.14
        elif timeline.missing_time_information:
            score -= 0.05
        score += min(len(symptoms), 3) * 0.035
        score -= min(len(conflicts), 3) * 0.1
        if category == "code_defect":
            simpler_supported = any(
                existing.category != "code_defect"
                and existing.likelihood_score >= 0.5
                for existing in candidates
            )
            if simpler_supported:
                score -= 0.16
        if category == "validation_gap":
            score = min(score, 0.38)
        if category == "intentional_safety_block":
            score = max(score, 0.82)
        quality = _candidate_evidence_quality(
            supporting,
            conflicts,
            category=category,
        )
        if (
            case.diagnosis_status in {"possible", "unknown"}
            and category in {"configuration", "environment", "code_defect"}
            and quality != "conflicting"
        ):
            quality = "weak"
        if category == "code_defect" and not direct and quality != "conflicting":
            quality = "weak"
        confidence = case.confidence
        confidence += 0.08 if quality == "strong" else 0.0
        confidence -= 0.2 if quality == "conflicting" else 0.0
        confidence -= 0.16 if quality == "insufficient" else 0.0
        confidence -= 0.1 if category == "code_defect" and not direct else 0.0
        confidence -= 0.08 if timeline.conflicting_timestamps else 0.0
        confirmation, rejection = _candidate_checks(category)
        candidate_id = _stable_id(
            "root_cause_candidate",
            case.diagnostic_case_id,
            category,
        )
        explains = [item.downstream_symptom_id for item in symptoms]
        unexplained = (
            explains
            if category in {"unknown", "code_defect"} and quality in {"weak", "insufficient"}
            else []
        )
        candidates.append(
            BobaRootCauseCandidateV1(
                root_cause_candidate_id=candidate_id,
                analysis_case_id=_stable_id(
                    "root_analysis_case",
                    case.diagnostic_case_id,
                ),
                title=_candidate_title(category, case),
                category=category,
                candidate_summary=_safe_text(
                    case.probable_cause_summary
                    if category == categories[0]
                    else next(
                        (
                            hypothesis.hypothesis
                            for hypothesis in hypotheses
                            if hypothesis.hypothesis
                        ),
                        f"{category.replace('_', ' ')} remains a competing explanation.",
                    )
                ),
                earliest_failure_relationship=(
                    "Direct evidence links this candidate to the earliest confirmed failure."
                    if direct and timeline.first_confirmed_failure_event_id
                    else "This candidate is consistent with the earliest known failure, "
                    "but causal order still requires verification."
                    if timeline.first_failure_event_id
                    else "Reliable failure timing is unavailable, so earliest-cause "
                    "precedence is unresolved."
                ),
                supporting_evidence_ids=_unique(
                    [item.evidence_id for item in supporting],
                    limit=64,
                    maximum=160,
                ),
                conflicting_evidence_ids=conflicts,
                explains_symptom_ids=explains,
                unexplained_symptom_ids=unexplained,
                likelihood_score=_clamp(score),
                confidence=_clamp(confidence),
                evidence_quality=quality,
                verification_required=True,
                confirmation_checks=confirmation,
                rejection_checks=rejection,
                repairability=_repairability(category),
                safety_constraints=[
                    "Do not apply repairs automatically.",
                    "Do not execute verification checks inside Root Cause Analyzer.",
                    *(
                        ["Do not bypass rights or safety gates."]
                        if category
                        in {
                            "intentional_safety_block",
                            "rights_safety",
                            "permission",
                        }
                        else []
                    ),
                ],
                recommended_owner_module=_owner(category),
                warnings=[
                    "Likelihood ranking is advisory and is not mathematical certainty.",
                    *(
                        ["Code defect remains speculative until simpler causes are excluded."]
                        if category == "code_defect" and not direct
                        else []
                    ),
                ],
                limitations=[
                    "The analyzer used bounded saved evidence only.",
                    "No verification check was executed.",
                ],
            )
        )
    candidates.sort(
        key=lambda item: (
            -item.likelihood_score,
            -item.confidence,
            _CATEGORY_COMPLEXITY[item.category],
            item.root_cause_candidate_id,
        )
    )
    candidate_ids = {item.root_cause_candidate_id for item in candidates}
    for symptom in symptoms:
        symptom.originating_candidate_ids = list(candidate_ids)[:8]
    return candidates


def identify_contributing_factors(
    case: BobaDiagnosticCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    evidence: Sequence[BobaRootCauseEvidenceV1],
) -> list[BobaContributingFactorV1]:
    """Identify factors without claiming they are necessary or sufficient."""

    mapping: dict[BobaRootCauseCategoryV1, BobaContributingFactorCategoryV1] = {
        "resource_exhaustion": "resource_pressure",
        "stale_artifact": "stale_state",
        "configuration": "incomplete_configuration",
        "environment": "environment_difference",
        "schema_mismatch": "incompatible_format",
        "data_quality": "weak_input_data",
        "timeout": "retry_exhaustion",
        "checkpoint_failure": "checkpoint_gap",
        "validation_gap": "validation_gap",
        "user_input": "user_decision_required",
        "permission": "rights_constraint",
        "rights_safety": "rights_constraint",
        "intentional_safety_block": "safety_constraint",
    }
    result: list[BobaContributingFactorV1] = []
    for candidate in candidates[:8]:
        factor_category = mapping.get(candidate.category)
        if factor_category is None:
            continue
        result.append(
            BobaContributingFactorV1(
                contributing_factor_id=_stable_id(
                    "root_contributing_factor",
                    case.diagnostic_case_id,
                    factor_category,
                ),
                analysis_case_id=candidate.analysis_case_id,
                factor_category=factor_category,
                factor_summary=_safe_text(
                    f"{candidate.title} may have enabled or worsened the observed failure."
                ),
                related_root_cause_candidate_ids=[
                    candidate.root_cause_candidate_id
                ],
                evidence_ids=candidate.supporting_evidence_ids,
                impact=(
                    "May affect confidence, timing, or downstream availability; "
                    "independent sufficiency is not established."
                ),
                necessary_for_failure=False,
                sufficient_for_failure=False,
                confidence=_clamp(min(candidate.confidence, 0.7)),
                verification_needed=True,
                warnings=[
                    "This factor is not assumed necessary or sufficient for the failure."
                ],
            )
        )
    for hypothesis in case.hypotheses:
        if hypothesis.category != "contributing_factor":
            continue
        factor_id = _stable_id(
            "root_contributing_factor",
            case.diagnostic_case_id,
            hypothesis.hypothesis_id,
        )
        if any(item.contributing_factor_id == factor_id for item in result):
            continue
        result.append(
            BobaContributingFactorV1(
                contributing_factor_id=factor_id,
                analysis_case_id=_stable_id(
                    "root_analysis_case",
                    case.diagnostic_case_id,
                ),
                factor_category="unknown",
                factor_summary=_safe_text(hypothesis.hypothesis),
                related_root_cause_candidate_ids=[
                    item.root_cause_candidate_id for item in candidates[:4]
                ],
                evidence_ids=_unique(
                    hypothesis.supporting_evidence_ids,
                    limit=64,
                    maximum=160,
                ),
                impact="Possible contributing influence; causal sufficiency is unresolved.",
                necessary_for_failure=False,
                sufficient_for_failure=False,
                confidence=_clamp(min(hypothesis.confidence, 0.6)),
                verification_needed=True,
                warnings=["Hypothesis-derived contributing factor remains unverified."],
            )
        )
    return result[:32]


def _gap_method(text: str) -> BobaEvidenceCollectionMethodV1:
    lowered = text.casefold()
    if "timestamp" in lowered or "time" in lowered:
        return "compare_timestamps"
    if "schema" in lowered or "version" in lowered:
        return "compare_schema"
    if "validation" in lowered or "validator" in lowered:
        return "run_future_validator"
    if "configuration" in lowered or "config" in lowered:
        return "inspect_configuration"
    if "environment" in lowered:
        return "inspect_environment"
    if "tool" in lowered or "executable" in lowered:
        return "check_tool_health"
    if "resource" in lowered:
        return "inspect_bounded_log"
    if "rights" in lowered or "permission" in lowered:
        return "human_rights_review"
    if "user" in lowered or "approval" in lowered:
        return "collect_user_input"
    if "reproduc" in lowered:
        return "reproduce_manually"
    if "artifact" in lowered or "checkpoint" in lowered:
        return "inspect_saved_artifact"
    return "unknown"


def identify_evidence_gaps(
    case: BobaDiagnosticCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    timeline: BobaFailureTimelineV1,
) -> list[BobaEvidenceGapV1]:
    """Describe missing evidence without collecting it."""

    items = list(case.missing_information)
    if timeline.missing_time_information:
        items.append("Reliable timestamps for all relevant failure events.")
    if timeline.conflicting_timestamps:
        items.append("A trusted ordering source that resolves conflicting timestamps.")
    for candidate in candidates:
        if candidate.evidence_quality in {"weak", "insufficient", "conflicting"}:
            items.append(
                f"Independent evidence to confirm or reject {candidate.title}."
            )
        if candidate.category in {"tool_unavailable", "tool_failure"}:
            items.append("Saved tool availability and bounded failure-class evidence.")
        if candidate.category == "resource_exhaustion":
            items.append("Bounded resource history for the failed stage.")
        if candidate.category == "validation_gap":
            items.append("A current required validation report.")
        if candidate.category in {
            "intentional_safety_block",
            "rights_safety",
            "permission",
        }:
            items.append("Human-reviewed rights or permission evidence.")
    result: list[BobaEvidenceGapV1] = []
    candidate_ids = [item.root_cause_candidate_id for item in candidates[:8]]
    for item in _unique(items, limit=64):
        method = _gap_method(item)
        requires_validator = method == "run_future_validator"
        requires_command = method in {
            "run_future_validator",
            "reproduce_manually",
            "check_tool_health",
        }
        requires_external = method == "human_rights_review"
        result.append(
            BobaEvidenceGapV1(
                evidence_gap_id=_stable_id(
                    "root_evidence_gap",
                    case.diagnostic_case_id,
                    item,
                ),
                analysis_case_id=_stable_id(
                    "root_analysis_case",
                    case.diagnostic_case_id,
                ),
                missing_information=item,
                why_needed=(
                    "This information could increase or decrease confidence in the "
                    "ranked candidates without assuming causation."
                ),
                affected_candidate_ids=candidate_ids,
                collection_method=method,
                requires_command_execution=requires_command,
                requires_validator=requires_validator,
                requires_external_access=requires_external,
                requires_human_review=True,
                safe_to_collect=method not in {"unavailable"},
                priority=_priority(
                    candidates[0].likelihood_score if candidates else 0.2,
                    case.processing_impact,
                ),
                warnings=[
                    "Root Cause Analyzer identified this gap but did not collect evidence."
                ],
            )
        )
    return result


def _verification_check_specs(
    candidate: BobaRootCauseCandidateV1,
) -> list[
    tuple[
        BobaRootCauseVerificationCheckTypeV1,
        str,
        str,
        bool,
        bool,
    ]
]:
    specs: list[
        tuple[
            BobaRootCauseVerificationCheckTypeV1,
            str,
            str,
            bool,
            bool,
        ]
    ] = [
        (
            "inspect_artifact",
            "Review the bounded saved evidence already referenced by this candidate.",
            "Confirms whether the candidate is grounded in the saved project state.",
            True,
            True,
        )
    ]
    category = candidate.category
    if category in {
        "missing_artifact",
        "corrupt_artifact",
        "stale_artifact",
        "checkpoint_failure",
        "storage",
    }:
        specs.append(
            (
                "inspect_dependency",
                "Inspect the nearest registered upstream and downstream artifact states.",
                "Separates an originating artifact problem from downstream symptoms.",
                True,
                True,
            )
        )
    if category == "stale_artifact":
        specs.append(
            (
                "inspect_timestamp",
                "Compare explicit saved timestamps and version references.",
                "Tests ordering while avoiding modification-time-only causality.",
                True,
                True,
            )
        )
    if category == "schema_mismatch":
        specs.append(
            (
                "inspect_schema",
                "Compare producer and consumer schema/version declarations.",
                "Confirms or rejects format incompatibility.",
                True,
                True,
            )
        )
    if category == "configuration":
        specs.append(
            (
                "inspect_configuration",
                "Review bounded non-secret configuration presence and defaults.",
                "Tests the configuration explanation without exposing secrets.",
                True,
                True,
            )
        )
    if category == "environment":
        specs.append(
            (
                "inspect_environment",
                "Review bounded environment and dependency capability metadata.",
                "Tests environment compatibility without changing it.",
                True,
                True,
            )
        )
    if category in {"validation_failure", "validation_gap"}:
        specs.append(
            (
                "inspect_validation_report",
                "Review the current saved validation status and bounded error fields.",
                "Distinguishes confirmed validation failure from missing proof.",
                True,
                True,
            )
        )
    if category in {"tool_unavailable", "tool_failure", "timeout"}:
        specs.append(
            (
                "check_tool_availability",
                "Ask a future approved tool-health workflow to verify the required capability.",
                "Confirms availability and failure class.",
                False,
                False,
            )
        )
    if category == "resource_exhaustion":
        specs.append(
            (
                "check_resource_history",
                "Review bounded saved resource-history evidence for the failed stage.",
                "Confirms whether resource pressure coincided with the failure.",
                True,
                True,
            )
        )
    if category in {
        "tool_failure",
        "timeout",
        "resource_exhaustion",
        "code_defect",
    }:
        specs.append(
            (
                "compare_successful_run",
                "Compare bounded failure metadata with a known successful equivalent run.",
                "Tests whether the candidate distinguishes failed and successful states.",
                True,
                True,
            )
        )
    if category in {
        "intentional_safety_block",
        "rights_safety",
        "permission",
    }:
        specs.append(
            (
                "verify_rights_state",
                "Request human review of the saved rights or safety decision.",
                "Confirms the intentional block without bypassing it.",
                True,
                True,
            )
        )
        specs.append(
            (
                "stop_processing",
                "Keep unsafe processing stopped until the responsible gate approves it.",
                "Prevents an intentional block from being misclassified or bypassed.",
                True,
                True,
            )
        )
    return specs[:12]


def build_verification_plans(
    case: BobaDiagnosticCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
) -> list[BobaRootCauseVerificationPlanV1]:
    """Create advisory plans; this function never executes their checks."""

    plans: list[BobaRootCauseVerificationPlanV1] = []
    for candidate in candidates[:8]:
        checks: list[BobaRootCauseVerificationCheckV1] = []
        for order, (
            check_type,
            description,
            information_gain,
            safe,
            read_only,
        ) in enumerate(_verification_check_specs(candidate), start=1):
            checks.append(
                BobaRootCauseVerificationCheckV1(
                    check_id=_stable_id(
                        "root_verification_check",
                        candidate.root_cause_candidate_id,
                        str(order),
                        check_type,
                    ),
                    order=order,
                    check_type=check_type,
                    description=description,
                    prerequisite=(
                        "Human approval and the responsible future module."
                        if not read_only
                        else "Access to bounded saved project evidence."
                    ),
                    expected_information_gain=information_gain,
                    safe=safe,
                    read_only=read_only,
                    requires_human_review=True,
                    warnings=["This check was planned but not executed."],
                )
            )
        requires_command = any(not item.read_only for item in checks)
        requires_validator = candidate.category in {
            "validation_failure",
            "validation_gap",
            "data_quality",
            "media_probe",
            "audio_video_sync",
            "rendering",
        }
        plans.append(
            BobaRootCauseVerificationPlanV1(
                verification_plan_id=_stable_id(
                    "root_verification_plan",
                    candidate.root_cause_candidate_id,
                ),
                analysis_case_id=_stable_id(
                    "root_analysis_case",
                    case.diagnostic_case_id,
                ),
                root_cause_candidate_id=candidate.root_cause_candidate_id,
                objective=_safe_text(
                    f"Confirm or reject: {candidate.title}",
                ),
                checks=checks,
                expected_confirmation_evidence=candidate.confirmation_checks,
                expected_rejection_evidence=candidate.rejection_checks,
                safe=all(item.safe for item in checks),
                read_only=all(item.read_only for item in checks),
                requires_command_execution=requires_command,
                requires_validator_execution=requires_validator,
                requires_code_modification=False,
                requires_external_access=(
                    candidate.category == "external_service"
                ),
                requires_human_approval=True,
                stop_conditions=[
                    "Stop when evidence is sufficient to confirm or reject the candidate.",
                    "Stop if a rights, safety, privacy, or destructive-risk concern appears.",
                ],
                rollback_requirement=(
                    "A future non-read-only verification must define rollback before approval."
                    if requires_command
                    else "No rollback is required for the planned read-only inspection."
                ),
                suggested_owner_module=candidate.recommended_owner_module,
                priority=_priority(
                    candidate.likelihood_score,
                    case.processing_impact,
                ),
                warnings=[
                    "Root Cause Analyzer created this plan but executed no check.",
                    "Human approval is required before verification or repair actions.",
                ],
            )
        )
    return plans


def build_workflow_impact(
    case: BobaDiagnosticCaseV1,
    report: BobaErrorDoctorSetV1,
    registry: Sequence[BobaArtifactRegistryEntryV1],
) -> BobaWorkflowImpactAnalysisV1:
    """Describe affected and safe stages without authorizing resume."""

    impacted_modules = _unique(
        [
            case.primary_module,
            *case.affected_modules,
            *_downstream_modules(case.primary_module, registry),
        ],
        limit=64,
        maximum=120,
    )
    impacted_artifacts = _unique(
        [case.primary_artifact, *case.affected_artifacts],
        limit=64,
        maximum=120,
    )
    blocked_stages: list[str] = []
    degraded_stages: list[str] = []
    for cascade in report.cascading_impacts:
        if cascade.originating_case_id == case.diagnostic_case_id:
            blocked_stages.extend(cascade.blocked_workflow_stages)
    if case.processing_impact in {"full_block", "unsafe_to_continue"}:
        blocked_stages.append(case.workflow_stage)
    elif case.processing_impact in {"partial_block", "degraded"}:
        degraded_stages.append(case.workflow_stage)
    affected_workflows = {
        _workflow_for(module)
        for module in impacted_modules
        if _workflow_for(module) != "unknown"
    }
    safe_stages = [
        workflow
        for workflow, _ in _WORKFLOW_CHAINS
        if workflow not in affected_workflows
    ]
    unsafe_actions = [
        "Automatic workflow resume",
        "Automatic repair or source-artifact modification",
        "Destructive cleanup or safety-gate bypass",
    ]
    if case.safety_impact in {"rights_gate_blocked", "safety_gate_blocked"}:
        unsafe_actions.append("Processing that bypasses the saved rights or safety block")
    return BobaWorkflowImpactAnalysisV1(
        workflow_impact_id=_stable_id(
            "root_workflow_impact",
            case.diagnostic_case_id,
        ),
        analysis_case_id=_stable_id(
            "root_analysis_case",
            case.diagnostic_case_id,
        ),
        originating_module=case.primary_module,
        impacted_modules=impacted_modules,
        impacted_artifacts=impacted_artifacts,
        blocked_stages=_unique(blocked_stages, limit=32, maximum=120),
        degraded_stages=_unique(degraded_stages, limit=32, maximum=120),
        safe_stages=_unique(safe_stages, limit=32, maximum=120),
        unsafe_next_actions=_unique(unsafe_actions, limit=32),
        conditionally_safe_actions=[
            "Read bounded saved diagnostic evidence.",
            "Prepare a human-reviewed verification request.",
            "Inspect unrelated healthy stages without modifying them.",
        ],
        resume_requirements=[
            "Verify the selected root-cause candidate through an approved future module.",
            "Resolve applicable rights and safety blocks.",
            "Obtain explicit human approval from the responsible operator.",
            "Let a future Workflow Controller evaluate verified state.",
        ],
        confidence=_clamp(case.confidence),
        warnings=[
            "Root Cause Analyzer does not authorize workflow resume.",
            "Safe-stage classification is advisory and bounded to known BOBA chains.",
        ],
    )


def detect_causal_graph_cycles(
    edges: Sequence[BobaCausalEdgeV1],
) -> bool:
    """Return true when the bounded directed graph contains a cycle."""

    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.from_node_id].append(edge.to_node_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for next_id in adjacency.get(node_id, []):
            if visit(next_id):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in tuple(adjacency))


def _node_type_for_candidate(
    category: BobaRootCauseCategoryV1,
) -> BobaCausalNodeTypeV1:
    mapping: dict[BobaRootCauseCategoryV1, BobaCausalNodeTypeV1] = {
        "missing_artifact": "missing_input",
        "corrupt_artifact": "corrupt_artifact",
        "stale_artifact": "stale_artifact",
        "configuration": "configuration_factor",
        "environment": "environment_factor",
        "tool_unavailable": "tool_failure",
        "tool_failure": "tool_failure",
        "timeout": "tool_failure",
        "resource_exhaustion": "resource_factor",
        "validation_gap": "validation_gap",
        "intentional_safety_block": "safety_block",
        "rights_safety": "rights_block",
        "permission": "rights_block",
    }
    return mapping.get(category, "root_cause_candidate")


def _relationship_for_candidate(
    candidate: BobaRootCauseCandidateV1,
    *,
    direct_causal_support: bool,
) -> BobaCausalRelationshipV1:
    if candidate.category in {
        "intentional_safety_block",
        "rights_safety",
        "permission",
    }:
        return "blocked"
    if candidate.conflicting_evidence_ids:
        return "correlated_with"
    if direct_causal_support and candidate.evidence_quality == "strong":
        return "caused"
    if (
        candidate.evidence_quality in {"strong", "moderate"}
        and candidate.likelihood_score >= 0.62
    ):
        return "probably_caused"
    return "may_have_caused"


def build_causal_graph(
    case: BobaDiagnosticCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    factors: Sequence[BobaContributingFactorV1],
    symptoms: Sequence[BobaDownstreamSymptomV1],
    impact: BobaWorkflowImpactAnalysisV1,
    *,
    evidence: Sequence[BobaRootCauseEvidenceV1],
    manual_context: Mapping[str, Any] | None = None,
) -> BobaCausalGraphV1:
    """Build a bounded, evidence-labelled graph with conservative edges."""

    analysis_case_id = _stable_id("root_analysis_case", case.diagnostic_case_id)
    graph_id = _stable_id("root_causal_graph", case.diagnostic_case_id)
    nodes: list[BobaCausalNodeV1] = []
    edges: list[BobaCausalEdgeV1] = []
    root_ids: list[str] = []
    symptom_ids: list[str] = []
    factor_ids: list[str] = []
    blocked_ids: list[str] = []
    evidence_by_id = {item.evidence_id: item for item in evidence}
    direct = _direct_causal_support(case, evidence, manual_context)
    candidate_nodes: dict[str, str] = {}
    symptom_nodes: dict[str, str] = {}
    factor_nodes: dict[str, str] = {}

    def add_node(node: BobaCausalNodeV1) -> None:
        if len(nodes) < 96 and all(item.node_id != node.node_id for item in nodes):
            nodes.append(node)

    def add_edge(
        from_node_id: str,
        to_node_id: str,
        relationship: BobaCausalRelationshipV1,
        evidence_ids: Sequence[str],
        confidence: float,
        *,
        confirmed: bool = False,
        warning: str = "",
    ) -> None:
        if len(edges) >= 192:
            return
        edge_id = _stable_id(
            "root_causal_edge",
            graph_id,
            from_node_id,
            to_node_id,
            relationship,
        )
        if any(item.edge_id == edge_id for item in edges):
            return
        edges.append(
            BobaCausalEdgeV1(
                edge_id=edge_id,
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                relationship=relationship,
                evidence_ids=_unique(
                    evidence_ids,
                    limit=64,
                    maximum=160,
                ),
                confidence=_clamp(confidence),
                confirmed=confirmed,
                verification_needed=not confirmed,
                warnings=[warning] if warning else [],
            )
        )

    for candidate in candidates[:24]:
        node_id = _stable_id(
            "root_causal_node",
            candidate.root_cause_candidate_id,
        )
        candidate_nodes[candidate.root_cause_candidate_id] = node_id
        root_ids.append(node_id)
        add_node(
            BobaCausalNodeV1(
                node_id=node_id,
                node_type=_node_type_for_candidate(candidate.category),
                module_name=case.primary_module,
                artifact_id=case.primary_artifact,
                label=candidate.title,
                description=candidate.candidate_summary,
                confirmed=(
                    direct
                    and candidate.evidence_quality == "strong"
                    and not candidate.conflicting_evidence_ids
                ),
                confidence=candidate.confidence,
                evidence_ids=candidate.supporting_evidence_ids,
                warnings=[
                    "Root-cause candidate node is ranked, not automatically proven."
                ],
            )
        )
    for symptom in symptoms[:64]:
        node_id = _stable_id(
            "root_causal_node",
            symptom.downstream_symptom_id,
        )
        symptom_nodes[symptom.downstream_symptom_id] = node_id
        symptom_ids.append(node_id)
        add_node(
            BobaCausalNodeV1(
                node_id=node_id,
                node_type="downstream_symptom",
                module_name=symptom.module_name,
                artifact_id=symptom.artifact_id,
                label=_safe_text(
                    symptom.symptom_summary,
                    maximum=240,
                ),
                description=symptom.symptom_summary,
                confirmed=False,
                confidence=symptom.confidence,
                evidence_ids=(
                    [symptom.source_finding_id]
                    if symptom.source_finding_id
                    else []
                ),
                warnings=["Downstream classification requires causal verification."],
            )
        )
    for factor in factors[:32]:
        node_id = _stable_id(
            "root_causal_node",
            factor.contributing_factor_id,
        )
        factor_nodes[factor.contributing_factor_id] = node_id
        factor_ids.append(node_id)
        add_node(
            BobaCausalNodeV1(
                node_id=node_id,
                node_type="contributing_factor",
                module_name=case.primary_module,
                artifact_id=case.primary_artifact,
                label=_safe_text(factor.factor_summary, maximum=240),
                description=factor.factor_summary,
                confirmed=False,
                confidence=factor.confidence,
                evidence_ids=factor.evidence_ids,
                warnings=[
                    "Contributing factor is not assumed necessary or sufficient."
                ],
            )
        )
    for stage in impact.blocked_stages[:32]:
        node_id = _stable_id(
            "root_causal_node",
            analysis_case_id,
            "blocked_stage",
            stage,
        )
        blocked_ids.append(node_id)
        add_node(
            BobaCausalNodeV1(
                node_id=node_id,
                node_type="downstream_symptom",
                module_name=stage,
                label=f"Blocked stage: {stage}",
                description=(
                    "Saved diagnostic evidence indicates this workflow stage is blocked."
                ),
                confirmed=case.processing_impact in {"full_block", "unsafe_to_continue"},
                confidence=case.confidence,
                evidence_ids=[],
                warnings=["Blocked stage is an impact, not a root cause."],
            )
        )
    for candidate in candidates[:24]:
        from_id = candidate_nodes[candidate.root_cause_candidate_id]
        relation = _relationship_for_candidate(
            candidate,
            direct_causal_support=direct,
        )
        for symptom_id in candidate.explains_symptom_ids[:64]:
            to_id = symptom_nodes.get(symptom_id)
            if not to_id:
                continue
            add_edge(
                from_id,
                to_id,
                relation,
                candidate.supporting_evidence_ids,
                min(candidate.confidence, candidate.likelihood_score),
                confirmed=(relation == "caused"),
                warning=(
                    ""
                    if relation == "caused"
                    else "Causal direction remains subject to verification."
                ),
            )
        for conflict_id in candidate.conflicting_evidence_ids[:16]:
            if conflict_id not in evidence_by_id:
                continue
            contradiction_id = _stable_id(
                "root_causal_node",
                graph_id,
                "contradiction",
                conflict_id,
            )
            add_node(
                BobaCausalNodeV1(
                    node_id=contradiction_id,
                    node_type="unknown",
                    module_name=evidence_by_id[conflict_id].module_name,
                    artifact_id=evidence_by_id[conflict_id].artifact_id,
                    label="Conflicting evidence",
                    description=evidence_by_id[conflict_id].evidence_summary,
                    confirmed=False,
                    confidence=evidence_by_id[conflict_id].confidence,
                    evidence_ids=[conflict_id],
                    warnings=["Contradictory evidence is preserved."],
                )
            )
            add_edge(
                contradiction_id,
                from_id,
                "contradicted_by",
                [conflict_id],
                evidence_by_id[conflict_id].confidence,
            )
    for factor in factors[:32]:
        factor_node = factor_nodes[factor.contributing_factor_id]
        related = factor.related_root_cause_candidate_ids or [
            item.root_cause_candidate_id for item in candidates[:1]
        ]
        for candidate_id in related[:8]:
            target = candidate_nodes.get(candidate_id)
            if target:
                add_edge(
                    factor_node,
                    target,
                    "contributed_to",
                    factor.evidence_ids,
                    factor.confidence,
                    warning="Contribution does not establish necessity or sufficiency.",
                )
    for symptom_node in symptom_ids:
        for blocked_node in blocked_ids:
            add_edge(
                symptom_node,
                blocked_node,
                "blocked",
                [],
                min(case.confidence, 0.72),
            )
    if (
        manual_context
        and manual_context.get("force_cycle_for_validation") is True
        and root_ids
        and symptom_ids
    ):
        add_edge(
            symptom_ids[0],
            root_ids[0],
            "correlated_with",
            [],
            0.2,
            warning="Synthetic/manual cycle requires human review.",
        )
    cycles = detect_causal_graph_cycles(edges)
    unresolved_links = []
    if not symptoms:
        unresolved_links.append("No bounded downstream symptom references were available.")
    if any(item.unexplained_symptom_ids for item in candidates):
        unresolved_links.append("One or more candidates leave symptoms unexplained.")
    graph_confidence = (
        sum(item.confidence for item in candidates[:3]) / min(len(candidates), 3)
        if candidates
        else 0.0
    )
    if cycles:
        graph_confidence -= 0.25
    return BobaCausalGraphV1(
        causal_graph_id=graph_id,
        analysis_case_id=analysis_case_id,
        nodes=nodes,
        edges=edges,
        root_candidate_node_ids=root_ids,
        symptom_node_ids=symptom_ids,
        contributing_node_ids=factor_ids,
        blocked_stage_node_ids=blocked_ids,
        graph_confidence=_clamp(graph_confidence),
        cycles_detected=cycles,
        unresolved_links=unresolved_links,
        warnings=[
            "Graph edges are bounded and evidence-labelled.",
            "Correlation is not converted to causation.",
            *(
                ["A graph cycle was detected and requires human review."]
                if cycles
                else []
            ),
        ],
    )


def _handoff_priority(
    case: BobaDiagnosticCaseV1,
    candidate: BobaRootCauseCandidateV1 | None,
) -> BobaRootCausePriorityV1:
    return _priority(
        candidate.likelihood_score if candidate else 0.3,
        case.processing_impact,
    )


def build_root_cause_handoffs(
    case: BobaDiagnosticCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    evidence_gaps: Sequence[BobaEvidenceGapV1],
    plans: Sequence[BobaRootCauseVerificationPlanV1],
    impact: BobaWorkflowImpactAnalysisV1,
) -> list[BobaRootCauseEscalationHandoffV1]:
    """Build advisory handoffs without invoking any downstream module."""

    result: list[BobaRootCauseEscalationHandoffV1] = []
    seen: set[BobaRootCauseHandoffTargetV1] = set()
    top = candidates[0] if candidates else None
    candidate_ids = [item.root_cause_candidate_id for item in candidates[:8]]
    evidence_ids = _unique(
        [
            evidence_id
            for candidate in candidates[:8]
            for evidence_id in candidate.supporting_evidence_ids
        ],
        limit=64,
        maximum=160,
    )
    unresolved = _unique(
        [item.missing_information for item in evidence_gaps],
        limit=32,
    )

    def add(
        target: BobaRootCauseHandoffTargetV1,
        reason: str,
        *,
        required_inputs: Sequence[str],
        allowed_actions: Sequence[str],
        warnings: Sequence[str] = (),
    ) -> None:
        if target in seen or len(result) >= 16:
            return
        seen.add(target)
        result.append(
            BobaRootCauseEscalationHandoffV1(
                handoff_id=_stable_id(
                    "root_cause_handoff",
                    case.diagnostic_case_id,
                    target,
                ),
                analysis_case_id=_stable_id(
                    "root_analysis_case",
                    case.diagnostic_case_id,
                ),
                root_cause_candidate_ids=candidate_ids,
                target_module=target,
                reason=_safe_text(reason),
                evidence_ids=evidence_ids,
                unresolved_questions=unresolved,
                required_inputs=_unique(required_inputs, limit=32),
                blocked_actions=[
                    "Automatic repair or artifact modification",
                    "Command, validator, or fallback-tool execution by Root Cause Analyzer",
                    "Automatic workflow resume",
                    "Destructive action or safety/rights bypass",
                ],
                allowed_advisory_actions=_unique(allowed_actions, limit=32),
                apply_automatically=False,
                human_approval_required=True,
                priority=_handoff_priority(case, top),
                warnings=_unique(
                    [
                        *warnings,
                        "The target module was not invoked.",
                        "Human approval is required before verification or repair.",
                    ],
                    limit=24,
                ),
            )
        )

    categories = {item.category for item in candidates}
    if categories & {
        "tool_unavailable",
        "tool_failure",
        "timeout",
        "resource_exhaustion",
        "external_service",
    }:
        failing = next(
            (
                item
                for item in candidates
                if item.category
                in {
                    "tool_unavailable",
                    "tool_failure",
                    "timeout",
                    "resource_exhaustion",
                    "external_service",
                }
            ),
            top,
        )
        add(
            "tool_recovery_brain",
            "A tool capability is unavailable or failed and needs future "
            "recovery-strategy analysis.",
            required_inputs=[
                f"Required capability: {case.primary_module or case.workflow_stage}",
                f"Failing tool or stage: {case.primary_module or 'unknown'}",
                f"Observed failure class: {failing.category if failing else 'unknown'}",
                "Required output properties: compatible, valid, bounded, and deterministic",
                "Quality requirements: preserve workflow correctness and validation truth",
                "Safety constraints: no unapproved download, install, external call, or bypass",
                "Attempted strategies: only those explicitly present in saved evidence",
                "Prohibited recovery methods: unsafe, destructive, rights-bypassing, or hidden",
                "Evidence still needed: tool availability, version, bounded failure output",
            ],
            allowed_actions=[
                "Compare compatible recovery strategies later.",
                "Prepare a human-reviewed fallback proposal later.",
            ],
            warnings=["No fallback tool was selected or executed."],
        )
    if categories & {"validation_failure", "validation_gap"} or any(
        plan.requires_validator_execution for plan in plans
    ):
        add(
            "validator_runner",
            "A future approved validator may be needed to confirm or reject a candidate.",
            required_inputs=[
                "Approved validator identity",
                "Bounded target artifact reference",
                "Expected pass/fail contract",
            ],
            allowed_actions=[
                "Review the verification plan.",
                "Run an approved validator only after separate human authorization.",
            ],
            warnings=["Root Cause Analyzer ran no validator."],
        )
        add(
            "report_reader",
            "Saved validation evidence may need bounded structured interpretation.",
            required_inputs=[
                "Saved validation report reference",
                "Expected schema and status fields",
            ],
            allowed_actions=["Read and summarize an approved saved report later."],
        )
    if categories & {
        "missing_artifact",
        "corrupt_artifact",
        "stale_artifact",
        "schema_mismatch",
        "dependency_order",
        "checkpoint_failure",
        "storage",
    }:
        add(
            "artifact_inspector",
            "Artifact state or dependency structure requires deeper read-only inspection.",
            required_inputs=[
                "Bounded artifact identifier",
                "Expected schema/version",
                "Registered upstream dependencies",
            ],
            allowed_actions=[
                "Inspect an approved saved artifact read-only.",
                "Compare schema and dependency metadata.",
            ],
        )
    if categories & {
        "intentional_safety_block",
        "rights_safety",
        "permission",
    } or case.safety_impact == "rights_gate_blocked":
        add(
            "rights_permission_gate",
            "Rights or permission evidence is missing, blocked, or requires human review.",
            required_inputs=[
                "Human-reviewed rights or permission evidence",
                "Source identity and allowed processing scope",
            ],
            allowed_actions=[
                "Review rights evidence.",
                "Keep processing blocked until an approved decision exists.",
            ],
            warnings=["An intentional rights block is not classified as a code defect."],
        )
    if (
        case.safety_impact
        in {"safety_gate_blocked", "destructive_risk", "rights_gate_blocked"}
        or impact.unsafe_next_actions
    ):
        add(
            "safety_gate",
            "Unsafe next actions must remain blocked until a future safety review.",
            required_inputs=[
                "Proposed verification or repair action",
                "Known safety constraints",
                "Human approval record",
            ],
            allowed_actions=["Review whether a future proposal is permitted."],
            warnings=["Root Cause Analyzer did not bypass or invoke Safety Gate."],
        )
    supported = [
        item
        for item in candidates
        if item.likelihood_score >= 0.6
        and item.evidence_quality in {"strong", "moderate"}
        and item.category
        not in {
            "intentional_safety_block",
            "rights_safety",
            "permission",
            "validation_gap",
        }
    ]
    if supported:
        add(
            "repair_planner",
            "One or more candidates have enough support for future, human-reviewed "
            "repair-option planning.",
            required_inputs=[
                "Ranked supported root-cause candidates",
                "Conflicting evidence and evidence gaps",
                "Verification requirements and safety constraints",
            ],
            allowed_actions=[
                "Prepare non-applying repair options later.",
                "Preserve rollback and validation requirements.",
            ],
            warnings=["No repair plan or repair was produced by this analyzer."],
        )
    code_candidates = [
        item
        for item in candidates
        if item.category == "code_defect"
        and item.confidence >= 0.72
        and item.evidence_quality in {"strong", "moderate"}
    ]
    simpler = [
        item
        for item in candidates
        if item.category != "code_defect"
        and item.likelihood_score >= (
            code_candidates[0].likelihood_score - 0.05
            if code_candidates
            else 0.0
        )
    ]
    if code_candidates and not simpler:
        add(
            "code_surgeon",
            "A probable code defect remains after simpler supported causes were "
            "reasonably excluded.",
            required_inputs=[
                "Human-approved repair plan",
                "Direct code-defect evidence",
                "Rollback and validation plan",
            ],
            allowed_actions=[
                "Review an approved repair plan later.",
                "Prepare a patch only in a future explicitly approved workflow.",
            ],
            warnings=["No patch was generated and no code was modified."],
        )
    if impact.blocked_stages:
        add(
            "workflow_controller",
            "Blocked stages may be reconsidered only after verification and gate approval.",
            required_inputs=[
                "Verified root-cause state",
                "Resolved safety/rights decisions",
                "Human approval",
            ],
            allowed_actions=["Evaluate pause/resume state later."],
            warnings=["Root Cause Analyzer did not authorize resume."],
        )
    if (
        not result
        or len(candidates) > 1
        or any(item.conflicting_evidence_ids for item in candidates)
        or case.safety_impact != "none_known"
    ):
        add(
            "human_operator",
            "Human judgment is required for uncertainty, safety, configuration, or "
            "production-impact decisions.",
            required_inputs=[
                "Ranked candidates",
                "Confirmed facts and contradictory evidence",
                "Evidence gaps and verification plans",
            ],
            allowed_actions=[
                "Choose whether to request a future verification.",
                "Approve or reject a future repair-planning handoff.",
            ],
        )
    priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    result.sort(
        key=lambda item: (
            priority_rank[item.priority],
            item.target_module,
            item.handoff_id,
        )
    )
    return result


def _analysis_status(
    case: BobaDiagnosticCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
) -> BobaRootCauseAnalysisStatusV1:
    if (
        case.safety_impact in {"rights_gate_blocked", "safety_gate_blocked"}
        or (
            candidates
            and candidates[0].category
            in {
                "intentional_safety_block",
                "rights_safety",
                "permission",
            }
        )
    ):
        return "intentional_safety_block"
    if not candidates:
        return "insufficient_evidence"
    if case.severity == "informational" and case.processing_impact == "none":
        return "no_defect_detected"
    if any(item.conflicting_evidence_ids for item in candidates):
        if len(candidates) > 1:
            return "multiple_competing_causes"
        return "conflicting_evidence"
    if len(candidates) > 1 and (
        candidates[0].likelihood_score - candidates[1].likelihood_score <= 0.08
    ):
        return "multiple_competing_causes"
    top = candidates[0]
    if (
        top.evidence_quality == "strong"
        and top.confidence >= 0.8
        and case.diagnosis_status == "observed_fact"
    ):
        return "root_cause_supported"
    if top.likelihood_score >= 0.48:
        return "probable_root_cause"
    if case.diagnosis_status in {"possible", "unknown", "insufficient_evidence"}:
        return "insufficient_evidence"
    if top.evidence_quality in {"weak", "insufficient"}:
        return "insufficient_evidence"
    return "unknown"


def _recommended_handoff(
    handoffs: Sequence[BobaRootCauseEscalationHandoffV1],
) -> BobaRootCauseHandoffTargetV1:
    return handoffs[0].target_module if handoffs else "human_operator"


def _analysis_case(
    case: BobaDiagnosticCaseV1,
    timeline: BobaFailureTimelineV1,
    graph: BobaCausalGraphV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    factors: Sequence[BobaContributingFactorV1],
    symptoms: Sequence[BobaDownstreamSymptomV1],
    gaps: Sequence[BobaEvidenceGapV1],
    plans: Sequence[BobaRootCauseVerificationPlanV1],
    handoffs: Sequence[BobaRootCauseEscalationHandoffV1],
) -> BobaRootCauseAnalysisCaseV1:
    top = candidates[0] if candidates else None
    first_failure = next(
        (
            event
            for event in timeline.events
            if event.event_id
            == (
                timeline.first_confirmed_failure_event_id
                or timeline.first_failure_event_id
                or timeline.earliest_event_id
            )
        ),
        None,
    )
    earliest = (
        f"{first_failure.observed_at or 'time unavailable'} — "
        f"{first_failure.event_summary}"
        if first_failure
        else "No reliable timestamped failure is available."
    )
    probable = _unique(
        [
            candidate.candidate_summary
            for candidate in candidates
            if candidate.evidence_quality in {"strong", "moderate"}
        ],
        limit=32,
    )
    hypotheses = _unique(
        [
            candidate.candidate_summary
            for candidate in candidates
            if candidate.evidence_quality in {"weak", "insufficient", "conflicting"}
        ],
        limit=32,
    )
    return BobaRootCauseAnalysisCaseV1(
        analysis_case_id=_stable_id(
            "root_analysis_case",
            case.diagnostic_case_id,
        ),
        source_diagnostic_case_id=case.diagnostic_case_id,
        title=_safe_text(case.title, maximum=240),
        primary_module=case.primary_module,
        primary_artifact=case.primary_artifact,
        workflow_stage=case.workflow_stage,
        analysis_status=_analysis_status(case, candidates),
        earliest_known_failure=_safe_text(earliest),
        most_likely_root_cause=(
            f"Highest-ranked candidate: {top.candidate_summary}"
            if top
            else "No evidence-supported root-cause candidate is available."
        ),
        root_cause_confidence=top.confidence if top else 0.0,
        confirmed_facts=_unique(case.confirmed_facts, limit=32),
        probable_inferences=probable,
        unresolved_hypotheses=hypotheses,
        contributing_factor_ids=[
            item.contributing_factor_id for item in factors
        ],
        downstream_symptom_ids=[
            item.downstream_symptom_id for item in symptoms
        ],
        affected_modules=_unique(case.affected_modules, limit=64, maximum=120),
        affected_artifacts=_unique(
            case.affected_artifacts,
            limit=64,
            maximum=120,
        ),
        failure_timeline_id=timeline.timeline_id,
        causal_graph_id=graph.causal_graph_id,
        evidence_gap_ids=[item.evidence_gap_id for item in gaps],
        verification_plan_ids=[item.verification_plan_id for item in plans],
        processing_impact=case.processing_impact,
        safety_impact=case.safety_impact,
        recommended_handoff=_recommended_handoff(handoffs),
        human_review_required=True,
        warnings=[
            "Earliest known failure is not automatically the root cause.",
            "The highest-ranked candidate may still be rejected by later evidence.",
        ],
        limitations=[
            "Analysis is bounded to saved Error Doctor evidence and known BOBA chains.",
            "No verification, repair, fallback, or workflow-resume action was executed.",
        ],
    )


def _summary(
    diagnostic_cases: Sequence[BobaDiagnosticCaseV1],
    analysis_cases: Sequence[BobaRootCauseAnalysisCaseV1],
    candidates: Sequence[BobaRootCauseCandidateV1],
    gaps: Sequence[BobaEvidenceGapV1],
    plans: Sequence[BobaRootCauseVerificationPlanV1],
    impacts: Sequence[BobaWorkflowImpactAnalysisV1],
    handoffs: Sequence[BobaRootCauseEscalationHandoffV1],
) -> BobaRootCauseAnalyzerSummaryV1:
    strongest = max(
        candidates,
        key=lambda item: (item.likelihood_score, item.confidence),
        default=None,
    )
    weakest = next(
        (
            candidate
            for candidate in sorted(
                candidates,
                key=lambda item: (item.confidence, item.likelihood_score),
            )
            if candidate.evidence_quality
            in {"insufficient", "weak", "conflicting", "unknown"}
        ),
        None,
    )
    safest_check = next(
        (
            check.description
            for plan in plans
            for check in plan.checks
            if check.safe and check.read_only
        ),
        "Generate or inspect a saved Error Doctor report manually.",
    )
    highest_handoff = handoffs[0] if handoffs else None
    return BobaRootCauseAnalyzerSummaryV1(
        total_diagnostic_cases=len(diagnostic_cases),
        total_analysis_cases=len(analysis_cases),
        supported_root_cause_count=sum(
            item.analysis_status == "root_cause_supported"
            for item in analysis_cases
        ),
        probable_root_cause_count=sum(
            item.analysis_status == "probable_root_cause"
            for item in analysis_cases
        ),
        competing_cause_count=sum(
            item.analysis_status
            in {"multiple_competing_causes", "conflicting_evidence"}
            for item in analysis_cases
        ),
        insufficient_evidence_count=sum(
            item.analysis_status == "insufficient_evidence"
            for item in analysis_cases
        ),
        intentional_safety_block_count=sum(
            item.analysis_status == "intentional_safety_block"
            for item in analysis_cases
        ),
        critical_case_count=sum(
            item.severity in {"critical", "blocker"}
            for item in diagnostic_cases
        ),
        blocked_workflow_count=len(
            {
                stage
                for impact in impacts
                for stage in impact.blocked_stages
            }
        ),
        strongest_root_cause_candidate=(
            f"{strongest.title} "
            f"(likelihood {strongest.likelihood_score:.2f}, "
            f"confidence {strongest.confidence:.2f}; not automatically proven)"
            if strongest
            else "No evidence-supported root-cause candidate is available."
        ),
        weakest_evidence_area=(
            weakest.title
            if weakest
            else gaps[0].missing_information
            if gaps
            else "No specific weak evidence area was identified."
        ),
        safest_next_verification=_safe_text(safest_check),
        highest_priority_handoff=(
            f"{highest_handoff.target_module}: {highest_handoff.reason}"
            if highest_handoff
            else "human_operator: review the insufficient evidence."
        ),
        unresolved_questions=_unique(
            [item.missing_information for item in gaps],
            limit=64,
        ),
        human_review_notes=[
            "BOBA Root Cause Analyzer V1 ranks evidence-supported causes but "
            "does not guarantee that the highest-ranked candidate is proven.",
            "It does not repair files, edit code, run commands, run validators, "
            "or activate fallback tools.",
            "Human approval is required before verification or repair actions.",
        ],
    )


def _insufficient_report(
    project_id: str,
    *,
    source_id: str,
    error_doctor_source: str,
    warnings: Sequence[str],
    manual_context_supplied: bool,
) -> BobaRootCauseAnalyzerSetV1:
    analysis_case_id = _stable_id(
        "root_analysis_case",
        project_id,
        "error_doctor_unavailable",
    )
    gap = BobaEvidenceGapV1(
        evidence_gap_id=_stable_id(
            "root_evidence_gap",
            analysis_case_id,
            "saved_error_doctor",
        ),
        analysis_case_id=analysis_case_id,
        missing_information="A usable saved BOBA Error Doctor V1 report.",
        why_needed=(
            "Root Cause Analyzer cannot construct evidence-supported causes without "
            "the upstream diagnostic artifact."
        ),
        affected_candidate_ids=[],
        collection_method="inspect_saved_artifact",
        requires_command_execution=False,
        requires_validator=False,
        requires_external_access=False,
        requires_human_review=True,
        safe_to_collect=True,
        priority="high",
        warnings=["No diagnostic case or root cause was fabricated."],
    )
    check = BobaRootCauseVerificationCheckV1(
        check_id=_stable_id(
            "root_verification_check",
            analysis_case_id,
            "generate_error_doctor",
        ),
        order=1,
        check_type="inspect_artifact",
        description=(
            "Generate or locate BOBA Error Doctor V1 manually through its approved API "
            "or UI, then rerun Root Cause Analyzer."
        ),
        prerequisite="Human chooses the approved Error Doctor workflow.",
        expected_information_gain="Provides the required bounded diagnostic evidence.",
        safe=True,
        read_only=True,
        requires_human_review=True,
        warnings=["Root Cause Analyzer did not generate Error Doctor automatically."],
    )
    plan = BobaRootCauseVerificationPlanV1(
        verification_plan_id=_stable_id(
            "root_verification_plan",
            analysis_case_id,
            "collect_error_doctor",
        ),
        analysis_case_id=analysis_case_id,
        objective="Obtain the missing saved Error Doctor report.",
        checks=[check],
        expected_confirmation_evidence=[
            "A valid boba_error_doctor_v1 artifact with diagnostic cases."
        ],
        expected_rejection_evidence=[
            "The report remains unavailable or cannot be parsed safely."
        ],
        safe=True,
        read_only=True,
        requires_command_execution=False,
        requires_validator_execution=False,
        requires_code_modification=False,
        requires_external_access=False,
        requires_human_approval=True,
        stop_conditions=[
            "Stop if generating Error Doctor is unavailable or unsafe.",
        ],
        rollback_requirement="No rollback is required for read-only artifact inspection.",
        suggested_owner_module="error_doctor",
        priority="high",
        warnings=["The plan was not executed."],
    )
    handoff = BobaRootCauseEscalationHandoffV1(
        handoff_id=_stable_id(
            "root_cause_handoff",
            analysis_case_id,
            "human_operator",
        ),
        analysis_case_id=analysis_case_id,
        root_cause_candidate_ids=[],
        target_module="human_operator",
        reason="A human must generate or locate the missing Error Doctor report.",
        evidence_ids=[],
        unresolved_questions=[gap.missing_information],
        required_inputs=["Saved BOBA Error Doctor V1 report"],
        blocked_actions=[
            "Root-cause claims",
            "Automatic verification, repair, fallback, or workflow resume",
        ],
        allowed_advisory_actions=[
            "Generate Error Doctor through its approved API or UI.",
            "Inspect whether its saved artifact is available.",
        ],
        apply_automatically=False,
        human_approval_required=True,
        priority="high",
        warnings=["No future module was invoked."],
    )
    case = BobaRootCauseAnalysisCaseV1(
        analysis_case_id=analysis_case_id,
        source_diagnostic_case_id="error_doctor_unavailable",
        title="Error Doctor evidence is unavailable",
        primary_module="error_doctor",
        primary_artifact="error_doctor",
        workflow_stage="self_healing",
        analysis_status="insufficient_evidence",
        earliest_known_failure=(
            "No diagnostic failure timeline can be reconstructed without Error Doctor."
        ),
        most_likely_root_cause=(
            "No root-cause candidate was generated because evidence is unavailable."
        ),
        root_cause_confidence=0.0,
        confirmed_facts=[
            "No usable saved BOBA Error Doctor V1 report was supplied."
        ],
        probable_inferences=[],
        unresolved_hypotheses=[],
        contributing_factor_ids=[],
        downstream_symptom_ids=[],
        affected_modules=["error_doctor", "root_cause_analyzer"],
        affected_artifacts=["error_doctor"],
        failure_timeline_id="",
        causal_graph_id="",
        evidence_gap_ids=[gap.evidence_gap_id],
        verification_plan_ids=[plan.verification_plan_id],
        processing_impact="degraded",
        safety_impact="human_review_needed",
        recommended_handoff="human_operator",
        human_review_required=True,
        warnings=["No diagnostic cases or root causes were fabricated."],
        limitations=["Causal analysis requires a saved Error Doctor report."],
    )
    summary = _summary(
        [],
        [case],
        [],
        [gap],
        [plan],
        [],
        [handoff],
    )
    return BobaRootCauseAnalyzerSetV1(
        project_id=project_id,
        source_id=source_id,
        error_doctor_source=error_doctor_source,
        analysis_cases=[case],
        failure_timelines=[],
        causal_graphs=[],
        root_cause_candidates=[],
        contributing_factors=[],
        downstream_symptoms=[],
        evidence=[],
        evidence_gaps=[gap],
        verification_plans=[plan],
        workflow_impacts=[],
        escalation_handoffs=[handoff],
        analyzer_summary=summary,
        signal_usage=BobaRootCauseSignalUsageV1(
            error_doctor_used=False,
            error_doctor_artifact_read=False,
            bounded_manual_context_used=False,
            fallback_used=True,
            unavailable_signals=["error_doctor_report"],
            warnings=[
                "Root Cause Analyzer did not run Error Doctor or Observer.",
                *(
                    [
                        "Supplied manual context was not used to fabricate "
                        "missing diagnostic evidence."
                    ]
                    if manual_context_supplied
                    else []
                ),
            ],
        ),
        warnings=_unique(warnings, limit=64),
        limitations=[
            "No causal analysis was fabricated without Error Doctor evidence.",
            "No commands, validators, code changes, repairs, fallbacks, network "
            "calls, media operations, or destructive actions occurred.",
        ],
    )


class BobaRootCauseAnalyzerV1:
    """Analyze saved diagnoses without executing verification or repair."""

    def __init__(
        self,
        *,
        registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
    ) -> None:
        self.registry = tuple(registry or build_boba_artifact_registry())

    def analyze(
        self,
        project_id: str,
        error_doctor: BobaErrorDoctorSetV1 | Mapping[str, Any] | None,
        *,
        source_id: str | None = None,
        manual_context: Mapping[str, Any] | None = None,
        dry_run: bool = False,
    ) -> BobaRootCauseAnalyzerSetV1:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError(
                "Invalid BOBA Root Cause Analyzer project id.",
                details={"project_id": project_id},
            )
        source = _safe_text(source_id or project_id, maximum=512) or project_id
        report, compatibility_warnings = _coerce_error_doctor(error_doctor)
        if report is None:
            return _insufficient_report(
                project_id,
                source_id=source,
                error_doctor_source=(
                    "malformed_error_doctor_v1"
                    if isinstance(error_doctor, Mapping)
                    else "missing_error_doctor_v1"
                ),
                warnings=[
                    *compatibility_warnings,
                    (
                        "Saved BOBA Error Doctor V1 report is malformed."
                        if isinstance(error_doctor, Mapping)
                        else "Saved BOBA Error Doctor V1 report is unavailable."
                    ),
                    "Root Cause Analyzer did not regenerate Error Doctor or Observer.",
                ],
                manual_context_supplied=bool(manual_context),
            )
        if not report.diagnostic_cases:
            return _insufficient_report(
                project_id,
                source_id=source,
                error_doctor_source="saved_error_doctor_v1_empty",
                warnings=[
                    "Saved Error Doctor report contains no diagnostic cases.",
                    "Root Cause Analyzer did not fabricate project failures.",
                ],
                manual_context_supplied=bool(manual_context),
            )
        all_analysis_cases: list[BobaRootCauseAnalysisCaseV1] = []
        all_timelines: list[BobaFailureTimelineV1] = []
        all_graphs: list[BobaCausalGraphV1] = []
        all_candidates: list[BobaRootCauseCandidateV1] = []
        all_factors: list[BobaContributingFactorV1] = []
        all_symptoms: list[BobaDownstreamSymptomV1] = []
        all_evidence: list[BobaRootCauseEvidenceV1] = []
        all_gaps: list[BobaEvidenceGapV1] = []
        all_plans: list[BobaRootCauseVerificationPlanV1] = []
        all_impacts: list[BobaWorkflowImpactAnalysisV1] = []
        all_handoffs: list[BobaRootCauseEscalationHandoffV1] = []
        for case in report.diagnostic_cases[:256]:
            evidence = normalize_error_doctor_case(
                case,
                manual_context=manual_context,
            )
            timeline = build_failure_timeline(
                case,
                evidence,
                manual_context=manual_context,
            )
            symptoms = identify_downstream_symptoms(case, report)
            candidates = generate_root_cause_candidates(
                case,
                evidence,
                symptoms,
                timeline,
                manual_context=manual_context,
            )
            factors = identify_contributing_factors(
                case,
                candidates,
                evidence,
            )
            gaps = identify_evidence_gaps(case, candidates, timeline)
            plans = build_verification_plans(case, candidates)
            impact = build_workflow_impact(case, report, self.registry)
            graph = build_causal_graph(
                case,
                candidates,
                factors,
                symptoms,
                impact,
                evidence=evidence,
                manual_context=manual_context,
            )
            handoffs = build_root_cause_handoffs(
                case,
                candidates,
                gaps,
                plans,
                impact,
            )
            analysis_case = _analysis_case(
                case,
                timeline,
                graph,
                candidates,
                factors,
                symptoms,
                gaps,
                plans,
                handoffs,
            )
            all_analysis_cases.append(analysis_case)
            all_timelines.append(timeline)
            all_graphs.append(graph)
            all_candidates.extend(candidates)
            all_factors.extend(factors)
            all_symptoms.extend(symptoms)
            all_evidence.extend(evidence)
            all_gaps.extend(gaps)
            all_plans.extend(plans)
            all_impacts.append(impact)
            all_handoffs.extend(handoffs)
        all_candidates.sort(
            key=lambda item: (
                -item.likelihood_score,
                -item.confidence,
                _CATEGORY_COMPLEXITY[item.category],
                item.root_cause_candidate_id,
            )
        )
        priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        all_handoffs.sort(
            key=lambda item: (
                priority_rank[item.priority],
                item.target_module,
                item.handoff_id,
            )
        )
        summary = _summary(
            report.diagnostic_cases,
            all_analysis_cases,
            all_candidates,
            all_gaps,
            all_plans,
            all_impacts,
            all_handoffs,
        )
        evidence_sources = {item.source_type for item in all_evidence}
        warnings = [
            "BOBA Root Cause Analyzer V1 uses saved Error Doctor evidence only.",
            "The highest-ranked candidate is not guaranteed to be a proven root cause.",
            "Earliest known failure is not automatically the root cause.",
            "Human approval is required before verification or repair actions.",
            "Root Cause Analyzer did not repair files, edit code, run commands, "
            "run validators, install tools, restart services, activate fallback "
            "tools, fetch URLs, call external APIs, download media, ingest media, "
            "render, bypass gates, or authorize workflow resume.",
            *compatibility_warnings,
        ]
        if report.project_id != project_id:
            warnings.append(
                "Saved Error Doctor project id differed from the requested project id; "
                "the requested id remained authoritative."
            )
        if dry_run:
            warnings.append(
                "Dry run: the Root Cause Analyzer artifact was not persisted."
            )
        return BobaRootCauseAnalyzerSetV1(
            project_id=project_id,
            source_id=source,
            error_doctor_source="saved_error_doctor_v1",
            analysis_cases=all_analysis_cases,
            failure_timelines=all_timelines,
            causal_graphs=all_graphs,
            root_cause_candidates=all_candidates,
            contributing_factors=all_factors,
            downstream_symptoms=all_symptoms,
            evidence=list(
                {
                    item.evidence_id: item
                    for item in all_evidence
                }.values()
            ),
            evidence_gaps=all_gaps,
            verification_plans=all_plans,
            workflow_impacts=all_impacts,
            escalation_handoffs=all_handoffs,
            analyzer_summary=summary,
            signal_usage=BobaRootCauseSignalUsageV1(
                error_doctor_used=True,
                error_doctor_artifact_read=True,
                observer_references_used=bool(
                    evidence_sources
                    & {
                        "observer_finding",
                        "artifact_observation",
                        "dependency_observation",
                        "validation_observation",
                        "safety_observation",
                    }
                ),
                validation_evidence_used=(
                    "validation_observation" in evidence_sources
                ),
                dependency_evidence_used=(
                    "dependency_observation" in evidence_sources
                ),
                safety_evidence_used=(
                    "safety_observation" in evidence_sources
                    or any(
                        item.analysis_status == "intentional_safety_block"
                        for item in all_analysis_cases
                    )
                ),
                bounded_manual_context_used=bool(manual_context),
                raw_logs_read=False,
                external_api_used=False,
                url_fetching_used=False,
                scraping_used=False,
                downloading_used=False,
                command_execution_used=False,
                validator_execution_used=False,
                code_modification_used=False,
                artifact_modification_used=False,
                repair_execution_used=False,
                tool_fallback_execution_used=False,
                destructive_action_used=False,
                fallback_used=bool(
                    compatibility_warnings
                    or manual_context
                    or report.signal_usage.fallback_used
                ),
                unavailable_signals=_unique(
                    [
                        *report.signal_usage.unavailable_signals,
                        *(
                            ["complete_failure_timestamps"]
                            if any(
                                timeline.missing_time_information
                                for timeline in all_timelines
                            )
                            else []
                        ),
                    ],
                    limit=64,
                    maximum=160,
                ),
                warnings=[
                    "Bounded manual context is unverified and is not a complete log."
                    if manual_context
                    else "",
                    "No verification, repair, fallback, or destructive action was executed.",
                ],
            ),
            warnings=_unique(warnings, limit=64),
            limitations=[
                "V1 uses bounded saved Error Doctor evidence and known BOBA dependencies.",
                "Sparse or conflicting timestamps limit causal ordering confidence.",
                "Candidate ranking preserves uncertainty and contradictory evidence.",
                "V1 does not inspect source code, full logs, complete artifacts, media, "
                "secrets, credentials, or tokens.",
                "V1 does not invoke Repair Planner, Tool Recovery Brain, Validator "
                "Runner, Artifact Inspector, Report Reader, Safety Gate, Rights Gate, "
                "Workflow Controller, Code Surgeon, or a human operator.",
                "V1 does not claim production readiness.",
            ],
        )


def generate_boba_root_cause_analyzer(
    project_id: str,
    error_doctor: BobaErrorDoctorSetV1 | Mapping[str, Any] | None,
    **kwargs: Any,
) -> BobaRootCauseAnalyzerSetV1:
    """Convenience wrapper for deterministic local causal analysis."""

    return BobaRootCauseAnalyzerV1().analyze(
        project_id,
        error_doctor,
        **kwargs,
    )

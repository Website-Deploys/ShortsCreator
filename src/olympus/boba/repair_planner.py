"""Deterministic advisory repair planning from saved Root Cause Analyzer reports."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, Literal, TypeAlias

from pydantic import Field
from pydantic import ValidationError as PydanticValidationError

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.observer import (
    BobaArtifactRegistryEntryV1,
    build_boba_artifact_registry,
)
from olympus.boba.root_cause_analyzer import (
    BobaRootCauseAnalysisCaseV1,
    BobaRootCauseAnalyzerSetV1,
    BobaRootCauseCandidateV1,
    BobaWorkflowImpactAnalysisV1,
)
from olympus.platform.errors import ValidationError

BobaRepairPlanningStatusV1 = Literal[
    "plan_ready",
    "conditional_plan",
    "needs_more_evidence",
    "conflicting_causes",
    "intentional_safety_block",
    "human_decision_required",
    "repair_not_required",
    "blocked",
    "unknown",
]
BobaRepairScopeV1 = Literal[
    "no_repair",
    "artifact",
    "checkpoint",
    "workflow",
    "configuration",
    "environment",
    "tool",
    "dependency",
    "data_input",
    "validation",
    "rendering",
    "code",
    "rights_permission",
    "human_decision",
    "unknown",
]
BobaRepairStrategyTypeV1 = Literal[
    "no_action",
    "collect_more_evidence",
    "regenerate_artifact",
    "restore_checkpoint",
    "resume_from_checkpoint",
    "retry_same_tool",
    "retry_with_safe_settings",
    "reduce_resource_usage",
    "use_registered_tool_fallback",
    "switch_safe_workflow_path",
    "repair_generated_state",
    "repair_configuration",
    "repair_environment",
    "replace_invalid_input",
    "rerun_validation",
    "isolate_failure",
    "propose_code_patch",
    "seek_permission",
    "human_manual_action",
    "stop_processing",
    "unknown",
]
BobaRepairStepTypeV1 = Literal[
    "inspect",
    "backup",
    "checkpoint",
    "collect_evidence",
    "validate_precondition",
    "regenerate",
    "retry",
    "adjust_safe_setting",
    "switch_tool",
    "switch_workflow",
    "restore",
    "configure",
    "install_dependency",
    "restart_service",
    "propose_patch",
    "apply_patch",
    "validate_result",
    "compare_quality",
    "resume_workflow",
    "stop",
    "human_review",
    "unknown",
]
BobaRepairReversibilityV1 = Literal[
    "fully_reversible",
    "mostly_reversible",
    "partially_reversible",
    "difficult_to_reverse",
    "irreversible",
    "unknown",
]
BobaRepairDestructivenessV1 = Literal[
    "none",
    "low",
    "medium",
    "high",
    "blocked",
    "unknown",
]
BobaRepairAutomationEligibilityV1 = Literal[
    "safe_advisory_only",
    "potentially_automatable_after_approval",
    "human_execution_required",
    "blocked",
    "unknown",
]
BobaRepairRiskLevelV1 = Literal[
    "minimal",
    "low",
    "medium",
    "high",
    "critical",
    "blocked",
    "unknown",
]
BobaRepairComplexityV1 = Literal[
    "minimal",
    "low",
    "medium",
    "high",
    "very_high",
    "unknown",
]
BobaRepairCheckpointTypeV1 = Literal[
    "none",
    "artifact_snapshot",
    "generated_state_snapshot",
    "workflow_checkpoint",
    "configuration_snapshot",
    "repository_branch",
    "database_backup",
    "media_reference_only",
    "unknown",
]
BobaRepairRollbackScopeV1 = Literal[
    "none",
    "artifact",
    "workflow",
    "configuration",
    "environment",
    "tool_selection",
    "code_branch",
    "database",
    "unknown",
]
BobaRepairValidationPhaseV1 = Literal[
    "pre_repair",
    "during_repair",
    "post_repair",
    "rollback",
    "resume",
    "unknown",
]
BobaRepairValidationCategoryV1 = Literal[
    "artifact_integrity",
    "schema",
    "dependency",
    "checkpoint",
    "rendering",
    "audio_video_sync",
    "media_probe",
    "captions",
    "framing",
    "output_quality",
    "performance",
    "resource_usage",
    "safety",
    "rights_permission",
    "regression",
    "workflow",
    "code_quality",
    "frontend",
    "api",
    "unknown",
]
BobaRepairApprovalStatusV1 = Literal[
    "planning_only",
    "awaiting_human_review",
    "blocked",
    "not_required_for_no_action",
    "unknown",
]
BobaRepairHandoffTargetV1 = Literal[
    "tool_recovery_brain",
    "code_surgeon",
    "validator_runner",
    "artifact_inspector",
    "report_reader",
    "safety_gate",
    "rights_permission_gate",
    "workflow_controller",
    "checkpoint_recovery_manager",
    "output_quality_reviewer",
    "human_operator",
    "unknown",
]
BobaRepairPriorityV1 = Literal["low", "medium", "high", "urgent"]

JsonObject: TypeAlias = dict[str, Any]

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SPACE = re.compile(r"\s+")
_WINDOWS_ABSOLUTE = re.compile(r"\b[A-Za-z]:[\\/][^\s;,]+")
_UNC_PATH = re.compile(r"\\\\[^\\\s]+\\[^\\\s]+(?:\\[^\s;,]+)*")
_UNIX_PRIVATE_PATH = re.compile(
    r"(?<![A-Za-z0-9])/(?:home|Users|root|var|tmp|private|opt)/[^\s;,]+"
)
_SECRET_KEY = re.compile(
    r"(?:secret|token|password|credential|cookie|authorization|api[_-]?key)",
    re.IGNORECASE,
)

_ROOT_CATEGORIES = {
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
}
_ROOT_REPAIRABILITY = {
    "likely_recoverable",
    "recoverable_with_approval",
    "requires_tool_fallback",
    "requires_code_change",
    "requires_configuration_change",
    "requires_human_decision",
    "not_a_defect",
    "blocked",
    "unknown",
}
_ROOT_EVIDENCE_QUALITY = {
    "strong",
    "moderate",
    "weak",
    "conflicting",
    "insufficient",
    "unknown",
}
_ROOT_ANALYSIS_STATUS = {
    "root_cause_supported",
    "probable_root_cause",
    "multiple_competing_causes",
    "insufficient_evidence",
    "conflicting_evidence",
    "intentional_safety_block",
    "no_defect_detected",
    "unknown",
}
_ROOT_PROCESSING_IMPACT = {
    "none",
    "degraded",
    "partial_block",
    "full_block",
    "unsafe_to_continue",
    "unknown",
}
_ROOT_SAFETY_IMPACT = {
    "none_known",
    "human_review_needed",
    "safety_gate_blocked",
    "rights_gate_blocked",
    "destructive_risk",
    "unknown",
}
_ROOT_HANDOFF_TARGETS = {
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
}

DEFAULT_VALIDATOR_REGISTRY: tuple[str, ...] = (
    "artifact_integrity",
    "artifact_schema",
    "dependency_integrity",
    "checkpoint_integrity",
    "ffprobe",
    "duration_validation",
    "audio_video_sync",
    "caption_timing",
    "framing",
    "output_quality",
    "rights_permission",
    "safety",
    "regression",
    "api",
    "frontend",
    "workflow",
)
DEFAULT_CHECKPOINT_REGISTRY: tuple[str, ...] = (
    "source",
    "analysis",
    "story",
    "virality",
    "planning",
    "editing",
    "rendering",
    "optimization",
)
DEFAULT_TOOL_CAPABILITY_REGISTRY: tuple[str, ...] = (
    "media_probe",
    "video_rendering",
    "audio_encoding",
    "artifact_validation",
    "checkpoint_validation",
)


class BobaRepairStepV1(BobaContract):
    repair_step_id: str = Field(min_length=1, max_length=160)
    repair_strategy_id: str = Field(min_length=1, max_length=160)
    order: int = Field(ge=1, le=64)
    step_type: BobaRepairStepTypeV1
    description: str = Field(min_length=1, max_length=700)
    target: str = Field(default="", max_length=180)
    read_only: bool = True
    reversible: bool = True
    requires_human_approval: Literal[True] = True
    requires_command_execution: bool = False
    requires_code_change: bool = False
    requires_external_access: bool = False
    safety_precondition: str = Field(min_length=1, max_length=700)
    success_condition: str = Field(min_length=1, max_length=700)
    failure_condition: str = Field(min_length=1, max_length=700)
    stop_condition: str = Field(min_length=1, max_length=700)
    rollback_step_reference: str = Field(default="", max_length=180)
    suggested_owner_module: str = Field(default="", max_length=160)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairStrategyV1(BobaContract):
    repair_strategy_id: str = Field(min_length=1, max_length=160)
    repair_case_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    strategy_type: BobaRepairStrategyTypeV1
    target_module: str = Field(default="", max_length=160)
    target_artifact: str = Field(default="", max_length=180)
    description: str = Field(min_length=1, max_length=700)
    rationale: str = Field(min_length=1, max_length=700)
    easy_explanation: str = Field(min_length=1, max_length=900)
    root_cause_candidate_ids: list[str] = Field(default_factory=list, max_length=24)
    prerequisites: list[str] = Field(default_factory=list, max_length=32)
    proposed_steps: list[BobaRepairStepV1] = Field(default_factory=list, max_length=32)
    expected_result: str = Field(min_length=1, max_length=700)
    expected_quality_effect: str = Field(min_length=1, max_length=700)
    expected_workflow_effect: str = Field(min_length=1, max_length=700)
    reversibility: BobaRepairReversibilityV1
    destructiveness: BobaRepairDestructivenessV1
    automation_eligibility: BobaRepairAutomationEligibilityV1
    human_approval_required: Literal[True] = True
    requires_checkpoint: bool = False
    requires_backup: bool = False
    requires_command_execution: bool = False
    requires_validator_execution: bool = False
    requires_code_change: bool = False
    requires_configuration_change: bool = False
    requires_tool_fallback: bool = False
    requires_service_restart: bool = False
    requires_package_installation: bool = False
    requires_external_access: bool = False
    requires_paid_service: bool = False
    requires_rights_review: bool = False
    estimated_risk: BobaRepairRiskLevelV1
    estimated_complexity: BobaRepairComplexityV1
    estimated_confidence: float = Field(ge=0.0, le=1.0)
    strategy_score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(default=0, ge=0, le=64)
    recommended: bool = False
    maximum_attempts: int | None = Field(default=None, ge=1, le=10)
    maximum_recovery_duration_seconds: int | None = Field(
        default=None,
        ge=1,
        le=86_400,
    )
    previously_attempted_strategies: list[str] = Field(
        default_factory=list,
        max_length=16,
    )
    escalation_condition: str = Field(default="", max_length=700)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=32)
    stop_conditions: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaRepairStrategyRiskV1(BobaContract):
    strategy_id: str = Field(min_length=1, max_length=160)
    risk_level: BobaRepairRiskLevelV1
    risk_reasons: list[str] = Field(default_factory=list, max_length=32)
    mitigations: list[str] = Field(default_factory=list, max_length=32)
    residual_risk: str = Field(min_length=1, max_length=700)
    acceptable_only_if: list[str] = Field(default_factory=list, max_length=32)
    blocked: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairRiskAssessmentV1(BobaContract):
    risk_assessment_id: str = Field(min_length=1, max_length=160)
    repair_case_id: str = Field(min_length=1, max_length=160)
    strategy_risks: list[BobaRepairStrategyRiskV1] = Field(
        default_factory=list,
        max_length=32,
    )
    overall_risk: BobaRepairRiskLevelV1
    source_data_risk: BobaRepairRiskLevelV1
    artifact_loss_risk: BobaRepairRiskLevelV1
    output_quality_risk: BobaRepairRiskLevelV1
    workflow_corruption_risk: BobaRepairRiskLevelV1
    configuration_risk: BobaRepairRiskLevelV1
    environment_risk: BobaRepairRiskLevelV1
    security_risk: BobaRepairRiskLevelV1
    rights_safety_risk: BobaRepairRiskLevelV1
    external_dependency_risk: BobaRepairRiskLevelV1
    rollback_failure_risk: BobaRepairRiskLevelV1
    human_error_risk: BobaRepairRiskLevelV1
    blockers: list[str] = Field(default_factory=list, max_length=32)
    mitigations: list[str] = Field(default_factory=list, max_length=32)
    residual_risks: list[str] = Field(default_factory=list, max_length=32)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairCheckpointPlanV1(BobaContract):
    checkpoint_plan_id: str = Field(min_length=1, max_length=160)
    repair_case_id: str = Field(min_length=1, max_length=160)
    checkpoint_required: bool
    checkpoint_type: BobaRepairCheckpointTypeV1
    artifacts_to_preserve: list[str] = Field(default_factory=list, max_length=64)
    state_to_preserve: list[str] = Field(default_factory=list, max_length=64)
    source_media_must_remain_untouched: Literal[True] = True
    checkpoint_validation_required: bool = True
    checkpoint_success_conditions: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    checkpoint_failure_conditions: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    storage_requirements: list[str] = Field(default_factory=list, max_length=32)
    retention_notes: list[str] = Field(default_factory=list, max_length=24)
    human_approval_required: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairRollbackPlanV1(BobaContract):
    rollback_plan_id: str = Field(min_length=1, max_length=160)
    repair_case_id: str = Field(min_length=1, max_length=160)
    rollback_required: bool
    rollback_scope: BobaRepairRollbackScopeV1
    rollback_trigger_conditions: list[str] = Field(default_factory=list, max_length=32)
    rollback_steps: list[str] = Field(default_factory=list, max_length=32)
    preserved_state_required: list[str] = Field(default_factory=list, max_length=32)
    rollback_validation: list[str] = Field(default_factory=list, max_length=32)
    rollback_owner_module: str = Field(default="", max_length=160)
    destructive_rollback_blocked: Literal[True] = True
    human_approval_required: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairValidationCheckV1(BobaContract):
    validation_check_id: str = Field(min_length=1, max_length=160)
    phase: BobaRepairValidationPhaseV1
    category: BobaRepairValidationCategoryV1
    description: str = Field(min_length=1, max_length=700)
    validator_name: str = Field(default="", max_length=160)
    expected_result: str = Field(min_length=1, max_length=700)
    required: bool = True
    blocks_acceptance_on_failure: bool = True
    requires_command_execution: bool = False
    requires_human_review: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairValidationPlanV1(BobaContract):
    validation_plan_id: str = Field(min_length=1, max_length=160)
    repair_case_id: str = Field(min_length=1, max_length=160)
    pre_repair_checks: list[BobaRepairValidationCheckV1] = Field(
        default_factory=list,
        max_length=32,
    )
    post_repair_checks: list[BobaRepairValidationCheckV1] = Field(
        default_factory=list,
        max_length=64,
    )
    required_validators: list[str] = Field(default_factory=list, max_length=32)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=32)
    rejection_criteria: list[str] = Field(default_factory=list, max_length=32)
    comparison_baseline: list[str] = Field(default_factory=list, max_length=32)
    regression_checks: list[str] = Field(default_factory=list, max_length=32)
    safety_checks: list[str] = Field(default_factory=list, max_length=32)
    rights_checks: list[str] = Field(default_factory=list, max_length=32)
    output_quality_checks: list[str] = Field(default_factory=list, max_length=32)
    workflow_resume_checks: list[str] = Field(default_factory=list, max_length=32)
    requires_validator_runner: bool = True
    requires_human_review: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaQualityPreservationPlanV1(BobaContract):
    quality_preservation_plan_id: str = Field(min_length=1, max_length=160)
    repair_case_id: str = Field(min_length=1, max_length=160)
    original_requirements: list[str] = Field(default_factory=list, max_length=32)
    non_negotiable_requirements: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    acceptable_degradations: list[str] = Field(default_factory=list, max_length=24)
    unacceptable_degradations: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    comparison_metrics: list[str] = Field(default_factory=list, max_length=32)
    creative_quality_checks: list[str] = Field(default_factory=list, max_length=32)
    technical_quality_checks: list[str] = Field(default_factory=list, max_length=32)
    rights_safety_checks: list[str] = Field(default_factory=list, max_length=32)
    fallback_acceptance_rules: list[str] = Field(default_factory=list, max_length=32)
    human_review_required: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairApprovalGateV1(BobaContract):
    approval_gate_id: str = Field(min_length=1, max_length=160)
    repair_case_id: str = Field(min_length=1, max_length=160)
    approval_status: BobaRepairApprovalStatusV1
    required_approvals: list[str] = Field(default_factory=list, max_length=32)
    actions_allowed_without_approval: list[str] = Field(
        default_factory=list,
        max_length=24,
    )
    actions_requiring_approval: list[str] = Field(default_factory=list, max_length=32)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=32)
    rights_gate_required: bool = False
    safety_gate_required: bool = True
    code_review_required: bool = False
    rollback_plan_required: bool = True
    validation_plan_required: bool = True
    output_quality_review_required: bool = True
    final_human_approval_required: Literal[True] = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairExecutionHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=160)
    repair_case_id: str = Field(min_length=1, max_length=160)
    repair_strategy_id: str = Field(default="", max_length=160)
    target_module: BobaRepairHandoffTargetV1
    reason: str = Field(min_length=1, max_length=700)
    required_inputs: list[str] = Field(default_factory=list, max_length=32)
    required_capability: str = Field(min_length=1, max_length=700)
    required_quality_properties: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    constraints: list[str] = Field(default_factory=list, max_length=32)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=32)
    checkpoint_plan_id: str = Field(default="", max_length=160)
    rollback_plan_id: str = Field(default="", max_length=160)
    validation_plan_id: str = Field(default="", max_length=160)
    approval_gate_id: str = Field(default="", max_length=160)
    apply_automatically: Literal[False] = False
    human_approval_required: Literal[True] = True
    priority: BobaRepairPriorityV1
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairRejectedStrategyV1(BobaContract):
    rejected_strategy_id: str = Field(min_length=1, max_length=160)
    repair_case_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    strategy_type: BobaRepairStrategyTypeV1
    rejection_reason: str = Field(min_length=1, max_length=700)
    safety_reason: str = Field(default="", max_length=700)
    quality_reason: str = Field(default="", max_length=700)
    rights_reason: str = Field(default="", max_length=700)
    reversibility_reason: str = Field(default="", max_length=700)
    evidence_reason: str = Field(default="", max_length=700)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRepairPlanningCaseV1(BobaContract):
    repair_case_id: str = Field(min_length=1, max_length=160)
    source_analysis_case_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    primary_module: str = Field(default="", max_length=160)
    primary_artifact: str = Field(default="", max_length=180)
    workflow_stage: str = Field(default="unknown", max_length=160)
    root_cause_candidate_ids: list[str] = Field(default_factory=list, max_length=24)
    selected_root_cause_candidate_id: str = Field(default="", max_length=160)
    selected_root_cause_summary: str = Field(default="", max_length=700)
    planning_status: BobaRepairPlanningStatusV1
    repair_needed: bool
    repair_scope: BobaRepairScopeV1
    blocked_reason: str = Field(default="", max_length=700)
    strategy_ids: list[str] = Field(default_factory=list, max_length=32)
    recommended_strategy_id: str = Field(default="", max_length=160)
    alternative_strategy_ids: list[str] = Field(default_factory=list, max_length=32)
    rejected_strategy_ids: list[str] = Field(default_factory=list, max_length=32)
    risk_assessment_id: str = Field(default="", max_length=160)
    checkpoint_plan_id: str = Field(default="", max_length=160)
    rollback_plan_id: str = Field(default="", max_length=160)
    validation_plan_id: str = Field(default="", max_length=160)
    quality_preservation_plan_id: str = Field(default="", max_length=160)
    approval_gate_id: str = Field(default="", max_length=160)
    execution_handoff_ids: list[str] = Field(default_factory=list, max_length=32)
    expected_workflow_impact: str = Field(min_length=1, max_length=700)
    human_review_required: Literal[True] = True
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaRepairPlannerSummaryV1(BobaContract):
    total_analysis_cases: int = Field(default=0, ge=0)
    total_repair_cases: int = Field(default=0, ge=0)
    plan_ready_count: int = Field(default=0, ge=0)
    conditional_plan_count: int = Field(default=0, ge=0)
    needs_more_evidence_count: int = Field(default=0, ge=0)
    safety_block_count: int = Field(default=0, ge=0)
    human_decision_count: int = Field(default=0, ge=0)
    repair_not_required_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    tool_recovery_handoff_count: int = Field(default=0, ge=0)
    code_surgeon_handoff_count: int = Field(default=0, ge=0)
    validator_handoff_count: int = Field(default=0, ge=0)
    highest_risk_case: str = Field(default="", max_length=700)
    safest_repair_strategy: str = Field(default="", max_length=700)
    most_reversible_strategy: str = Field(default="", max_length=700)
    strongest_quality_preservation_plan: str = Field(default="", max_length=700)
    highest_priority_handoff: str = Field(default="", max_length=700)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=64)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)


class BobaRepairPlannerSignalUsageV1(BobaContract):
    root_cause_analyzer_used: bool = False
    root_cause_artifact_read: bool = False
    failure_timelines_used: bool = False
    causal_graphs_used: bool = False
    root_cause_candidates_used: bool = False
    verification_plans_used: bool = False
    workflow_impacts_used: bool = False
    rights_safety_evidence_used: bool = False
    checkpoint_system_inspected: bool = False
    validation_registry_inspected: bool = False
    bounded_manual_context_used: bool = False
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
    workflow_resume_used: Literal[False] = False
    service_restart_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRepairPlannerSetV1(BobaContract):
    schema_version: Literal["boba_repair_planner_v1"] = "boba_repair_planner_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    root_cause_analyzer_source: str = Field(min_length=1, max_length=180)
    repair_cases: list[BobaRepairPlanningCaseV1] = Field(
        default_factory=list,
        max_length=256,
    )
    repair_strategies: list[BobaRepairStrategyV1] = Field(
        default_factory=list,
        max_length=2048,
    )
    risk_assessments: list[BobaRepairRiskAssessmentV1] = Field(
        default_factory=list,
        max_length=256,
    )
    checkpoint_plans: list[BobaRepairCheckpointPlanV1] = Field(
        default_factory=list,
        max_length=256,
    )
    rollback_plans: list[BobaRepairRollbackPlanV1] = Field(
        default_factory=list,
        max_length=256,
    )
    validation_plans: list[BobaRepairValidationPlanV1] = Field(
        default_factory=list,
        max_length=256,
    )
    quality_preservation_plans: list[BobaQualityPreservationPlanV1] = Field(
        default_factory=list,
        max_length=256,
    )
    approval_gates: list[BobaRepairApprovalGateV1] = Field(
        default_factory=list,
        max_length=256,
    )
    execution_handoffs: list[BobaRepairExecutionHandoffV1] = Field(
        default_factory=list,
        max_length=2048,
    )
    rejected_strategies: list[BobaRepairRejectedStrategyV1] = Field(
        default_factory=list,
        max_length=2048,
    )
    planner_summary: BobaRepairPlannerSummaryV1
    signal_usage: BobaRepairPlannerSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


def _text(value: Any, *, maximum: int = 700) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _safe_text(value: Any, *, maximum: int = 700) -> str:
    text = _text(value, maximum=maximum)
    text = _WINDOWS_ABSOLUTE.sub("[private path]", text)
    text = _UNC_PATH.sub("[private path]", text)
    return _UNIX_PRIVATE_PATH.sub("[private path]", text)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _unique(
    values: Sequence[Any],
    *,
    limit: int,
    maximum: int = 700,
) -> list[str]:
    result: list[str] = []
    for value in values:
        item = _safe_text(value, maximum=maximum)
        if item and item not in result:
            result.append(item)
        if len(result) >= limit:
            break
    return result


def _safe_context_value(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if depth >= 3:
        return _safe_text(value, maximum=300)
    if isinstance(value, str):
        return _safe_text(value, maximum=500)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            safe_key = _text(key, maximum=100)
            if not safe_key or _SECRET_KEY.search(safe_key):
                continue
            result[safe_key] = _safe_context_value(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [_safe_context_value(item, depth=depth + 1) for item in list(value)[:32]]
    return _safe_text(value, maximum=300)


def _bounded_context(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    result = _safe_context_value(value)
    return result if isinstance(result, dict) else {}


def _normalize_root_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    cases = payload.get("analysis_cases")
    if isinstance(cases, list):
        normalized_cases: list[Any] = []
        for item in cases[:256]:
            if not isinstance(item, Mapping):
                continue
            case = dict(item)
            if case.get("analysis_status") not in _ROOT_ANALYSIS_STATUS:
                case["analysis_status"] = "unknown"
            if case.get("processing_impact") not in _ROOT_PROCESSING_IMPACT:
                case["processing_impact"] = "unknown"
            if case.get("safety_impact") not in _ROOT_SAFETY_IMPACT:
                case["safety_impact"] = "unknown"
            if case.get("recommended_handoff") not in _ROOT_HANDOFF_TARGETS:
                case["recommended_handoff"] = "unknown"
            normalized_cases.append(case)
        payload["analysis_cases"] = normalized_cases
    candidates = payload.get("root_cause_candidates")
    if isinstance(candidates, list):
        normalized_candidates: list[Any] = []
        for item in candidates[:1024]:
            if not isinstance(item, Mapping):
                continue
            candidate = dict(item)
            if candidate.get("category") not in _ROOT_CATEGORIES:
                candidate["category"] = "unknown"
            if candidate.get("repairability") not in _ROOT_REPAIRABILITY:
                candidate["repairability"] = "unknown"
            if candidate.get("evidence_quality") not in _ROOT_EVIDENCE_QUALITY:
                candidate["evidence_quality"] = "unknown"
            normalized_candidates.append(candidate)
        payload["root_cause_candidates"] = normalized_candidates
    return payload


def _coerce_root_report(
    value: BobaRootCauseAnalyzerSetV1 | Mapping[str, Any] | None,
) -> tuple[BobaRootCauseAnalyzerSetV1 | None, list[str]]:
    if isinstance(value, BobaRootCauseAnalyzerSetV1):
        return value, []
    if not isinstance(value, Mapping):
        return None, ["A persisted Root Cause Analyzer V1 report is unavailable."]
    try:
        return BobaRootCauseAnalyzerSetV1.model_validate(
            _normalize_root_payload(value)
        ), []
    except (PydanticValidationError, ValidationError, TypeError, ValueError) as exc:
        return None, [
            "The persisted Root Cause Analyzer report is malformed and was not used: "
            f"{type(exc).__name__}."
        ]


def _priority(score: float, blocked: bool) -> BobaRepairPriorityV1:
    if blocked or score >= 0.82:
        return "urgent"
    if score >= 0.64:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _risk_rank(value: BobaRepairRiskLevelV1) -> int:
    return {
        "minimal": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
        "blocked": 5,
        "unknown": 6,
    }[value]


def _case_context(
    context: Mapping[str, Any],
    case: BobaRootCauseAnalysisCaseV1,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    global_context = context.get("global")
    if isinstance(global_context, Mapping):
        merged.update(global_context)
    cases = context.get("cases")
    if isinstance(cases, Mapping):
        for key in (
            case.analysis_case_id,
            case.source_diagnostic_case_id,
            case.primary_module,
            case.primary_artifact,
        ):
            item = cases.get(key)
            if isinstance(item, Mapping):
                merged.update(item)
    for key, value in context.items():
        if key not in {"global", "cases"}:
            merged.setdefault(key, value)
    return _bounded_context(merged)


def _context_strings(context: Mapping[str, Any], key: str) -> list[str]:
    value = context.get(key)
    if isinstance(value, str):
        return [_safe_text(value)]
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return _unique(value, limit=16, maximum=300)
    return []


def _context_bool(context: Mapping[str, Any], key: str) -> bool:
    return context.get(key) is True


def normalize_root_cause_case(
    case: BobaRootCauseAnalysisCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
) -> tuple[BobaRootCauseAnalysisCaseV1, list[BobaRootCauseCandidateV1]]:
    """Return one case and its bounded, deterministically ranked candidates."""

    related = [
        candidate
        for candidate in candidates
        if candidate.analysis_case_id == case.analysis_case_id
    ]
    related.sort(
        key=lambda candidate: (
            -candidate.likelihood_score,
            -candidate.confidence,
            candidate.root_cause_candidate_id,
        )
    )
    return case, related[:8]


def _selected_candidate(
    candidates: Sequence[BobaRootCauseCandidateV1],
) -> BobaRootCauseCandidateV1 | None:
    return candidates[0] if candidates else None


def _combined_case_text(
    case: BobaRootCauseAnalysisCaseV1,
    candidate: BobaRootCauseCandidateV1 | None,
) -> str:
    return " ".join(
        (
            case.title,
            case.most_likely_root_cause,
            *case.confirmed_facts,
            *case.probable_inferences,
            candidate.title if candidate else "",
            candidate.candidate_summary if candidate else "",
        )
    ).casefold()


def _repair_scope(
    case: BobaRootCauseAnalysisCaseV1,
    candidate: BobaRootCauseCandidateV1 | None,
) -> BobaRepairScopeV1:
    if candidate is None:
        return "unknown"
    category = candidate.category
    if category in {"intentional_safety_block", "rights_safety", "permission"}:
        return "rights_permission"
    if category == "user_input":
        return "human_decision"
    if category in {
        "missing_artifact",
        "corrupt_artifact",
        "stale_artifact",
        "schema_mismatch",
        "storage",
    }:
        return "artifact"
    if category == "checkpoint_failure":
        return "checkpoint"
    if category == "dependency_order":
        return "dependency"
    if category == "configuration":
        return "configuration"
    if category == "environment":
        return "environment"
    if category in {
        "tool_unavailable",
        "tool_failure",
        "timeout",
        "resource_exhaustion",
        "external_service",
    }:
        return "tool"
    if category == "data_quality":
        return "data_input"
    if category in {"validation_failure", "validation_gap"}:
        return "validation"
    if category in {"rendering", "audio_video_sync", "media_probe"}:
        return "rendering"
    if category == "code_defect":
        return "code"
    if case.processing_impact == "none":
        return "no_repair"
    return "unknown"


def determine_repair_eligibility(
    case: BobaRootCauseAnalysisCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    *,
    planning_context: Mapping[str, Any] | None = None,
) -> tuple[
    BobaRepairPlanningStatusV1,
    bool,
    BobaRepairScopeV1,
    str,
    float,
]:
    """Classify repair eligibility without treating a plan as execution approval."""

    context = planning_context or {}
    selected = _selected_candidate(candidates)
    scope = _repair_scope(case, selected)
    combined = _combined_case_text(case, selected)
    confidence = selected.confidence if selected else case.root_cause_confidence
    explicit_rights_or_permission = any(
        phrase in combined
        for phrase in (
            "rights blocked",
            "unknown rights",
            "permission required",
            "rights gate",
            "safety gate",
        )
    )
    if (
        (
            "human approval" in combined
            or "human decision" in combined
            or _context_bool(context, "human_approval_missing")
        )
        and not explicit_rights_or_permission
    ):
        return (
            "human_decision_required",
            False,
            "human_decision",
            "A human decision is missing; this is not a software repair.",
            _clamp(confidence),
        )
    rights_block = (
        case.analysis_status == "intentional_safety_block"
        or case.safety_impact in {"rights_gate_blocked", "safety_gate_blocked"}
        or (
            selected is not None
            and selected.category
            in {"intentional_safety_block", "rights_safety", "permission"}
        )
        or explicit_rights_or_permission
    )
    if rights_block:
        return (
            "intentional_safety_block",
            False,
            "rights_permission",
            "Processing remains blocked until Rights or Safety Gate and a human approve it.",
            _clamp(confidence),
        )
    if case.analysis_status == "no_defect_detected" or any(
        phrase in combined
        for phrase in ("healthy state", "no defect detected", "working as expected")
    ):
        return (
            "repair_not_required",
            False,
            "no_repair",
            "The saved analysis does not support a defect requiring repair.",
            _clamp(max(confidence, 0.7)),
        )
    optional_only = (
        "optional" in combined
        and case.processing_impact in {"none", "degraded"}
        and case.workflow_stage != "rendering"
    )
    if optional_only:
        return (
            "repair_not_required",
            False,
            "no_repair",
            "The missing optional capability has no required workflow impact.",
            _clamp(confidence),
        )
    if not candidates:
        return (
            "needs_more_evidence",
            False,
            "unknown",
            "No root-cause candidate is available for safe repair planning.",
            _clamp(min(confidence, 0.25)),
        )
    if case.analysis_status in {"multiple_competing_causes", "conflicting_evidence"}:
        return (
            "conflicting_causes",
            False,
            scope,
            "Competing causes require verification before a repair strategy is selected.",
            _clamp(confidence * 0.68),
        )
    if selected and selected.category == "validation_gap":
        return (
            "needs_more_evidence",
            False,
            "validation",
            "Missing validation is an evidence gap, not proof that repair is needed.",
            _clamp(confidence * 0.72),
        )
    if selected and (
        selected.evidence_quality in {"weak", "insufficient", "unknown"}
        or selected.repairability == "unknown"
    ):
        return (
            "needs_more_evidence",
            False,
            scope,
            "The candidate needs stronger evidence before repair planning can advance.",
            _clamp(confidence * 0.75),
        )
    if selected and selected.evidence_quality == "conflicting":
        return (
            "conflicting_causes",
            False,
            scope,
            "Conflicting evidence prevents selection of an executable repair.",
            _clamp(confidence * 0.6),
        )
    if selected and selected.repairability in {"blocked", "not_a_defect"}:
        return (
            "blocked" if selected.repairability == "blocked" else "repair_not_required",
            False,
            scope,
            "The selected candidate is blocked or is not a software defect.",
            _clamp(confidence),
        )
    if case.analysis_status == "insufficient_evidence":
        return (
            "needs_more_evidence",
            False,
            scope,
            "The Root Cause Analyzer explicitly reported insufficient evidence.",
            _clamp(confidence * 0.7),
        )
    if len(candidates) > 1 and abs(
        candidates[0].likelihood_score - candidates[1].likelihood_score
    ) <= 0.08:
        return (
            "conditional_plan",
            True,
            scope,
            "Two plausible causes are close enough to require conditional strategies.",
            _clamp(confidence * 0.82),
        )
    return (
        "plan_ready",
        True,
        scope,
        "",
        _clamp(confidence),
    )


def _strategy_types(
    case: BobaRootCauseAnalysisCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    status: BobaRepairPlanningStatusV1,
    context: Mapping[str, Any],
) -> list[BobaRepairStrategyTypeV1]:
    selected = _selected_candidate(candidates)
    category = selected.category if selected else "unknown"
    combined = _combined_case_text(case, selected)
    valid_checkpoint = (
        _context_bool(context, "valid_checkpoint_available")
        or context.get("checkpoint_status") == "valid"
    )
    checkpoint_invalid = context.get("checkpoint_status") in {
        "corrupt",
        "invalid",
        "missing",
    }
    upstream_healthy = (
        _context_bool(context, "upstream_healthy")
        or "healthy upstream" in combined
    )
    upstream_missing = (
        _context_bool(context, "upstream_missing")
        or "missing upstream" in combined
        or "required upstream artifact is missing" in combined
    )
    if status == "intentional_safety_block":
        return ["seek_permission", "stop_processing"]
    if status == "human_decision_required":
        return ["human_manual_action", "stop_processing"]
    if status == "repair_not_required":
        return ["no_action"]
    if status in {"needs_more_evidence", "conflicting_causes"}:
        result: list[BobaRepairStrategyTypeV1] = ["collect_more_evidence"]
        if category in {"validation_gap", "validation_failure"}:
            result.append("rerun_validation")
        elif status == "conflicting_causes":
            result.append("isolate_failure")
        return result
    if category == "missing_artifact":
        if upstream_missing:
            return (
                ["collect_more_evidence", "restore_checkpoint"]
                if valid_checkpoint
                else ["collect_more_evidence"]
            )
        result = ["regenerate_artifact"] if upstream_healthy else ["collect_more_evidence"]
        if valid_checkpoint:
            result.insert(0, "restore_checkpoint")
        elif not checkpoint_invalid:
            result.append("restore_checkpoint")
        return result
    if category == "corrupt_artifact":
        result = ["regenerate_artifact", "repair_generated_state"]
        if valid_checkpoint:
            result.insert(0, "restore_checkpoint")
        return result
    if category == "stale_artifact":
        result = ["regenerate_artifact", "repair_generated_state"]
        if valid_checkpoint:
            result.append("restore_checkpoint")
        return result
    if category in {"schema_mismatch", "storage", "dependency_order"}:
        return ["repair_generated_state", "regenerate_artifact", "collect_more_evidence"]
    if category == "checkpoint_failure":
        if valid_checkpoint:
            return ["restore_checkpoint", "resume_from_checkpoint"]
        return ["collect_more_evidence", "repair_generated_state"]
    if category == "configuration":
        return ["repair_configuration", "collect_more_evidence"]
    if category == "environment":
        return ["repair_environment", "collect_more_evidence"]
    if category == "tool_unavailable":
        return ["use_registered_tool_fallback", "collect_more_evidence"]
    if category == "tool_failure":
        return [
            "retry_same_tool",
            "retry_with_safe_settings",
            "use_registered_tool_fallback",
        ]
    if category == "timeout":
        return ["retry_with_safe_settings", "isolate_failure"]
    if category == "resource_exhaustion":
        return [
            "reduce_resource_usage",
            "retry_with_safe_settings",
            "use_registered_tool_fallback",
        ]
    if category == "data_quality":
        return ["replace_invalid_input", "collect_more_evidence"]
    if category == "validation_failure":
        return ["repair_generated_state", "rerun_validation"]
    if category == "validation_gap":
        return ["collect_more_evidence", "rerun_validation"]
    if category in {"rendering", "audio_video_sync", "media_probe"}:
        result = ["retry_with_safe_settings", "regenerate_artifact"]
        if valid_checkpoint:
            result.insert(0, "restore_checkpoint")
        return result
    if category == "code_defect":
        strong = selected is not None and (
            selected.evidence_quality in {"strong", "moderate"}
            and selected.confidence >= 0.72
        )
        return (
            ["propose_code_patch", "isolate_failure", "collect_more_evidence"]
            if strong
            else ["collect_more_evidence", "isolate_failure"]
        )
    if category == "user_input":
        return ["human_manual_action", "stop_processing"]
    if category in {"permission", "rights_safety", "intentional_safety_block"}:
        return ["seek_permission", "stop_processing"]
    return ["collect_more_evidence", "human_manual_action"]


def _strategy_metadata(
    strategy_type: BobaRepairStrategyTypeV1,
    target: str,
) -> tuple[str, str, str, str]:
    values: dict[
        BobaRepairStrategyTypeV1,
        tuple[str, str, str, str],
    ] = {
        "no_action": (
            "Keep the verified state unchanged",
            "Preserve the current project because no supported repair is required.",
            "Avoids changing healthy or intentionally limited behavior.",
            "BOBA found no supported software repair to apply, so the safest plan is to "
            "leave the project unchanged and keep the evidence available for review.",
        ),
        "collect_more_evidence": (
            "Collect the missing evidence first",
            "Inspect only bounded saved evidence needed to distinguish the candidates.",
            "A repair should not be chosen while the supported cause remains uncertain.",
            "BOBA needs a little more saved evidence before it can recommend a repair "
            "without guessing. Nothing will be changed during this review.",
        ),
        "regenerate_artifact": (
            "Regenerate only the affected generated artifact",
            f"Recreate only {target or 'the affected generated artifact'} from "
            "validated inputs.",
            "A scoped regeneration can replace invalid generated state without touching "
            "source media or unrelated stages.",
            "The safest repair is to rebuild only the broken generated result while "
            "keeping your original media and completed work untouched.",
        ),
        "restore_checkpoint": (
            "Restore from a validated checkpoint",
            "Restore the smallest affected scope from a checkpoint that first passes "
            "integrity validation.",
            "A valid checkpoint is reversible and avoids repeating unrelated work.",
            "BOBA can use a previously validated save point, but only after confirming "
            "that the checkpoint is complete and uncorrupted.",
        ),
        "resume_from_checkpoint": (
            "Resume from the validated checkpoint",
            "Ask Workflow Controller to resume only after checkpoint and validation gates pass.",
            "A bounded resume preserves completed stages and avoids duplicate processing.",
            "Olympus may continue from the last good save point after every required check "
            "passes and you approve the resume.",
        ),
        "retry_same_tool": (
            "Retry the same tool once with a strict budget",
            "Retry only the failed operation with bounded attempts and stop conditions.",
            "A transient tool crash may recover without changing tools or output requirements.",
            "The failed tool may be tried again only a limited number of times. BOBA will "
            "stop instead of looping if the same failure repeats.",
        ),
        "retry_with_safe_settings": (
            "Retry with bounded safe settings",
            "Retry the failed operation using conservative resource limits while preserving "
            "the required output specification.",
            "A constrained retry may address timeout or resource pressure without silently "
            "lowering quality.",
            "BOBA's plan is to retry only the failed work with safer limits. The result "
            "must still meet the original quality checks.",
        ),
        "reduce_resource_usage": (
            "Use a bounded lower-resource profile",
            "Reduce threads or memory pressure, or segment supported work, without reducing "
            "required output quality.",
            "The evidence indicates resource pressure, so bounded resource use directly "
            "addresses the supported failure.",
            "The failed step appears to need less memory. BOBA would use fewer resources "
            "while keeping the same required output quality.",
        ),
        "use_registered_tool_fallback": (
            "Request a compatible registered tool fallback",
            "Ask Tool Recovery Brain to compare registered tools against capability, quality, "
            "safety, and validation requirements.",
            "A compatible fallback may restore the missing capability, but completion alone "
            "does not prove acceptance.",
            "A different approved tool may help, but BOBA will not select or run it. The "
            "fallback must match the original quality and pass validation first.",
        ),
        "switch_safe_workflow_path": (
            "Use an approved safe workflow path",
            "Route future work through a compatible registered path after checkpointing.",
            "A different workflow can isolate the failed component while preserving inputs.",
            "Olympus may use another approved path only if it protects your source and "
            "produces an equivalent validated result.",
        ),
        "repair_generated_state": (
            "Repair only temporary generated state",
            "Replace bounded generated state after preserving evidence and a rollback snapshot.",
            "Temporary state can be repaired without altering the original source.",
            "BOBA would preserve the current evidence, repair only temporary project data, "
            "and validate the result before anything continues.",
        ),
        "repair_configuration": (
            "Propose a minimal configuration correction",
            "Back up non-secret configuration and propose the smallest supported change.",
            "A minimal reversible configuration update avoids unrelated system changes.",
            "BOBA can describe the smallest setting change, but it will not reveal secrets "
            "or modify configuration without your approval.",
        ),
        "repair_environment": (
            "Prepare an environment capability correction",
            "Identify the missing capability and prefer an already compatible environment.",
            "Environment or dependency changes should be isolated and human-approved.",
            "The system may need an environment or dependency change. BOBA will only prepare "
            "the requirements; it will not install or restart anything.",
        ),
        "replace_invalid_input": (
            "Request a validated replacement input",
            "Preserve the original reference and request a compatible authorized input.",
            "Invalid input should be corrected explicitly rather than silently transformed.",
            "The current input may not be usable. BOBA will keep it untouched and ask for a "
            "validated replacement instead of changing it silently.",
        ),
        "rerun_validation": (
            "Run the required validation through Validator Runner",
            "Ask Validator Runner to execute the approved checks and preserve pass/fail truth.",
            "Missing or failed validation must be resolved before a repair can be accepted.",
            "BOBA needs the required checks to run through the validator service. Missing "
            "proof will never be treated as a pass.",
        ),
        "isolate_failure": (
            "Isolate the failed component",
            "Preserve the current state and reproduce only the bounded failing component later.",
            "Isolation can distinguish competing causes without risking unrelated stages.",
            "BOBA's safer next step is to test only the failing part later, after approval, "
            "so the rest of the project stays untouched.",
        ),
        "propose_code_patch": (
            "Prepare a scoped Code Surgeon handoff",
            "Send the supported defect, branch requirement, rollback plan, and tests to Code "
            "Surgeon for a future approved patch.",
            "Strong code-defect evidence may justify a scoped patch, but never directly on main.",
            "BOBA can hand the supported defect to Code Surgeon for a separate branch. It "
            "does not generate or apply a patch itself.",
        ),
        "seek_permission": (
            "Request rights or permission review",
            "Keep processing blocked and request a human-reviewed Rights Gate decision.",
            "Permission is a human and safety decision, not a software defect.",
            "Olympus must remain stopped until the required rights or permission are confirmed.",
        ),
        "human_manual_action": (
            "Request a human decision",
            "Present the unresolved choice and required evidence to a human operator.",
            "The issue requires judgment or approval rather than an automatic repair.",
            "BOBA needs you or another authorized operator to decide the next safe action.",
        ),
        "stop_processing": (
            "Keep processing stopped",
            "Preserve all current evidence and block unsafe or unauthorized actions.",
            "Stopping is safer than guessing, bypassing a gate, or risking destructive change.",
            "BOBA will keep the project stopped because the next action is not yet "
            "safe or approved.",
        ),
        "unknown": (
            "Unknown advisory option",
            "No bounded strategy is available.",
            "The evidence is insufficient for a specific strategy.",
            "BOBA does not yet have enough information to suggest a specific safe option.",
        ),
    }
    return values[strategy_type]


def _strategy_flags(
    strategy_type: BobaRepairStrategyTypeV1,
) -> dict[str, bool]:
    actionable = strategy_type not in {
        "no_action",
        "collect_more_evidence",
        "seek_permission",
        "human_manual_action",
        "stop_processing",
    }
    return {
        "requires_checkpoint": actionable,
        "requires_backup": strategy_type
        in {
            "regenerate_artifact",
            "restore_checkpoint",
            "repair_generated_state",
            "repair_configuration",
            "repair_environment",
            "replace_invalid_input",
            "propose_code_patch",
        },
        "requires_command_execution": actionable,
        "requires_validator_execution": actionable
        or strategy_type == "rerun_validation",
        "requires_code_change": strategy_type == "propose_code_patch",
        "requires_configuration_change": strategy_type
        in {"repair_configuration", "repair_environment"},
        "requires_tool_fallback": strategy_type == "use_registered_tool_fallback",
        "requires_service_restart": False,
        "requires_package_installation": strategy_type == "repair_environment",
        "requires_external_access": False,
        "requires_paid_service": False,
        "requires_rights_review": strategy_type
        in {"seek_permission", "stop_processing"},
    }


def _strategy_reversibility(
    strategy_type: BobaRepairStrategyTypeV1,
) -> BobaRepairReversibilityV1:
    if strategy_type in {
        "no_action",
        "collect_more_evidence",
        "seek_permission",
        "human_manual_action",
        "stop_processing",
        "rerun_validation",
        "isolate_failure",
    }:
        return "fully_reversible"
    if strategy_type in {
        "restore_checkpoint",
        "resume_from_checkpoint",
        "retry_same_tool",
        "retry_with_safe_settings",
        "reduce_resource_usage",
        "use_registered_tool_fallback",
        "switch_safe_workflow_path",
        "regenerate_artifact",
        "repair_generated_state",
    }:
        return "mostly_reversible"
    if strategy_type in {"repair_configuration", "repair_environment"}:
        return "partially_reversible"
    if strategy_type in {"replace_invalid_input", "propose_code_patch"}:
        return "partially_reversible"
    return "unknown"


def _strategy_risk(
    strategy_type: BobaRepairStrategyTypeV1,
    flags: Mapping[str, bool],
) -> BobaRepairRiskLevelV1:
    if strategy_type == "stop_processing":
        return "blocked"
    if strategy_type in {
        "no_action",
        "collect_more_evidence",
        "seek_permission",
        "human_manual_action",
        "rerun_validation",
    }:
        return "minimal"
    if strategy_type in {"restore_checkpoint", "isolate_failure"}:
        return "low"
    if strategy_type in {
        "regenerate_artifact",
        "resume_from_checkpoint",
        "retry_same_tool",
        "retry_with_safe_settings",
        "reduce_resource_usage",
        "repair_generated_state",
    }:
        return "medium"
    if flags.get("requires_code_change") or flags.get("requires_package_installation"):
        return "high"
    if flags.get("requires_tool_fallback") or flags.get("requires_configuration_change"):
        return "high"
    return "medium"


def _strategy_complexity(
    strategy_type: BobaRepairStrategyTypeV1,
) -> BobaRepairComplexityV1:
    if strategy_type in {
        "no_action",
        "collect_more_evidence",
        "seek_permission",
        "human_manual_action",
        "stop_processing",
        "rerun_validation",
    }:
        return "minimal"
    if strategy_type in {
        "restore_checkpoint",
        "regenerate_artifact",
        "retry_same_tool",
        "retry_with_safe_settings",
        "reduce_resource_usage",
        "isolate_failure",
    }:
        return "low"
    if strategy_type in {
        "repair_generated_state",
        "resume_from_checkpoint",
        "repair_configuration",
        "use_registered_tool_fallback",
        "switch_safe_workflow_path",
    }:
        return "medium"
    if strategy_type in {"repair_environment", "replace_invalid_input"}:
        return "high"
    if strategy_type == "propose_code_patch":
        return "very_high"
    return "unknown"


def _step_specs(
    strategy_type: BobaRepairStrategyTypeV1,
    flags: Mapping[str, bool],
) -> list[tuple[BobaRepairStepTypeV1, str, str]]:
    if strategy_type == "no_action":
        return [
            (
                "human_review",
                "Confirm that the current healthy or intentionally limited state "
                "should remain unchanged.",
                "human_operator",
            )
        ]
    if strategy_type == "collect_more_evidence":
        return [
            (
                "inspect",
                "Inspect only the bounded evidence references named by Root Cause Analyzer.",
                "artifact_inspector",
            ),
            (
                "collect_evidence",
                "Record the missing proof without modifying project artifacts.",
                "report_reader",
            ),
        ]
    if strategy_type == "seek_permission":
        return [
            (
                "human_review",
                "Request an explicit rights or permission decision.",
                "rights_permission_gate",
            ),
            (
                "stop",
                "Keep processing blocked until an approved decision exists.",
                "workflow_controller",
            ),
        ]
    if strategy_type == "human_manual_action":
        return [
            (
                "human_review",
                "Present the decision, evidence, risks, and prohibited actions to a human.",
                "human_operator",
            )
        ]
    if strategy_type == "stop_processing":
        return [
            (
                "stop",
                "Keep the affected workflow stopped and preserve current evidence.",
                "safety_gate",
            )
        ]
    action: tuple[BobaRepairStepTypeV1, str, str]
    actions: dict[
        BobaRepairStrategyTypeV1,
        tuple[BobaRepairStepTypeV1, str, str],
    ] = {
        "regenerate_artifact": (
            "regenerate",
            "Regenerate only the affected generated artifact from validated inputs.",
            "checkpoint_recovery_manager",
        ),
        "restore_checkpoint": (
            "restore",
            "Restore only from a checkpoint that passed integrity validation.",
            "checkpoint_recovery_manager",
        ),
        "resume_from_checkpoint": (
            "resume_workflow",
            "Request conditional resume after every gate and validation passes.",
            "workflow_controller",
        ),
        "retry_same_tool": (
            "retry",
            "Retry the failed operation within the defined attempt and time budget.",
            "tool_recovery_brain",
        ),
        "retry_with_safe_settings": (
            "adjust_safe_setting",
            "Apply only approved bounded resource or timeout settings for a future retry.",
            "tool_recovery_brain",
        ),
        "reduce_resource_usage": (
            "adjust_safe_setting",
            "Use bounded thread, memory, or supported segmentation settings.",
            "tool_recovery_brain",
        ),
        "use_registered_tool_fallback": (
            "switch_tool",
            "Select a compatible registered tool only after separate approval.",
            "tool_recovery_brain",
        ),
        "switch_safe_workflow_path": (
            "switch_workflow",
            "Use an approved compatible workflow path without bypassing gates.",
            "workflow_controller",
        ),
        "repair_generated_state": (
            "restore",
            "Replace only bounded temporary or generated state.",
            "checkpoint_recovery_manager",
        ),
        "repair_configuration": (
            "configure",
            "Apply the smallest approved non-secret configuration correction.",
            "human_operator",
        ),
        "repair_environment": (
            "install_dependency",
            "Provide the missing capability in an approved isolated environment.",
            "human_operator",
        ),
        "replace_invalid_input": (
            "human_review",
            "Select an authorized validated replacement input while preserving "
            "the original reference.",
            "human_operator",
        ),
        "rerun_validation": (
            "validate_result",
            "Run the required approved validation and preserve pass/fail truth.",
            "validator_runner",
        ),
        "isolate_failure": (
            "switch_workflow",
            "Isolate only the failing component for future approved reproduction.",
            "workflow_controller",
        ),
        "propose_code_patch": (
            "propose_patch",
            "Ask Code Surgeon to prepare a scoped patch on a separate branch.",
            "code_surgeon",
        ),
        "unknown": (
            "human_review",
            "Review the unknown strategy manually.",
            "human_operator",
        ),
        "no_action": ("human_review", "Review the no-action plan.", "human_operator"),
        "collect_more_evidence": (
            "collect_evidence",
            "Collect bounded evidence.",
            "report_reader",
        ),
        "seek_permission": (
            "human_review",
            "Review permission.",
            "rights_permission_gate",
        ),
        "human_manual_action": (
            "human_review",
            "Request a human decision.",
            "human_operator",
        ),
        "stop_processing": ("stop", "Keep processing stopped.", "safety_gate"),
    }
    action = actions[strategy_type]
    result: list[tuple[BobaRepairStepTypeV1, str, str]] = [
        (
            "validate_precondition",
            "Confirm the supported cause, rights state, safety state, and required inputs.",
            "validator_runner",
        )
    ]
    if flags.get("requires_backup"):
        result.append(
            (
                "backup",
                "Preserve the affected generated state and required references before change.",
                "checkpoint_recovery_manager",
            )
        )
    if flags.get("requires_checkpoint"):
        result.append(
            (
                "checkpoint",
                "Create and validate the required checkpoint before future execution.",
                "checkpoint_recovery_manager",
            )
        )
    result.append(action)
    if strategy_type != "rerun_validation":
        result.append(
            (
                "validate_result",
                "Run all required technical, safety, rights, and regression checks.",
                "validator_runner",
            )
        )
    result.append(
        (
            "compare_quality",
            "Compare the result with the original technical and creative quality baseline.",
            "output_quality_reviewer",
        )
    )
    return result


def _build_steps(
    strategy_id: str,
    strategy_type: BobaRepairStrategyTypeV1,
    target: str,
    flags: Mapping[str, bool],
) -> list[BobaRepairStepV1]:
    steps: list[BobaRepairStepV1] = []
    for order, (step_type, description, owner) in enumerate(
        _step_specs(strategy_type, flags),
        start=1,
    ):
        future_change = step_type in {
            "regenerate",
            "retry",
            "adjust_safe_setting",
            "switch_tool",
            "switch_workflow",
            "restore",
            "configure",
            "install_dependency",
            "restart_service",
            "propose_patch",
            "apply_patch",
            "validate_result",
            "compare_quality",
            "resume_workflow",
        }
        steps.append(
            BobaRepairStepV1(
                repair_step_id=_stable_id(
                    "repair_step",
                    strategy_id,
                    str(order),
                    step_type,
                ),
                repair_strategy_id=strategy_id,
                order=order,
                step_type=step_type,
                description=description,
                target=_safe_text(target, maximum=180),
                read_only=not future_change,
                reversible=step_type not in {"apply_patch"},
                requires_human_approval=True,
                requires_command_execution=future_change,
                requires_code_change=step_type in {"propose_patch", "apply_patch"},
                requires_external_access=False,
                safety_precondition=(
                    "Human approval, validated checkpoint, intact source media, and all "
                    "applicable Rights and Safety gates."
                ),
                success_condition=(
                    "The responsible future module records the expected bounded result."
                ),
                failure_condition=(
                    "A required precondition, validation, quality, safety, or rights check fails."
                ),
                stop_condition=(
                    "Stop immediately on repeated failure, unexpected scope, source-data risk, "
                    "quality regression, or a safety/rights concern."
                ),
                rollback_step_reference=(
                    "Use the case rollback plan before any future non-read-only action."
                    if future_change
                    else ""
                ),
                suggested_owner_module=owner,
                warnings=[
                    "This future step was described but not executed by Repair Planner."
                ],
            )
        )
    return steps


def _strategy_score(
    strategy_type: BobaRepairStrategyTypeV1,
    candidate: BobaRootCauseCandidateV1 | None,
    flags: Mapping[str, bool],
    context: Mapping[str, Any],
) -> float:
    evidence = candidate.likelihood_score if candidate else 0.25
    score = 0.35 + evidence * 0.32
    if strategy_type not in {
        "collect_more_evidence",
        "no_action",
        "human_manual_action",
        "stop_processing",
    }:
        score += 0.16
    if strategy_type == "collect_more_evidence":
        score += (
            0.2
            if candidate is None
            or candidate.evidence_quality
            in {"weak", "insufficient", "conflicting", "unknown"}
            else -0.08
        )
    if strategy_type == "restore_checkpoint":
        score += (
            0.22
            if _context_bool(context, "valid_checkpoint_available")
            or context.get("checkpoint_status") == "valid"
            else -0.18
        )
    if _strategy_reversibility(strategy_type) == "fully_reversible":
        score += 0.13
    elif _strategy_reversibility(strategy_type) == "mostly_reversible":
        score += 0.09
    if flags.get("requires_code_change"):
        score -= 0.18
    if flags.get("requires_package_installation"):
        score -= 0.12
    if flags.get("requires_external_access"):
        score -= 0.2
    if flags.get("requires_paid_service"):
        score -= 0.18
    if strategy_type == "use_registered_tool_fallback":
        score -= 0.05
    previous = {
        _text(item, maximum=160).casefold()
        for item in _context_strings(context, "previously_attempted_strategies")
    }
    if strategy_type.casefold() in previous or any(
        strategy_type.casefold() in item for item in previous
    ):
        score -= 0.5
    if strategy_type == "stop_processing":
        score = 0.3
    if strategy_type == "no_action":
        score = 0.9
    return _clamp(score)


def _prohibited_actions() -> list[str]:
    return [
        "Modify, overwrite, rename, move, or delete source media",
        "Execute this strategy automatically",
        "Bypass Rights Gate, Safety Gate, approval, or required validation",
        "Hide errors, failed checks, quality loss, or unresolved uncertainty",
        "Use unlimited retries or repeat an identical failed attempt without new evidence",
        "Expose secrets, credentials, tokens, cookies, or private absolute paths",
        "Patch main directly or apply unreviewed code changes",
        "Use unapproved paid services, external uploads, DRM bypass, or access-control bypass",
    ]


def generate_repair_strategies(
    case: BobaRootCauseAnalysisCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    status: BobaRepairPlanningStatusV1,
    *,
    planning_context: Mapping[str, Any] | None = None,
) -> list[BobaRepairStrategyV1]:
    """Generate multiple bounded future options without executing any option."""

    context = planning_context or {}
    selected = _selected_candidate(candidates)
    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    target = case.primary_artifact or case.primary_module or case.workflow_stage
    strategies: list[BobaRepairStrategyV1] = []
    previous = _context_strings(context, "previously_attempted_strategies")
    for strategy_type in _strategy_types(case, candidates, status, context)[:8]:
        title, description, rationale, easy = _strategy_metadata(
            strategy_type,
            target,
        )
        flags = _strategy_flags(strategy_type)
        if _context_bool(context, "requires_external_access"):
            flags["requires_external_access"] = True
        if _context_bool(context, "requires_paid_service"):
            flags["requires_paid_service"] = True
        if _context_bool(context, "requires_service_restart"):
            flags["requires_service_restart"] = True
        strategy_id = _stable_id(
            "repair_strategy",
            repair_case_id,
            strategy_type,
            selected.root_cause_candidate_id if selected else "",
        )
        retry_related = strategy_type in {
            "retry_same_tool",
            "retry_with_safe_settings",
            "reduce_resource_usage",
            "use_registered_tool_fallback",
        }
        risk = _strategy_risk(strategy_type, flags)
        strategies.append(
            BobaRepairStrategyV1(
                repair_strategy_id=strategy_id,
                repair_case_id=repair_case_id,
                title=title,
                strategy_type=strategy_type,
                target_module=case.primary_module,
                target_artifact=case.primary_artifact,
                description=description,
                rationale=rationale,
                easy_explanation=easy,
                root_cause_candidate_ids=[
                    item.root_cause_candidate_id for item in candidates[:4]
                ],
                prerequisites=[
                    "Root Cause Analyzer evidence remains unchanged and available.",
                    "Source media remains untouched.",
                    "A human approves every future executable step.",
                    "Required checkpoint, rollback, validation, quality, rights, and safety "
                    "conditions are satisfied.",
                ],
                proposed_steps=_build_steps(
                    strategy_id,
                    strategy_type,
                    target,
                    flags,
                ),
                expected_result=(
                    "A bounded future module produces a validated result or records an honest "
                    "failure without changing unrelated state."
                ),
                expected_quality_effect=(
                    "No silent quality reduction is permitted; affected output must match the "
                    "non-negotiable quality plan or be rejected."
                ),
                expected_workflow_effect=(
                    "The affected workflow remains blocked until required validation, quality "
                    "review, safety review, rights review, and human approval pass."
                ),
                reversibility=_strategy_reversibility(strategy_type),
                destructiveness=(
                    "none"
                    if strategy_type
                    in {
                        "no_action",
                        "collect_more_evidence",
                        "seek_permission",
                        "human_manual_action",
                        "stop_processing",
                        "rerun_validation",
                        "isolate_failure",
                    }
                    else "low"
                ),
                automation_eligibility=(
                    "blocked"
                    if strategy_type == "stop_processing"
                    else "human_execution_required"
                    if flags["requires_code_change"]
                    or flags["requires_package_installation"]
                    else "safe_advisory_only"
                    if strategy_type
                    in {
                        "no_action",
                        "collect_more_evidence",
                        "seek_permission",
                        "human_manual_action",
                    }
                    else "potentially_automatable_after_approval"
                ),
                human_approval_required=True,
                **flags,
                estimated_risk=risk,
                estimated_complexity=_strategy_complexity(strategy_type),
                estimated_confidence=_clamp(
                    (selected.confidence if selected else case.root_cause_confidence)
                    * (
                        0.75
                        if status
                        in {
                            "conditional_plan",
                            "conflicting_causes",
                            "needs_more_evidence",
                        }
                        else 1.0
                    )
                    * (
                        0.72
                        if context.get("checkpoint_status")
                        in {"missing", "corrupt", "invalid"}
                        else 1.0
                    )
                ),
                strategy_score=_strategy_score(
                    strategy_type,
                    selected,
                    flags,
                    context,
                ),
                maximum_attempts=2 if retry_related else None,
                maximum_recovery_duration_seconds=900 if retry_related else None,
                previously_attempted_strategies=previous,
                escalation_condition=(
                    "Escalate after two bounded attempts, one repeated identical failure, "
                    "quality regression, or any new safety/rights concern."
                    if retry_related
                    else "Escalate when a required precondition, validation, quality, rights, "
                    "safety, or rollback condition cannot be satisfied."
                ),
                prohibited_actions=_prohibited_actions(),
                stop_conditions=[
                    "Stop before any action outside the selected artifact, module, "
                    "or workflow scope.",
                    "Stop if source media could be altered or required preserved state is missing.",
                    "Stop on failed required validation or unacceptable quality degradation.",
                    "Stop on missing approval or any Rights or Safety Gate block.",
                    *(
                        [
                            "Stop after the maximum attempts or maximum recovery duration.",
                            "Stop before repeating an identical failed strategy "
                            "without new evidence.",
                        ]
                        if retry_related
                        else []
                    ),
                ],
                warnings=[
                    "This strategy is advisory and was not executed.",
                    "A repair plan is not proof that the repair will succeed.",
                    "Human approval is required before any future execution.",
                ],
                limitations=[
                    "Planning is bounded to the persisted Root Cause Analyzer report and "
                    "bounded planning context.",
                    "No command, validator, repair, fallback, restart, installation, or workflow "
                    "resume occurred.",
                ],
            )
        )
    return rank_repair_strategies(strategies)


def rank_repair_strategies(
    strategies: Sequence[BobaRepairStrategyV1],
) -> list[BobaRepairStrategyV1]:
    """Rank strategies deterministically while preserving uncertainty."""

    ranked = sorted(
        strategies,
        key=lambda strategy: (
            -strategy.strategy_score,
            _risk_rank(strategy.estimated_risk),
            {
                "fully_reversible": 0,
                "mostly_reversible": 1,
                "partially_reversible": 2,
                "difficult_to_reverse": 3,
                "irreversible": 4,
                "unknown": 5,
            }[strategy.reversibility],
            strategy.repair_strategy_id,
        ),
    )
    for rank, strategy in enumerate(ranked, start=1):
        strategy.rank = rank
        strategy.recommended = rank == 1
    return ranked


def reject_unsafe_repair_strategies(
    case: BobaRootCauseAnalysisCaseV1,
    strategies: Sequence[BobaRepairStrategyV1],
    *,
    planning_context: Mapping[str, Any] | None = None,
) -> list[BobaRepairRejectedStrategyV1]:
    """Record unsafe options so they cannot be confused with recommendations."""

    context = planning_context or {}
    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    records: list[
        tuple[
            str,
            BobaRepairStrategyTypeV1,
            str,
            str,
            str,
            str,
            str,
            str,
        ]
    ] = [
        (
            "Modify or delete source media",
            "unknown",
            "Source-data modification is outside safe repair scope.",
            "Destructive source changes are prohibited.",
            "Source meaning and media quality could be irreversibly lost.",
            "",
            "The original source cannot be safely reconstructed from generated state.",
            "No supported evidence requires changing source media.",
        ),
        (
            "Retry without a finite budget",
            "retry_same_tool",
            "Unlimited retry loops are prohibited.",
            "Unbounded resource use and repeated failures are unsafe.",
            "Repeated retries can create inconsistent or duplicate output.",
            "",
            "There is no bounded rollback point for an unlimited loop.",
            "A repeated identical failure needs new evidence, not another unlimited attempt.",
        ),
        (
            "Silently lower output quality",
            "retry_with_safe_settings",
            "Silent quality degradation is prohibited.",
            "Hidden degradation violates repair truth requirements.",
            "Completion alone does not satisfy captions, framing, A/V sync, story, "
            "or media quality.",
            "",
            "The original quality baseline must remain available for comparison.",
            "No evidence authorizes lowering non-negotiable quality requirements.",
        ),
        (
            "Execute without checkpoint or rollback",
            "repair_generated_state",
            "Every non-trivial repair needs preserved state and rollback.",
            "An unbounded change could leave the workflow corrupted.",
            "The result could not be compared or safely rejected.",
            "",
            "No restoration path exists.",
            "The saved analysis does not prove an irreversible repair is necessary.",
        ),
        (
            "Bypass rights or safety controls",
            "stop_processing",
            "Rights and Safety gates cannot be bypassed.",
            "Gate bypass is prohibited.",
            "Unauthorized output cannot be accepted.",
            "Permission and platform restrictions remain binding.",
            "A bypass is not reversible evidence-based repair.",
            "No diagnostic evidence can authorize a gate bypass.",
        ),
        (
            "Expose credentials or secrets in a repair plan",
            "repair_configuration",
            "Sensitive values must not be stored or displayed.",
            "Credential exposure creates a security risk.",
            "",
            "",
            "A leaked secret cannot reliably be made private again.",
            "Configuration diagnosis requires only presence and bounded metadata.",
        ),
    ]
    selected = next((item for item in strategies if item.recommended), None)
    if selected and selected.requires_code_change:
        records.append(
            (
                "Patch main directly",
                "propose_code_patch",
                "Code changes require a separate branch, review, tests, and rollback.",
                "Direct main modification is prohibited.",
                "An unreviewed patch could regress output quality.",
                "",
                "Main must remain recoverable through an isolated branch.",
                "The evidence supports only a future scoped Code Surgeon review.",
            )
        )
    if context.get("checkpoint_status") in {"corrupt", "invalid"}:
        records.append(
            (
                "Restore the corrupt checkpoint",
                "restore_checkpoint",
                "An invalid checkpoint cannot be a recovery source.",
                "Restoring corrupt state risks workflow corruption.",
                "Generated output could be incomplete or invalid.",
                "",
                "Rollback to corrupt state is not a valid recovery.",
                "Checkpoint integrity evidence explicitly rejects this option.",
            )
        )
    if any(
        strategy.requires_external_access or strategy.requires_paid_service
        for strategy in strategies
    ):
        records.append(
            (
                "Use an unapproved paid or external provider",
                "use_registered_tool_fallback",
                "External or paid providers require explicit approval and compatible rights.",
                "Unapproved upload or service use is prohibited.",
                "Output properties and privacy may be unknown.",
                "Media rights may not permit external processing.",
                "External side effects may be difficult to reverse.",
                "No approval record exists in the planning evidence.",
            )
        )
    return [
        BobaRepairRejectedStrategyV1(
            rejected_strategy_id=_stable_id(
                "rejected_repair_strategy",
                repair_case_id,
                title,
            ),
            repair_case_id=repair_case_id,
            title=title,
            strategy_type=strategy_type,
            rejection_reason=rejection,
            safety_reason=safety,
            quality_reason=quality,
            rights_reason=rights,
            reversibility_reason=reversibility,
            evidence_reason=evidence,
            warnings=["This unsafe strategy was rejected and never executed."],
        )
        for (
            title,
            strategy_type,
            rejection,
            safety,
            quality,
            rights,
            reversibility,
            evidence,
        ) in records[:16]
    ]


def _max_risk(
    values: Sequence[BobaRepairRiskLevelV1],
) -> BobaRepairRiskLevelV1:
    return max(values, key=_risk_rank) if values else "unknown"


def assess_repair_risks(
    case: BobaRootCauseAnalysisCaseV1,
    strategies: Sequence[BobaRepairStrategyV1],
    status: BobaRepairPlanningStatusV1,
) -> BobaRepairRiskAssessmentV1:
    """Assess planned strategy risk without applying a strategy."""

    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    strategy_risks: list[BobaRepairStrategyRiskV1] = []
    for strategy in strategies[:16]:
        reasons: list[str] = []
        if strategy.requires_code_change:
            reasons.append("A future code change could create regressions.")
        if strategy.requires_configuration_change:
            reasons.append("Configuration or environment state could diverge.")
        if strategy.requires_package_installation:
            reasons.append("Dependency installation changes the runtime environment.")
        if strategy.requires_tool_fallback:
            reasons.append("A fallback tool may differ in output or behavior.")
        if strategy.requires_external_access:
            reasons.append("External access creates privacy and availability risk.")
        if strategy.requires_paid_service:
            reasons.append("A paid provider requires cost and policy approval.")
        if strategy.requires_rights_review:
            reasons.append("Rights or permission remains unresolved.")
        if not reasons:
            reasons.append("Future execution can still fail or produce an invalid result.")
        strategy_risks.append(
            BobaRepairStrategyRiskV1(
                strategy_id=strategy.repair_strategy_id,
                risk_level=strategy.estimated_risk,
                risk_reasons=reasons,
                mitigations=[
                    "Preserve source media and required generated state.",
                    "Validate the checkpoint before any future non-read-only action.",
                    "Use the ordered rollback and validation plan.",
                    "Reject failed technical, quality, rights, or safety checks.",
                ],
                residual_risk=(
                    "The plan may still fail or reveal a different cause; ranking is not proof."
                ),
                acceptable_only_if=[
                    "Human approval is recorded.",
                    "The checkpoint and rollback plan are valid.",
                    "Every required validation and output-quality check passes.",
                    "Rights and Safety gates permit the action.",
                ],
                blocked=strategy.estimated_risk == "blocked",
                confidence=strategy.estimated_confidence,
                warnings=["No risk was accepted automatically."],
            )
        )
    selected_risks = [item.risk_level for item in strategy_risks]
    rights_risk: BobaRepairRiskLevelV1 = (
        "blocked"
        if status == "intentional_safety_block"
        else "high"
        if case.safety_impact
        in {"human_review_needed", "rights_gate_blocked", "safety_gate_blocked"}
        else "low"
    )
    source_data_risk: BobaRepairRiskLevelV1 = (
        "minimal"
        if all(item.destructiveness in {"none", "low"} for item in strategies)
        else "high"
    )
    artifact_loss_risk: BobaRepairRiskLevelV1 = (
        "medium" if any(item.requires_backup for item in strategies) else "low"
    )
    quality_risk: BobaRepairRiskLevelV1 = (
        "high"
        if any(
            item.requires_tool_fallback
            or item.requires_code_change
            or item.repair_strategy_id.endswith("rendering")
            for item in strategies
        )
        or case.workflow_stage == "rendering"
        else "medium"
        if any(item.requires_command_execution for item in strategies)
        else "low"
    )
    configuration_risk: BobaRepairRiskLevelV1 = (
        "medium"
        if any(item.requires_configuration_change for item in strategies)
        else "minimal"
    )
    environment_risk: BobaRepairRiskLevelV1 = (
        "high"
        if any(item.requires_package_installation for item in strategies)
        else "low"
    )
    external_risk: BobaRepairRiskLevelV1 = (
        "high"
        if any(
            item.requires_external_access or item.requires_paid_service
            for item in strategies
        )
        else "minimal"
    )
    rollback_risk: BobaRepairRiskLevelV1 = (
        "medium"
        if any(
            item.reversibility
            in {"partially_reversible", "difficult_to_reverse", "irreversible", "unknown"}
            for item in strategies
        )
        else "low"
    )
    overall = _max_risk(
        [
            *selected_risks,
            rights_risk,
            source_data_risk,
            artifact_loss_risk,
            quality_risk,
            configuration_risk,
            environment_risk,
            external_risk,
            rollback_risk,
        ]
    )
    return BobaRepairRiskAssessmentV1(
        risk_assessment_id=_stable_id("repair_risk", repair_case_id),
        repair_case_id=repair_case_id,
        strategy_risks=strategy_risks,
        overall_risk=overall,
        source_data_risk=source_data_risk,
        artifact_loss_risk=artifact_loss_risk,
        output_quality_risk=quality_risk,
        workflow_corruption_risk=(
            "medium"
            if any(item.requires_command_execution for item in strategies)
            else "low"
        ),
        configuration_risk=configuration_risk,
        environment_risk=environment_risk,
        security_risk=(
            "medium"
            if any(
                item.requires_configuration_change or item.requires_external_access
                for item in strategies
            )
            else "low"
        ),
        rights_safety_risk=rights_risk,
        external_dependency_risk=external_risk,
        rollback_failure_risk=rollback_risk,
        human_error_risk=(
            "medium"
            if any(item.automation_eligibility == "human_execution_required" for item in strategies)
            else "low"
        ),
        blockers=[
            *(
                ["Rights or Safety Gate is blocked."]
                if rights_risk == "blocked"
                else []
            ),
            *(
                ["No strategy may execute without checkpoint, rollback, and validation."]
                if any(item.requires_command_execution for item in strategies)
                else []
            ),
        ],
        mitigations=[
            "Keep source media untouched.",
            "Prefer the smallest reversible strategy.",
            "Validate checkpoints before use.",
            "Reject any failed required validation or quality check.",
            "Require final human approval.",
        ],
        residual_risks=[
            "The supported cause may still be incomplete or wrong.",
            "A technically successful future action may still fail creative quality review.",
            "A different failure may appear during approved validation.",
        ],
        human_review_notes=[
            "Risk scores prioritize review and do not authorize execution.",
            "Blocked risk remains blocked until the responsible gate resolves it.",
        ],
        warnings=["No repair risk was accepted by Repair Planner."],
    )


def build_checkpoint_plan(
    case: BobaRootCauseAnalysisCaseV1,
    strategies: Sequence[BobaRepairStrategyV1],
    scope: BobaRepairScopeV1,
) -> BobaRepairCheckpointPlanV1:
    """Describe the checkpoint needed before any future repair."""

    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    recommended = next(
        (strategy for strategy in strategies if strategy.recommended),
        strategies[0] if strategies else None,
    )
    required = bool(recommended and recommended.requires_checkpoint)
    checkpoint_type: BobaRepairCheckpointTypeV1
    if not required:
        checkpoint_type = "none"
    elif scope == "configuration":
        checkpoint_type = "configuration_snapshot"
    elif scope == "code":
        checkpoint_type = "repository_branch"
    elif scope in {"workflow", "checkpoint"}:
        checkpoint_type = "workflow_checkpoint"
    elif scope == "environment":
        checkpoint_type = "generated_state_snapshot"
    elif scope == "human_decision":
        checkpoint_type = "none"
    else:
        checkpoint_type = "artifact_snapshot"
    artifacts = _unique(
        [
            case.primary_artifact,
            *case.affected_artifacts,
        ],
        limit=64,
        maximum=180,
    )
    return BobaRepairCheckpointPlanV1(
        checkpoint_plan_id=_stable_id("repair_checkpoint", repair_case_id),
        repair_case_id=repair_case_id,
        checkpoint_required=required,
        checkpoint_type=checkpoint_type,
        artifacts_to_preserve=artifacts,
        state_to_preserve=_unique(
            [
                "Root Cause Analyzer report and evidence references",
                "Current workflow and durable job checkpoint state",
                "Existing generated artifacts outside the repair scope",
                "Current non-secret configuration/version references",
                "Original output-quality comparison baseline",
            ],
            limit=64,
        ),
        source_media_must_remain_untouched=True,
        checkpoint_validation_required=required,
        checkpoint_success_conditions=(
            [
                "Checkpoint exists and is readable.",
                "Checkpoint schema and project identity match.",
                "Referenced generated artifacts exist and pass integrity checks.",
                "Required checksums or durable manifest references match.",
            ]
            if required
            else ["No non-read-only repair action is planned."]
        ),
        checkpoint_failure_conditions=(
            [
                "Checkpoint is missing, corrupt, stale, unvalidated, or belongs to "
                "another project.",
                "Required artifact references, checksums, or workflow state do not match.",
                "Source media protection cannot be guaranteed.",
            ]
            if required
            else ["A future plan becomes non-read-only without adding a checkpoint."]
        ),
        storage_requirements=[
            "Use existing local project storage with atomic publication.",
            "Do not store raw media copies in the Repair Planner artifact.",
            "Keep the checkpoint bounded to required state and references.",
        ],
        retention_notes=[
            "Retain the checkpoint through post-repair validation and human acceptance.",
            "Do not remove prior state until rollback is no longer required.",
        ],
        human_approval_required=True,
        warnings=[
            "Repair Planner did not create, validate, restore, or modify a checkpoint."
        ],
    )


def _rollback_scope(scope: BobaRepairScopeV1) -> BobaRepairRollbackScopeV1:
    mapping: dict[BobaRepairScopeV1, BobaRepairRollbackScopeV1] = {
        "no_repair": "none",
        "artifact": "artifact",
        "checkpoint": "workflow",
        "workflow": "workflow",
        "configuration": "configuration",
        "environment": "environment",
        "tool": "tool_selection",
        "dependency": "environment",
        "data_input": "artifact",
        "validation": "none",
        "rendering": "artifact",
        "code": "code_branch",
        "rights_permission": "none",
        "human_decision": "none",
        "unknown": "unknown",
    }
    return mapping[scope]


def build_rollback_plan(
    case: BobaRootCauseAnalysisCaseV1,
    strategies: Sequence[BobaRepairStrategyV1],
    checkpoint: BobaRepairCheckpointPlanV1,
    scope: BobaRepairScopeV1,
) -> BobaRepairRollbackPlanV1:
    """Define rollback before any future non-trivial repair."""

    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    rollback_required = any(
        strategy.requires_command_execution
        or strategy.requires_code_change
        or strategy.requires_configuration_change
        for strategy in strategies
    )
    rollback_scope = _rollback_scope(scope)
    return BobaRepairRollbackPlanV1(
        rollback_plan_id=_stable_id("repair_rollback", repair_case_id),
        repair_case_id=repair_case_id,
        rollback_required=rollback_required,
        rollback_scope=rollback_scope if rollback_required else "none",
        rollback_trigger_conditions=(
            [
                "Any required precondition or post-repair validation fails.",
                "Output quality is worse than the accepted baseline.",
                "Unexpected modules, artifacts, or source media are affected.",
                "A repeated failure, timeout, resource issue, or unknown state appears.",
                "Rights, safety, privacy, security, or approval status changes.",
            ]
            if rollback_required
            else ["A future non-read-only action is added to this plan."]
        ),
        rollback_steps=(
            [
                "Stop the affected workflow without deleting evidence.",
                "Preserve the failed repair result for bounded diagnosis.",
                "Restore the validated checkpoint or preserved generated state.",
                "Restore prior tool, workflow, configuration, environment, or branch selection.",
                "Revalidate artifact integrity, workflow state, rights, safety, "
                "and quality baseline.",
                "Keep the workflow paused for human review.",
            ]
            if rollback_required
            else ["Keep current state unchanged."]
        ),
        preserved_state_required=_unique(
            [
                *checkpoint.state_to_preserve,
                *checkpoint.artifacts_to_preserve,
            ],
            limit=32,
        ),
        rollback_validation=(
            [
                "Preserved artifacts match the checkpoint references.",
                "Workflow state is internally consistent and remains paused.",
                "Source media is unchanged.",
                "Prior validation and quality baseline remain available.",
            ]
            if rollback_required
            else ["No rollback validation is needed while no change occurs."]
        ),
        rollback_owner_module=(
            "code_surgeon"
            if scope == "code"
            else "checkpoint_recovery_manager"
            if rollback_required
            else "human_operator"
        ),
        destructive_rollback_blocked=True,
        human_approval_required=True,
        warnings=[
            "Repair Planner described rollback but did not execute it.",
            "Rollback must not delete source media or hide the failed repair.",
        ],
        limitations=[
            "Rollback feasibility must be verified by the responsible future module.",
            "An invalid or missing checkpoint cannot be used as rollback proof.",
        ],
    )


def _validation_check(
    repair_case_id: str,
    phase: BobaRepairValidationPhaseV1,
    category: BobaRepairValidationCategoryV1,
    description: str,
    validator: str,
    expected: str,
    *,
    command: bool = True,
) -> BobaRepairValidationCheckV1:
    return BobaRepairValidationCheckV1(
        validation_check_id=_stable_id(
            "repair_validation_check",
            repair_case_id,
            phase,
            category,
            description,
        ),
        phase=phase,
        category=category,
        description=description,
        validator_name=validator,
        expected_result=expected,
        required=True,
        blocks_acceptance_on_failure=True,
        requires_command_execution=command,
        requires_human_review=True,
        warnings=["Repair Planner described this check but did not run it."],
    )


def build_repair_validation_plan(
    case: BobaRootCauseAnalysisCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    strategies: Sequence[BobaRepairStrategyV1],
    checkpoint: BobaRepairCheckpointPlanV1,
    *,
    validator_registry: Sequence[str] = DEFAULT_VALIDATOR_REGISTRY,
) -> BobaRepairValidationPlanV1:
    """Create pre/post repair validation requirements without running validators."""

    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    selected = _selected_candidate(candidates)
    category = selected.category if selected else "unknown"
    pre = [
        _validation_check(
            repair_case_id,
            "pre_repair",
            "artifact_integrity",
            "Confirm required source and upstream artifacts are readable and unchanged.",
            "artifact_integrity",
            "All required inputs exist, are readable, and match expected references.",
        ),
        _validation_check(
            repair_case_id,
            "pre_repair",
            "safety",
            "Confirm the proposed future action is allowed by Safety Gate.",
            "safety",
            "Safety Gate explicitly permits the bounded action.",
            command=False,
        ),
        _validation_check(
            repair_case_id,
            "pre_repair",
            "rights_permission",
            "Confirm rights and permission allow the bounded future action.",
            "rights_permission",
            "Rights Gate records an approved state for the exact scope.",
            command=False,
        ),
    ]
    if checkpoint.checkpoint_required:
        pre.append(
            _validation_check(
                repair_case_id,
                "pre_repair",
                "checkpoint",
                "Validate checkpoint readability, schema, references, and project identity.",
                "checkpoint_integrity",
                "Checkpoint passes every required integrity check.",
            )
        )
    post = [
        _validation_check(
            repair_case_id,
            "post_repair",
            "artifact_integrity",
            "Validate repaired artifact existence, readability, size, and checksum "
            "where available.",
            "artifact_integrity",
            "Every required repaired artifact is valid and scoped correctly.",
        ),
        _validation_check(
            repair_case_id,
            "post_repair",
            "dependency",
            "Confirm upstream and downstream dependency references remain valid.",
            "dependency_integrity",
            "No unrelated dependency is stale, missing, or inconsistent.",
        ),
        _validation_check(
            repair_case_id,
            "post_repair",
            "output_quality",
            "Compare technical and creative output against the preserved baseline.",
            "output_quality",
            "No unacceptable degradation is present.",
        ),
        _validation_check(
            repair_case_id,
            "resume",
            "workflow",
            "Confirm every blocked stage prerequisite is valid before considering resume.",
            "workflow",
            "Workflow Controller receives a validated, gated resume recommendation only.",
        ),
    ]
    rendering_related = (
        category in {"rendering", "audio_video_sync", "media_probe", "resource_exhaustion"}
        or case.workflow_stage == "rendering"
        or case.primary_module == "rendering"
    )
    if rendering_related:
        post.extend(
            [
                _validation_check(
                    repair_case_id,
                    "post_repair",
                    "media_probe",
                    "Validate container, streams, codecs, resolution, frame rate, and duration.",
                    "ffprobe",
                    "The output is a readable expected-format media file.",
                ),
                _validation_check(
                    repair_case_id,
                    "post_repair",
                    "audio_video_sync",
                    "Validate audio/video duration delta and expected timeline duration.",
                    "audio_video_sync",
                    "A/V delta and duration remain within accepted tolerances.",
                ),
                _validation_check(
                    repair_case_id,
                    "post_repair",
                    "captions",
                    "Validate caption presence, timing, readability, and completeness.",
                    "caption_timing",
                    "Captions remain synchronized and readable.",
                ),
                _validation_check(
                    repair_case_id,
                    "post_repair",
                    "framing",
                    "Validate vertical framing, face/layout safety, and missing-frame risk.",
                    "framing",
                    "Framing remains intentional and no required subject is cut off.",
                ),
                _validation_check(
                    repair_case_id,
                    "post_repair",
                    "rendering",
                    "Confirm the canonical render manifest and every referenced MP4 are valid.",
                    "checkpoint_integrity",
                    "Manifest, checksums, MP4 files, and render truth all pass.",
                ),
            ]
        )
    if category == "code_defect" or any(
        strategy.requires_code_change for strategy in strategies
    ):
        post.extend(
            [
                _validation_check(
                    repair_case_id,
                    "post_repair",
                    "code_quality",
                    "Run approved lint, typing, and focused tests on a separate branch.",
                    "regression",
                    "All required code-quality checks pass without unrelated regressions.",
                ),
                _validation_check(
                    repair_case_id,
                    "post_repair",
                    "api",
                    "Validate affected API contracts and backward compatibility.",
                    "api",
                    "Affected API requests remain JSON-safe and compatible.",
                ),
                _validation_check(
                    repair_case_id,
                    "post_repair",
                    "frontend",
                    "Validate affected frontend types, tests, lint, and production build.",
                    "frontend",
                    "Frontend validation passes and truthful status remains visible.",
                ),
            ]
        )
    registered = set(validator_registry)
    names = _unique(
        [
            check.validator_name
            for check in [*pre, *post]
            if check.validator_name
        ],
        limit=32,
        maximum=160,
    )
    unavailable = [name for name in names if name not in registered]
    return BobaRepairValidationPlanV1(
        validation_plan_id=_stable_id("repair_validation", repair_case_id),
        repair_case_id=repair_case_id,
        pre_repair_checks=pre,
        post_repair_checks=post,
        required_validators=names,
        acceptance_criteria=[
            "Every required pre-repair and post-repair check passes.",
            "No source media or unrelated artifact changes.",
            "Checkpoint and rollback state remain valid.",
            "Output meets all non-negotiable technical and creative requirements.",
            "Rights and Safety gates approve the exact scope.",
            "A human approves the validated result.",
        ],
        rejection_criteria=[
            "Any required check fails, is missing, stale, or unknown.",
            "Output is corrupt, truncated, duplicated, unsynchronized, or lower quality.",
            "The action changes source media or exceeds the approved scope.",
            "Checkpoint or rollback validation fails.",
            "Rights, safety, security, privacy, or approval is unresolved.",
        ],
        comparison_baseline=[
            "Persisted pre-repair artifact and workflow references",
            "Original source timing, story meaning, and output specification",
            "Last validated checkpoint and successful equivalent run when available",
        ],
        regression_checks=[
            "Affected BOBA and Olympus unit tests",
            "Affected pipeline integration and durable checkpoint checks",
            "API JSON compatibility and frontend truth display",
        ],
        safety_checks=[
            "No destructive source or generated-state action",
            "No secret, credential, token, or private path exposure",
            "No hidden failure or quality degradation",
        ],
        rights_checks=[
            "Rights state is approved for the exact source and processing scope",
            "No platform, DRM, access-control, or permission bypass",
        ],
        output_quality_checks=[
            "Correct source section and complete story meaning",
            "No missing, duplicated, or truncated sections",
            "Expected technical media properties and A/V synchronization",
            "Readable captions and safe intentional framing",
        ],
        workflow_resume_checks=[
            "All required validations and quality checks passed",
            "Checkpoint and rollback state remain valid",
            "Rights and Safety gates approved",
            "Human approval is recorded",
            "Workflow Controller independently evaluates resume readiness",
        ],
        requires_validator_runner=bool(strategies),
        requires_human_review=True,
        warnings=[
            "Repair Planner ran no validator.",
            *(
                [
                    "Some described validator names are not in the bounded registry: "
                    + ", ".join(unavailable)
                ]
                if unavailable
                else []
            ),
        ],
    )


def build_quality_preservation_plan(
    case: BobaRootCauseAnalysisCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    strategies: Sequence[BobaRepairStrategyV1],
) -> BobaQualityPreservationPlanV1:
    """Define output acceptance independently from technical completion."""

    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    selected = _selected_candidate(candidates)
    output_sensitive = (
        case.workflow_stage in {"rendering", "editing", "optimization"}
        or case.primary_module in {"rendering", "editing", "optimization"}
        or (
            selected is not None
            and selected.category
            in {
                "rendering",
                "audio_video_sync",
                "media_probe",
                "resource_exhaustion",
                "tool_unavailable",
                "tool_failure",
                "code_defect",
            }
        )
        or any(
            strategy.requires_tool_fallback or strategy.requires_code_change
            for strategy in strategies
        )
    )
    return BobaQualityPreservationPlanV1(
        quality_preservation_plan_id=_stable_id("repair_quality", repair_case_id),
        repair_case_id=repair_case_id,
        original_requirements=[
            "Preserve the selected source section, story meaning, timing, and intended output.",
            "Preserve all truthful metadata about applied and unavailable effects.",
            "Preserve existing validated source and completed unrelated artifacts.",
        ],
        non_negotiable_requirements=[
            "Source media remains unchanged.",
            "Correct source section and complete story meaning are preserved.",
            "No missing, duplicated, frozen, or truncated required frames or audio.",
            "Expected duration, resolution, frame rate, audio presence, and codecs remain valid.",
            "A/V synchronization stays within the accepted tolerance.",
            "Captions remain readable, complete, and synchronized.",
            "Vertical framing and subject visibility remain intentional.",
            "Failures, unavailable effects, and degraded output remain honestly disclosed.",
        ],
        acceptable_degradations=[
            "Longer processing time or lower resource concurrency when output "
            "quality is unchanged.",
            "A disclosed implementation difference that preserves every non-negotiable result.",
        ],
        unacceptable_degradations=[
            "Silent reduction in resolution, frame rate, audio quality, captions, "
            "framing, or story completeness.",
            "Missing, duplicated, truncated, corrupt, or unsynchronized output.",
            "Fallback completion without equivalent technical and creative validation.",
            "Removal or concealment of warnings, failed checks, or unavailable effects.",
        ],
        comparison_metrics=[
            "Source start/end and final duration",
            "Container, video, and audio durations",
            "Resolution, frame rate, codecs, sample rate, and A/V delta",
            "Caption timing and readability",
            "Face/layout/framing status",
            "Story completeness and final payoff",
            "Rendered effect truth and validation warnings",
        ],
        creative_quality_checks=[
            "The clip still communicates the intended story and payoff.",
            "Pacing, hook, captions, framing, and ending remain coherent.",
            "A human reviewer accepts any disclosed creative difference.",
        ],
        technical_quality_checks=[
            "Artifact integrity and canonical manifest validation",
            "Media probe, duration, resolution, frame rate, codecs, and audio presence",
            "A/V sync, caption timing, framing, and no missing-frame validation",
            "Required unit, integration, API, and frontend regression checks",
        ],
        rights_safety_checks=[
            "The exact processing scope remains authorized.",
            "No gate, platform rule, DRM, access control, or safety warning is bypassed.",
        ],
        fallback_acceptance_rules=[
            "Fallback completion alone is never acceptance.",
            "The fallback must satisfy every non-negotiable technical and creative requirement.",
            "Any degradation must be disclosed and explicitly accepted by a human.",
            "Unacceptable degradation rejects the repaired output and triggers rollback.",
        ],
        human_review_required=True,
        warnings=[
            "Silent quality reduction is forbidden.",
            "Technical completion does not prove creative quality.",
            *(
                ["This case can directly affect rendered output quality."]
                if output_sensitive
                else ["Quality preservation still applies to downstream output."]
            ),
        ],
    )


def build_repair_approval_gate(
    case: BobaRootCauseAnalysisCaseV1,
    strategies: Sequence[BobaRepairStrategyV1],
    status: BobaRepairPlanningStatusV1,
) -> BobaRepairApprovalGateV1:
    """Keep every future executable action behind explicit approval."""

    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    actionable = any(strategy.requires_command_execution for strategy in strategies)
    rights_required = status == "intentional_safety_block" or any(
        strategy.requires_rights_review for strategy in strategies
    )
    if status == "repair_not_required":
        approval_status: BobaRepairApprovalStatusV1 = "not_required_for_no_action"
    elif status in {"intentional_safety_block", "blocked"}:
        approval_status = "blocked"
    else:
        approval_status = "planning_only"
    return BobaRepairApprovalGateV1(
        approval_gate_id=_stable_id("repair_approval", repair_case_id),
        repair_case_id=repair_case_id,
        approval_status=approval_status,
        required_approvals=_unique(
            [
                "Final human approval",
                *(
                    ["Rights + Permission Gate approval"]
                    if rights_required
                    else []
                ),
                *(
                    ["Safety Gate approval"]
                    if actionable or status != "repair_not_required"
                    else []
                ),
                *(
                    ["Code review approval"]
                    if any(strategy.requires_code_change for strategy in strategies)
                    else []
                ),
                *(
                    ["Environment or dependency-change approval"]
                    if any(
                        strategy.requires_package_installation
                        or strategy.requires_service_restart
                        for strategy in strategies
                    )
                    else []
                ),
                *(
                    ["Output Quality Reviewer approval"]
                    if actionable
                    else []
                ),
            ],
            limit=32,
        ),
        actions_allowed_without_approval=[
            "Read the saved Repair Planner report.",
            "Compare advisory strategies and rejected options.",
            "Export the bounded safe report.",
            "Keep processing stopped.",
        ],
        actions_requiring_approval=_unique(
            [
                "Any command, validator, repair, artifact change, retry, or workflow action",
                "Any configuration, environment, dependency, tool, or service change",
                "Any fallback selection or external/paid provider use",
                "Any code patch proposal, generation, application, or branch operation",
                "Any workflow resume or acceptance of changed output",
            ],
            limit=32,
        ),
        prohibited_actions=_prohibited_actions(),
        rights_gate_required=rights_required,
        safety_gate_required=status != "repair_not_required",
        code_review_required=any(strategy.requires_code_change for strategy in strategies),
        rollback_plan_required=actionable,
        validation_plan_required=bool(strategies),
        output_quality_review_required=actionable,
        final_human_approval_required=True,
        warnings=[
            "Repair Planner grants no execution approval.",
            "Planning status does not authorize any future module to act.",
        ],
    )


def build_repair_execution_handoffs(
    case: BobaRootCauseAnalysisCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    strategies: Sequence[BobaRepairStrategyV1],
    checkpoint: BobaRepairCheckpointPlanV1,
    rollback: BobaRepairRollbackPlanV1,
    validation: BobaRepairValidationPlanV1,
    quality: BobaQualityPreservationPlanV1,
    approval: BobaRepairApprovalGateV1,
    status: BobaRepairPlanningStatusV1,
    workflow_impact: BobaWorkflowImpactAnalysisV1 | None,
) -> list[BobaRepairExecutionHandoffV1]:
    """Prepare non-applying handoffs for future approved modules."""

    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    selected = _selected_candidate(candidates)
    recommended = next(
        (strategy for strategy in strategies if strategy.recommended),
        strategies[0] if strategies else None,
    )
    candidate_score = selected.likelihood_score if selected else 0.25
    blocked = status in {"intentional_safety_block", "blocked"}
    priority = _priority(candidate_score, blocked)
    common_quality = _unique(
        [
            *quality.non_negotiable_requirements,
            "Failed or missing validation rejects acceptance.",
        ],
        limit=20,
    )
    common_constraints = [
        "Use only the approved bounded repair scope.",
        "Keep source media and unrelated artifacts unchanged.",
        "Validate checkpoint and rollback before any non-read-only action.",
        "Preserve errors, warnings, evidence, and output-quality truth.",
        "Do not resume workflow until every gate and required check passes.",
    ]
    common_prohibited = _prohibited_actions()
    handoffs: list[BobaRepairExecutionHandoffV1] = []
    seen: set[BobaRepairHandoffTargetV1] = set()

    def add(
        target: BobaRepairHandoffTargetV1,
        reason: str,
        capability: str,
        *,
        strategy: BobaRepairStrategyV1 | None = recommended,
        inputs: Sequence[str] = (),
        constraints: Sequence[str] = (),
        warnings: Sequence[str] = (),
    ) -> None:
        if target in seen or len(handoffs) >= 20:
            return
        seen.add(target)
        handoffs.append(
            BobaRepairExecutionHandoffV1(
                handoff_id=_stable_id(
                    "repair_handoff",
                    repair_case_id,
                    target,
                    strategy.repair_strategy_id if strategy else "",
                ),
                repair_case_id=repair_case_id,
                repair_strategy_id=(
                    strategy.repair_strategy_id if strategy else ""
                ),
                target_module=target,
                reason=_safe_text(reason),
                required_inputs=_unique(
                    [
                        "Supported candidate: "
                        f"{selected.candidate_summary if selected else 'not selected'}",
                        f"Repair strategy: {strategy.title if strategy else 'manual review'}",
                        *inputs,
                    ],
                    limit=32,
                ),
                required_capability=_safe_text(capability),
                required_quality_properties=common_quality,
                constraints=_unique(
                    [*common_constraints, *constraints],
                    limit=32,
                ),
                prohibited_actions=common_prohibited,
                checkpoint_plan_id=checkpoint.checkpoint_plan_id,
                rollback_plan_id=rollback.rollback_plan_id,
                validation_plan_id=validation.validation_plan_id,
                approval_gate_id=approval.approval_gate_id,
                apply_automatically=False,
                human_approval_required=True,
                priority=priority,
                warnings=_unique(
                    [
                        *warnings,
                        "The target module was not invoked.",
                        "This handoff does not authorize execution.",
                    ],
                    limit=24,
                ),
            )
        )

    tool_strategies = [
        strategy
        for strategy in strategies
        if strategy.strategy_type
        in {
            "retry_same_tool",
            "retry_with_safe_settings",
            "reduce_resource_usage",
            "use_registered_tool_fallback",
        }
    ]
    if tool_strategies:
        strategy = tool_strategies[0]
        add(
            "tool_recovery_brain",
            "A bounded retry or compatible tool recovery option needs future capability analysis.",
            "Recover the required tool capability within the finite attempt and time budget.",
            strategy=strategy,
            inputs=[
                f"Maximum attempts: {strategy.maximum_attempts or 0}",
                "Maximum recovery duration seconds: "
                f"{strategy.maximum_recovery_duration_seconds or 0}",
                "Previously attempted strategies: "
                + (", ".join(strategy.previously_attempted_strategies) or "none known"),
                f"Escalation condition: {strategy.escalation_condition}",
            ],
            constraints=[
                "Use only registered compatible tools.",
                "Do not download, install, activate, or execute a fallback without approval.",
                "Fallback completion alone does not satisfy acceptance.",
            ],
            warnings=["Repair Planner selected and executed no fallback tool."],
        )
    code_strategy = next(
        (strategy for strategy in strategies if strategy.requires_code_change),
        None,
    )
    if code_strategy and selected and (
        selected.category == "code_defect"
        and selected.evidence_quality in {"strong", "moderate"}
        and selected.confidence >= 0.72
    ):
        add(
            "code_surgeon",
            "Strong code-defect evidence supports a future scoped patch review.",
            "Prepare a minimal patch on a separate branch with tests and rollback.",
            strategy=code_strategy,
            inputs=[
                "Direct supporting and conflicting evidence references",
                "Affected module and bounded repair target",
                "Required lint, typing, focused, integration, API, and frontend checks",
            ],
            constraints=[
                "Create a separate branch before any patch.",
                "Never patch main directly.",
                "Generate no patch until separately approved.",
                "Preserve a clean rollback path.",
            ],
            warnings=["Repair Planner generated no patch and modified no code."],
        )
    if validation.requires_validator_runner:
        add(
            "validator_runner",
            "Required pre-repair, post-repair, rollback, and resume checks need future execution.",
            "Execute approved validators and return unmodified pass/fail truth.",
            inputs=[
                "Required validators: " + ", ".join(validation.required_validators),
                "Acceptance criteria: " + "; ".join(validation.acceptance_criteria),
                "Rejection criteria: " + "; ".join(validation.rejection_criteria),
            ],
            constraints=[
                "Missing, stale, unknown, or failed validation is not a pass.",
                "Do not modify the target while validating it.",
            ],
            warnings=["Repair Planner ran no validator."],
        )
    if checkpoint.checkpoint_required or any(
        strategy.strategy_type
        in {
            "restore_checkpoint",
            "resume_from_checkpoint",
            "regenerate_artifact",
            "repair_generated_state",
        }
        for strategy in strategies
    ):
        checkpoint_strategy = next(
            (
                strategy
                for strategy in strategies
                if strategy.strategy_type
                in {
                    "restore_checkpoint",
                    "resume_from_checkpoint",
                    "regenerate_artifact",
                    "repair_generated_state",
                }
            ),
            recommended,
        )
        add(
            "checkpoint_recovery_manager",
            "The plan requires validated preserved state before restore, regeneration, or resume.",
            "Validate the checkpoint, snapshot, restore, or regenerate only the "
            "approved generated scope.",
            strategy=checkpoint_strategy,
            inputs=[
                f"Checkpoint type: {checkpoint.checkpoint_type}",
                "Artifacts to preserve: " + ", ".join(checkpoint.artifacts_to_preserve),
                "Checkpoint success conditions: "
                + "; ".join(checkpoint.checkpoint_success_conditions),
                "Rollback triggers: " + "; ".join(rollback.rollback_trigger_conditions),
            ],
            constraints=[
                "Reject missing, corrupt, stale, or unvalidated checkpoints.",
                "Never overwrite source media.",
            ],
            warnings=["No checkpoint was created, restored, or modified."],
        )
    if any(
        strategy.strategy_type
        in {
            "regenerate_artifact",
            "repair_generated_state",
            "restore_checkpoint",
            "collect_more_evidence",
        }
        for strategy in strategies
    ):
        add(
            "artifact_inspector",
            "Artifact state must be inspected read-only before any scoped recovery.",
            "Inspect bounded artifact identity, integrity, schema, and dependency references.",
            inputs=[
                f"Target artifact: {case.primary_artifact or 'unknown'}",
                "Affected artifacts: " + ", ".join(case.affected_artifacts),
            ],
            warnings=["Repair Planner did not read or modify arbitrary project files."],
        )
    if any(
        strategy.strategy_type == "collect_more_evidence"
        for strategy in strategies
    ):
        add(
            "report_reader",
            "Saved evidence or validation reports need bounded interpretation.",
            "Read approved saved reports without modifying or executing them.",
            inputs=[
                "Root Cause Analyzer evidence gaps and verification references",
                "Expected schema and bounded status fields",
            ],
        )
    output_affected = any(
        strategy.requires_command_execution
        or strategy.requires_tool_fallback
        or strategy.requires_code_change
        for strategy in strategies
    )
    if output_affected:
        add(
            "output_quality_reviewer",
            "Any future repaired or fallback output must pass technical and creative review.",
            "Compare repaired output against every non-negotiable baseline requirement.",
            inputs=[
                "Technical checks: " + "; ".join(quality.technical_quality_checks),
                "Creative checks: " + "; ".join(quality.creative_quality_checks),
                "Unacceptable degradations: "
                + "; ".join(quality.unacceptable_degradations),
            ],
            constraints=[
                "Reject silent degradation.",
                "Do not accept output only because a tool completed.",
            ],
        )
    if status != "repair_not_required" or output_affected:
        add(
            "safety_gate",
            "Potentially executable future steps require safety review.",
            "Approve or block the exact proposed scope using saved constraints.",
            inputs=[
                "Proposed future steps and prohibited actions",
                "Checkpoint, rollback, validation, and approval requirements",
            ],
            warnings=["Repair Planner did not invoke or bypass Safety Gate."],
        )
    if (
        status == "intentional_safety_block"
        or approval.rights_gate_required
        or any(strategy.requires_rights_review for strategy in strategies)
    ):
        add(
            "rights_permission_gate",
            "Rights, permission, or authorization remains unresolved or blocked.",
            "Review rights evidence and keep processing stopped unless explicitly approved.",
            inputs=[
                "Source identity and requested processing scope",
                "Human-reviewed ownership or permission evidence",
            ],
            constraints=["Never bypass platform restrictions, DRM, or access controls."],
            warnings=["A rights block is not a software defect."],
        )
    blocked_stages = workflow_impact.blocked_stages if workflow_impact else []
    if blocked_stages or any(
        strategy.strategy_type
        in {"resume_from_checkpoint", "switch_safe_workflow_path"}
        for strategy in strategies
    ):
        add(
            "workflow_controller",
            "Workflow state may be reconsidered only after all required gates and checks pass.",
            "Evaluate resume readiness without receiving automatic authorization.",
            inputs=[
                "Blocked stages: " + ", ".join(blocked_stages),
                "Workflow resume checks: "
                + "; ".join(validation.workflow_resume_checks),
            ],
            constraints=[
                "Do not resume automatically.",
                "Keep failed or unknown checkpoint state blocked.",
            ],
            warnings=["Repair Planner did not authorize or perform workflow resume."],
        )
    human_needed = (
        status
        in {
            "conditional_plan",
            "conflicting_causes",
            "human_decision_required",
            "intentional_safety_block",
            "blocked",
        }
        or any(
            strategy.requires_configuration_change
            or strategy.requires_package_installation
            or strategy.requires_service_restart
            or strategy.requires_external_access
            or strategy.requires_paid_service
            or strategy.requires_code_change
            for strategy in strategies
        )
    )
    if human_needed:
        add(
            "human_operator",
            "The plan contains uncertainty, approval, environment, code, quality, "
            "or rights decisions.",
            "Review the complete bounded plan and explicitly approve or reject future actions.",
            inputs=[
                "Recommended and alternative strategies",
                "Risk, checkpoint, rollback, validation, quality, and approval plans",
                "Rejected unsafe strategies and unresolved questions",
            ],
        )
    return handoffs


def _expected_workflow_impact(
    impact: BobaWorkflowImpactAnalysisV1 | None,
) -> str:
    if impact is None:
        return (
            "Workflow effect is unknown; keep affected processing blocked until validation."
        )
    blocked = ", ".join(impact.blocked_stages) or "none recorded"
    degraded = ", ".join(impact.degraded_stages) or "none recorded"
    return _safe_text(
        f"Blocked stages: {blocked}. Degraded stages: {degraded}. "
        "Resume remains conditional on checkpoint, validation, quality, rights, safety, "
        "and human approval."
    )


def _build_repair_case(
    case: BobaRootCauseAnalysisCaseV1,
    candidates: Sequence[BobaRootCauseCandidateV1],
    status: BobaRepairPlanningStatusV1,
    repair_needed: bool,
    scope: BobaRepairScopeV1,
    blocked_reason: str,
    confidence: float,
    strategies: Sequence[BobaRepairStrategyV1],
    rejected: Sequence[BobaRepairRejectedStrategyV1],
    risk: BobaRepairRiskAssessmentV1,
    checkpoint: BobaRepairCheckpointPlanV1,
    rollback: BobaRepairRollbackPlanV1,
    validation: BobaRepairValidationPlanV1,
    quality: BobaQualityPreservationPlanV1,
    approval: BobaRepairApprovalGateV1,
    handoffs: Sequence[BobaRepairExecutionHandoffV1],
    workflow_impact: BobaWorkflowImpactAnalysisV1 | None,
) -> BobaRepairPlanningCaseV1:
    repair_case_id = _stable_id("repair_case", case.analysis_case_id)
    selected = _selected_candidate(candidates)
    recommended = next(
        (strategy for strategy in strategies if strategy.recommended),
        strategies[0] if strategies else None,
    )
    alternatives = [
        strategy.repair_strategy_id
        for strategy in strategies
        if recommended is None
        or strategy.repair_strategy_id != recommended.repair_strategy_id
    ]
    if status in {"conflicting_causes", "conditional_plan"}:
        recommended_strategy_id = ""
        alternatives = [strategy.repair_strategy_id for strategy in strategies]
    else:
        recommended_strategy_id = (
            recommended.repair_strategy_id if recommended else ""
        )
    return BobaRepairPlanningCaseV1(
        repair_case_id=repair_case_id,
        source_analysis_case_id=case.analysis_case_id,
        title=case.title,
        primary_module=case.primary_module,
        primary_artifact=case.primary_artifact,
        workflow_stage=case.workflow_stage,
        root_cause_candidate_ids=[
            candidate.root_cause_candidate_id for candidate in candidates
        ],
        selected_root_cause_candidate_id=(
            selected.root_cause_candidate_id if selected else ""
        ),
        selected_root_cause_summary=(
            selected.candidate_summary if selected else case.most_likely_root_cause
        ),
        planning_status=status,
        repair_needed=repair_needed,
        repair_scope=scope,
        blocked_reason=blocked_reason,
        strategy_ids=[strategy.repair_strategy_id for strategy in strategies],
        recommended_strategy_id=recommended_strategy_id,
        alternative_strategy_ids=alternatives,
        rejected_strategy_ids=[
            strategy.rejected_strategy_id for strategy in rejected
        ],
        risk_assessment_id=risk.risk_assessment_id,
        checkpoint_plan_id=checkpoint.checkpoint_plan_id,
        rollback_plan_id=rollback.rollback_plan_id,
        validation_plan_id=validation.validation_plan_id,
        quality_preservation_plan_id=quality.quality_preservation_plan_id,
        approval_gate_id=approval.approval_gate_id,
        execution_handoff_ids=[handoff.handoff_id for handoff in handoffs],
        expected_workflow_impact=_expected_workflow_impact(workflow_impact),
        human_review_required=True,
        confidence=confidence,
        warnings=[
            "Repair Planner created advisory options only.",
            "A recommended strategy is not proof that repair will succeed.",
            *(
                ["Competing causes prevent final strategy selection."]
                if status in {"conflicting_causes", "conditional_plan"}
                else []
            ),
        ],
        limitations=[
            "No strategy, command, validator, patch, fallback, restart, installation, "
            "artifact change, or workflow resume was executed.",
            "Future modules must independently validate every precondition and gate.",
        ],
    )


def _empty_analysis_case(project_id: str) -> BobaRootCauseAnalysisCaseV1:
    return BobaRootCauseAnalysisCaseV1(
        analysis_case_id=_stable_id("root_analysis_case", project_id, "empty"),
        source_diagnostic_case_id="root_cause_analyzer_empty",
        title="Root Cause Analyzer contains no analysis cases",
        primary_module="root_cause_analyzer",
        primary_artifact="root_cause_analyzer",
        workflow_stage="self_healing",
        analysis_status="insufficient_evidence",
        earliest_known_failure="No failure event is available.",
        most_likely_root_cause="No root-cause candidate is available.",
        root_cause_confidence=0.0,
        confirmed_facts=[],
        probable_inferences=[],
        unresolved_hypotheses=["Generate or review Root Cause Analyzer evidence manually."],
        contributing_factor_ids=[],
        downstream_symptom_ids=[],
        affected_modules=["root_cause_analyzer"],
        affected_artifacts=["root_cause_analyzer"],
        failure_timeline_id="",
        causal_graph_id="",
        evidence_gap_ids=[],
        verification_plan_ids=[],
        processing_impact="unknown",
        safety_impact="human_review_needed",
        recommended_handoff="human_operator",
        human_review_required=True,
        warnings=["No repair cause was fabricated."],
        limitations=["The saved analyzer report contains no analysis cases."],
    )


def _planner_summary(
    source: BobaRootCauseAnalyzerSetV1 | None,
    cases: Sequence[BobaRepairPlanningCaseV1],
    strategies: Sequence[BobaRepairStrategyV1],
    risks: Sequence[BobaRepairRiskAssessmentV1],
    quality_plans: Sequence[BobaQualityPreservationPlanV1],
    handoffs: Sequence[BobaRepairExecutionHandoffV1],
    *,
    unavailable_reason: str = "",
) -> BobaRepairPlannerSummaryV1:
    statuses = [case.planning_status for case in cases]
    highest_risk = (
        max(risks, key=lambda item: _risk_rank(item.overall_risk))
        if risks
        else None
    )
    safest = (
        min(
            strategies,
            key=lambda strategy: (
                _risk_rank(strategy.estimated_risk),
                -strategy.strategy_score,
                strategy.repair_strategy_id,
            ),
        )
        if strategies
        else None
    )
    reversible_order = {
        "fully_reversible": 0,
        "mostly_reversible": 1,
        "partially_reversible": 2,
        "difficult_to_reverse": 3,
        "irreversible": 4,
        "unknown": 5,
    }
    most_reversible = (
        min(
            strategies,
            key=lambda strategy: (
                reversible_order[strategy.reversibility],
                _risk_rank(strategy.estimated_risk),
                -strategy.strategy_score,
            ),
        )
        if strategies
        else None
    )
    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    handoff = (
        min(
            handoffs,
            key=lambda item: (
                priority_order[item.priority],
                item.handoff_id,
            ),
        )
        if handoffs
        else None
    )
    unresolved = _unique(
        [
            unavailable_reason,
            *[
                case.blocked_reason
                for case in cases
                if case.blocked_reason
            ],
        ],
        limit=64,
    )
    return BobaRepairPlannerSummaryV1(
        total_analysis_cases=len(source.analysis_cases) if source else 0,
        total_repair_cases=len(cases),
        plan_ready_count=statuses.count("plan_ready"),
        conditional_plan_count=(
            statuses.count("conditional_plan")
            + statuses.count("conflicting_causes")
        ),
        needs_more_evidence_count=statuses.count("needs_more_evidence"),
        safety_block_count=statuses.count("intentional_safety_block"),
        human_decision_count=statuses.count("human_decision_required"),
        repair_not_required_count=statuses.count("repair_not_required"),
        blocked_count=statuses.count("blocked"),
        tool_recovery_handoff_count=sum(
            handoff.target_module == "tool_recovery_brain" for handoff in handoffs
        ),
        code_surgeon_handoff_count=sum(
            handoff.target_module == "code_surgeon" for handoff in handoffs
        ),
        validator_handoff_count=sum(
            handoff.target_module == "validator_runner" for handoff in handoffs
        ),
        highest_risk_case=(
            f"{highest_risk.repair_case_id}: {highest_risk.overall_risk}"
            if highest_risk
            else ""
        ),
        safest_repair_strategy=(
            f"{safest.title} ({safest.estimated_risk}, score {safest.strategy_score})"
            if safest
            else ""
        ),
        most_reversible_strategy=(
            f"{most_reversible.title} ({most_reversible.reversibility})"
            if most_reversible
            else ""
        ),
        strongest_quality_preservation_plan=(
            quality_plans[0].quality_preservation_plan_id
            if quality_plans
            else ""
        ),
        highest_priority_handoff=(
            f"{handoff.target_module}: {handoff.reason}" if handoff else ""
        ),
        unresolved_questions=unresolved,
        human_review_notes=[
            "All Repair Planner output is advisory.",
            "Highest-ranked does not mean guaranteed or approved.",
            "Human approval is required before verification or repair execution.",
        ],
    )


def _missing_report(
    project_id: str,
    source_id: str,
    warnings: Sequence[str],
) -> BobaRepairPlannerSetV1:
    reason = (
        warnings[0]
        if warnings
        else "A persisted Root Cause Analyzer V1 report is unavailable."
    )
    return BobaRepairPlannerSetV1(
        project_id=project_id,
        source_id=_safe_text(source_id, maximum=512) or project_id,
        root_cause_analyzer_source="unavailable",
        repair_cases=[],
        repair_strategies=[],
        risk_assessments=[],
        checkpoint_plans=[],
        rollback_plans=[],
        validation_plans=[],
        quality_preservation_plans=[],
        approval_gates=[],
        execution_handoffs=[],
        rejected_strategies=[],
        planner_summary=_planner_summary(
            None,
            [],
            [],
            [],
            [],
            [],
            unavailable_reason=(
                f"{reason} Generate Root Cause Analyzer manually before repair planning."
            ),
        ),
        signal_usage=BobaRepairPlannerSignalUsageV1(
            root_cause_analyzer_used=False,
            root_cause_artifact_read=False,
            checkpoint_system_inspected=False,
            validation_registry_inspected=False,
            unavailable_signals=[
                "root_cause_analyzer",
                "repair_eligibility",
                "repair_strategies",
            ],
            warnings=[
                "No upstream diagnostic module was regenerated automatically.",
                "No repair case was fabricated.",
            ],
        ),
        warnings=_unique(
            [
                *warnings,
                "Generate BOBA Root Cause Analyzer V1 manually before repair planning.",
            ],
            limit=64,
        ),
        limitations=[
            "Repair planning cannot proceed without a valid persisted Root Cause Analyzer report.",
            "No upstream module, validator, command, repair, fallback, restart, installation, "
            "or workflow action ran.",
        ],
    )


class BobaRepairPlannerV1:
    """Create ranked advisory repair plans from persisted causal analysis."""

    def __init__(
        self,
        *,
        module_registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
        tool_capability_registry: Sequence[str] | None = None,
        validator_registry: Sequence[str] | None = None,
        checkpoint_registry: Sequence[str] | None = None,
    ) -> None:
        self.module_registry = tuple(
            module_registry or build_boba_artifact_registry()
        )
        self.tool_capability_registry = tuple(
            tool_capability_registry or DEFAULT_TOOL_CAPABILITY_REGISTRY
        )
        self.validator_registry = tuple(
            validator_registry or DEFAULT_VALIDATOR_REGISTRY
        )
        self.checkpoint_registry = tuple(
            checkpoint_registry or DEFAULT_CHECKPOINT_REGISTRY
        )

    def plan(
        self,
        project_id: str,
        root_cause_analyzer: (
            BobaRootCauseAnalyzerSetV1 | Mapping[str, Any] | None
        ),
        *,
        source_id: str | None = None,
        manual_context: Mapping[str, Any] | None = None,
        dry_run: bool = False,
    ) -> BobaRepairPlannerSetV1:
        """Plan future repair options without executing or modifying anything."""

        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError(
                "Project id is invalid.",
                details={"project_id": project_id},
            )
        source, coercion_warnings = _coerce_root_report(root_cause_analyzer)
        effective_source_id = source_id or (
            source.source_id if source is not None else project_id
        )
        if source is None:
            return _missing_report(
                project_id,
                effective_source_id,
                coercion_warnings,
            )
        context = _bounded_context(manual_context)
        source_cases = list(source.analysis_cases[:256])
        empty_source = not source_cases
        if empty_source:
            source_cases = [_empty_analysis_case(project_id)]
        impacts_by_case = {
            impact.analysis_case_id: impact
            for impact in source.workflow_impacts
        }
        all_cases: list[BobaRepairPlanningCaseV1] = []
        all_strategies: list[BobaRepairStrategyV1] = []
        all_risks: list[BobaRepairRiskAssessmentV1] = []
        all_checkpoints: list[BobaRepairCheckpointPlanV1] = []
        all_rollbacks: list[BobaRepairRollbackPlanV1] = []
        all_validations: list[BobaRepairValidationPlanV1] = []
        all_quality: list[BobaQualityPreservationPlanV1] = []
        all_approvals: list[BobaRepairApprovalGateV1] = []
        all_handoffs: list[BobaRepairExecutionHandoffV1] = []
        all_rejected: list[BobaRepairRejectedStrategyV1] = []
        for source_case in source_cases:
            case, candidates = normalize_root_cause_case(
                source_case,
                source.root_cause_candidates,
            )
            case_context = _case_context(context, case)
            (
                status,
                repair_needed,
                scope,
                blocked_reason,
                confidence,
            ) = determine_repair_eligibility(
                case,
                candidates,
                planning_context=case_context,
            )
            strategies = generate_repair_strategies(
                case,
                candidates,
                status,
                planning_context=case_context,
            )
            rejected = reject_unsafe_repair_strategies(
                case,
                strategies,
                planning_context=case_context,
            )
            risk = assess_repair_risks(case, strategies, status)
            checkpoint = build_checkpoint_plan(case, strategies, scope)
            rollback = build_rollback_plan(
                case,
                strategies,
                checkpoint,
                scope,
            )
            validation = build_repair_validation_plan(
                case,
                candidates,
                strategies,
                checkpoint,
                validator_registry=self.validator_registry,
            )
            quality = build_quality_preservation_plan(
                case,
                candidates,
                strategies,
            )
            approval = build_repair_approval_gate(case, strategies, status)
            workflow_impact = impacts_by_case.get(case.analysis_case_id)
            handoffs = build_repair_execution_handoffs(
                case,
                candidates,
                strategies,
                checkpoint,
                rollback,
                validation,
                quality,
                approval,
                status,
                workflow_impact,
            )
            repair_case = _build_repair_case(
                case,
                candidates,
                status,
                repair_needed,
                scope,
                blocked_reason,
                confidence,
                strategies,
                rejected,
                risk,
                checkpoint,
                rollback,
                validation,
                quality,
                approval,
                handoffs,
                workflow_impact,
            )
            all_cases.append(repair_case)
            all_strategies.extend(strategies)
            all_risks.append(risk)
            all_checkpoints.append(checkpoint)
            all_rollbacks.append(rollback)
            all_validations.append(validation)
            all_quality.append(quality)
            all_approvals.append(approval)
            all_handoffs.extend(handoffs)
            all_rejected.extend(rejected)
        rights_used = any(
            case.safety_impact
            in {
                "human_review_needed",
                "safety_gate_blocked",
                "rights_gate_blocked",
                "destructive_risk",
            }
            for case in source.analysis_cases
        )
        report = BobaRepairPlannerSetV1(
            project_id=project_id,
            source_id=_safe_text(effective_source_id, maximum=512) or project_id,
            root_cause_analyzer_source=(
                f"root_cause_analyzer:{source.project_id}:{source.schema_version}"
            ),
            repair_cases=all_cases,
            repair_strategies=all_strategies,
            risk_assessments=all_risks,
            checkpoint_plans=all_checkpoints,
            rollback_plans=all_rollbacks,
            validation_plans=all_validations,
            quality_preservation_plans=all_quality,
            approval_gates=all_approvals,
            execution_handoffs=all_handoffs,
            rejected_strategies=all_rejected,
            planner_summary=_planner_summary(
                source,
                all_cases,
                all_strategies,
                all_risks,
                all_quality,
                all_handoffs,
                unavailable_reason=(
                    "The saved Root Cause Analyzer report contains no analysis cases."
                    if empty_source
                    else ""
                ),
            ),
            signal_usage=BobaRepairPlannerSignalUsageV1(
                root_cause_analyzer_used=True,
                root_cause_artifact_read=True,
                failure_timelines_used=bool(source.failure_timelines),
                causal_graphs_used=bool(source.causal_graphs),
                root_cause_candidates_used=bool(source.root_cause_candidates),
                verification_plans_used=bool(source.verification_plans),
                workflow_impacts_used=bool(source.workflow_impacts),
                rights_safety_evidence_used=rights_used,
                checkpoint_system_inspected=bool(self.checkpoint_registry),
                validation_registry_inspected=bool(self.validator_registry),
                bounded_manual_context_used=bool(context),
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
                workflow_resume_used=False,
                service_restart_used=False,
                package_installation_used=False,
                destructive_action_used=False,
                fallback_used=False,
                unavailable_signals=_unique(
                    [
                        *(
                            ["root_cause_candidates"]
                            if not source.root_cause_candidates
                            else []
                        ),
                        *(
                            ["failure_timelines"]
                            if not source.failure_timelines
                            else []
                        ),
                        *(
                            ["causal_graphs"]
                            if not source.causal_graphs
                            else []
                        ),
                    ],
                    limit=64,
                ),
                warnings=[
                    "No command, validator, repair, patch, artifact change, fallback, "
                    "workflow resume, restart, installation, download, or external API ran.",
                    *(
                        ["Dry run was requested; persistence belongs to the caller."]
                        if dry_run
                        else []
                    ),
                ],
            ),
            warnings=_unique(
                [
                    *coercion_warnings,
                    *(
                        [
                            "The saved analyzer report was empty; only a needs-more-evidence "
                            "plan was created."
                        ]
                        if empty_source
                        else []
                    ),
                    "BOBA Repair Planner V1 creates plans only and executes no strategy.",
                    "A repair plan is not proof that the repair will succeed.",
                    "Approved repairs must pass validation and output-quality review before "
                    "Olympus continues.",
                ],
                limit=64,
            ),
            limitations=[
                "Planning is bounded to persisted Root Cause Analyzer output, static local "
                "registries, and optional bounded manual context.",
                "No real repair, code patch, command, validator, artifact modification, tool "
                "fallback, workflow resume, service restart, package installation, rendering, "
                "media operation, or external request occurred.",
                "Future modules and humans must independently approve and verify every action.",
            ],
        )
        report.model_dump(mode="json")
        return report

    def analyze(
        self,
        project_id: str,
        root_cause_analyzer: (
            BobaRootCauseAnalyzerSetV1 | Mapping[str, Any] | None
        ),
        *,
        source_id: str | None = None,
        manual_context: Mapping[str, Any] | None = None,
        dry_run: bool = False,
    ) -> BobaRepairPlannerSetV1:
        """Compatibility alias for the planning entry point."""

        return self.plan(
            project_id,
            root_cause_analyzer,
            source_id=source_id,
            manual_context=manual_context,
            dry_run=dry_run,
        )


def generate_boba_repair_planner(
    project_id: str,
    root_cause_analyzer: BobaRootCauseAnalyzerSetV1 | Mapping[str, Any] | None,
    *,
    source_id: str | None = None,
    manual_context: Mapping[str, Any] | None = None,
    dry_run: bool = False,
) -> BobaRepairPlannerSetV1:
    """Generate one local advisory Repair Planner V1 report."""

    return BobaRepairPlannerV1().plan(
        project_id,
        root_cause_analyzer,
        source_id=source_id,
        manual_context=manual_context,
        dry_run=dry_run,
    )

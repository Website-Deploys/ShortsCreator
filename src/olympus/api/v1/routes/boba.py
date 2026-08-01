"""Inspection-only API routes for BOBA Core Brain V1."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from olympus.api.dependencies import (
    BobaIntegrationDep,
    PersonalizationServiceDep,
    SettingsDep,
)
from olympus.boba.approvals import BobaApprovalDecision
from olympus.boba.autopilot_controller import (
    BobaAutopilotControlModeV1,
    BobaAutopilotTriggerV1,
)
from olympus.boba.code_surgeon import (
    BobaCodeApprovalRecordV1,
    BobaCodeProposalSourceV1,
)
from olympus.boba.creator_learning import (
    BobaCreatorFeedbackEventType,
    BobaCreatorFeedbackTargetType,
    BobaCreatorUserAction,
)
from olympus.boba.creator_memory import build_and_save_creator_memory
from olympus.boba.experimentation import BobaExperimentOutcomeLabel
from olympus.boba.global_memory import build_and_save_global_memory
from olympus.boba.integration_layer import (
    BobaIntegrationApprovalBindingV1,
    BobaIntegrationArtifactReferenceV1,
    BobaIntegrationSafetyBindingV1,
)
from olympus.boba.memory_contracts import BobaMemoryQueryV1
from olympus.boba.memory_learning import BobaMemoryLearner
from olympus.boba.output_quality_reviewer import (
    BobaOutputComparisonBasisV1,
    BobaOutputReviewModeV1,
)
from olympus.boba.performance_feedback import (
    BobaManualPerformanceMetricsV1,
    BobaPerformanceEventType,
    BobaPerformanceOutcomeLabel,
    BobaPerformanceTargetType,
)
from olympus.boba.scout import BobaCandidateV1
from olympus.boba.tool_recovery import BobaToolRecoveryApprovalV1
from olympus.boba.workflow_controller import (
    BobaWorkflowPauseCategoryV1,
    BobaWorkflowTransitionTypeV1,
)
from olympus.platform.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/boba", tags=["boba"])


class EditorialPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str = Field(min_length=1, max_length=128)


class MemoryFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1, max_length=80)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    rating: dict[str, Any] | str = "neutral"
    labels: list[str] = Field(default_factory=list, max_length=24)
    notes: str = Field(default="", max_length=500)
    clip_traits: dict[str, Any] = Field(default_factory=dict)


class MemoryImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    payload: dict[str, Any]


class MemoryResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    scope: Literal["project", "creator", "global"]
    identifier: str | None = Field(default=None, max_length=128)


class CreatorLearningEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: BobaCreatorFeedbackEventType
    target_type: BobaCreatorFeedbackTargetType
    target_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    user_action: BobaCreatorUserAction
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    note: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=24)
    reversible: bool = True


class CreatorLearningGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: str = Field(
        default="local_creator",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    dry_run: bool = False


class ApprovalRejectionLearningGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: str = Field(
        default="local_creator",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    dry_run: bool = False


class ExperimentationGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: str = Field(
        default="local_creator",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    dry_run: bool = False


class ExperimentManualResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(min_length=1, max_length=128)
    selected_variant_id: str = Field(min_length=1, max_length=128)
    manual_rating: float = Field(ge=0.0, le=5.0)
    creator_note: str = Field(default="", max_length=500)
    outcome_label: BobaExperimentOutcomeLabel
    should_feed_learning: bool = False


class PerformanceFeedbackEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: BobaPerformanceEventType
    target_type: BobaPerformanceTargetType
    target_id: str = Field(min_length=1, max_length=180)
    candidate_id: str = Field(default="", max_length=128)
    brief_id: str = Field(default="", max_length=160)
    experiment_id: str = Field(default="", max_length=128)
    variant_id: str = Field(default="", max_length=128)
    manual_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    creator_note: str = Field(default="", max_length=500)
    platform: str = Field(default="", max_length=80)
    source_label: str = Field(default="manual_entry", min_length=1, max_length=120)
    metrics: BobaManualPerformanceMetricsV1 = Field(
        default_factory=BobaManualPerformanceMetricsV1
    )
    retention_notes: str = Field(default="", max_length=500)
    creator_interpretation: str = Field(default="", max_length=500)
    outcome_label: BobaPerformanceOutcomeLabel | None = None
    baseline_id: str = Field(default="", max_length=128)
    selected_variant_id: str = Field(default="", max_length=128)
    should_feed_learning: bool = False


class PerformanceFeedbackGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False


class ContentScoutGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_items: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    import_paths: list[str] = Field(default_factory=list, max_length=20)
    source_label: str = Field(default="manual", min_length=1, max_length=160)
    dry_run: bool = False


class ResearchBrainGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_sources: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=500,
    )
    pasted_text_entries: list[str | dict[str, Any]] = Field(
        default_factory=list,
        max_length=100,
    )
    import_paths: list[str] = Field(default_factory=list, max_length=20)
    source_label: str = Field(default="manual", min_length=1, max_length=160)
    dry_run: bool = False


class TrendTopicWatcherGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_snapshots: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=500,
    )
    pasted_topic_lists: list[str | dict[str, Any]] = Field(
        default_factory=list,
        max_length=100,
    )
    import_paths: list[str] = Field(default_factory=list, max_length=20)
    source_label: str = Field(default="manual", min_length=1, max_length=160)
    dry_run: bool = False


class CandidateVideoScorerGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=500,
    )
    import_paths: list[str] = Field(default_factory=list, max_length=20)
    source_label: str = Field(default="manual", min_length=1, max_length=160)
    dry_run: bool = False


class RightsPermissionGateGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_items: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=500,
    )
    source_label: str = Field(default="manual", min_length=1, max_length=160)
    dry_run: bool = False


class ObserverGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_context: dict[str, Any] = Field(default_factory=dict, max_length=64)
    dry_run: bool = False


class ErrorDoctorGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnostic_context: dict[str, Any] = Field(default_factory=dict, max_length=64)
    error_summaries: list[str | dict[str, Any]] = Field(
        default_factory=list,
        max_length=32,
    )
    dry_run: bool = False


class RootCauseAnalyzerGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnostic_context: dict[str, Any] = Field(default_factory=dict, max_length=64)
    dry_run: bool = False


class RepairPlannerGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planning_context: dict[str, Any] = Field(default_factory=dict, max_length=64)
    dry_run: bool = False


class CodeSurgeonProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repair_case_id: str | None = Field(default=None, max_length=160)
    repair_strategy_id: str | None = Field(default=None, max_length=160)
    unified_diff: str | None = Field(default=None, max_length=200_000)
    proposal_source: BobaCodeProposalSourceV1 = "user_provided_diff"
    deterministic_template_identifier: str | None = Field(
        default=None,
        max_length=120,
    )
    template_parameters: dict[str, Any] = Field(default_factory=dict, max_length=16)
    base_branch: str = Field(default="main", min_length=1, max_length=240)
    affected_paths: list[str] = Field(default_factory=list, max_length=64)
    approved_special_paths: list[str] = Field(default_factory=list, max_length=32)


class CodeSurgeonExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_proposal_id: str = Field(min_length=1, max_length=160)
    approval: BobaCodeApprovalRecordV1
    approved_validation_commands: list[str] = Field(
        default_factory=list,
        min_length=1,
        max_length=12,
    )


class CodeSurgeonCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isolated_run_id: str = Field(min_length=1, max_length=160)
    approval: BobaCodeApprovalRecordV1


class ToolRecoveryPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_handoff_id: str | None = Field(default=None, max_length=160)
    selected_repair_strategy_id: str | None = Field(default=None, max_length=160)
    failure_context: dict[str, Any] = Field(default_factory=dict, max_length=32)
    run_health_checks: bool | None = None


class ToolRecoveryHealthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_ids: list[str] = Field(default_factory=list, max_length=32)


class ToolRecoveryExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_plan_id: str = Field(min_length=1, max_length=160)
    recovery_strategy_id: str = Field(min_length=1, max_length=160)
    approval: BobaToolRecoveryApprovalV1


class ToolRecoveryValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_attempt_id: str = Field(min_length=1, max_length=160)


class ToolRecoveryRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_attempt_id: str = Field(min_length=1, max_length=160)
    trigger: str = Field(min_length=1, max_length=900)


class OutputQualityReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_reference: str = Field(min_length=1, max_length=500)
    baseline_reference: str | None = Field(default=None, max_length=500)
    review_mode: BobaOutputReviewModeV1 = (
        "full_available_evidence_review"
    )
    rights_status: str = Field(min_length=1, max_length=80)
    safety_status: str = Field(min_length=1, max_length=80)
    workflow_stage: str = Field(default="quality_review", max_length=160)
    comparison_basis: BobaOutputComparisonBasisV1 = "unknown"
    required_quality_properties: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    non_negotiable_requirements: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    output_modification_requested: Literal[False] = False
    source_modification_requested: Literal[False] = False
    network_review_requested: Literal[False] = False


class OutputQualityCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_reference: str = Field(min_length=1, max_length=500)
    baseline_reference: str = Field(min_length=1, max_length=500)
    rights_status: str = Field(min_length=1, max_length=80)
    safety_status: str = Field(min_length=1, max_length=80)
    comparison_basis: BobaOutputComparisonBasisV1 = "unknown"
    required_quality_properties: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    non_negotiable_requirements: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    output_modification_requested: Literal[False] = False
    source_modification_requested: Literal[False] = False
    network_review_requested: Literal[False] = False


class OutputQualityHumanReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_case_id: str = Field(min_length=1, max_length=160)
    reviewer_identity: str = Field(min_length=1, max_length=160)
    review_decision: Literal[
        "accept_for_next_internal_stage",
        "accept_with_disclosed_limitation",
        "reject_output",
        "send_back_to_tool_recovery",
        "send_back_to_repair_planner",
        "request_more_evidence",
    ]
    answers: dict[str, Any] = Field(default_factory=dict, max_length=16)
    notes: str = Field(default="", max_length=1_000)


class ScoutScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_profile_id: str | None = Field(default=None, max_length=80)


class CandidateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)
    creator_profile_id: str | None = Field(default=None, max_length=80)
    approve_for_processing: bool = False


class CreativeBriefDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)
    creator_profile_id: str | None = Field(default=None, max_length=80)


class AutopilotCreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_mode: BobaAutopilotControlModeV1 = "safe_read_only_automatic"
    trigger: BobaAutopilotTriggerV1 = "manual"
    source_event_id: str | None = Field(default=None, max_length=180)
    recovery_budget: dict[str, Any] = Field(default_factory=dict, max_length=16)


class AutopilotAdvanceSafeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maximum_steps: int = Field(default=12, ge=1, le=30)


class AutopilotCoordinateApprovedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=180)
    safety_decision_id: str = Field(min_length=1, max_length=180)
    approval_record: dict[str, Any]


class AutopilotReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=900)


class AutopilotHumanDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal[
        "reject_proposed_action",
        "select_repair_alternative",
        "request_more_evidence",
        "pause_autopilot",
        "cancel_autopilot",
        "approve_disclosed_quality_limitation",
        "reject_output",
        "approve_budget_reset",
        "acknowledge_uncertain_project_state",
    ]
    reason: str = Field(min_length=1, max_length=900)
    reviewer_identity: str = Field(min_length=1, max_length=160)
    action_id: str | None = Field(default=None, max_length=180)
    selected_alternative_id: str | None = Field(default=None, max_length=180)


class WorkflowDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = Field(default=None, max_length=512)


class WorkflowCreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = Field(default=None, max_length=512)
    project_snapshot: dict[str, Any] = Field(default_factory=dict, max_length=128)
    source_storage_reference: str | None = Field(default=None, max_length=500)
    source_artifact_digest: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    clip_ids: list[str] = Field(default_factory=list, max_length=256)
    output_ids_by_clip: dict[str, str] = Field(
        default_factory=dict,
        max_length=256,
    )
    rights_status: str = Field(default="unknown", max_length=160)


class WorkflowTransitionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_stage_instance_id: str = Field(min_length=1, max_length=180)
    target_stage_id: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=1)
    transition_type: BobaWorkflowTransitionTypeV1
    reason: str = Field(min_length=1, max_length=900)
    clip_id: str | None = Field(default=None, max_length=160)
    output_id: str | None = Field(default=None, max_length=160)
    approval_record_id: str | None = Field(default=None, max_length=180)
    safety_decision_id: str | None = Field(default=None, max_length=180)
    integration_request_id: str | None = Field(default=None, max_length=180)
    checkpoint_reference: str | None = Field(default=None, max_length=500)
    checkpoint_digest: str | None = Field(default=None, max_length=128)
    quality_decision_id: str | None = Field(default=None, max_length=180)
    human_decision_id: str | None = Field(default=None, max_length=180)
    expires_in_seconds: int = Field(default=300, ge=1, le=3_600)
    idempotency_key: str | None = Field(default=None, max_length=180)


class WorkflowTransitionEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    current_project_snapshot_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    rights_clear: bool | None = None
    approval_record: dict[str, Any] | None = None
    safety_decision: dict[str, Any] | None = None
    checkpoint_valid: bool | None = None
    technical_validation: dict[str, Any] | None = None
    quality_decision: dict[str, Any] | None = None
    human_decision: dict[str, Any] | None = None


class WorkflowAdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition_decision_id: str = Field(min_length=1, max_length=180)
    expected_revision: int = Field(ge=1)
    integration_parameters: dict[str, Any] = Field(
        default_factory=dict,
        max_length=128,
    )


class WorkflowCoordinateApprovedRequest(WorkflowAdvanceRequest):
    approval_binding: BobaIntegrationApprovalBindingV1 | None = None
    safety_binding: BobaIntegrationSafetyBindingV1 | None = None


class WorkflowPauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=900)
    category: BobaWorkflowPauseCategoryV1 = "manual"
    stage_instance_id: str | None = Field(default=None, max_length=180)


class WorkflowRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class WorkflowCancelRequest(WorkflowRevisionRequest):
    reason: str = Field(min_length=1, max_length=900)


class WorkflowRecoveryHoldRequest(WorkflowRevisionRequest):
    failed_stage_instance_id: str = Field(min_length=1, max_length=180)
    reason: str = Field(min_length=1, max_length=900)
    observer_record_id: str | None = Field(default=None, max_length=180)


class WorkflowRecoveryResultRequest(WorkflowRevisionRequest):
    recovery_hold_id: str = Field(min_length=1, max_length=180)
    recovery_result: dict[str, Any]


class WorkflowResumeEligibilityRequest(WorkflowRevisionRequest):
    recovery_hold_id: str = Field(min_length=1, max_length=180)
    current_project_snapshot_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    rights_clear: bool
    approval_record: dict[str, Any] | None = None
    safety_decision: dict[str, Any] | None = None
    checkpoint_valid: bool
    rollback_state_clear: bool
    technical_validation: dict[str, Any] | None = None
    quality_decision: dict[str, Any] | None = None
    human_decision: dict[str, Any] | None = None


class WorkflowHumanDecisionRequest(WorkflowRevisionRequest):
    decision_type: str = Field(min_length=1, max_length=160)
    decision: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=900)
    reviewer_reference: str = Field(min_length=1, max_length=160)
    explicit_confirmation: bool
    stage_instance_id: str | None = Field(default=None, max_length=180)
    transition_request_id: str | None = Field(default=None, max_length=180)
    conditions: list[str] = Field(default_factory=list, max_length=64)
    expires_in_seconds: int | None = Field(default=None, ge=1, le=86_400)


class ValidatorRegistryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = Field(default=None, max_length=512)


class ValidatorInputBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str = Field(default="", max_length=180)
    output_id: str = Field(default="", max_length=180)
    artifact_type: str = Field(min_length=1, max_length=160)
    producer_module_id: str = Field(default="", max_length=160)
    producer_record_id: str = Field(default="", max_length=180)
    schema_id: str = Field(default="", max_length=180)
    schema_version: str = Field(default="1", max_length=80)
    artifact_digest: str = Field(default="", max_length=64)
    sanitized_storage_reference: str = Field(min_length=1, max_length=500)
    immutable: bool = True
    source_media: bool = False
    source_media_read_only: bool = True
    accepted_output: bool = False
    required: bool = True
    available: bool = True
    stale: bool = False
    malformed: bool = False
    rights_status: str = Field(default="unknown", max_length=80)


class ValidatorCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validator_id: str = Field(min_length=1, max_length=180)
    check_key: str | None = Field(default=None, max_length=180)
    required: bool = True
    depends_on: list[str] = Field(default_factory=list, max_length=64)
    input_binding_indexes: list[int] = Field(default_factory=list, max_length=64)
    expected_values: dict[str, Any] = Field(default_factory=dict, max_length=64)
    tolerance: dict[str, float] = Field(default_factory=dict, max_length=32)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=32)
    rejection_criteria: list[str] = Field(default_factory=list, max_length=32)
    timeout_seconds: int | None = Field(default=None, ge=1, le=900)
    maximum_attempts: int = Field(default=1, ge=1, le=2)
    stop_suite_on_failure: bool = False


class ValidatorPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = Field(default=None, max_length=512)
    target_type: Literal[
        "project_artifact",
        "workflow_stage",
        "generated_output",
        "recovered_output",
        "checkpoint",
        "code_worktree",
        "code_patch_result",
        "tool_health",
        "validation_report",
        "unknown",
    ]
    target_id: str = Field(min_length=1, max_length=180)
    checks: list[ValidatorCheckRequest] = Field(min_length=1, max_length=64)
    input_bindings: list[ValidatorInputBindingRequest] = Field(
        min_length=1,
        max_length=64,
    )
    validation_objective: str = Field(min_length=1, max_length=900)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=64)
    rejection_criteria: list[str] = Field(min_length=1, max_length=64)
    plan_source_module: str = Field(default="api", min_length=1, max_length=160)
    plan_source_record_id: str = Field(default="", max_length=180)
    target_digest: str = Field(default="", max_length=64)
    project_snapshot_digest: str = Field(default="", max_length=64)
    workflow_run_id: str = Field(default="", max_length=180)
    stage_instance_id: str = Field(default="", max_length=180)
    workflow_revision: int = Field(default=0, ge=0)
    approval_record_id: str = Field(default="", max_length=180)
    safety_decision_id: str = Field(default="", max_length=180)
    policy_mode: Literal[
        "artifact_only",
        "media_inspection",
        "isolated_code",
    ] | None = None
    resource_budget_overrides: dict[str, int] = Field(
        default_factory=dict,
        max_length=16,
    )
    expires_in_seconds: int = Field(default=86_400, ge=60, le=604_800)
    allow_unavailable_required: bool = False


class ValidatorPlanValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_plan_id: str = Field(min_length=1, max_length=180)
    allow_unavailable_required: bool = False


class ValidatorCreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_plan_id: str = Field(min_length=1, max_length=180)


class ValidatorExecuteRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_stale_lease: bool = False


class ValidatorRetryCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_check_id: str = Field(min_length=1, max_length=180)

class SafetyPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_policy: dict[str, Any] = Field(default_factory=dict, max_length=64)


class SafetyActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autopilot_run_id: str = Field(default="", max_length=180)
    autopilot_action_id: str = Field(default="", max_length=180)
    requesting_module: str = Field(
        default="autopilot_controller",
        min_length=1,
        max_length=160,
    )
    target_module: str = Field(min_length=1, max_length=160)
    target_operation: str = Field(min_length=1, max_length=160)
    action_class: str = Field(default="unknown", max_length=80)
    action_description: str = Field(min_length=1, max_length=700)
    action_parameters: dict[str, Any] = Field(default_factory=dict, max_length=64)
    project_snapshot_id: str = Field(default="", max_length=180)
    project_snapshot_digest: str = Field(default="", max_length=64)
    plan_id: str = Field(default="", max_length=180)
    strategy_id: str = Field(default="", max_length=180)
    approval_record_id: str = Field(default="", max_length=180)
    patch_proposal_id: str = Field(default="", max_length=180)
    patch_diff_sha256: str = Field(default="", max_length=64)
    code_base_sha: str = Field(default="", max_length=64)
    tool_id: str = Field(default="", max_length=180)
    capability_id: str = Field(default="", max_length=180)
    configuration_digest: str = Field(default="", max_length=64)
    checkpoint_reference: str = Field(default="", max_length=500)
    checkpoint_digest: str = Field(default="", max_length=128)
    rollback_plan_id: str = Field(default="", max_length=180)
    validation_plan_id: str = Field(default="", max_length=180)
    quality_plan_id: str = Field(default="", max_length=180)
    retry_budget_digest: str = Field(default="", max_length=64)
    time_budget_seconds: int = Field(default=0, ge=0, le=3_600)
    requested_by: str = Field(default="autopilot_controller", max_length=160)


class SafetyEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_request_id: str = Field(min_length=1, max_length=180)
    approval_record: dict[str, Any] | None = None


class SafetyRevalidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_record: dict[str, Any] | None = None
    current_bindings: dict[str, Any] = Field(default_factory=dict, max_length=32)


class SafetyInvalidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=900)
    changes: dict[str, bool] = Field(default_factory=dict, max_length=32)


class SafetyHumanReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal[
        "approve_exact_medium_risk_action",
        "deny_action",
        "request_more_evidence",
        "acknowledge_disclosed_limitation",
        "approve_stricter_budget_reset",
        "select_safer_alternative",
        "keep_project_paused",
    ]
    reason: str = Field(min_length=1, max_length=900)
    reviewer_identity: str = Field(min_length=1, max_length=160)
    request_digest: str = Field(min_length=64, max_length=64)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)


class IntegrationLayerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requesting_module_id: str = Field(min_length=1, max_length=160)
    target_module_id: str = Field(min_length=1, max_length=160)
    target_operation_id: str = Field(min_length=1, max_length=240)
    request_parameters: dict[str, Any] = Field(
        default_factory=dict,
        max_length=128,
    )
    run_id: str = Field(default="", max_length=180)
    request_schema_id: str = Field(
        default="boba.integration.request",
        max_length=160,
    )
    request_schema_version: str = Field(default="1.0", max_length=80)
    artifact_references: list[BobaIntegrationArtifactReferenceV1] = Field(
        default_factory=list,
        max_length=64,
    )
    approval_binding: BobaIntegrationApprovalBindingV1 | None = None
    safety_binding: BobaIntegrationSafetyBindingV1 | None = None
    project_snapshot_digest: str = Field(default="", max_length=64)
    expires_in_seconds: int = Field(default=300, ge=1, le=3_600)
    idempotency_key: str | None = Field(default=None, max_length=180)


class IntegrationLayerRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1, max_length=180)


def _require_enabled(settings: SettingsDep) -> None:
    if not settings.boba.enabled:
        raise ValidationError("BOBA Core Brain is disabled by configuration.")


def _require_memory_enabled(settings: SettingsDep) -> None:
    _require_enabled(settings)
    if not settings.boba_memory.enabled:
        raise ValidationError("BOBA Memory is disabled by configuration.")


async def _require_project(project_id: str, boba: BobaIntegrationDep) -> None:
    if await boba.projects.get(project_id) is None:
        raise NotFoundError("Project was not found.", details={"id": project_id})


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _source_artifact_digest(
    boba: BobaIntegrationDep,
    storage_key: str,
) -> str:
    local_path = boba.storage.local_path(storage_key)
    if local_path:
        return await asyncio.to_thread(_sha256_file, local_path)
    source_bytes = await boba.storage.get(storage_key)
    return hashlib.sha256(source_bytes).hexdigest()


@router.get("/projects/{project_id}/integration-layer")
async def get_integration_layer(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> Any:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    existing = boba.load_boba_integration_layer(project_id)
    if existing is not None:
        return existing
    return await boba.build_boba_integration_registry(project_id)


@router.get("/projects/{project_id}/integration-layer/modules")
async def get_integration_layer_modules(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    registry = await boba.inspect_boba_integration_registry(project_id)
    return {
        "registry_snapshot": registry["registry_snapshot"],
        "modules": registry["modules"],
    }


@router.get("/projects/{project_id}/integration-layer/operations")
async def get_integration_layer_operations(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    registry = await boba.inspect_boba_integration_registry(project_id)
    return {
        "registry_snapshot": registry["registry_snapshot"],
        "operations": registry["operations"],
    }


@router.post("/projects/{project_id}/integration-layer/requests")
async def create_integration_layer_request(
    project_id: str,
    body: IntegrationLayerCreateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return await boba.create_boba_integration_request(
        project_id,
        requesting_module_id=body.requesting_module_id,
        target_module_id=body.target_module_id,
        target_operation_id=body.target_operation_id,
        request_parameters=body.request_parameters,
        run_id=body.run_id,
        request_schema_id=body.request_schema_id,
        request_schema_version=body.request_schema_version,
        artifact_references=body.artifact_references,
        approval_binding=body.approval_binding,
        safety_binding=body.safety_binding,
        project_snapshot_digest=body.project_snapshot_digest,
        expires_in_seconds=body.expires_in_seconds,
        idempotency_key=body.idempotency_key,
    )


@router.post("/projects/{project_id}/integration-layer/route")
async def route_integration_layer_request(
    project_id: str,
    body: IntegrationLayerRouteRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> Any:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return await boba.route_boba_integration_request(
        project_id,
        body.transaction_id,
    )


@router.get(
    "/projects/{project_id}/integration-layer/transactions/{transaction_id}"
)
async def get_integration_layer_transaction(
    project_id: str,
    transaction_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> Any:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.inspect_boba_integration_transaction(
        project_id,
        transaction_id,
    )


@router.get(
    "/projects/{project_id}/integration-layer/transactions/"
    "{transaction_id}/events"
)
async def get_integration_layer_events(
    project_id: str,
    transaction_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> list[Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.inspect_boba_integration_events(project_id, transaction_id)


@router.get("/projects/{project_id}/integration-layer/export")
async def export_integration_layer(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.export_boba_integration_layer(project_id)


@router.delete("/projects/{project_id}/integration-layer")
async def reset_integration_layer(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.reset_boba_integration_layer(project_id)


@router.post("/candidates")
def create_candidate(
    body: BobaCandidateV1,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    return boba.scout.create_candidate(body).model_dump(mode="json")


@router.get("/candidates")
def list_candidates(
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    candidates = boba.scout.list_candidates()
    return {
        "count": len(candidates),
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "scores": {
            item.candidate_id: score.model_dump(mode="json")
            for item in candidates
            if (score := boba.store.load_scout_score(item.candidate_id)) is not None
        },
        "metadata_only": True,
        "external_calls_made": False,
    }


@router.post("/candidates/{candidate_id}/score")
def score_candidate(
    candidate_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
    body: ScoutScoreRequest | None = None,
) -> dict[str, Any]:
    _require_enabled(settings)
    return boba.scout.score_candidate(
        candidate_id,
        creator_profile_id=body.creator_profile_id if body else None,
    ).model_dump(mode="json")


def _candidate_decision(
    candidate_id: str,
    decision: BobaApprovalDecision,
    body: CandidateDecisionRequest,
    boba: BobaIntegrationDep,
) -> dict[str, Any]:
    event, candidate, lesson = boba.approvals.decide_candidate(
        candidate_id,
        decision=decision,
        reason=body.reason,
        approve_for_processing=body.approve_for_processing,
        creator_profile_id=body.creator_profile_id,
    )
    return {
        "candidate": candidate.model_dump(mode="json"),
        "approval": event.model_dump(mode="json"),
        "memory_lesson_id": lesson.memory_id,
        "processing_triggered": False,
    }


@router.post("/candidates/{candidate_id}/approve")
def approve_candidate(
    candidate_id: str,
    body: CandidateDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    return _candidate_decision(candidate_id, "approved", body, boba)


@router.post("/candidates/{candidate_id}/reject")
def reject_candidate(
    candidate_id: str,
    body: CandidateDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    return _candidate_decision(candidate_id, "rejected", body, boba)


@router.post("/projects/{project_id}/creative-briefs")
async def create_creative_briefs(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    briefs = await boba.generate_creative_briefs(project_id)
    return {
        "project_id": project_id,
        "count": len(briefs),
        "briefs": [item.model_dump(mode="json") for item in briefs],
        "rendering_triggered": False,
    }


@router.get("/projects/{project_id}/creative-briefs")
async def get_creative_briefs(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    briefs = boba.creative_director.list_briefs(project_id)
    return {
        "project_id": project_id,
        "count": len(briefs),
        "briefs": [item.model_dump(mode="json") for item in briefs],
    }


@router.post("/projects/{project_id}/whole-video-understanding")
async def create_whole_video_understanding(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    understanding = await boba.generate_whole_video_understanding(project_id)
    return understanding.model_dump(mode="json")


@router.get("/projects/{project_id}/whole-video-understanding")
async def get_whole_video_understanding(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    understanding = boba.store.load_whole_video_understanding(project_id)
    if understanding is None:
        raise NotFoundError(
            "BOBA whole-video understanding is not available.",
            details={"project_id": project_id},
        )
    return understanding.model_dump(mode="json")


@router.post("/projects/{project_id}/candidate-clips/discover")
async def discover_candidate_clips(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    discovery = await boba.discover_candidate_clips(project_id)
    return discovery.model_dump(mode="json")


@router.get("/projects/{project_id}/candidate-clips")
async def get_candidate_clips(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    discovery = boba.store.load_candidate_clip_discovery(project_id)
    if discovery is None:
        raise NotFoundError(
            "BOBA candidate clip discovery is not available.",
            details={"project_id": project_id},
        )
    return discovery.model_dump(mode="json")


@router.post("/projects/{project_id}/clip-ranking/rank")
async def rank_discovered_candidate_clips(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_candidate_ranking:
        raise ValidationError("BOBA candidate ranking is disabled by configuration.")
    await _require_project(project_id, boba)
    ranking = await boba.rank_discovered_candidate_clips(project_id)
    return ranking.model_dump(mode="json")


@router.get("/projects/{project_id}/clip-ranking")
async def get_clip_ranking(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    ranking = boba.store.load_clip_ranking(project_id)
    if ranking is None:
        raise NotFoundError(
            "BOBA clip ranking is not available.",
            details={"project_id": project_id},
        )
    return ranking.model_dump(mode="json")


@router.post("/projects/{project_id}/editorial-decisions")
async def create_editorial_decisions(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_editorial_policy:
        raise ValidationError("BOBA editorial decisions are disabled by configuration.")
    await _require_project(project_id, boba)
    decisions = await boba.generate_editorial_decisions(project_id)
    return decisions.model_dump(mode="json")


@router.get("/projects/{project_id}/editorial-decisions")
async def get_editorial_decisions(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decisions = boba.store.load_editorial_decisions(project_id)
    if decisions is None:
        raise NotFoundError(
            "BOBA editorial decisions are not available.",
            details={"project_id": project_id},
        )
    return decisions.model_dump(mode="json")


@router.post("/projects/{project_id}/explanations")
async def create_explanations(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    explanations = await boba.generate_explanations(project_id)
    return explanations.model_dump(mode="json")


@router.get("/projects/{project_id}/explanations")
async def get_explanations(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    explanations = boba.store.load_explanations(project_id)
    if explanations is None:
        raise NotFoundError(
            "BOBA explanations are not available.",
            details={"project_id": project_id},
        )
    return explanations.model_dump(mode="json")


@router.post("/projects/{project_id}/creative-direction-v2")
async def create_creative_direction_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    direction = await boba.generate_creative_direction_v2(project_id)
    return direction.model_dump(mode="json")


@router.get("/projects/{project_id}/creative-direction-v2")
async def get_creative_direction_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    direction = boba.store.load_creative_direction_v2(project_id)
    if direction is None:
        raise NotFoundError(
            "BOBA Creative Director V2 direction is not available.",
            details={"project_id": project_id},
        )
    return direction.model_dump(mode="json")


@router.post("/projects/{project_id}/clip-briefs")
async def create_clip_briefs(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    briefs = await boba.generate_clip_briefs(project_id)
    return briefs.model_dump(mode="json")


@router.get("/projects/{project_id}/clip-briefs")
async def get_clip_briefs(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    briefs = boba.store.load_clip_briefs(project_id)
    if briefs is None:
        raise NotFoundError(
            "BOBA clip briefs are not available.",
            details={"project_id": project_id},
        )
    return briefs.model_dump(mode="json")


@router.post("/projects/{project_id}/hook-retention")
async def create_hook_retention(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    analysis = await boba.generate_hook_retention(project_id)
    return analysis.model_dump(mode="json")


@router.get("/projects/{project_id}/hook-retention")
async def get_hook_retention(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    analysis = boba.store.load_hook_retention(project_id)
    if analysis is None:
        raise NotFoundError(
            "BOBA hook and retention analysis is not available.",
            details={"project_id": project_id},
        )
    return analysis.model_dump(mode="json")


@router.post("/projects/{project_id}/caption-motion")
async def create_caption_motion(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    recommendations = await boba.generate_caption_motion(project_id)
    return recommendations.model_dump(mode="json")


@router.get("/projects/{project_id}/caption-motion")
async def get_caption_motion(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    recommendations = boba.store.load_caption_motion(project_id)
    if recommendations is None:
        raise NotFoundError(
            "BOBA caption and motion recommendations are not available.",
            details={"project_id": project_id},
        )
    return recommendations.model_dump(mode="json")


@router.post("/projects/{project_id}/music-mood")
async def create_music_mood(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    recommendations = await boba.generate_music_mood(project_id)
    return recommendations.model_dump(mode="json")


@router.get("/projects/{project_id}/music-mood")
async def get_music_mood(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    recommendations = boba.store.load_music_mood(project_id)
    if recommendations is None:
        raise NotFoundError(
            "BOBA music mood recommendations are not available.",
            details={"project_id": project_id},
        )
    return recommendations.model_dump(mode="json")


@router.post("/projects/{project_id}/experimentation")
async def create_experimentation(
    project_id: str,
    body: ExperimentationGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    experimentation = await boba.generate_experimentation_plan(
        project_id,
        creator_id=body.creator_id,
        dry_run=body.dry_run,
    )
    return experimentation.model_dump(mode="json")


@router.get("/projects/{project_id}/experimentation")
async def get_experimentation(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    experimentation = boba.load_experimentation_plan(project_id)
    if experimentation is None:
        raise NotFoundError(
            "BOBA experimentation plan is not available.",
            details={"project_id": project_id},
        )
    return experimentation.model_dump(mode="json")


@router.get("/projects/{project_id}/experimentation/export")
async def export_experimentation(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_experimentation_plan(project_id) is None:
        raise NotFoundError(
            "BOBA experimentation plan is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_experimentation_plan(project_id)


@router.delete("/projects/{project_id}/experimentation")
async def reset_experimentation(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_experimentation_plan(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "experimentation_removed": removed,
        "unrelated_memory_removed": False,
    }


@router.post("/projects/{project_id}/experimentation/results")
async def record_experimentation_result(
    project_id: str,
    body: ExperimentManualResultRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    result = boba.record_manual_experiment_result(
        project_id,
        experiment_id=body.experiment_id,
        selected_variant_id=body.selected_variant_id,
        manual_rating=body.manual_rating,
        outcome_label=body.outcome_label,
        creator_note=body.creator_note,
        should_feed_learning=body.should_feed_learning,
    )
    return result.model_dump(mode="json")


@router.post("/projects/{project_id}/performance-feedback/events")
async def record_performance_feedback_event(
    project_id: str,
    body: PerformanceFeedbackEventRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    event, feedback = await boba.record_performance_feedback_event(
        project_id,
        event_type=body.event_type,
        target_type=body.target_type,
        target_id=body.target_id,
        candidate_id=body.candidate_id,
        brief_id=body.brief_id,
        experiment_id=body.experiment_id,
        variant_id=body.variant_id,
        manual_rating=body.manual_rating,
        creator_note=body.creator_note,
        platform=body.platform,
        source_label=body.source_label,
        metrics=body.metrics,
        retention_notes=body.retention_notes,
        creator_interpretation=body.creator_interpretation,
        outcome_label=body.outcome_label,
        baseline_id=body.baseline_id,
        selected_variant_id=body.selected_variant_id,
        should_feed_learning=body.should_feed_learning,
    )
    return {
        "event": event.model_dump(mode="json"),
        "performance_feedback": feedback.model_dump(mode="json"),
        "analytics_collected": False,
        "automatically_applied": False,
    }


@router.post("/projects/{project_id}/performance-feedback")
async def create_performance_feedback(
    project_id: str,
    body: PerformanceFeedbackGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    feedback = await boba.generate_performance_feedback(
        project_id,
        dry_run=body.dry_run,
    )
    return feedback.model_dump(mode="json")


@router.get("/projects/{project_id}/performance-feedback")
async def get_performance_feedback(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    feedback = boba.load_performance_feedback(project_id)
    if feedback is None:
        raise NotFoundError(
            "BOBA performance feedback is not available.",
            details={"project_id": project_id},
        )
    return feedback.model_dump(mode="json")


@router.get("/projects/{project_id}/performance-feedback/export")
async def export_performance_feedback(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_performance_feedback(project_id) is None:
        raise NotFoundError(
            "BOBA performance feedback is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_performance_feedback(project_id)


@router.delete("/projects/{project_id}/performance-feedback")
async def reset_performance_feedback(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_performance_feedback(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "performance_feedback_removed": removed,
        "experimentation_removed": False,
        "creator_learning_removed": False,
        "approval_rejection_learning_removed": False,
        "unrelated_memory_removed": False,
    }


@router.post("/projects/{project_id}/content-scout-v2")
async def create_content_scout_v2(
    project_id: str,
    body: ContentScoutGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    scout = await boba.generate_content_scout_v2(
        project_id,
        manual_items=body.manual_items,
        import_paths=body.import_paths,
        source_label=body.source_label,
        dry_run=body.dry_run,
    )
    return scout.model_dump(mode="json")


@router.get("/projects/{project_id}/content-scout-v2")
async def get_content_scout_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    scout = boba.load_content_scout_v2(project_id)
    if scout is None:
        raise NotFoundError(
            "BOBA Content Scout V2 is not available.",
            details={"project_id": project_id},
        )
    return scout.model_dump(mode="json")


@router.get("/projects/{project_id}/content-scout-v2/export")
async def export_content_scout_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_content_scout_v2(project_id) is None:
        raise NotFoundError(
            "BOBA Content Scout V2 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_content_scout_v2(project_id)


@router.delete("/projects/{project_id}/content-scout-v2")
async def reset_content_scout_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_content_scout_v2(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "content_scout_v2_removed": removed,
        "scout_v1_removed": False,
        "creator_learning_removed": False,
        "approval_rejection_learning_removed": False,
        "performance_feedback_removed": False,
        "memory_removed": False,
    }


@router.post("/projects/{project_id}/research-brain")
async def create_research_brain(
    project_id: str,
    body: ResearchBrainGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    research = await boba.generate_research_brain(
        project_id,
        manual_sources=body.manual_sources,
        pasted_text_entries=body.pasted_text_entries,
        import_paths=body.import_paths,
        source_label=body.source_label,
        dry_run=body.dry_run,
    )
    return research.model_dump(mode="json")


@router.get("/projects/{project_id}/research-brain")
async def get_research_brain(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    research = boba.load_research_brain(project_id)
    if research is None:
        raise NotFoundError(
            "BOBA Research Brain V1 is not available.",
            details={"project_id": project_id},
        )
    return research.model_dump(mode="json")


@router.get("/projects/{project_id}/research-brain/export")
async def export_research_brain(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_research_brain(project_id) is None:
        raise NotFoundError(
            "BOBA Research Brain V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_research_brain(project_id)


@router.delete("/projects/{project_id}/research-brain")
async def reset_research_brain(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_research_brain(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "research_brain_removed": removed,
        "content_scout_removed": False,
        "creator_learning_removed": False,
        "approval_rejection_learning_removed": False,
        "performance_feedback_removed": False,
        "memory_removed": False,
    }


@router.post("/projects/{project_id}/trend-topic-watcher")
async def create_trend_topic_watcher(
    project_id: str,
    body: TrendTopicWatcherGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    watcher = await boba.generate_trend_topic_watcher(
        project_id,
        manual_snapshots=body.manual_snapshots,
        pasted_topic_lists=body.pasted_topic_lists,
        import_paths=body.import_paths,
        source_label=body.source_label,
        dry_run=body.dry_run,
    )
    return watcher.model_dump(mode="json")


@router.get("/projects/{project_id}/trend-topic-watcher")
async def get_trend_topic_watcher(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    watcher = boba.load_trend_topic_watcher(project_id)
    if watcher is None:
        raise NotFoundError(
            "BOBA Trend / Topic Watcher V1 is not available.",
            details={"project_id": project_id},
        )
    return watcher.model_dump(mode="json")


@router.get("/projects/{project_id}/trend-topic-watcher/export")
async def export_trend_topic_watcher(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_trend_topic_watcher(project_id) is None:
        raise NotFoundError(
            "BOBA Trend / Topic Watcher V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_trend_topic_watcher(project_id)


@router.delete("/projects/{project_id}/trend-topic-watcher")
async def reset_trend_topic_watcher(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_trend_topic_watcher(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "trend_topic_watcher_removed": removed,
        "research_brain_removed": False,
        "content_scout_removed": False,
        "creator_learning_removed": False,
        "performance_feedback_removed": False,
        "memory_removed": False,
    }


@router.post("/projects/{project_id}/candidate-video-scorer")
async def create_candidate_video_scorer(
    project_id: str,
    body: CandidateVideoScorerGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    scorer = await boba.generate_candidate_video_scorer(
        project_id,
        manual_candidates=body.manual_candidates,
        import_paths=body.import_paths,
        source_label=body.source_label,
        dry_run=body.dry_run,
    )
    return scorer.model_dump(mode="json")


@router.get("/projects/{project_id}/candidate-video-scorer")
async def get_candidate_video_scorer(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    scorer = boba.load_candidate_video_scorer(project_id)
    if scorer is None:
        raise NotFoundError(
            "BOBA Candidate Video Scorer V1 is not available.",
            details={"project_id": project_id},
        )
    return scorer.model_dump(mode="json")


@router.get("/projects/{project_id}/candidate-video-scorer/export")
async def export_candidate_video_scorer(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_candidate_video_scorer(project_id) is None:
        raise NotFoundError(
            "BOBA Candidate Video Scorer V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_candidate_video_scorer(project_id)


@router.delete("/projects/{project_id}/candidate-video-scorer")
async def reset_candidate_video_scorer(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_candidate_video_scorer(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "candidate_video_scorer_removed": removed,
        "trend_topic_watcher_removed": False,
        "research_brain_removed": False,
        "content_scout_removed": False,
        "creator_learning_removed": False,
        "approval_rejection_learning_removed": False,
        "performance_feedback_removed": False,
        "memory_removed": False,
        "media_ingested": False,
    }


@router.post("/projects/{project_id}/rights-permission-gate")
async def create_rights_permission_gate(
    project_id: str,
    body: RightsPermissionGateGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    gate = await boba.generate_rights_permission_gate(
        project_id,
        manual_items=body.manual_items,
        source_label=body.source_label,
        dry_run=body.dry_run,
    )
    return gate.model_dump(mode="json")


@router.get("/projects/{project_id}/rights-permission-gate")
async def get_rights_permission_gate(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    gate = boba.load_rights_permission_gate(project_id)
    if gate is None:
        raise NotFoundError(
            "BOBA Rights + Permission Gate V1 is not available.",
            details={"project_id": project_id},
        )
    return gate.model_dump(mode="json")


@router.get("/projects/{project_id}/rights-permission-gate/export")
async def export_rights_permission_gate(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_rights_permission_gate(project_id) is None:
        raise NotFoundError(
            "BOBA Rights + Permission Gate V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_rights_permission_gate(project_id)


@router.delete("/projects/{project_id}/rights-permission-gate")
async def reset_rights_permission_gate(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_rights_permission_gate(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "rights_permission_gate_removed": removed,
        "candidate_video_scorer_removed": False,
        "trend_topic_watcher_removed": False,
        "research_brain_removed": False,
        "content_scout_removed": False,
        "clip_briefs_removed": False,
        "music_mood_removed": False,
        "memory_removed": False,
        "media_ingested": False,
        "legal_validation_used": False,
    }


@router.post("/projects/{project_id}/observer")
async def create_observer_report(
    project_id: str,
    body: ObserverGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.generate_observer_report(
        project_id,
        workflow_context=body.workflow_context,
        dry_run=body.dry_run,
    )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/observer")
async def get_observer_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = boba.load_observer_report(project_id)
    if report is None:
        raise NotFoundError(
            "BOBA Observer V1 is not available.",
            details={"project_id": project_id},
        )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/observer/export")
async def export_observer_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_observer_report(project_id) is None:
        raise NotFoundError(
            "BOBA Observer V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_observer_report(project_id)


@router.delete("/projects/{project_id}/observer")
async def reset_observer_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_observer_report(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "observer_removed": removed,
        "other_boba_artifacts_removed": False,
        "unrelated_files_deleted": False,
        "validators_executed": False,
        "commands_executed": False,
        "code_modified": False,
        "media_downloaded": False,
        "media_ingested": False,
        "rendering_triggered": False,
    }


@router.post("/projects/{project_id}/error-doctor")
async def create_error_doctor_report(
    project_id: str,
    body: ErrorDoctorGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.generate_boba_error_doctor(
        project_id,
        diagnostic_context=body.diagnostic_context,
        error_summaries=body.error_summaries,
        dry_run=body.dry_run,
    )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/error-doctor")
async def get_error_doctor_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = boba.load_boba_error_doctor(project_id)
    if report is None:
        raise NotFoundError(
            "BOBA Error Doctor V1 is not available.",
            details={"project_id": project_id},
        )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/error-doctor/export")
async def export_error_doctor_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_boba_error_doctor(project_id) is None:
        raise NotFoundError(
            "BOBA Error Doctor V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_boba_error_doctor(project_id)


@router.delete("/projects/{project_id}/error-doctor")
async def reset_error_doctor_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_boba_error_doctor(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "error_doctor_removed": removed,
        "observer_removed": False,
        "other_boba_artifacts_removed": False,
        "unrelated_files_deleted": False,
        "validators_executed": False,
        "commands_executed": False,
        "code_modified": False,
        "artifacts_modified": False,
        "media_downloaded": False,
        "media_ingested": False,
        "rendering_triggered": False,
        "repairs_applied": False,
    }


@router.post("/projects/{project_id}/root-cause-analyzer")
async def create_root_cause_analyzer_report(
    project_id: str,
    body: RootCauseAnalyzerGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.generate_boba_root_cause_analyzer(
        project_id,
        diagnostic_context=body.diagnostic_context,
        dry_run=body.dry_run,
    )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/root-cause-analyzer")
async def get_root_cause_analyzer_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = boba.load_boba_root_cause_analyzer(project_id)
    if report is None:
        raise NotFoundError(
            "BOBA Root Cause Analyzer V1 is not available.",
            details={"project_id": project_id},
        )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/root-cause-analyzer/export")
async def export_root_cause_analyzer_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_boba_root_cause_analyzer(project_id) is None:
        raise NotFoundError(
            "BOBA Root Cause Analyzer V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_boba_root_cause_analyzer(project_id)


@router.delete("/projects/{project_id}/root-cause-analyzer")
async def reset_root_cause_analyzer_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_boba_root_cause_analyzer(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "root_cause_analyzer_removed": removed,
        "error_doctor_removed": False,
        "observer_removed": False,
        "other_boba_artifacts_removed": False,
        "unrelated_files_deleted": False,
        "validators_executed": False,
        "commands_executed": False,
        "code_modified": False,
        "artifacts_modified": False,
        "media_downloaded": False,
        "media_ingested": False,
        "rendering_triggered": False,
        "repairs_applied": False,
        "fallback_tools_executed": False,
        "workflow_resume_authorized": False,
    }


@router.post("/projects/{project_id}/repair-planner")
async def create_repair_planner_report(
    project_id: str,
    body: RepairPlannerGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.generate_boba_repair_planner(
        project_id,
        planning_context=body.planning_context,
        dry_run=body.dry_run,
    )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/repair-planner")
async def get_repair_planner_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = boba.load_boba_repair_planner(project_id)
    if report is None:
        raise NotFoundError(
            "BOBA Repair Planner V1 is not available.",
            details={"project_id": project_id},
        )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/repair-planner/export")
async def export_repair_planner_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_boba_repair_planner(project_id) is None:
        raise NotFoundError(
            "BOBA Repair Planner V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_boba_repair_planner(project_id)


@router.delete("/projects/{project_id}/repair-planner")
async def reset_repair_planner_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_boba_repair_planner(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "repair_planner_removed": removed,
        "root_cause_analyzer_removed": False,
        "error_doctor_removed": False,
        "observer_removed": False,
        "other_boba_artifacts_removed": False,
        "unrelated_files_deleted": False,
        "validators_executed": False,
        "commands_executed": False,
        "code_modified": False,
        "artifacts_modified": False,
        "media_downloaded": False,
        "media_ingested": False,
        "rendering_triggered": False,
        "repairs_applied": False,
        "fallback_tools_executed": False,
        "workflow_resumed": False,
        "services_restarted": False,
        "packages_installed": False,
    }


@router.post("/projects/{project_id}/code-surgeon/propose")
async def propose_code_surgeon_patch(
    project_id: str,
    body: CodeSurgeonProposalRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.generate_boba_code_surgeon_proposal(
        project_id,
        repair_case_id=body.repair_case_id,
        repair_strategy_id=body.repair_strategy_id,
        unified_diff=body.unified_diff,
        proposal_source=body.proposal_source,
        deterministic_template_identifier=body.deterministic_template_identifier,
        template_parameters=body.template_parameters,
        base_branch=body.base_branch,
        affected_paths=body.affected_paths,
        approved_special_paths=body.approved_special_paths,
    )
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/code-surgeon/validate-patch")
async def validate_code_surgeon_patch(
    project_id: str,
    body: CodeSurgeonProposalRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if not body.unified_diff and not body.deterministic_template_identifier:
        raise ValidationError("Patch validation requires a bounded diff or template.")
    report = await boba.validate_boba_code_surgeon_patch(
        project_id,
        repair_case_id=body.repair_case_id,
        repair_strategy_id=body.repair_strategy_id,
        unified_diff=body.unified_diff,
        deterministic_template_identifier=body.deterministic_template_identifier,
        template_parameters=body.template_parameters,
        base_branch=body.base_branch,
        affected_paths=body.affected_paths,
        approved_special_paths=body.approved_special_paths,
    )
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/code-surgeon/execute-approved")
async def execute_approved_code_surgeon_patch(
    project_id: str,
    body: CodeSurgeonExecuteRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.execute_approved_boba_code_surgeon_patch(
        project_id,
        patch_proposal_id=body.patch_proposal_id,
        approval=body.approval,
        approved_validation_commands=body.approved_validation_commands,
    )
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/code-surgeon/prepare-local-commit")
async def prepare_code_surgeon_local_commit(
    project_id: str,
    body: CodeSurgeonCommitRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.prepare_boba_code_surgeon_local_commit(
        project_id,
        isolated_run_id=body.isolated_run_id,
        approval=body.approval,
    )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/code-surgeon")
async def get_code_surgeon_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = boba.load_boba_code_surgeon(project_id)
    if report is None:
        raise NotFoundError(
            "BOBA Code Surgeon V1 is not available.",
            details={"project_id": project_id},
        )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/code-surgeon/export")
async def export_code_surgeon_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_boba_code_surgeon(project_id) is None:
        raise NotFoundError(
            "BOBA Code Surgeon V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_boba_code_surgeon(project_id)


@router.delete("/projects/{project_id}/code-surgeon")
async def reset_code_surgeon_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_boba_code_surgeon(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "code_surgeon_removed": removed,
        "repair_planner_removed": False,
        "root_cause_analyzer_removed": False,
        "other_boba_artifacts_removed": False,
        "source_code_deleted": False,
        "isolated_worktree_deleted": False,
        "branches_deleted": False,
        "main_modified": False,
        "push_used": False,
        "remote_pr_created": False,
        "merge_used": False,
        "tag_used": False,
        "deployment_used": False,
        "package_installation_used": False,
        "service_restart_used": False,
        "destructive_git_used": False,
    }


@router.post("/projects/{project_id}/tool-recovery/plan")
async def create_tool_recovery_plan(
    project_id: str,
    body: ToolRecoveryPlanRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.generate_boba_tool_recovery_plan(
        project_id,
        selected_handoff_id=body.selected_handoff_id,
        selected_repair_strategy_id=body.selected_repair_strategy_id,
        failure_context=body.failure_context,
        run_health_checks=body.run_health_checks,
    )
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/tool-recovery/health-check")
async def run_tool_recovery_health_checks(
    project_id: str,
    body: ToolRecoveryHealthRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.run_boba_tool_health_checks(
        project_id,
        tool_ids=body.tool_ids or None,
    )
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/tool-recovery/execute-approved")
async def execute_approved_tool_recovery(
    project_id: str,
    body: ToolRecoveryExecuteRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.execute_approved_boba_tool_recovery(
        project_id,
        recovery_plan_id=body.recovery_plan_id,
        recovery_strategy_id=body.recovery_strategy_id,
        approval=body.approval,
    )
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/tool-recovery/validate-output")
async def validate_tool_recovery_output(
    project_id: str,
    body: ToolRecoveryValidationRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.validate_boba_recovered_output(
        project_id,
        recovery_attempt_id=body.recovery_attempt_id,
    )
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/tool-recovery/rollback")
async def rollback_tool_recovery(
    project_id: str,
    body: ToolRecoveryRollbackRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.rollback_boba_tool_recovery(
        project_id,
        recovery_attempt_id=body.recovery_attempt_id,
        trigger=body.trigger,
    )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/tool-recovery")
async def get_tool_recovery_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = boba.load_boba_tool_recovery(project_id)
    if report is None:
        raise NotFoundError(
            "BOBA Tool Recovery Brain V1 is not available.",
            details={"project_id": project_id},
        )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/tool-recovery/export")
async def export_tool_recovery_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_boba_tool_recovery(project_id) is None:
        raise NotFoundError(
            "BOBA Tool Recovery Brain V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_boba_tool_recovery(project_id)


@router.delete("/projects/{project_id}/tool-recovery")
async def reset_tool_recovery_report(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_boba_tool_recovery(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "tool_recovery_removed": removed,
        "repair_planner_removed": False,
        "code_surgeon_removed": False,
        "source_media_deleted": False,
        "accepted_outputs_deleted": False,
        "recovery_workspace_deleted": False,
        "commands_executed": False,
        "network_access_used": False,
        "packages_installed": False,
        "services_restarted": False,
        "processes_killed": False,
        "workflow_resumed": False,
        "code_modified": False,
    }


@router.post("/projects/{project_id}/output-quality-reviewer/review")
async def create_output_quality_review(
    project_id: str,
    body: OutputQualityReviewRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.generate_boba_output_quality_review(
        project_id,
        output_reference=body.output_reference,
        baseline_reference=body.baseline_reference,
        review_mode=body.review_mode,
        rights_status=body.rights_status,
        safety_status=body.safety_status,
        workflow_stage=body.workflow_stage,
        comparison_basis=body.comparison_basis,
        required_quality_properties=body.required_quality_properties,
        non_negotiable_requirements=body.non_negotiable_requirements,
        output_modification_requested=body.output_modification_requested,
        source_modification_requested=body.source_modification_requested,
        network_review_requested=body.network_review_requested,
    )
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/output-quality-reviewer/compare")
async def compare_output_quality(
    project_id: str,
    body: OutputQualityCompareRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.compare_boba_output_quality_baseline(
        project_id,
        output_reference=body.output_reference,
        baseline_reference=body.baseline_reference,
        rights_status=body.rights_status,
        safety_status=body.safety_status,
        comparison_basis=body.comparison_basis,
        required_quality_properties=body.required_quality_properties,
        non_negotiable_requirements=body.non_negotiable_requirements,
    )
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/output-quality-reviewer/human-review")
async def record_output_quality_human_review(
    project_id: str,
    body: OutputQualityHumanReviewRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = await boba.record_boba_output_human_review(
        project_id,
        review_case_id=body.review_case_id,
        reviewer_identity=body.reviewer_identity,
        review_decision=body.review_decision,
        answers=body.answers,
        notes=body.notes,
    )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/output-quality-reviewer")
async def get_output_quality_reviewer(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    report = boba.load_boba_output_quality_reviewer(project_id)
    if report is None:
        raise NotFoundError(
            "BOBA Output Quality Reviewer V1 is not available.",
            details={"project_id": project_id},
        )
    return report.model_dump(mode="json")


@router.get("/projects/{project_id}/output-quality-reviewer/export")
async def export_output_quality_reviewer(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_boba_output_quality_reviewer(project_id) is None:
        raise NotFoundError(
            "BOBA Output Quality Reviewer V1 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_boba_output_quality_reviewer(project_id)


@router.delete("/projects/{project_id}/output-quality-reviewer")
async def reset_output_quality_reviewer(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_boba_output_quality_reviewer(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "output_quality_reviewer_removed": removed,
        "reviewed_output_deleted": False,
        "source_media_deleted": False,
        "tool_recovery_artifact_deleted": False,
        "code_surgeon_artifact_deleted": False,
        "render_manifest_deleted": False,
        "sample_evidence_deleted": False,
        "commands_executed": False,
        "rendering_used": False,
        "fallback_execution_used": False,
        "workflow_resumed": False,
        "network_access_used": False,
        "uploading_used": False,
        "publication_used": False,
        "destructive_action_used": False,
    }


@router.get("/projects/{project_id}/validator-runner")
async def get_validator_runner(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    runner = boba.load_boba_validator_runner(project_id)
    return runner.model_dump(mode="json")


@router.get("/projects/{project_id}/validator-runner/registry")
async def get_validator_registry(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.validator_runner.inspect_registry(
        project_id,
        source_id=project_id,
    )


@router.get("/projects/{project_id}/validator-runner/validators")
async def get_validators(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    registry = await get_validator_registry(project_id, boba, settings)
    return {
        "schema_version": "boba_validators_v1",
        "project_id": project_id,
        "validators": registry.get("validators", []),
    }


@router.get("/projects/{project_id}/validator-runner/availability")
async def get_validator_availability(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.validator_runner.inspect_availability(
        project_id,
        source_id=project_id,
    )


@router.post("/projects/{project_id}/validator-runner/plans")
async def create_validator_plan(
    project_id: str,
    body: ValidatorPlanRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    plan = boba.validator_runner.create_validation_plan(
        project_id,
        source_id=body.source_id or project_id,
        target_type=body.target_type,
        target_id=body.target_id,
        checks=[item.model_dump(exclude_none=True) for item in body.checks],
        input_bindings=[
            item.model_dump(exclude_none=True) for item in body.input_bindings
        ],
        validation_objective=body.validation_objective,
        acceptance_criteria=body.acceptance_criteria,
        rejection_criteria=body.rejection_criteria,
        plan_source_module=body.plan_source_module,
        plan_source_record_id=body.plan_source_record_id,
        target_digest=body.target_digest,
        project_snapshot_digest=body.project_snapshot_digest,
        workflow_run_id=body.workflow_run_id,
        stage_instance_id=body.stage_instance_id,
        workflow_revision=body.workflow_revision,
        approval_record_id=body.approval_record_id,
        safety_decision_id=body.safety_decision_id,
        policy_mode=body.policy_mode,
        resource_budget_overrides=body.resource_budget_overrides or None,
        expires_in_seconds=body.expires_in_seconds,
        allow_unavailable_required=body.allow_unavailable_required,
    )
    return plan.model_dump(mode="json")


@router.post("/projects/{project_id}/validator-runner/plans/validate")
async def validate_validator_plan(
    project_id: str,
    body: ValidatorPlanValidateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.validator_runner.validate_validation_plan(
        project_id,
        validation_plan_id=body.validation_plan_id,
        allow_unavailable_required=body.allow_unavailable_required,
    )


@router.post("/projects/{project_id}/validator-runner/runs")
async def create_validator_run(
    project_id: str,
    body: ValidatorCreateRunRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    run = boba.validator_runner.create_validation_run(
        project_id,
        body.validation_plan_id,
    )
    return run.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/validator-runner/runs/{run_id}/execute"
)
async def execute_validator_run(
    project_id: str,
    run_id: str,
    body: ValidatorExecuteRunRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.validator_runner.execute_validation_run(
        project_id,
        run_id,
        confirm_stale_lease=body.confirm_stale_lease,
    )


@router.post(
    "/projects/{project_id}/validator-runner/runs/{run_id}/cancel"
)
async def cancel_validator_run(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    run = boba.validator_runner.cancel_validation_run(project_id, run_id)
    return run.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/validator-runner/runs/{run_id}/retry-check"
)
async def retry_validator_check(
    project_id: str,
    run_id: str,
    body: ValidatorRetryCheckRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    run = boba.validator_runner.retry_validation_check(
        project_id,
        run_id,
        body.plan_check_id,
    )
    return run.model_dump(mode="json")


@router.get("/projects/{project_id}/validator-runner/runs/{run_id}")
async def get_validator_run(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.validator_runner.inspect_validation_run(project_id, run_id)


@router.get(
    "/projects/{project_id}/validator-runner/runs/{run_id}/results"
)
async def get_validator_results(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.validator_runner.inspect_results(project_id, run_id)


@router.get("/projects/{project_id}/validator-runner/runs/{run_id}/events")
async def get_validator_events(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    events = boba.validator_runner.inspect_events(project_id, run_id)
    return {
        "schema_version": "boba_validation_event_stream_v1",
        "project_id": project_id,
        "validation_run_id": run_id,
        "events": [item.model_dump(mode="json") for item in events],
    }


@router.get("/projects/{project_id}/validator-runner/export")
async def export_validator_runner(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.export_boba_validator_runner(project_id)


@router.delete("/projects/{project_id}/validator-runner")
async def reset_validator_runner(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.reset_boba_validator_runner(project_id)

@router.post("/projects/{project_id}/workflow-controller/definitions")
async def create_workflow_definition(
    project_id: str,
    body: WorkflowDefinitionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    definition = boba.build_boba_workflow_definition(
        project_id,
        source_id=body.source_id,
    )
    return definition.model_dump(mode="json")


@router.post("/projects/{project_id}/workflow-controller/runs")
async def create_workflow_run(
    project_id: str,
    body: WorkflowCreateRunRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    project = await boba.projects.get(project_id)
    if project is None:
        raise NotFoundError("Project was not found.", details={"id": project_id})
    if bool(body.source_storage_reference) != bool(body.source_artifact_digest):
        raise ValidationError(
            "Source storage reference and source artifact digest must be "
            "provided together."
        )
    source_storage_reference = (
        body.source_storage_reference or project.storage_key
    )
    source_artifact_digest = body.source_artifact_digest or (
        await _source_artifact_digest(boba, project.storage_key)
    )
    project_snapshot = body.project_snapshot or {
        "project_id": project.id,
        "project_status": project.status.value,
        "source_type": project.source_type,
        "source_filename": project.source_filename,
        "source_storage_reference": project.storage_key,
        "desired_clip_count": project.desired_clip_count,
        "updated_at": project.updated_at.isoformat(),
    }
    controller = boba.create_boba_workflow_run(
        project_id,
        source_id=body.source_id or project_id,
        project_snapshot=project_snapshot,
        source_storage_reference=source_storage_reference,
        source_artifact_digest=source_artifact_digest,
        clip_ids=body.clip_ids,
        output_ids_by_clip=body.output_ids_by_clip,
        rights_status=body.rights_status,
    )
    return controller.model_dump(mode="json")


@router.get("/projects/{project_id}/workflow-controller")
async def get_workflow_controller(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    controller = boba.load_boba_workflow_controller(project_id)
    if controller is None:
        raise NotFoundError(
            "BOBA Workflow Controller V1 is not available.",
            details={"project_id": project_id},
        )
    return controller.model_dump(mode="json")


@router.get(
    "/projects/{project_id}/workflow-controller/runs/{run_id}"
)
async def get_workflow_run(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.inspect_boba_workflow_run(project_id, run_id)


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/plan-next"
)
async def plan_workflow_next_stage(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.plan_boba_workflow_next_stage(project_id, run_id)


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/transitions"
)
async def create_workflow_transition(
    project_id: str,
    run_id: str,
    body: WorkflowTransitionCreateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    request = boba.create_boba_workflow_transition_request(
        project_id,
        run_id,
        source_stage_instance_id=body.source_stage_instance_id,
        target_stage_id=body.target_stage_id,
        expected_revision=body.expected_revision,
        transition_type=body.transition_type,
        reason=body.reason,
        clip_id=body.clip_id,
        output_id=body.output_id,
        approval_record_id=body.approval_record_id,
        safety_decision_id=body.safety_decision_id,
        integration_request_id=body.integration_request_id,
        checkpoint_reference=body.checkpoint_reference,
        checkpoint_digest=body.checkpoint_digest,
        quality_decision_id=body.quality_decision_id,
        human_decision_id=body.human_decision_id,
        expires_in_seconds=body.expires_in_seconds,
        idempotency_key=body.idempotency_key,
    )
    return request.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/"
    "transitions/{transition_id}/evaluate"
)
async def evaluate_workflow_transition(
    project_id: str,
    run_id: str,
    transition_id: str,
    body: WorkflowTransitionEvaluateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decision = boba.evaluate_boba_workflow_transition(
        project_id,
        run_id,
        transition_id,
        expected_revision=body.expected_revision,
        current_project_snapshot_digest=body.current_project_snapshot_digest,
        rights_clear=body.rights_clear,
        approval_record=body.approval_record,
        safety_decision=body.safety_decision,
        checkpoint_valid=body.checkpoint_valid,
        technical_validation=body.technical_validation,
        quality_decision=body.quality_decision,
        human_decision=body.human_decision,
    )
    return decision.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/advance-safe"
)
async def advance_workflow_safe_stage(
    project_id: str,
    run_id: str,
    body: WorkflowAdvanceRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    response = await boba.advance_boba_workflow_safe_read_only_stage(
        project_id,
        run_id,
        body.transition_decision_id,
        expected_revision=body.expected_revision,
        integration_parameters=body.integration_parameters or None,
    )
    return response.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/"
    "coordinate-approved-transition"
)
async def coordinate_approved_workflow_transition(
    project_id: str,
    run_id: str,
    body: WorkflowCoordinateApprovedRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    response = await boba.coordinate_approved_boba_workflow_transition(
        project_id,
        run_id,
        body.transition_decision_id,
        expected_revision=body.expected_revision,
        integration_parameters=body.integration_parameters or None,
        approval_binding=body.approval_binding,
        safety_binding=body.safety_binding,
    )
    return response.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/pause"
)
async def pause_workflow_run(
    project_id: str,
    run_id: str,
    body: WorkflowPauseRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    pause = boba.pause_boba_workflow(
        project_id,
        run_id,
        expected_revision=body.expected_revision,
        reason=body.reason,
        category=body.category,
        stage_instance_id=body.stage_instance_id,
    )
    return pause.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/continue"
)
async def continue_workflow_controller(
    project_id: str,
    run_id: str,
    body: WorkflowRevisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    run = boba.continue_boba_workflow_controller(
        project_id,
        run_id,
        expected_revision=body.expected_revision,
    )
    return run.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/cancel"
)
async def cancel_workflow_run(
    project_id: str,
    run_id: str,
    body: WorkflowCancelRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    run = boba.cancel_boba_workflow_run(
        project_id,
        run_id,
        expected_revision=body.expected_revision,
        reason=body.reason,
    )
    return run.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/recovery-holds"
)
async def create_workflow_recovery_hold(
    project_id: str,
    run_id: str,
    body: WorkflowRecoveryHoldRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    hold = boba.create_boba_workflow_recovery_hold(
        project_id,
        run_id,
        failed_stage_instance_id=body.failed_stage_instance_id,
        expected_revision=body.expected_revision,
        reason=body.reason,
        observer_record_id=body.observer_record_id,
    )
    return hold.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/recovery-result"
)
async def receive_workflow_recovery_result(
    project_id: str,
    run_id: str,
    body: WorkflowRecoveryResultRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    hold = boba.receive_boba_autopilot_recovery_result(
        project_id,
        run_id,
        body.recovery_hold_id,
        body.recovery_result,
        expected_revision=body.expected_revision,
    )
    return hold.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/"
    "resume-eligibility"
)
async def evaluate_workflow_resume_eligibility(
    project_id: str,
    run_id: str,
    body: WorkflowResumeEligibilityRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    review = boba.evaluate_boba_workflow_resume_eligibility(
        project_id,
        run_id,
        body.recovery_hold_id,
        expected_revision=body.expected_revision,
        current_project_snapshot_digest=body.current_project_snapshot_digest,
        rights_clear=body.rights_clear,
        approval_record=body.approval_record,
        safety_decision=body.safety_decision,
        checkpoint_valid=body.checkpoint_valid,
        rollback_state_clear=body.rollback_state_clear,
        technical_validation=body.technical_validation,
        quality_decision=body.quality_decision,
        human_decision=body.human_decision,
    )
    return review.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/human-decision"
)
async def record_workflow_human_decision(
    project_id: str,
    run_id: str,
    body: WorkflowHumanDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decision = boba.record_boba_workflow_human_decision(
        project_id,
        run_id,
        expected_revision=body.expected_revision,
        decision_type=body.decision_type,
        decision=body.decision,
        reason=body.reason,
        reviewer_reference=body.reviewer_reference,
        explicit_confirmation=body.explicit_confirmation,
        stage_instance_id=body.stage_instance_id,
        transition_request_id=body.transition_request_id,
        conditions=body.conditions,
        expires_in_seconds=body.expires_in_seconds,
    )
    return decision.model_dump(mode="json")


@router.get(
    "/projects/{project_id}/workflow-controller/runs/{run_id}/events"
)
async def get_workflow_events(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    events = boba.inspect_boba_workflow_events(project_id, run_id)
    return {
        "schema_version": "boba_workflow_event_stream_v1",
        "project_id": project_id,
        "run_id": run_id,
        "events": [item.model_dump(mode="json") for item in events],
    }


@router.get("/projects/{project_id}/workflow-controller/export")
async def export_workflow_controller(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.export_boba_workflow_controller(project_id)


@router.delete("/projects/{project_id}/workflow-controller")
async def reset_workflow_controller(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.reset_boba_workflow_controller(project_id)


@router.post("/projects/{project_id}/autopilot/runs")
async def create_autopilot_run(
    project_id: str,
    body: AutopilotCreateRunRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    controller = await boba.create_boba_autopilot_run(
        project_id,
        control_mode=body.control_mode,
        trigger=body.trigger,
        source_event_id=body.source_event_id,
        recovery_budget=body.recovery_budget or None,
    )
    return controller.model_dump(mode="json")


@router.post("/projects/{project_id}/autopilot/runs/{run_id}/plan-next")
async def plan_autopilot_next_action(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    action = await boba.plan_boba_autopilot_next_action(project_id, run_id)
    return action.model_dump(mode="json")


@router.post("/projects/{project_id}/autopilot/runs/{run_id}/advance-safe")
async def advance_autopilot_safe_read_only(
    project_id: str,
    run_id: str,
    body: AutopilotAdvanceSafeRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    controller = await boba.advance_boba_autopilot_safe_read_only(
        project_id,
        run_id,
        maximum_steps=body.maximum_steps,
    )
    return controller.model_dump(mode="json")


@router.post("/projects/{project_id}/autopilot/runs/{run_id}/coordinate-approved")
async def coordinate_autopilot_approved_action(
    project_id: str,
    run_id: str,
    body: AutopilotCoordinateApprovedRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    controller = await boba.coordinate_approved_boba_autopilot_action(
        project_id,
        run_id,
        action_id=body.action_id,
        approval_record=body.approval_record,
        safety_decision_id=body.safety_decision_id,
    )
    return controller.model_dump(mode="json")


@router.post("/projects/{project_id}/autopilot/runs/{run_id}/pause")
async def pause_autopilot_run(
    project_id: str,
    run_id: str,
    body: AutopilotReasonRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    controller = boba.pause_boba_autopilot_run(
        project_id,
        run_id,
        reason=body.reason or "Human requested a controller pause.",
    )
    return controller.model_dump(mode="json")


@router.post("/projects/{project_id}/autopilot/runs/{run_id}/continue")
async def continue_autopilot_run(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.continue_boba_autopilot_run(
        project_id,
        run_id,
    ).model_dump(mode="json")


@router.post("/projects/{project_id}/autopilot/runs/{run_id}/cancel")
async def cancel_autopilot_run(
    project_id: str,
    run_id: str,
    body: AutopilotReasonRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    controller = boba.cancel_boba_autopilot_run(
        project_id,
        run_id,
        reason=body.reason or "Human cancelled future Autopilot actions.",
    )
    return controller.model_dump(mode="json")


@router.post("/projects/{project_id}/autopilot/runs/{run_id}/human-decision")
async def record_autopilot_human_decision(
    project_id: str,
    run_id: str,
    body: AutopilotHumanDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    controller = boba.record_boba_autopilot_human_decision(
        project_id,
        run_id,
        decision=body.decision,
        reason=body.reason,
        reviewer_identity=body.reviewer_identity,
        action_id=body.action_id,
        selected_alternative_id=body.selected_alternative_id,
    )
    return controller.model_dump(mode="json")


@router.post("/projects/{project_id}/autopilot/runs/{run_id}/budget-reset-request")
async def request_autopilot_budget_reset(
    project_id: str,
    run_id: str,
    body: AutopilotReasonRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    controller = boba.request_boba_autopilot_budget_reset(
        project_id,
        run_id,
        reason=body.reason or "Additional bounded recovery attempts were requested.",
    )
    return controller.model_dump(mode="json")


@router.get("/projects/{project_id}/autopilot")
async def get_autopilot_controller(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    controller = boba.load_boba_autopilot_controller(project_id)
    if controller is None:
        raise NotFoundError(
            "BOBA Autopilot Controller V1 is not available.",
            details={"project_id": project_id},
        )
    return controller.model_dump(mode="json")


@router.get("/projects/{project_id}/autopilot/runs/{run_id}")
async def get_autopilot_run(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    record = boba.store.load_boba_autopilot_run(project_id, run_id)
    if record is None:
        raise NotFoundError(
            "BOBA Autopilot run was not found.",
            details={"run_id": run_id},
        )
    return record


@router.get("/projects/{project_id}/autopilot/runs/{run_id}/events")
async def get_autopilot_events(
    project_id: str,
    run_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    boba.inspect_boba_autopilot_run(project_id, run_id)
    events = boba.store.load_boba_autopilot_events(project_id, run_id)
    return {
        "schema_version": "boba_autopilot_event_stream_v1",
        "project_id": project_id,
        "run_id": run_id,
        "events": [item.model_dump(mode="json") for item in events],
    }


@router.get("/projects/{project_id}/autopilot/export")
async def export_autopilot_controller(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.export_boba_autopilot_controller(project_id)


@router.delete("/projects/{project_id}/autopilot")
async def reset_autopilot_controller(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_boba_autopilot_controller(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "autopilot_metadata_removed": removed,
        "upstream_boba_artifacts_deleted": False,
        "source_media_deleted": False,
        "accepted_outputs_deleted": False,
        "code_surgeon_worktrees_deleted": False,
        "tool_recovery_workspaces_deleted": False,
        "checkpoints_deleted": False,
        "workflow_resumed": False,
        "publication_used": False,
    }


@router.post("/projects/{project_id}/safety-gate/policies")
async def create_safety_gate_policy(
    project_id: str,
    body: SafetyPolicyRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    gate = await boba.create_boba_safety_policy_snapshot(
        project_id,
        project_policy=body.project_policy or None,
    )
    return gate.policy_snapshot.model_dump(mode="json")


@router.post("/projects/{project_id}/safety-gate/requests")
async def create_safety_gate_request(
    project_id: str,
    body: SafetyActionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    request = await boba.create_boba_safety_action_request(
        project_id,
        **body.model_dump(mode="python"),
    )
    return request.model_dump(mode="json")


@router.post("/projects/{project_id}/safety-gate/evaluate")
async def evaluate_safety_gate_request(
    project_id: str,
    body: SafetyEvaluateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decision = await boba.evaluate_boba_safety_action(
        project_id,
        body.action_request_id,
        approval_record=body.approval_record,
    )
    return decision.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/safety-gate/decisions/{decision_id}/revalidate"
)
async def revalidate_safety_gate_decision(
    project_id: str,
    decision_id: str,
    body: SafetyRevalidateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decision = boba.revalidate_boba_safety_decision(
        project_id,
        decision_id,
        approval_record=body.approval_record,
        current_bindings=body.current_bindings or None,
    )
    return decision.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/safety-gate/decisions/{decision_id}/invalidate"
)
async def invalidate_safety_gate_decision(
    project_id: str,
    decision_id: str,
    body: SafetyInvalidateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    invalidation = boba.invalidate_boba_safety_decision(
        project_id,
        decision_id,
        reason=body.reason,
        changes=body.changes or None,
    )
    return invalidation.model_dump(mode="json")


@router.post(
    "/projects/{project_id}/safety-gate/evaluations/{case_id}/human-review"
)
async def record_safety_gate_human_review(
    project_id: str,
    case_id: str,
    body: SafetyHumanReviewRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decision = boba.record_boba_human_safety_review(
        project_id,
        case_id,
        decision=body.decision,
        reason=body.reason,
        reviewer_identity=body.reviewer_identity,
        request_digest=body.request_digest,
        project_snapshot_digest=body.project_snapshot_digest,
    )
    return decision.model_dump(mode="json")


@router.get("/projects/{project_id}/safety-gate")
async def get_safety_gate(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    gate = boba.load_boba_safety_gate(project_id)
    if gate is None:
        raise NotFoundError(
            "BOBA Safety Gate V1 is not available.",
            details={"project_id": project_id},
        )
    return gate.model_dump(mode="json")


@router.get("/projects/{project_id}/safety-gate/evaluations/{case_id}")
async def get_safety_gate_evaluation(
    project_id: str,
    case_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.inspect_boba_safety_evaluation(
        project_id,
        case_id,
    ).model_dump(mode="json")


@router.get("/projects/{project_id}/safety-gate/decisions/{decision_id}")
async def get_safety_gate_decision(
    project_id: str,
    decision_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.inspect_boba_safety_decision(
        project_id,
        decision_id,
    ).model_dump(mode="json")


@router.get("/projects/{project_id}/safety-gate/export")
async def export_safety_gate(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    return boba.export_boba_safety_gate(project_id)


@router.delete("/projects/{project_id}/safety-gate")
async def reset_safety_gate(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_boba_safety_gate(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "safety_gate_summary_removed": removed,
        "immutable_policy_history_deleted": False,
        "immutable_decision_history_deleted": False,
        "upstream_boba_artifacts_deleted": False,
        "approvals_deleted": False,
        "source_media_deleted": False,
        "accepted_outputs_deleted": False,
        "autopilot_history_deleted": False,
        "workflow_resumed": False,
        "checkpoint_restored": False,
        "publication_used": False,
        "action_execution_used": False,
    }


@router.post("/projects/{project_id}/creator-learning/events")
async def record_creator_learning_event(
    project_id: str,
    body: CreatorLearningEventRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    event = await boba.record_creator_feedback_event(
        project_id,
        event_type=body.event_type,
        target_type=body.target_type,
        target_id=body.target_id,
        user_action=body.user_action,
        rating=body.rating,
        note=body.note,
        tags=body.tags,
        reversible=body.reversible,
    )
    return event.model_dump(mode="json")


@router.post("/projects/{project_id}/creator-learning")
async def generate_creator_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
    body: CreatorLearningGenerateRequest | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    request = body or CreatorLearningGenerateRequest()
    learning = await boba.generate_creator_learning_profile(
        project_id,
        creator_id=request.creator_id,
        dry_run=dry_run or request.dry_run,
    )
    return learning.model_dump(mode="json")


@router.get("/projects/{project_id}/creator-learning")
async def get_creator_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    learning = boba.load_creator_learning_profile(project_id)
    if learning is None:
        raise NotFoundError(
            "BOBA creator learning is not available.",
            details={"project_id": project_id},
        )
    return learning.model_dump(mode="json")


@router.get("/projects/{project_id}/creator-learning/export")
async def export_creator_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_creator_learning_profile(project_id) is None:
        raise NotFoundError(
            "BOBA creator learning is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_creator_learning_profile(project_id)


@router.delete("/projects/{project_id}/creator-learning")
async def reset_creator_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_creator_learning_profile(project_id)
    return {
        "reset": True,
        "project_id": project_id,
        "creator_learning_removed": removed,
        "unrelated_memory_removed": False,
    }


@router.post("/projects/{project_id}/approval-rejection-learning")
async def generate_approval_rejection_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
    body: ApprovalRejectionLearningGenerateRequest | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    request = body or ApprovalRejectionLearningGenerateRequest()
    learning = await boba.generate_approval_rejection_learning(
        project_id,
        creator_id=request.creator_id,
        dry_run=dry_run or request.dry_run,
    )
    return learning.model_dump(mode="json")


@router.get("/projects/{project_id}/approval-rejection-learning")
async def get_approval_rejection_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    learning = boba.load_approval_rejection_learning(project_id)
    if learning is None:
        raise NotFoundError(
            "BOBA approval/rejection learning is not available.",
            details={"project_id": project_id},
        )
    return learning.model_dump(mode="json")


@router.get("/projects/{project_id}/approval-rejection-learning/export")
async def export_approval_rejection_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_approval_rejection_learning(project_id) is None:
        raise NotFoundError(
            "BOBA approval/rejection learning is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_approval_rejection_learning(project_id)


@router.delete("/projects/{project_id}/approval-rejection-learning")
async def reset_approval_rejection_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_approval_rejection_learning(project_id)
    return {
        "reset": True,
        "project_id": project_id,
        "approval_rejection_learning_removed": removed,
        "creator_learning_removed": False,
        "unrelated_memory_removed": False,
    }


def _brief_decision(
    project_id: str,
    clip_id: str,
    decision: BobaApprovalDecision,
    body: CreativeBriefDecisionRequest,
    boba: BobaIntegrationDep,
) -> dict[str, Any]:
    event, lesson = boba.approvals.decide_clip_idea(
        project_id,
        clip_id,
        decision=decision,
        reason=body.reason,
        creator_profile_id=body.creator_profile_id,
    )
    return {
        "approval": event.model_dump(mode="json"),
        "memory_lesson_id": lesson.memory_id,
        "rendering_triggered": False,
    }


@router.post("/projects/{project_id}/creative-briefs/{clip_id}/approve")
async def approve_creative_brief(
    project_id: str,
    clip_id: str,
    body: CreativeBriefDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    return _brief_decision(project_id, clip_id, "approved", body, boba)


@router.post("/projects/{project_id}/creative-briefs/{clip_id}/reject")
async def reject_creative_brief(
    project_id: str,
    clip_id: str,
    body: CreativeBriefDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    return _brief_decision(project_id, clip_id, "rejected", body, boba)


@router.get("/projects/{project_id}/brain")
async def get_brain(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    state = boba.store.load_brain_state(project_id)
    if state is None:
        state = await boba.generate_boba_for_project(project_id)
    return state.model_dump(mode="json")


@router.get("/projects/{project_id}/decisions")
async def get_decisions(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decisions = boba.store.list_decisions(project_id)
    return {
        "project_id": project_id,
        "mode": "advisory",
        "count": len(decisions),
        "decisions": [item.model_dump(mode="json") for item in decisions],
    }


@router.get("/projects/{project_id}/observations")
async def get_observations(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    observations = boba.store.list_observations(project_id)
    return {
        "project_id": project_id,
        "count": len(observations),
        "observations": [item.model_dump(mode="json") for item in observations],
    }


@router.post("/projects/{project_id}/summarize")
async def summarize_project(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    state = await boba.generate_boba_for_project(project_id)
    return {
        "brain": state.model_dump(mode="json"),
        "summary": boba.brain.summarize_current_state(project_id),
    }


@router.post("/projects/{project_id}/rank-candidates")
async def rank_project_candidates(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_candidate_ranking:
        raise ValidationError("BOBA candidate ranking is disabled by configuration.")
    await _require_project(project_id, boba)
    return (await boba.rank_project_candidates(project_id)).model_dump(mode="json")


@router.post("/projects/{project_id}/editorial-policy")
async def create_project_editorial_policy(
    project_id: str,
    body: EditorialPolicyRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_editorial_policy:
        raise ValidationError("BOBA editorial policy is disabled by configuration.")
    await _require_project(project_id, boba)
    return (await boba.generate_boba_for_clip(project_id, body.clip_id)).model_dump(
        mode="json"
    )


@router.get("/memory/projects/{project_id}")
async def get_project_memory(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    memory = boba.store.load_project_memory(project_id)
    if memory is None:
        memory = await boba.build_project_memory(project_id)
    return memory.model_dump(mode="json")


@router.post("/memory/projects/{project_id}/build")
async def build_project_memory_route(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    return (await boba.build_project_memory(project_id)).model_dump(mode="json")


@router.get("/memory/creators/{profile_id}")
def get_creator_memory(
    profile_id: str,
    boba: BobaIntegrationDep,
    personalization: PersonalizationServiceDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_creator_memory:
        raise ValidationError("Creator memory is disabled by configuration.")
    memory = boba.store.load_creator_memory(profile_id)
    if memory is None:
        profile = personalization.get_profile(profile_id)
        memory = build_and_save_creator_memory(
            boba.store,
            profile,
            personalization.store.list_feedback(profile_id),
        )
    return memory.model_dump(mode="json")


@router.post("/memory/creators/{profile_id}/build")
def build_creator_memory_route(
    profile_id: str,
    boba: BobaIntegrationDep,
    personalization: PersonalizationServiceDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_creator_memory:
        raise ValidationError("Creator memory is disabled by configuration.")
    profile = personalization.get_profile(profile_id)
    return build_and_save_creator_memory(
        boba.store,
        profile,
        personalization.store.list_feedback(profile_id),
    ).model_dump(mode="json")


@router.get("/memory/global")
def get_global_memory(
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_global_memory:
        raise ValidationError("Global memory is disabled by configuration.")
    memory = boba.store.load_global_memory() or build_and_save_global_memory(boba.store)
    return memory.model_dump(mode="json")


@router.post("/memory/global/build")
def build_global_memory_route(
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_global_memory:
        raise ValidationError("Global memory is disabled by configuration.")
    return build_and_save_global_memory(boba.store).model_dump(mode="json")


@router.post("/memory/query")
def query_memory(
    body: BobaMemoryQueryV1,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    return boba.store.query_memory(body).model_dump(mode="json")


@router.post("/memory/feedback")
async def record_memory_feedback(
    body: MemoryFeedbackRequest,
    boba: BobaIntegrationDep,
    personalization: PersonalizationServiceDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(body.project_id, boba)
    feedback = personalization.record_feedback(
        profile_id=body.profile_id,
        project_id=body.project_id,
        clip_id=body.clip_id,
        rating=body.rating,
        labels=body.labels,
        notes=body.notes,
        clip_traits=body.clip_traits,
    )
    if personalization.memory_feedback_callback is None:
        BobaMemoryLearner(boba.store).learn_from_feedback(feedback)
        build_and_save_creator_memory(
            boba.store,
            personalization.get_profile(body.profile_id),
            personalization.store.list_feedback(body.profile_id),
        )
    creator_memory = boba.store.load_creator_memory(body.profile_id)
    if creator_memory is None:
        raise ValidationError("Creator memory was not created from explicit feedback.")
    return {
        "feedback": feedback.model_dump(mode="json"),
        "creator_memory": creator_memory.model_dump(mode="json"),
    }


@router.get("/memory/export")
def export_memory(
    boba: BobaIntegrationDep,
    settings: SettingsDep,
    scope: Literal["project", "creator", "global"] | None = None,
    identifier: str | None = None,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_import_export:
        raise ValidationError("BOBA memory export is disabled by configuration.")
    return boba.store.export_memory(scope, identifier)


@router.post("/memory/import")
def import_memory(
    body: MemoryImportRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not body.confirm:
        raise ValidationError("BOBA memory import requires explicit confirmation.")
    if not settings.boba_memory.allow_import_export:
        raise ValidationError("BOBA memory import is disabled by configuration.")
    return {"imported": boba.store.import_memory(body.payload)}


@router.post("/memory/reset")
def reset_memory(
    body: MemoryResetRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not body.confirm:
        raise ValidationError("BOBA memory reset requires explicit confirmation.")
    if body.scope == "project":
        if not body.identifier:
            raise ValidationError("Project memory reset requires identifier.")
        backup = boba.store.reset_project_memory(body.identifier)
    elif body.scope == "creator":
        if not body.identifier:
            raise ValidationError("Creator memory reset requires identifier.")
        backup = boba.store.reset_creator_memory(body.identifier)
    else:
        backup = boba.store.reset_global_memory()
    return {
        "reset": True,
        "scope": body.scope,
        "identifier": body.identifier,
        "backup_created": backup is not None,
        "backup_name": backup.name if backup else None,
    }

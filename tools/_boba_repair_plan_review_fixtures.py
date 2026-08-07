"""Synthetic canonical BOBA repair-planning records built through real contracts.

Shared by the Repair Plan Review validator and its unit tests so both exercise
genuine module contracts rather than hand-written dictionaries.

The fixtures deliberately include records that a reviewer must be warned about:
a strategy whose step target holds literal command text, a private absolute
path, a non-destructive rating on a code-changing strategy, an approval gate
that says approval is not required while the strategy acts, a plan marked ready
while a required validator failed, and a recovery attempt the owner called a
success while its own output validation records unmet required checks.
"""

from __future__ import annotations

from typing import Any

from olympus.boba.repair_planner import (
    BobaQualityPreservationPlanV1,
    BobaRepairApprovalGateV1,
    BobaRepairCheckpointPlanV1,
    BobaRepairExecutionHandoffV1,
    BobaRepairPlannerSetV1,
    BobaRepairPlannerSignalUsageV1,
    BobaRepairPlannerSummaryV1,
    BobaRepairPlanningCaseV1,
    BobaRepairRejectedStrategyV1,
    BobaRepairRiskAssessmentV1,
    BobaRepairRollbackPlanV1,
    BobaRepairStepV1,
    BobaRepairStrategyRiskV1,
    BobaRepairStrategyV1,
    BobaRepairValidationCheckV1,
    BobaRepairValidationPlanV1,
)
from olympus.boba.root_cause_analyzer import (
    BobaRootCauseAnalysisCaseV1,
    BobaRootCauseAnalyzerSetV1,
    BobaRootCauseAnalyzerSummaryV1,
    BobaRootCauseCandidateV1,
    BobaRootCauseSignalUsageV1,
)
from olympus.boba.store import BobaMemoryStore
from olympus.boba.tool_recovery import (
    BobaRecoveredOutputValidationV1,
    BobaToolRecoveryAttemptV1,
    BobaToolRecoveryBrainSetV1,
    BobaToolRecoveryCaseV1,
    BobaToolRecoveryRollbackV1,
    BobaToolRecoverySignalUsageV1,
    BobaToolRecoverySummaryV1,
)

# Stable identities the validator and the unit tests both assert against.
PROJECT_ID = "repair-plan-review-project"
INCIDENT_ID = "case_a"
ANALYSIS_CASE_ID = "analysis_a"
CANDIDATE_ID = "candidate_a"
REPAIR_CASE_ID = "repair_case_a"

# The reviewed repair plan identity is always a repair_strategy_id.
PLAN_REVERSIBLE = "strategy_reversible_a"
PLAN_CODE_CHANGE = "strategy_code_change_a"
PLAN_CHECKPOINT = "strategy_checkpoint_a"
PLAN_DESTRUCTIVE = "strategy_destructive_a"

# A step target that holds literal command text. The panel must never project it.
COMMAND_TARGET = "ffmpeg -i /home/operator/media/source.mp4 -c:v libx264 out.mp4"
PRIVATE_PATH_TARGET = "/home/operator/media/render_manifest.json"
SHELL_TARGET = "cd /root/work && rm -rf ./tmp || true"


# ----------------------------------------------------------------------
# Root Cause Analyzer
# ----------------------------------------------------------------------
def synthetic_root_cause_candidate(
    candidate_id: str = CANDIDATE_ID,
    *,
    analysis_case_id: str = ANALYSIS_CASE_ID,
    repairability: str = "recoverable_with_approval",
) -> BobaRootCauseCandidateV1:
    return BobaRootCauseCandidateV1(
        root_cause_candidate_id=candidate_id,
        analysis_case_id=analysis_case_id,
        title="The encoder rejected the requested pixel format",
        category="configuration",
        candidate_summary=(
            "The encoder capability recorded by Observer does not include the "
            "requested pixel format."
        ),
        earliest_failure_relationship="matches_earliest_failure",
        supporting_evidence_ids=["evidence_a"],
        conflicting_evidence_ids=[],
        likelihood_score=0.71,
        confidence=0.66,
        evidence_quality="moderate",
        verification_required=True,
        repairability=repairability,
        recommended_owner_module="repair_planner",
        warnings=["This candidate is a hypothesis until verified."],
    )


def synthetic_analysis_case(
    analysis_case_id: str = ANALYSIS_CASE_ID,
    *,
    incident_id: str = INCIDENT_ID,
    analysis_status: str = "probable_root_cause",
) -> BobaRootCauseAnalysisCaseV1:
    return BobaRootCauseAnalysisCaseV1(
        analysis_case_id=analysis_case_id,
        source_diagnostic_case_id=incident_id,
        title="Render stage stopped before writing output",
        primary_module="rendering",
        primary_artifact="render_manifest",
        workflow_stage="render",
        analysis_status=analysis_status,
        earliest_known_failure="The encoder exited before the manifest was written.",
        most_likely_root_cause="The encoder rejected the requested pixel format.",
        root_cause_confidence=0.66,
        confirmed_facts=["The expected output artifact does not exist."],
        probable_inferences=["The encoder configuration is unsupported."],
        affected_modules=["rendering"],
        affected_artifacts=["render_manifest"],
        processing_impact="full_block",
        safety_impact="none_known",
        recommended_handoff="repair_planner",
        human_review_required=True,
        limitations=["A most-likely root cause is not a confirmed fact."],
    )


def synthetic_root_cause_set(
    project_id: str = PROJECT_ID,
    *,
    cases: list[BobaRootCauseAnalysisCaseV1] | None = None,
    candidates: list[BobaRootCauseCandidateV1] | None = None,
) -> BobaRootCauseAnalyzerSetV1:
    return BobaRootCauseAnalyzerSetV1(
        project_id=project_id,
        source_id="synthetic_source",
        error_doctor_source="error_doctor_report",
        analysis_cases=cases if cases is not None else [synthetic_analysis_case()],
        root_cause_candidates=candidates
        if candidates is not None
        else [synthetic_root_cause_candidate()],
        analyzer_summary=BobaRootCauseAnalyzerSummaryV1(),
        signal_usage=BobaRootCauseSignalUsageV1(error_doctor_used=True),
    )


# ----------------------------------------------------------------------
# Repair Planner
# ----------------------------------------------------------------------
def synthetic_step(
    step_id: str,
    *,
    strategy_id: str,
    order: int,
    step_type: str = "inspect",
    description: str = "Read the recorded encoder capability for this stage.",
    target: str = "render_manifest",
    read_only: bool = True,
    reversible: bool = True,
    requires_command_execution: bool = False,
    requires_code_change: bool = False,
    requires_external_access: bool = False,
    rollback_step_reference: str = "",
    suggested_owner_module: str = "artifact_inspector",
) -> BobaRepairStepV1:
    return BobaRepairStepV1(
        repair_step_id=step_id,
        repair_strategy_id=strategy_id,
        order=order,
        step_type=step_type,
        description=description,
        target=target,
        read_only=read_only,
        reversible=reversible,
        requires_command_execution=requires_command_execution,
        requires_code_change=requires_code_change,
        requires_external_access=requires_external_access,
        safety_precondition="A checkpoint must exist before this step runs.",
        success_condition="The recorded capability matches the requested format.",
        failure_condition="The capability is still missing the requested format.",
        stop_condition="Stop if the source media would be touched.",
        rollback_step_reference=rollback_step_reference,
        suggested_owner_module=suggested_owner_module,
    )


def synthetic_strategy(
    strategy_id: str = PLAN_REVERSIBLE,
    *,
    repair_case_id: str = REPAIR_CASE_ID,
    title: str = "Retry the render with a supported pixel format",
    strategy_type: str = "retry_with_safe_settings",
    reversibility: str = "fully_reversible",
    destructiveness: str = "none",
    estimated_risk: str = "low",
    automation_eligibility: str = "human_execution_required",
    requires_command_execution: bool = False,
    requires_code_change: bool = False,
    requires_configuration_change: bool = False,
    requires_service_restart: bool = False,
    requires_package_installation: bool = False,
    requires_external_access: bool = False,
    requires_checkpoint: bool = True,
    requires_backup: bool = True,
    recommended: bool = True,
    rank: int = 1,
    steps: list[BobaRepairStepV1] | None = None,
) -> BobaRepairStrategyV1:
    return BobaRepairStrategyV1(
        repair_strategy_id=strategy_id,
        repair_case_id=repair_case_id,
        title=title,
        strategy_type=strategy_type,
        target_module="rendering",
        target_artifact="render_manifest",
        description="Re-run the render stage using a capability the encoder records.",
        rationale=(
            "Root Cause Analyzer recorded that the requested pixel format is absent "
            "from the encoder capability."
        ),
        easy_explanation=(
            "Try the render again with a setting the encoder already supports."
        ),
        root_cause_candidate_ids=[CANDIDATE_ID],
        prerequisites=["A checkpoint of the current generated state must exist."],
        proposed_steps=steps
        if steps is not None
        else [
            synthetic_step(
                f"{strategy_id}_step_1", strategy_id=strategy_id, order=1
            ),
            synthetic_step(
                f"{strategy_id}_step_2",
                strategy_id=strategy_id,
                order=2,
                step_type="validate_result",
                description="Confirm the new output matches the approved baseline.",
                suggested_owner_module="validator_runner",
                rollback_step_reference=f"{strategy_id}_step_1",
            ),
        ],
        expected_result="A render output that matches the approved baseline.",
        expected_quality_effect="No reduction against the approved baseline.",
        expected_workflow_effect="The render stage can be retried in place.",
        reversibility=reversibility,
        destructiveness=destructiveness,
        automation_eligibility=automation_eligibility,
        requires_checkpoint=requires_checkpoint,
        requires_backup=requires_backup,
        requires_command_execution=requires_command_execution,
        requires_validator_execution=True,
        requires_code_change=requires_code_change,
        requires_configuration_change=requires_configuration_change,
        requires_tool_fallback=False,
        requires_service_restart=requires_service_restart,
        requires_package_installation=requires_package_installation,
        requires_external_access=requires_external_access,
        requires_paid_service=False,
        requires_rights_review=False,
        estimated_risk=estimated_risk,
        estimated_complexity="low",
        estimated_confidence=0.63,
        strategy_score=0.58,
        rank=rank,
        recommended=recommended,
        maximum_attempts=2,
        escalation_condition="Escalate if the second attempt also fails.",
        prohibited_actions=["Never modify the source media."],
        stop_conditions=["Stop if the accepted output would change."],
    )


def synthetic_planning_case(
    repair_case_id: str = REPAIR_CASE_ID,
    *,
    analysis_case_id: str = ANALYSIS_CASE_ID,
    planning_status: str = "plan_ready",
    repair_needed: bool = True,
    repair_scope: str = "rendering",
    strategy_ids: list[str] | None = None,
    recommended_strategy_id: str = PLAN_REVERSIBLE,
    alternative_strategy_ids: list[str] | None = None,
    rejected_strategy_ids: list[str] | None = None,
    approval_gate_id: str = "gate_a",
    rollback_plan_id: str = "rollback_a",
    checkpoint_plan_id: str = "checkpoint_a",
    validation_plan_id: str = "validation_a",
    risk_assessment_id: str = "risk_a",
    quality_preservation_plan_id: str = "quality_a",
    blocked_reason: str = "",
) -> BobaRepairPlanningCaseV1:
    return BobaRepairPlanningCaseV1(
        repair_case_id=repair_case_id,
        source_analysis_case_id=analysis_case_id,
        title="Repair the render stage output",
        primary_module="rendering",
        primary_artifact="render_manifest",
        workflow_stage="render",
        root_cause_candidate_ids=[CANDIDATE_ID],
        selected_root_cause_candidate_id=CANDIDATE_ID,
        planning_status=planning_status,
        repair_needed=repair_needed,
        repair_scope=repair_scope,
        blocked_reason=blocked_reason,
        strategy_ids=strategy_ids
        if strategy_ids is not None
        else [PLAN_REVERSIBLE, PLAN_CODE_CHANGE, PLAN_CHECKPOINT, PLAN_DESTRUCTIVE],
        recommended_strategy_id=recommended_strategy_id,
        alternative_strategy_ids=alternative_strategy_ids
        if alternative_strategy_ids is not None
        else [PLAN_CODE_CHANGE, PLAN_CHECKPOINT],
        rejected_strategy_ids=rejected_strategy_ids
        if rejected_strategy_ids is not None
        else [],
        risk_assessment_id=risk_assessment_id,
        checkpoint_plan_id=checkpoint_plan_id,
        rollback_plan_id=rollback_plan_id,
        validation_plan_id=validation_plan_id,
        quality_preservation_plan_id=quality_preservation_plan_id,
        approval_gate_id=approval_gate_id,
        execution_handoff_ids=["handoff_a"],
        expected_workflow_impact="The render stage stays blocked until a human acts.",
        confidence=0.6,
        limitations=["Planning only. Repair Planner executes nothing."],
    )


def synthetic_risk_assessment(
    risk_assessment_id: str = "risk_a",
    *,
    repair_case_id: str = REPAIR_CASE_ID,
    overall_risk: str = "medium",
    strategy_risks: list[BobaRepairStrategyRiskV1] | None = None,
    blockers: list[str] | None = None,
) -> BobaRepairRiskAssessmentV1:
    return BobaRepairRiskAssessmentV1(
        risk_assessment_id=risk_assessment_id,
        repair_case_id=repair_case_id,
        strategy_risks=strategy_risks
        if strategy_risks is not None
        else [
            BobaRepairStrategyRiskV1(
                strategy_id=PLAN_REVERSIBLE,
                risk_level="low",
                risk_reasons=["The step set is read-only until validation."],
                mitigations=["Take a checkpoint before the retry."],
                residual_risk="The retry may fail for the same reason.",
                acceptable_only_if=["A checkpoint exists."],
                blocked=False,
                confidence=0.62,
            ),
            BobaRepairStrategyRiskV1(
                strategy_id=PLAN_DESTRUCTIVE,
                risk_level="critical",
                risk_reasons=["The strategy replaces generated state in place."],
                mitigations=["Require an explicit human decision."],
                residual_risk="Generated state may not be recoverable.",
                acceptable_only_if=["A verified checkpoint exists."],
                blocked=True,
                confidence=0.44,
            ),
        ],
        overall_risk=overall_risk,
        source_data_risk="minimal",
        artifact_loss_risk="medium",
        output_quality_risk="high",
        workflow_corruption_risk="medium",
        configuration_risk="medium",
        environment_risk="low",
        security_risk="minimal",
        rights_safety_risk="low",
        external_dependency_risk="minimal",
        rollback_failure_risk="medium",
        human_error_risk="medium",
        blockers=blockers if blockers is not None else [],
        mitigations=["Take a checkpoint before any state-changing step."],
        residual_risks=["A retry may reproduce the same encoder rejection."],
        human_review_notes=["A human must choose between the recorded strategies."],
    )


def synthetic_approval_gate(
    approval_gate_id: str = "gate_a",
    *,
    repair_case_id: str = REPAIR_CASE_ID,
    approval_status: str = "awaiting_human_review",
    rights_gate_required: bool = False,
    code_review_required: bool = False,
) -> BobaRepairApprovalGateV1:
    return BobaRepairApprovalGateV1(
        approval_gate_id=approval_gate_id,
        repair_case_id=repair_case_id,
        approval_status=approval_status,
        required_approvals=["Final human approval", "Safety Gate approval"],
        actions_allowed_without_approval=["Read the recorded plan."],
        actions_requiring_approval=["Any step that changes state."],
        prohibited_actions=["Modifying the source media."],
        rights_gate_required=rights_gate_required,
        code_review_required=code_review_required,
    )


def synthetic_rollback_plan(
    rollback_plan_id: str = "rollback_a",
    *,
    repair_case_id: str = REPAIR_CASE_ID,
    rollback_required: bool = True,
    rollback_scope: str = "artifact",
) -> BobaRepairRollbackPlanV1:
    return BobaRepairRollbackPlanV1(
        rollback_plan_id=rollback_plan_id,
        repair_case_id=repair_case_id,
        rollback_required=rollback_required,
        rollback_scope=rollback_scope,
        rollback_trigger_conditions=["The retry produces a lower-quality output."],
        # Rollback steps hold command text on purpose: the panel must never
        # project this list into a browser payload.
        rollback_steps=[
            "git checkout -- ./generated",
            SHELL_TARGET,
        ],
        preserved_state_required=["render_manifest", "caption_track"],
        rollback_validation=["Confirm the prior generated state is byte-identical."],
        rollback_owner_module="checkpoint_recovery_manager",
    )


def synthetic_checkpoint_plan(
    checkpoint_plan_id: str = "checkpoint_a",
    *,
    repair_case_id: str = REPAIR_CASE_ID,
    checkpoint_required: bool = True,
    checkpoint_validation_required: bool = True,
) -> BobaRepairCheckpointPlanV1:
    return BobaRepairCheckpointPlanV1(
        checkpoint_plan_id=checkpoint_plan_id,
        repair_case_id=repair_case_id,
        checkpoint_required=checkpoint_required,
        checkpoint_type="generated_state_snapshot",
        artifacts_to_preserve=["render_manifest", "caption_track"],
        state_to_preserve=["render_stage_progress"],
        checkpoint_validation_required=checkpoint_validation_required,
    )


def synthetic_validation_plan(
    validation_plan_id: str = "validation_a",
    *,
    repair_case_id: str = REPAIR_CASE_ID,
    required_validators: list[str] | None = None,
    requires_validator_runner: bool = True,
) -> BobaRepairValidationPlanV1:
    return BobaRepairValidationPlanV1(
        validation_plan_id=validation_plan_id,
        repair_case_id=repair_case_id,
        pre_repair_checks=[
            BobaRepairValidationCheckV1(
                validation_check_id="precheck_a",
                phase="pre_repair",
                category="artifact_integrity",
                description="Confirm a checkpoint of the generated state exists.",
                validator_name="checkpoint_presence",
                expected_result="A checkpoint is present and readable.",
                required=True,
                blocks_acceptance_on_failure=True,
            )
        ],
        post_repair_checks=[
            BobaRepairValidationCheckV1(
                validation_check_id="postcheck_a",
                phase="post_repair",
                category="output_quality",
                description="Compare the new output against the approved baseline.",
                validator_name="baseline_comparison",
                expected_result="No regression against the approved baseline.",
                required=True,
                blocks_acceptance_on_failure=True,
            )
        ],
        required_validators=required_validators
        if required_validators is not None
        else ["checkpoint_presence", "baseline_comparison"],
        acceptance_criteria=["Every required check passes."],
        rejection_criteria=["Any required check fails."],
        comparison_baseline=["approved_baseline"],
        output_quality_checks=["Compare against the approved baseline."],
        requires_validator_runner=requires_validator_runner,
    )


def synthetic_quality_plan(
    quality_preservation_plan_id: str = "quality_a",
    *,
    repair_case_id: str = REPAIR_CASE_ID,
) -> BobaQualityPreservationPlanV1:
    return BobaQualityPreservationPlanV1(
        quality_preservation_plan_id=quality_preservation_plan_id,
        repair_case_id=repair_case_id,
        original_requirements=["Match the approved baseline resolution."],
        non_negotiable_requirements=["Never modify the source media."],
        acceptable_degradations=[],
        unacceptable_degradations=["Any caption timing drift."],
        comparison_metrics=["resolution", "duration", "caption_timing"],
    )


def synthetic_handoff(
    handoff_id: str = "handoff_a",
    *,
    repair_case_id: str = REPAIR_CASE_ID,
    repair_strategy_id: str = PLAN_REVERSIBLE,
    target_module: str = "tool_recovery_brain",
) -> BobaRepairExecutionHandoffV1:
    return BobaRepairExecutionHandoffV1(
        handoff_id=handoff_id,
        repair_case_id=repair_case_id,
        repair_strategy_id=repair_strategy_id,
        target_module=target_module,
        reason="A human approved retry must be executed by its capability owner.",
        required_capability="video_render",
        checkpoint_plan_id="checkpoint_a",
        rollback_plan_id="rollback_a",
        validation_plan_id="validation_a",
        approval_gate_id="gate_a",
        priority="high",
    )


def synthetic_rejected_strategy(
    rejected_strategy_id: str = "rejected_a",
    *,
    repair_case_id: str = REPAIR_CASE_ID,
) -> BobaRepairRejectedStrategyV1:
    return BobaRepairRejectedStrategyV1(
        rejected_strategy_id=rejected_strategy_id,
        repair_case_id=repair_case_id,
        title="Delete the generated state and start over",
        strategy_type="repair_generated_state",
        rejection_reason="The action is irreversible and destroys prior work.",
        safety_reason="Safety Gate would block an irreversible deletion.",
        quality_reason="The approved baseline could not be reproduced.",
        reversibility_reason="No rollback path exists once state is deleted.",
    )


def command_bearing_strategy() -> BobaRepairStrategyV1:
    """A strategy whose steps hold literal command text and a private path."""
    return synthetic_strategy(
        PLAN_CODE_CHANGE,
        title="Patch the encoder configuration module",
        strategy_type="propose_code_patch",
        reversibility="partially_reversible",
        # Rated non-destructive while declaring a code change on purpose, so the
        # conflict detector has a real disagreement to report.
        destructiveness="none",
        estimated_risk="high",
        requires_command_execution=True,
        requires_code_change=True,
        requires_configuration_change=True,
        recommended=False,
        rank=2,
        steps=[
            synthetic_step(
                f"{PLAN_CODE_CHANGE}_step_1",
                strategy_id=PLAN_CODE_CHANGE,
                order=1,
                step_type="propose_patch",
                description="Prepare a patch for the encoder configuration module.",
                target=PRIVATE_PATH_TARGET,
                read_only=False,
                requires_code_change=True,
                suggested_owner_module="code_surgeon",
            ),
            synthetic_step(
                f"{PLAN_CODE_CHANGE}_step_2",
                strategy_id=PLAN_CODE_CHANGE,
                order=2,
                step_type="retry",
                # The description itself is command text and must be withheld.
                description=COMMAND_TARGET,
                target=COMMAND_TARGET,
                read_only=False,
                reversible=False,
                requires_command_execution=True,
                suggested_owner_module="tool_recovery_brain",
            ),
            synthetic_step(
                f"{PLAN_CODE_CHANGE}_step_3",
                strategy_id=PLAN_CODE_CHANGE,
                order=3,
                step_type="restart_service",
                description="Restart the render worker so the patch is loaded.",
                target="render_worker",
                read_only=False,
                suggested_owner_module="workflow_controller",
            ),
        ],
    )


def checkpoint_strategy() -> BobaRepairStrategyV1:
    return synthetic_strategy(
        PLAN_CHECKPOINT,
        title="Restore the last good checkpoint",
        strategy_type="restore_checkpoint",
        reversibility="difficult_to_reverse",
        destructiveness="medium",
        estimated_risk="high",
        recommended=False,
        rank=3,
        steps=[
            synthetic_step(
                f"{PLAN_CHECKPOINT}_step_1",
                strategy_id=PLAN_CHECKPOINT,
                order=1,
                step_type="restore",
                description="Restore the generated state from the last checkpoint.",
                target="checkpoint_a",
                read_only=False,
                reversible=False,
                suggested_owner_module="checkpoint_recovery_manager",
            ),
            synthetic_step(
                f"{PLAN_CHECKPOINT}_step_2",
                strategy_id=PLAN_CHECKPOINT,
                order=2,
                step_type="resume_workflow",
                description="Resume the workflow from the restored stage.",
                target="render",
                read_only=False,
                suggested_owner_module="workflow_controller",
            ),
        ],
    )


def destructive_strategy() -> BobaRepairStrategyV1:
    return synthetic_strategy(
        PLAN_DESTRUCTIVE,
        title="Regenerate the artifact in place",
        strategy_type="regenerate_artifact",
        # Fully reversible and blocked at the same time, on purpose.
        reversibility="fully_reversible",
        destructiveness="blocked",
        estimated_risk="critical",
        automation_eligibility="blocked",
        requires_package_installation=True,
        requires_external_access=True,
        recommended=False,
        rank=4,
        steps=[
            synthetic_step(
                f"{PLAN_DESTRUCTIVE}_step_1",
                strategy_id=PLAN_DESTRUCTIVE,
                order=1,
                step_type="regenerate",
                description="Replace the artifact with a newly generated one.",
                target="render_manifest",
                read_only=False,
                reversible=False,
                suggested_owner_module="tool_recovery_brain",
            )
        ],
    )


def synthetic_repair_planner_set(
    project_id: str = PROJECT_ID,
    *,
    cases: list[BobaRepairPlanningCaseV1] | None = None,
    strategies: list[BobaRepairStrategyV1] | None = None,
    risk_assessments: list[BobaRepairRiskAssessmentV1] | None = None,
    approval_gates: list[BobaRepairApprovalGateV1] | None = None,
    rollback_plans: list[BobaRepairRollbackPlanV1] | None = None,
    checkpoint_plans: list[BobaRepairCheckpointPlanV1] | None = None,
    validation_plans: list[BobaRepairValidationPlanV1] | None = None,
    quality_plans: list[BobaQualityPreservationPlanV1] | None = None,
    handoffs: list[BobaRepairExecutionHandoffV1] | None = None,
    rejected: list[BobaRepairRejectedStrategyV1] | None = None,
) -> BobaRepairPlannerSetV1:
    return BobaRepairPlannerSetV1(
        project_id=project_id,
        source_id="synthetic_source",
        root_cause_analyzer_source="root_cause_report",
        repair_cases=cases if cases is not None else [synthetic_planning_case()],
        repair_strategies=strategies
        if strategies is not None
        else [
            synthetic_strategy(),
            command_bearing_strategy(),
            checkpoint_strategy(),
            destructive_strategy(),
        ],
        risk_assessments=risk_assessments
        if risk_assessments is not None
        else [synthetic_risk_assessment()],
        checkpoint_plans=checkpoint_plans
        if checkpoint_plans is not None
        else [synthetic_checkpoint_plan()],
        rollback_plans=rollback_plans
        if rollback_plans is not None
        else [synthetic_rollback_plan()],
        validation_plans=validation_plans
        if validation_plans is not None
        else [synthetic_validation_plan()],
        quality_preservation_plans=quality_plans
        if quality_plans is not None
        else [synthetic_quality_plan()],
        approval_gates=approval_gates
        if approval_gates is not None
        else [synthetic_approval_gate()],
        execution_handoffs=handoffs if handoffs is not None else [synthetic_handoff()],
        rejected_strategies=rejected
        if rejected is not None
        else [synthetic_rejected_strategy()],
        planner_summary=BobaRepairPlannerSummaryV1(total_repair_cases=1),
        signal_usage=BobaRepairPlannerSignalUsageV1(root_cause_analyzer_used=True),
        limitations=["Repair Planner plans; it never executes."],
    )


# ----------------------------------------------------------------------
# Tool Recovery
# ----------------------------------------------------------------------
def synthetic_recovery_set(
    project_id: str = PROJECT_ID,
    *,
    repair_case_id: str = REPAIR_CASE_ID,
    strategy_ids: list[str] | None = None,
    attempt_status: str = "succeeded_pending_validation",
    required_checks_passed: bool = False,
) -> BobaToolRecoveryBrainSetV1:
    """A recovery attempt the owner called a success while validation disagrees."""
    case = BobaToolRecoveryCaseV1(
        recovery_case_id="recovery_case_a",
        source_repair_case_id=repair_case_id,
        source_repair_strategy_ids=strategy_ids
        if strategy_ids is not None
        else [PLAN_REVERSIBLE],
        title="Retry the render with a registered fallback tool",
        target_module="rendering",
        workflow_stage="render",
        required_capability="video_render",
        failing_tool_id="primary_encoder",
        failure_class="repeated_crash",
        rights_status="clear",
        safety_status="human_review_needed",
        checkpoint_required=True,
        checkpoint_ready=True,
        rollback_ready=True,
        recovery_eligible=True,
        human_approval_required=True,
        confidence=0.55,
    )
    attempts = [
        BobaToolRecoveryAttemptV1(
            recovery_attempt_id="recovery_attempt_a",
            recovery_case_id="recovery_case_a",
            recovery_plan_id="recovery_plan_a",
            recovery_strategy_id="recovery_strategy_a",
            attempt_number=1,
            tool_id="fallback_encoder",
            capability_id="video_render",
            execution_started_at="2026-02-01T11:00:00+00:00",
            execution_completed_at="2026-02-01T11:04:00+00:00",
            working_directory_reference="workspace_render",
            status=attempt_status,
            exit_code=0,
            output_artifact_refs=["render_manifest_retry"],
            failure_class="unknown",
            failure_summary="The fallback encoder produced an output artifact.",
            validation_required=True,
        ),
        BobaToolRecoveryAttemptV1(
            recovery_attempt_id="recovery_attempt_b",
            recovery_case_id="recovery_case_a",
            recovery_plan_id="recovery_plan_a",
            recovery_strategy_id="recovery_strategy_b",
            attempt_number=2,
            tool_id="fallback_encoder",
            capability_id="video_render",
            execution_started_at="2026-02-01T11:10:00+00:00",
            execution_completed_at="2026-02-01T11:12:00+00:00",
            working_directory_reference="workspace_render",
            status="failed",
            exit_code=1,
            failure_class="repeated_crash",
            failure_summary="The fallback encoder exited before writing output.",
            validation_required=True,
        ),
    ]
    return BobaToolRecoveryBrainSetV1(
        project_id=project_id,
        source_id="synthetic_source",
        repair_planner_source="repair_planner_report",
        recovery_cases=[case],
        recovery_attempts=attempts,
        output_validations=[
            BobaRecoveredOutputValidationV1(
                output_validation_id="recovery_validation_a",
                recovery_attempt_id="recovery_attempt_a",
                output_artifact_ref="render_manifest_retry",
                artifact_exists=True,
                artifact_non_empty=True,
                required_checks_passed=required_checks_passed,
                failed_required_checks=[]
                if required_checks_passed
                else ["caption_timing"],
                quality_review_required=True,
            )
        ],
        rollback_records=[
            BobaToolRecoveryRollbackV1(
                rollback_record_id="recovery_rollback_a",
                recovery_attempt_id="recovery_attempt_b",
                trigger="attempt_failed",
                scope="temporary_outputs",
                temporary_outputs_removed=True,
                original_outputs_preserved=True,
                source_media_preserved=True,
                checkpoint_unchanged=True,
                status="completed",
                human_review_required=True,
            )
        ],
        recovery_summary=BobaToolRecoverySummaryV1(),
        signal_usage=BobaToolRecoverySignalUsageV1(repair_planner_used=True),
    )


# ----------------------------------------------------------------------
# Seeding
# ----------------------------------------------------------------------
def seed_project(
    store: BobaMemoryStore,
    project_id: str = PROJECT_ID,
    *,
    with_repair_plans: bool = True,
    with_root_cause: bool = True,
    with_recovery: bool = True,
    with_incidents: bool = True,
    planner_set: BobaRepairPlannerSetV1 | None = None,
    root_cause_set: BobaRootCauseAnalyzerSetV1 | None = None,
    recovery_set: BobaToolRecoveryBrainSetV1 | None = None,
) -> dict[str, Any]:
    """Persist canonical repair-planning records for a synthetic review project."""
    if with_incidents:
        # Reuse the Error Doctor Panel fixtures so the incident identity the
        # linked-incident acknowledgement targets is a real canonical record.
        from tools._boba_error_doctor_review_fixtures import seed_project as seed_incidents

        seed_incidents(store, project_id)
    if with_root_cause:
        store.save_boba_root_cause_analyzer(
            root_cause_set or synthetic_root_cause_set(project_id)
        )
    if with_repair_plans:
        store.save_boba_repair_planner(
            planner_set or synthetic_repair_planner_set(project_id)
        )
    if with_recovery:
        store.save_boba_tool_recovery(recovery_set or synthetic_recovery_set(project_id))
    return {
        "project_id": project_id,
        "incident_id": INCIDENT_ID,
        "analysis_case_id": ANALYSIS_CASE_ID,
        "repair_case_id": REPAIR_CASE_ID,
        "repair_plan_ids": [
            PLAN_REVERSIBLE,
            PLAN_CODE_CHANGE,
            PLAN_CHECKPOINT,
            PLAN_DESTRUCTIVE,
        ],
    }

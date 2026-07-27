"""BOBA Repair Planner V1 contracts, planning, API, and safety tests."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_observer import build_synthetic_observer_report
from tools.validate_boba_repair_planner import (
    build_synthetic_planning_context,
    build_synthetic_root_cause_report,
    run_self_check,
    run_synthetic_project,
)
from tools.validate_boba_root_cause_analyzer import (
    build_synthetic_error_doctor_report,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaIntegration,
    BobaMemoryStore,
    BobaQualityPreservationPlanV1,
    BobaRepairApprovalGateV1,
    BobaRepairCheckpointPlanV1,
    BobaRepairExecutionHandoffV1,
    BobaRepairPlannerSetV1,
    BobaRepairPlannerSignalUsageV1,
    BobaRepairPlannerSummaryV1,
    BobaRepairPlannerV1,
    BobaRepairPlanningCaseV1,
    BobaRepairRejectedStrategyV1,
    BobaRepairRiskAssessmentV1,
    BobaRepairRollbackPlanV1,
    BobaRepairStepV1,
    BobaRepairStrategyRiskV1,
    BobaRepairStrategyV1,
    BobaRepairValidationCheckV1,
    BobaRepairValidationPlanV1,
    rank_repair_strategies,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_repair_planner_test"


@lru_cache(maxsize=4)
def _root(project_id: str = PROJECT_ID):
    return build_synthetic_root_cause_report(project_id)


@lru_cache(maxsize=4)
def _result(project_id: str = PROJECT_ID) -> BobaRepairPlannerSetV1:
    root = _root(project_id)
    return BobaRepairPlannerV1().plan(
        project_id,
        root,
        manual_context=build_synthetic_planning_context(root),
    )


def _case(source_case_id: str) -> BobaRepairPlanningCaseV1:
    root_case = next(
        item
        for item in _root().analysis_cases
        if item.source_diagnostic_case_id == source_case_id
    )
    return next(
        item
        for item in _result().repair_cases
        if item.source_analysis_case_id == root_case.analysis_case_id
    )


def _strategies(source_case_id: str) -> list[BobaRepairStrategyV1]:
    repair_case = _case(source_case_id)
    return [
        item
        for item in _result().repair_strategies
        if item.repair_case_id == repair_case.repair_case_id
    ]


def _recommended(source_case_id: str) -> BobaRepairStrategyV1:
    repair_case = _case(source_case_id)
    return next(
        item
        for item in _strategies(source_case_id)
        if item.repair_strategy_id == repair_case.recommended_strategy_id
    )


def _handoffs(source_case_id: str) -> list[BobaRepairExecutionHandoffV1]:
    repair_case = _case(source_case_id)
    return [
        item
        for item in _result().execution_handoffs
        if item.repair_case_id == repair_case.repair_case_id
    ]


def _validation(source_case_id: str) -> BobaRepairValidationPlanV1:
    repair_case = _case(source_case_id)
    return next(
        item
        for item in _result().validation_plans
        if item.repair_case_id == repair_case.repair_case_id
    )


def _quality(source_case_id: str) -> BobaQualityPreservationPlanV1:
    repair_case = _case(source_case_id)
    return next(
        item
        for item in _result().quality_preservation_plans
        if item.repair_case_id == repair_case.repair_case_id
    )


def _approval(source_case_id: str) -> BobaRepairApprovalGateV1:
    repair_case = _case(source_case_id)
    return next(
        item
        for item in _result().approval_gates
        if item.repair_case_id == repair_case.repair_case_id
    )


def _rejected_titles() -> set[str]:
    return {item.title.casefold() for item in _result().rejected_strategies}


def _roundtrip(value: Any, model: Any) -> None:
    assert model.model_validate(value.model_dump(mode="json")) == value


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _contains_key(item, key) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Repair Planner V1 Test",
        source_filename="synthetic-source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=120.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _integration(
    tmp_path: Path,
    project_id: str = PROJECT_ID,
) -> tuple[BobaIntegration, BobaMemoryStore]:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    asyncio.run(StorageProjectRepository(storage).save(_project(project_id)))
    return BobaIntegration(storage, store), store


def test_001_planner_set_serializes() -> None:
    _roundtrip(_result(), BobaRepairPlannerSetV1)


def test_002_repair_planning_case_serializes() -> None:
    _roundtrip(_result().repair_cases[0], BobaRepairPlanningCaseV1)


def test_003_repair_strategy_serializes() -> None:
    _roundtrip(_result().repair_strategies[0], BobaRepairStrategyV1)


def test_004_repair_step_serializes() -> None:
    value = _result().repair_strategies[0].proposed_steps[0]
    _roundtrip(value, BobaRepairStepV1)


def test_005_risk_assessment_serializes() -> None:
    _roundtrip(_result().risk_assessments[0], BobaRepairRiskAssessmentV1)


def test_006_strategy_risk_serializes() -> None:
    value = _result().risk_assessments[0].strategy_risks[0]
    _roundtrip(value, BobaRepairStrategyRiskV1)


def test_007_checkpoint_plan_serializes() -> None:
    _roundtrip(_result().checkpoint_plans[0], BobaRepairCheckpointPlanV1)


def test_008_rollback_plan_serializes() -> None:
    _roundtrip(_result().rollback_plans[0], BobaRepairRollbackPlanV1)


def test_009_validation_plan_serializes() -> None:
    _roundtrip(_result().validation_plans[0], BobaRepairValidationPlanV1)


def test_010_validation_check_serializes() -> None:
    value = _result().validation_plans[0].pre_repair_checks[0]
    _roundtrip(value, BobaRepairValidationCheckV1)


def test_011_quality_preservation_plan_serializes() -> None:
    _roundtrip(
        _result().quality_preservation_plans[0],
        BobaQualityPreservationPlanV1,
    )


def test_012_approval_gate_serializes() -> None:
    _roundtrip(_result().approval_gates[0], BobaRepairApprovalGateV1)


def test_013_execution_handoff_serializes() -> None:
    _roundtrip(_result().execution_handoffs[0], BobaRepairExecutionHandoffV1)


def test_014_rejected_strategy_serializes() -> None:
    _roundtrip(
        _result().rejected_strategies[0],
        BobaRepairRejectedStrategyV1,
    )


def test_015_summary_serializes() -> None:
    _roundtrip(_result().planner_summary, BobaRepairPlannerSummaryV1)


def test_016_signal_usage_serializes() -> None:
    _roundtrip(_result().signal_usage, BobaRepairPlannerSignalUsageV1)


def test_017_missing_root_cause_analyzer_degrades_gracefully() -> None:
    report = BobaRepairPlannerV1().plan(PROJECT_ID, None)
    assert report.repair_cases == []
    assert report.root_cause_analyzer_source == "unavailable"
    assert "root_cause_analyzer" in report.signal_usage.unavailable_signals


def test_018_malformed_analyzer_report_degrades_gracefully() -> None:
    report = BobaRepairPlannerV1().plan(PROJECT_ID, {"analysis_cases": "bad"})
    assert report.repair_cases == []
    assert any("malformed" in item.casefold() for item in report.warnings)


def test_019_empty_analyzer_produces_needs_more_evidence_plan() -> None:
    empty = _root().model_copy(
        update={
            "analysis_cases": [],
            "root_cause_candidates": [],
            "workflow_impacts": [],
        }
    )
    report = BobaRepairPlannerV1().plan(PROJECT_ID, empty)
    assert report.repair_cases[0].planning_status == "needs_more_evidence"
    assert report.repair_cases[0].repair_needed is False


def test_020_intentional_rights_block_has_no_software_repair() -> None:
    assert _case("case_rights_blocked").repair_needed is False
    assert {
        item.strategy_type for item in _strategies("case_rights_blocked")
    } <= {"seek_permission", "stop_processing"}


def test_021_permission_required_creates_seek_permission_strategy() -> None:
    assert any(
        item.strategy_type == "seek_permission"
        for item in _strategies("case_rights_unknown")
    )


def test_022_missing_human_approval_becomes_manual_action() -> None:
    assert _case("case_approval").planning_status == "human_decision_required"
    assert any(
        item.strategy_type == "human_manual_action"
        for item in _strategies("case_approval")
    )


def test_023_healthy_case_produces_no_action_strategy() -> None:
    assert _recommended("case_healthy").strategy_type == "no_action"


def test_024_missing_optional_artifact_is_not_over_repaired() -> None:
    assert _case("case_optional").repair_needed is False
    assert _recommended("case_optional").strategy_type == "no_action"


def test_025_missing_required_downstream_recommends_regeneration() -> None:
    assert (
        _recommended("case_missing_downstream_healthy").strategy_type
        == "regenerate_artifact"
    )


def test_026_missing_downstream_with_missing_upstream_addresses_upstream() -> None:
    assert _recommended("case_missing_upstream").strategy_type == (
        "collect_more_evidence"
    )


def test_027_corrupt_generated_artifact_recommends_recovery() -> None:
    assert {
        item.strategy_type for item in _strategies("case_corrupt")
    } & {"restore_checkpoint", "regenerate_artifact"}


def test_028_stale_downstream_recommends_scoped_regeneration() -> None:
    strategy = next(
        item
        for item in _strategies("case_stale")
        if item.strategy_type == "regenerate_artifact"
    )
    assert strategy.target_artifact
    assert "only" in strategy.description.casefold()


def test_029_source_media_remains_untouched() -> None:
    assert all(
        item.source_media_must_remain_untouched
        for item in _result().checkpoint_plans
    )


def test_030_valid_checkpoint_can_be_recommended() -> None:
    assert _recommended("case_checkpoint_valid").strategy_type == (
        "restore_checkpoint"
    )


def test_031_corrupt_checkpoint_is_rejected() -> None:
    repair_case = _case("case_checkpoint")
    assert any(
        item.repair_case_id == repair_case.repair_case_id
        and "corrupt checkpoint" in item.title.casefold()
        for item in _result().rejected_strategies
    )


def test_032_missing_checkpoint_lowers_strategy_confidence() -> None:
    assert _recommended("case_checkpoint_missing").estimated_confidence < (
        _recommended("case_checkpoint_valid").estimated_confidence
    )


def test_033_tool_unavailable_creates_tool_recovery_handoff() -> None:
    assert any(
        item.target_module == "tool_recovery_brain"
        for item in _handoffs("case_tool_missing")
    )


def test_034_tool_crash_creates_bounded_retry_strategy() -> None:
    retries = [
        item
        for item in _strategies("case_tool_crash")
        if item.strategy_type in {"retry_same_tool", "retry_with_safe_settings"}
    ]
    assert retries
    assert all(item.maximum_attempts == 2 for item in retries)


def test_035_timeout_strategy_has_maximum_attempts() -> None:
    retry = next(
        item
        for item in _strategies("case_timeout")
        if item.strategy_type == "retry_with_safe_settings"
    )
    assert retry.maximum_attempts == 2
    assert retry.maximum_recovery_duration_seconds == 900


def test_036_repeated_identical_retry_is_not_recommended() -> None:
    assert _recommended("case_timeout").strategy_type != (
        "retry_with_safe_settings"
    )


def test_037_resource_exhaustion_creates_lower_resource_strategy() -> None:
    assert any(
        item.strategy_type == "reduce_resource_usage"
        for item in _strategies("case_resource")
    )


def test_038_resource_fallback_preserves_output_requirements() -> None:
    strategy = next(
        item
        for item in _strategies("case_resource")
        if item.strategy_type == "reduce_resource_usage"
    )
    assert "No silent quality reduction" in strategy.expected_quality_effect
    assert _quality("case_resource").non_negotiable_requirements


def test_039_configuration_repair_requires_backup() -> None:
    strategy = next(
        item
        for item in _strategies("case_configuration")
        if item.strategy_type == "repair_configuration"
    )
    assert strategy.requires_backup is True


def test_040_configuration_repair_requires_approval() -> None:
    strategy = next(
        item
        for item in _strategies("case_configuration")
        if item.strategy_type == "repair_configuration"
    )
    assert strategy.human_approval_required is True
    assert _approval("case_configuration").final_human_approval_required is True


def test_041_environment_dependency_change_requires_approval() -> None:
    strategy = next(
        item
        for item in _strategies("case_environment")
        if item.strategy_type == "repair_environment"
    )
    assert strategy.requires_package_installation is True
    assert strategy.human_approval_required is True


def test_042_package_installation_is_never_executed() -> None:
    assert _result().signal_usage.package_installation_used is False


def test_043_service_restart_is_never_executed() -> None:
    assert _result().signal_usage.service_restart_used is False


def test_044_failed_validation_requires_validation_rerun() -> None:
    assert any(
        item.strategy_type == "rerun_validation"
        for item in _strategies("case_validation_failed")
    )
    assert _validation("case_validation_failed").post_repair_checks


def test_045_missing_validation_becomes_validator_handoff() -> None:
    assert any(
        item.target_module == "validator_runner"
        for item in _handoffs("case_validation_missing")
    )


def test_046_missing_validation_is_not_treated_as_repaired() -> None:
    repair_case = _case("case_validation_missing")
    assert repair_case.repair_needed is False
    assert repair_case.planning_status == "needs_more_evidence"


def test_047_strong_code_evidence_can_create_code_surgeon_handoff() -> None:
    assert any(
        item.target_module == "code_surgeon"
        for item in _handoffs("case_code_strong")
    )


def test_048_weak_code_evidence_prefers_more_verification() -> None:
    assert _case("case_code_weak").planning_status == "needs_more_evidence"
    assert _recommended("case_code_weak").strategy_type == (
        "collect_more_evidence"
    )


def test_049_code_patch_is_never_generated() -> None:
    code_strategy = next(
        item
        for item in _strategies("case_code_strong")
        if item.strategy_type == "propose_code_patch"
    )
    assert all(
        item.step_type not in {"apply_patch"}
        for item in code_strategy.proposed_steps
    )
    assert "diff --git" not in code_strategy.model_dump_json()


def test_050_code_is_never_modified() -> None:
    assert _result().signal_usage.code_modification_used is False


def test_051_main_branch_is_never_targeted_for_direct_patching() -> None:
    handoff = next(
        item
        for item in _handoffs("case_code_strong")
        if item.target_module == "code_surgeon"
    )
    assert any("separate branch" in item.casefold() for item in handoff.constraints)
    assert any("main" in item.casefold() for item in handoff.prohibited_actions)


def test_052_multiple_strategies_are_generated_when_reasonable() -> None:
    assert len(_strategies("case_resource")) >= 2


def test_053_safest_reversible_strategy_ranks_highest() -> None:
    strategies = _strategies("case_checkpoint_valid")
    assert strategies[0].recommended is True
    assert strategies[0].rank == 1
    assert strategies[0].strategy_type == "restore_checkpoint"


def test_054_irreversible_strategy_ranks_lower() -> None:
    source = _result().repair_strategies[0]
    safe = source.model_copy(
        update={
            "repair_strategy_id": "strategy_safe",
            "strategy_score": 0.5,
            "estimated_risk": "medium",
            "reversibility": "fully_reversible",
        }
    )
    irreversible = source.model_copy(
        update={
            "repair_strategy_id": "strategy_irreversible",
            "strategy_score": 0.5,
            "estimated_risk": "medium",
            "reversibility": "irreversible",
        }
    )
    assert rank_repair_strategies([irreversible, safe])[0].repair_strategy_id == (
        "strategy_safe"
    )


def test_055_source_data_modification_is_rejected() -> None:
    assert "modify or delete source media" in _rejected_titles()


def test_056_strategy_without_rollback_is_rejected_or_blocked() -> None:
    assert "execute without checkpoint or rollback" in _rejected_titles()


def test_057_silent_quality_degradation_is_rejected() -> None:
    assert "silently lower output quality" in _rejected_titles()


def test_058_fallback_completion_alone_does_not_mean_acceptance() -> None:
    assert any(
        "completion" in item.casefold() and "acceptance" in item.casefold()
        for item in _quality("case_resource").fallback_acceptance_rules
    )


def test_059_technical_validation_is_required() -> None:
    assert _validation("case_resource").required_validators
    assert all(
        item.blocks_acceptance_on_failure
        for item in _validation("case_resource").post_repair_checks
    )


def test_060_creative_quality_validation_can_be_required() -> None:
    assert _quality("case_resource").creative_quality_checks


def test_061_av_sync_validation_is_included_for_rendering_repairs() -> None:
    assert any(
        item.category == "audio_video_sync"
        for item in _validation("case_resource").post_repair_checks
    )


def test_062_caption_validation_is_included_when_relevant() -> None:
    assert any(
        item.category == "captions"
        for item in _validation("case_resource").post_repair_checks
    )


def test_063_rights_checks_remain_required() -> None:
    assert _validation("case_resource").rights_checks


def test_064_safety_checks_remain_required() -> None:
    assert _validation("case_resource").safety_checks


def test_065_checkpoint_plan_preserves_required_state() -> None:
    plan = next(
        item
        for item in _result().checkpoint_plans
        if item.repair_case_id == _case("case_resource").repair_case_id
    )
    assert plan.checkpoint_required is True
    assert plan.state_to_preserve


def test_066_rollback_plan_has_trigger_conditions() -> None:
    plan = next(
        item
        for item in _result().rollback_plans
        if item.repair_case_id == _case("case_resource").repair_case_id
    )
    assert plan.rollback_trigger_conditions


def test_067_rollback_validation_is_defined() -> None:
    plan = next(
        item
        for item in _result().rollback_plans
        if item.repair_case_id == _case("case_resource").repair_case_id
    )
    assert plan.rollback_validation


def test_068_validation_plan_has_acceptance_criteria() -> None:
    assert _validation("case_resource").acceptance_criteria


def test_069_validation_plan_has_rejection_criteria() -> None:
    assert _validation("case_resource").rejection_criteria


def test_070_quality_plan_has_non_negotiable_requirements() -> None:
    assert _quality("case_resource").non_negotiable_requirements


def test_071_quality_plan_has_unacceptable_degradations() -> None:
    assert _quality("case_resource").unacceptable_degradations


def test_072_approval_gate_remains_planning_only() -> None:
    assert _approval("case_resource").approval_status in {
        "planning_only",
        "awaiting_human_review",
    }
    assert all(
        not any(
            verb in item.casefold()
            for verb in ("execute", "modify", "install", "restart", "resume")
        )
        for item in _approval("case_resource").actions_allowed_without_approval
    )


def test_073_final_human_approval_is_required() -> None:
    assert all(
        item.final_human_approval_required for item in _result().approval_gates
    )


def test_074_apply_automatically_defaults_false() -> None:
    assert all(
        item.apply_automatically is False
        for item in _result().execution_handoffs
    )


def test_075_tool_recovery_handoff_includes_required_capability() -> None:
    handoff = next(
        item
        for item in _handoffs("case_tool_missing")
        if item.target_module == "tool_recovery_brain"
    )
    assert handoff.required_capability


def test_076_tool_recovery_handoff_includes_quality_properties() -> None:
    handoff = next(
        item
        for item in _handoffs("case_tool_missing")
        if item.target_module == "tool_recovery_brain"
    )
    assert handoff.required_quality_properties


def test_077_tool_recovery_handoff_includes_prohibited_actions() -> None:
    handoff = next(
        item
        for item in _handoffs("case_tool_missing")
        if item.target_module == "tool_recovery_brain"
    )
    assert handoff.prohibited_actions


def test_078_code_surgeon_handoff_includes_branch_requirement() -> None:
    handoff = next(
        item
        for item in _handoffs("case_code_strong")
        if item.target_module == "code_surgeon"
    )
    assert any("branch" in item.casefold() for item in handoff.constraints)


def test_079_validator_handoff_includes_acceptance_criteria() -> None:
    handoff = next(
        item
        for item in _handoffs("case_resource")
        if item.target_module == "validator_runner"
    )
    assert any(
        "acceptance" in item.casefold() or "pass" in item.casefold()
        for item in handoff.required_quality_properties + handoff.constraints
    )


def test_080_checkpoint_recovery_handoff_has_checkpoint_requirements() -> None:
    handoff = next(
        item
        for item in _handoffs("case_checkpoint_valid")
        if item.target_module == "checkpoint_recovery_manager"
    )
    assert handoff.checkpoint_plan_id
    assert "checkpoint" in handoff.required_capability.casefold()


def test_081_output_quality_reviewer_exists_for_affected_output() -> None:
    assert any(
        item.target_module == "output_quality_reviewer"
        for item in _handoffs("case_resource")
    )


def test_082_workflow_controller_does_not_authorize_resume() -> None:
    handoff = next(
        item
        for item in _handoffs("case_resource")
        if item.target_module == "workflow_controller"
    )
    assert handoff.apply_automatically is False
    assert any("resume" in item.casefold() for item in handoff.constraints)


def test_083_safety_gate_handoff_exists_for_executable_plans() -> None:
    assert any(
        item.target_module == "safety_gate"
        for item in _handoffs("case_resource")
    )


def test_084_unknown_rights_route_to_rights_gate() -> None:
    assert any(
        item.target_module == "rights_permission_gate"
        for item in _handoffs("case_rights_unknown")
    )


def test_085_competing_causes_create_conditional_strategies() -> None:
    assert _case("case_competing").planning_status in {
        "conflicting_causes",
        "conditional_plan",
    }
    assert len(_strategies("case_competing")) >= 2


def test_086_conflicting_evidence_lowers_plan_confidence() -> None:
    root_case = next(
        item
        for item in _root().analysis_cases
        if item.source_diagnostic_case_id == "case_competing"
    )
    assert _case("case_competing").confidence < root_case.root_cause_confidence


def test_087_more_evidence_strategy_is_generated_when_needed() -> None:
    assert any(
        item.strategy_type == "collect_more_evidence"
        for item in _strategies("case_code_weak")
    )


def test_088_destructive_strategy_is_rejected() -> None:
    assert any(
        "destructive" in item.safety_reason.casefold()
        for item in _result().rejected_strategies
    )


def test_089_unlimited_retry_strategy_is_rejected() -> None:
    assert "retry without a finite budget" in _rejected_titles()


def test_090_drm_platform_bypass_strategy_is_rejected() -> None:
    assert any(
        "drm" in item.casefold() or "access-control" in item.casefold()
        for strategy in _result().repair_strategies
        for item in strategy.prohibited_actions
    )


def test_091_secret_exposing_strategy_is_rejected() -> None:
    assert "expose credentials or secrets in a repair plan" in _rejected_titles()


def test_092_paid_external_service_requires_approval() -> None:
    assert any(
        item.requires_external_access and item.requires_paid_service
        for item in _strategies("case_resource")
    )
    assert _approval("case_resource").final_human_approval_required is True


def test_093_export_removes_private_paths(tmp_path: Path) -> None:
    root = _root().model_copy(deep=True)
    report = BobaRepairPlannerV1().plan(
        PROJECT_ID,
        root,
        manual_context={"bounded_path": r"D:\private\secret\artifact.json"},
    )
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_repair_planner(report)
    payload = store.export_boba_repair_planner(PROJECT_ID)
    encoded = json.dumps(payload)
    assert r"D:\private" not in encoded
    assert payload["privacy"]["private_paths_excluded"] is True


def test_094_export_removes_sensitive_evidence(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_repair_planner(_result())
    payload = store.export_boba_repair_planner(PROJECT_ID)
    assert payload["privacy"]["sensitive_evidence_excluded"] is True
    assert not _contains_key(payload, "previously_attempted_strategies")


def test_095_export_excludes_complete_source_reports(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_repair_planner(_result())
    payload = store.export_boba_repair_planner(PROJECT_ID)
    assert "root_cause_analyzer" not in payload
    assert payload["privacy"]["root_cause_analyzer_report_excluded"] is True


def test_096_reset_removes_only_repair_planner_artifact(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_root_cause_analyzer(_root())
    store.save_boba_error_doctor(build_synthetic_error_doctor_report(PROJECT_ID))
    store.save_observer_report(build_synthetic_observer_report(PROJECT_ID))
    store.save_boba_repair_planner(_result())
    assert store.reset_boba_repair_planner(PROJECT_ID) is True
    assert store.load_boba_repair_planner(PROJECT_ID) is None
    assert store.load_boba_root_cause_analyzer(PROJECT_ID) is not None
    assert store.load_boba_error_doctor(PROJECT_ID) is not None
    assert store.load_observer_report(PROJECT_ID) is not None


def test_097_root_cause_analyzer_artifact_remains_unchanged(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_root_cause_analyzer(_root())
    root_path = store.root_cause_analyzer_path(PROJECT_ID)
    before = (root_path.read_bytes(), root_path.stat().st_mtime_ns)
    store.save_boba_repair_planner(_result())
    after = (root_path.read_bytes(), root_path.stat().st_mtime_ns)
    assert before == after


def test_098_error_doctor_artifact_remains_unchanged(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_error_doctor(build_synthetic_error_doctor_report(PROJECT_ID))
    source_path = store.error_doctor_path(PROJECT_ID)
    before = (source_path.read_bytes(), source_path.stat().st_mtime_ns)
    store.save_boba_repair_planner(_result())
    after = (source_path.read_bytes(), source_path.stat().st_mtime_ns)
    assert before == after


def test_099_observer_artifacts_remain_unchanged(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_observer_report(build_synthetic_observer_report(PROJECT_ID))
    source_path = store.observer_path(PROJECT_ID)
    before = (source_path.read_bytes(), source_path.stat().st_mtime_ns)
    store.save_boba_repair_planner(_result())
    after = (source_path.read_bytes(), source_path.stat().st_mtime_ns)
    assert before == after


def test_100_persistence_produces_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_repair_planner(_result())
    path = store.repair_planner_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/repair_planner/index.json"
    )
    assert payload["schema_version"] == "boba_repair_planner_v1"
    path.write_text("{malformed prior report", encoding="utf-8")
    assert store.load_boba_repair_planner(PROJECT_ID) is None


def test_101_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_boba_root_cause_analyzer(_root())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        dry_run = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/repair-planner",
            json={"dry_run": True},
        )
        assert dry_run.status_code == 200, dry_run.text
        assert store.load_boba_repair_planner(PROJECT_ID) is None
        created = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/repair-planner",
            json={},
        )
        assert created.status_code == 200, created.text
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/repair-planner"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_repair_planner_v1"


def test_102_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_boba_repair_planner(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/repair-planner/export"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "boba_repair_planner_export_v1"
    assert payload["privacy"]["command_execution_used"] is False


def test_103_api_delete_resets_only_repair_planner(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_boba_root_cause_analyzer(_root())
    store.save_boba_error_doctor(build_synthetic_error_doctor_report(PROJECT_ID))
    store.save_observer_report(build_synthetic_observer_report(PROJECT_ID))
    store.save_boba_repair_planner(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/repair-planner"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["repair_planner_removed"] is True
    assert payload["root_cause_analyzer_removed"] is False
    assert payload["error_doctor_removed"] is False
    assert payload["observer_removed"] is False
    assert payload["repairs_applied"] is False
    assert store.load_boba_root_cause_analyzer(PROJECT_ID) is not None


def test_104_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.command_execution_used_false is True
    assert report.repair_execution_used_false is True


def test_105_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.repair_cases_exist is True
    assert report.root_cause_analyzer_unchanged is True


def test_106_external_api_used_remains_false() -> None:
    assert _result().signal_usage.external_api_used is False


def test_107_url_fetching_used_remains_false() -> None:
    assert _result().signal_usage.url_fetching_used is False


def test_108_scraping_used_remains_false() -> None:
    assert _result().signal_usage.scraping_used is False


def test_109_downloading_used_remains_false() -> None:
    assert _result().signal_usage.downloading_used is False


def test_110_command_execution_used_remains_false() -> None:
    assert _result().signal_usage.command_execution_used is False


def test_111_validator_execution_used_remains_false() -> None:
    assert _result().signal_usage.validator_execution_used is False


def test_112_code_modification_used_remains_false() -> None:
    assert _result().signal_usage.code_modification_used is False


def test_113_artifact_modification_used_remains_false() -> None:
    assert _result().signal_usage.artifact_modification_used is False


def test_114_repair_execution_used_remains_false() -> None:
    assert _result().signal_usage.repair_execution_used is False


def test_115_tool_fallback_execution_used_remains_false() -> None:
    assert _result().signal_usage.tool_fallback_execution_used is False


def test_116_workflow_resume_used_remains_false() -> None:
    assert _result().signal_usage.workflow_resume_used is False


def test_117_service_restart_used_remains_false() -> None:
    assert _result().signal_usage.service_restart_used is False


def test_118_package_installation_used_remains_false() -> None:
    assert _result().signal_usage.package_installation_used is False


def test_119_destructive_action_used_remains_false() -> None:
    assert _result().signal_usage.destructive_action_used is False


def test_120_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Repair Planner must not render.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.command_execution_used is False


def test_121_no_media_ingestion_is_triggered(monkeypatch: Any) -> None:
    def fail_binary_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Repair Planner must not ingest media.")

    monkeypatch.setattr(Path, "write_bytes", fail_binary_write)
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.downloading_used is False


def test_122_no_commands_are_executed(monkeypatch: Any) -> None:
    def fail_command(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Repair Planner must not execute commands.")

    monkeypatch.setattr(subprocess, "Popen", fail_command)
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.command_execution_used is False


def test_123_no_validators_are_executed_by_planner(monkeypatch: Any) -> None:
    def fail_validator(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Repair Planner must not execute validators.")

    monkeypatch.setattr(subprocess, "check_call", fail_validator)
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.validator_execution_used is False


def test_124_no_code_is_modified(monkeypatch: Any) -> None:
    def fail_text_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Repair Planner must not modify code.")

    monkeypatch.setattr(Path, "write_text", fail_text_write)
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.code_modification_used is False


def test_125_no_artifacts_are_repaired() -> None:
    root = _root().model_copy(deep=True)
    before = root.model_dump_json()
    BobaRepairPlannerV1().plan(PROJECT_ID, root)
    assert root.model_dump_json() == before


def test_126_no_fallback_tools_are_executed(monkeypatch: Any) -> None:
    def fail_tool_lookup(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Repair Planner must not activate fallback tools.")

    monkeypatch.setattr(shutil, "which", fail_tool_lookup)
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.tool_fallback_execution_used is False


def test_127_no_workflow_is_resumed() -> None:
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.workflow_resume_used is False


def test_128_no_service_is_restarted(monkeypatch: Any) -> None:
    def fail_restart(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Repair Planner must not restart services.")

    monkeypatch.setattr(subprocess, "check_output", fail_restart)
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.service_restart_used is False


def test_129_no_package_is_installed(monkeypatch: Any) -> None:
    def fail_install(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Repair Planner must not install packages.")

    monkeypatch.setattr(subprocess, "call", fail_install)
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.package_installation_used is False


def test_130_no_destructive_action_occurs(monkeypatch: Any) -> None:
    def fail_unlink(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Repair Planner must not delete files.")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    assert BobaRepairPlannerV1().plan(
        PROJECT_ID,
        _root(),
    ).signal_usage.destructive_action_used is False


def test_131_no_generated_reports_or_media_are_staged() -> None:
    ignore_text = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(
        encoding="utf-8"
    )
    assert "work/" in ignore_text
    assert "storage_data/" in ignore_text
    assert ".venv/" in ignore_text
    assert "node_modules/" in ignore_text
    assert "frontend/.next/" in ignore_text

"""BOBA Root Cause Analyzer V1 contracts, causality, API, and safety tests."""

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
from tools.validate_boba_root_cause_analyzer import (
    build_synthetic_error_doctor_report,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaCausalEdgeV1,
    BobaCausalGraphV1,
    BobaCausalNodeV1,
    BobaContributingFactorV1,
    BobaDiagnosticCaseV1,
    BobaDiagnosticEvidenceV1,
    BobaDiagnosticHypothesisV1,
    BobaDownstreamSymptomV1,
    BobaErrorDoctorSetV1,
    BobaErrorDoctorSignalUsageV1,
    BobaErrorDoctorSummaryV1,
    BobaEvidenceGapV1,
    BobaFailureTimelineEventV1,
    BobaFailureTimelineV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaRootCauseAnalysisCaseV1,
    BobaRootCauseAnalyzerSetV1,
    BobaRootCauseAnalyzerSummaryV1,
    BobaRootCauseAnalyzerV1,
    BobaRootCauseCandidateV1,
    BobaRootCauseEscalationHandoffV1,
    BobaRootCauseEvidenceV1,
    BobaRootCauseSignalUsageV1,
    BobaRootCauseVerificationCheckV1,
    BobaRootCauseVerificationPlanV1,
    BobaWorkflowImpactAnalysisV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_root_cause_test"


@lru_cache(maxsize=4)
def _source(project_id: str = PROJECT_ID) -> BobaErrorDoctorSetV1:
    return build_synthetic_error_doctor_report(project_id)


@lru_cache(maxsize=4)
def _result(project_id: str = PROJECT_ID) -> BobaRootCauseAnalyzerSetV1:
    return BobaRootCauseAnalyzerV1().analyze(
        project_id,
        _source(project_id),
        manual_context={
            "conflicting_timestamps": True,
            "healthy_modules": ["content_scout_v2", "creator_learning"],
        },
    )


def _analysis_case(
    source_case_id: str,
    report: BobaRootCauseAnalyzerSetV1 | None = None,
) -> BobaRootCauseAnalysisCaseV1:
    effective = report or _result()
    return next(
        item
        for item in effective.analysis_cases
        if item.source_diagnostic_case_id == source_case_id
    )


def _candidate(
    source_case_id: str,
    category: str,
    report: BobaRootCauseAnalyzerSetV1 | None = None,
) -> BobaRootCauseCandidateV1:
    effective = report or _result()
    analysis_case = _analysis_case(source_case_id, effective)
    return next(
        item
        for item in effective.root_cause_candidates
        if item.analysis_case_id == analysis_case.analysis_case_id
        and item.category == category
    )


def _timeline(
    source_case_id: str,
    report: BobaRootCauseAnalyzerSetV1 | None = None,
) -> BobaFailureTimelineV1:
    effective = report or _result()
    analysis_case = _analysis_case(source_case_id, effective)
    return next(
        item
        for item in effective.failure_timelines
        if item.timeline_id == analysis_case.failure_timeline_id
    )


def _graph(
    source_case_id: str,
    report: BobaRootCauseAnalyzerSetV1 | None = None,
) -> BobaCausalGraphV1:
    effective = report or _result()
    analysis_case = _analysis_case(source_case_id, effective)
    return next(
        item
        for item in effective.causal_graphs
        if item.causal_graph_id == analysis_case.causal_graph_id
    )


def _empty_error_doctor(project_id: str = PROJECT_ID) -> BobaErrorDoctorSetV1:
    return BobaErrorDoctorSetV1(
        project_id=project_id,
        source_id="empty_error_doctor",
        observer_source="saved_observer_v1",
        doctor_summary=BobaErrorDoctorSummaryV1(),
        signal_usage=BobaErrorDoctorSignalUsageV1(),
    )


def _custom_report(
    case: BobaDiagnosticCaseV1,
    project_id: str = PROJECT_ID,
) -> BobaErrorDoctorSetV1:
    return BobaErrorDoctorSetV1(
        project_id=project_id,
        source_id="custom_error_doctor",
        observer_source="saved_observer_v1",
        diagnostic_cases=[case],
        doctor_summary=BobaErrorDoctorSummaryV1(total_diagnostic_cases=1),
        signal_usage=BobaErrorDoctorSignalUsageV1(observer_used=True),
    )


def _custom_case(
    *,
    case_id: str,
    category: str,
    symptom: str,
    cause: str,
    status: str = "possible",
    affected_modules: list[str] | None = None,
    hypotheses: list[BobaDiagnosticHypothesisV1] | None = None,
) -> BobaDiagnosticCaseV1:
    return BobaDiagnosticCaseV1(
        diagnostic_case_id=case_id,
        title=symptom,
        primary_module="rendering",
        primary_artifact="render_output",
        workflow_stage="self_healing",
        error_category=category,  # type: ignore[arg-type]
        severity="high",
        urgency="soon",
        diagnosis_status=status,  # type: ignore[arg-type]
        symptom_summary=symptom,
        probable_cause_summary=cause,
        confirmed_facts=[symptom] if status == "observed_fact" else [],
        hypotheses=hypotheses or [],
        affected_modules=affected_modules or ["rendering"],
        affected_artifacts=["render_output"],
        related_finding_ids=[],
        evidence=[
            BobaDiagnosticEvidenceV1(
                evidence_id=f"evidence_{case_id}",
                source_type="artifact_observation",
                source_id=case_id,
                module_name="rendering",
                artifact_id="render_output",
                evidence_summary=symptom,
                confidence=0.45 if status == "possible" else 0.9,
            )
        ],
        missing_information=[],
        processing_impact="partial_block",
        safety_impact="none_known",
        recommended_investigation=["Inspect bounded evidence."],
        escalation_target="root_cause_analyzer",
        confidence=0.45 if status == "possible" else 0.9,
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Root Cause Analyzer V1 Test",
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


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def test_001_analyzer_set_serializes() -> None:
    payload = json.loads(_result().model_dump_json())
    assert payload["schema_version"] == "boba_root_cause_analyzer_v1"
    assert BobaRootCauseAnalyzerSetV1.model_validate(payload) == _result()


def test_002_analysis_case_serializes() -> None:
    value = _result().analysis_cases[0]
    assert BobaRootCauseAnalysisCaseV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_003_failure_timeline_serializes() -> None:
    value = _result().failure_timelines[0]
    assert BobaFailureTimelineV1.model_validate(value.model_dump(mode="json")) == value


def test_004_timeline_event_serializes() -> None:
    value = next(item for timeline in _result().failure_timelines for item in timeline.events)
    assert BobaFailureTimelineEventV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_005_causal_graph_serializes() -> None:
    value = _result().causal_graphs[0]
    assert BobaCausalGraphV1.model_validate(value.model_dump(mode="json")) == value


def test_006_causal_node_serializes() -> None:
    value = next(item for graph in _result().causal_graphs for item in graph.nodes)
    assert BobaCausalNodeV1.model_validate(value.model_dump(mode="json")) == value


def test_007_causal_edge_serializes() -> None:
    value = next(item for graph in _result().causal_graphs for item in graph.edges)
    assert BobaCausalEdgeV1.model_validate(value.model_dump(mode="json")) == value


def test_008_root_cause_candidate_serializes() -> None:
    value = _result().root_cause_candidates[0]
    assert BobaRootCauseCandidateV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_009_contributing_factor_serializes() -> None:
    value = _result().contributing_factors[0]
    assert BobaContributingFactorV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_010_downstream_symptom_serializes() -> None:
    value = _result().downstream_symptoms[0]
    assert BobaDownstreamSymptomV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_011_root_cause_evidence_serializes() -> None:
    value = _result().evidence[0]
    assert BobaRootCauseEvidenceV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_012_evidence_gap_serializes() -> None:
    value = _result().evidence_gaps[0]
    assert BobaEvidenceGapV1.model_validate(value.model_dump(mode="json")) == value


def test_013_verification_plan_serializes() -> None:
    value = _result().verification_plans[0]
    assert BobaRootCauseVerificationPlanV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_014_verification_check_serializes() -> None:
    value = _result().verification_plans[0].checks[0]
    assert BobaRootCauseVerificationCheckV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_015_workflow_impact_serializes() -> None:
    value = _result().workflow_impacts[0]
    assert BobaWorkflowImpactAnalysisV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_016_escalation_handoff_serializes() -> None:
    value = _result().escalation_handoffs[0]
    assert BobaRootCauseEscalationHandoffV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_017_summary_serializes() -> None:
    value = _result().analyzer_summary
    assert BobaRootCauseAnalyzerSummaryV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_018_signal_usage_serializes() -> None:
    value = _result().signal_usage
    assert BobaRootCauseSignalUsageV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_019_missing_error_doctor_degrades_gracefully() -> None:
    report = BobaRootCauseAnalyzerV1().analyze(PROJECT_ID, None)
    assert report.error_doctor_source == "missing_error_doctor_v1"
    assert report.analysis_cases[0].analysis_status == "insufficient_evidence"
    assert report.root_cause_candidates == []


def test_020_malformed_error_doctor_degrades_gracefully() -> None:
    report = BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        {"project_id": PROJECT_ID, "diagnostic_cases": [{"invalid": True}]},
    )
    assert report.error_doctor_source == "malformed_error_doctor_v1"
    assert report.analysis_cases[0].analysis_status == "insufficient_evidence"


def test_021_empty_error_doctor_produces_insufficient_evidence_analysis() -> None:
    report = BobaRootCauseAnalyzerV1().analyze(PROJECT_ID, _empty_error_doctor())
    assert report.error_doctor_source == "saved_error_doctor_v1_empty"
    assert report.analysis_cases[0].analysis_status == "insufficient_evidence"


def test_022_earliest_known_failure_is_not_automatically_root_cause() -> None:
    case = _analysis_case("case_missing_upstream")
    assert case.earliest_known_failure != case.most_likely_root_cause
    assert any("not automatically" in item for item in case.warnings)


def test_023_missing_required_upstream_ranks_above_downstream_symptoms() -> None:
    candidate = _candidate("case_missing_upstream", "missing_artifact")
    assert candidate.likelihood_score >= 0.7
    assert len(candidate.explains_symptom_ids) >= 3


def test_024_missing_downstream_with_healthy_upstream_is_incomplete_stage_candidate() -> None:
    case = _custom_case(
        case_id="healthy_upstream_missing_output",
        category="missing_artifact",
        symptom="Downstream output is missing while the saved upstream is healthy.",
        cause="The downstream stage may be incomplete.",
        status="probable",
    )
    report = BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _custom_report(case),
        manual_context={"healthy_upstream": True},
    )
    assert report.root_cause_candidates[0].category == "missing_artifact"
    assert report.analysis_cases[0].analysis_status == "probable_root_cause"


def test_025_multiple_downstream_blocks_form_cascade() -> None:
    case = _analysis_case("case_missing_upstream")
    symptoms = [
        item
        for item in _result().downstream_symptoms
        if item.analysis_case_id == case.analysis_case_id
    ]
    assert len(symptoms) >= 3
    assert max(item.cascade_depth for item in symptoms) >= 2


def test_026_missing_optional_artifact_is_not_blocker() -> None:
    case = _analysis_case("case_optional")
    candidate = _candidate("case_optional", "missing_artifact")
    assert case.processing_impact == "none"
    assert case.analysis_status == "no_defect_detected"
    assert candidate.likelihood_score < 0.5


def test_027_corrupt_required_artifact_becomes_high_priority_candidate() -> None:
    candidate = _candidate("case_corrupt", "corrupt_artifact")
    assert candidate.likelihood_score >= 0.7
    assert _analysis_case("case_corrupt").processing_impact == "full_block"


def test_028_unreadable_artifact_remains_distinct_from_missing_artifact() -> None:
    case = _custom_case(
        case_id="unreadable",
        category="unreadable_artifact",
        symptom="The artifact exists but is unreadable.",
        cause="Unreadable artifact evidence is distinct from absence.",
        status="observed_fact",
    )
    report = BobaRootCauseAnalyzerV1().analyze(PROJECT_ID, _custom_report(case))
    assert report.root_cause_candidates[0].category == "corrupt_artifact"
    assert any(
        event.event_type == "artifact_unreadable"
        for event in report.failure_timelines[0].events
    )
    assert not any(
        event.event_type == "artifact_missing"
        for event in report.failure_timelines[0].events
    )


def test_029_stale_downstream_artifact_is_linked_conservatively() -> None:
    graph = _graph("case_stale")
    assert any(
        edge.relationship in {"probably_caused", "may_have_caused"}
        for edge in graph.edges
    )
    assert not any(edge.relationship == "caused" for edge in graph.edges)


def test_030_conflicting_timestamps_lower_timeline_confidence() -> None:
    timeline = _timeline("case_missing_upstream")
    assert timeline.conflicting_timestamps is True
    assert timeline.ordering_confidence < 0.78


def test_031_missing_timestamps_are_not_invented() -> None:
    timeline = _timeline("case_optional")
    assert timeline.missing_time_information is True
    assert all(event.observed_at == "" for event in timeline.events)


def test_032_direct_evidence_can_support_caused_edge() -> None:
    report = BobaRootCauseAnalyzerV1().analyze(PROJECT_ID, _source())
    assert any(
        edge.relationship == "caused" and edge.confirmed
        for edge in _graph("case_missing_upstream", report).edges
    )


def test_033_weak_evidence_uses_may_have_caused() -> None:
    case = _custom_case(
        case_id="weak_environment",
        category="environment",
        symptom="Rendering stopped with weak environment evidence.",
        cause="An environment difference may be related.",
        affected_modules=["rendering", "optimization"],
    )
    report = BobaRootCauseAnalyzerV1().analyze(PROJECT_ID, _custom_report(case))
    assert any(
        edge.relationship == "may_have_caused"
        for edge in report.causal_graphs[0].edges
    )


def test_034_correlation_is_not_converted_to_causation() -> None:
    report = BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
        manual_context={"conflicting_evidence": True},
    )
    graph = _graph("case_missing_upstream", report)
    assert any(edge.relationship == "correlated_with" for edge in graph.edges)
    assert not any(edge.relationship == "caused" for edge in graph.edges)


def test_035_causal_graph_size_is_bounded() -> None:
    assert all(
        len(graph.nodes) <= 96 and len(graph.edges) <= 192
        for graph in _result().causal_graphs
    )


def test_036_causal_graph_cycles_are_reported() -> None:
    report = BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
        manual_context={"force_cycle_for_validation": True},
    )
    graph = _graph("case_missing_upstream", report)
    assert graph.cycles_detected is True
    assert any("cycle" in item.casefold() for item in graph.warnings)


def test_037_root_cause_candidate_contains_supporting_evidence() -> None:
    assert _candidate(
        "case_missing_upstream",
        "missing_artifact",
    ).supporting_evidence_ids


def test_038_root_cause_candidate_contains_conflicting_evidence() -> None:
    case = _analysis_case("case_competing")
    assert any(
        candidate.conflicting_evidence_ids
        for candidate in _result().root_cause_candidates
        if candidate.analysis_case_id == case.analysis_case_id
    )


def test_039_candidate_lists_unexplained_symptoms() -> None:
    candidate = _candidate("case_code_weak", "code_defect")
    assert candidate.evidence_quality == "weak"
    assert candidate.unexplained_symptom_ids == candidate.explains_symptom_ids


def test_040_missing_validation_remains_validation_gap() -> None:
    candidate = _candidate("case_validation_missing", "validation_gap")
    assert candidate.evidence_quality == "insufficient"
    assert candidate.likelihood_score <= 0.38


def test_041_failed_validation_becomes_confirmed_failure_evidence() -> None:
    candidate = _candidate("case_validation_failed", "validation_failure")
    timeline = _timeline("case_validation_failed")
    assert candidate.likelihood_score >= 0.7
    assert any(
        event.event_type == "validation_failed" and event.confirmed
        for event in timeline.events
    )


def test_042_unknown_validation_format_remains_unknown() -> None:
    assert _candidate("case_validation_unknown", "unknown")
    assert _analysis_case("case_validation_unknown").analysis_status in {
        "insufficient_evidence",
        "unknown",
    }


def test_043_configuration_issue_stays_hypothetical_without_proof() -> None:
    candidate = _candidate("case_configuration", "configuration")
    assert candidate.evidence_quality == "weak"
    assert _analysis_case("case_configuration").analysis_status == "insufficient_evidence"


def test_044_environment_issue_stays_hypothetical_without_proof() -> None:
    candidate = _candidate("case_environment", "environment")
    assert candidate.evidence_quality == "weak"
    assert _analysis_case("case_environment").analysis_status == "insufficient_evidence"


def test_045_missing_executable_creates_tool_unavailable_candidate() -> None:
    assert _candidate("case_tool_missing", "tool_unavailable")


def test_046_temporary_tool_crash_creates_tool_failure_candidate() -> None:
    assert _candidate("case_tool_crash", "tool_failure")


def test_047_resource_exhaustion_creates_recovery_handoff() -> None:
    case = _analysis_case("case_resource")
    assert any(
        handoff.target_module == "tool_recovery_brain"
        and handoff.analysis_case_id == case.analysis_case_id
        for handoff in _result().escalation_handoffs
    )


def test_048_timeout_creates_bounded_tool_failure_candidate() -> None:
    candidate = _candidate("case_timeout", "timeout")
    assert candidate.verification_required is True
    assert candidate.repairability == "requires_tool_fallback"


def test_049_checkpoint_failure_creates_checkpoint_candidate() -> None:
    assert _candidate("case_checkpoint", "checkpoint_failure")


def test_050_weak_input_data_creates_data_quality_candidate() -> None:
    assert _candidate("case_weak_input", "data_quality")


def test_051_code_defect_is_not_assumed_from_generic_failure() -> None:
    assert not any(
        candidate.category == "code_defect"
        for candidate in _result().root_cause_candidates
        if candidate.analysis_case_id == _analysis_case("case_tool_crash").analysis_case_id
    )


def test_052_code_surgeon_handoff_requires_stronger_evidence() -> None:
    case = _analysis_case("case_code_weak")
    assert not any(
        handoff.target_module == "code_surgeon"
        and handoff.analysis_case_id == case.analysis_case_id
        for handoff in _result().escalation_handoffs
    )


def test_053_unknown_rights_becomes_intentional_safety_block() -> None:
    assert _analysis_case("case_rights_unknown").analysis_status == (
        "intentional_safety_block"
    )


def test_054_blocked_rights_is_not_classified_as_defect() -> None:
    case = _analysis_case("case_rights_blocked")
    assert case.analysis_status == "intentional_safety_block"
    assert not any(
        candidate.category == "code_defect"
        for candidate in _result().root_cause_candidates
        if candidate.analysis_case_id == case.analysis_case_id
    )


def test_055_missing_approval_becomes_human_decision_block() -> None:
    case = _analysis_case("case_approval")
    assert case.analysis_status == "intentional_safety_block"
    assert case.human_review_required is True


def test_056_competing_candidates_are_ranked() -> None:
    case = _analysis_case("case_competing")
    candidates = [
        item
        for item in _result().root_cause_candidates
        if item.analysis_case_id == case.analysis_case_id
    ]
    assert len(candidates) >= 2
    assert candidates == sorted(
        candidates,
        key=lambda item: (-item.likelihood_score, -item.confidence),
    )


def test_057_contradictory_evidence_lowers_confidence() -> None:
    candidate = _candidate("case_competing", "configuration")
    assert candidate.conflicting_evidence_ids
    assert candidate.confidence < 0.58


def test_058_simpler_supported_cause_ranks_above_speculative_cause() -> None:
    code_hypothesis = BobaDiagnosticHypothesisV1(
        hypothesis_id="hyp_code",
        hypothesis="A code defect may exist.",
        category="direct_cause",
        confidence=0.2,
        verification_needed=True,
        suggested_check="Exclude simpler causes.",
    )
    case = _custom_case(
        case_id="simple_before_code",
        category="missing_artifact",
        symptom="A required artifact is confirmed missing.",
        cause="The missing artifact explains the blocked stage.",
        status="observed_fact",
        hypotheses=[code_hypothesis],
        affected_modules=["rendering", "optimization"],
    )
    report = BobaRootCauseAnalyzerV1().analyze(PROJECT_ID, _custom_report(case))
    assert report.root_cause_candidates[0].category == "missing_artifact"
    assert report.root_cause_candidates[-1].category == "code_defect"


def test_059_contributing_factor_is_not_automatically_sufficient() -> None:
    assert all(
        not item.sufficient_for_failure for item in _result().contributing_factors
    )


def test_060_contributing_factor_is_not_automatically_necessary() -> None:
    assert all(
        not item.necessary_for_failure for item in _result().contributing_factors
    )


def test_061_confirmation_checks_are_produced() -> None:
    assert all(item.confirmation_checks for item in _result().root_cause_candidates)


def test_062_rejection_checks_are_produced() -> None:
    assert all(item.rejection_checks for item in _result().root_cause_candidates)


def test_063_evidence_gaps_explain_why_information_is_needed() -> None:
    assert all(item.why_needed for item in _result().evidence_gaps)


def test_064_verification_plans_are_ordered() -> None:
    assert all(
        [check.order for check in plan.checks]
        == list(range(1, len(plan.checks) + 1))
        for plan in _result().verification_plans
    )


def test_065_verification_plans_start_with_safe_read_only_checks() -> None:
    assert all(
        plan.checks and plan.checks[0].safe and plan.checks[0].read_only
        for plan in _result().verification_plans
    )


def test_066_verification_plans_never_execute() -> None:
    signal = _result().signal_usage
    assert signal.command_execution_used is False
    assert signal.validator_execution_used is False


def test_067_tool_recovery_handoff_includes_required_capability() -> None:
    handoff = next(
        item
        for item in _result().escalation_handoffs
        if item.target_module == "tool_recovery_brain"
    )
    assert any("Required capability:" in item for item in handoff.required_inputs)
    assert any("Quality requirements:" in item for item in handoff.required_inputs)


def test_068_tool_recovery_handoff_does_not_execute_fallback() -> None:
    assert _result().signal_usage.tool_fallback_execution_used is False
    assert all(
        not item.apply_automatically for item in _result().escalation_handoffs
    )


def test_069_repair_planner_handoff_defaults_apply_automatically_false() -> None:
    handoff = next(
        item
        for item in _result().escalation_handoffs
        if item.target_module == "repair_planner"
    )
    assert handoff.apply_automatically is False


def test_070_all_handoffs_require_human_approval() -> None:
    assert all(
        item.human_approval_required for item in _result().escalation_handoffs
    )


def test_071_workflow_impact_lists_blocked_stages() -> None:
    case = _analysis_case("case_missing_upstream")
    impact = next(
        item
        for item in _result().workflow_impacts
        if item.analysis_case_id == case.analysis_case_id
    )
    assert "video_intelligence" in impact.blocked_stages


def test_072_workflow_impact_lists_unsafe_next_actions() -> None:
    assert all(item.unsafe_next_actions for item in _result().workflow_impacts)


def test_073_analyzer_never_authorizes_workflow_resume() -> None:
    assert all(
        "Automatic workflow resume" in impact.unsafe_next_actions
        for impact in _result().workflow_impacts
    )
    assert all(
        "does not authorize workflow resume" in " ".join(impact.warnings)
        for impact in _result().workflow_impacts
    )


def test_074_export_removes_private_paths(tmp_path: Path) -> None:
    report = BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
        manual_context={"bounded_path": r"D:\private\secret\artifact.json"},
    )
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_root_cause_analyzer(report)
    payload = store.export_boba_root_cause_analyzer(PROJECT_ID)
    encoded = json.dumps(payload)
    assert r"D:\private" not in encoded
    assert payload["privacy"]["private_paths_excluded"] is True


def test_075_export_removes_complete_source_reports(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_root_cause_analyzer(_result())
    payload = store.export_boba_root_cause_analyzer(PROJECT_ID)
    assert "error_doctor" not in payload
    assert "observer" not in payload
    assert payload["privacy"]["error_doctor_report_excluded"] is True
    assert payload["privacy"]["observer_report_excluded"] is True


def test_076_export_excludes_complete_logs(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_root_cause_analyzer(_result())
    payload = store.export_boba_root_cause_analyzer(PROJECT_ID)
    assert "raw_logs" not in payload
    assert payload["privacy"]["raw_logs_excluded"] is True
    assert not _contains_key(payload["root_cause_analyzer"], "observed_value")


def test_077_reset_removes_only_root_cause_analyzer_artifact(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_error_doctor(_source())
    store.save_observer_report(build_synthetic_observer_report(PROJECT_ID))
    store.save_boba_root_cause_analyzer(_result())
    assert store.reset_boba_root_cause_analyzer(PROJECT_ID) is True
    assert store.load_boba_root_cause_analyzer(PROJECT_ID) is None
    assert store.load_boba_error_doctor(PROJECT_ID) is not None
    assert store.load_observer_report(PROJECT_ID) is not None


def test_078_error_doctor_artifact_remains_unchanged() -> None:
    source = _source().model_copy(deep=True)
    before = source.model_dump_json()
    BobaRootCauseAnalyzerV1().analyze(PROJECT_ID, source)
    assert source.model_dump_json() == before


def test_079_observer_artifacts_remain_unchanged(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    observer = build_synthetic_observer_report(PROJECT_ID)
    store.save_observer_report(observer)
    observer_path = store.observer_path(PROJECT_ID)
    before = (observer_path.read_bytes(), observer_path.stat().st_mtime_ns)
    store.save_boba_error_doctor(_source())
    store.save_boba_root_cause_analyzer(_result())
    after = (observer_path.read_bytes(), observer_path.stat().st_mtime_ns)
    assert before == after


def test_080_persistence_produces_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_root_cause_analyzer(_result())
    path = store.root_cause_analyzer_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/root_cause_analyzer/index.json"
    )
    assert payload["schema_version"] == "boba_root_cause_analyzer_v1"
    path.write_text("{malformed prior report", encoding="utf-8")
    assert store.load_boba_root_cause_analyzer(PROJECT_ID) is None


def test_081_missing_optional_inputs_degrade_gracefully() -> None:
    report = BobaRootCauseAnalyzerV1().analyze(PROJECT_ID, _source())
    assert report.signal_usage.bounded_manual_context_used is False
    assert report.analysis_cases


def test_082_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_boba_error_doctor(_source())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        dry_run = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/root-cause-analyzer",
            json={"dry_run": True},
        )
        assert dry_run.status_code == 200, dry_run.text
        assert store.load_boba_root_cause_analyzer(PROJECT_ID) is None
        created = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/root-cause-analyzer",
            json={},
        )
        assert created.status_code == 200, created.text
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/root-cause-analyzer"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_root_cause_analyzer_v1"


def test_083_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_boba_root_cause_analyzer(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/root-cause-analyzer/export"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "boba_root_cause_analyzer_export_v1"
    assert payload["privacy"]["command_execution_used"] is False
    assert not _contains_key(payload["root_cause_analyzer"], "observed_value")


def test_084_api_delete_resets_only_root_cause_analyzer(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_observer_report(build_synthetic_observer_report(PROJECT_ID))
    store.save_boba_error_doctor(_source())
    store.save_boba_root_cause_analyzer(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/root-cause-analyzer"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["root_cause_analyzer_removed"] is True
    assert payload["error_doctor_removed"] is False
    assert payload["observer_removed"] is False
    assert payload["repairs_applied"] is False
    assert store.load_boba_error_doctor(PROJECT_ID) is not None
    assert store.load_observer_report(PROJECT_ID) is not None


def test_085_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.command_execution_used_false is True
    assert report.validator_execution_used_false is True


def test_086_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.causal_graphs_exist is True
    assert report.error_doctor_unchanged is True


def test_087_external_api_used_remains_false() -> None:
    assert _result().signal_usage.external_api_used is False


def test_088_url_fetching_used_remains_false() -> None:
    assert _result().signal_usage.url_fetching_used is False


def test_089_scraping_used_remains_false() -> None:
    assert _result().signal_usage.scraping_used is False


def test_090_downloading_used_remains_false() -> None:
    assert _result().signal_usage.downloading_used is False


def test_091_command_execution_used_remains_false() -> None:
    assert _result().signal_usage.command_execution_used is False


def test_092_validator_execution_used_remains_false() -> None:
    assert _result().signal_usage.validator_execution_used is False


def test_093_code_modification_used_remains_false() -> None:
    assert _result().signal_usage.code_modification_used is False


def test_094_artifact_modification_used_remains_false() -> None:
    assert _result().signal_usage.artifact_modification_used is False


def test_095_repair_execution_used_remains_false() -> None:
    assert _result().signal_usage.repair_execution_used is False


def test_096_tool_fallback_execution_used_remains_false() -> None:
    assert _result().signal_usage.tool_fallback_execution_used is False


def test_097_destructive_action_used_remains_false() -> None:
    assert _result().signal_usage.destructive_action_used is False


def test_098_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Root Cause Analyzer must not render.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
    ).signal_usage.command_execution_used is False


def test_099_no_media_ingestion_is_triggered(monkeypatch: Any) -> None:
    def fail_binary_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Root Cause Analyzer must not ingest media.")

    monkeypatch.setattr(Path, "write_bytes", fail_binary_write)
    assert BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
    ).signal_usage.downloading_used is False


def test_100_no_commands_are_executed(monkeypatch: Any) -> None:
    def fail_command(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Root Cause Analyzer must not execute commands.")

    monkeypatch.setattr(subprocess, "Popen", fail_command)
    assert BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
    ).signal_usage.command_execution_used is False


def test_101_no_validators_are_executed_by_analyzer(monkeypatch: Any) -> None:
    def fail_validator(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Root Cause Analyzer must not execute validators.")

    monkeypatch.setattr(subprocess, "check_call", fail_validator)
    assert BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
    ).signal_usage.validator_execution_used is False


def test_102_no_code_is_modified(monkeypatch: Any) -> None:
    def fail_text_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Root Cause Analyzer must not modify code.")

    monkeypatch.setattr(Path, "write_text", fail_text_write)
    assert BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
    ).signal_usage.code_modification_used is False


def test_103_no_source_artifacts_are_modified() -> None:
    source = _source().model_copy(deep=True)
    before = source.model_dump_json()
    BobaRootCauseAnalyzerV1().analyze(PROJECT_ID, source)
    assert source.model_dump_json() == before


def test_104_no_repairs_are_executed(monkeypatch: Any) -> None:
    def fail_copy(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Root Cause Analyzer must not repair files.")

    monkeypatch.setattr(shutil, "copy2", fail_copy)
    assert BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
    ).signal_usage.repair_execution_used is False


def test_105_no_fallback_tools_are_executed(monkeypatch: Any) -> None:
    def fail_tool_lookup(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Root Cause Analyzer must not activate fallback tools.")

    monkeypatch.setattr(shutil, "which", fail_tool_lookup)
    assert BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
    ).signal_usage.tool_fallback_execution_used is False


def test_106_no_destructive_action_occurs(monkeypatch: Any) -> None:
    def fail_unlink(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Root Cause Analyzer must not delete files.")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    assert BobaRootCauseAnalyzerV1().analyze(
        PROJECT_ID,
        _source(),
    ).signal_usage.destructive_action_used is False


def test_107_no_generated_reports_or_media_are_staged() -> None:
    ignore_text = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(
        encoding="utf-8"
    )
    assert "work/" in ignore_text
    assert "storage_data/" in ignore_text
    assert ".venv/" in ignore_text
    assert "node_modules/" in ignore_text
    assert "frontend/.next/" in ignore_text

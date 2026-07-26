"""BOBA Error Doctor V1 contracts, diagnosis, API, and safety tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import urllib.request
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_error_doctor import (
    run_self_check,
    run_synthetic_project,
)
from tools.validate_boba_observer import build_synthetic_observer_report

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaArtifactObservationV1,
    BobaCascadingImpactV1,
    BobaClassifiedFindingV1,
    BobaDiagnosticCaseV1,
    BobaDiagnosticEvidenceV1,
    BobaDiagnosticHypothesisV1,
    BobaErrorDoctorEscalationHandoffV1,
    BobaErrorDoctorSetV1,
    BobaErrorDoctorSignalUsageV1,
    BobaErrorDoctorSummaryV1,
    BobaErrorDoctorV1,
    BobaIntegration,
    BobaInvestigationRecommendationV1,
    BobaMemoryStore,
    BobaModuleHealthObservationV1,
    BobaObserverSetV1,
    BobaObserverSignalUsageV1,
    BobaObserverSummaryV1,
    BobaProjectMemoryV1,
    BobaSafetyObservationV1,
    BobaValidationObservationV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_error_doctor_test"


def _observer(project_id: str = PROJECT_ID) -> BobaObserverSetV1:
    observer = build_synthetic_observer_report(project_id)
    observer.validation_observations.append(
        BobaValidationObservationV1(
            validator_name="synthetic_required_validator",
            report_path="synthetic/failed.json",
            report_exists=True,
            latest_status="failed",
            report_created_at="2026-01-15T11:00:00+00:00",
            freshness_status="fresh",
            issue_level="blocker",
            warnings=["Synthetic failed validation."],
        )
    )
    observer.safety_observations.append(
        BobaSafetyObservationV1(
            safety_id="synthetic_rights_unknown",
            safety_area="rights_permission",
            status="needs_human_review",
            reason="Synthetic rights status is unknown.",
            related_artifacts=["rights_permission_gate"],
            required_human_checks=["Confirm rights manually."],
            unsafe_next_actions=["Do not process automatically."],
            warnings=["Unknown rights remain blocked."],
        )
    )
    return observer


def _empty_observer(project_id: str = PROJECT_ID) -> BobaObserverSetV1:
    return BobaObserverSetV1(
        project_id=project_id,
        source_id="synthetic_empty_observer",
        observer_summary=BobaObserverSummaryV1(),
        signal_usage=BobaObserverSignalUsageV1(),
    )


@lru_cache(maxsize=4)
def _result(project_id: str = PROJECT_ID) -> BobaErrorDoctorSetV1:
    return BobaErrorDoctorV1().analyze(
        project_id,
        _observer(project_id),
        error_summaries=[
            {
                "summary": "Synthetic FFmpeg executable is unavailable.",
                "category": "external_tool",
                "module_name": "rendering",
            }
        ],
    )


def _case(
    report: BobaErrorDoctorSetV1,
    category: str,
) -> BobaDiagnosticCaseV1:
    return next(
        item for item in report.diagnostic_cases if item.error_category == category
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Error Doctor V1 Test",
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
        return key in value or any(
            _contains_key(item, key) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def test_01_error_doctor_set_serializes() -> None:
    payload = json.loads(_result().model_dump_json())
    assert payload["schema_version"] == "boba_error_doctor_v1"
    assert BobaErrorDoctorSetV1.model_validate(payload) == _result()


def test_02_diagnostic_case_serializes() -> None:
    value = _result().diagnostic_cases[0]
    assert BobaDiagnosticCaseV1.model_validate(value.model_dump(mode="json")) == value


def test_03_classified_finding_serializes() -> None:
    value = _result().classified_findings[0]
    assert BobaClassifiedFindingV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_04_diagnostic_evidence_serializes() -> None:
    value = _result().diagnostic_cases[0].evidence[0]
    assert BobaDiagnosticEvidenceV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_05_diagnostic_hypothesis_serializes() -> None:
    value = next(
        hypothesis
        for case in _result().diagnostic_cases
        for hypothesis in case.hypotheses
    )
    assert BobaDiagnosticHypothesisV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_06_cascading_impact_serializes() -> None:
    value = _result().cascading_impacts[0]
    assert BobaCascadingImpactV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_07_investigation_recommendation_serializes() -> None:
    value = _result().investigation_recommendations[0]
    assert BobaInvestigationRecommendationV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_08_escalation_handoff_serializes() -> None:
    value = _result().escalation_handoffs[0]
    assert BobaErrorDoctorEscalationHandoffV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_09_summary_serializes() -> None:
    value = _result().doctor_summary
    assert BobaErrorDoctorSummaryV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_10_signal_usage_serializes() -> None:
    value = _result().signal_usage
    assert BobaErrorDoctorSignalUsageV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_11_missing_observer_degrades_gracefully() -> None:
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, None)
    assert report.observer_source == "missing_observer_v1"
    assert report.diagnostic_cases[0].diagnosis_status == "insufficient_evidence"
    assert report.classified_findings == []
    assert report.signal_usage.observer_used is False


def test_12_empty_observer_produces_insufficient_evidence_result() -> None:
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _empty_observer())
    assert report.observer_source == "saved_observer_v1_empty"
    assert report.diagnostic_cases[0].diagnosis_status == "insufficient_evidence"
    assert report.classified_findings == []


def test_13_missing_required_upstream_is_probable_cause() -> None:
    assert any(
        case.error_category == "missing_artifact"
        and case.diagnosis_status == "probable"
        for case in _result().diagnostic_cases
    )


def test_14_missing_downstream_with_healthy_upstream_is_incomplete_step() -> None:
    observer = _empty_observer()
    observer.module_health_observations = [
        BobaModuleHealthObservationV1(
            module_name="caption_motion",
            module_category="creative",
            expected_artifacts=["caption_motion"],
            required_dependencies=["hook_retention"],
            health_status="missing",
            missing_outputs=["caption_motion"],
            confidence=0.9,
        )
    ]
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, observer)
    case = _case(report, "missing_artifact")
    assert case.diagnosis_status == "probable"
    assert case.processing_impact == "degraded"


def test_15_multiple_downstream_blocks_are_grouped_into_cascade() -> None:
    assert any(
        len(impact.impacted_modules) > 1
        for impact in _result().cascading_impacts
    )


def test_16_missing_optional_artifact_is_not_blocker() -> None:
    optional = [
        finding
        for finding in _result().classified_findings
        if any("optional dependency" in warning.casefold() for warning in finding.warnings)
    ]
    assert optional
    assert all(item.severity not in {"critical", "blocker"} for item in optional)


def test_17_corrupt_required_artifact_receives_blocking_severity() -> None:
    case = _case(_result(), "corrupt_artifact")
    assert case.severity in {"high", "critical", "blocker"}


def test_18_unreadable_artifact_is_not_treated_as_missing() -> None:
    observer = _empty_observer()
    observer.artifact_observations = [
        BobaArtifactObservationV1(
            artifact_id="clip_briefs",
            module_name="clip_briefs",
            artifact_type="json",
            expected_path="clip_briefs/index.json",
            exists=True,
            readable=False,
            freshness_status="unknown",
            dependency_status="satisfied",
            issue_level="blocker",
            warnings=["Artifact cannot be read."],
        )
    ]
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, observer)
    assert _case(report, "unreadable_artifact")
    assert not any(
        case.error_category == "missing_artifact"
        for case in report.diagnostic_cases
    )


def test_19_stale_downstream_artifact_becomes_stale_output_diagnosis() -> None:
    case = _case(_result(), "stale_artifact")
    assert case.diagnosis_status == "probable"
    assert case.severity in {"low", "medium"}


def test_20_downstream_newer_than_upstream_is_not_falsely_stale() -> None:
    observer = _empty_observer()
    observer.artifact_observations = [
        BobaArtifactObservationV1(
            artifact_id="caption_motion",
            module_name="caption_motion",
            artifact_type="json",
            expected_path="caption_motion/index.json",
            exists=True,
            readable=True,
            freshness_status="fresh",
            dependency_status="satisfied",
            issue_level="ok",
        )
    ]
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, observer)
    assert not any(
        case.error_category == "stale_artifact"
        for case in report.diagnostic_cases
    )


def test_21_missing_validation_is_gap_not_confirmed_failure() -> None:
    case = _case(_result(), "validation_missing")
    assert case.diagnosis_status == "insufficient_evidence"
    assert "not proof" in case.probable_cause_summary.casefold()


def test_22_failed_validation_is_classified_as_validation_failure() -> None:
    case = _case(_result(), "validation_failure")
    assert case.diagnosis_status == "observed_fact"
    assert case.severity == "high"


def test_23_unknown_validation_format_remains_unknown() -> None:
    case = _case(_result(), "unknown")
    assert case.diagnosis_status == "insufficient_evidence"
    assert case.severity == "unknown"


def test_24_unknown_rights_creates_safety_blocker() -> None:
    assert any(
        finding.classified_category == "rights_safety"
        and finding.original_issue_level == "needs_human_review"
        and finding.severity == "blocker"
        for finding in _result().classified_findings
    )


def test_25_blocked_rights_is_intentional_safety_blocking() -> None:
    assert any(
        finding.classified_category == "rights_safety"
        and finding.original_issue_level == "blocked"
        and "intentional safety" in finding.explanation.casefold()
        for finding in _result().classified_findings
    )


def test_26_ready_for_human_review_still_requires_human_review() -> None:
    observer = _empty_observer()
    observer.safety_observations = [
        BobaSafetyObservationV1(
            safety_id="safe_review",
            safety_area="rights_permission",
            status="safe_to_review",
            reason="Ready for human review only.",
            required_human_checks=["Human review remains required."],
        )
    ]
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, observer)
    assert any(
        "human" in note.casefold()
        for note in report.doctor_summary.human_review_notes
    )


def test_27_duplicate_findings_are_grouped() -> None:
    counts = Counter(
        finding.duplicate_group_id for finding in _result().classified_findings
    )
    assert any(count > 1 for count in counts.values())


def test_28_unrelated_findings_are_not_incorrectly_grouped() -> None:
    report = BobaErrorDoctorV1().analyze(
        PROJECT_ID,
        _observer(),
        error_summaries=[
            {
                "summary": "Synthetic configuration is absent.",
                "category": "configuration",
                "module_name": "api",
            },
            {
                "summary": "Synthetic local tool timed out.",
                "category": "timeout",
                "module_name": "rendering",
            },
        ],
    )
    selected = [
        finding
        for finding in report.classified_findings
        if finding.classified_category in {"configuration", "timeout"}
    ]
    assert len({finding.duplicate_group_id for finding in selected}) == 2


def test_29_confirmed_facts_are_separated_from_hypotheses() -> None:
    for case in _result().diagnostic_cases:
        hypotheses = {item.hypothesis for item in case.hypotheses}
        assert set(case.confirmed_facts).isdisjoint(hypotheses)


def test_30_hypotheses_include_confidence_and_verification() -> None:
    hypotheses = [
        hypothesis
        for case in _result().diagnostic_cases
        for hypothesis in case.hypotheses
    ]
    assert hypotheses
    assert all(
        0.0 <= hypothesis.confidence < 1.0
        and hypothesis.verification_needed
        and hypothesis.suggested_check
        for hypothesis in hypotheses
    )


def test_31_conflicting_evidence_lowers_confidence() -> None:
    normal = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    conflicting = BobaErrorDoctorV1().analyze(
        PROJECT_ID,
        _observer(),
        manual_context={"conflicting_evidence": True},
    )
    assert max(case.confidence for case in conflicting.diagnostic_cases) < max(
        case.confidence for case in normal.diagnostic_cases
    )
    assert all(
        case.diagnosis_status == "conflicting_evidence"
        for case in conflicting.diagnostic_cases
    )


def test_32_missing_information_is_reported() -> None:
    assert any(case.missing_information for case in _result().diagnostic_cases)
    assert _result().doctor_summary.unresolved_information


def test_33_investigation_steps_remain_advisory() -> None:
    assert all(
        item.requires_human_review and not item.requires_code_change
        for item in _result().investigation_recommendations
    )


def test_34_recommendations_never_execute_commands(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not execute commands.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    assert report.signal_usage.command_execution_used is False


def test_35_recommendations_never_edit_code(monkeypatch: Any) -> None:
    observer = _observer()

    def fail_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not edit code.")

    monkeypatch.setattr(Path, "write_text", fail_write)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, observer)
    assert report.signal_usage.code_modification_used is False


def test_36_recommendations_never_delete_files(monkeypatch: Any) -> None:
    def fail_unlink(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not delete files.")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    assert report.signal_usage.destructive_action_used is False


def test_37_recommendations_never_bypass_rights_gates() -> None:
    actions = " ".join(
        item.action for item in _result().investigation_recommendations
    ).casefold()
    assert "bypass" not in actions
    assert "do not continue" in actions


def test_38_repair_planner_handoff_defaults_to_not_apply() -> None:
    handoffs = [
        item
        for item in _result().escalation_handoffs
        if item.target_module == "repair_planner"
    ]
    assert handoffs
    assert all(item.apply_automatically is False for item in handoffs)


def test_39_root_cause_analyzer_handoff_requires_human_approval() -> None:
    handoffs = [
        item
        for item in _result().escalation_handoffs
        if item.target_module == "root_cause_analyzer"
    ]
    assert handoffs
    assert all(item.human_approval_required is True for item in handoffs)


def test_40_tool_recovery_handoff_is_used_for_tool_failures() -> None:
    assert any(
        item.target_module == "tool_recovery_brain"
        for item in _result().escalation_handoffs
    )


def test_41_validator_runner_handoff_is_used_for_missing_validation() -> None:
    assert any(
        item.target_module == "validator_runner"
        for item in _result().escalation_handoffs
    )


def test_42_rights_gate_handoff_is_used_for_rights_uncertainty() -> None:
    assert any(
        item.target_module == "rights_permission_gate"
        for item in _result().escalation_handoffs
    )


def test_43_cascading_impact_lists_affected_modules() -> None:
    assert any(
        len(item.impacted_modules) > 1 for item in _result().cascading_impacts
    )


def test_44_summary_counts_are_consistent() -> None:
    report = _result()
    summary = report.doctor_summary
    assert sum(
        (
            summary.informational_count,
            summary.low_count,
            summary.medium_count,
            summary.high_count,
            summary.critical_count,
            summary.blocker_count,
            summary.unknown_count,
        )
    ) == len(report.diagnostic_cases)
    assert summary.total_observer_findings == len(report.classified_findings)


def test_45_export_removes_private_paths(tmp_path: Path) -> None:
    report = BobaErrorDoctorV1().analyze(
        PROJECT_ID,
        _observer(),
        error_summaries=[r"Failure near D:\private\secret\artifact.json"],
    )
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_error_doctor(report)
    payload = store.export_boba_error_doctor(PROJECT_ID)
    encoded = json.dumps(payload)
    assert r"D:\private" not in encoded
    assert payload["privacy"]["private_paths_excluded"] is True
    assert not _contains_key(payload["error_doctor"], "observed_value")


def test_46_export_excludes_observer_dumps_and_full_logs(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_error_doctor(_result())
    payload = store.export_boba_error_doctor(PROJECT_ID)
    assert "observer" not in payload
    assert "raw_logs" not in payload
    assert payload["privacy"]["observer_report_excluded"] is True
    assert payload["privacy"]["raw_logs_excluded"] is True


def test_47_reset_removes_only_error_doctor_artifact(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba", memory_root=tmp_path / "memory")
    store.save_observer_report(_observer())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives Error Doctor reset.",
        )
    )
    store.save_boba_error_doctor(_result())
    assert store.reset_boba_error_doctor(PROJECT_ID) is True
    assert store.load_boba_error_doctor(PROJECT_ID) is None
    assert store.load_observer_report(PROJECT_ID) is not None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_48_observer_artifact_remains_unchanged_after_generation() -> None:
    observer = _observer()
    before = observer.model_dump_json()
    BobaErrorDoctorV1().analyze(PROJECT_ID, observer)
    assert observer.model_dump_json() == before


def test_49_missing_optional_inputs_degrade_gracefully() -> None:
    optional = [
        finding
        for finding in _result().classified_findings
        if any("optional dependency" in warning.casefold() for warning in finding.warnings)
    ]
    assert optional
    assert all(finding.severity in {"informational", "low"} for finding in optional)


def test_50_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_error_doctor(_result())
    path = store.error_doctor_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/error_doctor/index.json"
    )
    assert payload["schema_version"] == "boba_error_doctor_v1"
    path.write_text("{malformed prior report", encoding="utf-8")
    assert store.load_boba_error_doctor(PROJECT_ID) is None


def test_51_api_get_returns_saved_report(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_observer_report(_observer())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        dry_run = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor",
            json={"dry_run": True},
        )
        assert dry_run.status_code == 200, dry_run.text
        assert store.load_boba_error_doctor(PROJECT_ID) is None
        created = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor",
            json={},
        )
        assert created.status_code == 200, created.text
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_error_doctor_v1"


def test_52_api_export_returns_safe_report(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_boba_error_doctor(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor/export"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "boba_error_doctor_export_v1"
    assert payload["privacy"]["command_execution_used"] is False
    assert not _contains_key(payload["error_doctor"], "observed_value")


def test_53_api_delete_resets_only_error_doctor(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_observer_report(_observer())
    store.save_boba_error_doctor(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["error_doctor_removed"] is True
    assert payload["observer_removed"] is False
    assert payload["repairs_applied"] is False
    assert store.load_observer_report(PROJECT_ID) is not None


def test_54_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.command_execution_used_false is True
    assert report.validator_execution_used_false is True


def test_55_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.cascading_effects_detected is True
    assert report.observer_unchanged is True


def test_56_external_api_used_remains_false() -> None:
    assert _result().signal_usage.external_api_used is False


def test_57_url_fetching_used_remains_false() -> None:
    assert _result().signal_usage.url_fetching_used is False


def test_58_scraping_used_remains_false() -> None:
    assert _result().signal_usage.scraping_used is False


def test_59_downloading_used_remains_false() -> None:
    assert _result().signal_usage.downloading_used is False


def test_60_command_execution_used_remains_false() -> None:
    assert _result().signal_usage.command_execution_used is False


def test_61_validator_execution_used_remains_false() -> None:
    assert _result().signal_usage.validator_execution_used is False


def test_62_code_modification_used_remains_false() -> None:
    assert _result().signal_usage.code_modification_used is False


def test_63_artifact_modification_used_remains_false() -> None:
    assert _result().signal_usage.artifact_modification_used is False


def test_64_destructive_action_used_remains_false() -> None:
    assert _result().signal_usage.destructive_action_used is False


def test_65_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not render.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    assert report.signal_usage.command_execution_used is False


def test_66_no_downloading_is_triggered(monkeypatch: Any) -> None:
    def fail_binary_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not download.")

    monkeypatch.setattr(Path, "write_bytes", fail_binary_write)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    assert report.signal_usage.downloading_used is False


def test_67_no_url_fetching_is_triggered(monkeypatch: Any) -> None:
    def fail_url_fetch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not fetch URLs.")

    monkeypatch.setattr(urllib.request, "urlopen", fail_url_fetch)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    assert report.signal_usage.url_fetching_used is False


def test_68_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not use the network.")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    assert report.signal_usage.external_api_used is False


def test_69_no_commands_are_executed(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not execute commands.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    assert report.signal_usage.command_execution_used is False


def test_70_no_validators_are_executed_by_engine(monkeypatch: Any) -> None:
    def fail_validator(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not execute validators.")

    monkeypatch.setattr(
        "tools.validate_boba_observer.run_self_check",
        fail_validator,
    )
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    assert report.signal_usage.validator_execution_used is False


def test_71_no_source_files_are_edited(monkeypatch: Any) -> None:
    observer = _observer()

    def fail_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not edit source files.")

    monkeypatch.setattr(Path, "write_text", fail_write)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, observer)
    assert report.signal_usage.code_modification_used is False


def test_72_no_source_artifacts_are_modified(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_observer_report(_observer())
    observer_path = store.observer_path(PROJECT_ID)
    before = (observer_path.read_bytes(), observer_path.stat().st_mtime_ns)
    report = BobaErrorDoctorV1().analyze(
        PROJECT_ID,
        store.load_observer_report(PROJECT_ID),
    )
    store.save_boba_error_doctor(report)
    after = (observer_path.read_bytes(), observer_path.stat().st_mtime_ns)
    assert after == before


def test_73_no_destructive_actions_occur(monkeypatch: Any) -> None:
    def fail_unlink(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Error Doctor must not delete files.")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    report = BobaErrorDoctorV1().analyze(PROJECT_ID, _observer())
    assert report.signal_usage.destructive_action_used is False


def test_74_no_generated_reports_or_media_are_staged() -> None:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    staged = {
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
        if line.strip()
    }
    forbidden_prefixes = {
        ".venv/",
        "media/",
        "storage_data/",
        "work/",
        "frontend/.next/",
        "frontend/node_modules/",
        "node_modules/",
    }
    forbidden_suffixes = {".mp4", ".mov", ".wav", ".webm", ".env"}
    assert not any(
        any(path.startswith(prefix) for prefix in forbidden_prefixes)
        or any(path.casefold().endswith(suffix) for suffix in forbidden_suffixes)
        for path in staged
    )

"""BOBA Performance Feedback Brain V1 contracts, behavior, and safety tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tools.validate_boba_performance_feedback import (
    build_synthetic_performance_artifacts,
    build_synthetic_performance_events,
    build_synthetic_performance_feedback,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaExperimentOutcomeReviewV1,
    BobaIntegration,
    BobaManualPerformanceMetricsV1,
    BobaMemoryStore,
    BobaPerformanceAuditSummaryV1,
    BobaPerformanceFactorV1,
    BobaPerformanceFeedbackBrainV1,
    BobaPerformanceFeedbackEventV1,
    BobaPerformanceFeedbackSetV1,
    BobaPerformanceFeedbackSignalUsageV1,
    BobaPerformanceLearningHandoffV1,
    BobaPerformancePatternSummaryV1,
    BobaPerformanceSnapshotV1,
    BobaProjectMemoryV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_performance_feedback_test"


@lru_cache(maxsize=4)
def _result(project_id: str = PROJECT_ID) -> BobaPerformanceFeedbackSetV1:
    return build_synthetic_performance_feedback(project_id)


@lru_cache(maxsize=4)
def _events(project_id: str = PROJECT_ID) -> tuple[BobaPerformanceFeedbackEventV1, ...]:
    experimentation = build_synthetic_performance_artifacts(project_id)[
        "experimentation"
    ]
    return tuple(
        build_synthetic_performance_events(
            project_id,
            experimentation=experimentation,
        )
    )


def _factor_confidence(
    result: BobaPerformanceFeedbackSetV1,
    text: str,
) -> float:
    factors = [
        *result.pattern_summary.strongest_positive_patterns,
        *result.pattern_summary.strongest_negative_patterns,
    ]
    return max(
        (
            factor.confidence
            for factor in factors
            if text in factor.summary.casefold()
        ),
        default=0.0,
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Performance Feedback Test",
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


def _patch_artifact_loaders(
    monkeypatch: Any,
    store: BobaMemoryStore,
    project_id: str = PROJECT_ID,
) -> None:
    artifacts = build_synthetic_performance_artifacts(project_id)
    store.save_experimentation_plan(artifacts["experimentation"])
    loaders = {
        "load_creator_learning": "creator_learning",
        "load_approval_rejection_learning": "approval_rejection_learning",
        "load_clip_briefs": "clip_briefs",
        "load_hook_retention": "hook_retention",
        "load_caption_motion": "caption_motion",
        "load_music_mood": "music_mood",
        "load_clip_ranking": "clip_ranking",
        "load_editorial_decisions": "editorial_decision",
        "load_project_memory": "memory",
    }
    for method, artifact_name in loaders.items():
        monkeypatch.setattr(
            store,
            method,
            lambda _project_id, key=artifact_name: artifacts[key],
        )


def test_01_performance_feedback_set_contract_serializes() -> None:
    payload = json.loads(_result().model_dump_json())
    assert payload["schema_version"] == "boba_performance_feedback_v1"
    assert BobaPerformanceFeedbackSetV1.model_validate(payload) == _result()


def test_02_feedback_event_contract_serializes() -> None:
    event = _events()[0]
    assert BobaPerformanceFeedbackEventV1.model_validate(
        event.model_dump(mode="json")
    ) == event
    assert event.user_entered is True


def test_03_snapshot_contract_serializes() -> None:
    snapshot = _result().performance_snapshots[0]
    assert BobaPerformanceSnapshotV1.model_validate(
        snapshot.model_dump(mode="json")
    ) == snapshot


def test_04_manual_metrics_contract_serializes_with_optional_fields() -> None:
    metrics = BobaManualPerformanceMetricsV1()
    payload = metrics.model_dump(mode="json")
    assert all(
        value is None
        for key, value in payload.items()
        if key != "custom_metrics"
    )
    assert payload["custom_metrics"] == {}


def test_05_experiment_outcome_review_contract_serializes() -> None:
    outcome = _result().experiment_outcomes[0]
    assert BobaExperimentOutcomeReviewV1.model_validate(
        outcome.model_dump(mode="json")
    ) == outcome


def test_06_performance_factor_contract_serializes() -> None:
    factor = _result().pattern_summary.strongest_positive_patterns[0]
    assert BobaPerformanceFactorV1.model_validate(
        factor.model_dump(mode="json")
    ) == factor


def test_07_pattern_summary_contract_serializes() -> None:
    summary = _result().pattern_summary
    assert BobaPerformancePatternSummaryV1.model_validate(
        summary.model_dump(mode="json")
    ) == summary


def test_08_learning_handoff_contract_serializes() -> None:
    handoff = _result().learning_handoff
    assert BobaPerformanceLearningHandoffV1.model_validate(
        handoff.model_dump(mode="json")
    ) == handoff
    assert handoff.apply_automatically is False


def test_09_audit_summary_contract_serializes() -> None:
    audit = _result().audit_summary
    assert BobaPerformanceAuditSummaryV1.model_validate(
        audit.model_dump(mode="json")
    ) == audit


def test_10_signal_usage_contract_serializes() -> None:
    usage = _result().signal_usage
    assert BobaPerformanceFeedbackSignalUsageV1.model_validate(
        usage.model_dump(mode="json")
    ) == usage


def test_11_manual_clip_result_creates_snapshot() -> None:
    event = _events()[0]
    result = BobaPerformanceFeedbackBrainV1().analyze(
        PROJECT_ID,
        [event],
    )
    assert len(result.performance_snapshots) == 1
    assert result.performance_snapshots[0].source_event_id == event.event_id


def test_12_manual_experiment_result_creates_outcome_review() -> None:
    artifacts = build_synthetic_performance_artifacts(PROJECT_ID)
    event = next(
        item for item in _events() if item.event_type == "manual_experiment_result"
    )
    result = BobaPerformanceFeedbackBrainV1().analyze(
        PROJECT_ID,
        [event],
        experimentation=artifacts["experimentation"],
    )
    assert len(result.experiment_outcomes) == 1
    assert result.experiment_outcomes[0].experiment_id == event.experiment_id


def test_13_negative_metrics_are_rejected() -> None:
    with pytest.raises(ValidationError):
        BobaManualPerformanceMetricsV1(views=-1)


def test_14_missing_metrics_reduce_confidence() -> None:
    brain = BobaPerformanceFeedbackBrainV1()
    sparse = brain.create_event(
        PROJECT_ID,
        event_type="manual_rating",
        target_type="project",
        target_id=PROJECT_ID,
        manual_rating=4.0,
    )
    sparse_snapshot = brain.snapshot_from_event(sparse)
    full_snapshot = brain.snapshot_from_event(_events()[0])
    assert sparse_snapshot is not None
    assert full_snapshot is not None
    assert sparse_snapshot.data_confidence < full_snapshot.data_confidence
    assert any("No numeric metrics" in item for item in sparse_snapshot.warnings)


def test_15_multiple_metrics_increase_confidence() -> None:
    brain = BobaPerformanceFeedbackBrainV1()
    one_metric = brain.create_event(
        PROJECT_ID,
        event_type="manual_clip_result",
        target_type="clip",
        target_id="one_metric",
        metrics={"views": 100},
    )
    many_metrics = brain.create_event(
        PROJECT_ID,
        event_type="manual_clip_result",
        target_type="clip",
        target_id="many_metrics",
        metrics={
            "views": 100,
            "likes": 20,
            "comments": 4,
            "shares": 8,
            "retention_percent": 72.0,
        },
    )
    one_snapshot = brain.snapshot_from_event(one_metric)
    many_snapshot = brain.snapshot_from_event(many_metrics)
    assert one_snapshot is not None
    assert many_snapshot is not None
    assert many_snapshot.data_confidence > one_snapshot.data_confidence


def test_16_creator_note_can_create_cautious_factor() -> None:
    brain = BobaPerformanceFeedbackBrainV1()
    event = brain.create_event(
        PROJECT_ID,
        event_type="manual_note",
        target_type="clip",
        target_id="caption_note",
        manual_rating=4.0,
        creator_note="clean captions worked better",
    )
    result = brain.analyze(PROJECT_ID, [event])
    assert any(
        factor.category == "caption"
        for factor in result.pattern_summary.strongest_positive_patterns
    )
    assert result.pattern_summary.risky_conclusions


def test_17_high_performing_hook_creates_positive_hook_factor() -> None:
    assert any(
        factor.category == "hook" and "curiosity gap" in factor.summary
        for factor in _result().pattern_summary.strongest_positive_patterns
    )


def test_18_low_performing_slow_hook_creates_negative_retention_factor() -> None:
    negative = _result().pattern_summary.strongest_negative_patterns
    assert any(
        factor.category == "retention" and "dropped before payoff" in factor.summary
        for factor in negative
    )
    assert any(
        factor.category == "hook" and "slow opening" in factor.summary
        for factor in negative
    )


def test_19_winning_caption_variant_creates_caption_guidance() -> None:
    assert any(
        "caption" in guidance.casefold()
        for guidance in _result().learning_handoff.caption_motion_guidance
    )
    assert any(
        outcome.outcome_label == "variant_won"
        and any(factor.category == "caption" for factor in outcome.likely_success_factors)
        for outcome in _result().experiment_outcomes
    )


def test_20_losing_heavy_motion_variant_creates_motion_caution() -> None:
    assert any(
        "motion" in guidance.casefold()
        for guidance in _result().learning_handoff.caption_motion_guidance
    )
    assert any(
        outcome.outcome_label == "baseline_won"
        and any(factor.category == "motion" for factor in outcome.likely_failure_factors)
        for outcome in _result().experiment_outcomes
    )


def test_21_inconclusive_result_does_not_create_strong_learning() -> None:
    outcome = next(
        item
        for item in _result().experiment_outcomes
        if item.outcome_label == "inconclusive"
    )
    assert outcome.should_feed_learning is False
    assert outcome.learning_targets == []
    assert any("Inconclusive" in warning for warning in outcome.warnings)


def test_22_repeated_outcomes_increase_confidence() -> None:
    first = build_synthetic_performance_feedback(
        PROJECT_ID,
        include_contradictions=False,
        event_limit=1,
    )
    repeated = build_synthetic_performance_feedback(
        PROJECT_ID,
        include_contradictions=False,
        event_limit=2,
    )
    assert _factor_confidence(repeated, "curiosity gap") > _factor_confidence(
        first,
        "curiosity gap",
    )


def test_23_contradictory_outcomes_reduce_confidence() -> None:
    without = build_synthetic_performance_feedback(
        PROJECT_ID,
        include_contradictions=False,
    )
    with_contradictions = _result()
    assert with_contradictions.pattern_summary.contradictions
    assert (
        with_contradictions.pattern_summary.confidence
        < without.pattern_summary.confidence
    )


def test_24_auto_collected_count_remains_zero() -> None:
    assert _result().audit_summary.auto_collected_count == 0
    assert _result().audit_summary.user_entered_count == len(
        _result().performance_events
    )


def test_25_analytics_api_used_remains_false() -> None:
    assert _result().signal_usage.analytics_api_used is False


def test_26_apply_automatically_defaults_false() -> None:
    assert BobaPerformanceLearningHandoffV1().apply_automatically is False
    assert _result().learning_handoff.apply_automatically is False


def test_27_dry_run_does_not_persist(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    integration, store = _integration(tmp_path)
    _patch_artifact_loaders(monkeypatch, store)
    store.record_performance_feedback_event(_events()[0])
    result = asyncio.run(
        integration.generate_performance_feedback(PROJECT_ID, dry_run=True)
    )
    assert result.performance_events
    assert store.performance_feedback_path(PROJECT_ID).exists() is False
    assert any("Dry run" in warning for warning in result.warnings)


def test_28_export_excludes_raw_media_secrets_and_full_transcripts(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_performance_feedback(_result())
    encoded = json.dumps(store.export_performance_feedback(PROJECT_ID)).casefold()
    for forbidden in (
        "creator_note",
        "retention_notes",
        "creator_interpretation",
        "raw_media",
        "full_transcript",
        "api_key",
        "access_token",
        "password",
        ".mp4",
        ".wav",
    ):
        assert forbidden not in encoded


def test_29_reset_removes_only_performance_feedback_data(tmp_path: Path) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    artifacts = build_synthetic_performance_artifacts(PROJECT_ID)
    store.save_experimentation_plan(artifacts["experimentation"])
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    store.save_performance_feedback(_result())
    store.record_performance_feedback_event(_events()[0])
    assert store.reset_performance_feedback(PROJECT_ID) is True
    assert store.load_performance_feedback(PROJECT_ID) is None
    assert store.list_performance_feedback_events(PROJECT_ID) == []
    assert store.load_experimentation_plan(PROJECT_ID) is not None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_30_missing_performance_data_creates_clear_limitation() -> None:
    result = BobaPerformanceFeedbackBrainV1().analyze(PROJECT_ID, [])
    assert result.performance_events == []
    assert any("cannot be inferred" in item for item in result.limitations)
    assert any("No manual performance" in item for item in result.warnings)


def test_31_missing_optional_artifacts_degrade_gracefully() -> None:
    result = BobaPerformanceFeedbackBrainV1().analyze(
        PROJECT_ID,
        [_events()[0]],
    )
    assert result.performance_snapshots
    assert result.signal_usage.fallback_used is True
    assert "experimentation" in result.signal_usage.unavailable_signals


def test_32_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_performance_feedback(_result())
    path = store.performance_feedback_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/performance_feedback/index.json"
    )
    assert payload["schema_version"] == "boba_performance_feedback_v1"
    assert store.load_performance_feedback(PROJECT_ID) == saved


def test_33_events_log_is_append_safe(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    first, second = _events()[:2]
    store.record_performance_feedback_event(first)
    store.record_performance_feedback_event(second)
    store.record_performance_feedback_event(first)
    loaded = store.list_performance_feedback_events(PROJECT_ID)
    assert [item.event_id for item in loaded] == [first.event_id, second.event_id]
    assert store.performance_feedback_events_path(PROJECT_ID).read_text(
        encoding="utf-8"
    ).count("\n") == 2


def test_34_api_event_route_records_explicit_manual_result(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/performance-feedback/events",
            json={
                "event_type": "manual_clip_result",
                "target_type": "clip",
                "target_id": "clip_api",
                "manual_rating": 4.0,
                "creator_note": "Explicit API review.",
                "metrics": {"views": 100, "retention_percent": 70.0},
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["event"]["user_entered"] is True
    assert response.json()["analytics_collected"] is False
    assert response.json()["automatically_applied"] is False
    assert len(store.list_performance_feedback_events(PROJECT_ID)) == 1


def test_35_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_performance_feedback(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/performance-feedback"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_performance_feedback_v1"
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Performance Feedback Brain V1" in panel
    assert "Performance data is manual in V1" in panel


def test_36_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_performance_feedback(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/performance-feedback/export"
        )
    assert response.status_code == 200, response.text
    assert "raw_media" not in response.text.casefold()
    assert "full_transcript" not in response.text.casefold()
    assert "api_key" not in response.text.casefold()
    assert "creator_note" not in response.text.casefold()


def test_37_api_delete_resets_project_artifact_only(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_performance_feedback(_result())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/performance-feedback"
        )
    assert response.status_code == 200, response.text
    assert response.json()["unrelated_memory_removed"] is False
    assert response.json()["experimentation_removed"] is False
    assert store.load_performance_feedback(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_38_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.auto_collected_count_zero is True
    assert report.external_calls_made is False


def test_39_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.events_recorded >= 9
    assert report.outcomes_created >= 3
    assert report.contradictions_reduce_confidence is True


def test_40_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Performance feedback must not invoke a renderer.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert build_synthetic_performance_feedback("proj_no_render").performance_events


def test_41_no_uploading_is_triggered(monkeypatch: Any) -> None:
    def fail_upload(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Performance feedback must not upload media.")

    monkeypatch.setattr(Path, "write_bytes", fail_upload)
    assert build_synthetic_performance_feedback("proj_no_upload").performance_events


def test_42_no_analytics_are_collected() -> None:
    report = run_synthetic_project(
        ROOT / "work" / "validation_reports" / "performance_feedback_tests"
    )
    assert report.analytics_collected is False
    assert report.auto_collected_count_zero is True
    assert report.analytics_api_used_false is True


def test_43_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Performance feedback must not use the network.")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = build_synthetic_performance_feedback("proj_no_network")
    assert result.signal_usage.analytics_api_used is False


def test_44_no_reports_or_media_are_staged() -> None:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    staged = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines()]
    forbidden = (
        "work/",
        "storage_data/",
        "media/",
        ".venv/",
        "node_modules/",
        "frontend/.next/",
    )
    assert not any(path.startswith(forbidden) for path in staged)
    assert not any(path.casefold().endswith((".mp4", ".mov", ".wav")) for path in staged)

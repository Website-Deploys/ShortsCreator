"""BOBA Experimentation System V1 behavior, persistence, and safety tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_experimentation import (
    build_synthetic_experimentation,
    build_synthetic_experimentation_artifacts,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaExperimentApprovalRequirementV1,
    BobaExperimentationSetV1,
    BobaExperimentationSignalUsageV1,
    BobaExperimentationSystemV1,
    BobaExperimentBaselineV1,
    BobaExperimentHypothesisV1,
    BobaExperimentLearningHandoffV1,
    BobaExperimentManualResultV1,
    BobaExperimentMetricPlanV1,
    BobaExperimentPlanV1,
    BobaExperimentRiskReviewV1,
    BobaExperimentSuccessCriteriaV1,
    BobaExperimentVariantV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaProjectMemoryV1,
    BobaRejectedExperimentIdeaV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_experimentation_test"


@lru_cache(maxsize=4)
def _result(project_id: str = PROJECT_ID) -> BobaExperimentationSetV1:
    return build_synthetic_experimentation(project_id)


def _plan(experiment_type: str) -> BobaExperimentPlanV1:
    return next(
        item
        for item in _result().experiment_plans
        if item.experiment_type == experiment_type
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Experimentation Test",
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
) -> None:
    artifacts = build_synthetic_experimentation_artifacts()
    loaders = {
        "load_clip_briefs": "clip_briefs",
        "load_hook_retention": "hook_retention",
        "load_caption_motion": "caption_motion",
        "load_music_mood": "music_mood",
        "load_creative_direction_v2": "creative_direction",
        "load_editorial_decisions": "editorial_decision",
        "load_explanations": "explanation",
        "load_creator_learning": "creator_learning",
        "load_approval_rejection_learning": "approval_rejection_learning",
        "load_project_memory": "memory",
    }
    for method, artifact in loaders.items():
        monkeypatch.setattr(
            store,
            method,
            lambda _project_id, key=artifact: artifacts[key],
        )


def test_01_experimentation_set_contract_serializes() -> None:
    result = _result()
    assert BobaExperimentationSetV1.model_validate_json(
        result.model_dump_json()
    ) == result


def test_02_experiment_plan_contract_serializes() -> None:
    plan = _result().experiment_plans[0]
    assert BobaExperimentPlanV1.model_validate(plan.model_dump()) == plan


def test_03_baseline_contract_serializes() -> None:
    baseline = _result().experiment_plans[0].baseline
    assert BobaExperimentBaselineV1.model_validate(baseline.model_dump()) == baseline


def test_04_variant_contract_serializes() -> None:
    variant = _result().experiment_plans[0].variants[0]
    assert BobaExperimentVariantV1.model_validate(variant.model_dump()) == variant


def test_05_hypothesis_contract_serializes() -> None:
    hypothesis = _result().experiment_plans[0].hypothesis
    assert BobaExperimentHypothesisV1.model_validate(
        hypothesis.model_dump()
    ) == hypothesis


def test_06_metric_plan_contract_serializes() -> None:
    metric_plan = _result().experiment_plans[0].metric_plan
    assert BobaExperimentMetricPlanV1.model_validate(
        metric_plan.model_dump()
    ) == metric_plan


def test_07_success_criteria_contract_serializes() -> None:
    criteria = _result().experiment_plans[0].success_criteria
    assert BobaExperimentSuccessCriteriaV1.model_validate(
        criteria.model_dump()
    ) == criteria


def test_08_risk_review_contract_serializes() -> None:
    risk = _result().experiment_plans[0].risk_review
    assert BobaExperimentRiskReviewV1.model_validate(risk.model_dump()) == risk


def test_09_learning_handoff_contract_serializes() -> None:
    handoff = _result().experiment_plans[0].learning_handoff
    assert BobaExperimentLearningHandoffV1.model_validate(
        handoff.model_dump()
    ) == handoff


def test_10_rejected_idea_contract_serializes() -> None:
    rejected = _result().rejected_experiment_ideas[0]
    assert BobaRejectedExperimentIdeaV1.model_validate(
        rejected.model_dump()
    ) == rejected


def test_11_approval_requirement_contract_serializes() -> None:
    requirement = _result().approval_requirements[0]
    assert BobaExperimentApprovalRequirementV1.model_validate(
        requirement.model_dump()
    ) == requirement


def test_12_signal_usage_contract_serializes() -> None:
    usage = _result().signal_usage
    assert BobaExperimentationSignalUsageV1.model_validate(
        usage.model_dump()
    ) == usage


def test_13_weak_hook_creates_hook_experiment() -> None:
    plan = _plan("hook_ab_test")
    assert plan.candidate_id in {"strong_clip", "weak_hook_clip"}
    assert plan.baseline.source_artifact == "hook_retention"


def test_14_caption_overload_creates_caption_experiment() -> None:
    plan = next(
        item
        for item in _result().experiment_plans
        if item.experiment_type == "caption_ab_test"
        and item.candidate_id == "caption_overload_clip"
    )
    assert plan.risk_review.caption_overload_risk is True


def test_15_heavy_motion_risk_creates_motion_experiment() -> None:
    plan = next(
        item
        for item in _result().experiment_plans
        if item.experiment_type == "motion_ab_test"
        and item.candidate_id == "heavy_motion_clip"
    )
    assert plan.risk_review.motion_safety_risk is True
    assert plan.risk_review.blockers


def test_16_wrong_mood_risk_creates_music_mood_experiment() -> None:
    plan = next(
        item
        for item in _result().experiment_plans
        if item.experiment_type == "music_mood_ab_test"
        and item.candidate_id == "wrong_mood_clip"
    )
    assert plan.risk_review.audio_mismatch_risk is True


def test_17_retention_risk_creates_retention_experiment() -> None:
    assert _plan("retention_ab_test").metric_plan.primary_metric == (
        "retention_quality_review"
    )


def test_18_baseline_is_traceable_to_source_artifact() -> None:
    assert all(
        plan.baseline.source_artifact and plan.baseline.source_field
        for plan in _result().experiment_plans
    )


def test_19_variants_change_one_main_variable() -> None:
    assert all(
        len({variant.changed_variable for variant in plan.variants}) == 1
        for plan in _result().experiment_plans
    )


def test_20_creator_approval_is_required_by_default() -> None:
    assert all(
        plan.required_creator_approval
        and plan.status == "needs_creator_approval"
        for plan in _result().experiment_plans
    )


def test_21_apply_automatically_defaults_false() -> None:
    assert all(
        plan.learning_handoff.apply_automatically is False
        for plan in _result().experiment_plans
    )


def test_22_misleading_hook_idea_is_rejected() -> None:
    assert any(
        item.experiment_type == "hook_ab_test"
        and "misleading" in item.reason_rejected.casefold()
        for item in _result().rejected_experiment_ideas
    )


def test_23_unresolved_rights_risk_creates_warning_or_rejection() -> None:
    plans = [
        item
        for item in _result().experiment_plans
        if item.candidate_id == "wrong_mood_clip"
    ]
    rejected = _result().rejected_experiment_ideas
    assert any(plan.risk_review.rights_risk for plan in plans)
    assert any("rights" in item.risk.casefold() for item in rejected)


def test_24_metric_plan_does_not_collect_analytics_in_v1() -> None:
    assert all(
        any("V1" in note and "manual" in note for note in plan.metric_plan.notes)
        for plan in _result().experiment_plans
    )
    assert any("No viewer analytics" in warning for warning in _result().warnings)


def test_25_future_viewer_metrics_mark_analytics_required_later_true() -> None:
    retention = _plan("retention_ab_test")
    assert "future_viewer_retention" in retention.metric_plan.secondary_metrics
    assert retention.metric_plan.analytics_required_later is True


def test_26_manual_result_contract_serializes() -> None:
    plan = _result().experiment_plans[0]
    result = BobaExperimentationSystemV1().create_manual_result(
        plan,
        selected_variant_id=plan.variants[0].variant_id,
        manual_rating=4.5,
        outcome_label="variant_preferred",
        creator_note="Explicit review.",
    )
    assert BobaExperimentManualResultV1.model_validate(result.model_dump()) == result


def test_27_manual_result_does_not_auto_apply_winner() -> None:
    plan = _result().experiment_plans[0]
    result = BobaExperimentationSystemV1().create_manual_result(
        plan,
        selected_variant_id=plan.variants[0].variant_id,
        manual_rating=5.0,
        outcome_label="variant_preferred",
        should_feed_learning=True,
    )
    assert result.should_feed_learning is True
    assert any("without applying" in warning for warning in result.warnings)
    assert plan.learning_handoff.apply_automatically is False


def test_28_dry_run_does_not_persist(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    integration, store = _integration(tmp_path)
    _patch_artifact_loaders(monkeypatch, store)
    result = asyncio.run(
        integration.generate_experimentation_plan(PROJECT_ID, dry_run=True)
    )
    assert result.experiment_plans
    assert store.experimentation_path(PROJECT_ID).exists() is False


def test_29_export_excludes_raw_media_secrets_and_full_transcripts(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    result = _result()
    store.save_experimentation_plan(result)
    manual = BobaExperimentationSystemV1().create_manual_result(
        result.experiment_plans[0],
        selected_variant_id=result.experiment_plans[0].variants[0].variant_id,
        manual_rating=4.0,
        outcome_label="variant_preferred",
        creator_note="Private explicit note.",
    )
    store.record_manual_experiment_result(PROJECT_ID, manual)
    encoded = json.dumps(store.export_experimentation_plan(PROJECT_ID)).casefold()
    for forbidden in (
        "creator_note",
        "raw_media",
        "full_transcript",
        "api_key",
        "access_token",
        "password",
        ".mp4",
        ".wav",
    ):
        assert forbidden not in encoded


def test_30_reset_removes_only_experimentation_artifact(tmp_path: Path) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    store.save_experimentation_plan(_result())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    assert store.reset_experimentation_plan(PROJECT_ID) is True
    assert store.load_experimentation_plan(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_31_missing_required_artifacts_creates_clear_limitation() -> None:
    result = BobaExperimentationSystemV1().analyze(PROJECT_ID)
    assert result.experiment_plans == []
    assert any("require" in item.casefold() for item in result.limitations)
    assert result.signal_usage.fallback_used is True


def test_32_missing_optional_artifacts_degrade_gracefully() -> None:
    artifacts = build_synthetic_experimentation_artifacts()
    result = BobaExperimentationSystemV1().analyze(
        PROJECT_ID,
        clip_briefs=artifacts["clip_briefs"],
        hook_retention=artifacts["hook_retention"],
    )
    assert result.experiment_plans
    assert result.signal_usage.fallback_used is True
    assert "music_mood" in result.signal_usage.unavailable_signals


def test_33_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_experimentation_plan(_result())
    path = store.experimentation_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/experimentation/index.json"
    )
    assert payload["schema_version"] == "boba_experimentation_system_v1"
    assert store.load_experimentation_plan(PROJECT_ID) == saved


def test_34_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_experimentation_plan(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/experimentation"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_experimentation_system_v1"
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Experimentation System V1" in panel
    assert "BOBA does not upload, render, or collect" in panel


def test_35_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_experimentation_plan(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/experimentation/export"
        )
    assert response.status_code == 200, response.text
    assert "raw_media" not in response.text.casefold()
    assert "full_transcript" not in response.text.casefold()
    assert "api_key" not in response.text.casefold()


def test_36_api_delete_resets_project_artifact_only(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_experimentation_plan(_result())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/experimentation"
        )
    assert response.status_code == 200, response.text
    assert response.json()["unrelated_memory_removed"] is False
    assert store.load_experimentation_plan(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_37_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.external_calls_made is False
    assert report.rendering_triggered is False


def test_38_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.experiment_plans >= 8
    assert report.rejected_ideas > 0


def test_39_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Experiment planning must not invoke a renderer.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert build_synthetic_experimentation("proj_no_render").experiment_plans


def test_40_no_uploading_is_triggered(monkeypatch: Any) -> None:
    def fail_upload(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Experiment planning must not upload media.")

    monkeypatch.setattr(Path, "write_bytes", fail_upload)
    assert build_synthetic_experimentation("proj_no_upload").experiment_plans


def test_41_no_analytics_are_collected() -> None:
    report = run_synthetic_project(ROOT / "work" / "validation_reports" / "tests")
    assert report.analytics_collected is False
    assert all(
        "future_viewer" not in plan.metric_plan.required_result_fields
        for plan in _result().experiment_plans
    )


def test_42_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Experiment planning must not use network calls.")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    assert build_synthetic_experimentation("proj_no_network").experiment_plans


def test_43_no_reports_or_media_are_staged() -> None:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    staged = result.stdout.replace("\\", "/").casefold().splitlines()
    forbidden_prefixes = (
        "work/",
        "storage_data/",
        "media/",
        ".venv/",
        "node_modules/",
        "frontend/.next/",
    )
    forbidden_suffixes = (".mp4", ".mov", ".wav", ".mp3")
    assert result.returncode == 0
    assert not any(
        path.startswith(forbidden_prefixes) or path.endswith(forbidden_suffixes)
        for path in staged
    )

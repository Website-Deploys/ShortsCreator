"""BOBA Hook + Retention Brain V1 contracts, behavior, API, and safety tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_hook_retention import (
    REPORT_DIR,
    build_synthetic_hook_retention,
    build_synthetic_hook_retention_inputs,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaBriefHookEnhancementV1,
    BobaHookAlternativeV1,
    BobaHookAnalysisV1,
    BobaHookRetentionAnalysisV1,
    BobaHookRetentionBrainV1,
    BobaHookRetentionSetV1,
    BobaHookRetentionSignalUsageV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaRetentionPlanV1,
    BobaRetentionRiskReviewV1,
    BobaRetentionScoreV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_hook_retention_brain"


def _result(project_id: str = PROJECT_ID) -> BobaHookRetentionSetV1:
    return build_synthetic_hook_retention(project_id)


def _analysis(
    candidate_id: str = "must_make_truth",
) -> BobaHookRetentionAnalysisV1:
    return next(
        item for item in _result().analyses if item.candidate_id == candidate_id
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Hook Retention Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=340.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def test_01_hook_retention_set_contract_serializes() -> None:
    result = _result()
    assert BobaHookRetentionSetV1.model_validate_json(result.model_dump_json()) == result
    assert result.schema_version == "boba_hook_retention_brain_v1"


def test_02_analysis_contract_serializes() -> None:
    analysis = _analysis()
    assert BobaHookRetentionAnalysisV1.model_validate(analysis.model_dump()) == analysis


def test_03_hook_analysis_serializes() -> None:
    hook = _analysis().hook_analysis
    assert BobaHookAnalysisV1.model_validate(hook.model_dump()) == hook


def test_04_hook_alternative_serializes() -> None:
    alternative = _analysis().hook_alternatives[0]
    assert BobaHookAlternativeV1.model_validate(alternative.model_dump()) == alternative


def test_05_retention_plan_serializes() -> None:
    plan = _analysis().retention_plan
    assert BobaRetentionPlanV1.model_validate(plan.model_dump()) == plan


def test_06_risk_review_serializes() -> None:
    review = _analysis().retention_risk_review
    assert BobaRetentionRiskReviewV1.model_validate(review.model_dump()) == review


def test_07_retention_score_serializes() -> None:
    score = _analysis().retention_score
    assert BobaRetentionScoreV1.model_validate(score.model_dump()) == score


def test_08_brief_enhancement_serializes() -> None:
    enhancement = _analysis().brief_enhancements
    assert (
        BobaBriefHookEnhancementV1.model_validate(enhancement.model_dump())
        == enhancement
    )
    assert enhancement.apply_suggestion is False


def test_09_signal_usage_serializes() -> None:
    usage = _result().signal_usage
    assert BobaHookRetentionSignalUsageV1.model_validate(usage.model_dump()) == usage


def test_10_strong_hook_gets_higher_hook_score() -> None:
    strong = _analysis("must_make_truth")
    weak = _analysis("weak_hook")
    assert strong.retention_score.hook_score > weak.retention_score.hook_score


def test_11_weak_opening_creates_slow_start_risk() -> None:
    weak = _analysis("weak_hook")
    assert weak.retention_risk_review.slow_start_risk is True
    assert any("hook" in warning.casefold() for warning in weak.warnings)


def test_12_missing_payoff_creates_weak_payoff_risk() -> None:
    missing = _analysis("weak_payoff")
    assert missing.retention_risk_review.weak_payoff_risk is True


def test_13_unclear_context_creates_context_risk() -> None:
    context = _analysis("slow_start")
    assert context.retention_risk_review.unclear_context_risk is True


def test_14_alternatives_include_best_safest_boldest() -> None:
    labels = {
        alternative.recommendation_label
        for alternative in _analysis().hook_alternatives
    }
    assert {"best", "safest", "boldest"}.issubset(labels)
    assert 3 <= len(_analysis().hook_alternatives) <= 5


def test_15_avoid_alternative_has_higher_risk() -> None:
    alternatives = {
        item.recommendation_label: item for item in _analysis().hook_alternatives
    }
    assert alternatives["avoid"].risk_score > alternatives["best"].risk_score
    assert alternatives["avoid"].risk_score > alternatives["safest"].risk_score


def test_16_first_three_second_plan_exists() -> None:
    analysis = _analysis()
    assert analysis.retention_plan.seconds_0_to_3
    assert analysis.hook_analysis.first_three_second_clarity >= 0.0


def test_17_retention_plan_contains_every_time_section() -> None:
    plan = _analysis().retention_plan
    assert plan.seconds_0_to_3
    assert plan.seconds_3_to_10
    assert plan.middle_hold_strategy
    assert plan.payoff_timing_strategy
    assert plan.ending_replay_trigger


def test_18_brief_enhancement_does_not_mutate_original_brief() -> None:
    (
        briefs,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    ) = build_synthetic_hook_retention_inputs("proj_no_mutation")
    before = briefs.model_dump_json()
    result = BobaHookRetentionBrainV1().analyze_from_signals(
        "proj_no_mutation",
        signals,
        clip_briefs=briefs,
        creative_direction_v2=direction,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        memory=memory,
    )
    assert result.analyses[0].brief_enhancements.apply_suggestion is False
    assert briefs.model_dump_json() == before


def test_19_scores_are_clamped_to_valid_range() -> None:
    (
        briefs,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    ) = build_synthetic_hook_retention_inputs("proj_clamped_scores")
    ranking_payload = ranking.model_dump(mode="json")
    ranking_payload["ranked_candidates"][0]["score_breakdown"]["hook_score"] = 900
    result = BobaHookRetentionBrainV1().analyze_from_signals(
        "proj_clamped_scores",
        signals,
        clip_briefs=briefs,
        creative_direction_v2=direction,
        editorial_decisions=decisions,
        clip_ranking=ranking_payload,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        virality={"hook_score": -500, "replay_score": 700},
        memory=memory,
    )
    for analysis in result.analyses:
        for value in analysis.retention_score.model_dump().values():
            assert 0.0 <= value <= 100.0


def test_20_project_summary_identifies_weakest_hooks() -> None:
    summary = _result().project_retention_summary.casefold()
    assert "weakest hooks" in summary
    assert "weak_hook" in summary


def test_21_missing_clip_briefs_fail_clearly() -> None:
    with pytest.raises(ValidationError, match="requires saved clip briefs"):
        BobaHookRetentionBrainV1().analyze(
            project_id="proj_missing_briefs",
            clip_briefs=None,
        )


def test_22_missing_optional_artifacts_degrade_gracefully() -> None:
    briefs, *_ = build_synthetic_hook_retention_inputs("proj_fallback")
    result = BobaHookRetentionBrainV1().analyze(
        project_id="proj_fallback",
        clip_briefs=briefs,
    )
    assert result.analyses
    assert result.signal_usage.fallback_used is True
    assert "creative_direction_v2" in result.signal_usage.unavailable_signals


def test_23_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    result = store.save_hook_retention(_result())
    path = store.hook_retention_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/hook_retention/index.json"
    )
    assert store.load_hook_retention(PROJECT_ID) == result
    assert payload["schema_version"] == "boba_hook_retention_brain_v1"
    assert "transcript_segments" not in payload


def test_24_api_routes_return_saved_artifact_and_frontend_exposes_it(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    (
        briefs,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        _signals,
    ) = build_synthetic_hook_retention_inputs(PROJECT_ID)
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    store.save_clip_briefs(briefs)
    store.save_creative_direction_v2(direction)
    store.save_whole_video_understanding(understanding)
    store.save_candidate_clip_discovery(discovery)
    store.save_clip_ranking(ranking)
    store.save_editorial_decisions(decisions)
    store.save_explanations(explanations)
    store.save_project_memory(memory)
    integration = BobaIntegration(storage, store)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        created = client.post(f"/api/v1/boba/projects/{PROJECT_ID}/hook-retention")
        saved = client.get(f"/api/v1/boba/projects/{PROJECT_ID}/hook-retention")
    assert created.status_code == 200
    assert saved.status_code == 200
    assert created.json()["analyses"] == saved.json()["analyses"]
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Hook + Retention Brain V1" in panel
    assert "Project retention summary" in panel
    assert "Clip brief enhancement suggestions" in panel


def test_25_validator_self_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_hook_retention.py"),
            "--self-check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"passed": true' in result.stdout.casefold()
    assert '"rendering_triggered": false' in result.stdout.casefold()


def test_26_validator_synthetic_project_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_hook_retention.py"),
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"strong_hook_scores_higher": true' in result.stdout.casefold()
    assert '"slow_start_detected": true' in result.stdout.casefold()
    assert '"artifact_persisted": true' in result.stdout.casefold()


def test_27_generation_does_not_trigger_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rendering or subprocess execution is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert _result().analyses


def test_28_generation_makes_no_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    assert _result().signal_usage.clip_briefs_used is True


def test_29_reports_and_media_are_not_staged() -> None:
    assert REPORT_DIR == ROOT / "work" / "validation_reports" / "boba_hook_retention"
    assert "media" not in REPORT_DIR.parts
    assert "storage_data" not in REPORT_DIR.parts
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    ).stdout.splitlines()
    assert not any(
        path.startswith(("work/", "media/", "storage_data/")) for path in staged
    )

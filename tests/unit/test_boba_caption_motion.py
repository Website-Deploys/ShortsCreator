"""BOBA Caption + Motion Recommendation Brain V1 contracts and behavior tests."""

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
from tools.validate_boba_caption_motion import (
    REPORT_DIR,
    build_synthetic_caption_motion,
    build_synthetic_caption_motion_inputs,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaCaptionMotionBriefEnhancementV1,
    BobaCaptionMotionRecommendationBrainV1,
    BobaCaptionMotionRecommendationSetV1,
    BobaCaptionMotionRecommendationV1,
    BobaCaptionMotionSafetyReviewV1,
    BobaCaptionMotionScoreV1,
    BobaCaptionMotionSignalUsageV1,
    BobaCaptionMotionTimestampV1,
    BobaCaptionMotionTimingMapV1,
    BobaCaptionRecommendationV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaMotionRecommendationV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_caption_motion_brain"


def _result(project_id: str = PROJECT_ID) -> BobaCaptionMotionRecommendationSetV1:
    return build_synthetic_caption_motion(project_id)


def _recommendation(
    candidate_id: str = "strong_educational",
) -> BobaCaptionMotionRecommendationV1:
    return next(
        item for item in _result().recommendations if item.candidate_id == candidate_id
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Caption Motion Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=420.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def test_01_recommendation_set_contract_serializes() -> None:
    result = _result()
    assert BobaCaptionMotionRecommendationSetV1.model_validate_json(
        result.model_dump_json()
    ) == result
    assert result.schema_version == "boba_caption_motion_recommendation_brain_v1"


def test_02_recommendation_contract_serializes() -> None:
    recommendation = _recommendation()
    assert (
        BobaCaptionMotionRecommendationV1.model_validate(
            recommendation.model_dump()
        )
        == recommendation
    )


def test_03_caption_recommendation_serializes() -> None:
    caption = _recommendation().caption_recommendation
    assert BobaCaptionRecommendationV1.model_validate(caption.model_dump()) == caption


def test_04_motion_recommendation_serializes() -> None:
    motion = _recommendation().motion_recommendation
    assert BobaMotionRecommendationV1.model_validate(motion.model_dump()) == motion


def test_05_timing_map_serializes() -> None:
    timing = _recommendation().timing_map
    assert BobaCaptionMotionTimingMapV1.model_validate(timing.model_dump()) == timing


def test_06_timestamp_serializes() -> None:
    timestamp = _recommendation().timing_map.caption_highlight_timestamps[0]
    assert (
        BobaCaptionMotionTimestampV1.model_validate(timestamp.model_dump())
        == timestamp
    )


def test_07_safety_review_serializes() -> None:
    safety = _recommendation().safety_review
    assert (
        BobaCaptionMotionSafetyReviewV1.model_validate(safety.model_dump()) == safety
    )


def test_08_score_serializes() -> None:
    score = _recommendation().recommendation_score
    assert BobaCaptionMotionScoreV1.model_validate(score.model_dump()) == score


def test_09_brief_enhancement_serializes() -> None:
    enhancement = _recommendation().brief_enhancement
    assert (
        BobaCaptionMotionBriefEnhancementV1.model_validate(
            enhancement.model_dump()
        )
        == enhancement
    )
    assert enhancement.apply_suggestion is False


def test_10_signal_usage_serializes() -> None:
    usage = _result().signal_usage
    assert BobaCaptionMotionSignalUsageV1.model_validate(usage.model_dump()) == usage


def test_11_educational_clip_gets_keyword_or_educational_captions() -> None:
    assert _recommendation().caption_recommendation.caption_style in {
        "keyword_highlight",
        "educational_steps",
    }


def test_12_emotional_clip_gets_emotional_or_clean_captions() -> None:
    caption = _recommendation("strong_emotional").caption_recommendation
    assert caption.caption_style in {"emotional_emphasis", "clean_subtitles"}
    assert caption.caption_density in {"low", "medium"}


def test_13_high_energy_clip_gets_bold_or_punchy_captions() -> None:
    caption = _recommendation("high_energy").caption_recommendation
    assert caption.caption_style in {"bold_hook_captions", "punchline_caption"}
    assert caption.caption_rhythm == "punchy"


def test_14_caption_overload_risk_reduces_density() -> None:
    overloaded = _recommendation("weak_hook")
    assert overloaded.safety_review.caption_overload_risk is True
    assert overloaded.caption_recommendation.caption_density == "low"
    assert overloaded.caption_recommendation.caption_density != (
        _recommendation("strong_educational").caption_recommendation.caption_density
    )


def test_15_keyword_highlights_are_bounded() -> None:
    for recommendation in _result().recommendations:
        keywords = recommendation.caption_recommendation.keyword_highlights
        assert len(keywords) <= 8
        assert all(len(keyword) <= 48 for keyword in keywords)


def test_16_missing_face_layout_signals_prefer_stable_motion() -> None:
    briefs, *_rest = build_synthetic_caption_motion_inputs("proj_missing_layout")
    result = BobaCaptionMotionRecommendationBrainV1().analyze(
        project_id="proj_missing_layout",
        clip_briefs=briefs,
    )
    assert result.recommendations
    assert all(
        item.motion_recommendation.motion_style in {"stable", "layout_safe"}
        for item in result.recommendations
    )


def test_17_multi_speaker_risk_prefers_layout_safe_motion() -> None:
    recommendation = _recommendation("layout_risk")
    assert recommendation.motion_recommendation.motion_style in {
        "stable",
        "layout_safe",
    }
    assert recommendation.safety_review.multi_speaker_layout_risk is True


def test_18_strong_hook_payoff_creates_punch_in_moment() -> None:
    recommendation = _recommendation("high_energy")
    assert recommendation.motion_recommendation.punch_in_moments
    assert any(
        timestamp.action == "opening_punch_in"
        for timestamp in recommendation.timing_map.motion_timestamps
    )


def test_19_calm_clip_uses_subtle_or_stable_motion() -> None:
    motion = _recommendation("strong_emotional").motion_recommendation
    assert motion.motion_style in {"subtle_zoom", "stable"}
    assert motion.motion_intensity in {"none", "light"}


def test_20_timing_map_contains_every_section() -> None:
    timing = _recommendation().timing_map
    assert timing.seconds_0_to_3
    assert timing.seconds_3_to_10
    assert timing.middle_section
    assert timing.payoff_section
    assert timing.ending_section


def test_21_safety_review_flags_unavailable_signals() -> None:
    briefs, *_rest = build_synthetic_caption_motion_inputs("proj_signal_warning")
    result = BobaCaptionMotionRecommendationBrainV1().analyze(
        project_id="proj_signal_warning",
        clip_briefs=briefs,
    )
    assert all(
        item.safety_review.unavailable_face_signal_risk
        and item.safety_review.unavailable_layout_signal_risk
        for item in result.recommendations
    )


def test_22_scores_are_clamped_to_valid_range() -> None:
    for recommendation in _result().recommendations:
        for value in recommendation.recommendation_score.model_dump().values():
            assert 0.0 <= value <= 100.0


def test_23_brief_enhancement_does_not_mutate_original_brief() -> None:
    (
        briefs,
        hook,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
        face_validation,
        speaker_validation,
        analysis_signals,
    ) = build_synthetic_caption_motion_inputs("proj_no_mutation")
    before = briefs.model_dump_json()
    result = BobaCaptionMotionRecommendationBrainV1().analyze_from_signals(
        "proj_no_mutation",
        signals,
        clip_briefs=briefs,
        hook_retention=hook,
        creative_direction_v2=direction,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        face_motion_validation=face_validation,
        multi_speaker_validation=speaker_validation,
        analysis_signals=analysis_signals,
        memory=memory,
    )
    assert all(
        item.brief_enhancement.apply_suggestion is False
        for item in result.recommendations
    )
    assert briefs.model_dump_json() == before


def test_24_missing_clip_briefs_fail_clearly() -> None:
    with pytest.raises(ValidationError, match="requires saved clip briefs"):
        BobaCaptionMotionRecommendationBrainV1().analyze(
            project_id="proj_missing_briefs",
            clip_briefs=None,
        )


def test_25_missing_optional_artifacts_degrade_gracefully() -> None:
    briefs, *_rest = build_synthetic_caption_motion_inputs("proj_fallback")
    result = BobaCaptionMotionRecommendationBrainV1().analyze(
        project_id="proj_fallback",
        clip_briefs=briefs,
    )
    assert result.recommendations
    assert result.signal_usage.fallback_used is True
    assert "hook_retention" in result.signal_usage.unavailable_signals


def test_26_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    result = store.save_caption_motion(_result())
    path = store.caption_motion_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/caption_motion/index.json"
    )
    assert store.load_caption_motion(PROJECT_ID) == result
    assert payload["schema_version"] == "boba_caption_motion_recommendation_brain_v1"
    encoded = json.dumps(payload)
    assert "transcript_segments" not in encoded
    assert '"raw_media"' not in encoded


def test_27_api_routes_return_saved_artifact_and_frontend_exposes_it(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    (
        briefs,
        hook,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        _signals,
        _face_validation,
        _speaker_validation,
        _analysis_signals,
    ) = build_synthetic_caption_motion_inputs(PROJECT_ID)
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    store.save_clip_briefs(briefs)
    store.save_hook_retention(hook)
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
        created = client.post(f"/api/v1/boba/projects/{PROJECT_ID}/caption-motion")
        saved = client.get(f"/api/v1/boba/projects/{PROJECT_ID}/caption-motion")
    assert created.status_code == 200
    assert saved.status_code == 200
    assert created.json()["recommendations"] == saved.json()["recommendations"]
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Caption + Motion Recommendation Brain V1" in panel
    assert "Timing map and safety review" in panel
    assert "Advisory clip-brief enhancements" in panel


def test_28_validator_self_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_caption_motion.py"),
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


def test_29_validator_synthetic_project_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_caption_motion.py"),
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"high_energy_motion_valid": true' in result.stdout.casefold()
    assert '"layout_risk_motion_safe": true' in result.stdout.casefold()
    assert '"artifact_persisted": true' in result.stdout.casefold()


def test_30_generation_does_not_trigger_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rendering or subprocess execution is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert _result().recommendations


def test_31_generation_makes_no_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    assert _result().signal_usage.clip_briefs_used is True


def test_32_reports_and_media_are_not_staged() -> None:
    assert REPORT_DIR == ROOT / "work" / "validation_reports" / "boba_caption_motion"
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

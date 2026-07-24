"""BOBA Music Mood Brain V1 contracts, behavior, and boundary tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_music_mood import (
    build_synthetic_music_mood,
    build_synthetic_music_mood_inputs,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaAudioEnergyMapV1,
    BobaAudioRiskReviewV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaMusicMoodBrainV1,
    BobaMusicMoodBriefEnhancementV1,
    BobaMusicMoodRecommendationSetV1,
    BobaMusicMoodRecommendationV1,
    BobaMusicMoodScoreV1,
    BobaMusicMoodSignalUsageV1,
    BobaMusicMoodV1,
    BobaSfxRecommendationV1,
    BobaSpeechClarityPlanV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_music_mood_brain"


@lru_cache(maxsize=4)
def _result(project_id: str = PROJECT_ID) -> BobaMusicMoodRecommendationSetV1:
    return build_synthetic_music_mood(project_id)


def _recommendation(
    candidate_id: str = "strong_educational",
) -> BobaMusicMoodRecommendationV1:
    return next(
        item for item in _result().recommendations if item.candidate_id == candidate_id
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Music Mood Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=600.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _forbidden_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {
            *{str(key).casefold() for key in value},
            *(
                key
                for nested in value.values()
                for key in _forbidden_keys(nested)
            ),
        }
    if isinstance(value, list):
        return {
            key
            for nested in value
            for key in _forbidden_keys(nested)
        }
    return set()


def test_01_recommendation_set_contract_serializes() -> None:
    result = _result()
    assert BobaMusicMoodRecommendationSetV1.model_validate_json(
        result.model_dump_json()
    ) == result
    assert result.schema_version == "boba_music_mood_brain_v1"


def test_02_recommendation_contract_serializes() -> None:
    recommendation = _recommendation()
    assert (
        BobaMusicMoodRecommendationV1.model_validate(
            recommendation.model_dump()
        )
        == recommendation
    )


def test_03_music_mood_contract_serializes() -> None:
    mood = _recommendation().music_mood
    assert BobaMusicMoodV1.model_validate(mood.model_dump()) == mood


def test_04_audio_energy_map_serializes() -> None:
    energy_map = _recommendation().audio_energy_map
    assert BobaAudioEnergyMapV1.model_validate(energy_map.model_dump()) == energy_map


def test_05_speech_clarity_plan_serializes() -> None:
    clarity = _recommendation().speech_clarity_plan
    assert BobaSpeechClarityPlanV1.model_validate(clarity.model_dump()) == clarity


def test_06_sfx_recommendation_serializes() -> None:
    sfx = _recommendation().sfx_recommendation
    assert BobaSfxRecommendationV1.model_validate(sfx.model_dump()) == sfx


def test_07_audio_risk_review_serializes() -> None:
    review = _recommendation().audio_risk_review
    assert BobaAudioRiskReviewV1.model_validate(review.model_dump()) == review


def test_08_score_serializes() -> None:
    score = _recommendation().recommendation_score
    assert BobaMusicMoodScoreV1.model_validate(score.model_dump()) == score


def test_09_brief_enhancement_serializes() -> None:
    enhancement = _recommendation().brief_enhancement
    assert (
        BobaMusicMoodBriefEnhancementV1.model_validate(enhancement.model_dump())
        == enhancement
    )
    assert enhancement.apply_suggestion is False


def test_10_signal_usage_serializes() -> None:
    usage = _result().signal_usage
    assert BobaMusicMoodSignalUsageV1.model_validate(usage.model_dump()) == usage


def test_11_motivational_clip_gets_motivational_mood() -> None:
    assert _recommendation("motivational_clip").music_mood.primary_mood in {
        "motivational",
        "inspiring",
        "heroic",
    }


def test_12_emotional_clip_gets_emotional_mood() -> None:
    assert _recommendation("strong_emotional").music_mood.primary_mood in {
        "emotional",
        "cinematic",
        "minimal",
    }


def test_13_educational_clip_gets_clean_mood() -> None:
    assert _recommendation().music_mood.primary_mood in {
        "educational_clean",
        "minimal",
    }


def test_14_tense_clip_gets_tense_mood() -> None:
    assert _recommendation("tense_clip").music_mood.primary_mood in {
        "tense",
        "suspenseful",
        "mysterious",
    }


def test_15_funny_clip_gets_funny_or_upbeat_mood() -> None:
    assert _recommendation("funny_clip").music_mood.primary_mood in {
        "funny",
        "upbeat",
    }


def test_16_serious_speech_heavy_clip_prioritizes_clarity() -> None:
    clarity = _recommendation("serious_speech").speech_clarity_plan
    assert clarity.speech_priority in {"high", "critical"}
    assert "speech" in clarity.ducking_guidance.casefold()


def test_17_weak_evidence_clip_gets_conservative_warning() -> None:
    recommendation = _recommendation("weak_hook")
    assert recommendation.music_mood.primary_mood in {"minimal", "no_music"}
    assert any("weak" in warning.casefold() for warning in recommendation.warnings)


def test_18_emotional_clip_avoids_heavy_sfx() -> None:
    assert _recommendation(
        "strong_emotional"
    ).sfx_recommendation.sfx_intensity in {"none", "light"}


def test_19_high_energy_hook_allows_light_or_moderate_sfx() -> None:
    assert _recommendation("funny_clip").sfx_recommendation.sfx_intensity in {
        "light",
        "moderate",
    }


def test_20_ducking_guidance_always_exists() -> None:
    assert all(
        item.speech_clarity_plan.ducking_guidance
        and "duck" in item.speech_clarity_plan.ducking_guidance.casefold()
        for item in _result().recommendations
    )


def test_21_silence_moments_are_preserved_when_needed() -> None:
    emotional = _recommendation("strong_emotional")
    assert emotional.audio_energy_map.silence_moments
    assert any(
        "preserve" in item.casefold()
        for item in emotional.audio_energy_map.silence_moments
    )


def test_22_rights_review_warning_always_exists() -> None:
    assert all(
        item.audio_risk_review.rights_review_required
        and "rights review" in item.brief_enhancement.rights_review_warning.casefold()
        for item in _result().recommendations
    )


def test_23_no_track_names_are_generated() -> None:
    payload = _result().model_dump(mode="json")
    keys = _forbidden_keys(payload)
    assert not {
        "track",
        "track_name",
        "music_asset",
        "selected_asset",
        "filename",
    } & keys
    encoded = json.dumps(payload).casefold()
    assert "copyright safety" not in encoded


def test_24_no_file_paths_are_generated() -> None:
    payload = _result().model_dump(mode="json")
    keys = _forbidden_keys(payload)
    assert not {"path", "file_path", "url"} & keys
    encoded = json.dumps(payload).casefold()
    assert "://" not in encoded
    assert "\\\\" not in encoded
    assert not any(
        extension in encoded
        for extension in (".mp3", ".wav", ".m4a", ".flac", ".aac")
    )


def test_25_scores_are_clamped_to_valid_range() -> None:
    for recommendation in _result().recommendations:
        for value in recommendation.recommendation_score.model_dump().values():
            assert 0.0 <= value <= 100.0


def test_26_brief_enhancement_does_not_mutate_original_brief() -> None:
    inputs = build_synthetic_music_mood_inputs("proj_music_no_mutation")
    briefs = inputs["clip_briefs"]
    before = briefs.model_dump_json()
    result = BobaMusicMoodBrainV1().analyze_from_signals(
        "proj_music_no_mutation",
        inputs["signals"],
        clip_briefs=briefs,
        hook_retention=inputs["hook_retention"],
        caption_motion=inputs["caption_motion"],
        creative_direction_v2=inputs["creative_direction_v2"],
        editorial_decisions=inputs["editorial_decisions"],
        clip_ranking=inputs["clip_ranking"],
        candidate_discovery=inputs["candidate_discovery"],
        whole_video_understanding=inputs["whole_video_understanding"],
        explanations=inputs["explanations"],
        audio_signals=inputs["audio_signals"],
        silence_signals=inputs["silence_signals"],
        music_manifest_metadata=inputs["music_manifest_metadata"],
        memory=inputs["memory"],
    )
    assert all(
        item.brief_enhancement.apply_suggestion is False
        for item in result.recommendations
    )
    assert briefs.model_dump_json() == before


def test_27_missing_clip_briefs_fail_clearly() -> None:
    with pytest.raises(ValidationError, match="requires saved clip briefs"):
        BobaMusicMoodBrainV1().analyze(
            project_id="proj_music_missing_briefs",
            clip_briefs=None,
        )


def test_28_missing_optional_artifacts_degrade_gracefully() -> None:
    inputs = build_synthetic_music_mood_inputs("proj_music_fallback")
    result = BobaMusicMoodBrainV1().analyze(
        project_id="proj_music_fallback",
        clip_briefs=inputs["clip_briefs"],
    )
    assert result.recommendations
    assert result.signal_usage.fallback_used is True
    assert "hook_retention" in result.signal_usage.unavailable_signals


def test_29_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    result = store.save_music_mood(_result())
    path = store.music_mood_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(f"projects/{PROJECT_ID}/music_mood/index.json")
    assert store.load_music_mood(PROJECT_ID) == result
    assert payload["schema_version"] == "boba_music_mood_brain_v1"
    encoded = json.dumps(payload)
    assert "transcript_segments" not in encoded
    assert '"raw_media"' not in encoded


def test_30_api_routes_return_saved_artifact_and_frontend_exposes_it(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    inputs = build_synthetic_music_mood_inputs(PROJECT_ID)
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    store.save_clip_briefs(inputs["clip_briefs"])
    store.save_hook_retention(inputs["hook_retention"])
    store.save_caption_motion(inputs["caption_motion"])
    store.save_creative_direction_v2(inputs["creative_direction_v2"])
    store.save_whole_video_understanding(inputs["whole_video_understanding"])
    store.save_candidate_clip_discovery(inputs["candidate_discovery"])
    store.save_clip_ranking(inputs["clip_ranking"])
    store.save_editorial_decisions(inputs["editorial_decisions"])
    store.save_explanations(inputs["explanations"])
    store.save_project_memory(inputs["memory"])
    integration = BobaIntegration(storage, store)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        created = client.post(f"/api/v1/boba/projects/{PROJECT_ID}/music-mood")
        saved = client.get(f"/api/v1/boba/projects/{PROJECT_ID}/music-mood")
    assert created.status_code == 200, created.text
    assert saved.status_code == 200, saved.text
    assert created.json()["recommendations"] == saved.json()["recommendations"]
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Music Mood Brain V1" in panel
    assert "Audio energy map and risks" in panel
    assert "Not applied automatically." in panel


def test_31_validator_self_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_music_mood.py"),
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


def test_32_validator_synthetic_project_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_music_mood.py"),
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"motivational_mood_valid": true' in result.stdout.casefold()
    assert '"weak_evidence_fallback_valid": true' in result.stdout.casefold()
    assert '"artifact_persisted": true' in result.stdout.casefold()


def test_33_generation_does_not_trigger_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = build_synthetic_music_mood_inputs("proj_music_no_render")

    def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rendering or subprocess execution is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    result = BobaMusicMoodBrainV1().analyze(
        project_id="proj_music_no_render",
        clip_briefs=inputs["clip_briefs"],
    )
    assert result.recommendations


def test_34_generation_makes_no_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = build_synthetic_music_mood_inputs("proj_music_no_network")

    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "socket", fail_network)
    result = BobaMusicMoodBrainV1().analyze_from_signals(
        "proj_music_no_network",
        inputs["signals"],
        clip_briefs=inputs["clip_briefs"],
        hook_retention=inputs["hook_retention"],
        caption_motion=inputs["caption_motion"],
    )
    assert result.recommendations


def test_35_no_reports_or_media_are_staged() -> None:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    staged = {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    }
    forbidden_prefixes = (
        "work/",
        "storage_data/",
        "media/",
        ".venv/",
        "frontend/node_modules/",
        "frontend/.next/",
    )
    forbidden_suffixes = (".mp4", ".mov", ".mkv", ".wav", ".mp3")
    assert not any(
        path.startswith(forbidden_prefixes) or path.casefold().endswith(forbidden_suffixes)
        for path in staged
    )

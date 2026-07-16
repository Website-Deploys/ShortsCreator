"""Creator Personalization V2 contract, safety, integration, API, and CLI tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.dependencies import (
    personalization_service_provider,
    project_service_provider,
)
from olympus.editing.captions import build_caption_intelligence
from olympus.editing.motion import build_motion_intelligence
from olympus.integration.clip_intelligence import unified_clip_intelligence
from olympus.metadata import UPLOAD_METADATA_V2_VERSION
from olympus.metadata.generator import generate_upload_metadata
from olympus.music.intelligence import plan_music_intelligence
from olympus.optimization.analyzers import UploadMetadataV2Analyzer
from olympus.optimization.pipeline import OPTIMIZATION_PIPELINE_VERSION
from olympus.personalization import (
    ClipFeedbackV2,
    CreatorPersonalizationService,
    CreatorProfileV2,
    PersonalizationAppliedV2,
    ProfileStore,
    apply_editing_personalization,
    apply_planning_personalization,
    caption_personalization,
    motion_personalization,
    music_personalization,
    preset_names,
    profile_directives,
    profile_from_preset,
)
from olympus.platform.errors import ValidationError
from olympus.rendering.ffmpeg_renderer import _render_metadata
from olympus.rendering.stages import GenerateRenderManifestStage


@pytest.fixture
def personalization_service(tmp_path: Path) -> CreatorPersonalizationService:
    return CreatorPersonalizationService(
        ProfileStore(tmp_path / "personalization"),
        conservative_until_feedback_count=5,
    )


def test_contracts_serialize_with_safe_privacy_defaults() -> None:
    profile = profile_from_preset("balanced_default", profile_id="creator")
    feedback = ClipFeedbackV2(
        feedback_id="feedback_one",
        profile_id=profile.profile_id,
        project_id="project_one",
        clip_id="clip_one",
        rating={"overall": "like"},
    )
    applied = PersonalizationAppliedV2(
        profile_id=profile.profile_id,
        profile_name=profile.profile_name,
        applied=True,
        affected_systems=["planning"],
    )

    assert CreatorProfileV2.model_validate_json(profile.model_dump_json()) == profile
    assert ClipFeedbackV2.model_validate_json(feedback.model_dump_json()) == feedback
    assert PersonalizationAppliedV2.model_validate_json(applied.model_dump_json()) == applied
    assert profile.privacy.local_only is True
    assert profile.privacy.no_sensitive_data is True
    assert profile.privacy.no_cloud_sync is True
    assert profile.learning.enabled is False
    assert profile.learning.explicit_feedback_only is True


def test_all_explainable_presets_are_available_and_editable() -> None:
    expected = {
        "balanced_default",
        "viral_storyteller",
        "clean_podcast",
        "motivational_shorts",
        "music_performance",
        "gaming_reactive",
        "education_clarity",
    }
    assert set(preset_names()) == expected
    for preset in expected:
        profile = profile_from_preset(
            preset,
            profile_id=f"profile_{preset}",
            profile_name=f"Custom {preset}",
        )
        profile.caption_preferences.max_words_per_line = 4
        assert profile.preset_id == preset
        assert profile.caption_preferences.max_words_per_line == 4


def test_local_store_create_activate_update_export_import_and_reset(
    personalization_service: CreatorPersonalizationService,
) -> None:
    service = personalization_service
    default = service.initialize()
    podcast = service.create_profile(
        "clean_podcast",
        profile_name="My Podcast",
        learning_enabled=True,
        activate=True,
    )
    assert service.store.get_active_profile().profile_id == podcast.profile_id  # type: ignore[union-attr]
    updated = service.update_profile(
        podcast.profile_id,
        {
            "caption_preferences": {"highlight_density": 0.2},
            "upload_metadata_preferences": {"title_style": "clear"},
        },
    )
    assert updated.caption_preferences.highlight_density == 0.2
    exported = service.export_profile(podcast.profile_id)
    imported = service.import_profile(exported["profile"])
    assert imported.profile_id != podcast.profile_id
    assert imported.profile_name.endswith("(Imported)")
    reset = service.reset_profile(podcast.profile_id)
    assert reset.learning.enabled is False
    assert reset.learning.total_feedback_count == 0
    assert {item.profile_id for item in service.list_profiles()} >= {
        default.profile_id,
        podcast.profile_id,
        imported.profile_id,
    }
    assert not list(service.store.root.rglob("*.tmp"))
    assert list(service.store.backups_dir.glob("*.json"))


def test_store_rejects_secrets_long_notes_transcripts_and_immutable_privacy(
    personalization_service: CreatorPersonalizationService,
) -> None:
    service = personalization_service
    profile = service.initialize()
    with pytest.raises(ValidationError):
        service.update_profile(profile.profile_id, {"privacy": {"local_only": False}})
    with pytest.raises(ValidationError):
        service.update_profile(
            profile.profile_id,
            {"channel_context": {"target_audience_notes": "api_key=not-allowed"}},
        )
    with pytest.raises(ValidationError):
        service.record_feedback(
            profile_id=profile.profile_id,
            project_id="project",
            clip_id="clip",
            rating="like",
            notes="x" * 501,
        )
    with pytest.raises(ValidationError):
        service.store.import_profile(
            {
                **profile.model_dump(mode="json"),
                "channel_context": {
                    **profile.channel_context.model_dump(mode="json"),
                    "target_audience_notes": "word " * 300,
                },
            }
        )


def test_feedback_is_explicit_only_and_learning_is_gradual(
    personalization_service: CreatorPersonalizationService,
) -> None:
    service = personalization_service
    profile = service.initialize()
    disabled = service.record_feedback(
        profile_id=profile.profile_id,
        project_id="project",
        clip_id="disabled",
        rating="like",
        labels=["make_more_like_this"],
        clip_traits={"hook_category": "curiosity_gap"},
    )
    after_disabled = service.get_profile(profile.profile_id)
    assert disabled.applied_to_profile is False
    assert after_disabled.learning.total_feedback_count == 1
    assert after_disabled.learned_patterns.liked_hook_categories == []

    service.update_profile(profile.profile_id, {"learning": {"enabled": True}})
    before_motion = service.get_profile(profile.profile_id).motion_preferences.intensity
    enabled = service.record_feedback(
        profile_id=profile.profile_id,
        project_id="project",
        clip_id="enabled",
        rating={"overall": "dislike", "motion": "dislike"},
        labels=["avoid_in_future", "too_much_motion", "title_bad"],
        notes="Explicit short feedback only.",
        clip_traits={
            "hook_category": "generic",
            "title_pattern": "context",
            "motion_style": "gaming_reactive",
            "clip_traits": ["low_context"],
        },
    )
    after_enabled = service.get_profile(profile.profile_id)
    assert enabled.applied_to_profile is True
    assert after_enabled.learned_patterns.disliked_hook_categories == ["generic"]
    assert after_enabled.learned_patterns.disliked_title_patterns == ["context"]
    assert 0 < before_motion - after_enabled.motion_preferences.intensity <= 0.03
    assert after_enabled.learning.confidence <= 0.2


def test_safe_learned_traits_change_future_recommendations(
    personalization_service: CreatorPersonalizationService,
) -> None:
    service = personalization_service
    profile = service.create_profile(
        "balanced_default",
        learning_enabled=True,
        activate=True,
    )
    feedback = service.record_feedback(
        profile_id=profile.profile_id,
        project_id="project",
        clip_id="liked_clip",
        rating={
            "overall": "like",
            "hook": "like",
            "captions": "like",
            "music": "like",
            "motion": "dislike",
            "title_metadata": "like",
        },
        labels=["make_more_like_this", "captions_good", "music_good", "title_good"],
        clip_traits={
            "hook_category": "curiosity_gap",
            "title_pattern": "emotional",
            "caption_style": "bold_hook",
            "music_mood": "motivational",
            "motion_style": "gaming_reactive",
            "clip_traits": ["complete_story"],
        },
    )
    learned = feedback.extracted_safe_learning
    assert learned.liked_caption_styles == ["bold_hook"]
    assert learned.liked_music_moods == ["motivational"]
    assert learned.disliked_motion_styles == ["gaming_reactive"]
    assert learned.liked_motion_styles == []

    updated = service.get_profile(profile.profile_id)
    assert 0 < updated.caption_preferences.weights["feedback"] <= 0.03
    assert 0 < updated.music_preferences.weights["feedback"] <= 0.03
    assert -0.03 <= updated.motion_preferences.weights["feedback"] < 0
    assert 0 < updated.upload_metadata_preferences.weights["feedback"] <= 0.03
    directives = profile_directives(updated)

    captions = caption_personalization(
        directives,
        default_style="default_clean",
        default_max_words=5,
    )
    music = music_personalization(
        directives,
        target_mood="neutral",
        gain_db=-18.0,
        source_is_music=False,
    )
    scores, evidence = apply_planning_personalization(
        {
            "emotion": 0.5,
            "payoff": 0.5,
            "hook": 0.5,
            "story_completion": 0.5,
            "story": 0.5,
            "clarity": 0.5,
            "retention": 0.5,
        },
        {
            "safety_status": "low",
            "clip_traits": ["complete_story"],
            "story_v2_guidance": {"context_risk": 0.1},
            "v2_candidate_metadata": {
                "hook_analysis": {"category": "curiosity_gap"}
            },
        },
        directives,
        max_score_delta=0.15,
    )
    assert captions["style"] == "bold_hook"
    assert music["target_mood"] == "motivational"
    assert scores["hook"] > 0.5
    assert scores["retention"] > 0.5
    assert any("Explicit feedback" in item["reason"] for item in evidence["adjustments"])


def test_planning_personalization_is_bounded_and_never_boosts_unsafe_clips() -> None:
    profile = profile_from_preset("motivational_shorts", profile_id="motivational")
    directives = profile_directives(profile)
    scores = {
        "emotion": 0.5,
        "payoff": 0.5,
        "hook": 0.5,
        "story_completion": 0.5,
        "story": 0.5,
        "clarity": 0.5,
        "retention": 0.5,
    }
    candidate = {
        "safety_status": "low",
        "story_v2_guidance": {"context_risk": 0.1},
        "v2_candidate_metadata": {"hook_analysis": {"category": "curiosity_gap"}},
    }
    personalized, evidence = apply_planning_personalization(
        scores,
        candidate,
        directives,
        max_score_delta=0.15,
    )
    assert personalized["emotion"] > scores["emotion"]
    assert personalized["hook"] > scores["hook"]
    assert all(
        abs(float(item.get("delta") or 0.0)) <= 0.15
        for item in evidence["adjustments"]
    )

    unsafe, unsafe_evidence = apply_planning_personalization(
        scores,
        {**candidate, "safety_status": "blocked"},
        directives,
        max_score_delta=0.15,
    )
    assert unsafe == scores
    assert any(item["applied"] is False for item in unsafe_evidence["adjustments"])
    assert unsafe_evidence["warnings"]


def test_editing_and_caption_profiles_change_real_decisions_with_safety_caps() -> None:
    baseline = {
        "style": "balanced_default",
        "pacing": "balanced",
        "zoom_frequency": "medium",
        "sfx_density": "low",
        "transition_style": "subtle",
    }
    podcast = profile_directives(profile_from_preset("clean_podcast", profile_id="podcast"))
    motivational = profile_directives(
        profile_from_preset("motivational_shorts", profile_id="motivational")
    )
    podcast_edit, _ = apply_editing_personalization(baseline, podcast)
    motivational_edit, _ = apply_editing_personalization(baseline, motivational)
    assert podcast_edit["sfx_density"] == "minimal"
    assert podcast_edit["transition_style"] == "clean_cut"
    assert motivational_edit["pacing"] == "fast"
    assert motivational_edit["zoom_frequency"] == "medium_high"

    events, intelligence = build_caption_intelligence(
        clip={"clip_id": "clip", "duration": 3.0},
        events=[
            {
                "id": "caption_1",
                "text": "This mindset changes everything",
                "start": 0.0,
                "end": 2.0,
                "timing_source": "word_level",
            }
        ],
        timing_quality={"source": "word_level", "quality_level": "word"},
        blueprint={
            "personalization_directives_v2": motivational,
            "hook_v2": {
                "category": "curiosity_gap",
                "hook_line": "This mindset changes everything",
            },
            "story_v2_guidance": {"payoff": "changes everything"},
        },
        face_plan={
            "mode": "center_fallback",
            "input_analysis": {
                "face_tracking_available": True,
                "detected_face_count": 0,
            },
        },
        project_id="project",
        captions_enabled=True,
    )
    assert events[0]["style"] == "motivational_impact"
    assert events[0]["uppercase"] is True
    assert intelligence["timing_plan"]["max_words_per_line"] == 4
    assert intelligence["caption_personalization"]["applied"] is True

    bounded = caption_personalization(
        {
            **motivational,
            "captions": {**motivational["captions"], "max_words_per_line": 99},
        },
        default_style="default_clean",
        default_max_words=5,
    )
    assert bounded["max_words_per_line"] == 8


def test_music_profile_respects_source_performance_protection() -> None:
    directives = profile_directives(
        profile_from_preset("motivational_shorts", profile_id="motivational")
    )
    direct = music_personalization(
        directives,
        target_mood="neutral",
        gain_db=-18.0,
        source_is_music=False,
    )
    assert direct["target_mood"] == "motivational"
    assert direct["gain_db"] == -16.0
    assert direct["applied"] is True

    planned = plan_music_intelligence(
        clip={"clip_id": "performance", "duration": 20.0},
        blueprint={
            "content_niche": {"primary": "music_performance"},
            "personalization_directives_v2": directives,
        },
        bundle={"caption_timing": {"captions": []}, "silence_detection": {"silences": []}},
        project_id="project",
    )
    assert planned["decision"]["should_use_music"] is False
    assert planned["decision"]["disabled_reason"] == "source_is_music_performance"
    assert any(
        "protection overrides" in warning
        for warning in planned["music_personalization"]["warnings"]
    )


def test_motion_personalization_never_fakes_motion_when_face_safety_fails() -> None:
    directives = profile_directives(
        profile_from_preset("motivational_shorts", profile_id="motivational")
    )
    direct = motion_personalization(
        directives,
        style="default_clean",
        intensity=0.5,
    )
    assert direct["style"] == "motivational_dynamic"
    assert direct["intensity"] == 0.62

    intelligence = build_motion_intelligence(
        clip={"clip_id": "clip", "duration": 12.0},
        blueprint={
            "personalization_directives_v2": directives,
            "content_niche": {"primary": "motivational"},
            "hook_v2": {"category": "curiosity_gap"},
            "story_v2_guidance": {"story_shape": "problem_solution"},
        },
        caption_intelligence={
            "caption_safe_zone": {"strategy": "bottom_safe", "collision_risk": "low"}
        },
        music_intelligence={"decision": {"music_role": "motivational_drive"}},
        face_plan={
            "mode": "single_face_tracking",
            "fallback_reason": "low_confidence_faces",
            "crop_keyframes": [],
        },
        sfx_plan={"enabled": False, "effects": []},
        project_id="project",
    )
    assert intelligence["decision"]["should_apply_motion"] is False
    assert intelligence["decision"]["disabled_reason"] == "face_tracking_unstable"
    assert intelligence["effect_plan"]["effects"] == []
    assert (
        intelligence["motion_personalization"]["disabled_or_limited_reason"]
        == "face_tracking_unstable"
    )


def test_upload_metadata_and_unified_truth_preserve_personalization() -> None:
    profile = profile_from_preset("motivational_shorts", profile_id="motivational")
    profile.upload_metadata_preferences.banned_hashtags = ["General"]
    profile.upload_metadata_preferences.preferred_hashtags = ["#Motivational"]
    directives = profile_directives(profile)
    metadata = generate_upload_metadata(
        project_id="project",
        clip_id="clip",
        unified_clip_intelligence={
            "story": {
                "story_shape": "problem_solution",
                "payoff": "A practical motivational mindset shift",
            },
            "virality": {
                "hook_line": "Why this motivational mindset shift matters",
                "hook_category": "curiosity_gap",
                "overall_score": 0.82,
            },
            "trend_research": {
                "niche": "motivational",
                "matched_patterns": [{"label": "clear_takeaway"}],
                "confidence": 0.7,
            },
            "copyright_safety": {
                "risk_level": "low",
                "upload_readiness": "ready_with_low_risk",
                "manual_review_required": False,
            },
        },
        timeline={
            "metadata": {
                "personalization_directives_v2": directives,
                "title": "Motivational mindset",
            }
        },
    )
    personalization = metadata["upload_metadata_personalization"]
    all_tags = {
        tag
        for platform in ("youtube_shorts", "instagram_reels", "tiktok")
        for tag in metadata[platform]["hashtags"]
    }
    assert personalization["profile_id"] == profile.profile_id
    assert personalization["title_style"] == "emotional"
    assert "#General" not in all_tags
    assert "copyright safe" not in metadata["universal"]["best_title"].lower()
    assert "guaranteed viral" not in metadata["universal"]["best_title"].lower()

    unified = unified_clip_intelligence(
        clip={"clip_id": "clip", "start": 2.0, "end": 14.0},
        plan={"id": "plan", "blueprint": {}},
        render_metadata={
            "personalization_applied_v2": {
                "profile_id": profile.profile_id,
                "profile_name": profile.profile_name,
                "applied": True,
                "confidence": 0.4,
                "affected_systems": ["planning", "captions"],
                "adjustments": [
                    {
                        "system": "captions",
                        "field": "style",
                        "value": "motivational_impact",
                        "reason": "Explicit profile caption preference.",
                        "applied": True,
                    }
                ],
                "warnings": ["Motion limited by face safety."],
                "reasons": ["Applied explicit creator preferences."],
            },
            "upload_metadata_v2": metadata,
        },
        render_output={"clip_id": "clip", "output_key": "renders/clip.mp4"},
    )
    assert unified["personalization"]["applied"] is True
    assert unified["personalization"]["profile_name"] == "Motivational Shorts"
    assert unified["personalization"]["key_adjustments"][0]["system"] == "captions"
    assert unified["personalization"]["warnings"]


def test_render_metadata_publishes_personalization_truth_and_current_versions() -> None:
    application = {
        "profile_id": "motivational",
        "profile_name": "Motivational Shorts",
        "applied": True,
        "confidence": 0.3,
        "affected_systems": ["editing", "captions"],
        "adjustments": [
            {
                "system": "captions",
                "field": "style",
                "value": "motivational_impact",
                "reason": "Explicit profile caption preference.",
                "applied": True,
            }
        ],
        "warnings": [],
        "reasons": ["Applied explicit creator preferences."],
    }
    metadata = _render_metadata(
        {
            "clip_id": "clip",
            "duration": 5.0,
            "source_start": 0.0,
            "source_end": 5.0,
            "tracks": [],
            "metadata": {
                "editing_v2": {
                    "personalization_applied_v2": application,
                    "voice_enhancement_plan": {},
                    "video_enhancement_plan": {},
                    "caption_style": {},
                },
                "render_assets_v2": {},
            },
        },
        [],
        {
            "format": {"duration": "5.0"},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "5.0",
                    "width": 1080,
                    "height": 1920,
                },
                {"codec_type": "audio", "duration": "5.0"},
            ],
        },
    )
    assert metadata["personalization_applied_v2"] == application
    assert metadata["unified_clip_intelligence"]["personalization"]["applied"] is True
    assert GenerateRenderManifestStage.version == "11"
    assert UploadMetadataV2Analyzer.version == "2"
    assert UPLOAD_METADATA_V2_VERSION == "2"
    assert OPTIMIZATION_PIPELINE_VERSION == "3"


class _FakeProjects:
    async def get(self, project_id: str) -> dict[str, str]:
        if project_id != "project_one":
            raise AssertionError("unexpected project")
        return {"id": project_id}


def test_personalization_api_routes_validate_and_store_explicit_feedback(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    service = CreatorPersonalizationService(ProfileStore(tmp_path / "api-personalization"))
    app.dependency_overrides[personalization_service_provider] = lambda: service
    app.dependency_overrides[project_service_provider] = _FakeProjects
    with TestClient(app) as client:
        listed = client.get("/api/v1/personalization/profiles")
        assert listed.status_code == 200
        assert listed.json()["active_profile_id"] == "default"

        created = client.post(
            "/api/v1/personalization/profiles",
            json={
                "preset_id": "clean_podcast",
                "profile_name": "API Podcast",
                "learning_enabled": True,
                "activate": True,
            },
        )
        assert created.status_code == 201
        profile_id = created.json()["profile_id"]

        updated = client.patch(
            f"/api/v1/personalization/profiles/{profile_id}",
            json={"updates": {"caption_preferences": {"highlight_density": 0.2}}},
        )
        assert updated.status_code == 200
        assert updated.json()["caption_preferences"]["highlight_density"] == 0.2

        feedback = client.post(
            "/api/v1/personalization/feedback",
            json={
                "profile_id": profile_id,
                "project_id": "project_one",
                "clip_id": "clip_one",
                "rating": {"overall": "like", "captions": "like"},
                "labels": ["make_more_like_this", "captions_good"],
                "notes": "Explicit API feedback.",
                "clip_traits": {
                    "hook_category": "curiosity_gap",
                    "caption_style": "clean_podcast",
                },
            },
        )
        assert feedback.status_code == 201
        assert feedback.json()["applied_to_profile"] is True

        invalid = client.post(
            "/api/v1/personalization/feedback",
            json={
                "profile_id": profile_id,
                "project_id": "project_one",
                "clip_id": "clip_one",
                "rating": {"overall": "like"},
                "labels": ["track_view_without_consent"],
            },
        )
        assert invalid.status_code == 422


def _run_cli(*arguments: str) -> tuple[int, dict[str, Any]]:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "validate_creator_personalization.py"),
            *arguments,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.returncode, json.loads(completed.stdout)[
        "creator_personalization_validation_v2"
    ]


def test_cli_self_check_simulation_feedback_export_and_reset(tmp_path: Path) -> None:
    code, self_check = _run_cli("--self-check")
    assert code == 0
    assert self_check["passed"] is True
    assert all(self_check["privacy_checks"].values())

    code, simulation = _run_cli(
        "--simulate",
        "--profile",
        "motivational_shorts",
        "--niche",
        "motivational",
    )
    assert code == 0
    assert set(simulation["affected_systems"]) == {
        "planning",
        "editing",
        "captions",
        "music",
        "motion",
        "upload_metadata",
    }

    code, feedback = _run_cli(
        "--simulate-feedback",
        "--rating",
        "like",
        "--labels",
        "make_more_like_this,title_good",
    )
    assert code == 0
    assert feedback["feedback_recorded"] is True
    assert feedback["feedback_applied"] is True

    storage = tmp_path / "cli-store"
    code, created = _run_cli(
        "--create-profile",
        "clean_podcast",
        "--storage-dir",
        str(storage),
    )
    assert code == 0
    assert created["profile_name"] == "Clean Podcast"

    code, exported = _run_cli(
        "--export-profile",
        "default",
        "--storage-dir",
        str(storage),
    )
    assert code == 0
    assert exported["exported_file"].endswith(".json")

    code, reset = _run_cli(
        "--reset-profile",
        "default",
        "--confirm",
        "--storage-dir",
        str(storage),
    )
    assert code == 0
    assert reset["learning_enabled"] is False

"""Tests for the configuration layer."""

from __future__ import annotations

from olympus.platform.config import Settings
from olympus.platform.config.settings import Environment, StorageBackend


def test_defaults_are_sane() -> None:
    """A freshly constructed Settings object has safe development defaults."""

    settings = Settings()
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.storage.backend is StorageBackend.LOCAL
    assert settings.api.port == 8000
    assert settings.link_ingestion.enabled is True
    assert settings.link_ingestion.allowed_platforms_list == ["youtube"]
    assert settings.link_ingestion.allow_direct_media_urls is False
    assert settings.link_ingestion.allow_playlists is False
    assert settings.link_ingestion.require_user_rights_confirmation is True
    assert settings.music_intelligence.enabled is True
    assert settings.music_intelligence.require_license_verified is True
    assert settings.music_intelligence.allow_unknown_license is False
    assert settings.music_intelligence.enable_ducking is True
    assert settings.music_intelligence.max_music_gain_db == -14.0
    assert settings.multi_speaker_layout.enabled is True
    assert settings.multi_speaker_layout.prefer_two_speaker_stack is True
    assert settings.multi_speaker_layout.minimum_face_confidence == 0.55
    assert settings.multi_speaker_layout.minimum_association_confidence == 0.60
    assert settings.caption_intelligence.enabled is True
    assert settings.caption_intelligence.prefer_word_level is True
    assert settings.caption_intelligence.allow_estimated_word_timing is True
    assert settings.caption_intelligence.enable_caption_render_validation is True
    assert settings.caption_fonts.primary == "Arial"
    assert settings.caption_fonts.allow_custom_font_paths is False
    assert settings.motion_graphics.enabled is True
    assert settings.motion_graphics.enable_speed_ramps is False
    assert settings.motion_graphics.enable_safe_flash is False
    assert settings.motion_graphics.max_zoom_scale == 1.18
    assert settings.upload_metadata.enabled is True
    assert settings.upload_metadata.max_title_length == 70
    assert settings.upload_metadata.max_youtube_hashtags == 8
    assert settings.upload_metadata.max_instagram_hashtags == 12
    assert settings.upload_metadata.block_misleading_claims is True
    assert settings.upload_metadata.block_spam_hashtags is True
    assert settings.creator_personalization.enabled is True
    assert settings.creator_personalization.learning_enabled_by_default is False
    assert settings.creator_personalization.explicit_feedback_only is True
    assert settings.creator_personalization.active_profile_id == "default"
    assert settings.creator_personalization.storage_dir == "work/personalization"
    assert settings.creator_personalization.max_feedback_notes_chars == 500
    assert settings.creator_personalization.max_profiles == 20
    assert settings.creator_personalization.apply_to_planning is True
    assert settings.creator_personalization.apply_to_editing is True
    assert settings.creator_personalization.apply_to_music is True
    assert settings.creator_personalization.apply_to_captions is True
    assert settings.creator_personalization.apply_to_motion is True
    assert settings.creator_personalization.apply_to_upload_metadata is True
    assert settings.creator_personalization.max_score_delta == 0.15
    assert settings.creator_personalization.conservative_until_feedback_count == 5
    assert settings.creator_personalization.allow_export_import is True
    assert settings.is_production is False


def test_cors_origins_parsed_from_csv() -> None:
    """CORS origins provided as a comma-separated string parse into a list."""

    settings = Settings(api={"cors_origins": "http://a.com, http://b.com"})
    assert settings.api.cors_origins_list == ["http://a.com", "http://b.com"]


def test_production_flag() -> None:
    """The production helper reflects the environment."""

    settings = Settings(environment=Environment.PRODUCTION)
    assert settings.is_production is True

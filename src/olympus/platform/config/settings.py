"""Typed, validated application settings.

Configuration is loaded from environment variables (and an optional ``.env``
file in development) into strongly-typed, validated models using
``pydantic-settings``. This gives us:

- a single source of truth for configuration,
- validation at startup (the app fails loudly on misconfiguration rather than
  failing silently later - per the Constitution),
- no secrets in code.

All variables are prefixed with ``OLYMPUS_`` and nested groups use ``__`` as a
delimiter, e.g. ``OLYMPUS_DATABASE__URL``.

Settings are accessed exclusively through :func:`get_settings`, which is cached
so the environment is parsed once per process.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environments. Behaviour (logging, docs exposure) keys off this."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    """Log rendering format. ``console`` for humans, ``json`` for machines."""

    CONSOLE = "console"
    JSON = "json"


class ApiSettings(BaseModel):
    """HTTP API server settings."""

    host: str = "0.0.0.0"
    port: int = 8000
    # Origins permitted by CORS, stored as a comma-separated string. Kept as a
    # plain string (rather than list) so it loads cleanly from a single
    # environment variable; use :attr:`cors_origins_list` to get the parsed list.
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """The configured CORS origins, parsed into a list."""

        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


class DatabaseSettings(BaseModel):
    """PostgreSQL connection settings (async driver)."""

    url: str = "postgresql+asyncpg://olympus:olympus@localhost:5432/olympus"
    pool_size: int = 5
    max_overflow: int = 10
    # Emit SQL to the logs (development debugging only).
    echo: bool = False


class RedisSettings(BaseModel):
    """Redis settings (caching and ephemeral state)."""

    url: str = "redis://localhost:6379/0"


class QueueSettings(BaseModel):
    """Celery broker / result backend settings."""

    broker_url: str = "redis://localhost:6379/1"
    result_backend: str = "redis://localhost:6379/2"
    # Hard ceiling on task runtime to prevent runaway jobs (seconds).
    task_time_limit: int = 60 * 30


class StorageBackend(StrEnum):
    """Selectable storage adapters."""

    LOCAL = "local"
    S3 = "s3"


class StorageSettings(BaseModel):
    """Storage abstraction settings.

    Defaults to the ``local`` backend so the application starts with no cloud
    credentials. The ``s3`` backend is selected explicitly in deployed
    environments.
    """

    backend: StorageBackend = StorageBackend.LOCAL
    local_root: str = "./storage_data"
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None


class AiSettings(BaseModel):
    """AI service abstraction settings.

    ``noop`` providers let the application start and run end-to-end wiring tests
    without any model weights. Real providers (e.g. ``faster-whisper``) are
    selected in deployed environments via ``OLYMPUS_AI__TRANSCRIPTION_PROVIDER``.
    """

    transcription_provider: str = "noop"

    # --- faster-whisper provider tuning (only used when the provider is selected) ---
    # Model size/name (e.g. "tiny", "base", "small", "medium", "large-v3") or a
    # path/HF repo id. "base" balances quality and CPU speed for the foundation.
    whisper_model: str = "base"
    # "auto" picks CUDA when available and falls back to CPU; or force "cpu"/"cuda".
    whisper_device: str = "auto"
    # "auto" -> int8 on CPU, float16 on GPU; or force e.g. "int8"/"float16"/"float32".
    whisper_compute_type: str = "auto"
    # Decoding beam size (higher = more accurate, slower).
    whisper_beam_size: int = 5
    # Optional ISO language hint (e.g. "en"); empty -> auto-detect per audio.
    whisper_language: str | None = None
    # Optional directory to cache downloaded model weights (defaults to HF cache).
    whisper_download_root: str | None = None
    # Hard ceiling (seconds) on a single transcription before it is aborted.
    whisper_timeout_seconds: float = 1800.0


class RenderingSettings(BaseModel):
    """Rendering abstraction settings."""

    backend: str = "ffmpeg"
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    asset_root: str = "./assets"


class LinkIngestionSettings(BaseModel):
    """Safe defaults for public video-link ingestion."""

    enabled: bool = True
    allowed_platforms: str = "youtube"
    max_source_duration_minutes: int = Field(default=120, ge=1)
    max_source_file_size_mb: int = Field(default=4096, ge=1)
    max_height: int = Field(default=1440, ge=144)
    preferred_container: str = "mp4"
    preferred_video_codecs: str = "h264,avc1,vp9,av01"
    preferred_audio_codecs: str = "aac,opus,m4a"
    allow_direct_media_urls: bool = False
    allow_playlists: bool = False
    allow_live_streams: bool = False
    require_user_rights_confirmation: bool = True
    download_timeout_seconds: float = Field(default=7200.0, gt=0)
    metadata_timeout_seconds: float = Field(default=60.0, gt=0)
    cleanup_partial_downloads: bool = True
    report_progress_interval_seconds: float = Field(default=1.0, gt=0)

    @property
    def allowed_platforms_list(self) -> list[str]:
        """Return normalized platform identifiers from the CSV setting."""

        return [item.strip().lower() for item in self.allowed_platforms.split(",") if item.strip()]

    @property
    def preferred_video_codecs_list(self) -> list[str]:
        """Return preferred video codecs in priority order."""

        return [
            item.strip().lower()
            for item in self.preferred_video_codecs.split(",")
            if item.strip()
        ]

    @property
    def preferred_audio_codecs_list(self) -> list[str]:
        """Return preferred audio codecs in priority order."""

        return [
            item.strip().lower()
            for item in self.preferred_audio_codecs.split(",")
            if item.strip()
        ]


class TrendResearchSettings(BaseModel):
    """Safe runtime controls for Internet Trend Research V2."""

    enabled: bool = True
    provider: str = "evergreen"
    allow_official_source_refresh: bool = True
    allow_configured_web_search: bool = False
    allow_live_web_provider: bool = False
    configured_search_endpoint: str | None = None
    configured_search_api_key_env: str = ""
    configured_search_provider_name: str = "custom"
    fetch_configured_result_pages: bool = False
    web_search_endpoint: str | None = None
    web_search_api_key: SecretStr | None = None
    cache_enabled: bool = True
    cache_dir: str = "work/trend_cache"
    max_queries_per_video: int = Field(default=5, ge=1, le=5)
    max_sources_per_snapshot: int = Field(default=12, ge=1, le=12)
    general_ttl_hours: int = Field(default=168, ge=1)
    niche_ttl_hours: int = Field(default=72, ge=1)
    fast_ttl_hours: int = Field(default=24, ge=1)
    stale_cache_allowed_hours: int = Field(default=336, ge=0)
    live_refresh_min_interval_hours: int = Field(default=12, ge=0)
    force_live_refresh: bool = False
    max_fetch_bytes: int = Field(default=250_000, ge=10_000, le=2_000_000)
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    max_redirects: int = Field(default=3, ge=0, le=5)
    user_agent: str = "OlympusTrendResearch/1.0"
    source_allowlist_enabled: bool = True
    allowed_domains: list[str] = Field(
        default_factory=lambda: [
            "youtube.com",
            "support.google.com",
            "blog.youtube",
            "creators.instagram.com",
            "about.instagram.com",
            "newsroom.tiktok.com",
            "ads.tiktok.com",
            "creatoracademy.youtube.com",
        ]
    )
    blocked_domains: list[str] = Field(default_factory=list)
    fallback_to_evergreen: bool = True
    require_source_attribution: bool = True
    recency_window_days: int = Field(default=30, ge=1, le=365)
    language: str = "en"
    region: str | None = None


class MusicIntelligenceSettings(BaseModel):
    """Safe controls for Music Intelligence V2."""

    enabled: bool = True
    require_license_verified: bool = True
    allow_unknown_license: bool = False
    allow_vocal_music_under_speech: bool = False
    default_music_gain_db: float = Field(default=-20.0, ge=-40.0, le=0.0)
    min_music_gain_db: float = Field(default=-32.0, ge=-50.0, le=0.0)
    max_music_gain_db: float = Field(default=-14.0, ge=-40.0, le=0.0)
    enable_ducking: bool = True
    ducking_threshold_db: float = Field(default=-24.0, ge=-60.0, le=0.0)
    ducking_ratio: float = Field(default=6.0, ge=1.0, le=20.0)
    ducking_reduction_db: float = Field(default=6.0, ge=0.0, le=24.0)
    ducking_attack_ms: float = Field(default=120.0, ge=1.0, le=2000.0)
    ducking_release_ms: float = Field(default=450.0, ge=1.0, le=5000.0)
    fade_in_seconds: float = Field(default=0.35, ge=0.0, le=5.0)
    fade_out_seconds: float = Field(default=0.8, ge=0.0, le=5.0)
    enable_payoff_swell: bool = True
    enable_hook_music_event: bool = True
    avoid_music_for_singing: bool = True
    max_track_reuse_per_project: int = Field(default=2, ge=1, le=20)
    validation_required: bool = True
    fallback_to_generated_assets: bool = True


class MultiSpeakerLayoutSettings(BaseModel):
    """Safe deterministic controls for Multi-Speaker Layout V2."""

    enabled: bool = True
    prefer_two_speaker_stack: bool = True
    enable_active_speaker_focus: bool = True
    enable_multi_face_safe_frame: bool = True
    minimum_face_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    minimum_track_coverage: float = Field(default=0.45, ge=0.0, le=1.0)
    minimum_association_confidence: float = Field(default=0.60, ge=0.0, le=1.0)
    minimum_speaker_hold_seconds: float = Field(default=1.2, ge=0.0, le=10.0)
    switch_hysteresis_seconds: float = Field(default=0.45, ge=0.0, le=5.0)
    missing_detection_hold_seconds: float = Field(default=0.6, ge=0.0, le=5.0)
    interpolation_max_gap_seconds: float = Field(default=1.0, ge=0.05, le=10.0)
    max_crop_movement_per_second: float = Field(default=0.22, ge=0.01, le=1.0)
    max_zoom_change_per_second: float = Field(default=0.18, ge=0.01, le=1.0)
    maximum_render_switches_per_minute: int = Field(default=24, ge=1, le=120)
    preserve_natural_two_face_frame: bool = True
    fallback_to_center_crop: bool = True
    validation_required: bool = True


class CaptionIntelligenceSettings(BaseModel):
    """Safe deterministic controls for Captions / Typography V2."""

    enabled: bool = True
    default_style: str = "default_clean"
    prefer_word_level: bool = True
    allow_estimated_word_timing: bool = True
    max_words_per_line: int = Field(default=7, ge=2, le=12)
    max_lines: int = Field(default=2, ge=1, le=3)
    min_display_time_seconds: float = Field(default=0.35, ge=0.1, le=2.0)
    max_display_time_seconds: float = Field(default=3.2, ge=0.5, le=10.0)
    enable_hook_treatment: bool = True
    enable_keyword_emphasis: bool = True
    enable_speaker_aware_captions: bool = True
    enable_face_avoidance: bool = True
    enable_safe_zone_validation: bool = True
    enable_caption_render_validation: bool = True
    allow_emoji: bool = False
    require_readability_validation: bool = True


class CaptionFontsSettings(BaseModel):
    """Font-family policy; Olympus never bundles or exposes system font files."""

    primary: str = "Arial"
    fallback: list[str] = Field(default_factory=lambda: ["Arial", "Segoe UI", "Verdana"])
    allow_custom_font_paths: bool = False


class MotionGraphicsSettings(BaseModel):
    """Bounded controls for Motion Graphics / Effects V2."""

    enabled: bool = True
    default_style: str = "default_clean"
    max_major_effects_under_15s: int = Field(default=3, ge=0, le=8)
    max_major_effects_under_30s: int = Field(default=5, ge=0, le=12)
    enable_hook_punch_in: bool = True
    enable_pattern_interrupts: bool = True
    enable_payoff_hold: bool = True
    enable_subtle_push_in: bool = True
    enable_reaction_zoom: bool = True
    enable_speed_ramps: bool = False
    enable_safe_flash: bool = False
    enable_micro_shake: bool = True
    enable_background_blur: bool = True
    max_zoom_scale: float = Field(default=1.18, ge=1.0, le=1.3)
    max_micro_shake_seconds: float = Field(default=0.35, ge=0.0, le=0.4)
    require_caption_safety: bool = True
    require_face_safety: bool = True
    require_layout_safety: bool = True
    require_render_validation: bool = True


class CopyrightSafetySettings(BaseModel):
    """Conservative controls for Copyright / Safety Checker V2."""

    enabled: bool = True
    warn_only: bool = False
    block_on_blocked: bool = True
    block_on_high_risk: bool = False
    require_rights_confirmation_for_links: bool = True
    require_music_license_verified: bool = True
    require_sfx_license_verified: bool = True
    require_visual_asset_license_verified: bool = True
    warn_on_unknown_source: bool = True
    warn_on_generated_validation_music: bool = True
    require_manual_review_for_third_party_links: bool = True
    max_report_text_excerpt_chars: int = Field(default=300, ge=0, le=2000)


class UploadMetadataSettings(BaseModel):
    """Truth-first controls for Title / Description / Hashtag V2."""

    enabled: bool = True
    generate_youtube: bool = True
    generate_instagram: bool = True
    generate_tiktok: bool = True
    max_title_length: int = Field(default=70, ge=20, le=100)
    max_youtube_hashtags: int = Field(default=8, ge=1, le=8)
    max_instagram_hashtags: int = Field(default=12, ge=1, le=12)
    max_tiktok_hashtags: int = Field(default=8, ge=1, le=8)
    allow_emojis: bool = False
    allow_curiosity_titles: bool = True
    block_misleading_claims: bool = True
    block_spam_hashtags: bool = True
    require_safety_check: bool = True
    require_manual_review_warning: bool = True
    generate_ab_variants: bool = True
    title_variant_count: int = Field(default=5, ge=1, le=5)


class CreatorPersonalizationSettings(BaseModel):
    """Local-only, explicit-feedback controls for Creator Personalization V2."""

    enabled: bool = True
    learning_enabled_by_default: bool = False
    explicit_feedback_only: Literal[True] = True
    active_profile_id: str = "default"
    storage_dir: str = "work/personalization"
    max_feedback_notes_chars: int = Field(default=500, ge=0, le=500)
    max_profiles: int = Field(default=20, ge=1, le=100)
    apply_to_planning: bool = True
    apply_to_editing: bool = True
    apply_to_music: bool = True
    apply_to_captions: bool = True
    apply_to_motion: bool = True
    apply_to_upload_metadata: bool = True
    max_score_delta: float = Field(default=0.15, ge=0.0, le=0.15)
    conservative_until_feedback_count: int = Field(default=5, ge=1, le=100)
    allow_export_import: bool = True


class DurableJobsSettings(BaseModel):
    """Local durable Workflow Engine persistence and recovery controls."""

    enabled: bool = True
    storage_dir: str = "work/jobs"
    run_in_process: bool = True
    heartbeat_interval_seconds: float = Field(default=10.0, ge=0.25, le=300.0)
    stale_after_seconds: float = Field(default=120.0, ge=1.0, le=86_400.0)
    max_attempts: int = Field(default=3, ge=1, le=20)
    cleanup_completed_after_days: int = Field(default=14, ge=0, le=3650)
    cleanup_failed_after_days: int = Field(default=30, ge=0, le=3650)
    allow_resume_completed: bool = False
    allow_partial_render_resume: bool = True
    prevent_duplicate_project_jobs: bool = True
    max_logs_tail_chars: int = Field(default=8000, ge=100, le=100_000)
    worker_poll_interval_seconds: float = Field(default=2.0, ge=0.05, le=60.0)


class Settings(BaseSettings):
    """Root settings object, composed of typed sub-sections."""

    model_config = SettingsConfigDict(
        env_prefix="OLYMPUS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE

    api: ApiSettings = Field(default_factory=ApiSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    rendering: RenderingSettings = Field(default_factory=RenderingSettings)
    link_ingestion: LinkIngestionSettings = Field(default_factory=LinkIngestionSettings)
    trend_research: TrendResearchSettings = Field(default_factory=TrendResearchSettings)
    music_intelligence: MusicIntelligenceSettings = Field(
        default_factory=MusicIntelligenceSettings
    )
    multi_speaker_layout: MultiSpeakerLayoutSettings = Field(
        default_factory=MultiSpeakerLayoutSettings
    )
    caption_intelligence: CaptionIntelligenceSettings = Field(
        default_factory=CaptionIntelligenceSettings
    )
    caption_fonts: CaptionFontsSettings = Field(default_factory=CaptionFontsSettings)
    motion_graphics: MotionGraphicsSettings = Field(default_factory=MotionGraphicsSettings)
    copyright_safety: CopyrightSafetySettings = Field(
        default_factory=CopyrightSafetySettings
    )
    upload_metadata: UploadMetadataSettings = Field(default_factory=UploadMetadataSettings)
    creator_personalization: CreatorPersonalizationSettings = Field(
        default_factory=CreatorPersonalizationSettings
    )
    durable_jobs: DurableJobsSettings = Field(default_factory=DurableJobsSettings)

    @property
    def is_production(self) -> bool:
        """True in production - used to gate debug behaviour and docs exposure."""

        return self.environment == Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached, validated application settings.

    Cached so the environment is parsed exactly once per process. Tests may
    clear the cache via ``get_settings.cache_clear()`` to inject overrides.
    """

    return Settings()

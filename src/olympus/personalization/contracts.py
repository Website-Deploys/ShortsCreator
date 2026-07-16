"""JSON-safe contracts for local Creator Personalization V2."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PERSONALIZATION_VERSION = "2"
RatingValue = Literal["like", "dislike", "neutral"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LearningSettings(ContractModel):
    enabled: bool = False
    explicit_feedback_only: Literal[True] = True
    total_feedback_count: int = Field(default=0, ge=0)
    last_feedback_at: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ChannelContext(ContractModel):
    channel_name: str = Field(default="", max_length=80)
    primary_platforms: list[str] = Field(default_factory=list, max_length=8)
    content_niches: list[str] = Field(default_factory=list, max_length=12)
    target_audience_notes: str = Field(default="", max_length=240)
    language: str = Field(default="en", max_length=24)
    tone: str = Field(default="balanced", max_length=40)


class ClipSelectionPreferences(ContractModel):
    preferred_clip_count_strategy: str = Field(default="automatic", max_length=40)
    prefer_emotional_payoff: bool = False
    prefer_high_curiosity_hooks: bool = False
    prefer_fast_start: bool = True
    prefer_complete_story: bool = True
    prefer_conversation_moments: bool = False
    avoid_repetitive_clips: bool = True
    avoid_low_context_clips: bool = True
    weights: dict[str, float] = Field(default_factory=dict)


class EditingPreferences(ContractModel):
    style_preset: str = Field(default="balanced_default", max_length=48)
    pacing: str = Field(default="balanced", max_length=24)
    motion_intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    zoom_intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    sfx_intensity: float = Field(default=0.35, ge=0.0, le=1.0)
    caption_intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    music_intensity: float = Field(default=0.45, ge=0.0, le=1.0)
    color_style: str = Field(default="natural", max_length=32)
    avoid_effects: list[str] = Field(default_factory=list, max_length=24)
    prefer_effects: list[str] = Field(default_factory=list, max_length=24)
    weights: dict[str, float] = Field(default_factory=dict)


class CaptionPreferences(ContractModel):
    style: str = Field(default="default_clean", max_length=48)
    casing: Literal["natural", "uppercase", "sentence"] = "natural"
    highlight_density: float = Field(default=0.4, ge=0.0, le=1.0)
    emoji_allowed: bool = False
    profanity_handling: Literal["preserve", "mask", "remove"] = "mask"
    max_words_per_line: int = Field(default=5, ge=2, le=8)
    avoid_styles: list[str] = Field(default_factory=list, max_length=16)
    weights: dict[str, float] = Field(default_factory=dict)


class MusicPreferences(ContractModel):
    preferred_moods: list[str] = Field(default_factory=list, max_length=12)
    avoided_moods: list[str] = Field(default_factory=list, max_length=12)
    prefer_instrumental: bool = True
    max_loudness: float = Field(default=-18.0, ge=-40.0, le=-8.0)
    music_presence: Literal["none", "low", "balanced", "high"] = "balanced"
    avoid_reuse: bool = True
    weights: dict[str, float] = Field(default_factory=dict)


class MotionPreferences(ContractModel):
    preferred_styles: list[str] = Field(default_factory=list, max_length=12)
    avoided_styles: list[str] = Field(default_factory=list, max_length=12)
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    safety_first: Literal[True] = True
    avoid_flash: Literal[True] = True
    avoid_shake: bool = True
    weights: dict[str, float] = Field(default_factory=dict)


class UploadMetadataPreferences(ContractModel):
    title_style: str = Field(default="clear", max_length=32)
    description_style: str = Field(default="concise", max_length=32)
    hashtag_style: str = Field(default="focused", max_length=32)
    prefer_curiosity_titles: bool = False
    prefer_emotional_titles: bool = False
    avoid_generic_titles: bool = True
    avoid_clickbait_lies: Literal[True] = True
    banned_hashtags: list[str] = Field(default_factory=list, max_length=40)
    preferred_hashtags: list[str] = Field(default_factory=list, max_length=24)
    emoji_allowed: bool = False
    title_variant_style: str = Field(default="balanced", max_length=32)
    weights: dict[str, float] = Field(default_factory=dict)


class SafetyPreferences(ContractModel):
    always_show_manual_review: bool = True
    block_unknown_rights: bool = False
    warn_before_export_if_uncertain: bool = True
    conservative_mode: bool = True


class LearnedPatterns(ContractModel):
    liked_hook_categories: list[str] = Field(default_factory=list, max_length=40)
    disliked_hook_categories: list[str] = Field(default_factory=list, max_length=40)
    liked_title_patterns: list[str] = Field(default_factory=list, max_length=40)
    disliked_title_patterns: list[str] = Field(default_factory=list, max_length=40)
    liked_caption_styles: list[str] = Field(default_factory=list, max_length=40)
    disliked_caption_styles: list[str] = Field(default_factory=list, max_length=40)
    liked_music_moods: list[str] = Field(default_factory=list, max_length=40)
    disliked_music_moods: list[str] = Field(default_factory=list, max_length=40)
    liked_motion_styles: list[str] = Field(default_factory=list, max_length=40)
    disliked_motion_styles: list[str] = Field(default_factory=list, max_length=40)
    liked_clip_traits: list[str] = Field(default_factory=list, max_length=40)
    disliked_clip_traits: list[str] = Field(default_factory=list, max_length=40)


class PrivacySettings(ContractModel):
    local_only: Literal[True] = True
    no_sensitive_data: Literal[True] = True
    no_cloud_sync: Literal[True] = True
    exportable: bool = True
    resettable: bool = True


class CreatorProfileV2(ContractModel):
    profile_id: str = Field(min_length=1, max_length=80)
    profile_name: str = Field(min_length=1, max_length=80)
    preset_id: str = Field(default="balanced_default", max_length=48)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    version: Literal["2"] = "2"
    learning: LearningSettings = Field(default_factory=LearningSettings)
    channel_context: ChannelContext = Field(default_factory=ChannelContext)
    clip_selection_preferences: ClipSelectionPreferences = Field(
        default_factory=ClipSelectionPreferences
    )
    editing_preferences: EditingPreferences = Field(default_factory=EditingPreferences)
    caption_preferences: CaptionPreferences = Field(default_factory=CaptionPreferences)
    music_preferences: MusicPreferences = Field(default_factory=MusicPreferences)
    motion_preferences: MotionPreferences = Field(default_factory=MotionPreferences)
    upload_metadata_preferences: UploadMetadataPreferences = Field(
        default_factory=UploadMetadataPreferences
    )
    safety_preferences: SafetyPreferences = Field(default_factory=SafetyPreferences)
    learned_patterns: LearnedPatterns = Field(default_factory=LearnedPatterns)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("profile_id may contain only letters, numbers, '_' and '-'")
        return value

    @model_validator(mode="after")
    def validate_weights(self) -> CreatorProfileV2:
        sections = (
            self.clip_selection_preferences.weights,
            self.editing_preferences.weights,
            self.caption_preferences.weights,
            self.music_preferences.weights,
            self.motion_preferences.weights,
            self.upload_metadata_preferences.weights,
        )
        if any(abs(weight) > 1.0 for section in sections for weight in section.values()):
            raise ValueError("preference weights must remain between -1.0 and 1.0")
        return self


class FeedbackRating(ContractModel):
    overall: RatingValue = "neutral"
    clip_selection: RatingValue | None = None
    hook: RatingValue | None = None
    story: RatingValue | None = None
    captions: RatingValue | None = None
    editing: RatingValue | None = None
    music: RatingValue | None = None
    motion: RatingValue | None = None
    title_metadata: RatingValue | None = None


class FeedbackLabels(ContractModel):
    liked: bool = False
    disliked: bool = False
    make_more_like_this: bool = False
    avoid_in_future: bool = False
    too_generic: bool = False
    too_slow: bool = False
    too_much_motion: bool = False
    too_little_motion: bool = False
    title_good: bool = False
    title_bad: bool = False
    captions_good: bool = False
    captions_bad: bool = False
    music_good: bool = False
    music_bad: bool = False

    @model_validator(mode="after")
    def reject_conflicting_labels(self) -> FeedbackLabels:
        conflicts = (
            ("liked", "disliked"),
            ("make_more_like_this", "avoid_in_future"),
            ("too_much_motion", "too_little_motion"),
            ("title_good", "title_bad"),
            ("captions_good", "captions_bad"),
            ("music_good", "music_bad"),
        )
        selected = [pair for pair in conflicts if all(getattr(self, name) for name in pair)]
        if selected:
            raise ValueError(f"Conflicting feedback labels are not allowed: {selected}")
        return self


class SafeLearning(ContractModel):
    liked_hook_categories: list[str] = Field(default_factory=list)
    disliked_hook_categories: list[str] = Field(default_factory=list)
    liked_title_patterns: list[str] = Field(default_factory=list)
    disliked_title_patterns: list[str] = Field(default_factory=list)
    liked_caption_styles: list[str] = Field(default_factory=list)
    disliked_caption_styles: list[str] = Field(default_factory=list)
    liked_music_moods: list[str] = Field(default_factory=list)
    disliked_music_moods: list[str] = Field(default_factory=list)
    liked_motion_styles: list[str] = Field(default_factory=list)
    disliked_motion_styles: list[str] = Field(default_factory=list)
    liked_clip_traits: list[str] = Field(default_factory=list)
    disliked_clip_traits: list[str] = Field(default_factory=list)


class ClipFeedbackV2(ContractModel):
    feedback_id: str = Field(min_length=1, max_length=96)
    profile_id: str = Field(min_length=1, max_length=80)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=utc_now)
    version: Literal["2"] = "2"
    rating: FeedbackRating = Field(default_factory=FeedbackRating)
    labels: FeedbackLabels = Field(default_factory=FeedbackLabels)
    notes: str = Field(default="", max_length=500)
    extracted_safe_learning: SafeLearning = Field(default_factory=SafeLearning)
    applied_to_profile: bool = False


class PersonalizationAdjustment(ContractModel):
    system: str
    field: str
    previous: Any = None
    value: Any = None
    delta: float | None = None
    reason: str
    applied: bool = True


class PersonalizationAppliedV2(ContractModel):
    profile_id: str | None = None
    profile_name: str | None = None
    applied: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    affected_systems: list[str] = Field(default_factory=list)
    adjustments: list[PersonalizationAdjustment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


def model_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")

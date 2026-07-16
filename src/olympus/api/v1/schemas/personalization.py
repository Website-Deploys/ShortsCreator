"""Validated API payloads for local Creator Personalization V2."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from olympus.personalization.contracts import FeedbackRating

FeedbackLabel = Literal[
    "liked",
    "disliked",
    "make_more_like_this",
    "avoid_in_future",
    "too_generic",
    "too_slow",
    "too_much_motion",
    "too_little_motion",
    "title_good",
    "title_bad",
    "captions_good",
    "captions_bad",
    "music_good",
    "music_bad",
]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProfileRequest(ApiModel):
    preset_id: str = Field(min_length=1, max_length=48)
    profile_name: str | None = Field(default=None, min_length=1, max_length=80)
    learning_enabled: bool = False
    activate: bool = False


class UpdateProfileRequest(ApiModel):
    updates: dict[str, Any]


class ActivateProfileRequest(ApiModel):
    confirm: bool = True


class ResetProfileRequest(ApiModel):
    confirm: bool


class ImportProfileRequest(ApiModel):
    profile: dict[str, Any]
    activate: bool = False


class ClipTraitsInput(ApiModel):
    hook_category: str | None = Field(default=None, max_length=48)
    title_pattern: str | None = Field(default=None, max_length=48)
    caption_style: str | None = Field(default=None, max_length=48)
    music_mood: str | None = Field(default=None, max_length=48)
    motion_style: str | None = Field(default=None, max_length=48)
    clip_traits: list[str] = Field(default_factory=list, max_length=12)


class SubmitFeedbackRequest(ApiModel):
    profile_id: str = Field(min_length=1, max_length=80)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    rating: FeedbackRating = Field(default_factory=FeedbackRating)
    labels: list[FeedbackLabel] = Field(default_factory=list, max_length=14)
    notes: str = Field(default="", max_length=500)
    clip_traits: ClipTraitsInput = Field(default_factory=ClipTraitsInput)

    @model_validator(mode="after")
    def reject_conflicting_labels(self) -> SubmitFeedbackRequest:
        selected = set(self.labels)
        conflicts = (
            {"liked", "disliked"},
            {"make_more_like_this", "avoid_in_future"},
            {"too_much_motion", "too_little_motion"},
            {"title_good", "title_bad"},
            {"captions_good", "captions_bad"},
            {"music_good", "music_bad"},
        )
        if any(pair <= selected for pair in conflicts):
            raise ValueError("Conflicting feedback labels are not allowed.")
        return self

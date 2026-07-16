"""Explicit-only feedback extraction and conservative profile learning."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from olympus.personalization.contracts import (
    ClipFeedbackV2,
    CreatorProfileV2,
    FeedbackLabels,
    FeedbackRating,
    SafeLearning,
    utc_now,
)
from olympus.personalization.validation import validate_clip_traits, validate_safe_text

_PATTERN_FIELDS = {
    "hook_category": ("liked_hook_categories", "disliked_hook_categories"),
    "title_pattern": ("liked_title_patterns", "disliked_title_patterns"),
    "caption_style": ("liked_caption_styles", "disliked_caption_styles"),
    "music_mood": ("liked_music_moods", "disliked_music_moods"),
    "motion_style": ("liked_motion_styles", "disliked_motion_styles"),
}


def feedback_labels(values: list[str] | None) -> FeedbackLabels:
    valid = set(FeedbackLabels.model_fields)
    selected = {value for value in values or [] if value in valid}
    return FeedbackLabels(**{name: name in selected for name in valid})


def extract_safe_learning(
    rating: FeedbackRating,
    labels: FeedbackLabels,
    clip_traits: dict[str, Any] | None,
) -> SafeLearning:
    traits = validate_clip_traits(clip_traits)
    positive = bool(
        rating.overall == "like" or labels.liked or labels.make_more_like_this
    )
    negative = bool(
        rating.overall == "dislike" or labels.disliked or labels.avoid_in_future
    )
    output: dict[str, list[str]] = {
        field: [] for field in SafeLearning.model_fields
    }
    for source, (liked_field, disliked_field) in _PATTERN_FIELDS.items():
        value = traits.get(source)
        if not value:
            continue
        category_rating = {
            "hook_category": rating.hook,
            "title_pattern": rating.title_metadata,
            "caption_style": rating.captions,
            "music_mood": rating.music,
            "motion_style": rating.motion,
        }[source]
        category_positive = category_rating == "like"
        category_negative = category_rating == "dislike"
        if source == "title_pattern":
            category_positive = category_positive or labels.title_good
            category_negative = category_negative or labels.title_bad
        elif source == "caption_style":
            category_positive = category_positive or labels.captions_good
            category_negative = category_negative or labels.captions_bad
        elif source == "music_mood":
            category_positive = category_positive or labels.music_good
            category_negative = category_negative or labels.music_bad
        elif source == "motion_style":
            category_positive = category_positive or labels.too_little_motion
            category_negative = category_negative or labels.too_much_motion
        explicit_category = category_positive or category_negative
        if category_positive or (positive and not explicit_category):
            output[liked_field].append(value)
        if category_negative or (negative and not explicit_category):
            output[disliked_field].append(value)
    clip_values = traits.get("clip_traits") or []
    if positive:
        output["liked_clip_traits"].extend(clip_values)
    if negative:
        output["disliked_clip_traits"].extend(clip_values)
    return SafeLearning(**{key: list(dict.fromkeys(value)) for key, value in output.items()})


def build_feedback(
    *,
    profile_id: str,
    project_id: str,
    clip_id: str,
    rating: FeedbackRating,
    labels: FeedbackLabels,
    notes: str = "",
    clip_traits: dict[str, Any] | None = None,
    max_note_chars: int = 500,
) -> ClipFeedbackV2:
    safe_notes = validate_safe_text(notes, field="notes", max_chars=max_note_chars)
    return ClipFeedbackV2(
        feedback_id=f"feedback_{uuid4().hex[:20]}",
        profile_id=profile_id,
        project_id=project_id,
        clip_id=clip_id,
        rating=rating,
        labels=labels,
        notes=safe_notes,
        extracted_safe_learning=extract_safe_learning(rating, labels, clip_traits),
    )


def _append_unique(target: list[str], values: list[str], *, limit: int = 40) -> list[str]:
    return list(dict.fromkeys([*target, *values]))[-limit:]


def _adjust_weight(weights: dict[str, float], key: str, rating: str | None, step: float) -> None:
    if rating not in {"like", "dislike"}:
        return
    direction = 1.0 if rating == "like" else -1.0
    weights[key] = round(min(0.15, max(-0.15, weights.get(key, 0.0) + direction * step)), 3)


def apply_feedback_to_profile(
    profile: CreatorProfileV2,
    feedback: ClipFeedbackV2,
    *,
    conservative_until: int = 5,
) -> tuple[CreatorProfileV2, bool]:
    updated = profile.model_copy(deep=True)
    learning = updated.learning
    learning.total_feedback_count += 1
    learning.last_feedback_at = feedback.created_at
    learning.confidence = min(
        0.9,
        round(learning.total_feedback_count / max(conservative_until * 2, 10), 3),
    )
    updated.updated_at = utc_now()
    if not learning.enabled or not learning.explicit_feedback_only:
        return updated, False

    extracted = feedback.extracted_safe_learning
    patterns = updated.learned_patterns
    for field in type(extracted).model_fields:
        setattr(
            patterns,
            field,
            _append_unique(getattr(patterns, field), getattr(extracted, field)),
        )

    step = min(0.03, 0.01 + learning.confidence * 0.02)
    labels = feedback.labels
    ratings = feedback.rating
    _adjust_weight(
        updated.clip_selection_preferences.weights,
        "overall",
        ratings.overall,
        step,
    )
    _adjust_weight(
        updated.clip_selection_preferences.weights,
        "hook",
        ratings.hook,
        step,
    )
    _adjust_weight(
        updated.clip_selection_preferences.weights,
        "story",
        ratings.story,
        step,
    )
    _adjust_weight(updated.caption_preferences.weights, "feedback", ratings.captions, step)
    _adjust_weight(updated.editing_preferences.weights, "feedback", ratings.editing, step)
    _adjust_weight(updated.music_preferences.weights, "feedback", ratings.music, step)
    _adjust_weight(updated.motion_preferences.weights, "feedback", ratings.motion, step)
    _adjust_weight(
        updated.upload_metadata_preferences.weights,
        "feedback",
        ratings.title_metadata,
        step,
    )
    if labels.captions_good or labels.captions_bad:
        _adjust_weight(
            updated.caption_preferences.weights,
            "feedback",
            "like" if labels.captions_good else "dislike",
            step,
        )
    if labels.music_good or labels.music_bad:
        _adjust_weight(
            updated.music_preferences.weights,
            "feedback",
            "like" if labels.music_good else "dislike",
            step,
        )
    if labels.title_good or labels.title_bad:
        _adjust_weight(
            updated.upload_metadata_preferences.weights,
            "feedback",
            "like" if labels.title_good else "dislike",
            step,
        )
    if labels.too_slow:
        updated.editing_preferences.weights["pacing_fast"] = min(
            0.15,
            updated.editing_preferences.weights.get("pacing_fast", 0.0) + step,
        )
    if labels.too_much_motion or ratings.motion == "dislike":
        updated.motion_preferences.intensity = max(
            0.0, updated.motion_preferences.intensity - step
        )
        updated.editing_preferences.motion_intensity = max(
            0.0, updated.editing_preferences.motion_intensity - step
        )
    if labels.too_little_motion or ratings.motion == "like":
        updated.motion_preferences.intensity = min(
            1.0, updated.motion_preferences.intensity + step
        )
        updated.editing_preferences.motion_intensity = min(
            1.0, updated.editing_preferences.motion_intensity + step
        )
    if labels.too_generic or labels.title_bad:
        updated.upload_metadata_preferences.avoid_generic_titles = True
    return updated, True

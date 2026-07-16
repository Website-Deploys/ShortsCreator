"""Build transparent creator memory from profiles and explicit feedback only."""

from __future__ import annotations

from typing import Any

from olympus.boba.memory_contracts import BobaCreatorMemoryV1, BobaMemoryRecordV1
from olympus.boba.memory_summarizer import memory_strings, memory_summary, safe_excerpt
from olympus.boba.store import BobaMemoryStore
from olympus.personalization.contracts import ClipFeedbackV2, CreatorProfileV2


def _feedback_models(values: list[Any]) -> list[ClipFeedbackV2]:
    feedback: list[ClipFeedbackV2] = []
    for value in values:
        if isinstance(value, ClipFeedbackV2):
            feedback.append(value)
        elif isinstance(value, dict):
            feedback.append(ClipFeedbackV2.model_validate(value))
    return feedback


def _feedback_record(feedback: ClipFeedbackV2) -> BobaMemoryRecordV1:
    labels = [name for name, enabled in feedback.labels.model_dump().items() if enabled]
    traits = [
        item
        for values in feedback.extracted_safe_learning.model_dump().values()
        for item in values
    ]
    summary = memory_summary(
        [
            f"Explicit feedback rated clip {feedback.rating.overall}",
            f"Labels: {', '.join(labels)}" if labels else "No labels",
        ]
    )
    return BobaMemoryRecordV1(
        memory_id=f"memory_{feedback.feedback_id}"[:128],
        scope="creator",
        record_type="user_feedback",
        source="creator_personalization_v2",
        project_id=feedback.project_id,
        clip_id=feedback.clip_id,
        creator_profile_id=feedback.profile_id,
        confidence=0.3,
        importance=0.6,
        decay_rate=0.05,
        tags=memory_strings(["explicit_feedback", *labels, *traits], limit=32, max_chars=80),
        summary=summary,
        evidence=[safe_excerpt(feedback.notes)] if feedback.notes else [],
        applies_to=[
            "planning",
            "ranking",
            "editorial_policy",
            "captions",
            "music",
            "motion",
            "upload_metadata",
        ],
        metadata={"rating": feedback.rating.model_dump(mode="json")},
    )


def build_creator_memory(
    profile: CreatorProfileV2,
    feedback_values: list[Any] | None = None,
) -> tuple[BobaCreatorMemoryV1, list[BobaMemoryRecordV1]]:
    feedback = _feedback_models(feedback_values or [])
    learned = profile.learned_patterns
    repeated_music_loud = sum(
        1
        for item in feedback
        if item.rating.music == "dislike"
        and "music" in item.notes.lower()
        and any(word in item.notes.lower() for word in ("loud", "overpower", "speech"))
    )
    preferred_clip_traits = memory_strings(learned.liked_clip_traits, limit=100)
    avoided_clip_traits = memory_strings(learned.disliked_clip_traits, limit=100)
    preferred_music = memory_strings(
        [*profile.music_preferences.preferred_moods, *learned.liked_music_moods], limit=100
    )
    avoided_music = memory_strings(
        [*profile.music_preferences.avoided_moods, *learned.disliked_music_moods], limit=100
    )
    known_good = memory_strings(
        [
            *learned.liked_clip_traits,
            *learned.liked_hook_categories,
            *learned.liked_title_patterns,
        ],
        limit=100,
    )
    known_bad = memory_strings(
        [
            *learned.disliked_clip_traits,
            *learned.disliked_hook_categories,
            *learned.disliked_title_patterns,
        ],
        limit=100,
    )
    if repeated_music_loud >= 3:
        avoided_music = memory_strings([*avoided_music, "high_music_intensity"], limit=100)
        known_bad = memory_strings([*known_bad, "music_overpowers_speech"], limit=100)
        preferred_clip_traits = memory_strings(
            [*preferred_clip_traits, "speech_first_mix"], limit=100
        )
    style_summary = memory_summary(
        [
            f"Profile {profile.profile_name} uses {profile.editing_preferences.style_preset}",
            f"Pacing is {profile.editing_preferences.pacing}",
            f"Title style is {profile.upload_metadata_preferences.title_style}",
            f"Learning uses {len(feedback)} explicit feedback items",
        ]
    )
    creator_memory = BobaCreatorMemoryV1(
        creator_profile_id=profile.profile_id,
        learning_enabled=profile.learning.enabled,
        style_summary=style_summary,
        preferred_clip_traits=preferred_clip_traits,
        avoided_clip_traits=avoided_clip_traits,
        preferred_hook_styles=memory_strings(learned.liked_hook_categories, limit=100),
        avoided_hook_styles=memory_strings(learned.disliked_hook_categories, limit=100),
        preferred_title_styles=memory_strings(
            [
                profile.upload_metadata_preferences.title_style,
                *learned.liked_title_patterns,
            ],
            limit=100,
        ),
        avoided_title_styles=memory_strings(
            [
                *(["generic"] if profile.upload_metadata_preferences.avoid_generic_titles else []),
                *learned.disliked_title_patterns,
            ],
            limit=100,
        ),
        preferred_caption_styles=memory_strings(
            [profile.caption_preferences.style, *learned.liked_caption_styles], limit=100
        ),
        avoided_caption_styles=memory_strings(
            [*profile.caption_preferences.avoid_styles, *learned.disliked_caption_styles], limit=100
        ),
        preferred_music_moods=preferred_music,
        avoided_music_moods=avoided_music,
        preferred_motion_styles=memory_strings(
            [*profile.motion_preferences.preferred_styles, *learned.liked_motion_styles], limit=100
        ),
        avoided_motion_styles=memory_strings(
            [*profile.motion_preferences.avoided_styles, *learned.disliked_motion_styles], limit=100
        ),
        banned_hashtags=memory_strings(
            profile.upload_metadata_preferences.banned_hashtags, limit=100
        ),
        preferred_hashtags=memory_strings(
            profile.upload_metadata_preferences.preferred_hashtags, limit=100
        ),
        known_good_patterns=known_good,
        known_bad_patterns=known_bad,
        feedback_count=len(feedback),
        confidence=profile.learning.confidence,
        warnings=(
            []
            if profile.learning.enabled
            else [
                "Creator learning is disabled; existing explicit settings remain available."
            ]
        ),
    )
    records = [_feedback_record(item) for item in feedback]
    records.append(
        BobaMemoryRecordV1(
            memory_id=f"creator_preference_{profile.profile_id}"[:128],
            scope="creator",
            record_type="creator_preference",
            source="creator_profile_v2",
            creator_profile_id=profile.profile_id,
            confidence=max(0.2, profile.learning.confidence),
            importance=0.85,
            tags=memory_strings(
                ["creator_preference", *preferred_clip_traits, *known_bad], limit=32, max_chars=80
            ),
            summary=style_summary,
            applies_to=[
                "planning",
                "ranking",
                "editorial_policy",
                "captions",
                "music",
                "motion",
                "upload_metadata",
            ],
        )
    )
    return creator_memory, records


def build_and_save_creator_memory(
    store: BobaMemoryStore,
    profile: CreatorProfileV2,
    feedback_values: list[Any] | None = None,
) -> BobaCreatorMemoryV1:
    creator_memory, records = build_creator_memory(profile, feedback_values)
    for record in records:
        store.save_record(record)
    return store.save_creator_memory(creator_memory)

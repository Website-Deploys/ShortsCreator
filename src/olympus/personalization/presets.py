"""Safe, editable Creator Personalization V2 presets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from olympus.personalization.contracts import CreatorProfileV2

PRESETS: dict[str, dict[str, Any]] = {
    "balanced_default": {
        "name": "Balanced Default",
        "channel_context": {"tone": "balanced"},
        "editing_preferences": {"style_preset": "balanced_default"},
        "caption_preferences": {"style": "default_clean"},
        "upload_metadata_preferences": {"title_style": "clear"},
    },
    "viral_storyteller": {
        "name": "Viral Storyteller",
        "channel_context": {"tone": "story-driven"},
        "clip_selection_preferences": {
            "prefer_emotional_payoff": True,
            "prefer_high_curiosity_hooks": True,
        },
        "editing_preferences": {
            "style_preset": "viral_storyteller",
            "pacing": "fast",
            "motion_intensity": 0.7,
            "caption_intensity": 0.75,
        },
        "caption_preferences": {"style": "bold_hook", "highlight_density": 0.7},
        "music_preferences": {"music_presence": "high"},
        "motion_preferences": {"preferred_styles": ["story_punch"], "intensity": 0.7},
        "upload_metadata_preferences": {
            "title_style": "curiosity",
            "prefer_curiosity_titles": True,
            "prefer_emotional_titles": True,
        },
    },
    "clean_podcast": {
        "name": "Clean Podcast",
        "channel_context": {"tone": "conversational", "content_niches": ["podcast"]},
        "clip_selection_preferences": {"prefer_conversation_moments": True},
        "editing_preferences": {
            "style_preset": "clean_podcast",
            "pacing": "measured",
            "motion_intensity": 0.18,
            "zoom_intensity": 0.2,
            "sfx_intensity": 0.08,
            "caption_intensity": 0.35,
        },
        "caption_preferences": {"style": "podcast_clean", "highlight_density": 0.25},
        "music_preferences": {
            "preferred_moods": ["neutral", "warm"],
            "music_presence": "low",
            "max_loudness": -22.0,
        },
        "motion_preferences": {"preferred_styles": ["clean_podcast"], "intensity": 0.18},
        "upload_metadata_preferences": {"title_style": "clear"},
    },
    "motivational_shorts": {
        "name": "Motivational Shorts",
        "channel_context": {"tone": "motivational", "content_niches": ["motivational"]},
        "clip_selection_preferences": {
            "prefer_emotional_payoff": True,
            "prefer_high_curiosity_hooks": True,
            "prefer_fast_start": True,
        },
        "editing_preferences": {
            "style_preset": "motivational_shorts",
            "pacing": "fast",
            "motion_intensity": 0.62,
            "zoom_intensity": 0.62,
            "caption_intensity": 0.82,
            "music_intensity": 0.65,
        },
        "caption_preferences": {
            "style": "motivational_impact",
            "casing": "uppercase",
            "highlight_density": 0.8,
            "max_words_per_line": 4,
        },
        "music_preferences": {
            "preferred_moods": ["motivational", "uplifting"],
            "music_presence": "high",
            "max_loudness": -16.0,
        },
        "motion_preferences": {
            "preferred_styles": ["motivational_punch"],
            "intensity": 0.62,
        },
        "upload_metadata_preferences": {
            "title_style": "emotional",
            "prefer_curiosity_titles": True,
            "prefer_emotional_titles": True,
            "preferred_hashtags": ["#Motivation", "#Mindset"],
        },
    },
    "music_performance": {
        "name": "Music Performance",
        "channel_context": {"tone": "performance", "content_niches": ["music_performance"]},
        "editing_preferences": {
            "style_preset": "music_performance",
            "motion_intensity": 0.15,
            "sfx_intensity": 0.0,
            "music_intensity": 0.0,
        },
        "caption_preferences": {"style": "music_minimal", "highlight_density": 0.2},
        "music_preferences": {"music_presence": "none"},
        "motion_preferences": {
            "preferred_styles": ["music_performance_minimal"],
            "intensity": 0.12,
        },
        "upload_metadata_preferences": {
            "title_style": "performance",
            "preferred_hashtags": ["#Music", "#LivePerformance"],
        },
    },
    "gaming_reactive": {
        "name": "Gaming Reactive",
        "channel_context": {"tone": "reactive", "content_niches": ["gaming"]},
        "editing_preferences": {
            "style_preset": "gaming_reactive",
            "pacing": "fast",
            "motion_intensity": 0.75,
            "zoom_intensity": 0.72,
            "caption_intensity": 0.68,
        },
        "caption_preferences": {"style": "gaming_energy", "highlight_density": 0.65},
        "music_preferences": {"preferred_moods": ["energetic"], "music_presence": "low"},
        "motion_preferences": {"preferred_styles": ["gaming_reactive"], "intensity": 0.72},
        "upload_metadata_preferences": {
            "title_style": "reaction",
            "preferred_hashtags": ["#Gaming"],
        },
    },
    "education_clarity": {
        "name": "Education Clarity",
        "channel_context": {"tone": "informative", "content_niches": ["education"]},
        "clip_selection_preferences": {"prefer_complete_story": True},
        "editing_preferences": {
            "style_preset": "education_clarity",
            "pacing": "measured",
            "motion_intensity": 0.25,
            "sfx_intensity": 0.08,
            "caption_intensity": 0.48,
        },
        "caption_preferences": {"style": "education_clear", "highlight_density": 0.4},
        "music_preferences": {"music_presence": "low", "max_loudness": -23.0},
        "motion_preferences": {"preferred_styles": ["education_clarity"], "intensity": 0.24},
        "upload_metadata_preferences": {"title_style": "clear"},
    },
}


def preset_names() -> list[str]:
    return sorted(PRESETS)


def profile_from_preset(
    preset_id: str,
    *,
    profile_id: str | None = None,
    profile_name: str | None = None,
    learning_enabled: bool = False,
) -> CreatorProfileV2:
    if preset_id not in PRESETS:
        raise ValueError(f"Unknown personalization preset: {preset_id}")
    preset = deepcopy(PRESETS[preset_id])
    default_name = str(preset.pop("name"))
    name = profile_name or default_name
    identifier = profile_id or f"profile_{uuid4().hex[:16]}"
    return CreatorProfileV2(
        profile_id=identifier,
        profile_name=name,
        preset_id=preset_id,
        learning={"enabled": learning_enabled},
        **preset,
    )

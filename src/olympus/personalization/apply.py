"""Bounded preference application across Olympus V2 decision systems."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, TypeVar

from olympus.personalization.contracts import CreatorProfileV2
from olympus.personalization.store import ProfileStore
from olympus.platform.config import get_settings

_SYSTEMS = ("planning", "editing", "captions", "music", "motion", "upload_metadata")
_CAPTION_STYLE_ALIASES = {
    "podcast_clean": "clean_podcast",
    "education_clear": "educational_clear",
}
_MOTION_STYLE_ALIASES = {
    "story_punch": "default_clean",
    "motivational_punch": "motivational_dynamic",
    "education_clarity": "educational_clarity",
}
_TitleCandidate = TypeVar("_TitleCandidate", bound=Mapping[str, Any])


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _round(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 3)


def _intensity_label(value: float) -> str:
    if value <= 0.12:
        return "minimal"
    if value <= 0.32:
        return "low"
    if value <= 0.55:
        return "medium"
    if value <= 0.75:
        return "medium_high"
    return "high"


def profile_directives(profile: CreatorProfileV2 | dict[str, Any]) -> dict[str, Any]:
    raw = profile.model_dump(mode="json") if isinstance(profile, CreatorProfileV2) else profile
    return {
        "version": "2",
        "profile_id": raw.get("profile_id"),
        "profile_name": raw.get("profile_name"),
        "preset_id": raw.get("preset_id"),
        "confidence": _float(_dict(raw.get("learning")).get("confidence")),
        "feedback_count": int(_float(_dict(raw.get("learning")).get("total_feedback_count"))),
        "learning_enabled": _dict(raw.get("learning")).get("enabled") is True,
        "clip_selection": deepcopy(_dict(raw.get("clip_selection_preferences"))),
        "editing": deepcopy(_dict(raw.get("editing_preferences"))),
        "captions": deepcopy(_dict(raw.get("caption_preferences"))),
        "music": deepcopy(_dict(raw.get("music_preferences"))),
        "motion": deepcopy(_dict(raw.get("motion_preferences"))),
        "upload_metadata": deepcopy(_dict(raw.get("upload_metadata_preferences"))),
        "safety": deepcopy(_dict(raw.get("safety_preferences"))),
        "learned_patterns": deepcopy(_dict(raw.get("learned_patterns"))),
        "privacy": {
            "local_only": True,
            "explicit_feedback_only": True,
            "no_cloud_sync": True,
        },
    }


def load_runtime_directives() -> dict[str, Any] | None:
    settings = get_settings().creator_personalization
    if not settings.enabled:
        return None
    try:
        store = ProfileStore(
            settings.storage_dir,
            max_profiles=settings.max_profiles,
            max_note_chars=settings.max_feedback_notes_chars,
        )
        profile = store.get_active_profile(fallback_id=settings.active_profile_id)
    except Exception:
        return None
    return profile_directives(profile) if profile is not None else None


def empty_application(reason: str = "No active creator profile was available.") -> dict[str, Any]:
    return {
        "version": "2",
        "profile_id": None,
        "profile_name": None,
        "applied": False,
        "confidence": 0.0,
        "affected_systems": [],
        "adjustments": [],
        "warnings": [],
        "reasons": [reason],
    }


def _application(
    directives: dict[str, Any] | None,
    *,
    system: str,
    adjustments: list[dict[str, Any]],
    warnings: list[str] | None = None,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    if not directives:
        return empty_application()
    applied = any(item.get("applied", True) for item in adjustments)
    return {
        "version": "2",
        "profile_id": directives.get("profile_id"),
        "profile_name": directives.get("profile_name"),
        "applied": applied,
        "confidence": _float(directives.get("confidence")),
        "affected_systems": [system] if applied else [],
        "adjustments": adjustments,
        "warnings": list(dict.fromkeys(warnings or [])),
        "reasons": reasons
        or (
            [f"Applied explicit {system} preferences."]
            if applied
            else ["Profile matched defaults."]
        ),
    }


def apply_planning_personalization(
    scores: dict[str, float],
    candidate: dict[str, Any],
    directives: dict[str, Any] | None,
    *,
    max_score_delta: float,
) -> tuple[dict[str, float], dict[str, Any]]:
    if not directives:
        return scores, empty_application()
    output = dict(scores)
    preferences = _dict(directives.get("clip_selection"))
    learned = _dict(directives.get("learned_patterns"))
    weights = _dict(preferences.get("weights"))
    story = _dict(candidate.get("story_v2_guidance"))
    hook = _dict(_dict(candidate.get("v2_candidate_metadata")).get("hook_analysis"))
    hook_category = str(
        hook.get("category")
        or _dict(candidate.get("hook_candidate")).get("category")
        or ""
    )
    context_risk = _float(story.get("context_risk"))
    unsafe = str(
        candidate.get("safety_status")
        or _dict(candidate.get("copyright_safety")).get("risk_level")
        or ""
    ).lower() in {"high", "blocked"}
    adjustments: list[dict[str, Any]] = []
    desired: dict[str, float] = {}

    def add(field: str, delta: float, reason: str) -> None:
        if delta > 0 and unsafe:
            adjustments.append(
                {
                    "system": "planning",
                    "field": field,
                    "previous": output.get(field),
                    "value": output.get(field),
                    "delta": 0.0,
                    "reason": "Personalization cannot boost a clip with high or blocked risk.",
                    "applied": False,
                }
            )
            return
        desired[field] = desired.get(field, 0.0) + delta
        adjustments.append(
            {
                "system": "planning",
                "field": field,
                "previous": output.get(field),
                "delta": delta,
                "reason": reason,
                "applied": True,
            }
        )

    strength = min(
        max_score_delta,
        0.04 + min(10, int(directives.get("feedback_count") or 0)) * 0.003,
    )
    if preferences.get("prefer_emotional_payoff"):
        add("emotion", strength, "Profile prefers emotional payoff.")
        add("payoff", strength * 0.7, "Profile prefers a clear emotional landing.")
    if preferences.get("prefer_high_curiosity_hooks") and hook_category in {
        "curiosity",
        "curiosity_gap",
        "open_loop",
        "question",
    }:
        add("hook", strength, "Profile prefers high-curiosity openings.")
    if preferences.get("prefer_complete_story"):
        add("story_completion", strength * 0.8, "Profile prefers complete stories.")
        add("story", strength * 0.5, "Profile prefers coherent story arcs.")
    if preferences.get("avoid_low_context_clips") and context_risk >= 0.55:
        add("clarity", -strength, "Profile avoids clips with high context dependency.")
        add("retention", -strength * 0.5, "Context risk was conservatively penalized.")
    source_type = str(candidate.get("candidate_type") or candidate.get("source") or "")
    if preferences.get("prefer_conversation_moments") and "speaker" in source_type:
        add("retention", strength * 0.6, "Profile prefers strong conversation moments.")
    liked_hooks = {str(item) for item in _list(learned.get("liked_hook_categories"))}
    disliked_hooks = {
        str(item) for item in _list(learned.get("disliked_hook_categories"))
    }
    if hook_category in liked_hooks:
        add("hook", strength * 0.6, "Explicit feedback liked this hook category.")
    if hook_category in disliked_hooks:
        add("hook", -strength * 0.8, "Explicit feedback disliked this hook category.")
    candidate_traits = {
        str(item)
        for item in [
            *_list(candidate.get("clip_traits")),
            *_list(_dict(candidate.get("v2_candidate_metadata")).get("clip_traits")),
        ]
    }
    liked_traits = {str(item) for item in _list(learned.get("liked_clip_traits"))}
    disliked_traits = {
        str(item) for item in _list(learned.get("disliked_clip_traits"))
    }
    if candidate_traits & liked_traits:
        add("retention", strength * 0.4, "Explicit feedback liked matching clip traits.")
    if candidate_traits & disliked_traits:
        add("retention", -strength * 0.6, "Explicit feedback avoided matching clip traits.")
    for field, score_field in (("overall", "retention"), ("hook", "hook"), ("story", "story")):
        learned_weight = _float(weights.get(field))
        if learned_weight:
            add(
                score_field,
                strength * learned_weight,
                f"Conservative explicit-feedback {field} weight.",
            )

    for field, requested in desired.items():
        bounded = min(max_score_delta, max(-max_score_delta, requested))
        previous = _float(output.get(field))
        output[field] = _round(previous + bounded)
        for item in adjustments:
            if item["field"] == field and item.get("applied"):
                item["value"] = output[field]
                item["delta"] = round(output[field] - previous, 3)
    warnings = ["Unsafe clips are never boosted by creator preferences."] if unsafe else []
    return output, _application(
        directives,
        system="planning",
        adjustments=adjustments,
        warnings=warnings,
    )


def apply_editing_personalization(
    preset: dict[str, str], directives: dict[str, Any] | None
) -> tuple[dict[str, str], dict[str, Any]]:
    if not directives:
        return preset, empty_application()
    preferences = _dict(directives.get("editing"))
    output = dict(preset)
    adjustments: list[dict[str, Any]] = []

    def replace(field: str, value: str, reason: str) -> None:
        previous = output.get(field)
        if value and value != previous:
            output[field] = value
            adjustments.append(
                {
                    "system": "editing",
                    "field": field,
                    "previous": previous,
                    "value": value,
                    "reason": reason,
                    "applied": True,
                }
            )

    replace("style", str(preferences.get("style_preset") or ""), "Profile editing preset.")
    pacing = str(preferences.get("pacing") or "")
    weights = _dict(preferences.get("weights"))
    if _float(weights.get("pacing_fast")) > 0.0:
        pacing = "fast"
    replace("pacing", pacing, "Profile pacing preference.")
    motion = _float(preferences.get("motion_intensity"), 0.5)
    zoom = _float(preferences.get("zoom_intensity"), 0.5)
    sfx = _float(preferences.get("sfx_intensity"), 0.35)
    replace("zoom_frequency", _intensity_label(zoom), "Profile zoom intensity.")
    replace("sfx_density", _intensity_label(sfx), "Profile SFX intensity.")
    if motion <= 0.25:
        replace("transition_style", "clean_cut", "Profile requests restrained motion.")
    application = _application(
        directives,
        system="editing",
        adjustments=adjustments,
    )
    application["style_preset"] = output["style"]
    application["motion_intensity"] = motion
    application["zoom_intensity"] = zoom
    application["sfx_intensity"] = sfx
    application["caption_intensity"] = _float(preferences.get("caption_intensity"), 0.5)
    return output, application


def caption_personalization(
    directives: dict[str, Any] | None,
    *,
    default_style: str,
    default_max_words: int,
) -> dict[str, Any]:
    if not directives:
        return {
            **empty_application(),
            "style": default_style,
            "casing": "natural",
            "highlight_density": 0.4,
            "max_words_per_line": default_max_words,
        }
    preferences = _dict(directives.get("captions"))
    learned = _dict(directives.get("learned_patterns"))
    requested = str(preferences.get("style") or default_style)
    style = _CAPTION_STYLE_ALIASES.get(requested, requested)
    avoided = {
        _CAPTION_STYLE_ALIASES.get(str(item), str(item))
        for item in [
            *_list(preferences.get("avoid_styles")),
            *_list(learned.get("disliked_caption_styles")),
        ]
    }
    liked = [
        _CAPTION_STYLE_ALIASES.get(str(item), str(item))
        for item in _list(learned.get("liked_caption_styles"))
    ]
    if liked and (style == default_style or style in avoided):
        style = next((item for item in reversed(liked) if item not in avoided), style)
    warnings: list[str] = []
    if style in avoided:
        warnings.append(f"Requested caption style '{style}' was also avoided; default retained.")
        style = default_style
    weights = _dict(preferences.get("weights"))
    highlight_density = min(
        1.0,
        max(
            0.0,
            _float(preferences.get("highlight_density"), 0.4)
            + _float(weights.get("feedback")) * 0.2,
        ),
    )
    max_words = max(
        2,
        min(8, int(_float(preferences.get("max_words_per_line"), default_max_words))),
    )
    adjustments: list[dict[str, Any]] = []
    for field, previous, value, reason in (
        ("style", default_style, style, "Profile caption style."),
        ("casing", "natural", preferences.get("casing") or "natural", "Profile caption casing."),
        (
            "highlight_density",
            0.4,
            highlight_density,
            "Profile emphasis density.",
        ),
        (
            "max_words_per_line",
            default_max_words,
            max_words,
            "Profile caption line length within readability limits.",
        ),
    ):
        if value != previous:
            adjustments.append(
                {
                    "system": "captions",
                    "field": field,
                    "previous": previous,
                    "value": value,
                    "reason": reason,
                    "applied": True,
                }
            )
    result = _application(
        directives,
        system="captions",
        adjustments=adjustments,
        warnings=warnings,
    )
    result.update(
        {
            "style": style,
            "casing": preferences.get("casing") or "natural",
            "highlight_density": highlight_density,
            "max_words_per_line": max_words,
            "emoji_allowed": preferences.get("emoji_allowed") is True,
        }
    )
    return result


def music_personalization(
    directives: dict[str, Any] | None,
    *,
    target_mood: str,
    gain_db: float | None,
    source_is_music: bool,
) -> dict[str, Any]:
    if not directives:
        return {
            **empty_application(),
            "target_mood": target_mood,
            "gain_db": gain_db,
            "music_presence": "balanced",
        }
    preferences = _dict(directives.get("music"))
    learned = _dict(directives.get("learned_patterns"))
    preferred = list(
        dict.fromkeys(
            str(item).lower()
            for item in [
                *_list(preferences.get("preferred_moods")),
                *_list(learned.get("liked_music_moods")),
            ]
        )
    )
    avoided = {
        str(item).lower()
        for item in [
            *_list(preferences.get("avoided_moods")),
            *_list(learned.get("disliked_music_moods")),
        ]
    }
    selected_mood = target_mood
    warnings: list[str] = []
    if selected_mood.lower() in avoided:
        selected_mood = next((item for item in preferred if item not in avoided), "neutral")
    elif preferred:
        selected_mood = preferred[0]
    max_loudness = _float(preferences.get("max_loudness"), -18.0)
    presence = str(preferences.get("music_presence") or "balanced")
    adjusted_gain = min(gain_db, max_loudness) if gain_db is not None else None
    if adjusted_gain is not None and presence == "low":
        adjusted_gain = min(adjusted_gain, -22.0)
    elif adjusted_gain is not None and presence == "high":
        adjusted_gain = min(max(adjusted_gain, -16.0), max_loudness)
    adjustments: list[dict[str, Any]] = []
    if selected_mood != target_mood:
        adjustments.append(
            {
                "system": "music",
                "field": "target_mood",
                "previous": target_mood,
                "value": selected_mood,
                "reason": "Profile preferred or avoided music mood.",
                "applied": True,
            }
        )
    if adjusted_gain != gain_db:
        adjustments.append(
            {
                "system": "music",
                "field": "music_gain_db",
                "previous": gain_db,
                "value": adjusted_gain,
                "reason": "Profile loudness ceiling kept speech primary.",
                "applied": True,
            }
        )
    if presence != "balanced" and gain_db is not None:
        adjustments.append(
            {
                "system": "music",
                "field": "music_presence",
                "previous": "balanced",
                "value": presence,
                "reason": "Profile changed background music presence.",
                "applied": True,
            }
        )
    if source_is_music and presence != "none":
        warnings.append("Music-performance protection overrides overlay music preference.")
    result = _application(
        directives,
        system="music",
        adjustments=adjustments,
        warnings=warnings,
    )
    result.update(
        {
            "preferred_moods": preferred,
            "avoided_moods": sorted(avoided),
            "target_mood": selected_mood,
            "gain_db": adjusted_gain,
            "music_presence": presence,
            "prefer_instrumental": preferences.get("prefer_instrumental") is not False,
            "avoid_reuse": preferences.get("avoid_reuse") is not False,
            "selected_due_to_profile": bool(adjustments),
        }
    )
    return result


def motion_personalization(
    directives: dict[str, Any] | None,
    *,
    style: str,
    intensity: float,
) -> dict[str, Any]:
    if not directives:
        return {
            **empty_application(),
            "style": style,
            "intensity": intensity,
            "avoided_styles": [],
            "avoided_effects": [],
        }
    preferences = _dict(directives.get("motion"))
    editing = _dict(directives.get("editing"))
    learned = _dict(directives.get("learned_patterns"))
    preferred = list(
        dict.fromkeys(
            str(item)
            for item in [
                *_list(preferences.get("preferred_styles")),
                *_list(learned.get("liked_motion_styles")),
            ]
        )
    )
    avoided = {
        str(item)
        for item in [
            *_list(preferences.get("avoided_styles")),
            *_list(learned.get("disliked_motion_styles")),
        ]
    }
    selected_style = _MOTION_STYLE_ALIASES.get(preferred[0], preferred[0]) if preferred else style
    warnings: list[str] = []
    if selected_style in avoided:
        warnings.append("Preferred motion style was also avoided; core style retained.")
        selected_style = style
    requested_intensity = min(
        _float(preferences.get("intensity"), intensity),
        _float(editing.get("motion_intensity"), intensity),
    )
    adjustments: list[dict[str, Any]] = []
    if selected_style != style:
        adjustments.append(
            {
                "system": "motion",
                "field": "motion_style",
                "previous": style,
                "value": selected_style,
                "reason": "Profile motion style preference.",
                "applied": True,
            }
        )
    if round(requested_intensity, 3) != round(intensity, 3):
        adjustments.append(
            {
                "system": "motion",
                "field": "intensity",
                "previous": intensity,
                "value": requested_intensity,
                "reason": "Profile motion intensity, still subject to safety validation.",
                "applied": True,
            }
        )
    result = _application(
        directives,
        system="motion",
        adjustments=adjustments,
        warnings=warnings,
    )
    result.update(
        {
            "style": selected_style,
            "intensity": requested_intensity,
            "intensity_label": _intensity_label(requested_intensity),
            "avoided_styles": sorted(avoided),
            "avoided_effects": [str(item) for item in _list(editing.get("avoid_effects"))],
            "avoid_flash": True,
            "avoid_shake": preferences.get("avoid_shake") is not False,
        }
    )
    return result


def rerank_title_candidates(
    titles: list[_TitleCandidate], directives: dict[str, Any] | None
) -> tuple[list[_TitleCandidate], dict[str, Any]]:
    if not directives or not titles:
        return titles, empty_application()
    preferences = _dict(directives.get("upload_metadata"))
    learned = _dict(directives.get("learned_patterns"))
    liked = {str(value) for value in _list(learned.get("liked_title_patterns"))}
    disliked = {str(value) for value in _list(learned.get("disliked_title_patterns"))}
    curiosity = preferences.get("prefer_curiosity_titles") is True
    emotional = preferences.get("prefer_emotional_titles") is True
    avoid_generic = preferences.get("avoid_generic_titles") is not False

    def score(item: Mapping[str, Any]) -> float:
        pattern = str(item.get("pattern") or "")
        value = _float(item.get("truth_score")) * 2 + _float(item.get("clarity_score"))
        if curiosity:
            value += _float(item.get("curiosity_score")) * 0.8
        if emotional and pattern in {"emotional", "story", "transformation"}:
            value += 0.35
        if pattern in liked:
            value += 0.25
        if pattern in disliked:
            value -= 0.4
        if avoid_generic and pattern in {"niche_fallback", "context"}:
            value -= 0.3
        return value

    ranked = sorted(titles, key=score, reverse=True)
    changed = ranked[0].get("text") != titles[0].get("text")
    adjustments = (
        [
            {
                "system": "upload_metadata",
                "field": "title_variants",
                "previous": titles[0].get("text"),
                "value": ranked[0].get("text"),
                "reason": "Profile title style reranked truthful candidates.",
                "applied": True,
            }
        ]
        if changed
        else []
    )
    result = _application(
        directives,
        system="upload_metadata",
        adjustments=adjustments,
        reasons=[
            "Truth and safety stayed primary while title candidates were preference-ranked."
        ],
    )
    result.update(
        {
            "title_style": preferences.get("title_style") or "clear",
            "description_style": preferences.get("description_style") or "concise",
            "hashtag_style": preferences.get("hashtag_style") or "focused",
            "variant_reranking_reason": (
                "creator preferences changed the top truthful variant"
                if changed
                else "existing top truthful variant already matched the profile"
            ),
            "hashtags_added": [],
            "hashtags_removed": [],
            "emoji_allowed": preferences.get("emoji_allowed") is True,
        }
    )
    return ranked, result


def personalize_hashtags(
    hashtags: list[str],
    directives: dict[str, Any] | None,
    *,
    relevant_terms: list[str],
    limit: int,
) -> tuple[list[str], list[str], list[str]]:
    if not directives:
        return hashtags[:limit], [], []
    preferences = _dict(directives.get("upload_metadata"))
    banned = {str(tag).lower().lstrip("#") for tag in _list(preferences.get("banned_hashtags"))}
    preferred = [str(tag) for tag in _list(preferences.get("preferred_hashtags"))]
    terms = {str(term).lower().replace("_", "") for term in relevant_terms}
    output: list[str] = []
    removed: list[str] = []
    for tag in hashtags:
        key = tag.lower().lstrip("#")
        if key in banned:
            removed.append(tag)
        elif key not in {item.lower().lstrip("#") for item in output}:
            output.append(tag)
    added: list[str] = []
    for raw in preferred:
        tag = raw if raw.startswith("#") else f"#{raw}"
        key = tag.lower().lstrip("#")
        if key in banned or key not in terms:
            continue
        if key not in {item.lower().lstrip("#") for item in output}:
            output.append(tag)
            added.append(tag)
    if len(output) > limit:
        removed.extend(output[limit:])
        output = output[:limit]
    return output, added, removed


def combine_applications(*applications: dict[str, Any]) -> dict[str, Any]:
    available = [item for item in applications if _dict(item).get("profile_id")]
    if not available:
        return empty_application()
    first = available[0]
    adjustments = [
        adjustment
        for item in available
        for adjustment in _list(item.get("adjustments"))
    ]
    affected = list(
        dict.fromkeys(
            system
            for item in available
            for system in _list(item.get("affected_systems"))
            if system in _SYSTEMS
        )
    )
    return {
        "version": "2",
        "profile_id": first.get("profile_id"),
        "profile_name": first.get("profile_name"),
        "applied": bool(affected),
        "confidence": max(_float(item.get("confidence")) for item in available),
        "affected_systems": affected,
        "adjustments": adjustments,
        "warnings": list(
            dict.fromkeys(
                str(warning)
                for item in available
                for warning in _list(item.get("warnings"))
                if warning
            )
        ),
        "reasons": list(
            dict.fromkeys(
                str(reason)
                for item in available
                for reason in _list(item.get("reasons"))
                if reason
            )
        ),
    }

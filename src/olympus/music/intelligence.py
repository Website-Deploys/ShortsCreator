"""Deterministic Story/Virality/Trend-aware music decisions and selection."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from olympus.personalization import apply as P  # noqa: N812
from olympus.platform.config import get_settings


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _niche(blueprint: dict[str, Any]) -> str:
    research = _dict(
        blueprint.get("internet_trend_research_v2") or blueprint.get("viral_research_snapshot")
    )
    detected = _dict(research.get("detected_niche"))
    niche = _dict(blueprint.get("content_niche"))
    metadata = _dict(blueprint.get("v2_metadata"))
    metadata_niche = _dict(metadata.get("content_niche"))
    return (
        _str(detected.get("primary"))
        or _str(niche.get("primary"))
        or _str(metadata_niche.get("primary"))
        or _str(metadata.get("content_category"))
        or "unknown_mixed"
    ).lower().replace(" ", "_")


def _speech_metrics(duration: float, bundle: dict[str, Any]) -> tuple[float, float]:
    captions = _list(_dict(bundle.get("caption_timing")).get("captions"))
    spoken = sum(
        max(0.0, _float(_dict(item).get("end")) - _float(_dict(item).get("start")))
        for item in captions
    )
    silences = _list(_dict(bundle.get("silence_detection")).get("silences"))
    silent = sum(
        max(0.0, _float(_dict(item).get("end")) - _float(_dict(item).get("start")))
        for item in silences
    )
    if duration <= 0:
        return 0.0, 0.0
    return round(_clamp(spoken / duration, 0.0, 1.0), 3), round(
        _clamp(silent / duration, 0.0, 1.0), 3
    )


def _profile(niche: str, story_shape: str, requested_mood: str) -> dict[str, Any]:
    combined = " ".join((niche, story_shape, requested_mood)).lower()
    if any(token in combined for token in ("music_singing", "singing", "music_performance")):
        return {
            "role": "none",
            "mood": "none",
            "energy": 0.0,
            "intensity": 0.0,
            "tempo": [0, 0],
            "genres": [],
            "avoid": ["all_background_music"],
        }
    if any(token in combined for token in ("emotional", "grief", "vulnerable", "reflection")):
        return {
            "role": "emotional_bed",
            "mood": "emotional",
            "energy": 0.35,
            "intensity": 0.35,
            "tempo": [60, 100],
            "genres": ["ambient", "cinematic", "piano"],
            "avoid": ["aggressive", "playful"],
        }
    if any(token in combined for token in ("gaming", "stream", "reaction")):
        return {
            "role": "gaming_energy",
            "mood": "intense",
            "energy": 0.82,
            "intensity": 0.78,
            "tempo": [110, 160],
            "genres": ["electronic", "pulse"],
            "avoid": ["sad_piano"],
        }
    if any(token in combined for token in ("comedy", "funny", "entertainment")):
        return {
            "role": "playful_energy",
            "mood": "playful",
            "energy": 0.65,
            "intensity": 0.58,
            "tempo": [90, 140],
            "genres": ["playful", "light_electronic"],
            "avoid": ["heavy_cinematic"],
        }
    if any(
        token in combined
        for token in (
            "motivational",
            "business",
            "money",
            "self_improvement",
            "pain_transformation",
        )
    ):
        return {
            "role": "motivational_drive",
            "mood": "motivational",
            "energy": 0.72,
            "intensity": 0.68,
            "tempo": [90, 140],
            "genres": ["cinematic", "electronic", "inspirational"],
            "avoid": ["comedy", "novelty"],
        }
    if any(token in combined for token in ("education", "tutorial", "how_to", "explainer")):
        return {
            "role": "educational_focus",
            "mood": "focused",
            "energy": 0.42,
            "intensity": 0.35,
            "tempo": [80, 120],
            "genres": ["ambient", "minimal", "lofi"],
            "avoid": ["dramatic", "busy"],
        }
    if any(token in combined for token in ("news", "debate", "argument", "commentary", "serious")):
        return {
            "role": "cinematic_tension",
            "mood": "mysterious",
            "energy": 0.46,
            "intensity": 0.42,
            "tempo": [70, 115],
            "genres": ["ambient", "cinematic", "minimal"],
            "avoid": ["manipulative", "playful"],
        }
    return {
        "role": "subtle_bed",
        "mood": "neutral",
        "energy": 0.32,
        "intensity": 0.28,
        "tempo": [70, 110],
        "genres": ["ambient", "minimal"],
        "avoid": ["busy", "vocal"],
    }


def _gain_for(role: str, speech_density: float) -> float:
    ranges = {
        "subtle_bed": (-28.0, -22.0),
        "educational_focus": (-26.0, -20.0),
        "motivational_drive": (-22.0, -16.0),
        "emotional_bed": (-26.0, -20.0),
        "gaming_energy": (-22.0, -16.0),
        "playful_energy": (-24.0, -18.0),
        "cinematic_tension": (-27.0, -21.0),
    }
    low, high = ranges.get(role, (-28.0, -20.0))
    position = 0.35 if speech_density >= 0.72 else 0.55
    return round(low + (high - low) * position, 1)


def plan_music_intelligence(
    *,
    clip: dict[str, Any],
    blueprint: dict[str, Any],
    bundle: dict[str, Any],
    project_id: str | None,
) -> dict[str, Any]:
    duration = _float(clip.get("duration"))
    clip_id = _str(clip.get("clip_id"))
    story = _dict(blueprint.get("story_v2_guidance"))
    story_editing = _dict(story.get("editing_guidance"))
    storytelling = _dict(blueprint.get("storytelling_v2"))
    hook = _dict(blueprint.get("hook_analysis_v2")) or _dict(blueprint.get("hook_v2"))
    ending = _dict(blueprint.get("ending_payoff_v2"))
    trend = _dict(blueprint.get("trend_match_v2"))
    editing_trend = _dict(blueprint.get("editing_trend_guidance"))
    planning_music = _dict(blueprint.get("music_decision_v2"))
    speech_density, silence_ratio = _speech_metrics(duration, bundle)
    niche = _niche(blueprint)
    story_shape = _str(story.get("story_shape") or storytelling.get("story_shape"))
    requested_mood = _str(
        story_editing.get("music_mood")
        or editing_trend.get("music_mood")
        or planning_music.get("category")
    )
    profile = _profile(niche, story_shape, requested_mood)
    source_is_music = profile["role"] == "none"
    settings = get_settings().music_intelligence
    user_disabled = planning_music.get("status") == "disabled" or not settings.enabled
    too_short = duration > 0 and duration < 4.0
    should_use = not (source_is_music or user_disabled or too_short)
    disabled_reason = (
        "source_is_music_performance"
        if source_is_music
        else "user_disabled"
        if user_disabled
        else "speech_clarity_risk"
        if too_short
        else None
    )
    reason = (
        "Background music is disabled because source performance audio is primary."
        if source_is_music
        else "Background music is disabled by the project setting."
        if user_disabled
        else "The clip is too short for a bed without distracting from speech."
        if too_short
        else (
            f"Use a {profile['role'].replace('_', ' ')} matched to the "
            f"{niche.replace('_', ' ')} clip and its "
            f"{story_shape.replace('_', ' ') or 'spoken'} story."
        )
    )
    payoff_at = max(0.0, duration - 2.0) if duration else None
    trend_patterns = [
        _str(_dict(item).get("label") or _dict(item).get("pattern_id"))
        for item in _list(trend.get("matched_patterns"))
        if _dict(item)
    ]
    decision_seed = f"{project_id}|{clip_id}|{niche}|{story_shape}|{profile['role']}"
    decision_id = "music_" + hashlib.sha256(decision_seed.encode()).hexdigest()[:16]
    gain = _gain_for(profile["role"], speech_density) if should_use else None
    personalization_settings = get_settings().creator_personalization
    music_personalization = P.music_personalization(
        _dict(blueprint.get("personalization_directives_v2")) or None
        if personalization_settings.apply_to_music
        else None,
        target_mood=_str(profile.get("mood")),
        gain_db=gain,
        source_is_music=source_is_music,
    )
    profile["mood"] = music_personalization.get("target_mood") or profile["mood"]
    gain = music_personalization.get("gain_db")
    if (
        music_personalization.get("music_presence") == "none"
        and not source_is_music
        and should_use
    ):
        should_use = False
        disabled_reason = "creator_profile_disabled"
        reason = "Background music is disabled by the active creator profile."
        gain = None
    ducking = bool(should_use and settings.enable_ducking and speech_density >= 0.2)
    return {
        "version": "2",
        "music_decision_id": decision_id,
        "clip_id": clip_id,
        "project_id": project_id,
        "created_at": datetime.now(UTC).isoformat(),
        "input_signals": {
            "story_shape": story_shape or None,
            "emotional_arc": requested_mood or None,
            "content_niche": niche,
            "hook_category": _str(hook.get("category")) or None,
            "payoff_type": _str(story.get("ending_reason") or ending.get("ending_type")) or None,
            "trend_patterns": trend_patterns,
            "virality_score": _float(_dict(blueprint.get("viral_score_v2")).get("overall"), 0.0),
            "speech_density": speech_density,
            "silence_ratio": silence_ratio,
            "source_audio_type": "music_performance" if source_is_music else "speech",
            "existing_music_risk": "unknown",
            "user_preferences": {
                "music_enabled": not user_disabled,
                "creator_profile_id": music_personalization.get("profile_id"),
            },
        },
        "decision": {
            "should_use_music": should_use,
            "reason": reason,
            "disabled_reason": disabled_reason,
            "music_role": profile["role"],
            "target_mood": profile["mood"],
            "target_energy": profile["energy"],
            "target_intensity": profile["intensity"],
            "target_tempo_range": profile["tempo"],
            "target_genres": profile["genres"],
            "avoid_genres": profile["avoid"],
            "vocal_music_allowed": False,
            "instrumental_required": True,
            "confidence": 0.82 if niche != "unknown_mixed" else 0.62,
        },
        "selected_asset": None,
        "asset_scores": [],
        "mix_plan": {
            "voice_priority": True,
            "music_gain_db": gain,
            "ducking_enabled": ducking,
            "ducking_threshold": settings.ducking_threshold_db,
            "ducking_ratio": settings.ducking_ratio,
            "fade_in_seconds": settings.fade_in_seconds,
            "fade_out_seconds": settings.fade_out_seconds,
            "loop_strategy": "pending_asset_resolution" if should_use else "none",
            "trim_strategy": "safe_default" if should_use else "none",
            "hook_swell": False,
            "payoff_swell": bool(
                should_use and settings.enable_payoff_swell and payoff_at is not None
            ),
            "silence_under_key_words": False,
            "warnings": [
                "Existing source music detection is unavailable; source conflict risk is unknown."
            ],
        },
        "ducking_plan": {
            "enabled": ducking,
            "method": "ffmpeg_sidechaincompress" if ducking else "none",
            "speech_segments_used": len(_list(_dict(bundle.get("caption_timing")).get("captions"))),
            "reduction_db": settings.ducking_reduction_db,
            "attack_ms": settings.ducking_attack_ms,
            "release_ms": settings.ducking_release_ms,
            "warnings": [],
        },
        "music_preparation": {
            "source_duration": None,
            "target_duration": duration,
            "loop_strategy": "pending_asset_resolution" if should_use else "none",
            "trim_strategy": "safe_default" if should_use else "none",
            "fade_in": settings.fade_in_seconds,
            "fade_out": settings.fade_out_seconds,
            "crossfade_used": False,
            "hook_alignment": "gentle_entry" if should_use else "none",
            "payoff_alignment": payoff_at,
            "warnings": [],
        },
        "music_story_events": {
            "hook_event": {
                "enabled": bool(should_use and settings.enable_hook_music_event),
                "time": 0.0,
                "type": "gentle_energy_entry",
            },
            "tension_events": [],
            "turn_event": None,
            "payoff_event": {
                "enabled": bool(should_use and settings.enable_payoff_swell),
                "time": payoff_at,
                "gain_change_db": 1.5,
                "type": "soft_swell",
            }
            if payoff_at is not None
            else None,
            "ending_event": {"type": "fade_under_ending", "time": duration},
            "warnings": [],
        },
        "audio_analysis": {
            "source_loudness": None,
            "source_peak": None,
            "speech_density": speech_density,
            "silence_ratio": silence_ratio,
            "music_loudness": None,
            "music_peak": None,
            "existing_music_risk": "unknown",
            "clipping_risk": "unknown",
            "warnings": ["No source-separation or existing-music detector is configured."],
        },
        "validation": {
            "music_mixed": False,
            "music_audible": "not_rendered",
            "speech_clarity_passed": "not_rendered",
            "audio_video_sync_passed": None,
            "duration_passed": None,
            "loudness_summary": None,
            "warnings": [],
        },
        "music_personalization": music_personalization,
    }


def _asset_score(
    asset: dict[str, Any],
    intelligence: dict[str, Any],
    usage_counts: dict[str, int],
) -> dict[str, Any]:
    decision = _dict(intelligence.get("decision"))
    signals = _dict(intelligence.get("input_signals"))
    moods = set(_list(asset.get("mood_tags")))
    genres = set(_list(asset.get("genre_tags")))
    niches = set(_list(asset.get("niche_tags")))
    target_mood = _str(decision.get("target_mood")).lower()
    targets = {target_mood, *_list(decision.get("target_genres"))}
    mood = 1.0 if target_mood in moods else min(1.0, len(targets & (moods | genres)) / 2)
    energy = 1.0 - min(
        1.0,
        abs(
            _float(asset.get("energy_level"), 0.5)
            - _float(decision.get("target_energy"), 0.5)
        ),
    )
    tempo_range = _list(decision.get("target_tempo_range"))
    bpm = _float(asset.get("bpm"))
    tempo = 0.5
    if len(tempo_range) == 2 and bpm:
        low, high = _float(tempo_range[0]), _float(tempo_range[1])
        tempo = (
            1.0
            if low <= bpm <= high
            else max(0.0, 1.0 - min(abs(bpm - low), abs(bpm - high)) / 60)
        )
    speech_safe = (
        1.0
        if asset.get("speech_safe") is True and asset.get("has_vocals") is not True
        else 0.0
    )
    loopable = 1.0 if asset.get("loopable") is True else 0.35
    target_duration = _float(_dict(intelligence.get("music_preparation")).get("target_duration"))
    asset_duration = _float(asset.get("duration"))
    duration_fit = (
        1.0
        if asset_duration >= target_duration
        else 0.75
        if asset.get("loopable")
        else 0.0
    )
    license_score = 1.0 if asset.get("automatic_use_allowed") else 0.0
    niche = _str(signals.get("content_niche")).lower()
    niche_fit = 1.0 if niche in niches else 0.5
    trend_fit = min(1.0, len(_list(signals.get("trend_patterns"))) * 0.2)
    folder_type = _str(asset.get("folder_type")).lower()
    folder_priority = {
        "curated": 1.0,
        "user": 0.65,
        "generated": 0.15,
    }.get(folder_type, 0.0)
    quality = 1.0 if asset.get("quality_status") == "passed" else 0.0
    reuse = int(usage_counts.get(_str(asset.get("asset_id")), 0)) + int(
        _float(asset.get("usage_count"), 0.0)
    )
    personalization = _dict(intelligence.get("music_personalization"))
    reuse_rate = 0.08 if personalization.get("avoid_reuse") is True else 0.04
    repetition_penalty = min(0.3, reuse * reuse_rate)
    overall = _clamp(
        mood * 0.28
        + energy * 0.12
        + tempo * 0.08
        + speech_safe * 0.12
        + loopable * 0.06
        + duration_fit * 0.06
        + license_score * 0.12
        + niche_fit * 0.04
        + trend_fit * 0.02
        + folder_priority * 0.07
        + quality * 0.03
        - repetition_penalty,
        0.0,
        1.0,
    )
    return {
        "asset_id": asset.get("asset_id"),
        "overall": round(overall, 3),
        "mood": round(mood, 3),
        "energy": round(energy, 3),
        "tempo": round(tempo, 3),
        "speech_safe": round(speech_safe, 3),
        "loopable": round(loopable, 3),
        "duration_fit": round(duration_fit, 3),
        "license": round(license_score, 3),
        "trend_fit": round(trend_fit, 3),
        "folder_priority": round(folder_priority, 3),
        "quality": round(quality, 3),
        "repetition_penalty": round(repetition_penalty, 3),
        "explanation": (
            "weighted mood, energy, tempo, speech safety, duration, license, "
            "niche, trend, curated-library priority, quality, and reuse match"
        ),
    }


def resolve_music_intelligence(
    intelligence: dict[str, Any],
    safe_assets: list[dict[str, Any]],
    *,
    rejected_assets: list[dict[str, Any]] | None = None,
    usage_counts: dict[str, int] | None = None,
    library_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = deepcopy(intelligence)
    decision = _dict(resolved.get("decision"))
    if not decision.get("should_use_music"):
        return resolved
    usage = usage_counts or {}
    target_mood = _str(decision.get("target_mood")).lower()
    exact_mood_assets = [
        asset
        for asset in safe_assets
        if target_mood and target_mood in set(_list(asset.get("mood_tags")))
    ]
    exact_curated = [
        asset
        for asset in exact_mood_assets
        if _str(asset.get("folder_type")).lower() == "curated"
    ]
    exact_user = [
        asset
        for asset in exact_mood_assets
        if _str(asset.get("folder_type")).lower() == "user"
    ]
    candidates = exact_curated or exact_user or exact_mood_assets or safe_assets
    curated_assets = [
        asset
        for asset in safe_assets
        if _str(asset.get("folder_type")).lower() == "curated"
    ]
    generated_assets = [
        asset
        for asset in safe_assets
        if _str(asset.get("folder_type")).lower() == "generated"
    ]
    library = library_metadata or {}
    library_selection = {
        "library_version": _str(library.get("version")) or "unknown",
        "asset_pool_size": len(safe_assets),
        "curated_assets_available": len(curated_assets),
        "generated_assets_available": len(generated_assets),
        "selected_priority_tier": None,
        "rejected_assets_considered": len(rejected_assets or []),
        "selection_reason": None,
    }
    resolved["music_library_selection"] = library_selection
    scores = [_asset_score(asset, resolved, usage) for asset in candidates]
    scores.sort(
        key=lambda item: (_float(item.get("overall")), _str(item.get("asset_id"))),
        reverse=True,
    )
    resolved["asset_scores"] = scores
    if not scores:
        decision.update(
            {
                "should_use_music": False,
                "disabled_reason": "no_safe_asset",
                "reason": (
                    "Music was planned but disabled because no verified safe local asset exists."
                ),
            }
        )
        resolved["selected_asset"] = None
        _dict(resolved.get("mix_plan"))["warnings"] = [
            "No safe_default asset with verified license and an existing file was available."
        ]
        resolved["asset_rejections"] = [
            {
                "asset_id": item.get("asset_id"),
                "reasons": item.get("rejection_reasons") or [],
            }
            for item in rejected_assets or []
        ]
        library_selection["selection_reason"] = (
            "No asset passed file, license, quality, speech-safety, and automatic-use rules."
        )
        return resolved
    selected_score = scores[0]
    selected = next(
        item for item in candidates if item.get("asset_id") == selected_score.get("asset_id")
    )
    preparation = _dict(resolved.get("music_preparation"))
    target_duration = _float(preparation.get("target_duration"))
    source_duration = _float(selected.get("duration"))
    loop_strategy = "no_loop_needed" if source_duration >= target_duration else "simple_loop"
    preparation.update(
        {
            "source_duration": source_duration or None,
            "loop_strategy": loop_strategy,
            "trim_strategy": "start_at_beginning",
            "crossfade_used": False,
            "warnings": []
            if loop_strategy == "no_loop_needed"
            else ["A deterministic simple loop is used; no beat-level seam analysis is claimed."],
        }
    )
    mix = _dict(resolved.get("mix_plan"))
    settings = get_settings().music_intelligence
    recommended = selected.get("recommended_gain_db")
    planned_gain = _float(mix.get("music_gain_db"), settings.default_music_gain_db)
    if recommended is not None:
        planned_gain = _clamp(
            _float(recommended, planned_gain),
            planned_gain - 2.0,
            planned_gain + 2.0,
        )
    mix["music_gain_db"] = round(
        _clamp(planned_gain, settings.min_music_gain_db, settings.max_music_gain_db), 1
    )
    mix["loop_strategy"] = loop_strategy
    mix["trim_strategy"] = preparation["trim_strategy"]
    selected_asset = {
        **{key: value for key, value in selected.items() if key != "rejection_reasons"},
        "energy": selected.get("energy_level"),
        "loopable": bool(selected.get("loopable")),
        "selection_reason": (
            f"Selected {selected.get('title')} from the "
            f"{selected.get('folder_type') or 'unknown'} tier with score "
            f"{selected_score['overall']:.3f}; {selected_score['explanation']}."
        ),
        "score": selected_score,
    }
    resolved["selected_asset"] = selected_asset
    selected_tier = _str(selected.get("folder_type")).lower() or "unknown"
    library_selection["selected_priority_tier"] = selected_tier
    if selected_tier == "curated":
        library_selection["selection_reason"] = (
            "A verified curated production asset matched the requested mood."
        )
    elif selected_tier == "user":
        library_selection["selection_reason"] = (
            "No curated mood match was available; a verified user asset was selected."
        )
    elif selected_tier == "generated":
        library_selection["selection_reason"] = (
            "No curated or verified user mood match was available; a generated "
            "validation asset was used as fallback."
        )
        mix_warnings = _list(mix.get("warnings"))
        mix["warnings"] = [
            *mix_warnings,
            "Generated validation asset used because no curated production match exists.",
        ]
    else:
        library_selection["selection_reason"] = (
            "Selected the highest-scoring safe local asset."
        )
    analysis = _dict(resolved.get("audio_analysis"))
    analysis.update(
        {
            "music_loudness": selected.get("integrated_loudness_lufs"),
            "music_peak": selected.get("peak_dbfs"),
            "clipping_risk": "low" if mix["music_gain_db"] <= -14.0 else "review",
        }
    )
    return resolved

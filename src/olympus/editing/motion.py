"""Story-driven, bounded Motion Graphics / Effects V2 planning.

The planner is intentionally deterministic and asset-free. It translates existing
Story, Virality, Trend, Planning, Caption, Music, SFX, face, and layout signals into
an executable set of FFmpeg-native motion events. Unsupported duration-changing or
flash effects are never emitted.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from olympus.editing import timeline as T  # noqa: N812 (module alias is intentional)
from olympus.personalization import apply as P  # noqa: N812
from olympus.platform.config import get_settings

_ZOOM_EFFECTS = {
    "hook_punch_in",
    "subtle_push_in",
    "reaction_zoom",
    "payoff_hold",
    "quote_hold",
    "pattern_interrupt_zoom",
    "sfx_sync_punch",
}
_DURATION_CHANGING_EFFECTS = {"speed_ramp", "freeze_frame"}
_FLASH_EFFECTS = {"impact_flash_safe", "flash", "strobe"}


def _primary_niche(blueprint: dict[str, Any]) -> str:
    niche = T.as_dict(blueprint.get("content_niche"))
    metadata = T.as_dict(blueprint.get("v2_metadata"))
    value = T.as_str(niche.get("primary") or metadata.get("content_category") or "unknown")
    return value.lower().replace("-", "_").replace(" ", "_")


def select_motion_style(
    *,
    niche: str,
    story_shape: str = "",
    hook_category: str = "",
) -> tuple[str, str, float, str]:
    """Return style, intensity label, numeric intensity, and selection reason."""

    signal = " ".join((niche, story_shape, hook_category)).lower().replace("-", "_")
    if any(token in signal for token in ("music", "singing", "performance")):
        return (
            "music_performance_minimal",
            "minimal",
            0.2,
            "Performance content keeps motion minimal so vocals and the performer stay primary.",
        )
    if any(token in signal for token in ("gaming", "stream", "reaction")):
        return (
            "gaming_reactive",
            "medium_high",
            0.72,
            "Gaming or reaction content supports faster but bounded reaction motion.",
        )
    if any(token in signal for token in ("comedy", "funny", "punchline")):
        return (
            "comedy_pop",
            "medium",
            0.62,
            "Comedy benefits from selective punchline and reaction emphasis.",
        )
    if any(token in signal for token in ("education", "tutorial", "explainer", "how_to")):
        return (
            "educational_clarity",
            "low_medium",
            0.42,
            "Educational motion stays subordinate to captions and comprehension.",
        )
    if any(token in signal for token in ("emotional", "confession", "personal_story")):
        return (
            "emotional_cinematic",
            "low_medium",
            0.38,
            "Emotional storytelling uses restrained pushes and a calm landing.",
        )
    if any(token in signal for token in ("motivational", "motivation", "self_improvement")):
        return (
            "motivational_dynamic",
            "medium",
            0.6,
            "Motivational content supports a strong hook and deliberate payoff emphasis.",
        )
    if any(token in signal for token in ("news", "serious", "commentary", "analysis")):
        return (
            "cinematic_tension",
            "low",
            0.3,
            "Serious commentary uses restrained motion and avoids manipulative effects.",
        )
    if any(token in signal for token in ("podcast", "interview", "conversation")):
        return (
            "clean_podcast",
            "low",
            0.3,
            "Podcast motion stays clean and only emphasizes strong spoken moments.",
        )
    return (
        "default_clean",
        "low_medium",
        0.4,
        "Conservative default motion is used because no stronger style signal is available.",
    )


def _relative_time(value: Any, clip: dict[str, Any]) -> float | None:
    if not isinstance(value, int | float):
        return None
    timestamp = float(value)
    duration = T.as_float(clip.get("duration"))
    source_start = T.as_float(clip.get("source_start"))
    source_end = T.as_float(clip.get("source_end"), source_start + duration)
    if source_start <= timestamp <= source_end:
        return T.round3(timestamp - source_start)
    if 0.0 <= timestamp <= duration:
        return T.round3(timestamp)
    return None


def _time_from_dict(value: Any, clip: dict[str, Any]) -> float | None:
    item = T.as_dict(value)
    for key in ("time", "timestamp", "start", "payoff_start"):
        result = _relative_time(item.get(key), clip)
        if result is not None:
            return result
    return None


def _effect(
    effect_type: str,
    start: float,
    end: float,
    *,
    intensity: float,
    scale: float,
    target_region: str,
    reason: str,
    source_signal: str,
    easing: str,
) -> dict[str, Any]:
    start = T.round3(start)
    end = T.round3(max(start, end))
    seed = f"{effect_type}|{start:.3f}|{end:.3f}|{source_signal}"
    effect_id = "motion_" + hashlib.sha256(seed.encode()).hexdigest()[:14]
    return {
        "id": effect_id,
        "effect_id": effect_id,
        "type": effect_type,
        "start": start,
        "end": end,
        "start_time": start,
        "end_time": end,
        "duration": T.round3(end - start),
        "intensity": T.round3(intensity),
        "scale": T.round3(scale),
        "target_region": target_region,
        "reason": reason,
        "source_signal": source_signal,
        "expected_filter": "zoompan",
        "safety_checked": False,
        "confidence": 0.78,
        "easing": easing,
        "evidence": [{"type": source_signal, "detail": reason}],
        "warnings": [],
    }


def _hook_effect(
    style: str,
    hook_category: str,
    duration: float,
    intensity: float,
) -> dict[str, Any] | None:
    if duration < 1.5:
        return None
    category = hook_category.lower().replace("-", "_")
    if style == "emotional_cinematic" or "confession" in category:
        return _effect(
            "subtle_push_in",
            0.0,
            min(duration, 2.2),
            intensity=min(intensity, 0.38),
            scale=1.055,
            target_region="primary_subject",
            reason="A restrained opening push supports the emotional hook without a harsh hit.",
            source_signal="virality_hook_category",
            easing="slow_push",
        )
    if style == "music_performance_minimal":
        return _effect(
            "subtle_push_in",
            0.0,
            min(duration, 2.4),
            intensity=0.18,
            scale=1.035,
            target_region="full_frame_safe",
            reason="A minimal opening push preserves the performance while avoiding a static crop.",
            source_signal="content_niche",
            easing="slow_push",
        )
    if style == "gaming_reactive":
        return _effect(
            "reaction_zoom",
            0.0,
            min(duration, 0.72),
            intensity=min(0.78, max(0.6, intensity)),
            scale=1.14,
            target_region="primary_subject",
            reason="The reaction hook receives one bounded zoom instead of repeated shake spam.",
            source_signal="content_niche+hook_category",
            easing="fast_punch",
        )
    scale = 1.1 if style in {"clean_podcast", "educational_clarity"} else 1.125
    if category in {"curiosity_gap", "mistake_warning", "contrarian_truth", "payoff_first"}:
        reason = f"The {category.replace('_', ' ')} hook receives a clean first-beat punch-in."
    else:
        reason = "The faithful opening line receives one clean punch-in for immediate intent."
    return _effect(
        "hook_punch_in",
        0.0,
        min(duration, 0.82),
        intensity=min(0.72, max(0.42, intensity)),
        scale=scale,
        target_region="primary_subject",
        reason=reason,
        source_signal="virality_hook_category",
        easing="fast_punch",
    )


def _pattern_interrupt(
    style: str,
    clip: dict[str, Any],
    story_guidance: dict[str, Any],
    intensity: float,
) -> dict[str, Any] | None:
    if style in {
        "clean_podcast",
        "emotional_cinematic",
        "music_performance_minimal",
        "cinematic_tension",
    }:
        return None
    turn = _time_from_dict(story_guidance.get("turning_point"), clip)
    duration = T.as_float(clip.get("duration"))
    if turn is None or turn < 2.0 or turn > duration - 1.8:
        return None
    scale = 1.115 if style in {"gaming_reactive", "comedy_pop"} else 1.075
    return _effect(
        "pattern_interrupt_zoom",
        turn,
        min(duration, turn + 0.68),
        intensity=min(0.72, intensity),
        scale=scale,
        target_region="primary_subject",
        reason="Story V2 identifies a real turn, so one bounded crop change marks the beat.",
        source_signal="story_v2_turning_point",
        easing="quick_pulse",
    )


def _payoff_effect(
    style: str,
    clip: dict[str, Any],
    blueprint: dict[str, Any],
    story_guidance: dict[str, Any],
    intensity: float,
) -> dict[str, Any] | None:
    duration = T.as_float(clip.get("duration"))
    if duration < 4.0:
        return None
    closing = T.as_dict(blueprint.get("closing_payoff"))
    payoff_time = _time_from_dict(closing, clip)
    payoff_present = bool(
        story_guidance.get("payoff_present")
        or T.as_str(story_guidance.get("payoff"))
        or T.as_dict(blueprint.get("ending_payoff_v2")).get("payoff_present")
        or T.as_str(T.as_dict(blueprint.get("ending_payoff_v2")).get("ending_line"))
    )
    if not payoff_present:
        return None
    start = payoff_time if payoff_time is not None else max(0.0, duration - 2.1)
    start = min(max(0.0, start), max(0.0, duration - 0.8))
    effect_type = (
        "quote_hold"
        if style in {"emotional_cinematic", "motivational_dynamic"}
        else "payoff_hold"
    )
    return _effect(
        effect_type,
        start,
        max(start + 0.6, duration - 0.08),
        intensity=min(0.5, max(0.22, intensity)),
        scale=1.055 if style != "gaming_reactive" else 1.07,
        target_region="primary_subject",
        reason="The ending payoff gets a slow visual hold without extending or retiming audio.",
        source_signal="story_v2_payoff",
        easing="payoff_hold",
    )


def _maximum_effects(duration: float) -> int:
    settings = get_settings().motion_graphics
    if duration < 15.0:
        return settings.max_major_effects_under_15s
    if duration < 30.0:
        return settings.max_major_effects_under_30s
    return max(settings.max_major_effects_under_30s, 6)


def validate_motion_effects(
    effects: list[dict[str, Any]],
    *,
    duration: float,
    caption_safe: bool,
    face_safe: bool,
    layout_safe: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate and downgrade a motion plan before any FFmpeg command is built."""

    settings = get_settings().motion_graphics
    warnings: list[str] = []
    accepted: list[dict[str, Any]] = []
    last_major_start: float | None = None
    maximum = _maximum_effects(duration)
    for raw in sorted(effects, key=lambda item: T.as_float(item.get("start_time"))):
        effect = dict(raw)
        effect_type = T.as_str(effect.get("type"))
        start = T.as_float(effect.get("start_time"), T.as_float(effect.get("start")))
        end = T.as_float(effect.get("end_time"), T.as_float(effect.get("end")))
        if effect_type in _FLASH_EFFECTS:
            warnings.append(f"{effect_type} disabled because full-frame flash effects are off.")
            continue
        if effect_type in _DURATION_CHANGING_EFFECTS:
            warnings.append(
                f"{effect_type} disabled because duration-changing motion is unsupported."
            )
            continue
        if effect_type not in _ZOOM_EFFECTS:
            warnings.append(
                f"{effect_type or 'unknown effect'} disabled because no safe renderer exists."
            )
            continue
        if start < 0 or end <= start or end > duration + 0.001:
            warnings.append(f"{effect_type} disabled because its timestamps are outside the clip.")
            continue
        if len(accepted) >= maximum:
            warnings.append("Major effect limit reached; lower-priority effects were removed.")
            break
        if last_major_start is not None and start - last_major_start < 2.0:
            warnings.append(
                f"{effect_type} removed to keep at least 2 seconds between major effects."
            )
            continue
        effect["scale"] = T.round3(
            min(settings.max_zoom_scale, max(1.0, T.as_float(effect.get("scale"), 1.0)))
        )
        effect["safety_checked"] = True
        effect["warnings"] = list(effect.get("warnings") or [])
        accepted.append(effect)
        last_major_start = start

    caption_requirement_passed = caption_safe or not settings.require_caption_safety
    face_requirement_passed = face_safe or not settings.require_face_safety
    layout_requirement_passed = layout_safe or not settings.require_layout_safety
    safety_passed = bool(
        caption_requirement_passed and face_requirement_passed and layout_requirement_passed
    )
    if not caption_safe and settings.require_caption_safety:
        warnings.append("Caption collision safety was unavailable or failed.")
    if not face_safe and settings.require_face_safety:
        warnings.append("Face stability was insufficient for bounded motion.")
    if not layout_safe and settings.require_layout_safety:
        warnings.append("Complex layout disabled whole-frame motion.")
    if not safety_passed:
        accepted = []
    return accepted, {
        "passed": safety_passed,
        "flash_safe": True,
        "density_safe": len(accepted) <= maximum,
        "caption_safe": caption_safe,
        "face_safe": face_safe,
        "layout_safe": layout_safe,
        "duration_safe": True,
        "max_zoom_scale": settings.max_zoom_scale,
        "max_major_effects": maximum,
        "speed_ramps_enabled": False,
        "safe_flash_enabled": False,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _face_safety(face_plan: dict[str, Any]) -> tuple[bool, list[str]]:
    mode = T.as_str(face_plan.get("mode")) or "center_fallback"
    fallback = T.as_str(face_plan.get("fallback_reason"))
    warnings: list[str] = []
    if mode == "two_speaker_stack":
        return True, warnings
    if fallback and any(token in fallback for token in ("low_confidence", "sparse", "unstable")):
        warnings.append(
            "Face tracking is unstable; motion is disabled instead of risking a bad crop."
        )
        return False, warnings
    if mode in {"single_face_tracking", "active_speaker_focus", "multi_face_safe_frame"}:
        keyframes = T.as_list(face_plan.get("crop_keyframes"))
        return len(keyframes) >= 2, warnings
    input_analysis = T.as_dict(face_plan.get("input_analysis"))
    if input_analysis.get("face_tracking_available") is False:
        warnings.append(
            "Face detection was unavailable; motion is skipped instead of claiming face safety."
        )
        return False, warnings
    if (
        input_analysis.get("face_tracking_available") is True
        and input_analysis.get("detected_face_count") == 0
    ):
        return True, warnings
    warnings.append("Face safety could not be verified; only a no-face analysis can waive it.")
    return False, warnings


def build_motion_intelligence(
    *,
    clip: dict[str, Any],
    blueprint: dict[str, Any],
    caption_intelligence: dict[str, Any],
    music_intelligence: dict[str, Any],
    face_plan: dict[str, Any],
    sfx_plan: dict[str, Any],
    project_id: str | None = None,
) -> dict[str, Any]:
    """Build the complete JSON-safe Motion Graphics / Effects V2 contract."""

    settings = get_settings().motion_graphics
    duration = T.as_float(clip.get("duration"))
    story = T.as_dict(blueprint.get("story_v2_guidance"))
    story_shape = T.as_str(
        story.get("story_shape") or T.as_dict(blueprint.get("storytelling_v2")).get("story_shape")
    )
    hook = T.as_dict(blueprint.get("hook_analysis_v2")) or T.as_dict(
        blueprint.get("hook_v2")
    )
    hook_category = T.as_str(hook.get("category"))
    niche = _primary_niche(blueprint)
    style, intensity_label, intensity, style_reason = select_motion_style(
        niche=niche,
        story_shape=story_shape,
        hook_category=hook_category,
    )
    personalization_settings = get_settings().creator_personalization
    motion_personalization = P.motion_personalization(
        T.as_dict(blueprint.get("personalization_directives_v2")) or None
        if personalization_settings.apply_to_motion
        else None,
        style=style,
        intensity=intensity,
    )
    style = T.as_str(motion_personalization.get("style")) or style
    intensity = T.as_float(motion_personalization.get("intensity"), intensity)
    intensity_label = T.as_str(
        motion_personalization.get("intensity_label")
    ) or intensity_label
    if motion_personalization.get("applied"):
        style_reason = f"{style_reason} The active creator profile adjusted motion style."
    caption_safe_zone = T.as_dict(caption_intelligence.get("caption_safe_zone"))
    caption_safe = bool(
        caption_safe_zone.get("strategy")
        and T.as_str(caption_safe_zone.get("collision_risk")) != "high"
    )
    face_safe, face_warnings = _face_safety(face_plan)
    layout_mode = T.as_str(face_plan.get("mode")) or "center_fallback"
    layout_safe = layout_mode != "two_speaker_stack"
    source_motion = T.as_str(
        T.as_dict(blueprint.get("source_motion")).get("level")
        or T.as_dict(blueprint.get("v2_metadata")).get("source_motion_level")
    ) or "unknown"
    disabled_reason: str | None = None
    if not settings.enabled:
        disabled_reason = "user_disabled"
    elif intensity <= 0.05:
        disabled_reason = "creator_profile_motion_disabled"
    elif duration < 1.5:
        disabled_reason = "clip_too_short"
    elif source_motion == "high":
        disabled_reason = "source_motion_high"
    elif layout_mode == "two_speaker_stack" and settings.require_layout_safety:
        disabled_reason = "layout_complexity"
    elif not face_safe and settings.require_face_safety:
        disabled_reason = "face_tracking_unstable"
    elif not caption_safe and settings.require_caption_safety:
        disabled_reason = "caption_collision_risk"

    effects: list[dict[str, Any]] = []
    if disabled_reason is None:
        hook_enabled = (
            settings.enable_subtle_push_in
            if style in {"emotional_cinematic", "music_performance_minimal"}
            else settings.enable_reaction_zoom
            if style == "gaming_reactive"
            else settings.enable_hook_punch_in
        )
        if hook_enabled:
            hook_effect = _hook_effect(style, hook_category, duration, intensity)
            if hook_effect:
                effects.append(hook_effect)
        if settings.enable_pattern_interrupts:
            interrupt = _pattern_interrupt(style, clip, story, intensity)
            if interrupt:
                effects.append(interrupt)
        if settings.enable_payoff_hold:
            payoff = _payoff_effect(style, clip, blueprint, story, intensity)
            if payoff:
                effects.append(payoff)

    avoided_effects = {
        T.as_str(item) for item in T.as_list(motion_personalization.get("avoided_effects"))
    }
    before_filter = len(effects)
    effects = [
        effect
        for effect in effects
        if T.as_str(effect.get("type")) not in avoided_effects
        and not (
            motion_personalization.get("avoid_shake") is True
            and "shake" in T.as_str(effect.get("type"))
        )
    ]
    if before_filter and not effects and disabled_reason is None:
        disabled_reason = "creator_profile_avoided_planned_effects"

    for effect in effects:
        effect_seed = (
            f"{clip.get('clip_id')}|{effect.get('type')}|"
            f"{effect.get('start_time')}|{effect.get('end_time')}"
        )
        effect_id = "motion_" + hashlib.sha256(effect_seed.encode()).hexdigest()[:14]
        effect["id"] = effect_id
        effect["effect_id"] = effect_id

    effects, safety = validate_motion_effects(
        effects,
        duration=duration,
        caption_safe=caption_safe,
        face_safe=face_safe,
        layout_safe=layout_safe,
    )
    if disabled_reason is None and not safety["passed"]:
        disabled_reason = "validation_failed"
    should_apply = bool(effects and disabled_reason is None)
    warnings = list(dict.fromkeys([*face_warnings, *T.as_list(safety.get("warnings"))]))
    if motion_personalization.get("applied") and disabled_reason:
        warnings.append(
            f"Profile motion was limited by {disabled_reason.replace('_', ' ')}."
        )
    motion_personalization["disabled_or_limited_reason"] = disabled_reason
    motion_personalization["warnings"] = list(
        dict.fromkeys(
            [
                *T.as_list(motion_personalization.get("warnings")),
                *warnings,
            ]
        )
    )
    safety["warnings"] = warnings
    hook_effect = next((item for item in effects if item["start_time"] <= 3.0), None)
    payoff_effect = next(
        (item for item in reversed(effects) if item["type"] in {"payoff_hold", "quote_hold"}),
        None,
    )
    patterns = [item for item in effects if item["type"] == "pattern_interrupt_zoom"]
    expected_filters = sorted(
        {T.as_str(item.get("expected_filter")) for item in effects if item.get("expected_filter")}
    )
    seed = f"{project_id}|{clip.get('clip_id')}|{style}|{hook_category}|{duration:.3f}"
    decision_id = "motion_" + hashlib.sha256(seed.encode()).hexdigest()[:16]
    caption_inputs = T.as_dict(caption_intelligence.get("input_signals"))
    music_decision = T.as_dict(music_intelligence.get("decision"))
    trend = T.as_dict(blueprint.get("trend_match_v2"))
    return {
        "version": "2",
        "motion_decision_id": decision_id,
        "clip_id": clip.get("clip_id"),
        "project_id": project_id,
        "created_at": datetime.now(UTC).isoformat(),
        "input_signals": {
            "story_shape": story_shape,
            "emotional_arc": story.get("emotional_arc"),
            "hook_category": hook_category,
            "payoff_type": T.as_dict(blueprint.get("ending_payoff_v2")).get("ending_type"),
            "content_niche": niche,
            "trend_patterns": [
                T.as_dict(item).get("label")
                for item in T.as_list(trend.get("matched_patterns"))
                if T.as_dict(item).get("label")
            ],
            "virality_score": T.as_dict(blueprint.get("viral_score_v2")).get("overall"),
            "speech_density": caption_inputs.get("speech_density"),
            "caption_style": T.as_dict(caption_intelligence.get("style_decision")).get(
                "caption_style"
            ),
            "music_role": music_decision.get("music_role"),
            "sfx_plan": sfx_plan,
            "face_tracking_mode": layout_mode,
            "multi_speaker_layout": layout_mode,
            "source_motion_level": source_motion,
        },
        "decision": {
            "should_apply_motion": should_apply,
            "motion_style": style,
            "intensity": intensity_label,
            "intensity_score": T.round3(intensity),
            "pacing_profile": T.as_dict(blueprint.get("editing_trend_guidance")).get(
                "pacing_style"
            ),
            "reason": style_reason
            if should_apply
            else f"Motion skipped safely: {disabled_reason or 'no justified effects'}.",
            "confidence": 0.84 if niche != "unknown" else 0.64,
            "disabled_reason": disabled_reason if not should_apply else None,
        },
        "effect_plan": {
            "effects": effects,
            "hook_effect": hook_effect,
            "pattern_interrupts": patterns,
            "transitions": [],
            "payoff_effect": payoff_effect,
            "safety_limits": {
                "major_effect_spacing_seconds": 2.0,
                "maximum_major_effects": _maximum_effects(duration),
                "max_zoom_scale": settings.max_zoom_scale,
                "flash_enabled": False,
                "speed_ramps_enabled": False,
            },
            "warnings": warnings,
        },
        "hook_motion_treatment": {
            "applied": hook_effect is not None,
            "hook_category": hook_category,
            "effect_type": hook_effect.get("type") if hook_effect else None,
            "start_time": hook_effect.get("start_time") if hook_effect else None,
            "end_time": hook_effect.get("end_time") if hook_effect else None,
            "target": hook_effect.get("target_region") if hook_effect else None,
            "intensity": hook_effect.get("intensity") if hook_effect else None,
            "reason": hook_effect.get("reason") if hook_effect else disabled_reason,
            "warnings": warnings,
        },
        "payoff_motion_treatment": {
            "applied": payoff_effect is not None,
            "payoff_type": T.as_dict(blueprint.get("ending_payoff_v2")).get("ending_type"),
            "effect_type": payoff_effect.get("type") if payoff_effect else None,
            "start_time": payoff_effect.get("start_time") if payoff_effect else None,
            "end_time": payoff_effect.get("end_time") if payoff_effect else None,
            "hold_duration": payoff_effect.get("duration") if payoff_effect else 0.0,
            "reason": payoff_effect.get("reason") if payoff_effect else disabled_reason,
            "warnings": warnings,
        },
        "motion_safety_validation": safety,
        "motion_personalization": motion_personalization,
        "render_plan": {
            "ffmpeg_filters_expected": expected_filters,
            "keyframes_count": len(effects) * 2,
            "effect_regions": [
                {
                    "effect_id": item["effect_id"],
                    "start_time": item["start_time"],
                    "end_time": item["end_time"],
                    "target_region": item["target_region"],
                }
                for item in effects
            ],
            "caption_safe": caption_safe,
            "face_safe": face_safe,
            "layout_safe": layout_safe,
            "duration_safe": True,
            "warnings": warnings,
        },
        "validation": {
            "effects_planned": len(effects),
            "effects_rendered": 0,
            "ffmpeg_filter_present": False,
            "output_exists": False,
            "sync_passed": None,
            "duration_passed": None,
            "safety_passed": safety["passed"],
            "warnings": warnings,
            "passed": False if effects else safety["passed"],
        },
    }

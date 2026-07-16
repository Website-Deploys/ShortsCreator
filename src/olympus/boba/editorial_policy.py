"""Advisory editorial policy generation for BOBA Core Brain V1."""

from __future__ import annotations

from typing import Any

from olympus.boba.contracts import BobaEditorialPolicyV1


def _number(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def create_editorial_policy(
    project_id: str,
    clip_id: str,
    clip: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> BobaEditorialPolicyV1:
    context = context or {}
    niche = str(clip.get("content_niche") or context.get("content_niche") or "general")
    hook_type = str(clip.get("hook_type") or clip.get("hook_category") or "clear_statement")
    emotion = _number(clip.get("emotional_strength") or clip.get("emotion"))
    hook = _number(clip.get("hook_strength") or clip.get("hook"))
    face_available = bool(
        clip.get("face_layout_available", context.get("face_layout_available", False))
    )
    transcript_available = bool(context.get("transcript_available", True))
    music_available = bool(context.get("music_available", True))
    safety_status = str(context.get("safety_status") or "unknown")
    manual_review = bool(context.get("manual_review_required"))

    if "podcast" in niche.lower():
        pacing = "balanced"
        policy_name = "clean_podcast_advisory"
    elif emotion >= 0.75 and hook >= 0.7:
        pacing = "fast"
        policy_name = "motivational_momentum_advisory"
    elif hook >= 0.8:
        pacing = "fast"
        policy_name = "hook_forward_advisory"
    else:
        pacing = "balanced"
        policy_name = "story_first_advisory"

    treatment = {
        "type": (
            "curiosity_caption"
            if "curiosity" in hook_type or "open" in hook_type
            else "punch_zoom" if hook >= 0.65 and face_available else "cold_open"
        ),
        "preserve_first_meaningful_word": True,
        "no_fake_hook_text": True,
    }
    warnings: list[str] = []
    if not transcript_available:
        warnings.append("Transcript unavailable; caption emphasis cannot be verified.")
    if not face_available:
        warnings.append("Face/layout signals unavailable; motion should use a stable fallback.")
    if manual_review or safety_status in {"blocked", "high", "unknown"}:
        warnings.append("Safety/manual review must be resolved outside BOBA before publishing.")
    if not music_available:
        warnings.append("No verified music readiness signal is available.")

    motion_style = "subtle_push_in" if face_available else "stable_center_fallback"
    return BobaEditorialPolicyV1(
        project_id=project_id,
        clip_id=clip_id,
        policy_name=policy_name,
        pacing=pacing,
        hook_treatment=treatment,
        caption_directives={
            "density": "medium" if pacing == "balanced" else "compact",
            "casing": "natural",
            "line_limit": 2,
            "emphasis_words": list(clip.get("caption_emphasis_words") or [])[:6],
            "timing_warning": None if transcript_available else "timing_not_verified",
            "preserve_spoken_words": True,
        },
        music_directives={
            "use_music": music_available and safety_status != "blocked",
            "mood": str(
                clip.get("music_mood")
                or ("motivational" if emotion > 0.65 else "neutral")
            ),
            "intensity": "low" if "podcast" in niche.lower() else "medium",
            "ducking_priority": "speech_first",
            "speech_first_warning": (
                "Music audibility and speech clarity require render validation."
            ),
        },
        motion_directives={
            "motion_style": motion_style,
            "intensity": "subtle" if pacing == "balanced" else "moderate",
            "enabled": face_available,
            "disable_reason": None if face_available else "face_or_layout_signals_unavailable",
            "no_flash": True,
        },
        sfx_directives={
            "style": "subtle_only",
            "allowed": ["clean_whoosh", "soft_impact"],
            "noise_like_forbidden": True,
            "max_count": 4,
        },
        silence_directives={
            "remove_leading_dead_air_if_safe": True,
            "preserve_intentional_dramatic_pause": True,
        },
        ending_directives={
            "include_payoff_tail": True,
            "postroll_seconds": 0.5,
            "avoid_cutting_final_word": True,
            "loop_friendly_only_if_story_complete": True,
        },
        safety_constraints=[
            "Never override a safety blocker.",
            "Never claim copyright safety or guaranteed virality.",
            "Keep captions faithful to spoken content.",
            "Require user rights confirmation for linked sources.",
        ],
        explanation=(
            f"BOBA recommends {pacing} {policy_name.replace('_advisory', '').replace('_', ' ')} "
            "editing while preserving speech clarity, readable captions, and the final payoff. "
            "This policy is advisory; Editing V2 remains authoritative."
        ),
        confidence=round(max(0.3, min(0.9, 0.45 + 0.2 * hook + 0.15 * emotion)), 3),
        warnings=warnings,
    )

"""JSON-safe helpers for passing Olympus V2 clip intelligence between engines."""

from __future__ import annotations

from typing import Any

from olympus.metadata import compact_upload_metadata
from olympus.personalization import apply as P  # noqa: N812


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def round3(value: Any) -> float:
    return round(as_float(value), 3)


def temporal_iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return 0.0 if union <= 0 else inter / union


def story_v2_available(story_v2: dict[str, Any] | None) -> bool:
    data = as_dict(story_v2)
    return data.get("schema") == "story_analysis_v2" or bool(
        data.get("micro_stories") or data.get("recommended_clip_stories")
    )


def story_recommendations(story_v2: dict[str, Any] | None) -> list[dict[str, Any]]:
    data = as_dict(story_v2)
    recommended = [as_dict(item) for item in as_list(data.get("recommended_clip_stories"))]
    if recommended:
        return recommended
    return [as_dict(item) for item in as_list(data.get("micro_stories"))]


def story_guidance_maps(story_v2: dict[str, Any] | None) -> dict[str, dict[str, dict[str, Any]]]:
    data = as_dict(story_v2)
    maps: dict[str, dict[str, dict[str, Any]]] = {
        "virality": {},
        "planning": {},
        "editing": {},
    }
    for key, field in (
        ("virality", "virality_story_guidance"),
        ("planning", "planning_story_guidance"),
        ("editing", "editing_story_guidance"),
    ):
        for item in as_list(data.get(field)):
            guidance = as_dict(item)
            story_id = as_str(guidance.get("story_id"))
            if story_id:
                maps[key][story_id] = guidance
    return maps


def best_story_for_window(
    story_v2: dict[str, Any] | None,
    start: float,
    end: float,
) -> dict[str, Any]:
    stories = story_recommendations(story_v2)
    if not stories:
        return {}
    scored: list[tuple[float, dict[str, Any]]] = []
    for story in stories:
        story_start = as_float(story.get("recommended_start"), as_float(story.get("start")))
        story_end = as_float(story.get("recommended_end"), as_float(story.get("end")))
        overlap = temporal_iou(start, end, story_start, story_end)
        if overlap <= 0:
            continue
        completeness = as_float(story.get("completeness_score"))
        payoff = as_float(story.get("payoff_score"))
        context_penalty = as_float(story.get("context_dependency_score")) * 0.2
        scored.append((overlap + 0.25 * completeness + 0.15 * payoff - context_penalty, story))
    if scored:
        return max(scored, key=lambda item: item[0])[1]
    return {}


def story_guidance_for_window(
    story_v2: dict[str, Any] | None,
    start: float,
    end: float,
) -> dict[str, Any]:
    story = best_story_for_window(story_v2, start, end)
    if not story:
        return {
            "story_guidance_used": False,
            "story_guidance_source": "fallback",
            "fallback_reason": "no_overlapping_story_analysis_v2_micro_story",
        }
    story_id = as_str(story.get("story_id"))
    maps = story_guidance_maps(story_v2)
    planning = maps["planning"].get(story_id) or as_dict(
        as_dict(story.get("downstream_guidance")).get("planning")
    )
    virality = maps["virality"].get(story_id) or as_dict(
        as_dict(story.get("downstream_guidance")).get("virality")
    )
    editing = maps["editing"].get(story_id) or as_dict(
        as_dict(story.get("downstream_guidance")).get("editing")
    )
    payoff = as_dict(story.get("payoff"))
    ending = as_dict(story.get("ending"))
    setup = as_dict(story.get("setup"))
    tension = as_dict(story.get("tension"))
    repair = as_dict(story.get("boundary_repair"))
    story_start = as_float(story.get("recommended_start"), as_float(story.get("start")))
    story_end = as_float(story.get("recommended_end"), as_float(story.get("end")))
    completeness = as_float(story.get("completeness_score"))
    payoff_strength = max(
        as_float(story.get("payoff_score")),
        1.0 if payoff.get("payoff_present") is True else 0.0,
    )
    context_risk = as_float(story.get("context_dependency_score"))
    ending_strength = as_float(
        ending.get("final_line_strength"), as_float(story.get("ending_score"))
    )
    warnings = [as_str(item) for item in as_list(story.get("risks")) if as_str(item)]
    return {
        "story_guidance_used": True,
        "story_guidance_source": "story_analysis_v2",
        "story_id": story_id,
        "candidate_id": as_str(story.get("candidate_id")) or story_id,
        "match_iou": round3(temporal_iou(start, end, story_start, story_end)),
        "story_start": round3(story.get("start")),
        "story_end": round3(story.get("end")),
        "recommended_start": round3(story_start),
        "recommended_end": round3(story_end),
        "story_shape": as_str(story.get("story_shape")),
        "story_summary": as_str(story.get("summary") or story.get("one_sentence_summary")),
        "why_story_works": as_str(story.get("viewer_promise") or tension.get("viewer_question")),
        "setup": as_str(setup.get("setup_text")),
        "tension": as_str(tension.get("unresolved_question")),
        "turning_point": as_dict(story.get("turning_point")),
        "payoff": as_str(payoff.get("payoff_text")),
        "payoff_present": payoff.get("payoff_present") is True,
        "ending_reason": as_str(ending.get("reason") or ending.get("ending_type")),
        "completeness_score": round3(completeness),
        "payoff_strength": round3(payoff_strength),
        "context_risk": round3(context_risk),
        "ending_strength": round3(ending_strength),
        "boundary_repair": repair,
        "planning_guidance": planning,
        "virality_guidance": virality,
        "editing_guidance": editing,
        "warnings": warnings,
    }


def story_candidate(story: dict[str, Any], story_v2: dict[str, Any] | None) -> dict[str, Any]:
    story = as_dict(story)
    story_id = as_str(story.get("story_id"))
    guidance = story_guidance_for_window(
        story_v2,
        as_float(story.get("start")),
        as_float(story.get("end")),
    )
    start = as_float(guidance.get("recommended_start"), as_float(story.get("recommended_start")))
    end = as_float(guidance.get("recommended_end"), as_float(story.get("recommended_end")))
    return {
        "raw_start": start,
        "raw_end": end,
        "source": "story_v2_micro_story",
        "candidate_type": "story_v2_micro_story",
        "source_candidate_type": "story_v2_micro_story",
        "source_reason": "Story V2 recommended a complete setup-to-payoff micro-story",
        "candidate_id": as_str(story.get("candidate_id")) or story_id,
        "story_id": story_id,
        "peak_heat": round3(story.get("completeness_score")),
        "story_v2_guidance": guidance,
        "planning_story_integration": {
            "story_guidance_used": True,
            "story_boundary_used": True,
            "story_guidance_source": "story_analysis_v2",
            "original_candidate_start": round3(story.get("start")),
            "original_candidate_end": round3(story.get("end")),
            "story_recommended_start": round3(start),
            "story_recommended_end": round3(end),
            "final_start": round3(start),
            "final_end": round3(end),
            "reason": as_str(guidance.get("boundary_repair", {}).get("reason"))
            or "Story V2 recommended clip boundaries",
            "confidence": round3(as_float(guidance.get("ending_strength"), 0.5)),
        },
        "evidence": [
            {
                "type": "story_analysis_v2",
                "timestamp": start,
                "detail": as_str(story.get("summary")) or f"Story V2 micro-story {story_id}",
            }
        ],
    }


def build_planning_story_integration(
    candidate: dict[str, Any],
    *,
    original_start: float,
    original_end: float,
    final_start: float,
    final_end: float,
    boundary_used: bool,
) -> dict[str, Any]:
    existing = as_dict(candidate.get("planning_story_integration"))
    guidance = as_dict(candidate.get("story_v2_guidance"))
    if not guidance or guidance.get("story_guidance_used") is not True:
        return {
            "story_guidance_used": False,
            "story_boundary_used": False,
            "original_candidate_start": round3(original_start),
            "original_candidate_end": round3(original_end),
            "final_start": round3(final_start),
            "final_end": round3(final_end),
            "reason": "Story V2 guidance unavailable for this candidate; fallback boundaries used",
            "confidence": 0.0,
        }
    return {
        **existing,
        "story_guidance_used": True,
        "story_boundary_used": bool(boundary_used),
        "story_guidance_source": "story_analysis_v2",
        "story_id": guidance.get("story_id"),
        "original_candidate_start": round3(original_start),
        "original_candidate_end": round3(original_end),
        "story_recommended_start": guidance.get("recommended_start"),
        "story_recommended_end": guidance.get("recommended_end"),
        "final_start": round3(final_start),
        "final_end": round3(final_end),
        "reason": as_str(as_dict(guidance.get("boundary_repair")).get("reason"))
        or (
            "Story V2 boundary used"
            if boundary_used
            else "Transcript snap refined Story V2 boundary"
        ),
        "confidence": round3(as_float(guidance.get("ending_strength"), 0.55)),
    }


def apply_story_scores(scores: dict[str, float], guidance: dict[str, Any]) -> dict[str, float]:
    if guidance.get("story_guidance_used") is not True:
        return scores
    completeness = as_float(guidance.get("completeness_score"))
    payoff = as_float(guidance.get("payoff_strength"))
    context_independence = 1.0 - as_float(guidance.get("context_risk"))
    ending = as_float(guidance.get("ending_strength"))
    out = dict(scores)
    out["story_completion"] = round3(
        0.45 * as_float(out.get("story_completion")) + 0.55 * completeness
    )
    out["payoff"] = round3(0.4 * as_float(out.get("payoff")) + 0.6 * payoff)
    out["clarity"] = round3(0.7 * as_float(out.get("clarity")) + 0.3 * context_independence)
    out["ending"] = round3(0.45 * as_float(out.get("ending")) + 0.55 * ending)
    out["story"] = round3(
        0.35 * as_float(out.get("story")) + 0.35 * completeness + 0.2 * payoff + 0.1 * ending
    )
    if as_float(guidance.get("context_risk")) >= 0.55:
        out["retention"] = round3(max(0.0, as_float(out.get("retention")) - 0.08))
    if guidance.get("payoff_present") is False:
        out["payoff"] = round3(min(as_float(out.get("payoff")), 0.38))
        out["story"] = round3(min(as_float(out.get("story")), 0.45))
    return out


def unified_clip_intelligence(
    *,
    clip: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    blueprint: dict[str, Any] | None = None,
    editing_v2: dict[str, Any] | None = None,
    render_metadata: dict[str, Any] | None = None,
    render_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clip = as_dict(clip)
    plan = as_dict(plan)
    blueprint = as_dict(blueprint or plan.get("blueprint"))
    editing_v2 = as_dict(editing_v2 or as_dict(render_metadata).get("editing_v2"))
    render_metadata = as_dict(render_metadata)
    render_output = as_dict(render_output)
    existing = as_dict(
        render_metadata.get("unified_clip_intelligence") or plan.get("unified_clip_intelligence")
    )
    story_guidance = as_dict(
        blueprint.get("story_v2_guidance") or plan.get("story_v2_guidance") or existing.get("story")
    )
    viral_score = as_dict(blueprint.get("viral_score_v2"))
    hook = as_dict(blueprint.get("hook_analysis_v2")) or as_dict(blueprint.get("hook_v2"))
    story = as_dict(blueprint.get("storytelling_v2"))
    ending = as_dict(blueprint.get("ending_payoff_v2"))
    trend = as_dict(blueprint.get("trend_match_v2"))
    trend_snapshot = as_dict(
        blueprint.get("internet_trend_research_v2")
        or blueprint.get("viral_research_snapshot")
    )
    v2_meta = as_dict(blueprint.get("v2_metadata"))
    existing_virality = as_dict(existing.get("virality"))
    existing_planning = as_dict(existing.get("planning"))
    existing_editing = as_dict(existing.get("editing"))
    existing_trend = as_dict(existing.get("trend_research"))
    existing_music = as_dict(existing.get("music_intelligence"))
    existing_layout = as_dict(existing.get("multi_speaker_layout"))
    existing_caption = as_dict(existing.get("caption_intelligence"))
    existing_motion = as_dict(existing.get("motion_graphics"))
    existing_safety = as_dict(existing.get("copyright_safety"))
    existing_upload_metadata = as_dict(existing.get("upload_metadata"))
    existing_personalization = as_dict(existing.get("personalization"))
    caption_intelligence = as_dict(
        render_metadata.get("caption_intelligence_v2")
        or editing_v2.get("caption_intelligence_v2")
    )
    caption_style = as_dict(caption_intelligence.get("style_decision"))
    caption_timing = as_dict(caption_intelligence.get("caption_timing_quality"))
    caption_hook = as_dict(caption_intelligence.get("hook_caption_treatment"))
    caption_emphasis = as_dict(caption_intelligence.get("caption_emphasis"))
    caption_speaker = as_dict(caption_intelligence.get("speaker_captioning"))
    caption_safe_zone = as_dict(caption_intelligence.get("caption_safe_zone"))
    caption_readability = as_dict(
        render_metadata.get("caption_readability_validation")
        or caption_intelligence.get("caption_readability_validation")
    )
    caption_validation = as_dict(
        render_metadata.get("caption_render_validation")
        or caption_intelligence.get("validation")
    )
    music_intelligence = as_dict(
        render_metadata.get("music_intelligence_v2")
        or editing_v2.get("music_intelligence_v2")
    )
    music_decision = as_dict(music_intelligence.get("decision"))
    music_selected = as_dict(music_intelligence.get("selected_asset"))
    music_library_selection = as_dict(
        music_intelligence.get("music_library_selection")
    )
    music_mix = as_dict(music_intelligence.get("mix_plan"))
    music_events = as_dict(music_intelligence.get("music_story_events"))
    music_validation = as_dict(
        render_metadata.get("music_validation") or music_intelligence.get("validation")
    )
    multi_speaker = as_dict(
        render_metadata.get("multi_speaker_layout_v2")
        or editing_v2.get("multi_speaker_layout_v2")
        or editing_v2.get("face_tracking_plan")
    )
    layout_input = as_dict(multi_speaker.get("input_analysis"))
    layout_decision = as_dict(multi_speaker.get("decision"))
    layout_validation = as_dict(
        render_metadata.get("multi_speaker_validation")
        or multi_speaker.get("validation")
    )
    motion_intelligence = as_dict(
        render_metadata.get("motion_intelligence_v2")
        or editing_v2.get("motion_intelligence_v2")
    )
    motion_decision = as_dict(motion_intelligence.get("decision"))
    motion_effect_plan = as_dict(motion_intelligence.get("effect_plan"))
    motion_safety = as_dict(
        render_metadata.get("motion_safety_validation")
        or motion_intelligence.get("motion_safety_validation")
    )
    motion_validation = as_dict(
        render_metadata.get("motion_render_validation")
        or motion_intelligence.get("validation")
    )
    safety_report = as_dict(render_metadata.get("copyright_safety_v2"))
    safety_overall = as_dict(safety_report.get("overall"))
    safety_source = as_dict(safety_report.get("source_video"))
    safety_music = as_dict(safety_report.get("music"))
    safety_sfx = as_dict(safety_report.get("sfx"))
    safety_manual = as_dict(safety_report.get("manual_review"))
    upload_metadata_report = as_dict(render_metadata.get("upload_metadata_v2"))
    upload_metadata = (
        compact_upload_metadata(upload_metadata_report)
        if upload_metadata_report
        else existing_upload_metadata
    )
    personalization_applied = as_dict(
        render_metadata.get("personalization_applied_v2")
        or editing_v2.get("personalization_applied_v2")
        or blueprint.get("planning_personalization")
    )
    upload_personalization = as_dict(
        upload_metadata_report.get("upload_metadata_personalization")
    )
    if personalization_applied or upload_personalization:
        personalization_applied = P.combine_applications(
            personalization_applied,
            upload_personalization,
        )
    elif existing_personalization:
        personalization_applied = existing_personalization
    safety_result = as_dict(safety_report.get("result"))
    safety_warnings = as_list(safety_result.get("warnings"))
    trend_sources = [
        as_dict(item) for item in as_list(trend_snapshot.get("sources")) if as_dict(item)
    ]
    trend_patterns = trend.get("matched_patterns") or existing_trend.get("matched_patterns") or []
    rendering = as_dict(existing.get("rendering"))
    rendering.update(
        {
            "mp4_path_or_key": render_output.get("output_key") or rendering.get("mp4_path_or_key"),
            "preview_url": rendering.get("preview_url"),
            "download_url": rendering.get("download_url"),
            "captions_status": "burned_in" if render_output.get("subtitles_included") else None,
            "music_mixed": render_metadata.get("music_mixed"),
            "sfx_mixed_count": render_metadata.get("sfx_mixed_count"),
            "voice_enhancement_applied": render_metadata.get("voice_enhancement_applied"),
            "video_enhancement_applied": render_metadata.get("video_enhancement_applied"),
            "face_tracking_applied": render_metadata.get("face_tracking_applied"),
            "sync_validation": render_metadata.get("sync_validation"),
            "duration_validation": render_metadata.get("duration_validation"),
            "caption_render_validation": render_metadata.get("caption_render_validation"),
            "motion_render_validation": render_metadata.get("motion_render_validation"),
            "warnings": list(
                dict.fromkeys(
                    [
                        *as_list(render_metadata.get("warnings")),
                        *safety_warnings,
                    ]
                )
            ),
        }
    )
    return {
        "clip_id": clip.get("clip_id") or plan.get("id") or render_output.get("clip_id"),
        "story_id": story_guidance.get("story_id")
        or plan.get("story_id")
        or existing.get("story_id"),
        "candidate_id": plan.get("candidate_id")
        or as_dict(v2_meta.get("source_candidate_metadata")).get("candidate_id"),
        "plan_id": clip.get("plan_id")
        or plan.get("id")
        or render_output.get("plan_id")
        or existing.get("plan_id"),
        "timeline_id": clip.get("clip_id")
        or render_output.get("clip_id")
        or existing.get("timeline_id"),
        "render_id": render_output.get("render_id") or existing.get("render_id"),
        "source_start": clip.get("source_start")
        or plan.get("start")
        or existing.get("source_start"),
        "source_end": clip.get("source_end") or plan.get("end") or existing.get("source_end"),
        "final_duration": clip.get("duration")
        or plan.get("duration")
        or render_output.get("duration")
        or existing.get("final_duration"),
        "story": {
            "story_shape": story_guidance.get("story_shape") or story.get("story_shape"),
            "setup": story_guidance.get("setup"),
            "tension": story_guidance.get("tension"),
            "turning_point": story_guidance.get("turning_point"),
            "payoff": story_guidance.get("payoff") or ending.get("ending_line"),
            "ending_reason": story_guidance.get("ending_reason") or ending.get("ending_type"),
            "completeness_score": story_guidance.get("completeness_score") or story.get("score"),
            "context_risk": story_guidance.get("context_risk"),
            "boundary_repair": story_guidance.get("boundary_repair"),
            "story_summary": story_guidance.get("story_summary"),
            "why_story_works": story_guidance.get("why_story_works"),
            "warnings": story_guidance.get("warnings") or [],
        },
        "virality": {
            "overall_score": viral_score.get("overall")
            or plan.get("quality_score")
            or existing_virality.get("overall_score"),
            "hook_score": hook.get("score")
            or plan.get("hook_score")
            or existing_virality.get("hook_score"),
            "retention_score": plan.get("retention_score")
            or existing_virality.get("retention_score"),
            "story_score": plan.get("story_score") or existing_virality.get("story_score"),
            "payoff_score": plan.get("payoff_score") or existing_virality.get("payoff_score"),
            "emotion_score": plan.get("emotion_score") or existing_virality.get("emotion_score"),
            "shareability_score": as_dict(plan.get("scores")).get("shareability")
            or existing_virality.get("shareability_score"),
            "clarity_score": plan.get("clarity_score") or existing_virality.get("clarity_score"),
            "trend_fit_score": as_dict(plan.get("scores")).get("trend_fit")
            or trend.get("trend_fit_score")
            or existing_virality.get("trend_fit_score"),
            "uniqueness_score": plan.get("uniqueness_score")
            or existing_virality.get("uniqueness_score"),
            "hook_category": hook.get("category") or existing_virality.get("hook_category"),
            "hook_line": plan.get("hook_line")
            or hook.get("hook_line")
            or hook.get("overlay_text")
            or existing_virality.get("hook_line"),
            "trend_patterns": trend_patterns
            or existing_virality.get("trend_patterns")
            or [],
            "why_this_can_work": as_dict(viral_score.get("breakdown")).get("top_strengths")
            or v2_meta.get("why_selected"),
            "why_not_higher": as_dict(viral_score.get("breakdown")).get("weaknesses") or [],
            "confidence": plan.get("confidence") or existing_virality.get("confidence"),
        },
        "planning": {
            "rank": plan.get("rank") or clip.get("rank") or existing_planning.get("rank"),
            "selected_reason": v2_meta.get("why_selected") or plan.get("explanation"),
            "rejected_alternatives": plan.get("alternatives")
            or existing_planning.get("rejected_alternatives")
            or [],
            "duplicate_group": plan.get("duplicate_group")
            or existing_planning.get("duplicate_group"),
            "timeline_diversity_reason": plan.get("timeline_diversity_reason")
            or existing_planning.get("timeline_diversity_reason"),
            "boundary_optimization": blueprint.get("boundary_optimization_v2")
            or existing_planning.get("boundary_optimization"),
            "expected_output_reason": v2_meta.get("risk_notes")
            or existing_planning.get("expected_output_reason"),
            "planning_story_integration": plan.get("planning_story_integration")
            or blueprint.get("planning_story_integration"),
            "planning_trend_integration": plan.get("planning_trend_integration")
            or blueprint.get("planning_trend_integration")
            or existing_planning.get("planning_trend_integration"),
        },
        "editing": {
            "edit_style": editing_v2.get("editing_style")
            or as_dict(blueprint.get("edit_decision_v2")).get("transition_style")
            or existing_editing.get("edit_style"),
            "hook_treatment": editing_v2.get("hook_editing")
            or as_dict(blueprint.get("hook_v2")).get("first_three_second_editing")
            or existing_editing.get("hook_treatment"),
            "caption_emphasis_words": caption_emphasis.get("highlighted_words")
            or as_dict(editing_v2.get("caption_style")).get("highlight_words")
            or existing_editing.get("caption_emphasis_words"),
            "music_mood": as_dict(editing_v2.get("music_plan")).get("mood")
            or as_dict(editing_v2.get("music_plan")).get("category")
            or as_dict(blueprint.get("music_decision_v2")).get("category")
            or existing_editing.get("music_mood"),
            "sfx_moments": as_dict(editing_v2.get("sfx_plan")).get("events")
            or as_dict(blueprint.get("sound_effect_plan_v2")).get("effects"),
            "motion_priority": as_dict(editing_v2.get("motion_plan")).get("reason"),
            "face_tracking_mode": as_dict(editing_v2.get("face_tracking_plan")).get("mode"),
            "pacing_style": as_dict(editing_v2.get("pacing_profile")).get("profile"),
            "ending_hold": as_dict(editing_v2.get("ending_hold")).get("duration_s"),
            "voice_enhancement": editing_v2.get("voice_enhancement_plan"),
            "video_enhancement": editing_v2.get("video_enhancement_plan"),
            "editing_guidance_consumed": editing_v2.get("editing_guidance_consumed"),
            "editing_trend_guidance": editing_v2.get("editing_trend_guidance")
            or blueprint.get("editing_trend_guidance")
            or existing_editing.get("editing_trend_guidance"),
            "motion_intelligence_v2": motion_intelligence
            or existing_editing.get("motion_intelligence_v2"),
        },
        "trend_research": {
            "snapshot_id": trend_snapshot.get("snapshot_id")
            or existing_trend.get("snapshot_id"),
            "research_status": trend_snapshot.get("research_status")
            or existing_trend.get("research_status"),
            "cache_status": trend_snapshot.get("cache_status")
            or existing_trend.get("cache_status"),
            "provider_used": trend_snapshot.get("provider_used")
            or existing_trend.get("provider_used"),
            "provider_status": trend_snapshot.get("provider_status")
            or existing_trend.get("provider_status"),
            "internet_available": trend_snapshot.get("internet_available")
            if trend_snapshot
            else existing_trend.get("internet_available"),
            "live_research_attempted": trend_snapshot.get("live_research_attempted")
            if trend_snapshot
            else existing_trend.get("live_research_attempted"),
            "live_research_succeeded": trend_snapshot.get("live_research_succeeded")
            if trend_snapshot
            else existing_trend.get("live_research_succeeded"),
            "fallback_used": trend_snapshot.get("fallback_used")
            if trend_snapshot
            else existing_trend.get("fallback_used"),
            "niche": as_dict(trend_snapshot.get("detected_niche")).get("primary")
            or existing_trend.get("niche"),
            "matched_patterns": trend_patterns,
            "trend_fit_score": trend.get("trend_fit_score")
            or trend.get("score")
            or existing_trend.get("trend_fit_score"),
            "source_count": trend_snapshot.get("source_count")
            or len(trend_sources)
            or existing_trend.get("source_count"),
            "source_domains": list(
                dict.fromkeys(
                    as_str(source.get("domain"))
                    for source in trend_sources
                    if as_str(source.get("domain"))
                )
            )
            or as_list(trend_snapshot.get("source_domains"))
            or as_list(existing_trend.get("source_domains")),
            "source_credibility_summary": trend_snapshot.get(
                "source_credibility_summary"
            )
            or existing_trend.get("source_credibility_summary"),
            "confidence": trend.get("confidence")
            or trend_snapshot.get("confidence")
            or existing_trend.get("confidence"),
            "warnings": trend_snapshot.get("warnings")
            or trend.get("warnings")
            or existing_trend.get("warnings")
            or [],
        },
        "music_intelligence": {
            "music_decision_id": music_intelligence.get("music_decision_id")
            or existing_music.get("music_decision_id"),
            "should_use_music": music_decision.get("should_use_music")
            if music_decision
            else existing_music.get("should_use_music"),
            "reason": music_decision.get("reason") or existing_music.get("reason"),
            "disabled_reason": music_decision.get("disabled_reason")
            or existing_music.get("disabled_reason"),
            "mood": music_decision.get("target_mood") or existing_music.get("mood"),
            "role": music_decision.get("music_role") or existing_music.get("role"),
            "selected_asset": {
                "asset_id": music_selected.get("asset_id"),
                "title": music_selected.get("title"),
                "license": music_selected.get("license"),
                "license_verified": music_selected.get("license_verified"),
                "safe_default": music_selected.get("safe_default"),
                "quality": music_selected.get("quality"),
                "quality_status": music_selected.get("quality_status"),
                "folder_type": music_selected.get("folder_type"),
            }
            if music_selected
            else existing_music.get("selected_asset"),
            "license_safe": music_validation.get("license_safe")
            if music_validation
            else existing_music.get("license_safe"),
            "music_gain_db": music_mix.get("music_gain_db")
            or existing_music.get("music_gain_db"),
            "ducking_enabled": music_mix.get("ducking_enabled")
            if music_mix
            else existing_music.get("ducking_enabled"),
            "hook_music_event": music_events.get("hook_event")
            or existing_music.get("hook_music_event"),
            "payoff_music_event": music_events.get("payoff_event")
            or existing_music.get("payoff_music_event"),
            "validation_status": music_validation.get("passed")
            if music_validation
            else existing_music.get("validation_status"),
            "audibility": music_validation.get("audible")
            or existing_music.get("audibility"),
            "speech_clarity": music_validation.get("speech_clarity_passed")
            or existing_music.get("speech_clarity"),
            "library_selection": music_library_selection
            or existing_music.get("library_selection"),
            "warning": music_validation.get("warning")
            or existing_music.get("warning"),
        },
        "multi_speaker_layout": {
            "layout_decision_id": multi_speaker.get("layout_decision_id")
            or existing_layout.get("layout_decision_id"),
            "mode": multi_speaker.get("mode")
            or layout_decision.get("mode")
            or existing_layout.get("mode"),
            "applied": layout_validation.get("applied")
            if layout_validation
            else existing_layout.get("applied"),
            "detected_face_count": layout_input.get("detected_face_count")
            or existing_layout.get("detected_face_count"),
            "tracked_participant_count": len(as_list(multi_speaker.get("participants")))
            or existing_layout.get("tracked_participant_count"),
            "speaker_count": layout_input.get("speaker_count")
            or existing_layout.get("speaker_count"),
            "speaker_association_available": layout_input.get(
                "active_speaker_evidence_available"
            )
            if layout_input
            else existing_layout.get("speaker_association_available"),
            "active_speaker_used": (
                multi_speaker.get("mode") == "active_speaker_focus"
                and bool(as_list(multi_speaker.get("speaker_switches")))
            )
            if multi_speaker
            else existing_layout.get("active_speaker_used"),
            "rendered_region_count": layout_validation.get("rendered_regions")
            or existing_layout.get("rendered_region_count"),
            "switch_count": layout_validation.get("rendered_switches")
            if layout_validation
            else existing_layout.get("switch_count"),
            "confidence": multi_speaker.get("confidence")
            or layout_decision.get("confidence")
            or existing_layout.get("confidence"),
            "reason": layout_decision.get("reason") or existing_layout.get("reason"),
            "fallback_reason": multi_speaker.get("fallback_reason")
            or layout_decision.get("fallback_reason")
            or existing_layout.get("fallback_reason"),
            "validation_status": layout_validation.get("passed")
            if layout_validation
            else existing_layout.get("validation_status"),
            "warnings": layout_validation.get("warnings")
            or multi_speaker.get("warnings")
            or existing_layout.get("warnings")
            or [],
        },
        "motion_graphics": {
            "applied": (
                as_float(motion_validation.get("effects_rendered")) > 0
                and motion_validation.get("passed") is True
            )
            if motion_validation
            else existing_motion.get("applied"),
            "motion_style": motion_decision.get("motion_style")
            or existing_motion.get("motion_style"),
            "intensity": motion_decision.get("intensity")
            or existing_motion.get("intensity"),
            "effect_count": motion_validation.get("effects_rendered")
            if motion_validation
            else len(as_list(motion_effect_plan.get("effects")))
            or existing_motion.get("effect_count"),
            "planned_effect_count": motion_validation.get("effects_planned")
            if motion_validation
            else len(as_list(motion_effect_plan.get("effects"))),
            "hook_effect": as_dict(motion_effect_plan.get("hook_effect")).get("type")
            or existing_motion.get("hook_effect"),
            "pattern_interrupts": motion_effect_plan.get("pattern_interrupts")
            or existing_motion.get("pattern_interrupts")
            or [],
            "payoff_effect": as_dict(motion_effect_plan.get("payoff_effect")).get("type")
            or existing_motion.get("payoff_effect"),
            "caption_safe": motion_safety.get("caption_safe")
            if motion_safety
            else existing_motion.get("caption_safe"),
            "face_safe": motion_safety.get("face_safe")
            if motion_safety
            else existing_motion.get("face_safe"),
            "layout_safe": motion_safety.get("layout_safe")
            if motion_safety
            else existing_motion.get("layout_safe"),
            "render_validation_passed": motion_validation.get("passed")
            if motion_validation
            else existing_motion.get("render_validation_passed"),
            "reason": motion_decision.get("reason") or existing_motion.get("reason"),
            "disabled_reason": motion_decision.get("disabled_reason")
            or existing_motion.get("disabled_reason"),
            "warnings": motion_validation.get("warnings")
            or motion_effect_plan.get("warnings")
            or existing_motion.get("warnings")
            or [],
        },
        "caption_intelligence": {
            "applied": caption_validation.get("passed")
            if caption_validation
            else existing_caption.get("applied"),
            "style": caption_style.get("caption_style")
            or existing_caption.get("style"),
            "typography_mood": caption_style.get("typography_mood")
            or existing_caption.get("typography_mood"),
            "timing_source": caption_timing.get("source")
            or existing_caption.get("timing_source"),
            "timing_estimated": caption_timing.get("estimated")
            if caption_timing
            else existing_caption.get("timing_estimated"),
            "hook_treatment": caption_hook.get("applied")
            if caption_hook
            else existing_caption.get("hook_treatment"),
            "highlighted_words": caption_emphasis.get("highlighted_words")
            or existing_caption.get("highlighted_words")
            or [],
            "highlighted_words_count": len(
                as_list(caption_emphasis.get("highlighted_words"))
            )
            if caption_emphasis
            else existing_caption.get("highlighted_words_count"),
            "speaker_aware": caption_speaker.get("enabled")
            if caption_speaker
            else existing_caption.get("speaker_aware"),
            "speaker_strategy": caption_speaker.get("placement_strategy")
            or existing_caption.get("speaker_strategy"),
            "safe_zone_strategy": caption_safe_zone.get("strategy")
            or existing_caption.get("safe_zone_strategy"),
            "readability_passed": caption_readability.get("passed")
            if caption_readability
            else existing_caption.get("readability_passed"),
            "render_validation_passed": caption_validation.get("passed")
            if caption_validation
            else existing_caption.get("render_validation_passed"),
            "reason": caption_style.get("reason") or existing_caption.get("reason"),
            "warnings": caption_validation.get("warnings")
            or caption_intelligence.get("warnings")
            or existing_caption.get("warnings")
            or [],
        },
        "copyright_safety": {
            "report_id": safety_report.get("report_id")
            or existing_safety.get("report_id"),
            "risk_level": safety_overall.get("risk_level")
            or existing_safety.get("risk_level"),
            "upload_readiness": safety_overall.get("upload_readiness")
            or existing_safety.get("upload_readiness"),
            "source_rights_confirmed": safety_source.get("rights_confirmed")
            if safety_source
            else existing_safety.get("source_rights_confirmed"),
            "music_license_verified": safety_music.get("license_verified")
            if safety_music
            else existing_safety.get("music_license_verified"),
            "sfx_license_verified": safety_sfx.get("all_license_verified")
            if safety_sfx
            else existing_safety.get("sfx_license_verified"),
            "manual_review_required": safety_manual.get("required")
            if safety_manual
            else existing_safety.get("manual_review_required"),
            "blocked_reasons": safety_result.get("errors")
            or existing_safety.get("blocked_reasons")
            or [],
            "warnings": safety_warnings
            or existing_safety.get("warnings")
            or [],
            "disclaimer": safety_overall.get("disclaimer")
            or existing_safety.get("disclaimer"),
        },
        "upload_metadata": upload_metadata,
        "personalization": {
            "applied": personalization_applied.get("applied") is True,
            "profile_id": personalization_applied.get("profile_id"),
            "profile_name": personalization_applied.get("profile_name"),
            "confidence": personalization_applied.get("confidence"),
            "affected_systems": as_list(
                personalization_applied.get("affected_systems")
            ),
            "key_adjustments": [
                {
                    "system": as_dict(item).get("system"),
                    "field": as_dict(item).get("field"),
                    "value": as_dict(item).get("value"),
                    "reason": as_dict(item).get("reason"),
                    "applied": as_dict(item).get("applied", True),
                }
                for item in as_list(personalization_applied.get("adjustments"))[:10]
                if as_dict(item)
            ],
            "warnings": as_list(personalization_applied.get("warnings")),
            "reasons": as_list(personalization_applied.get("reasons")),
        },
        "rendering": rendering,
    }

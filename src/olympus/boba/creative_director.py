"""Creative brief generation from existing Olympus and BOBA signals."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.memory_contracts import BobaMemoryRecordV1
from olympus.platform.errors import ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore

PacingLevel = Literal["calm", "balanced", "fast", "aggressive"]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any, *, maximum: int = 300) -> str:
    return " ".join(str(value or "").split())[:maximum].strip()


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _score(value: Any) -> float:
    return max(0.0, min(1.0, _number(value)))


class BobaCreativeBriefV1(BobaContract):
    clip_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    target_emotion: str = Field(min_length=1, max_length=80)
    hook_type: str = Field(min_length=1, max_length=80)
    curiosity_trigger: str = Field(min_length=1, max_length=300)
    story_angle: str = Field(min_length=1, max_length=400)
    recommended_duration_seconds: float = Field(ge=1.0, le=180.0)
    pacing_level: PacingLevel
    caption_style: str = Field(min_length=1, max_length=80)
    motion_style: str = Field(min_length=1, max_length=80)
    music_mood: str = Field(min_length=1, max_length=80)
    editing_notes: list[str] = Field(default_factory=list, max_length=16)
    risk_warnings: list[str] = Field(default_factory=list, max_length=16)
    why_it_may_work: str = Field(min_length=1, max_length=600)
    whole_video_understanding_used: bool = False
    understanding_guidance: list[str] = Field(default_factory=list, max_length=8)


class BobaOpeningThreeSecondPlanV2(BobaContract):
    what_viewer_sees_first: str = Field(min_length=1, max_length=500)
    caption_implication: str = Field(min_length=1, max_length=500)
    curiosity_gap: str = Field(min_length=1, max_length=500)
    motion_choice: str = Field(min_length=1, max_length=400)
    avoid: list[str] = Field(default_factory=list, max_length=12)


class BobaHookTreatmentV2(BobaContract):
    hook_type: str = Field(min_length=1, max_length=80)
    opening_line_direction: str = Field(min_length=1, max_length=500)
    first_visual_emphasis: str = Field(min_length=1, max_length=500)
    curiosity_trigger: str = Field(min_length=1, max_length=500)
    pattern_interrupt: str = Field(min_length=1, max_length=500)
    reason_it_should_work: str = Field(min_length=1, max_length=700)
    hook_risk: str = Field(min_length=1, max_length=500)


class BobaPacingMapV2(BobaContract):
    first_3_seconds: str = Field(min_length=1, max_length=500)
    seconds_3_to_10: str = Field(min_length=1, max_length=500)
    middle_section: str = Field(min_length=1, max_length=500)
    payoff_section: str = Field(min_length=1, max_length=500)
    ending: str = Field(min_length=1, max_length=500)
    pacing_intensity: str = Field(min_length=1, max_length=80)
    filler_cut_notes: list[str] = Field(default_factory=list, max_length=16)


class BobaCaptionDirectionV2(BobaContract):
    style: str = Field(min_length=1, max_length=80)
    emphasis_words: list[str] = Field(default_factory=list, max_length=12)
    rhythm: str = Field(min_length=1, max_length=500)
    highlight_moments: list[str] = Field(default_factory=list, max_length=16)
    readability_notes: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=16)


class BobaMotionDirectionV2(BobaContract):
    style: str = Field(min_length=1, max_length=80)
    zoom_moments: list[str] = Field(default_factory=list, max_length=16)
    punch_in_moments: list[str] = Field(default_factory=list, max_length=16)
    stable_moments: list[str] = Field(default_factory=list, max_length=16)
    layout_safe_moments: list[str] = Field(default_factory=list, max_length=16)
    visual_emphasis_moments: list[str] = Field(default_factory=list, max_length=16)
    safety_warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaAudioDirectionV2(BobaContract):
    music_mood: str = Field(min_length=1, max_length=80)
    sfx_intensity: str = Field(min_length=1, max_length=80)
    ducking_guidance: str = Field(min_length=1, max_length=500)
    silence_notes: str = Field(min_length=1, max_length=500)
    speech_clarity_notes: str = Field(min_length=1, max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRetentionPlanV2(BobaContract):
    opening_hook: str = Field(min_length=1, max_length=500)
    curiosity_loop: str = Field(min_length=1, max_length=500)
    mid_clip_hold: str = Field(min_length=1, max_length=500)
    payoff_delivery: str = Field(min_length=1, max_length=500)
    replay_trigger: str = Field(min_length=1, max_length=500)
    retention_risks: list[str] = Field(default_factory=list, max_length=20)


class BobaEmotionalArcV2(BobaContract):
    starting_emotion: str = Field(min_length=1, max_length=120)
    build_emotion: str = Field(min_length=1, max_length=120)
    payoff_emotion: str = Field(min_length=1, max_length=120)
    intended_viewer_feeling: str = Field(min_length=1, max_length=240)
    emotional_risk: str = Field(min_length=1, max_length=500)


class BobaCreativeQualityScoreV2(BobaContract):
    hook_quality: float = Field(ge=0.0, le=100.0)
    clarity: float = Field(ge=0.0, le=100.0)
    emotional_pull: float = Field(ge=0.0, le=100.0)
    pacing_strength: float = Field(ge=0.0, le=100.0)
    visual_direction_strength: float = Field(ge=0.0, le=100.0)
    caption_strength: float = Field(ge=0.0, le=100.0)
    audio_direction_strength: float = Field(ge=0.0, le=100.0)
    overall_confidence: float = Field(ge=0.0, le=100.0)


class BobaCreativeDirectorSignalUsageV2(BobaContract):
    editorial_decisions_used: bool
    explanations_used: bool
    clip_ranking_used: bool
    candidate_discovery_used: bool
    whole_video_understanding_used: bool
    analysis_signals_used: bool
    memory_used: bool
    fallback_used: bool
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaProjectCreativeDirectionV2(BobaContract):
    overall_style: str = Field(min_length=1, max_length=300)
    tone: str = Field(min_length=1, max_length=120)
    pacing_philosophy: str = Field(min_length=1, max_length=600)
    caption_philosophy: str = Field(min_length=1, max_length=600)
    motion_philosophy: str = Field(min_length=1, max_length=600)
    audio_philosophy: str = Field(min_length=1, max_length=600)
    target_viewer_feeling: str = Field(min_length=1, max_length=300)
    human_review_notes: list[str] = Field(default_factory=list, max_length=24)


class BobaClipCreativeDirectionV2(BobaContract):
    candidate_id: str = Field(min_length=1, max_length=128)
    ranked_clip_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    selected: bool
    render_readiness: str = Field(min_length=1, max_length=80)
    final_clip_angle: str = Field(min_length=1, max_length=500)
    hook_treatment: BobaHookTreatmentV2
    opening_three_second_plan: BobaOpeningThreeSecondPlanV2
    story_framing: str = Field(min_length=1, max_length=700)
    pacing_map: BobaPacingMapV2
    caption_direction: BobaCaptionDirectionV2
    motion_direction: BobaMotionDirectionV2
    audio_direction: BobaAudioDirectionV2
    retention_plan: BobaRetentionPlanV2
    emotional_arc: BobaEmotionalArcV2
    creative_quality_score: BobaCreativeQualityScoreV2
    risk_fixes: list[str] = Field(default_factory=list, max_length=24)
    editor_notes: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)


class BobaCreativeDirectionSetV2(BobaContract):
    schema_version: Literal["boba_creative_director_v2"] = "boba_creative_director_v2"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    project_direction: BobaProjectCreativeDirectionV2
    clip_directions: list[BobaClipCreativeDirectionV2] = Field(
        default_factory=list, max_length=10
    )
    creative_quality_summary: BobaCreativeQualityScoreV2
    signal_usage: BobaCreativeDirectorSignalUsageV2
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaCreativeDirector:
    """Turn persisted Olympus facts into compact, non-executing clip briefs."""

    def __init__(self, store: BobaMemoryStore) -> None:
        self.store = store

    def create_briefs(
        self,
        project_id: str,
        signals: dict[str, Any],
        *,
        creator_profile_id: str | None = None,
    ) -> list[BobaCreativeBriefV1]:
        candidates = self._candidate_inputs(signals)
        records = self.store.list_records("project", {"project_id": project_id})
        if creator_profile_id:
            records.extend(
                self.store.list_records(
                    "creator", {"creator_profile_id": creator_profile_id}
                )
            )
        briefs = [
            self._brief(project_id, item, index, signals, records)
            for index, item in enumerate(candidates[:20])
        ]
        for brief in briefs:
            self.store.save_creative_brief(brief)
        return briefs

    def list_briefs(self, project_id: str) -> list[BobaCreativeBriefV1]:
        return self.store.list_creative_briefs(project_id)

    @staticmethod
    def _candidate_inputs(signals: dict[str, Any]) -> list[dict[str, Any]]:
        for key in (
            "selected_plans",
            "planning_candidates",
            "editorial_candidate_clips",
            "ranked_candidate_clips",
            "discovered_candidate_clips",
        ):
            values = [_dict(item) for item in _list(signals.get(key)) if _dict(item)]
            if values:
                return values
        story = _dict(signals.get("story_analysis_v2"))
        return [
            _dict(item)
            for item in _list(story.get("recommended_clip_stories"))
            if _dict(item)
        ]

    def _brief(
        self,
        project_id: str,
        plan: dict[str, Any],
        index: int,
        signals: dict[str, Any],
        records: list[BobaMemoryRecordV1],
    ) -> BobaCreativeBriefV1:
        unified = _dict(plan.get("unified_clip_intelligence"))
        story = _dict(plan.get("story") or unified.get("story"))
        virality = _dict(plan.get("virality") or unified.get("virality"))
        planning = _dict(plan.get("planning") or unified.get("planning"))
        clip_id = _text(
            plan.get("clip_id")
            or plan.get("id")
            or plan.get("candidate_id")
            or unified.get("clip_id")
            or f"clip_{index + 1}",
            maximum=128,
        )
        timeline = self._timeline(signals, clip_id)
        editing = _dict(plan.get("editing") or unified.get("editing"))
        if timeline:
            editing = {**editing, **timeline}
        analysis = _dict(signals.get("analysis_signals_v2"))
        start = _number(
            plan.get("start") or plan.get("source_start") or plan.get("start_seconds")
        )
        end = _number(plan.get("end") or plan.get("source_end") or plan.get("end_seconds"))
        duration = max(0.0, end - start)
        if not duration:
            duration = _number(
                plan.get("duration")
                or plan.get("final_duration")
                or planning.get("final_duration"),
                30.0,
            )
        recommended_duration = max(12.0, min(60.0, duration or 30.0))
        understanding = self._whole_video_guidance(signals, start, end)

        transcript_hook = self._transcript_hook(signals, start, end)
        hook_line = _text(
            plan.get("hook_line")
            or virality.get("hook_line")
            or planning.get("hook_line")
            or transcript_hook,
            maximum=260,
        )
        hook_type = _text(
            plan.get("hook_category")
            or plan.get("hook_type")
            or virality.get("hook_category")
            or virality.get("hook_type")
            or "clear_value",
            maximum=80,
        ).casefold().replace(" ", "_")
        target_emotion = self._target_emotion(plan, story, analysis)
        if target_emotion == "informative" and understanding.get("target_emotion"):
            target_emotion = _text(
                understanding.get("target_emotion"), maximum=80
            ).casefold().replace(" ", "_")
        story_angle = _text(
            plan.get("story_shape")
            or story.get("story_shape")
            or story.get("story_summary")
            or plan.get("selected_reason")
            or planning.get("selected_reason")
            or understanding.get("story_angle")
            or "Deliver one self-contained idea with a clear payoff.",
            maximum=400,
        )
        curiosity_trigger = hook_line or self._curiosity_trigger(hook_type, story_angle)
        hook_score = _score(
            plan.get("hook_score")
            or _dict(plan.get("scores")).get("hook")
            or virality.get("hook_score")
        )
        emotion_score = _score(
            plan.get("emotion_score")
            or _dict(plan.get("scores")).get("emotion")
            or virality.get("emotion_score")
        )
        pacing = self._pacing(hook_score, emotion_score, recommended_duration, target_emotion)
        caption_style = self._caption_style(hook_type, target_emotion)
        motion_style = self._motion_style(pacing, target_emotion)
        music_mood = self._music_mood(target_emotion, pacing)
        pacing_preference = self._memory_preference(records, "pacing_level", pacing)
        if pacing_preference in {"calm", "balanced", "fast", "aggressive"}:
            pacing = cast(PacingLevel, pacing_preference)
        caption_style = self._memory_preference(records, "caption_style", caption_style)
        motion_style = self._memory_preference(records, "motion_style", motion_style)
        music_mood = self._memory_preference(records, "music_mood", music_mood)
        risks = self._risk_warnings(signals, plan, analysis)
        editing_notes = [
            f"Open with a {hook_type.replace('_', ' ')} hook and emphasize its strongest phrase.",
            f"Use {pacing} pacing while preserving setup and payoff.",
            "Use "
            f"{caption_style.replace('_', ' ')} captions and "
            f"{motion_style.replace('_', ' ')} motion.",
            "Treat music_mood as metadata only; select no copyrighted track.",
        ]
        upstream_note = _text(
            editing.get("editing_notes")
            or editing.get("pacing_style")
            or editing.get("edit_style"),
            maximum=260,
        )
        if upstream_note:
            editing_notes.append(f"Preserve upstream editing guidance: {upstream_note}")
        guidance_notes = [
            _text(item, maximum=260)
            for item in _list(understanding.get("notes"))
            if _text(item, maximum=260)
        ]
        editing_notes.extend(guidance_notes[:3])
        if understanding.get("setup_needed"):
            risks.append("Whole-video context map says this range needs earlier setup.")
        why = _text(
            virality.get("why_this_can_work")
            or virality.get("why_this_clip_works")
            or plan.get("selected_reason")
            or planning.get("selected_reason")
            or understanding.get("reason")
            or f"The {hook_type.replace('_', ' ')} opening supports a focused {story_angle} angle.",
            maximum=600,
        )
        return BobaCreativeBriefV1(
            clip_id=clip_id,
            project_id=project_id,
            target_emotion=target_emotion,
            hook_type=hook_type,
            curiosity_trigger=curiosity_trigger,
            story_angle=story_angle,
            recommended_duration_seconds=round(recommended_duration, 3),
            pacing_level=pacing,
            caption_style=caption_style,
            motion_style=motion_style,
            music_mood=music_mood,
            editing_notes=editing_notes,
            risk_warnings=risks,
            why_it_may_work=why,
            whole_video_understanding_used=bool(understanding.get("used")),
            understanding_guidance=guidance_notes[:8],
        )

    @staticmethod
    def _timeline(signals: dict[str, Any], clip_id: str) -> dict[str, Any]:
        return next(
            (
                _dict(item)
                for item in _list(signals.get("editing_timelines"))
                if _text(
                    _dict(item).get("clip_id")
                    or _dict(item).get("timeline_id")
                    or _dict(item).get("id"),
                    maximum=128,
                )
                == clip_id
            ),
            {},
        )

    @staticmethod
    def _transcript_hook(signals: dict[str, Any], start: float, end: float) -> str:
        for item in _list(signals.get("transcript_segments")):
            segment = _dict(item)
            segment_start = _number(segment.get("start"))
            if segment_start + 0.01 < start or (end and segment_start > end):
                continue
            text = _text(segment.get("text") or segment.get("transcript"), maximum=220)
            if text:
                return text
        return ""

    @staticmethod
    def _whole_video_guidance(
        signals: dict[str, Any], start: float, end: float
    ) -> dict[str, Any]:
        understanding = _dict(signals.get("whole_video_understanding"))
        if not understanding:
            return {}

        def overlap(item: dict[str, Any]) -> float:
            item_start = _number(item.get("start_seconds") or item.get("start"))
            item_end = _number(
                item.get("end_seconds") or item.get("end"), item_start
            )
            clip_end = end if end > start else start + 60.0
            return max(0.0, min(clip_end, item_end) - max(start, item_start))

        topics = [_dict(item) for item in _list(understanding.get("topic_timeline"))]
        topic = max(topics, key=overlap, default={})
        hints = [
            _dict(item) for item in _list(understanding.get("shortability_hints"))
        ]
        hint = max(hints, key=overlap, default={})
        beats = [_dict(item) for item in _list(understanding.get("emotional_beats"))]
        beat = max(beats, key=overlap, default={})
        notes: list[str] = []
        topic_name = _text(topic.get("topic"), maximum=160)
        if topic_name:
            notes.append(f"Use whole-video topic context: {topic_name}.")
        hint_reason = _text(hint.get("reason"), maximum=220)
        if hint_reason:
            notes.append(f"Whole-video shortability guidance: {hint_reason}")
        return {
            "used": True,
            "story_angle": (
                topic.get("summary")
                or understanding.get("overall_summary")
                or understanding.get("primary_topic")
            ),
            "target_emotion": beat.get("emotion_label"),
            "setup_needed": bool(hint.get("setup_needed")),
            "reason": hint_reason or understanding.get("overall_summary"),
            "notes": notes,
        }

    @staticmethod
    def _target_emotion(
        plan: dict[str, Any], story: dict[str, Any], analysis: dict[str, Any]
    ) -> str:
        emotion = _text(
            plan.get("target_emotion")
            or plan.get("emotion")
            or story.get("target_emotion")
            or story.get("dominant_emotion")
            or analysis.get("dominant_emotion")
            or _dict(analysis.get("emotion")).get("dominant")
            or "informative",
            maximum=80,
        )
        return emotion.casefold().replace(" ", "_")

    @staticmethod
    def _curiosity_trigger(hook_type: str, story_angle: str) -> str:
        if "curiosity" in hook_type or "open_loop" in hook_type:
            return f"Create an unanswered question around: {story_angle}"[:300]
        if "problem" in hook_type or "mistake" in hook_type:
            return f"Reveal the consequence before explaining: {story_angle}"[:300]
        return f"Promise one clear payoff: {story_angle}"[:300]

    @staticmethod
    def _pacing(
        hook_score: float,
        emotion_score: float,
        duration: float,
        target_emotion: str,
    ) -> PacingLevel:
        if target_emotion in {"reflective", "sad", "emotional", "empathetic"}:
            return "calm"
        if hook_score >= 0.82 and duration <= 35:
            return "aggressive"
        if hook_score >= 0.62 or emotion_score >= 0.7:
            return "fast"
        return "balanced"

    @staticmethod
    def _caption_style(hook_type: str, target_emotion: str) -> str:
        if "curiosity" in hook_type or "open_loop" in hook_type:
            return "bold_keyword_emphasis"
        if target_emotion in {"reflective", "sad", "emotional", "empathetic"}:
            return "restrained_cinematic"
        return "clean_high_contrast"

    @staticmethod
    def _motion_style(pacing: PacingLevel, target_emotion: str) -> str:
        if target_emotion in {"reflective", "sad", "emotional", "empathetic"}:
            return "subtle_stable"
        if pacing in {"fast", "aggressive"}:
            return "controlled_punch_in"
        return "gentle_emphasis"

    @staticmethod
    def _music_mood(target_emotion: str, pacing: PacingLevel) -> str:
        if target_emotion in {"reflective", "sad", "emotional", "empathetic"}:
            return "warm_reflective"
        if target_emotion in {"motivational", "hopeful", "triumphant"}:
            return "uplifting_momentum"
        if pacing in {"fast", "aggressive"}:
            return "clean_high_energy"
        return "subtle_modern"

    @staticmethod
    def _memory_preference(
        records: list[BobaMemoryRecordV1], field: str, fallback: str
    ) -> str:
        totals: dict[str, float] = {}
        for record in records:
            preferences = record.metadata.get("creative_preferences")
            if not isinstance(preferences, dict):
                continue
            values = preferences.get(field)
            if not isinstance(values, dict):
                continue
            for value, adjustment in values.items():
                if isinstance(adjustment, int | float) and not isinstance(adjustment, bool):
                    totals[str(value)] = totals.get(str(value), 0.0) + (
                        float(adjustment) * record.confidence
                    )
        preferred = (
            max(totals, key=lambda item: totals[item])
            if totals and max(totals.values()) > 0
            else None
        )
        return preferred or fallback

    @staticmethod
    def _risk_warnings(
        signals: dict[str, Any], plan: dict[str, Any], analysis: dict[str, Any]
    ) -> list[str]:
        warnings: list[str] = []
        if not analysis:
            warnings.append("analysis_signals_v2 is unavailable; brief uses fallback guidance.")
        if not signals.get("transcript_available"):
            warnings.append("Transcript is unavailable; hook wording requires human review.")
        if str(signals.get("safety_status") or "unknown").casefold() in {
            "unknown",
            "high",
            "blocked",
        }:
            warnings.append("Safety or rights status needs human review before processing.")
        if signals.get("safety_manual_review_required"):
            warnings.append("Existing Olympus safety metadata requires manual review.")
        context_risk = _score(
            plan.get("context_risk")
            or _dict(plan.get("story")).get("context_risk")
            or _dict(plan.get("unified_clip_intelligence")).get("context_risk")
        )
        if context_risk >= 0.6:
            warnings.append("High context dependency may make the clip confusing on its own.")
        return list(dict.fromkeys(warnings))


def _v2_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _v2_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _v2_unique(
    values: Sequence[Any], *, limit: int, maximum: int = 500
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _text(value, maximum=maximum)
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
        if len(result) >= limit:
            break
    return result


def _score_100(value: Any, default: float = 0.0) -> float:
    parsed = _number(value, default)
    if 0.0 <= parsed <= 1.0 and parsed != 0.0:
        parsed *= 100.0
    return round(max(0.0, min(100.0, parsed)), 2)


class BobaCreativeDirectorV2Engine:
    """Deepen saved editorial choices into deterministic advisory edit direction."""

    def direct(
        self,
        *,
        project_id: str,
        editorial_decisions: Mapping[str, Any] | BaseModel | None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
        analysis_signal_health: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaCreativeDirectionSetV2:
        editorial = _v2_dict(editorial_decisions)
        if not editorial:
            raise ValidationError(
                "BOBA Creative Director V2 requires saved editorial decisions.",
                details={"project_id": project_id, "required_artifact": "editorial_decision"},
            )
        artifact_project_id = _text(editorial.get("project_id"), maximum=128)
        if artifact_project_id and artifact_project_id != project_id:
            raise ValidationError(
                "BOBA editorial decisions belong to a different project.",
                details={
                    "project_id": project_id,
                    "artifact_project_id": artifact_project_id,
                },
            )

        decisions = [
            item
            for value in _v2_list(editorial.get("decisions"))
            if (item := _v2_dict(value))
        ]
        selected = [item for item in decisions if bool(item.get("selected"))][:10]
        ranking = _v2_dict(clip_ranking)
        discovery = _v2_dict(candidate_discovery)
        understanding = _v2_dict(whole_video_understanding)
        explanation_set = _v2_dict(explanations)
        memory_data = _v2_dict(memory)
        analysis = self._analysis_context(analysis_signal_health)

        ranked_by_id = {
            candidate_id: item
            for value in _v2_list(ranking.get("ranked_candidates"))
            if (item := _v2_dict(value))
            and (candidate_id := _text(item.get("candidate_id"), maximum=128))
        }
        discovered_by_id = {
            candidate_id: item
            for value in _v2_list(discovery.get("candidates"))
            if (item := _v2_dict(value))
            and (candidate_id := _text(item.get("candidate_id"), maximum=128))
        }
        explanations_by_id = self._explanations_by_candidate(explanation_set)
        selected_ids = {
            _text(item.get("candidate_id"), maximum=128) for item in selected
        }
        ranking_used = any(candidate_id in ranked_by_id for candidate_id in selected_ids)
        discovery_used = any(
            candidate_id in discovered_by_id for candidate_id in selected_ids
        )
        clip_explanations_used = any(
            candidate_id in explanations_by_id for candidate_id in selected_ids
        )
        project_explanation = _v2_dict(explanation_set.get("project_summary"))
        explanations_used = clip_explanations_used or bool(
            _text(project_explanation.get("overall_summary"))
        )
        memory_used = bool(
            _text(memory_data.get("source_summary"))
            or _v2_list(memory_data.get("main_topics"))
            or _v2_list(memory_data.get("known_limitations"))
        )
        understanding_used = bool(understanding)
        analysis_used = bool(analysis.get("available"))

        clip_directions = [
            self._clip_direction(
                project_id=project_id,
                decision=decision,
                ranked=ranked_by_id.get(
                    _text(decision.get("candidate_id"), maximum=128), {}
                ),
                candidate=discovered_by_id.get(
                    _text(decision.get("candidate_id"), maximum=128), {}
                ),
                understanding=understanding,
                explanations=explanations_by_id.get(
                    _text(decision.get("candidate_id"), maximum=128), []
                ),
                analysis=analysis,
            )
            for decision in selected
        ]

        unavailable: list[str] = []
        if not explanations_used:
            unavailable.append("explanations")
        if not ranking_used:
            unavailable.append("clip_ranking")
        if not discovery_used:
            unavailable.append("candidate_discovery")
        if not understanding_used:
            unavailable.append("whole_video_understanding")
        if not analysis_used:
            unavailable.append("analysis_signal_health")
        if not memory_used:
            unavailable.append("project_memory")
        unavailable.extend(_v2_list(analysis.get("unavailable")))
        unavailable = _v2_unique(unavailable, limit=32, maximum=160)
        warnings = _v2_unique(
            [
                *(_v2_list(editorial.get("warnings"))),
                *(_v2_list(ranking.get("warnings"))),
                *(_v2_list(discovery.get("warnings"))),
                *(_v2_list(understanding.get("warnings"))),
                *(_v2_list(explanation_set.get("warnings"))),
                *(_v2_list(analysis.get("warnings"))),
                *(
                    ["No selected editorial decisions were available for clip direction."]
                    if not selected
                    else []
                ),
            ],
            limit=64,
        )
        fallback_used = bool(unavailable) or any(
            "fallback" in warning.casefold()
            or "unavailable" in warning.casefold()
            or "missing" in warning.casefold()
            for direction in clip_directions
            for warning in direction.warnings
        )
        signal_usage = BobaCreativeDirectorSignalUsageV2(
            editorial_decisions_used=True,
            explanations_used=explanations_used,
            clip_ranking_used=ranking_used,
            candidate_discovery_used=discovery_used,
            whole_video_understanding_used=understanding_used,
            analysis_signals_used=analysis_used,
            memory_used=memory_used,
            fallback_used=fallback_used,
            unavailable_signals=unavailable,
            warnings=_v2_unique(
                [
                    *(_v2_list(analysis.get("warnings"))),
                    *(
                        [
                            "Optional BOBA inputs were unavailable; saved editorial "
                            "choices were used as the fallback authority."
                        ]
                        if unavailable
                        else []
                    ),
                ],
                limit=32,
            ),
        )
        project_direction = self._project_direction(
            selected=selected,
            understanding=understanding,
            explanation=project_explanation,
            memory=memory_data if memory_used else {},
            analysis=analysis,
            editorial=editorial,
        )
        return BobaCreativeDirectionSetV2(
            project_id=project_id,
            source_id=_text(
                editorial.get("source_id") or understanding.get("source_id"),
                maximum=512,
            ),
            project_direction=project_direction,
            clip_directions=clip_directions,
            creative_quality_summary=self._quality_summary(clip_directions),
            signal_usage=signal_usage,
            warnings=warnings,
            limitations=[
                "Creative Director V2 is advisory and does not modify editing "
                "timelines or render media.",
                "Music direction is mood metadata only; no song, asset path, or "
                "copyright-safety claim is produced.",
                "Creative quality scores summarize saved evidence and do not "
                "predict audience performance.",
                "Human review remains required for source meaning, rights, "
                "framing, speech clarity, and final edit quality.",
            ],
        )

    def direct_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        editorial_decisions: Mapping[str, Any] | BaseModel | None = None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaCreativeDirectionSetV2:
        analysis = {
            "analysis_signals_v2": _v2_dict(signals.get("analysis_signals_v2")),
            "transcript_available": bool(signals.get("transcript_available")),
            "face_signals_available": bool(signals.get("face_signals_available")),
            "speaker_signals_available": bool(signals.get("speaker_signals_available")),
            "visual_signals_available": bool(signals.get("visual_signals_available")),
        }
        return self.direct(
            project_id=project_id,
            editorial_decisions=(
                editorial_decisions or _v2_dict(signals.get("editorial_decisions"))
            ),
            clip_ranking=clip_ranking or _v2_dict(signals.get("clip_ranking")),
            candidate_discovery=(
                candidate_discovery or _v2_dict(signals.get("candidate_clip_discovery"))
            ),
            whole_video_understanding=(
                whole_video_understanding
                or _v2_dict(signals.get("whole_video_understanding"))
            ),
            explanations=explanations or _v2_dict(signals.get("explanations")),
            memory=memory,
            analysis_signal_health=analysis,
        )

    def _clip_direction(
        self,
        *,
        project_id: str,
        decision: Mapping[str, Any],
        ranked: Mapping[str, Any],
        candidate: Mapping[str, Any],
        understanding: Mapping[str, Any],
        explanations: Sequence[Mapping[str, Any]],
        analysis: Mapping[str, Any],
    ) -> BobaClipCreativeDirectionV2:
        candidate_id = _text(decision.get("candidate_id"), maximum=128) or "candidate"
        ranked_clip_id = (
            _text(decision.get("ranked_clip_id"), maximum=128) or candidate_id
        )
        angle = _text(
            decision.get("final_story_angle")
            or candidate.get("story_angle")
            or ranked.get("story_angle")
            or "Present one self-contained idea and preserve its payoff.",
            maximum=500,
        )
        hook_type = _text(
            decision.get("final_hook_strategy") or "direct_value", maximum=80
        ).casefold().replace(" ", "_")
        opening_line = _text(
            decision.get("opening_line_direction")
            or candidate.get("hook_idea")
            or ranked.get("hook_idea")
            or "State the clip's value immediately.",
            maximum=500,
        )
        risk = _v2_dict(decision.get("risk_review"))
        window = _v2_dict(decision.get("source_window"))
        duration = self._duration(window, candidate)
        educational = self._matches(
            decision,
            ranked,
            candidate,
            needles=("educat", "tutorial", "lesson", "explain", "how_to"),
        )
        emotional = self._matches(
            decision,
            ranked,
            candidate,
            needles=(
                "emotion",
                "reflect",
                "heart",
                "sad",
                "hope",
                "cinematic",
                "vulnerab",
            ),
        )
        motivational = self._matches(
            decision,
            ranked,
            candidate,
            needles=("motivat", "inspir", "triumph", "uplift", "transformation"),
        )
        high_energy = str(decision.get("pacing_intensity") or "").casefold() in {
            "fast",
            "aggressive",
        } or self._matches(
            decision,
            ranked,
            candidate,
            needles=("energetic", "high_energy", "shocking_truth", "contradiction"),
        )
        face_available = bool(analysis.get("face_available"))
        visual_available = bool(analysis.get("visual_available"))
        layout_risk = bool(risk.get("visual_layout_risk"))
        safe_motion = layout_risk or not face_available or not visual_available
        explanation_reason = self._explanation_reason(explanations)
        ranking_reasons = _v2_unique(
            _v2_list(ranked.get("ranking_reasons")), limit=3, maximum=350
        )
        decision_reasons = _v2_unique(
            _v2_list(decision.get("decision_reasons")), limit=3, maximum=350
        )
        reason_source = (
            explanation_reason
            or (decision_reasons[0] if decision_reasons else "")
            or (ranking_reasons[0] if ranking_reasons else "")
            or "The saved editorial decision identifies a clear hook and self-contained angle."
        )
        hook_treatment = BobaHookTreatmentV2(
            hook_type=hook_type,
            opening_line_direction=opening_line,
            first_visual_emphasis=self._first_visual(
                decision,
                hook_type=hook_type,
                motivational=motivational,
                safe_motion=safe_motion,
            ),
            curiosity_trigger=self._curiosity_trigger_v2(
                hook_type,
                candidate=candidate,
                angle=angle,
            ),
            pattern_interrupt=self._pattern_interrupt(
                hook_type=hook_type,
                high_energy=high_energy,
                safe_motion=safe_motion,
            ),
            reason_it_should_work=_text(
                f"{reason_source} This is an evidence-bound creative hypothesis, "
                "not audience-performance proof.",
                maximum=700,
            ),
            hook_risk=self._hook_risk(risk=risk, ranked=ranked),
        )
        opening_plan = BobaOpeningThreeSecondPlanV2(
            what_viewer_sees_first=hook_treatment.first_visual_emphasis,
            caption_implication=_text(
                f"Make the first caption imply: {opening_line}", maximum=500
            ),
            curiosity_gap=hook_treatment.curiosity_trigger,
            motion_choice=(
                "Stay stable and layout-safe until the speaker and framing are visually reliable."
                if safe_motion
                else "Use one clean opening punch-in, then settle before the next editorial beat."
            ),
            avoid=_v2_unique(
                [
                    "Avoid dead air or a slow fade-in before the meaningful opening line.",
                    "Avoid stacking multiple motion or SFX events in the first three seconds.",
                    *(
                        ["Avoid face-dependent crop moves until layout signals are verified."]
                        if safe_motion
                        else []
                    ),
                ],
                limit=12,
            ),
        )
        pacing_map = self._pacing_map(
            decision=decision,
            candidate=candidate,
            understanding=understanding,
            duration=duration,
            high_energy=high_energy,
            emotional=emotional,
            risk=risk,
        )
        caption_direction = self._caption_direction(
            decision=decision,
            ranked=ranked,
            candidate=candidate,
            hook_type=hook_type,
            educational=educational,
            emotional=emotional,
            high_energy=high_energy,
            analysis=analysis,
        )
        motion_direction = self._motion_direction(
            decision=decision,
            safe_motion=safe_motion,
            face_available=face_available,
            visual_available=visual_available,
            high_energy=high_energy,
            emotional=emotional,
            duration=duration,
        )
        audio_direction = self._audio_direction(
            decision=decision,
            risk=risk,
            analysis=analysis,
            high_energy=high_energy,
            emotional=emotional,
        )
        retention_plan = self._retention_plan(
            decision=decision,
            candidate=candidate,
            hook=hook_treatment,
            duration=duration,
            risk=risk,
        )
        emotional_arc = self._emotional_arc(
            decision=decision,
            candidate=candidate,
            understanding=understanding,
            window=window,
            emotional=emotional,
            motivational=motivational,
        )
        quality = self._quality_score(
            decision=decision,
            ranked=ranked,
            risk=risk,
            analysis=analysis,
            caption=caption_direction,
            audio=audio_direction,
        )
        risk_fixes = self._risk_fixes(
            decision=decision,
            candidate=candidate,
            risk=risk,
            safe_motion=safe_motion,
            analysis=analysis,
        )
        instruction_packet = _v2_dict(decision.get("editing_instruction_packet"))
        editor_notes = _v2_unique(
            [
                instruction_packet.get("hook_instruction"),
                instruction_packet.get("cut_instruction"),
                instruction_packet.get("caption_instruction"),
                instruction_packet.get("motion_instruction"),
                instruction_packet.get("audio_instruction"),
                instruction_packet.get("retention_instruction"),
                *(
                    [f"Explanation context: {explanation_reason}"]
                    if explanation_reason
                    else []
                ),
                "Treat this direction as advisory; confirm choices during human edit review.",
            ],
            limit=24,
        )
        warnings = _v2_unique(
            [
                *(_v2_list(decision.get("improvement_notes"))),
                *(_v2_list(ranked.get("risk_warnings"))),
                *(_v2_list(candidate.get("warnings"))),
                *(
                    [
                        "Face/layout signals are unavailable; motion direction "
                        "uses a stable safety fallback."
                    ]
                    if not face_available
                    else []
                ),
                *(
                    ["Visual signals are unavailable; visual emphasis requires human review."]
                    if not visual_available
                    else []
                ),
                *(
                    [
                        "Candidate discovery was unavailable; editorial direction "
                        "supplied fallback context."
                    ]
                    if not candidate
                    else []
                ),
                *(
                    [
                        "Clip ranking was unavailable; editorial ranking score "
                        "supplied fallback quality inputs."
                    ]
                    if not ranked
                    else []
                ),
            ],
            limit=32,
        )
        confidence_values = [
            _score(decision.get("confidence")),
            *([_score(ranked.get("confidence"))] if ranked else []),
            *([_score(candidate.get("confidence"))] if candidate else []),
        ]
        confidence = sum(confidence_values) / max(1, len(confidence_values))
        if safe_motion:
            confidence *= 0.9
        return BobaClipCreativeDirectionV2(
            candidate_id=candidate_id,
            ranked_clip_id=ranked_clip_id,
            project_id=project_id,
            selected=True,
            render_readiness=_text(
                decision.get("render_readiness") or "needs_revision", maximum=80
            ),
            final_clip_angle=angle,
            hook_treatment=hook_treatment,
            opening_three_second_plan=opening_plan,
            story_framing=self._story_framing(
                angle=angle,
                candidate=candidate,
                risk=risk,
            ),
            pacing_map=pacing_map,
            caption_direction=caption_direction,
            motion_direction=motion_direction,
            audio_direction=audio_direction,
            retention_plan=retention_plan,
            emotional_arc=emotional_arc,
            creative_quality_score=quality,
            risk_fixes=risk_fixes,
            editor_notes=editor_notes,
            warnings=warnings,
            confidence=round(max(0.0, min(1.0, confidence)), 3),
        )

    @staticmethod
    def _project_direction(
        *,
        selected: Sequence[Mapping[str, Any]],
        understanding: Mapping[str, Any],
        explanation: Mapping[str, Any],
        memory: Mapping[str, Any],
        analysis: Mapping[str, Any],
        editorial: Mapping[str, Any],
    ) -> BobaProjectCreativeDirectionV2:
        tone = _text(understanding.get("tone"), maximum=120)
        if not tone:
            moods = [
                _text(item.get("music_mood"), maximum=80)
                for item in selected
                if _text(item.get("music_mood"), maximum=80)
            ]
            tone = BobaCreativeDirectorV2Engine._mode(moods) or "clear and grounded"
        style_text = " ".join(
            _text(
                item.get("candidate_type")
                or item.get("final_story_angle")
                or item.get("music_mood"),
                maximum=160,
            ).casefold()
            for item in selected
        )
        if any(word in style_text for word in ("educat", "lesson", "explain", "how to")):
            overall_style = "Educational, clean, clarity-first, and payoff-led"
            viewer_feeling = "Confident that one useful idea was understood quickly and completely."
        elif any(word in style_text for word in ("emotion", "reflect", "cinematic", "heart")):
            overall_style = "Emotional, cinematic, restrained, and payoff-driven"
            viewer_feeling = "Emotionally connected, then rewarded by a complete final thought."
        elif any(word in style_text for word in ("motivat", "triumph", "energetic")):
            overall_style = "Motivational, momentum-led, punchy, and speech-first"
            viewer_feeling = "Energized by a credible transformation or practical takeaway."
        else:
            overall_style = "Story-led, clean, retention-aware, and speech-first"
            viewer_feeling = "Curious immediately, oriented quickly, and satisfied by the payoff."
        paces = [
            _text(item.get("pacing_intensity"), maximum=80) for item in selected
        ]
        dominant_pace = BobaCreativeDirectorV2Engine._mode(paces) or "moderate"
        captions = [_text(item.get("caption_style"), maximum=80) for item in selected]
        motions = [_text(item.get("motion_style"), maximum=80) for item in selected]
        moods = [_text(item.get("music_mood"), maximum=80) for item in selected]
        face_available = bool(analysis.get("face_available"))
        visual_available = bool(analysis.get("visual_available"))
        human_notes = [
            "Confirm source meaning, rights, framing, speech clarity, and final "
            "edit quality before production.",
            *(
                [
                    "Face or visual layout evidence is unavailable; keep motion "
                    "conservative until framing is reviewed."
                ]
                if not face_available or not visual_available
                else []
            ),
            *(
                [
                    f"Explanation context: {_text(explanation.get('overall_summary'), maximum=500)}"
                ]
                if _text(explanation.get("overall_summary"))
                else []
            ),
            *(
                [
                    "Bounded project-memory context: "
                    f"{_text(memory.get('source_summary'), maximum=400)}"
                ]
                if _text(memory.get("source_summary"))
                else []
            ),
            *(_v2_list(editorial.get("limitations"))),
        ]
        return BobaProjectCreativeDirectionV2(
            overall_style=overall_style,
            tone=tone,
            pacing_philosophy=(
                f"Use {dominant_pace.replace('_', ' ')} pacing as the baseline, "
                "remove only verified filler, "
                "and preserve setup, meaning, payoff, and ending breath."
            ),
            caption_philosophy=(
                "Use "
                f"{BobaCreativeDirectorV2Engine._mode(captions) or 'clean subtitles'} "
                "as the baseline; "
                "emphasize only hook and payoff words while preserving readability."
            ),
            motion_philosophy=(
                "Use "
                f"{BobaCreativeDirectorV2Engine._mode(motions) or 'stable'} motion "
                "as the baseline; "
                "prefer stable, layout-safe framing whenever face or visual evidence is incomplete."
            ),
            audio_philosophy=(
                "Use "
                f"{BobaCreativeDirectorV2Engine._mode(moods) or 'subtle'} music "
                "mood metadata only, "
                "keep speech dominant, and use sparse clean SFX rather than noise-like effects."
            ),
            target_viewer_feeling=viewer_feeling,
            human_review_notes=_v2_unique(human_notes, limit=24),
        )

    @staticmethod
    def _first_visual(
        decision: Mapping[str, Any],
        *,
        hook_type: str,
        motivational: bool,
        safe_motion: bool,
    ) -> str:
        emphasis = _v2_unique(
            _v2_list(decision.get("visual_emphasis")), limit=2, maximum=300
        )
        if safe_motion:
            return (
                "Open on a stable, layout-safe view of the current speaker or subject; "
                "do not crop-switch before identity and framing are clear."
            )
        if motivational:
            return (
                "Lead with the strongest transformation or payoff image and one "
                "controlled punch-in."
            )
        if emphasis:
            return _text(f"Lead with {emphasis[0]} and make it readable immediately.", maximum=500)
        return _text(
            f"Open on the clearest subject while the {hook_type.replace('_', ' ')} line begins.",
            maximum=500,
        )

    @staticmethod
    def _curiosity_trigger_v2(
        hook_type: str, *, candidate: Mapping[str, Any], angle: str
    ) -> str:
        hook_idea = _text(candidate.get("hook_idea"), maximum=300)
        subject = hook_idea or angle
        if hook_type in {"curiosity_gap", "educational_open_loop", "story_turn"}:
            return _text(
                f"Open one specific unanswered question around: {subject}",
                maximum=500,
            )
        if hook_type in {"contradiction", "shocking_truth"}:
            return _text(
                "Show the surprising claim first, then withhold its reason briefly: "
                f"{subject}",
                maximum=500,
            )
        if hook_type == "problem_solution":
            return _text(
                f"Show the consequence before revealing the fix: {subject}",
                maximum=500,
            )
        return _text(
            f"Promise one concrete payoff and deliver it inside this clip: {subject}",
            maximum=500,
        )

    @staticmethod
    def _pattern_interrupt(
        *, hook_type: str, high_energy: bool, safe_motion: bool
    ) -> str:
        if safe_motion:
            return (
                "Use an immediate caption contrast or clean opening cut; avoid "
                "unsafe reframing as the interrupt."
            )
        if high_energy or hook_type in {"contradiction", "shocking_truth"}:
            return (
                "Use one decisive opening cut and controlled punch-in, then return "
                "to stable framing."
            )
        return (
            "Use a clean opening cut plus selective keyword emphasis rather than "
            "continuous motion."
        )

    @staticmethod
    def _hook_risk(*, risk: Mapping[str, Any], ranked: Mapping[str, Any]) -> str:
        hook_score = _score_100(
            _v2_dict(ranked.get("score_breakdown")).get("hook_score")
        )
        if bool(risk.get("weak_hook")) or (ranked and hook_score < 60.0):
            return (
                "The saved hook evidence is weak; tighten the first line and verify "
                "its value without inventing a claim."
            )
        if bool(risk.get("missing_context")):
            return (
                "The hook may confuse viewers without a minimal context phrase "
                "before the open loop."
            )
        return (
            "No specific hook blocker was saved, but timing and wording still "
            "require human review."
        )

    @staticmethod
    def _pacing_map(
        *,
        decision: Mapping[str, Any],
        candidate: Mapping[str, Any],
        understanding: Mapping[str, Any],
        duration: float,
        high_energy: bool,
        emotional: bool,
        risk: Mapping[str, Any],
    ) -> BobaPacingMapV2:
        intensity = _text(decision.get("pacing_intensity") or "moderate", maximum=80)
        if emotional:
            middle = (
                "Let the emotional turn breathe; avoid jump cuts that damage "
                "sincerity or meaning."
            )
        elif high_energy:
            middle = (
                "Maintain momentum with purposeful cuts at idea changes, not "
                "arbitrary rapid edits."
            )
        else:
            middle = (
                "Use clean cuts at semantic beats and keep the explanation easy "
                "to follow."
            )
        filler_notes: list[Any] = []
        if bool(risk.get("filler_risk")):
            filler_notes.append(
                "Remove verified pauses or repetition, but never cut required setup "
                "or payoff words."
            )
        for value in _v2_list(understanding.get("section_scores")):
            section = _v2_dict(value)
            if (
                BobaCreativeDirectorV2Engine._overlaps_window(
                    section, decision, candidate
                )
                and _score(section.get("filler_score")) >= 0.6
            ):
                filler_notes.append(
                    "A whole-video section overlapping this clip has elevated filler "
                    "risk; review that span before trimming."
                )
                break
        if not filler_notes:
            filler_notes.append(
                "Keep cuts meaning-led; no unsupported filler removal is prescribed."
            )
        return BobaPacingMapV2(
            first_3_seconds=(
                "Start on the meaningful hook with no slow fade; establish value "
                "and visual focus immediately."
            ),
            seconds_3_to_10=(
                "Resolve basic context quickly while keeping the central curiosity "
                "or tension open."
            ),
            middle_section=middle,
            payoff_section=(
                "Slow the cut rhythm slightly around the payoff so the complete "
                "line remains understandable."
            ),
            ending=(
                "Preserve the final thought and a brief ending hold within the "
                f"approximately {duration:.1f}-second clip."
            ),
            pacing_intensity=intensity,
            filler_cut_notes=_v2_unique(filler_notes, limit=16),
        )

    @staticmethod
    def _caption_direction(
        *,
        decision: Mapping[str, Any],
        ranked: Mapping[str, Any],
        candidate: Mapping[str, Any],
        hook_type: str,
        educational: bool,
        emotional: bool,
        high_energy: bool,
        analysis: Mapping[str, Any],
    ) -> BobaCaptionDirectionV2:
        style = _text(decision.get("caption_style") or "clean_subtitles", maximum=80)
        if educational and style not in {"clean_subtitles", "keyword_highlight"}:
            style = "keyword_highlight"
        if emotional and style == "bold_hook_captions":
            style = "emotional_emphasis"
        words = BobaCreativeDirectorV2Engine._emphasis_words(
            decision.get("opening_line_direction"),
            candidate.get("hook_idea"),
            ranked.get("suggested_title"),
        )
        rhythm = (
            "Use short phrase groups at idea beats; highlight one keyword at a "
            "time and leave breathing room."
            if high_energy
            else "Use readable phrase groups synchronized to speech; keep most "
            "subtitles clean and emphasize selectively."
        )
        if emotional:
            rhythm = (
                "Use restrained phrase groups with longer holds on emotionally "
                "important words and the payoff."
            )
        warnings = []
        if not bool(analysis.get("transcript_available")):
            warnings.append(
                "Transcript availability is not confirmed; caption wording and "
                "timing require review."
            )
        if style == "none":
            warnings.append(
                "Editorial direction disables captions; verify accessibility and "
                "comprehension before use."
            )
        return BobaCaptionDirectionV2(
            style=style,
            emphasis_words=words,
            rhythm=rhythm,
            highlight_moments=[
                "Highlight the strongest "
                f"{hook_type.replace('_', ' ')} word during the opening line.",
                "Highlight the decisive word in the payoff, then return to clean subtitles.",
            ],
            readability_notes=[
                "Keep captions readable inside vertical-safe margins and away from "
                "faces or key visual details.",
                "Prefer one or two lines with high contrast; do not emphasize every "
                "spoken word.",
            ],
            warnings=warnings,
        )

    @staticmethod
    def _motion_direction(
        *,
        decision: Mapping[str, Any],
        safe_motion: bool,
        face_available: bool,
        visual_available: bool,
        high_energy: bool,
        emotional: bool,
        duration: float,
    ) -> BobaMotionDirectionV2:
        requested = _text(decision.get("motion_style") or "stable", maximum=80)
        style = "layout_safe" if safe_motion else requested
        if emotional and not safe_motion and requested in {
            "high_motion",
            "dynamic_zoom",
        }:
            style = "subtle_zoom"
        safety_warnings: list[Any] = []
        if not face_available:
            safety_warnings.append(
                "Face/layout signals are unavailable; do not prescribe "
                "face-dependent crop tracking."
            )
        if not visual_available:
            safety_warnings.append(
                "Visual signal health is unavailable; confirm every motion cue "
                "against the source frame."
            )
        if safe_motion and requested not in {"stable", "layout_safe"}:
            safety_warnings.append(
                f"Editorial motion style '{requested}' was softened to layout-safe "
                "advisory direction because framing evidence is incomplete."
            )
        punch = []
        zoom = []
        if not safe_motion:
            punch.append("Use one punch-in on the strongest opening hook word.")
            if high_energy:
                punch.append(
                    "Use at most one additional punch-in at the main turn or reveal."
                )
            if emotional:
                zoom.append(
                    "Use a slow, subtle zoom through the emotional build; stop "
                    "before the payoff line."
                )
            else:
                zoom.append("Use a gentle emphasis zoom only across a meaningful idea beat.")
        return BobaMotionDirectionV2(
            style=style,
            zoom_moments=zoom,
            punch_in_moments=punch,
            stable_moments=[
                "Hold stable while setup or context is spoken.",
                "Hold stable through the complete payoff and final words.",
            ],
            layout_safe_moments=[
                "Keep the opening subject inside safe framing until speaker/layout "
                "identity is clear.",
                "Avoid crop switching near the ending of the approximately "
                f"{duration:.1f}-second clip.",
            ],
            visual_emphasis_moments=_v2_unique(
                [
                    *(_v2_list(decision.get("visual_emphasis"))),
                    "Opening hook",
                    "Main turn or reveal",
                    "Final payoff",
                ],
                limit=16,
            ),
            safety_warnings=_v2_unique(safety_warnings, limit=24),
        )

    @staticmethod
    def _audio_direction(
        *,
        decision: Mapping[str, Any],
        risk: Mapping[str, Any],
        analysis: Mapping[str, Any],
        high_energy: bool,
        emotional: bool,
    ) -> BobaAudioDirectionV2:
        mood = _text(decision.get("music_mood") or "none", maximum=80)
        sfx = _text(decision.get("sfx_intensity") or "none", maximum=80)
        warnings: list[Any] = [
            "Music mood is advisory metadata only; no track or asset is selected."
        ]
        if sfx == "heavy":
            warnings.append(
                "Heavy SFX can damage speech clarity; use sparse clean accents or "
                "reduce intensity after review."
            )
        if bool(risk.get("audio_risk")) or not bool(
            analysis.get("transcript_available")
        ):
            warnings.append(
                "Speech clarity evidence is incomplete or risky; review dialogue "
                "before mixing."
            )
        silence_notes = (
            "Preserve a brief intentional breath before the emotional payoff; "
            "remove only verified dead air."
            if emotional
            else "Remove only verified opening dead air; preserve pauses that carry "
            "meaning or emphasis."
        )
        ducking = (
            "Keep speech dominant and duck the music bed firmly under every spoken "
            "phrase; restore gently between phrases."
            if high_energy
            else "Keep speech dominant with conservative music ducking and smooth "
            "recovery between phrases."
        )
        return BobaAudioDirectionV2(
            music_mood=mood,
            sfx_intensity=sfx,
            ducking_guidance=ducking,
            silence_notes=silence_notes,
            speech_clarity_notes=(
                "Confirm every word remains intelligible after enhancement, music, "
                "and SFX; never mask the hook or payoff."
            ),
            warnings=_v2_unique(warnings, limit=24),
        )

    @staticmethod
    def _retention_plan(
        *,
        decision: Mapping[str, Any],
        candidate: Mapping[str, Any],
        hook: BobaHookTreatmentV2,
        duration: float,
        risk: Mapping[str, Any],
    ) -> BobaRetentionPlanV2:
        tactics = _v2_unique(
            _v2_list(decision.get("retention_tactics")), limit=5, maximum=400
        )
        risks: list[Any] = []
        if bool(risk.get("weak_hook")):
            risks.append("Weak opening evidence may reduce first-three-second clarity.")
        if bool(risk.get("missing_context")) or bool(candidate.get("context_needed")):
            risks.append(
                "Missing context may create confusion instead of productive curiosity."
            )
        if bool(risk.get("weak_payoff")) or candidate.get("payoff_present") is False:
            risks.append(
                "The payoff may be weak or absent; do not end before the complete "
                "thought."
            )
        if bool(risk.get("filler_risk")):
            risks.append("Filler may weaken the middle section; trim only after meaning review.")
        return BobaRetentionPlanV2(
            opening_hook=_text(
                f"Deliver the {hook.hook_type.replace('_', ' ')} opening immediately: "
                f"{hook.opening_line_direction}",
                maximum=500,
            ),
            curiosity_loop=hook.curiosity_trigger,
            mid_clip_hold=(
                tactics[0]
                if tactics
                else "Keep one unresolved question active while each sentence advances the answer."
            ),
            payoff_delivery=(
                "Let the complete payoff line land with cleaner captions, stable "
                "framing, and no competing SFX."
            ),
            replay_trigger=_text(
                f"End the approximately {duration:.1f}-second clip on a concise "
                "takeaway or reveal that makes the opening newly meaningful.",
                maximum=500,
            ),
            retention_risks=_v2_unique(risks, limit=20),
        )

    @staticmethod
    def _emotional_arc(
        *,
        decision: Mapping[str, Any],
        candidate: Mapping[str, Any],
        understanding: Mapping[str, Any],
        window: Mapping[str, Any],
        emotional: bool,
        motivational: bool,
    ) -> BobaEmotionalArcV2:
        beats = [
            item
            for value in _v2_list(understanding.get("emotional_beats"))
            if (item := _v2_dict(value))
            and BobaCreativeDirectorV2Engine._overlaps(item, window)
        ]
        beats.sort(key=lambda item: _number(item.get("start_seconds")))
        fallback = _text(candidate.get("emotion_label"), maximum=120) or "focused curiosity"
        start = _text(beats[0].get("emotion_label"), maximum=120) if beats else fallback
        build = (
            _text(beats[len(beats) // 2].get("emotion_label"), maximum=120)
            if beats
            else ("rising determination" if motivational else "growing interest")
        )
        payoff = (
            _text(beats[-1].get("emotion_label"), maximum=120)
            if beats
            else ("earned motivation" if motivational else "clarity and resolution")
        )
        if emotional:
            feeling = "Connected to the speaker's emotion and satisfied by an unhurried payoff."
        elif motivational:
            feeling = "Energized by an earned shift from challenge to possibility."
        else:
            feeling = "Curious at the start and clear about the value by the ending."
        emotional_risk = (
            "The saved emotional evidence is limited; avoid manufacturing intensity "
            "with excessive music or motion."
            if not beats
            else "Preserve the source emotion; avoid edits that exaggerate or reverse its meaning."
        )
        if _text(decision.get("render_readiness")) == "blocked":
            emotional_risk += " This direction must not be treated as render approval."
        return BobaEmotionalArcV2(
            starting_emotion=start,
            build_emotion=build,
            payoff_emotion=payoff,
            intended_viewer_feeling=feeling,
            emotional_risk=_text(emotional_risk, maximum=500),
        )

    @staticmethod
    def _quality_score(
        *,
        decision: Mapping[str, Any],
        ranked: Mapping[str, Any],
        risk: Mapping[str, Any],
        analysis: Mapping[str, Any],
        caption: BobaCaptionDirectionV2,
        audio: BobaAudioDirectionV2,
    ) -> BobaCreativeQualityScoreV2:
        breakdown = _v2_dict(ranked.get("score_breakdown"))
        base = _score_100(decision.get("ranking_score"), 60.0)
        hook = _score_100(breakdown.get("hook_score"), base)
        clarity = _score_100(breakdown.get("clarity_score"), base)
        emotional = _score_100(breakdown.get("emotional_score"), base)
        pacing = _score_100(breakdown.get("pacing_score"), base)
        visual = (
            82.0
            if analysis.get("face_available") and analysis.get("visual_available")
            else 58.0
        )
        if risk.get("visual_layout_risk"):
            visual = min(visual, 52.0)
        caption_score = max(45.0, min(92.0, (clarity * 0.55) + (hook * 0.35) + 8.0))
        if caption.style == "none":
            caption_score = min(caption_score, 48.0)
        audio_score = 78.0
        if risk.get("audio_risk"):
            audio_score = 52.0
        if audio.sfx_intensity == "heavy":
            audio_score = min(audio_score, 60.0)
        values = [hook, clarity, emotional, pacing, visual, caption_score, audio_score]
        evidence_confidence = max(
            0.0, min(1.0, _number(decision.get("confidence"), 0.5))
        )
        overall = (sum(values) / len(values)) * (0.75 + (evidence_confidence * 0.25))
        return BobaCreativeQualityScoreV2(
            hook_quality=round(hook, 2),
            clarity=round(clarity, 2),
            emotional_pull=round(emotional, 2),
            pacing_strength=round(pacing, 2),
            visual_direction_strength=round(visual, 2),
            caption_strength=round(caption_score, 2),
            audio_direction_strength=round(audio_score, 2),
            overall_confidence=round(max(0.0, min(100.0, overall)), 2),
        )

    @staticmethod
    def _risk_fixes(
        *,
        decision: Mapping[str, Any],
        candidate: Mapping[str, Any],
        risk: Mapping[str, Any],
        safe_motion: bool,
        analysis: Mapping[str, Any],
    ) -> list[str]:
        fixes: list[Any] = []
        if risk.get("weak_hook"):
            fixes.append(
                "Improve the hook by stating one specific value, tension, or "
                "contradiction immediately."
            )
        if (
            risk.get("missing_context")
            or candidate.get("context_needed")
            or candidate.get("setup_required")
        ):
            fixes.append(
                "Add the minimum missing context before the claim; do not replace "
                "context with a misleading caption."
            )
        if risk.get("weak_payoff") or candidate.get("payoff_present") is False:
            fixes.append("Preserve or restore the complete payoff before the ending hold.")
        if risk.get("filler_risk"):
            fixes.append(
                "Reduce verified filler while preserving setup, emotional turn, "
                "and payoff wording."
            )
        if safe_motion:
            fixes.append(
                "Keep motion stable and layout-safe until face and framing evidence "
                "is verified."
            )
        if risk.get("audio_risk") or not analysis.get("transcript_available"):
            fixes.append("Check speech clarity manually before adding music or SFX.")
        if _text(decision.get("sfx_intensity")) == "heavy":
            fixes.append(
                "Avoid heavy SFX by default; use sparse, clean accents that never "
                "mask speech."
            )
        if risk.get("rights_risk"):
            fixes.append(
                "Require human rights review; creative direction does not establish "
                "copyright safety."
            )
        if risk.get("unavailable_signal_risk"):
            fixes.append(
                "Complete human review because one or more source signals were "
                "unavailable."
            )
        if _text(decision.get("render_readiness")) != "ready_for_render":
            fixes.append(
                "Resolve the saved render-readiness issue before any downstream "
                "production decision."
            )
        return _v2_unique(
            [*fixes, *(_v2_list(decision.get("improvement_notes")))], limit=24
        )

    @staticmethod
    def _story_framing(
        *, angle: str, candidate: Mapping[str, Any], risk: Mapping[str, Any]
    ) -> str:
        setup = "Include only the minimum setup needed for standalone clarity."
        if candidate.get("setup_required") or risk.get("missing_context"):
            setup = "Restore the minimum verified setup before advancing to the main claim."
        payoff = (
            "Preserve the complete saved payoff and let the ending resolve the opening."
            if candidate.get("payoff_present") is not False
            else "The saved candidate lacks confirmed payoff evidence; repair or "
            "reject before production."
        )
        return _text(f"Frame the clip as: {angle}. {setup} {payoff}", maximum=700)

    @staticmethod
    def _quality_summary(
        directions: Sequence[BobaClipCreativeDirectionV2],
    ) -> BobaCreativeQualityScoreV2:
        fields = (
            "hook_quality",
            "clarity",
            "emotional_pull",
            "pacing_strength",
            "visual_direction_strength",
            "caption_strength",
            "audio_direction_strength",
            "overall_confidence",
        )
        if not directions:
            return BobaCreativeQualityScoreV2(**dict.fromkeys(fields, 0.0))
        values = {
            field: round(
                sum(getattr(item.creative_quality_score, field) for item in directions)
                / len(directions),
                2,
            )
            for field in fields
        }
        return BobaCreativeQualityScoreV2(**values)

    @staticmethod
    def _analysis_context(
        value: Mapping[str, Any] | BaseModel | None,
    ) -> dict[str, Any]:
        raw = _v2_dict(value)
        root = _v2_dict(raw.get("analysis_signals_v2")) or raw
        explicit_keys = {
            "transcript_available",
            "face_signals_available",
            "speaker_signals_available",
            "visual_signals_available",
        }
        available = bool(root) or any(key in raw for key in explicit_keys)

        def resolved(explicit: str, *needles: str) -> bool:
            if explicit in raw:
                return bool(raw.get(explicit))
            return BobaCreativeDirectorV2Engine._nested_signal_available(root, needles)

        transcript = resolved("transcript_available", "transcript", "speech")
        face = resolved("face_signals_available", "face")
        speaker = resolved("speaker_signals_available", "speaker", "diarization")
        visual = resolved("visual_signals_available", "visual", "scene", "video", "face")
        unavailable = []
        if available:
            if not transcript:
                unavailable.append("transcript")
            if not face:
                unavailable.append("face_layout_signals")
            if not speaker:
                unavailable.append("speaker_signals")
            if not visual:
                unavailable.append("visual_signals")
        warnings = []
        if available and not face:
            warnings.append(
                "Face/layout signals are unavailable; stable motion fallback is "
                "required."
            )
        if available and not visual:
            warnings.append(
                "Visual signal health is unavailable; visual direction needs human "
                "review."
            )
        return {
            "available": available,
            "transcript_available": transcript,
            "face_available": face,
            "speaker_available": speaker,
            "visual_available": visual,
            "unavailable": unavailable,
            "warnings": warnings,
        }

    @staticmethod
    def _nested_signal_available(
        value: Mapping[str, Any], needles: Sequence[str]
    ) -> bool:
        for key, item in value.items():
            normalized = str(key).casefold()
            matched = any(needle in normalized for needle in needles)
            if isinstance(item, Mapping):
                status = str(item.get("status") or "").casefold()
                item_available = item.get("available")
                if matched and (
                    item_available is True
                    or status in {"available", "completed", "ok", "healthy", "ready"}
                    or bool(item.get("count"))
                ):
                    return True
                if BobaCreativeDirectorV2Engine._nested_signal_available(item, needles):
                    return True
            elif matched and bool(item):
                return True
        return False

    @staticmethod
    def _explanations_by_candidate(
        explanation_set: Mapping[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for group in (
            "candidate_explanations",
            "ranking_explanations",
            "editorial_explanations",
        ):
            for value in _v2_list(explanation_set.get(group)):
                item = _v2_dict(value)
                candidate_id = _text(item.get("candidate_id"), maximum=128)
                if candidate_id:
                    result.setdefault(candidate_id, []).append(item)
        return result

    @staticmethod
    def _explanation_reason(explanations: Sequence[Mapping[str, Any]]) -> str:
        for item in explanations:
            reasons = _v2_unique(
                _v2_list(item.get("key_reasons")), limit=1, maximum=500
            )
            if reasons:
                return reasons[0]
        for item in explanations:
            summary = _text(item.get("short_summary"), maximum=500)
            if summary:
                return summary
        return ""

    @staticmethod
    def _emphasis_words(*values: Any) -> list[str]:
        stopwords = {
            "about",
            "after",
            "again",
            "because",
            "before",
            "could",
            "from",
            "have",
            "into",
            "should",
            "that",
            "their",
            "there",
            "these",
            "this",
            "those",
            "through",
            "what",
            "when",
            "where",
            "which",
            "with",
            "would",
            "your",
        }
        words: list[str] = []
        for value in values:
            for word in re.findall(r"[A-Za-z0-9']+", _text(value, maximum=500)):
                clean = word.strip("'")
                if len(clean) < 4 or clean.casefold() in stopwords:
                    continue
                words.append(clean)
        return _v2_unique(words, limit=8, maximum=40)

    @staticmethod
    def _matches(
        *values: Mapping[str, Any], needles: Sequence[str]
    ) -> bool:
        haystack = " ".join(
            _text(item, maximum=2_000).casefold()
            for value in values
            for item in value.values()
            if isinstance(item, str)
        )
        return any(needle in haystack for needle in needles)

    @staticmethod
    def _duration(window: Mapping[str, Any], candidate: Mapping[str, Any]) -> float:
        duration = _number(
            window.get("duration_seconds") or candidate.get("duration_seconds")
        )
        if duration <= 0.0:
            start = _number(window.get("start_seconds") or candidate.get("start_seconds"))
            end = _number(window.get("end_seconds") or candidate.get("end_seconds"))
            duration = max(0.0, end - start)
        return max(1.0, min(180.0, duration or 30.0))

    @staticmethod
    def _overlaps(
        item: Mapping[str, Any], window: Mapping[str, Any]
    ) -> bool:
        start = _number(window.get("start_seconds") or window.get("start"))
        end = _number(window.get("end_seconds") or window.get("end"), start)
        item_start = _number(item.get("start_seconds") or item.get("start"))
        item_end = _number(item.get("end_seconds") or item.get("end"), item_start)
        return end > start and item_end > item_start and min(end, item_end) > max(start, item_start)

    @staticmethod
    def _overlaps_window(
        item: Mapping[str, Any],
        decision: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> bool:
        window = _v2_dict(decision.get("source_window")) or candidate
        return BobaCreativeDirectorV2Engine._overlaps(item, window)

    @staticmethod
    def _mode(values: Sequence[str]) -> str:
        clean = [value for value in values if value]
        if not clean:
            return ""
        counts = {value: clean.count(value) for value in set(clean)}
        return min(counts, key=lambda value: (-counts[value], value))

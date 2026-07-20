"""Creative brief generation from existing Olympus and BOBA signals."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import Field

from olympus.boba.contracts import BobaContract
from olympus.boba.memory_contracts import BobaMemoryRecordV1

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
        for key in ("selected_plans", "planning_candidates"):
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
        start = _number(plan.get("start") or plan.get("source_start"))
        end = _number(plan.get("end") or plan.get("source_end"))
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

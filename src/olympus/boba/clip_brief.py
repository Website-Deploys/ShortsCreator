"""Compact editor-ready handoff briefs built from saved BOBA artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from olympus.boba.clip_ranking import BobaProductionPriority
from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.editorial_decision import BobaRenderReadiness
from olympus.platform.errors import ValidationError

BobaBriefInstructionType = Literal[
    "hook",
    "opening",
    "story",
    "cut",
    "caption",
    "motion",
    "audio",
    "sfx",
    "retention",
    "risk",
]
BobaBriefInstructionPriority = Literal["must_follow", "should_follow", "optional"]
BobaEditorChecklistCategory = Literal[
    "hook",
    "context",
    "payoff",
    "pacing",
    "captions",
    "motion",
    "audio",
    "rights",
    "render_safety",
    "human_review",
]
BobaEditorChecklistStatus = Literal["pending", "passed", "warning", "blocked"]


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _artifact(value: Mapping[str, Any] | BaseModel | None) -> dict[str, Any]:
    raw = _dict(value)
    return _dict(raw.get("data")) or raw


def _text(value: Any, *, maximum: int = 500) -> str:
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


def _unit(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _number(value, default)))


def _unique(values: Sequence[Any], *, limit: int, maximum: int = 500) -> list[str]:
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


def _source_range(*values: Mapping[str, Any]) -> tuple[float, float]:
    for value in values:
        if not value:
            continue
        start = _number(
            value.get("start_seconds")
            if value.get("start_seconds") is not None
            else value.get("start") or value.get("source_start")
        )
        end = _number(
            value.get("end_seconds")
            if value.get("end_seconds") is not None
            else value.get("end") or value.get("source_end"),
            start,
        )
        if start or end or any(
            key in value
            for key in ("start_seconds", "end_seconds", "start", "end")
        ):
            return max(0.0, start), max(0.0, end)
    return 0.0, 0.0


def _overlaps(value: Mapping[str, Any], start: float, end: float) -> bool:
    item_start, item_end = _source_range(value)
    return item_end > item_start and min(end, item_end) > max(start, item_start)


def _safe_music_mood(value: Any) -> tuple[str, bool]:
    mood = _text(value, maximum=80) or "none"
    unsafe = any(
        marker in mood.casefold()
        for marker in ("/", "\\", ":\\", ".mp3", ".wav", ".m4a", ".aac", ".flac")
    )
    return ("unspecified", True) if unsafe else (mood, False)


class BobaSourceWindowV1(BobaContract):
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(ge=0.0, le=180.0)


class BobaBriefInstructionV1(BobaContract):
    instruction_type: BobaBriefInstructionType
    summary: str = Field(min_length=1, max_length=700)
    do_this: str = Field(min_length=1, max_length=1000)
    avoid_this: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)
    priority: BobaBriefInstructionPriority


class BobaEditorChecklistItemV1(BobaContract):
    item_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=240)
    category: BobaEditorChecklistCategory
    required: bool
    status: BobaEditorChecklistStatus
    reason: str = Field(min_length=1, max_length=500)


class BobaClipBriefSignalUsageV1(BobaContract):
    creative_direction_v2_used: bool
    editorial_decision_used: bool
    explanation_used: bool
    clip_ranking_used: bool
    candidate_discovery_used: bool
    whole_video_understanding_used: bool
    memory_used: bool
    fallback_used: bool
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaClipBriefV1(BobaContract):
    brief_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    ranked_clip_id: str = Field(min_length=1, max_length=128)
    source_window: BobaSourceWindowV1
    production_priority: BobaProductionPriority
    render_readiness: BobaRenderReadiness
    brief_title: str = Field(min_length=1, max_length=180)
    final_clip_angle: str = Field(min_length=1, max_length=600)
    target_viewer_feeling: str = Field(min_length=1, max_length=300)
    hook_instruction: BobaBriefInstructionV1
    opening_three_second_instruction: BobaBriefInstructionV1
    story_instruction: BobaBriefInstructionV1
    cut_instruction: BobaBriefInstructionV1
    caption_instruction: BobaBriefInstructionV1
    motion_instruction: BobaBriefInstructionV1
    audio_instruction: BobaBriefInstructionV1
    sfx_instruction: BobaBriefInstructionV1
    retention_instruction: BobaBriefInstructionV1
    risk_fixes: list[str] = Field(default_factory=list, max_length=24)
    editor_checklist: list[BobaEditorChecklistItemV1] = Field(
        default_factory=list, max_length=20
    )
    human_review_notes: list[str] = Field(default_factory=list, max_length=24)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaClipBriefSetV1(BobaContract):
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    brief_version: Literal["boba_clip_brief_generator_v1"] = (
        "boba_clip_brief_generator_v1"
    )
    selected_briefs: list[BobaClipBriefV1] = Field(default_factory=list, max_length=10)
    backup_briefs: list[BobaClipBriefV1] = Field(default_factory=list, max_length=50)
    blocked_briefs: list[BobaClipBriefV1] = Field(default_factory=list, max_length=100)
    production_order: list[str] = Field(default_factory=list, max_length=10)
    project_summary: str = Field(min_length=1, max_length=1200)
    signal_usage: BobaClipBriefSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaClipBriefGeneratorV1:
    """Distill saved BOBA decisions into compact, non-executing editor packets."""

    def generate(
        self,
        *,
        project_id: str,
        creative_direction_v2: Mapping[str, Any] | BaseModel | None,
        editorial_decisions: Mapping[str, Any] | BaseModel | None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaClipBriefSetV1:
        creative = _artifact(creative_direction_v2)
        editorial = _artifact(editorial_decisions)
        if not creative:
            raise ValidationError(
                "BOBA Clip Brief Generator requires saved Creative Director V2 direction.",
                details={
                    "project_id": project_id,
                    "required_artifact": "creative_direction_v2",
                },
            )
        if not editorial:
            raise ValidationError(
                "BOBA Clip Brief Generator requires saved editorial decisions.",
                details={
                    "project_id": project_id,
                    "required_artifact": "editorial_decision",
                },
            )
        self._validate_project(project_id, creative, "creative_direction_v2")
        self._validate_project(project_id, editorial, "editorial_decision")

        ranking = _artifact(clip_ranking)
        discovery = _artifact(candidate_discovery)
        explanation_set = _artifact(explanations)
        understanding = _artifact(whole_video_understanding)
        memory_data = _artifact(memory)
        directions = self._by_id(creative.get("clip_directions"), "candidate_id")
        ranked = self._by_id(ranking.get("ranked_candidates"), "candidate_id")
        candidates = self._by_id(discovery.get("candidates"), "candidate_id")
        explanation_map = self._explanations_by_id(explanation_set)
        decisions = [
            item
            for value in _list(editorial.get("decisions"))
            if (item := _dict(value))
        ]
        decisions.sort(
            key=lambda item: (
                int(_number(item.get("rank"), 10_000)),
                _text(item.get("candidate_id"), maximum=128),
            )
        )
        ranking_backups = {
            _text(value, maximum=128)
            for value in _list(ranking.get("backup_clip_ids"))
            if _text(value, maximum=128)
        }
        selected_briefs: list[BobaClipBriefV1] = []
        backup_briefs: list[BobaClipBriefV1] = []
        blocked_briefs: list[BobaClipBriefV1] = []
        warnings = self._artifact_warnings(
            creative, editorial, ranking, discovery, explanation_set, understanding
        )
        used_ids: set[str] = set()
        fallback_brief_ids: list[str] = []

        for decision in decisions:
            candidate_id = _text(decision.get("candidate_id"), maximum=128)
            if not candidate_id or candidate_id in used_ids:
                continue
            used_ids.add(candidate_id)
            direction = directions.get(candidate_id, {})
            ranked_item = ranked.get(candidate_id, {})
            candidate = candidates.get(candidate_id, {})
            category, category_warning = self._category(
                decision,
                ranked_item,
                candidate,
                ranking_backups=ranking_backups,
            )
            if category_warning:
                warnings.append(category_warning)
            if not direction:
                fallback_brief_ids.append(candidate_id)
            brief = self._brief(
                project_id=project_id,
                category=category,
                decision=decision,
                direction=direction,
                ranked=ranked_item,
                candidate=candidate,
                explanations=explanation_map.get(candidate_id, []),
                understanding=understanding,
                memory=memory_data,
            )
            if category == "selected":
                selected_briefs.append(brief)
            elif category == "backup":
                backup_briefs.append(brief)
            else:
                blocked_briefs.append(brief)

        for rejected in _list(ranking.get("rejected_candidates")):
            rejected_item = _dict(rejected)
            candidate_id = _text(rejected_item.get("candidate_id"), maximum=128)
            if not candidate_id or candidate_id in used_ids:
                continue
            used_ids.add(candidate_id)
            candidate = candidates.get(candidate_id, {})
            reason = _text(
                rejected_item.get("reason") or "The ranking artifact rejected this candidate."
            )
            decision = self._blocked_decision(
                project_id,
                candidate_id,
                candidate=candidate,
                ranked=rejected_item,
                reason=reason,
            )
            fallback_brief_ids.append(candidate_id)
            blocked_briefs.append(
                self._brief(
                    project_id=project_id,
                    category="blocked",
                    decision=decision,
                    direction={},
                    ranked=rejected_item,
                    candidate=candidate,
                    explanations=explanation_map.get(candidate_id, []),
                    understanding=understanding,
                    memory=memory_data,
                )
            )

        selected_by_id = {item.candidate_id: item for item in selected_briefs}
        production_order = [
            candidate_id
            for value in _list(editorial.get("production_order"))
            if (candidate_id := _text(value, maximum=128)) in selected_by_id
        ]
        production_order.extend(
            item.candidate_id
            for item in selected_briefs
            if item.candidate_id not in production_order
        )
        selected_briefs.sort(
            key=lambda item: production_order.index(item.candidate_id)
            if item.candidate_id in production_order
            else len(production_order)
        )
        backup_briefs.sort(key=self._brief_sort_key)
        blocked_briefs.sort(key=self._brief_sort_key)

        unavailable: list[str] = []
        for available, name in (
            (bool(ranking), "clip_ranking"),
            (bool(discovery), "candidate_discovery"),
            (bool(explanation_set), "explanation"),
            (bool(understanding), "whole_video_understanding"),
            (self._memory_available(memory_data), "project_memory"),
        ):
            if not available:
                unavailable.append(name)
        if fallback_brief_ids:
            warnings.append(
                "Some briefs used Editorial Decision fallback because no matching "
                "Creative Director V2 clip direction was available: "
                + ", ".join(fallback_brief_ids[:10])
            )
        if not selected_briefs:
            warnings.append(
                "No selected editor-ready briefs were produced from the saved editorial state."
            )
        fallback_used = bool(unavailable or fallback_brief_ids)
        signal_usage = BobaClipBriefSignalUsageV1(
            creative_direction_v2_used=True,
            editorial_decision_used=True,
            explanation_used=bool(explanation_set),
            clip_ranking_used=bool(ranking),
            candidate_discovery_used=bool(discovery),
            whole_video_understanding_used=bool(understanding),
            memory_used=self._memory_available(memory_data),
            fallback_used=fallback_used,
            unavailable_signals=unavailable,
            warnings=_unique(
                [
                    *(
                        [
                            "Optional BOBA artifacts were unavailable; briefs retain "
                            "explicit fallback language."
                        ]
                        if unavailable
                        else []
                    ),
                    *(
                        [
                            "One or more per-clip V2 directions were unavailable; "
                            "Editorial Decision instructions were used without inventing evidence."
                        ]
                        if fallback_brief_ids
                        else []
                    ),
                ],
                limit=32,
            ),
        )
        return BobaClipBriefSetV1(
            project_id=project_id,
            source_id=_text(
                creative.get("source_id")
                or editorial.get("source_id")
                or ranking.get("source_id")
                or discovery.get("source_id")
                or understanding.get("source_id"),
                maximum=512,
            ),
            selected_briefs=selected_briefs[:10],
            backup_briefs=backup_briefs[:50],
            blocked_briefs=blocked_briefs[:100],
            production_order=production_order[:10],
            project_summary=self._project_summary(
                creative,
                editorial,
                understanding,
                selected_count=len(selected_briefs),
                backup_count=len(backup_briefs),
                blocked_count=len(blocked_briefs),
            ),
            signal_usage=signal_usage,
            warnings=_unique(warnings, limit=64, maximum=700),
            limitations=[
                "Clip Brief Generator V1 is advisory and does not alter Olympus editing "
                "timelines or trigger rendering.",
                "Music guidance describes mood only; it selects no song, file path, or "
                "copyright-cleared asset.",
                "Rights and copyright status require explicit human or existing gate review; "
                "this artifact does not claim safety.",
                "Brief confidence summarizes saved BOBA evidence and does not predict audience "
                "performance.",
                "A human editor must review source meaning, cuts, captions, audio, motion, and "
                "final output before production.",
            ],
        )

    def generate_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        creative_direction_v2: Mapping[str, Any] | BaseModel | None = None,
        editorial_decisions: Mapping[str, Any] | BaseModel | None = None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaClipBriefSetV1:
        return self.generate(
            project_id=project_id,
            creative_direction_v2=(
                creative_direction_v2 or _dict(signals.get("creative_direction_v2"))
            ),
            editorial_decisions=(
                editorial_decisions or _dict(signals.get("editorial_decisions"))
            ),
            clip_ranking=clip_ranking or _dict(signals.get("clip_ranking")),
            candidate_discovery=(
                candidate_discovery or _dict(signals.get("candidate_clip_discovery"))
            ),
            explanations=explanations or _dict(signals.get("explanations")),
            whole_video_understanding=(
                whole_video_understanding
                or _dict(signals.get("whole_video_understanding"))
            ),
            memory=memory,
        )

    def _brief(
        self,
        *,
        project_id: str,
        category: Literal["selected", "backup", "blocked"],
        decision: Mapping[str, Any],
        direction: Mapping[str, Any],
        ranked: Mapping[str, Any],
        candidate: Mapping[str, Any],
        explanations: Sequence[Mapping[str, Any]],
        understanding: Mapping[str, Any],
        memory: Mapping[str, Any],
    ) -> BobaClipBriefV1:
        candidate_id = _text(
            decision.get("candidate_id")
            or direction.get("candidate_id")
            or ranked.get("candidate_id")
            or candidate.get("candidate_id"),
            maximum=128,
        ) or "candidate"
        ranked_clip_id = _text(
            decision.get("ranked_clip_id")
            or direction.get("ranked_clip_id")
            or candidate_id,
            maximum=128,
        )
        decision_window = _dict(decision.get("source_window"))
        ranked_window = _dict(ranked.get("source_window"))
        start, end = _source_range(decision_window, ranked_window, candidate)
        duration = round(max(0.0, end - start), 3)
        risk = _dict(decision.get("risk_review"))
        packet = _dict(decision.get("editing_instruction_packet"))
        hook = _dict(direction.get("hook_treatment"))
        opening = _dict(direction.get("opening_three_second_plan"))
        pacing = _dict(direction.get("pacing_map"))
        caption = _dict(direction.get("caption_direction"))
        motion = _dict(direction.get("motion_direction"))
        audio = _dict(direction.get("audio_direction"))
        retention = _dict(direction.get("retention_plan"))
        emotion = _dict(direction.get("emotional_arc"))
        project_direction = _dict(understanding.get("project_direction"))
        explanation_summary = self._explanation_summary(explanations)
        context_links = [
            _dict(value)
            for value in _list(understanding.get("context_payoff_map"))
            if _overlaps(_dict(value), start, end)
        ]
        context_reason = _text(
            _dict(context_links[0]).get("description") if context_links else "",
            maximum=400,
        )
        title = _text(
            decision.get("suggested_title")
            or ranked.get("suggested_title")
            or candidate.get("suggested_title")
            or f"Clip {candidate_id}",
            maximum=180,
        )
        angle = _text(
            direction.get("final_clip_angle")
            or decision.get("final_story_angle")
            or ranked.get("story_angle")
            or candidate.get("story_angle")
            or "Present one self-contained idea and preserve its payoff.",
            maximum=600,
        )
        target_feeling = _text(
            emotion.get("intended_viewer_feeling")
            or project_direction.get("target_viewer_feeling")
            or candidate.get("emotion_label")
            or ranked.get("emotion_label")
            or "Clear on the value and satisfied by the payoff.",
            maximum=300,
        )
        priority = self._priority(decision.get("production_priority"), category)
        readiness = self._readiness(decision.get("render_readiness"), category)
        instruction_priority: BobaBriefInstructionPriority = (
            "must_follow" if category in {"selected", "blocked"} else "should_follow"
        )
        hook_score = _number(_dict(ranked.get("score_breakdown")).get("hook_score"))
        hook_reason = _unique(
            [
                hook.get("reason_it_should_work"),
                explanation_summary,
                f"Saved ranking hook score: {hook_score:.1f}/100."
                if hook_score
                else "",
            ],
            limit=3,
            maximum=500,
        )
        hook_instruction = self._instruction(
            "hook",
            _text(
                hook.get("opening_line_direction")
                or packet.get("hook_instruction")
                or decision.get("opening_line_direction")
                or candidate.get("hook_idea")
                or "State the clip value immediately.",
                maximum=700,
            ),
            _unique(
                [
                    hook.get("opening_line_direction"),
                    hook.get("first_visual_emphasis"),
                    hook.get("curiosity_trigger"),
                    hook.get("pattern_interrupt"),
                ],
                limit=4,
            ),
            _unique(
                [
                    hook.get("hook_risk"),
                    "Do not open with dead air, a generic greeting, or an unsupported claim.",
                ],
                limit=3,
            ),
            hook_reason or ["This follows the saved BOBA editorial hook strategy."],
            instruction_priority,
        )
        opening_instruction = self._instruction(
            "opening",
            _text(
                opening.get("what_viewer_sees_first")
                or decision.get("opening_line_direction")
                or "Open directly on the strongest meaningful visual and spoken idea.",
                maximum=700,
            ),
            _unique(
                [
                    opening.get("what_viewer_sees_first"),
                    opening.get("caption_implication"),
                    opening.get("curiosity_gap"),
                    opening.get("motion_choice"),
                    pacing.get("first_3_seconds"),
                ],
                limit=5,
            ),
            _unique(
                [
                    *_list(opening.get("avoid")),
                    "Do not spend the first three seconds on setup that can follow the hook.",
                ],
                limit=5,
            ),
            [
                _text(
                    hook.get("reason_it_should_work")
                    or "The opening should establish value and curiosity before supporting context."
                )
            ],
            instruction_priority,
        )
        story_instruction = self._instruction(
            "story",
            angle,
            _unique(
                [
                    direction.get("story_framing"),
                    "Give the viewer only the context needed to understand the claim.",
                    "Preserve the setup-to-payoff relationship and the final lesson.",
                    context_reason,
                ],
                limit=4,
            ),
            [
                "Do not remove setup that changes meaning, and do not end before "
                "the promised payoff."
            ],
            _unique(
                [
                    explanation_summary,
                    candidate.get("discovery_reason"),
                    context_reason,
                ],
                limit=3,
            )
            or ["This angle follows the saved editorial decision."],
            instruction_priority,
        )
        cut_instruction = self._instruction(
            "cut",
            f"Use the advisory source window {start:.2f}s to {end:.2f}s ({duration:.2f}s).",
            _unique(
                [
                    packet.get("cut_instruction"),
                    "Trim only verified filler or dead air while preserving context and payoff.",
                    "Hold the ending long enough for the final word and payoff to land.",
                ],
                limit=3,
            ),
            [
                "Do not make an abrupt start, cut a sentence mid-thought, or shorten "
                "the clip before its payoff."
            ],
            [
                _text(
                    _dict(candidate.get("boundary_suggestion")).get("reason")
                    or "The window comes from the saved editorial and ranking artifacts."
                )
            ],
            instruction_priority,
        )
        caption_style = _text(
            caption.get("style") or decision.get("caption_style") or "clean_subtitles",
            maximum=80,
        )
        caption_instruction = self._instruction(
            "caption",
            f"Use {caption_style.replace('_', ' ')} captions with speech-first readability.",
            _unique(
                [
                    packet.get("caption_instruction"),
                    "Emphasize: "
                    + ", ".join(
                        _unique(
                            _list(caption.get("emphasis_words")),
                            limit=12,
                            maximum=40,
                        )
                    )
                    + "."
                    if _list(caption.get("emphasis_words"))
                    else "Emphasize only verified hook and payoff words.",
                    caption.get("rhythm"),
                    *_list(caption.get("readability_notes")),
                ],
                limit=5,
            ),
            _unique(
                [
                    *_list(caption.get("warnings")),
                    "Do not obscure faces, overload the frame, or paraphrase spoken "
                    "meaning inaccurately.",
                ],
                limit=4,
            ),
            ["Captions should strengthen comprehension without becoming the edit itself."],
            instruction_priority,
        )
        motion_style = _text(
            motion.get("style") or decision.get("motion_style") or "stable",
            maximum=80,
        )
        motion_instruction = self._instruction(
            "motion",
            f"Use {motion_style.replace('_', ' ')} motion while keeping framing "
            "stable and readable.",
            _unique(
                [
                    packet.get("motion_instruction"),
                    *[f"Zoom: {item}" for item in _list(motion.get("zoom_moments"))],
                    *[
                        f"Punch-in: {item}"
                        for item in _list(motion.get("punch_in_moments"))
                    ],
                    *[
                        f"Hold stable: {item}"
                        for item in _list(motion.get("stable_moments"))
                    ],
                    *[
                        f"Layout-safe: {item}"
                        for item in _list(motion.get("layout_safe_moments"))
                    ],
                ],
                limit=7,
            ),
            _unique(
                [
                    *_list(motion.get("safety_warnings")),
                    "Do not use unverified face tracking, unstable reframing, or "
                    "rapid zooms that harm comprehension.",
                ],
                limit=6,
            ),
            [
                "Motion must support the hook and story while respecting available "
                "face and layout evidence."
            ],
            instruction_priority,
        )
        music_mood, unsafe_music_value = _safe_music_mood(
            audio.get("music_mood") or decision.get("music_mood") or "none"
        )
        music_summary = (
            "Use no background music unless a permitted asset and clear editorial "
            "reason are confirmed."
            if music_mood == "none"
            else (
                f"Use {'an' if music_mood[:1].casefold() in 'aeiou' else 'a'} "
                f"{music_mood.replace('_', ' ')} music mood only if a permitted asset "
                "is available."
            )
        )
        audio_instruction = self._instruction(
            "audio",
            music_summary,
            _unique(
                [
                    audio.get("ducking_guidance"),
                    audio.get("speech_clarity_notes"),
                    audio.get("silence_notes"),
                    "Keep speech clearly dominant and review every transition by ear.",
                ],
                limit=4,
            ),
            _unique(
                [
                    *_list(audio.get("warnings")),
                    "Do not select a song or asset path in this brief, mask unclear "
                    "speech, or let music overpower dialogue.",
                ],
                limit=5,
            ),
            [
                "Audio direction is mood metadata only and does not establish asset "
                "rights or final loudness."
            ],
            instruction_priority,
        )
        sfx_intensity = _text(
            audio.get("sfx_intensity") or decision.get("sfx_intensity") or "none",
            maximum=80,
        )
        sfx_instruction = self._instruction(
            "sfx",
            f"Use {sfx_intensity.replace('_', ' ')} clean SFX only where they clarify "
            "a hook, turn, or payoff.",
            [
                "Use sparse, subtle, non-noise-like accents and audition them against "
                "speech before approval."
            ],
            [
                "Do not add static, hiss, harsh noise, repetitive hits, or any effect "
                "that competes with important words."
            ],
            ["SFX are optional support; intelligible speech and story timing take priority."],
            "should_follow" if category != "blocked" else "must_follow",
        )
        retention_instruction = self._instruction(
            "retention",
            _text(
                retention.get("opening_hook")
                or packet.get("retention_instruction")
                or "Open the loop immediately and resolve it with the preserved payoff.",
                maximum=700,
            ),
            _unique(
                [
                    f"Open loop: {_text(retention.get('curiosity_loop'))}"
                    if retention.get("curiosity_loop")
                    else "Open loop: establish one honest question the payoff will answer.",
                    f"Mid-clip hold: {_text(retention.get('mid_clip_hold'))}"
                    if retention.get("mid_clip_hold")
                    else "",
                    f"Payoff delivery: {_text(retention.get('payoff_delivery'))}"
                    if retention.get("payoff_delivery")
                    else "Payoff delivery: resolve the opening promise before the cut.",
                    f"Replay trigger: {_text(retention.get('replay_trigger'))}"
                    if retention.get("replay_trigger")
                    else "",
                ],
                limit=4,
            ),
            _unique(
                [
                    *_list(retention.get("retention_risks")),
                    "Do not delay the payoff artificially or use a misleading open loop.",
                ],
                limit=5,
            ),
            ["Retention treatment must preserve meaning rather than manufacture a false promise."],
            instruction_priority,
        )
        risk_fixes = self._risk_fixes(risk, candidate)
        warnings = _unique(
            [
                *(_list(direction.get("warnings"))),
                *(_list(decision.get("improvement_notes"))),
                *(_list(candidate.get("warnings"))),
                *(self._explanation_warnings(explanations)),
                *(
                    [
                        "Creative Director V2 supplied no matching per-clip direction; "
                        "this brief uses explicit Editorial Decision fallback guidance."
                    ]
                    if not direction
                    else []
                ),
                *(
                    [
                        "An upstream music value resembled an asset path and was replaced "
                        "with an unspecified mood."
                    ]
                    if unsafe_music_value
                    else []
                ),
                *(
                    ["The source window is invalid and must be repaired before rendering."]
                    if duration <= 0.0
                    else []
                ),
            ],
            limit=32,
        )
        notes = _unique(
            [
                *(_list(direction.get("editor_notes"))),
                *(_list(decision.get("improvement_notes"))),
                *(_list(_dict(understanding.get("signal_usage")).get("warnings"))),
                *(_list(memory.get("known_limitations"))),
                *self._project_human_checks(explanations),
                "Review the complete source around the advisory window before accepting the cut.",
            ],
            limit=24,
        )
        confidence_values = [
            _unit(direction.get("confidence"), -1.0),
            _unit(decision.get("confidence"), -1.0),
            _unit(ranked.get("confidence"), -1.0),
            *[
                _unit(value.get("confidence"), -1.0)
                for value in explanations
                if _dict(value)
            ],
        ]
        confidence_values = [value for value in confidence_values if value >= 0.0]
        confidence = (
            sum(confidence_values) / len(confidence_values)
            if confidence_values
            else 0.5
        )
        if not direction:
            confidence = max(0.0, confidence - 0.1)
        return BobaClipBriefV1(
            brief_id=f"brief_{candidate_id}"[:160],
            project_id=project_id,
            candidate_id=candidate_id,
            ranked_clip_id=ranked_clip_id,
            source_window=BobaSourceWindowV1(
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
                duration_seconds=duration,
            ),
            production_priority=priority,
            render_readiness=readiness,
            brief_title=title,
            final_clip_angle=angle,
            target_viewer_feeling=target_feeling,
            hook_instruction=hook_instruction,
            opening_three_second_instruction=opening_instruction,
            story_instruction=story_instruction,
            cut_instruction=cut_instruction,
            caption_instruction=caption_instruction,
            motion_instruction=motion_instruction,
            audio_instruction=audio_instruction,
            sfx_instruction=sfx_instruction,
            retention_instruction=retention_instruction,
            risk_fixes=risk_fixes,
            editor_checklist=self._checklist(
                candidate_id=candidate_id,
                category=category,
                readiness=readiness,
                risk=risk,
            ),
            human_review_notes=notes,
            confidence=round(_unit(confidence), 3),
            warnings=warnings,
            limitations=[
                "This packet is advisory and has not been applied to an edit or render.",
                "Music and SFX text describes treatment only; no asset is selected or cleared.",
                "A human must verify source context, rights, timing, framing, and final playback.",
            ],
        )

    @staticmethod
    def _instruction(
        instruction_type: BobaBriefInstructionType,
        summary: str,
        do_values: Sequence[Any],
        avoid_values: Sequence[Any],
        reason_values: Sequence[Any],
        priority: BobaBriefInstructionPriority,
    ) -> BobaBriefInstructionV1:
        do_this = "; ".join(_unique(do_values, limit=8, maximum=500)) or (
            "Follow the saved editorial direction without inventing unsupported treatment."
        )
        avoid_this = "; ".join(_unique(avoid_values, limit=8, maximum=500)) or (
            "Avoid choices that change meaning, hide risk, or reduce clarity."
        )
        reason = "; ".join(_unique(reason_values, limit=6, maximum=500)) or (
            "This instruction reflects the available saved BOBA evidence."
        )
        return BobaBriefInstructionV1(
            instruction_type=instruction_type,
            summary=_text(summary, maximum=700)
            or "Follow the saved BOBA editorial direction.",
            do_this=do_this[:1000],
            avoid_this=avoid_this[:1000],
            reason=reason[:1000],
            priority=priority,
        )

    @staticmethod
    def _category(
        decision: Mapping[str, Any],
        ranked: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        ranking_backups: set[str],
    ) -> tuple[Literal["selected", "backup", "blocked"], str]:
        candidate_id = _text(decision.get("candidate_id"), maximum=128)
        readiness = _text(decision.get("render_readiness"), maximum=80)
        priority = _text(decision.get("production_priority"), maximum=80)
        risk = _dict(decision.get("risk_review"))
        start, end = _source_range(
            _dict(decision.get("source_window")),
            _dict(ranked.get("source_window")),
            candidate,
        )
        invalid_window = end <= start
        rights_blocked = bool(risk.get("rights_risk")) and bool(
            _list(risk.get("blockers"))
        )
        duplicate_only = bool(risk.get("duplicate_risk")) and (
            _text(ranked.get("tier"), maximum=80) == "reject"
            or priority == "do_not_produce"
        )
        if (
            readiness == "blocked"
            or priority == "do_not_produce"
            or invalid_window
            or rights_blocked
            or duplicate_only
        ):
            warning = (
                f"Candidate {candidate_id} was blocked because its source window is invalid."
                if invalid_window
                else ""
            )
            return "blocked", warning
        if bool(decision.get("selected")) and readiness in {
            "ready_for_render",
            "needs_revision",
        }:
            return "selected", ""
        if (
            candidate_id in ranking_backups
            or _text(ranked.get("tier"), maximum=80)
            in {"backup_candidate", "needs_revision"}
            or priority in {"medium", "low"}
            or readiness == "needs_revision"
        ):
            return "backup", ""
        return "backup", ""

    @staticmethod
    def _blocked_decision(
        project_id: str,
        candidate_id: str,
        *,
        candidate: Mapping[str, Any],
        ranked: Mapping[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        start, end = _source_range(_dict(ranked.get("source_window")), candidate)
        return {
            "project_id": project_id,
            "candidate_id": candidate_id,
            "ranked_clip_id": candidate_id,
            "rank": int(_number(ranked.get("rank"), 10_000)),
            "source_window": {
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": max(0.0, end - start),
            },
            "production_priority": "do_not_produce",
            "render_readiness": "blocked",
            "suggested_title": candidate.get("suggested_title")
            or f"Blocked {candidate_id}",
            "final_story_angle": candidate.get("story_angle")
            or "Resolve the rejection before developing this clip.",
            "risk_review": {
                "weak_hook": True,
                "missing_context": bool(candidate.get("context_needed")),
                "weak_payoff": not bool(candidate.get("payoff_present")),
                "filler_risk": False,
                "duplicate_risk": "duplicate" in reason.casefold()
                or "overlap" in reason.casefold(),
                "rights_risk": "rights" in reason.casefold(),
                "audio_risk": False,
                "visual_layout_risk": False,
                "unavailable_signal_risk": False,
                "blockers": [reason],
                "warnings": [],
            },
            "improvement_notes": [reason],
            "confidence": _unit(ranked.get("confidence"), 0.8),
        }

    @staticmethod
    def _risk_fixes(
        risk: Mapping[str, Any], candidate: Mapping[str, Any]
    ) -> list[str]:
        missing_context = bool(risk.get("missing_context") or candidate.get("context_needed"))
        weak_payoff = bool(risk.get("weak_payoff") or not candidate.get("payoff_present", True))
        weak_hook = bool(risk.get("weak_hook"))
        filler = bool(risk.get("filler_risk"))
        return _unique(
            [
                (
                    "Context fix: add the minimum verified setup needed before the claim."
                    if missing_context
                    else "Context check: verify the clip remains understandable "
                    "without hidden setup."
                ),
                (
                    "Payoff fix: extend or revise the ending until the promised payoff is complete."
                    if weak_payoff
                    else "Payoff check: preserve the complete final lesson or emotional resolution."
                ),
                (
                    "Hook fix: replace the weak opening with the saved direct-value "
                    "or curiosity treatment."
                    if weak_hook
                    else "Hook check: confirm the first meaningful words state value "
                    "or curiosity clearly."
                ),
                (
                    "Filler fix: remove only verified repetition, dead air, or low-value setup."
                    if filler
                    else "Filler check: remove dead air only when meaning and pacing remain intact."
                ),
                "Rights review: confirm permission for the source and every external "
                "music, SFX, or visual asset.",
                "Audio review: listen for speech clarity, synchronization, silence, "
                "and overpowering music or SFX.",
                "Motion safety review: verify face/layout evidence, stable framing, "
                "readable captions, and comfortable movement.",
            ],
            limit=24,
            maximum=600,
        )

    @staticmethod
    def _checklist(
        *,
        candidate_id: str,
        category: Literal["selected", "backup", "blocked"],
        readiness: BobaRenderReadiness,
        risk: Mapping[str, Any],
    ) -> list[BobaEditorChecklistItemV1]:
        def item(
            suffix: str,
            label: str,
            checklist_category: BobaEditorChecklistCategory,
            reason: str,
            *,
            warning: bool = False,
            blocked: bool = False,
        ) -> BobaEditorChecklistItemV1:
            status: BobaEditorChecklistStatus = "pending"
            if blocked:
                status = "blocked"
            elif warning:
                status = "warning"
            return BobaEditorChecklistItemV1(
                item_id=f"{candidate_id}_{suffix}"[:128],
                label=label,
                category=checklist_category,
                required=True,
                status=status,
                reason=reason,
            )

        blocked_clip = category == "blocked" or readiness == "blocked"
        return [
            item(
                "hook",
                "Hook is clear in the first meaningful words",
                "hook",
                "Confirm the opening communicates value or curiosity without misleading "
                "the viewer.",
                warning=bool(risk.get("weak_hook")),
                blocked=blocked_clip and bool(risk.get("weak_hook")),
            ),
            item(
                "context",
                "Context is sufficient",
                "context",
                "Watch the source around the window and confirm the claim is understandable.",
                warning=bool(risk.get("missing_context")),
                blocked=blocked_clip and bool(risk.get("missing_context")),
            ),
            item(
                "payoff",
                "Payoff is preserved",
                "payoff",
                "Confirm the ending completes the promised idea and is not cut abruptly.",
                warning=bool(risk.get("weak_payoff")),
                blocked=blocked_clip and bool(risk.get("weak_payoff")),
            ),
            item(
                "pacing",
                "Pacing preserves meaning",
                "pacing",
                "Review filler cuts and holds without changing speech meaning or emotional timing.",
                warning=bool(risk.get("filler_risk")),
            ),
            item(
                "captions",
                "Captions are accurate and readable",
                "captions",
                "Check transcription fidelity, line length, placement, and emphasis.",
            ),
            item(
                "motion",
                "Motion and framing are safe",
                "motion",
                "Check faces, layout, crop stability, caption clearance, and motion comfort.",
                warning=bool(risk.get("visual_layout_risk")),
            ),
            item(
                "audio",
                "Speech is clear and dominant",
                "audio",
                "Listen for synchronization, clipping, silence, and music/SFX balance.",
                warning=bool(risk.get("audio_risk")),
            ),
            item(
                "rights",
                "Source and external asset rights are confirmed",
                "rights",
                "Do not proceed on an external source or asset without the required "
                "rights confirmation.",
                warning=bool(risk.get("rights_risk")),
                blocked=bool(risk.get("rights_risk")) and blocked_clip,
            ),
            item(
                "render_safety",
                "Render readiness and source window are reviewed",
                "render_safety",
                "The brief is advisory; verify the editing timeline and render gates separately.",
                warning=readiness == "needs_revision",
                blocked=readiness == "blocked",
            ),
            item(
                "human_review",
                "A human reviews the completed output",
                "human_review",
                "Final editorial quality, meaning, rights, and playback require human judgment.",
                blocked=blocked_clip,
            ),
        ]

    @staticmethod
    def _project_summary(
        creative: Mapping[str, Any],
        editorial: Mapping[str, Any],
        understanding: Mapping[str, Any],
        *,
        selected_count: int,
        backup_count: int,
        blocked_count: int,
    ) -> str:
        project_direction = _dict(creative.get("project_direction"))
        parts = _unique(
            [
                editorial.get("summary"),
                project_direction.get("overall_style"),
                project_direction.get("target_viewer_feeling"),
                f"Primary topic: {_text(understanding.get('primary_topic'), maximum=160)}."
                if understanding.get("primary_topic")
                else "",
                (
                    f"Packet contains {selected_count} selected, {backup_count} backup, "
                    f"and {blocked_count} blocked brief(s)."
                ),
            ],
            limit=5,
            maximum=700,
        )
        return " ".join(parts)[:1200] or "BOBA produced an advisory editor packet."

    @staticmethod
    def _by_id(values: Any, field: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for value in _list(values):
            item = _dict(value)
            item_id = _text(item.get(field), maximum=128)
            if item_id and item_id not in result:
                result[item_id] = item
        return result

    @staticmethod
    def _explanations_by_id(
        explanations: Mapping[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for key in (
            "editorial_explanations",
            "ranking_explanations",
            "candidate_explanations",
        ):
            for value in _list(explanations.get(key)):
                item = _dict(value)
                candidate_id = _text(
                    item.get("candidate_id") or item.get("clip_id"), maximum=128
                )
                if candidate_id:
                    result.setdefault(candidate_id, []).append(item)
        return result

    @staticmethod
    def _explanation_summary(values: Sequence[Mapping[str, Any]]) -> str:
        parts = _unique(
            [
                value.get("short_summary") or value.get("detailed_explanation")
                for value in values
            ],
            limit=2,
            maximum=400,
        )
        return "; ".join(parts)[:700]

    @staticmethod
    def _explanation_warnings(values: Sequence[Mapping[str, Any]]) -> list[str]:
        return _unique(
            [
                item
                for value in values
                for item in [*_list(value.get("warnings")), *_list(value.get("limitations"))]
            ],
            limit=12,
            maximum=500,
        )

    @staticmethod
    def _project_human_checks(values: Sequence[Mapping[str, Any]]) -> list[str]:
        return _unique(
            [
                item
                for value in values
                for item in _list(value.get("human_review_notes"))
            ],
            limit=8,
        )

    @staticmethod
    def _artifact_warnings(*artifacts: Mapping[str, Any]) -> list[str]:
        return _unique(
            [
                item
                for artifact in artifacts
                for item in [*_list(artifact.get("warnings")), *_list(artifact.get("limitations"))]
            ],
            limit=64,
            maximum=700,
        )

    @staticmethod
    def _memory_available(memory: Mapping[str, Any]) -> bool:
        return bool(
            _text(memory.get("source_summary"))
            or _list(memory.get("main_topics"))
            or _list(memory.get("known_limitations"))
        )

    @staticmethod
    def _priority(
        value: Any, category: Literal["selected", "backup", "blocked"]
    ) -> BobaProductionPriority:
        priority = _text(value, maximum=80)
        if category == "blocked":
            return "do_not_produce"
        if priority in {"immediate", "high", "medium", "low"}:
            return priority  # type: ignore[return-value]
        return "high" if category == "selected" else "medium"

    @staticmethod
    def _readiness(
        value: Any, category: Literal["selected", "backup", "blocked"]
    ) -> BobaRenderReadiness:
        readiness = _text(value, maximum=80)
        if category == "blocked":
            return "blocked"
        if readiness in {"ready_for_render", "needs_revision"}:
            return readiness  # type: ignore[return-value]
        return "needs_revision"

    @staticmethod
    def _brief_sort_key(brief: BobaClipBriefV1) -> tuple[int, str]:
        priority = {
            "immediate": 0,
            "high": 1,
            "medium": 2,
            "low": 3,
            "do_not_produce": 4,
        }
        return priority[brief.production_priority], brief.candidate_id

    @staticmethod
    def _validate_project(
        project_id: str, artifact: Mapping[str, Any], artifact_name: str
    ) -> None:
        artifact_project_id = _text(artifact.get("project_id"), maximum=128)
        if artifact_project_id and artifact_project_id != project_id:
            raise ValidationError(
                f"BOBA {artifact_name} belongs to a different project.",
                details={
                    "project_id": project_id,
                    "artifact_project_id": artifact_project_id,
                },
            )

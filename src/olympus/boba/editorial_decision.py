"""Deterministic advisory editorial decisions over BOBA-ranked clip candidates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from olympus.boba.clip_discovery import (
    BobaCandidateClipDiscoveryV1,
    BobaCandidateClipV1,
)
from olympus.boba.clip_ranking import (
    BobaClipRankingV1,
    BobaProductionPriority,
    BobaRankedClipV1,
    BobaRankingTier,
)
from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.creative_director import BobaCreativeBriefV1
from olympus.boba.memory_contracts import BobaProjectMemoryV1
from olympus.boba.whole_video import BobaWholeVideoUnderstandingV1
from olympus.platform.errors import ValidationError

BobaRenderReadiness = Literal["ready_for_render", "needs_revision", "blocked"]
BobaPacingIntensity = Literal["calm", "moderate", "fast", "aggressive"]
BobaCaptionStyle = Literal[
    "clean_subtitles",
    "bold_hook_captions",
    "emotional_emphasis",
    "keyword_highlight",
    "minimal",
    "none",
]
BobaMotionStyle = Literal[
    "stable",
    "subtle_zoom",
    "dynamic_zoom",
    "punch_in",
    "high_motion",
    "layout_safe",
]
BobaMusicMood = Literal[
    "none",
    "motivational",
    "emotional",
    "suspense",
    "energetic",
    "calm",
    "funny",
    "cinematic",
    "educational",
]
BobaSfxIntensity = Literal["none", "light", "moderate", "heavy"]
BobaHookStrategy = Literal[
    "curiosity_gap",
    "emotional_reveal",
    "problem_solution",
    "contradiction",
    "shocking_truth",
    "motivational_payoff",
    "story_turn",
    "educational_open_loop",
    "direct_value",
]


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: Any, *, maximum: int = 400) -> str:
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


def _artifact(value: Mapping[str, Any] | BaseModel | None) -> dict[str, Any]:
    raw = _dict(value)
    data = _dict(raw.get("data"))
    return data or raw


def _unique(values: Sequence[str], *, limit: int, maximum: int = 400) -> list[str]:
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


def _range(value: Mapping[str, Any]) -> tuple[float, float]:
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
    return max(0.0, start), max(0.0, end)


def _overlaps(value: Mapping[str, Any], start: float, end: float) -> bool:
    item_start, item_end = _range(value)
    return item_end > item_start and min(end, item_end) > max(start, item_start)


class BobaEditingInstructionPacketV1(BobaContract):
    hook_instruction: str = Field(min_length=1, max_length=500)
    cut_instruction: str = Field(min_length=1, max_length=500)
    caption_instruction: str = Field(min_length=1, max_length=500)
    motion_instruction: str = Field(min_length=1, max_length=500)
    audio_instruction: str = Field(min_length=1, max_length=500)
    pacing_instruction: str = Field(min_length=1, max_length=500)
    retention_instruction: str = Field(min_length=1, max_length=500)
    risk_instruction: str = Field(min_length=1, max_length=700)


class BobaEditorialRiskReviewV1(BobaContract):
    weak_hook: bool
    missing_context: bool
    weak_payoff: bool
    filler_risk: bool
    duplicate_risk: bool
    rights_risk: bool
    audio_risk: bool
    visual_layout_risk: bool
    unavailable_signal_risk: bool
    blockers: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaEditorialRiskSummaryV1(BobaContract):
    selected_count: int = Field(default=0, ge=0, le=10)
    ready_for_render_count: int = Field(default=0, ge=0)
    needs_revision_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    top_risks: list[str] = Field(default_factory=list, max_length=16)
    blockers: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaEditorialSignalUsageV1(BobaContract):
    clip_ranking_used: bool
    candidate_discovery_used: bool
    whole_video_understanding_used: bool
    creative_briefs_used: bool
    analysis_signals_used: bool
    story_used: bool
    virality_used: bool
    planning_used: bool
    memory_used: bool
    fallback_used: bool
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaEditorialDecisionV1(BobaContract):
    candidate_id: str = Field(min_length=1, max_length=128)
    ranked_clip_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    rank: int = Field(ge=1)
    ranking_score: float = Field(ge=0.0, le=100.0)
    ranking_tier: BobaRankingTier
    suggested_title: str = Field(min_length=1, max_length=160)
    candidate_type: str = Field(min_length=1, max_length=80)
    source_window: dict[str, float]
    selected: bool
    render_readiness: BobaRenderReadiness
    render_readiness_reason: str = Field(min_length=1, max_length=500)
    production_priority: BobaProductionPriority
    final_story_angle: str = Field(min_length=1, max_length=400)
    final_hook_strategy: BobaHookStrategy
    opening_line_direction: str = Field(min_length=1, max_length=500)
    pacing_intensity: BobaPacingIntensity
    caption_style: BobaCaptionStyle
    motion_style: BobaMotionStyle
    music_mood: BobaMusicMood
    sfx_intensity: BobaSfxIntensity
    visual_emphasis: list[str] = Field(default_factory=list, max_length=16)
    retention_tactics: list[str] = Field(default_factory=list, max_length=20)
    editing_instruction_packet: BobaEditingInstructionPacketV1
    risk_review: BobaEditorialRiskReviewV1
    decision_reasons: list[str] = Field(default_factory=list, max_length=24)
    improvement_notes: list[str] = Field(default_factory=list, max_length=24)
    confidence: float = Field(ge=0.0, le=1.0)


class BobaEditorialDecisionSetV1(BobaContract):
    schema_version: Literal["boba_editorial_decision_engine_v1"] = (
        "boba_editorial_decision_engine_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    summary: str = Field(min_length=1, max_length=1000)
    selected_clip_ids: list[str] = Field(default_factory=list, max_length=10)
    rejected_clip_ids: list[str] = Field(default_factory=list, max_length=100)
    production_order: list[str] = Field(default_factory=list, max_length=10)
    decisions: list[BobaEditorialDecisionV1] = Field(default_factory=list, max_length=100)
    risk_summary: BobaEditorialRiskSummaryV1
    signal_usage: BobaEditorialSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaEditorialDecisionEngine:
    """Convert BOBA rankings into compact, non-executing editorial instructions."""

    def __init__(
        self,
        *,
        maximum_selected: int = 10,
        minimum_selection_target: int = 3,
    ) -> None:
        if not 3 <= maximum_selected <= 10:
            raise ValueError("maximum_selected must be between 3 and 10")
        if not 1 <= minimum_selection_target <= maximum_selected:
            raise ValueError("minimum target must not exceed maximum_selected")
        self.maximum_selected = maximum_selected
        self.minimum_selection_target = minimum_selection_target

    def decide(
        self,
        *,
        project_id: str,
        clip_ranking: BobaClipRankingV1 | Mapping[str, Any] | None,
        candidate_discovery: (
            BobaCandidateClipDiscoveryV1 | Mapping[str, Any] | None
        ) = None,
        whole_video_understanding: (
            BobaWholeVideoUnderstandingV1 | Mapping[str, Any] | None
        ) = None,
        creative_briefs: Sequence[BobaCreativeBriefV1 | Mapping[str, Any]] | None = None,
        analysis_artifact: Mapping[str, Any] | None = None,
        story_artifact: Mapping[str, Any] | None = None,
        virality_artifact: Mapping[str, Any] | None = None,
        planning_artifact: Mapping[str, Any] | None = None,
        editing_artifact: Mapping[str, Any] | None = None,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
        source_context: Mapping[str, Any] | None = None,
    ) -> BobaEditorialDecisionSetV1:
        ranking = self._ranking(clip_ranking, project_id)
        discovery = self._discovery(candidate_discovery, project_id)
        understanding = _artifact(whole_video_understanding)
        briefs = self._briefs(creative_briefs, project_id)
        analysis = _artifact(analysis_artifact)
        story = _artifact(story_artifact)
        virality = _artifact(virality_artifact)
        planning = _artifact(planning_artifact)
        editing = _artifact(editing_artifact)
        memory_data = _dict(memory)
        source = _dict(source_context)
        usage = self._signal_usage(
            discovery=discovery,
            understanding=understanding,
            briefs=briefs,
            analysis=analysis,
            story=story,
            virality=virality,
            planning=planning,
            memory=memory_data,
        )
        candidates = {
            item.candidate_id: item
            for item in (discovery.candidates if discovery is not None else [])
        }
        briefs_by_id = {item.clip_id: item for item in briefs}
        decisions = [
            self._decision(
                project_id,
                ranked,
                candidate=candidates.get(ranked.candidate_id),
                brief=briefs_by_id.get(ranked.candidate_id),
                understanding=understanding,
                analysis=analysis,
                story=story,
                virality=virality,
                planning=planning,
                editing=editing,
                memory=memory_data,
                source_context=source,
                signal_usage=usage,
            )
            for ranked in ranking.ranked_candidates
        ]
        decision_ids = {item.candidate_id for item in decisions}
        for index, rejected in enumerate(ranking.rejected_candidates, start=len(decisions) + 1):
            if rejected.candidate_id in decision_ids:
                continue
            decisions.append(
                self._rejected_decision(
                    project_id,
                    rejected.candidate_id,
                    rank=index,
                    score=rejected.score,
                    reason=rejected.reason,
                    warning=rejected.warning,
                    candidate=candidates.get(rejected.candidate_id),
                )
            )
            decision_ids.add(rejected.candidate_id)
        selected_ids = self._select(ranking, decisions)
        selected_set = set(selected_ids)
        for decision in decisions:
            decision.selected = decision.candidate_id in selected_set
            if decision.selected:
                decision.decision_reasons = _unique(
                    [
                        *decision.decision_reasons,
                        "Selected in BOBA's advisory production order.",
                    ],
                    limit=24,
                )
            elif decision.render_readiness != "blocked":
                decision.decision_reasons = _unique(
                    [
                        *decision.decision_reasons,
                        "Retained outside the current advisory production set.",
                    ],
                    limit=24,
                )
        selected_ids = [
            item.candidate_id
            for item in decisions
            if item.selected and item.render_readiness != "blocked"
        ][: self.maximum_selected]
        rejected_ids = [item.candidate_id for item in decisions if not item.selected]
        risk_summary = self._risk_summary(decisions)
        warnings = list(usage.warnings)
        if len(selected_ids) < self.minimum_selection_target:
            warnings.append(
                "Fewer than three candidates cleared editorial selection; blocked or weak "
                "clips were not promoted to fill a quota."
            )
        if any(item.render_readiness != "ready_for_render" for item in decisions if item.selected):
            warnings.append(
                "At least one selected advisory decision still needs revision before rendering."
            )
        summary = (
            f"BOBA produced {len(decisions)} editorial decision(s), selected "
            f"{len(selected_ids)} in production order, marked "
            f"{risk_summary.ready_for_render_count} ready, "
            f"{risk_summary.needs_revision_count} for revision, and "
            f"{risk_summary.blocked_count} blocked."
        )
        return BobaEditorialDecisionSetV1(
            project_id=project_id,
            source_id=ranking.source_id,
            summary=summary,
            selected_clip_ids=selected_ids,
            rejected_clip_ids=_unique(rejected_ids, limit=100, maximum=128),
            production_order=selected_ids,
            decisions=decisions,
            risk_summary=risk_summary,
            signal_usage=usage,
            warnings=_unique(warnings, limit=64),
            limitations=[
                "V1 decisions are advisory metadata and do not alter Olympus plans or timelines.",
                "Render readiness is a preflight heuristic, not proof that rendering succeeded.",
                "Music output is mood metadata only; no song, asset, or file path is selected.",
                "Rights warnings do not establish ownership, permission, or copyright safety.",
                "Scores and tactics do not predict real audience performance.",
                "Human editorial and rights review remain required.",
            ],
        )

    def decide_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        clip_ranking: BobaClipRankingV1 | Mapping[str, Any] | None,
        candidate_discovery: (
            BobaCandidateClipDiscoveryV1 | Mapping[str, Any] | None
        ) = None,
        creative_briefs: Sequence[BobaCreativeBriefV1 | Mapping[str, Any]] | None = None,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
    ) -> BobaEditorialDecisionSetV1:
        project = _dict(signals.get("project"))
        source_type = _text(
            signals.get("source_type") or project.get("source_type"), maximum=80
        ) or "upload"
        rights_status = _text(project.get("rights_status"), maximum=80) or (
            "local_upload" if source_type == "upload" else "unknown"
        )
        planning = {
            "selected_plans": _list(signals.get("selected_plans")),
            "planning_candidates": _list(signals.get("planning_candidates")),
            "planning_summary": _dict(signals.get("planning_summary")),
        }
        return self.decide(
            project_id=project_id,
            clip_ranking=clip_ranking,
            candidate_discovery=candidate_discovery,
            whole_video_understanding=_dict(signals.get("whole_video_understanding")),
            creative_briefs=creative_briefs,
            analysis_artifact=_dict(signals.get("analysis_signals_v2")),
            story_artifact=_dict(signals.get("story_analysis_v2")),
            virality_artifact=_dict(signals.get("virality_summary")),
            planning_artifact=planning,
            editing_artifact={
                "summary": _dict(signals.get("editing_summary")),
                "timelines": _list(signals.get("editing_timelines")),
            },
            memory=memory,
            source_context={
                "source_type": source_type,
                "external_source": source_type != "upload",
                "rights_status": rights_status,
                "transcript_available": bool(signals.get("transcript_available")),
                "face_signals_available": bool(signals.get("face_signals_available")),
                "speaker_signals_available": bool(
                    signals.get("speaker_signals_available")
                ),
                "visual_signals_available": bool(signals.get("visual_signals_available")),
            },
        )

    @staticmethod
    def _ranking(
        value: BobaClipRankingV1 | Mapping[str, Any] | None,
        project_id: str,
    ) -> BobaClipRankingV1:
        if value is None or not _dict(value):
            raise ValidationError(
                "BOBA Editorial Decision Engine requires a saved clip ranking artifact.",
                details={"project_id": project_id, "missing_signal": "clip_ranking"},
            )
        try:
            ranking = (
                value
                if isinstance(value, BobaClipRankingV1)
                else BobaClipRankingV1.model_validate(value)
            )
        except ValueError as exc:
            raise ValidationError(
                "BOBA clip ranking artifact is invalid.",
                details={"project_id": project_id},
            ) from exc
        if not ranking.ranked_candidates:
            raise ValidationError(
                "BOBA editorial decisions cannot use an empty clip ranking artifact.",
                details={"project_id": project_id, "ranked_candidate_count": 0},
            )
        return ranking

    @staticmethod
    def _discovery(
        value: BobaCandidateClipDiscoveryV1 | Mapping[str, Any] | None,
        project_id: str,
    ) -> BobaCandidateClipDiscoveryV1 | None:
        if value is None or not _dict(value):
            return None
        try:
            return (
                value
                if isinstance(value, BobaCandidateClipDiscoveryV1)
                else BobaCandidateClipDiscoveryV1.model_validate(value)
            )
        except ValueError as exc:
            raise ValidationError(
                "BOBA candidate discovery artifact is invalid.",
                details={"project_id": project_id},
            ) from exc

    @staticmethod
    def _briefs(
        values: Sequence[BobaCreativeBriefV1 | Mapping[str, Any]] | None,
        project_id: str,
    ) -> list[BobaCreativeBriefV1]:
        result: list[BobaCreativeBriefV1] = []
        for value in values or []:
            try:
                result.append(
                    value
                    if isinstance(value, BobaCreativeBriefV1)
                    else BobaCreativeBriefV1.model_validate(value)
                )
            except ValueError as exc:
                raise ValidationError(
                    "BOBA creative brief artifact is invalid.",
                    details={"project_id": project_id},
                ) from exc
        return result

    def _decision(
        self,
        project_id: str,
        ranked: BobaRankedClipV1,
        *,
        candidate: BobaCandidateClipV1 | None,
        brief: BobaCreativeBriefV1 | None,
        understanding: dict[str, Any],
        analysis: dict[str, Any],
        story: dict[str, Any],
        virality: dict[str, Any],
        planning: dict[str, Any],
        editing: dict[str, Any],
        memory: dict[str, Any],
        source_context: dict[str, Any],
        signal_usage: BobaEditorialSignalUsageV1,
    ) -> BobaEditorialDecisionV1:
        start = ranked.source_window.get("start_seconds", 0.0)
        end = ranked.source_window.get("end_seconds", start)
        context = self._clip_context(
            start,
            end,
            understanding=understanding,
            story=story,
            virality=virality,
            planning=planning,
            editing=editing,
        )
        hook_strategy = self._hook_strategy(ranked, candidate, brief)
        risk = self._risk_review(
            ranked,
            candidate=candidate,
            source_context=source_context,
            signal_usage=signal_usage,
        )
        readiness, readiness_reason = self._readiness(ranked, risk)
        pacing = self._pacing(ranked, candidate, brief, context)
        caption = self._caption_style(
            ranked,
            candidate,
            brief,
            hook_strategy=hook_strategy,
            transcript_available=bool(source_context.get("transcript_available")),
        )
        motion = self._motion_style(
            ranked,
            brief,
            pacing=pacing,
            visual_layout_risk=risk.visual_layout_risk,
        )
        music = self._music_mood(ranked, candidate, brief, pacing=pacing)
        pacing, caption, motion, music = self._memory_preferences(
            memory,
            pacing=pacing,
            caption=caption,
            motion=motion,
            music=music,
            risk=risk,
        )
        sfx = self._sfx_intensity(ranked, pacing=pacing, readiness=readiness)
        story_angle = self._story_angle(ranked, candidate, brief, context)
        opening = self._opening_direction(ranked, hook_strategy, risk)
        visual_emphasis = self._visual_emphasis(
            hook_strategy,
            caption=caption,
            motion=motion,
            candidate=candidate,
        )
        retention = self._retention_tactics(ranked, hook_strategy, risk)
        improvements = self._improvement_notes(ranked, risk)
        reasons = self._decision_reasons(
            ranked,
            brief=brief,
            readiness=readiness,
            story_angle=story_angle,
        )
        packet = self._instruction_packet(
            ranked,
            hook_strategy=hook_strategy,
            opening=opening,
            pacing=pacing,
            caption=caption,
            motion=motion,
            music=music,
            sfx=sfx,
            retention=retention,
            risk=risk,
        )
        priority = ranked.production_priority
        if readiness == "blocked":
            priority = "do_not_produce"
        elif readiness == "needs_revision" and priority == "immediate":
            priority = "high"
        confidence_penalty = 0.08 * len(risk.blockers) + 0.02 * len(risk.warnings)
        confidence = round(
            _unit(ranked.confidence - min(0.35, confidence_penalty)), 3
        )
        return BobaEditorialDecisionV1(
            candidate_id=ranked.candidate_id,
            ranked_clip_id=ranked.candidate_id,
            project_id=project_id,
            rank=ranked.rank,
            ranking_score=ranked.total_score,
            ranking_tier=ranked.tier,
            suggested_title=ranked.suggested_title,
            candidate_type=ranked.candidate_type,
            source_window=ranked.source_window,
            selected=False,
            render_readiness=readiness,
            render_readiness_reason=readiness_reason,
            production_priority=priority,
            final_story_angle=story_angle,
            final_hook_strategy=hook_strategy,
            opening_line_direction=opening,
            pacing_intensity=pacing,
            caption_style=caption,
            motion_style=motion,
            music_mood=music,
            sfx_intensity=sfx,
            visual_emphasis=visual_emphasis,
            retention_tactics=retention,
            editing_instruction_packet=packet,
            risk_review=risk,
            decision_reasons=reasons,
            improvement_notes=improvements,
            confidence=confidence,
        )

    @staticmethod
    def _clip_context(
        start: float,
        end: float,
        *,
        understanding: dict[str, Any],
        story: dict[str, Any],
        virality: dict[str, Any],
        planning: dict[str, Any],
        editing: dict[str, Any],
    ) -> dict[str, Any]:
        sections = [
            _dict(item)
            for item in _list(understanding.get("section_scores"))
            if _overlaps(_dict(item), start, end)
        ]
        emotional_beats = [
            _dict(item)
            for item in _list(understanding.get("emotional_beats"))
            if _overlaps(_dict(item), start, end)
        ]
        story_items = [
            _dict(item)
            for item in [
                *_list(story.get("micro_stories")),
                *_list(story.get("recommended_clip_stories")),
            ]
            if _overlaps(_dict(item), start, end)
        ]
        planning_items: list[dict[str, Any]] = []
        for key in ("selected_plans", "planning_candidates", "plans", "candidates"):
            planning_items.extend(
                _dict(item)
                for item in _list(planning.get(key))
                if _overlaps(_dict(item), start, end)
            )
        editing_items = [
            _dict(item)
            for item in _list(editing.get("timelines"))
            if _overlaps(_dict(item), start, end)
        ]
        return {
            "sections": sections,
            "emotional_beats": emotional_beats,
            "story_items": story_items,
            "planning_items": planning_items,
            "editing_items": editing_items,
            "virality": virality,
            "energy": max(
                [_unit(item.get("energy_score")) for item in sections] or [0.0]
            ),
            "emotion_intensity": max(
                [_unit(item.get("intensity")) for item in emotional_beats] or [0.0]
            ),
        }

    @staticmethod
    def _hook_strategy(
        ranked: BobaRankedClipV1,
        candidate: BobaCandidateClipV1 | None,
        brief: BobaCreativeBriefV1 | None,
    ) -> BobaHookStrategy:
        text = " ".join(
            [
                ranked.candidate_type,
                ranked.hook_idea,
                brief.hook_type if brief else "",
                candidate.discovery_reason if candidate else "",
            ]
        ).casefold()
        if "controvers" in text or "contradict" in text:
            return "contradiction"
        if "truth" in text or "shocking" in text:
            return "shocking_truth"
        if "motiv" in text or "triumph" in text:
            return "motivational_payoff"
        if "emotional" in text or "reveal" in text:
            return "emotional_reveal"
        if "story_turn" in text or "turn" in text:
            return "story_turn"
        if "education" in text or "explanation" in text or "how" in text:
            return "educational_open_loop"
        if "payoff" in text or "solution" in text:
            return "problem_solution"
        if "curiosity" in text or "why" in text or "open_loop" in text:
            return "curiosity_gap"
        return "direct_value"

    @staticmethod
    def _risk_review(
        ranked: BobaRankedClipV1,
        *,
        candidate: BobaCandidateClipV1 | None,
        source_context: dict[str, Any],
        signal_usage: BobaEditorialSignalUsageV1,
    ) -> BobaEditorialRiskReviewV1:
        breakdown = ranked.score_breakdown
        warning_text = " ".join([*ranked.risk_warnings, *ranked.improvement_suggestions]).casefold()
        weak_hook = breakdown.hook_score < 55.0
        missing_context = bool(
            breakdown.context_risk_score >= 50.0
            or (candidate and (candidate.context_needed or candidate.setup_required))
        )
        weak_payoff = bool(
            breakdown.payoff_score < 55.0
            or (candidate is not None and not candidate.payoff_present)
        )
        filler_risk = bool(
            breakdown.repetition_penalty >= 50.0
            or "filler" in warning_text
            or "repetition" in warning_text
        )
        duplicate_risk = bool(
            breakdown.overlap_penalty >= 45.0
            or "duplicate" in warning_text
            or "overlap" in warning_text
        )
        rights_status = _text(source_context.get("rights_status"), maximum=80).casefold()
        external = bool(source_context.get("external_source"))
        rights_risk = bool(
            breakdown.rights_safety_penalty >= 50.0
            or (
                rights_status in {"denied", "not_authorized", "rejected", "unknown"}
                and external
            )
        )
        audio_risk = not bool(source_context.get("transcript_available"))
        visual_layout_risk = not bool(source_context.get("face_signals_available"))
        unavailable_signal_risk = signal_usage.fallback_used
        blockers: list[str] = []
        start = ranked.source_window.get("start_seconds", 0.0)
        end = ranked.source_window.get("end_seconds", start)
        if end <= start:
            blockers.append("Candidate source window is invalid.")
        if rights_status in {"denied", "not_authorized", "rejected"}:
            blockers.append("Source rights are explicitly not authorized.")
        elif breakdown.rights_safety_penalty >= 90.0:
            blockers.append("Ranking reports a severe source-rights safety penalty.")
        if breakdown.context_risk_score >= 85.0:
            blockers.append("Context dependency is too severe for a standalone clip.")
        if ranked.tier == "reject":
            blockers.append("BOBA Clip Ranking rejected this candidate.")
        warnings: list[str] = list(ranked.risk_warnings)
        risk_messages = (
            (weak_hook, "Hook strength is below the editorial readiness floor."),
            (missing_context, "The clip needs setup or additional context."),
            (weak_payoff, "The clip has no sufficiently strong confirmed payoff."),
            (filler_risk, "Filler or repetition should be cut before rendering."),
            (duplicate_risk, "The candidate duplicates or heavily overlaps a stronger idea."),
            (rights_risk, "Rights status requires human confirmation before production."),
            (audio_risk, "Transcript/audio evidence is unavailable for caption and mix review."),
            (
                visual_layout_risk,
                "Face/layout evidence is unavailable; motion must use a safe fallback.",
            ),
            (
                unavailable_signal_risk,
                "One or more optional upstream signals are unavailable.",
            ),
        )
        warnings.extend(message for active, message in risk_messages if active)
        return BobaEditorialRiskReviewV1(
            weak_hook=weak_hook,
            missing_context=missing_context,
            weak_payoff=weak_payoff,
            filler_risk=filler_risk,
            duplicate_risk=duplicate_risk,
            rights_risk=rights_risk,
            audio_risk=audio_risk,
            visual_layout_risk=visual_layout_risk,
            unavailable_signal_risk=unavailable_signal_risk,
            blockers=_unique(blockers, limit=24),
            warnings=_unique(warnings, limit=32),
        )

    @staticmethod
    def _readiness(
        ranked: BobaRankedClipV1,
        risk: BobaEditorialRiskReviewV1,
    ) -> tuple[BobaRenderReadiness, str]:
        if risk.blockers:
            return "blocked", risk.blockers[0]
        revision_risk = any(
            (
                risk.weak_hook,
                risk.missing_context,
                risk.weak_payoff,
                risk.filler_risk,
                risk.duplicate_risk,
                risk.rights_risk,
            )
        )
        if ranked.total_score >= 70.0 and not revision_risk:
            return (
                "ready_for_render",
                "Strong ranking and no blocking hook, payoff, context, duplicate, or rights risk.",
            )
        if ranked.tier in {"must_make", "strong_candidate", "backup_candidate"}:
            return (
                "needs_revision",
                "Candidate remains promising but one or more editorial risks need correction.",
            )
        return (
            "needs_revision",
            "Candidate ranking is below the production-ready floor and needs editorial revision.",
        )

    @staticmethod
    def _pacing(
        ranked: BobaRankedClipV1,
        candidate: BobaCandidateClipV1 | None,
        brief: BobaCreativeBriefV1 | None,
        context: dict[str, Any],
    ) -> BobaPacingIntensity:
        if brief:
            mapped = {
                "calm": "calm",
                "balanced": "moderate",
                "fast": "fast",
                "aggressive": "aggressive",
            }.get(brief.pacing_level)
            if mapped:
                return mapped  # type: ignore[return-value]
        duration = ranked.source_window.get("duration_seconds", 0.0)
        energy = max(
            context.get("energy", 0.0),
            context.get("emotion_intensity", 0.0),
            ranked.score_breakdown.emotional_score / 100.0,
        )
        if ranked.candidate_type == "high_energy_section" and energy >= 0.8:
            return "aggressive"
        if ranked.score_breakdown.pacing_score >= 82.0 or energy >= 0.72:
            return "fast"
        if duration > 50.0 or (candidate and candidate.emotion_label in {"sad", "reflective"}):
            return "calm"
        return "moderate"

    @staticmethod
    def _caption_style(
        ranked: BobaRankedClipV1,
        candidate: BobaCandidateClipV1 | None,
        brief: BobaCreativeBriefV1 | None,
        *,
        hook_strategy: BobaHookStrategy,
        transcript_available: bool,
    ) -> BobaCaptionStyle:
        if not transcript_available:
            return "none"
        brief_style = (brief.caption_style if brief else "").casefold()
        if "minimal" in brief_style:
            return "minimal"
        if "keyword" in brief_style:
            return "keyword_highlight"
        if "emotion" in brief_style:
            return "emotional_emphasis"
        if "bold" in brief_style or "hook" in brief_style:
            return "bold_hook_captions"
        if hook_strategy in {"curiosity_gap", "contradiction", "shocking_truth"}:
            return "bold_hook_captions"
        if hook_strategy in {"emotional_reveal", "motivational_payoff"}:
            return "emotional_emphasis"
        if hook_strategy in {"educational_open_loop", "direct_value"} or (
            candidate and candidate.candidate_type == "educational_moment"
        ):
            return "keyword_highlight"
        if ranked.score_breakdown.clarity_score >= 90.0:
            return "minimal"
        return "clean_subtitles"

    @staticmethod
    def _motion_style(
        ranked: BobaRankedClipV1,
        brief: BobaCreativeBriefV1 | None,
        *,
        pacing: BobaPacingIntensity,
        visual_layout_risk: bool,
    ) -> BobaMotionStyle:
        if visual_layout_risk:
            return "layout_safe"
        brief_style = (brief.motion_style if brief else "").casefold()
        if "stable" in brief_style or "layout" in brief_style:
            return "stable"
        if "punch" in brief_style:
            return "punch_in"
        if "dynamic" in brief_style:
            return "dynamic_zoom"
        if pacing == "aggressive":
            return "high_motion"
        if pacing == "fast":
            return "dynamic_zoom"
        if ranked.score_breakdown.hook_score >= 78.0:
            return "punch_in"
        return "subtle_zoom"

    @staticmethod
    def _music_mood(
        ranked: BobaRankedClipV1,
        candidate: BobaCandidateClipV1 | None,
        brief: BobaCreativeBriefV1 | None,
        *,
        pacing: BobaPacingIntensity,
    ) -> BobaMusicMood:
        text = " ".join(
            [
                brief.music_mood if brief else "",
                candidate.emotion_label if candidate else "",
                ranked.candidate_type,
                ranked.story_angle,
            ]
        ).casefold()
        options: tuple[tuple[str, BobaMusicMood], ...] = (
            ("funny", "funny"),
            ("humor", "funny"),
            ("motiv", "motivational"),
            ("triumph", "motivational"),
            ("education", "educational"),
            ("explanation", "educational"),
            ("suspense", "suspense"),
            ("tension", "suspense"),
            ("emotional", "emotional"),
            ("sad", "emotional"),
            ("cinematic", "cinematic"),
            ("story_turn", "cinematic"),
            ("calm", "calm"),
            ("reflective", "calm"),
            ("energetic", "energetic"),
        )
        for cue, mood in options:
            if cue in text:
                return mood
        if pacing in {"fast", "aggressive"}:
            return "energetic"
        return "calm"

    @staticmethod
    def _memory_preferences(
        memory: dict[str, Any],
        *,
        pacing: BobaPacingIntensity,
        caption: BobaCaptionStyle,
        motion: BobaMotionStyle,
        music: BobaMusicMood,
        risk: BobaEditorialRiskReviewV1,
    ) -> tuple[BobaPacingIntensity, BobaCaptionStyle, BobaMotionStyle, BobaMusicMood]:
        if not memory:
            return pacing, caption, motion, music
        memory_text = json_safe_memory_text(memory)
        if "prefers fast" in memory_text or "liked fast" in memory_text:
            pacing = "fast"
        elif "prefers calm" in memory_text or "liked calm" in memory_text:
            pacing = "calm"
        if "keyword caption" in memory_text:
            caption = "keyword_highlight"
        elif "minimal caption" in memory_text:
            caption = "minimal"
        if "stable motion" in memory_text or risk.visual_layout_risk:
            motion = "layout_safe" if risk.visual_layout_risk else "stable"
        for mood in (
            "motivational",
            "emotional",
            "suspense",
            "energetic",
            "calm",
            "funny",
            "cinematic",
            "educational",
        ):
            if f"prefers {mood}" in memory_text or f"liked {mood}" in memory_text:
                music = mood
                break
        return pacing, caption, motion, music

    @staticmethod
    def _sfx_intensity(
        ranked: BobaRankedClipV1,
        *,
        pacing: BobaPacingIntensity,
        readiness: BobaRenderReadiness,
    ) -> BobaSfxIntensity:
        if readiness == "blocked":
            return "none"
        if pacing in {"fast", "aggressive"} and ranked.score_breakdown.hook_score >= 72.0:
            return "moderate"
        if ranked.score_breakdown.hook_score >= 65.0:
            return "light"
        return "none"

    @staticmethod
    def _story_angle(
        ranked: BobaRankedClipV1,
        candidate: BobaCandidateClipV1 | None,
        brief: BobaCreativeBriefV1 | None,
        context: dict[str, Any],
    ) -> str:
        if brief and brief.story_angle:
            return brief.story_angle
        for item in context.get("story_items", []):
            angle = _text(
                item.get("story_summary")
                or item.get("summary")
                or item.get("story_shape"),
                maximum=400,
            )
            if angle:
                return angle
        return _text(
            candidate.story_angle if candidate else ranked.story_angle,
            maximum=400,
        ) or "Deliver one self-contained source-supported idea with a clear ending."

    @staticmethod
    def _opening_direction(
        ranked: BobaRankedClipV1,
        hook_strategy: BobaHookStrategy,
        risk: BobaEditorialRiskReviewV1,
    ) -> str:
        if risk.weak_hook:
            return (
                "Start on the clearest truthful value statement already present in the source; "
                "do not invent a stronger claim."
            )
        return (
            f"Use a {hook_strategy.replace('_', ' ')} opening and front-load the existing "
            f"source-supported hook idea: {ranked.hook_idea}"
        )[:500]

    @staticmethod
    def _visual_emphasis(
        hook_strategy: BobaHookStrategy,
        *,
        caption: BobaCaptionStyle,
        motion: BobaMotionStyle,
        candidate: BobaCandidateClipV1 | None,
    ) -> list[str]:
        values = [
            f"Emphasize the opening {hook_strategy.replace('_', ' ')} beat.",
            f"Use {caption.replace('_', ' ')} without changing spoken meaning.",
            f"Keep motion {motion.replace('_', ' ')} and layout-safe.",
        ]
        if candidate and candidate.payoff_present:
            values.append("Hold visual emphasis through the confirmed payoff.")
        return values

    @staticmethod
    def _retention_tactics(
        ranked: BobaRankedClipV1,
        hook_strategy: BobaHookStrategy,
        risk: BobaEditorialRiskReviewV1,
    ) -> list[str]:
        values = ["Make the first three seconds immediate and free of avoidable dead air."]
        if hook_strategy in {"curiosity_gap", "educational_open_loop", "story_turn"}:
            values.append("Preserve the truthful open loop until its source-supported answer.")
        if ranked.score_breakdown.payoff_score >= 65.0:
            values.append("Protect the payoff tail; do not cut the final resolving phrase.")
        values.append("Use one restrained pattern interrupt instead of constant motion.")
        if risk.filler_risk:
            values.append("Cut filler and repeated phrases without changing meaning.")
        if risk.missing_context:
            values.append("Add compact truthful setup before asking the viewer to infer context.")
        return _unique(values, limit=20)

    @staticmethod
    def _improvement_notes(
        ranked: BobaRankedClipV1,
        risk: BobaEditorialRiskReviewV1,
    ) -> list[str]:
        values = list(ranked.improvement_suggestions)
        additions = (
            (risk.weak_hook, "Strengthen the opening using only source-supported wording."),
            (risk.missing_context, "Repair the boundary or add compact truthful setup."),
            (risk.weak_payoff, "Extend to the complete payoff or reject the clip."),
            (risk.filler_risk, "Remove repeated/filler material before timeline execution."),
            (risk.duplicate_risk, "Differentiate the angle or keep the stronger candidate only."),
            (risk.rights_risk, "Confirm ownership or permission before production."),
            (risk.audio_risk, "Verify transcript, speech clarity, music, and sync before render."),
            (
                risk.visual_layout_risk,
                "Use stable/layout-safe framing until face and speaker evidence is available.",
            ),
        )
        values.extend(message for active, message in additions if active)
        return _unique(values, limit=24)

    @staticmethod
    def _decision_reasons(
        ranked: BobaRankedClipV1,
        *,
        brief: BobaCreativeBriefV1 | None,
        readiness: BobaRenderReadiness,
        story_angle: str,
    ) -> list[str]:
        values = list(ranked.ranking_reasons)
        values.append(
            f"Ranking tier {ranked.tier.replace('_', ' ')} produced {readiness.replace('_', ' ')}."
        )
        values.append(f"Editorial angle: {story_angle}")
        if brief:
            values.append("A saved BOBA Creative Director brief informed this decision.")
        return _unique(values, limit=24)

    @staticmethod
    def _instruction_packet(
        ranked: BobaRankedClipV1,
        *,
        hook_strategy: BobaHookStrategy,
        opening: str,
        pacing: BobaPacingIntensity,
        caption: BobaCaptionStyle,
        motion: BobaMotionStyle,
        music: BobaMusicMood,
        sfx: BobaSfxIntensity,
        retention: list[str],
        risk: BobaEditorialRiskReviewV1,
    ) -> BobaEditingInstructionPacketV1:
        risk_text = "; ".join([*risk.blockers, *risk.warnings]) or (
            "No blocking editorial risk was detected; normal human review still applies."
        )
        return BobaEditingInstructionPacketV1(
            hook_instruction=(
                f"Use {hook_strategy.replace('_', ' ')}. {opening}"
            )[:500],
            cut_instruction=(
                "Preserve the complete source window and payoff; cut only verified filler or "
                "dead air without changing meaning."
            ),
            caption_instruction=(
                f"Use {caption.replace('_', ' ')} captions faithful to spoken content."
            ),
            motion_instruction=(
                f"Use {motion.replace('_', ' ')} motion with stable, readable framing."
            ),
            audio_instruction=(
                f"Use {music} mood metadata and {sfx} clean SFX intensity; choose no track or "
                "asset here and keep speech first."
            ),
            pacing_instruction=(
                f"Use {pacing} pacing while preserving setup, speech synchronization, and payoff."
            ),
            retention_instruction=" ".join(retention)[:500],
            risk_instruction=risk_text[:700],
        )

    def _select(
        self,
        ranking: BobaClipRankingV1,
        decisions: list[BobaEditorialDecisionV1],
    ) -> list[str]:
        by_id = {item.candidate_id: item for item in decisions}
        ranked_by_id = {item.candidate_id: item for item in ranking.ranked_candidates}
        ordered_ids = _unique(
            [
                *ranking.recommended_clip_ids,
                *[item.candidate_id for item in ranking.ranked_candidates],
            ],
            limit=100,
            maximum=128,
        )
        selected: list[str] = []
        for candidate_id in ordered_ids:
            decision = by_id.get(candidate_id)
            ranked = ranked_by_id.get(candidate_id)
            if (
                decision is None
                or ranked is None
                or decision.render_readiness == "blocked"
                or ranked.tier not in {"must_make", "strong_candidate"}
            ):
                continue
            selected.append(candidate_id)
            if len(selected) >= self.maximum_selected:
                return selected
        if len(selected) < self.minimum_selection_target:
            for candidate_id in ordered_ids:
                decision = by_id.get(candidate_id)
                ranked = ranked_by_id.get(candidate_id)
                if (
                    candidate_id in selected
                    or decision is None
                    or ranked is None
                    or decision.render_readiness == "blocked"
                    or ranked.tier != "backup_candidate"
                ):
                    continue
                selected.append(candidate_id)
                if len(selected) >= self.minimum_selection_target:
                    break
        return selected[: self.maximum_selected]

    @staticmethod
    def _rejected_decision(
        project_id: str,
        candidate_id: str,
        *,
        rank: int,
        score: float,
        reason: str,
        warning: str,
        candidate: BobaCandidateClipV1 | None,
    ) -> BobaEditorialDecisionV1:
        duplicate = "duplicate" in reason.casefold() or "overlap" in reason.casefold()
        title = candidate.suggested_title if candidate else f"Rejected {candidate_id}"
        angle = (
            candidate.story_angle
            if candidate
            else "Rejected ranking candidate has no retained editorial angle."
        )
        window = (
            {
                "start_seconds": candidate.start_seconds,
                "end_seconds": candidate.end_seconds,
                "duration_seconds": candidate.duration_seconds,
            }
            if candidate
            else {"start_seconds": 0.0, "end_seconds": 0.0, "duration_seconds": 0.0}
        )
        risk = BobaEditorialRiskReviewV1(
            weak_hook=True,
            missing_context=False,
            weak_payoff=True,
            filler_risk=False,
            duplicate_risk=duplicate,
            rights_risk=False,
            audio_risk=False,
            visual_layout_risk=False,
            unavailable_signal_risk=False,
            blockers=[reason],
            warnings=[warning] if warning else [],
        )
        packet = BobaEditingInstructionPacketV1(
            hook_instruction="Do not produce this rejected candidate without a new ranking.",
            cut_instruction="Keep this rejected candidate out of the production timeline.",
            caption_instruction="No caption instruction applies while the candidate is blocked.",
            motion_instruction="No motion instruction applies while the candidate is blocked.",
            audio_instruction="No music, SFX, or track selection applies while blocked.",
            pacing_instruction="No pacing instruction applies while the candidate is blocked.",
            retention_instruction="Resolve the ranking rejection before retention treatment.",
            risk_instruction=reason,
        )
        return BobaEditorialDecisionV1(
            candidate_id=candidate_id,
            ranked_clip_id=candidate_id,
            project_id=project_id,
            rank=rank,
            ranking_score=max(0.0, min(100.0, score)),
            ranking_tier="reject",
            suggested_title=title,
            candidate_type=candidate.candidate_type if candidate else "unknown",
            source_window=window,
            selected=False,
            render_readiness="blocked",
            render_readiness_reason=reason,
            production_priority="do_not_produce",
            final_story_angle=angle,
            final_hook_strategy="direct_value",
            opening_line_direction="Do not create an opening until the rejection is resolved.",
            pacing_intensity="moderate",
            caption_style="none",
            motion_style="stable",
            music_mood="none",
            sfx_intensity="none",
            visual_emphasis=[],
            retention_tactics=[],
            editing_instruction_packet=packet,
            risk_review=risk,
            decision_reasons=[reason],
            improvement_notes=[warning] if warning else ["Review the ranking rejection."],
            confidence=0.9,
        )

    @staticmethod
    def _risk_summary(
        decisions: list[BobaEditorialDecisionV1],
    ) -> BobaEditorialRiskSummaryV1:
        risk_counts: Counter[str] = Counter()
        blockers: list[str] = []
        warnings: list[str] = []
        labels = (
            ("weak_hook", "weak hook"),
            ("missing_context", "missing context"),
            ("weak_payoff", "weak payoff"),
            ("filler_risk", "filler/repetition"),
            ("duplicate_risk", "duplicate/overlap"),
            ("rights_risk", "rights review"),
            ("audio_risk", "audio evidence"),
            ("visual_layout_risk", "visual/layout evidence"),
            ("unavailable_signal_risk", "unavailable signals"),
        )
        for decision in decisions:
            for field, label in labels:
                if getattr(decision.risk_review, field):
                    risk_counts[label] += 1
            blockers.extend(
                f"{decision.candidate_id}: {item}"
                for item in decision.risk_review.blockers
            )
            warnings.extend(
                f"{decision.candidate_id}: {item}"
                for item in decision.risk_review.warnings
            )
        top_risks = [
            f"{label}: {count} clip(s)"
            for label, count in risk_counts.most_common(16)
        ]
        return BobaEditorialRiskSummaryV1(
            selected_count=sum(item.selected for item in decisions),
            ready_for_render_count=sum(
                item.render_readiness == "ready_for_render" for item in decisions
            ),
            needs_revision_count=sum(
                item.render_readiness == "needs_revision" for item in decisions
            ),
            blocked_count=sum(item.render_readiness == "blocked" for item in decisions),
            top_risks=top_risks,
            blockers=_unique(blockers, limit=64),
            warnings=_unique(warnings, limit=64),
        )

    @staticmethod
    def _signal_usage(
        *,
        discovery: BobaCandidateClipDiscoveryV1 | None,
        understanding: dict[str, Any],
        briefs: list[BobaCreativeBriefV1],
        analysis: dict[str, Any],
        story: dict[str, Any],
        virality: dict[str, Any],
        planning: dict[str, Any],
        memory: dict[str, Any],
    ) -> BobaEditorialSignalUsageV1:
        availability = {
            "candidate_discovery": discovery is not None,
            "whole_video_understanding": bool(understanding),
            "creative_briefs": bool(briefs),
            "analysis_signals_v2": bool(analysis),
            "story_analysis_v2": bool(story),
            "virality_v2": bool(virality),
            "planning_v2": any(bool(value) for value in planning.values()),
            "boba_memory": bool(memory),
        }
        unavailable = [name for name, available in availability.items() if not available]
        warnings: list[str] = []
        if unavailable:
            warnings.append(
                "Editorial decisions used deterministic fallbacks for unavailable optional "
                "signals: "
                + ", ".join(unavailable)
                + "."
            )
        return BobaEditorialSignalUsageV1(
            clip_ranking_used=True,
            candidate_discovery_used=discovery is not None,
            whole_video_understanding_used=bool(understanding),
            creative_briefs_used=bool(briefs),
            analysis_signals_used=bool(analysis),
            story_used=bool(story),
            virality_used=bool(virality),
            planning_used=any(bool(value) for value in planning.values()),
            memory_used=bool(memory),
            fallback_used=bool(unavailable),
            unavailable_signals=unavailable,
            warnings=warnings,
        )


def json_safe_memory_text(memory: Mapping[str, Any]) -> str:
    """Return a bounded preference-only memory string without retaining raw records."""

    values: list[str] = []
    for key in ("source_summary", "summary", "preferred_patterns"):
        value = memory.get(key)
        if isinstance(value, str):
            values.append(_text(value, maximum=300))
        else:
            values.extend(_text(item, maximum=180) for item in _list(value))
    for value in _list(memory.get("memory_records"))[:50]:
        item = _dict(value)
        values.append(_text(item.get("summary"), maximum=180))
    return " ".join(values).casefold()[:5000]

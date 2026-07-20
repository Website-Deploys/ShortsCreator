"""Deterministic advisory ranking over BOBA-discovered candidate clips."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from olympus.boba.clip_discovery import (
    BobaCandidateClipDiscoveryV1,
    BobaCandidateClipV1,
)
from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.memory_contracts import BobaProjectMemoryV1
from olympus.boba.whole_video import BobaWholeVideoUnderstandingV1
from olympus.platform.errors import ValidationError

BobaRankingTier = Literal[
    "must_make",
    "strong_candidate",
    "backup_candidate",
    "needs_revision",
    "reject",
]
BobaProductionPriority = Literal[
    "immediate",
    "high",
    "medium",
    "low",
    "do_not_produce",
]

_STRONG_HOOK_CUES = (
    "why",
    "how",
    "what happened",
    "the truth",
    "nobody talks",
    "the reason",
    "mistake",
    "secret",
    "changed everything",
    "?",
)
_EMOTIONAL_CUES = (
    "surprise",
    "tension",
    "funny",
    "humor",
    "laugh",
    "hope",
    "motivat",
    "inspir",
    "anger",
    "fear",
    "joy",
    "triumph",
)
_CONFIRMED_RIGHTS = {
    "confirmed",
    "owned",
    "permission_confirmed",
    "rights_confirmed",
    "local_upload",
}


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


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


def _unit(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _number(value, default)))


def _points(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(100.0, _number(value, default)))


def _artifact(value: Mapping[str, Any] | BaseModel | None) -> dict[str, Any]:
    raw = _dict(value)
    data = _dict(raw.get("data"))
    return data or raw


def _unique(values: Sequence[str], *, limit: int, maximum: int = 300) -> list[str]:
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


def _range(item: Mapping[str, Any]) -> tuple[float, float]:
    start = _number(
        item.get("start_seconds")
        if item.get("start_seconds") is not None
        else item.get("start") or item.get("source_start")
    )
    end = _number(
        item.get("end_seconds")
        if item.get("end_seconds") is not None
        else item.get("end") or item.get("source_end"),
        start,
    )
    return max(0.0, start), max(0.0, end)


def _overlap_seconds(
    start: float, end: float, other_start: float, other_end: float
) -> float:
    return max(0.0, min(end, other_end) - max(start, other_start))


def _overlap_ratio(
    start: float, end: float, other_start: float, other_end: float
) -> float:
    intersection = _overlap_seconds(start, end, other_start, other_end)
    shorter = min(max(0.0, end - start), max(0.0, other_end - other_start))
    return intersection / shorter if shorter > 0.0 else 0.0


class BobaClipScoreBreakdownV1(BobaContract):
    hook_score: float = Field(ge=0.0, le=100.0)
    payoff_score: float = Field(ge=0.0, le=100.0)
    standalone_score: float = Field(ge=0.0, le=100.0)
    emotional_score: float = Field(ge=0.0, le=100.0)
    clarity_score: float = Field(ge=0.0, le=100.0)
    novelty_score: float = Field(ge=0.0, le=100.0)
    pacing_score: float = Field(ge=0.0, le=100.0)
    retention_score: float = Field(ge=0.0, le=100.0)
    context_risk_score: float = Field(ge=0.0, le=100.0)
    repetition_penalty: float = Field(ge=0.0, le=100.0)
    overlap_penalty: float = Field(ge=0.0, le=100.0)
    rights_safety_penalty: float = Field(ge=0.0, le=100.0)
    memory_alignment_score: float = Field(ge=0.0, le=100.0)
    final_score: float = Field(ge=0.0, le=100.0)


class BobaRankedClipV1(BobaContract):
    candidate_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    rank: int = Field(ge=1)
    tier: BobaRankingTier
    total_score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    production_priority: BobaProductionPriority
    score_breakdown: BobaClipScoreBreakdownV1
    ranking_reasons: list[str] = Field(default_factory=list, max_length=20)
    risk_warnings: list[str] = Field(default_factory=list, max_length=20)
    improvement_suggestions: list[str] = Field(default_factory=list, max_length=20)
    source_window: dict[str, float]
    candidate_type: str = Field(min_length=1, max_length=80)
    suggested_title: str = Field(min_length=1, max_length=160)
    hook_idea: str = Field(min_length=1, max_length=300)
    story_angle: str = Field(min_length=1, max_length=400)
    source_topic: str = Field(default="unknown", min_length=1, max_length=160)
    emotion_label: str = Field(default="unknown", min_length=1, max_length=80)


class BobaRankingDiversitySummaryV1(BobaContract):
    ranked_count: int = Field(default=0, ge=0)
    recommended_count: int = Field(default=0, ge=0, le=10)
    topic_count: int = Field(default=0, ge=0)
    emotion_count: int = Field(default=0, ge=0)
    candidate_type_count: int = Field(default=0, ge=0)
    overlap_penalties_applied: int = Field(default=0, ge=0)
    duplicate_candidates_removed: int = Field(default=0, ge=0)
    diversity_warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRankingSignalUsageV1(BobaContract):
    candidate_discovery_used: bool
    whole_video_understanding_used: bool
    virality_used: bool
    story_used: bool
    planning_used: bool
    memory_used: bool
    fallback_used: bool
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRejectedRankCandidateV1(BobaContract):
    candidate_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=400)
    score: float = Field(ge=0.0, le=100.0)
    overlap_with_candidate_id: str | None = Field(default=None, max_length=128)
    warning: str = Field(default="", max_length=400)


class BobaClipRankingV1(BobaContract):
    schema_version: Literal["boba_clip_ranking_brain_v1"] = (
        "boba_clip_ranking_brain_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    summary: str = Field(min_length=1, max_length=800)
    ranked_candidates: list[BobaRankedClipV1] = Field(default_factory=list, max_length=100)
    recommended_clip_ids: list[str] = Field(default_factory=list, max_length=10)
    backup_clip_ids: list[str] = Field(default_factory=list, max_length=100)
    rejected_clip_ids: list[str] = Field(default_factory=list, max_length=100)
    rejected_candidates: list[BobaRejectedRankCandidateV1] = Field(
        default_factory=list, max_length=100
    )
    diversity_summary: BobaRankingDiversitySummaryV1
    signal_usage: BobaRankingSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


@dataclass(slots=True)
class _ScoredCandidate:
    candidate: BobaCandidateClipV1
    hook: float
    payoff: float
    standalone: float
    emotional: float
    clarity: float
    novelty: float
    pacing: float
    retention: float
    context_risk: float
    repetition: float
    rights: float
    memory: float
    overlap: float = 0.0
    overlap_with: str | None = None
    final: float = 0.0


class BobaClipRankingEngine:
    """Rank discovered candidates without selecting Olympus plans or rendering media."""

    def __init__(
        self,
        *,
        maximum_recommendations: int = 10,
        minimum_recommendation_target: int = 3,
    ) -> None:
        if not 3 <= maximum_recommendations <= 10:
            raise ValueError("maximum_recommendations must be between 3 and 10")
        if not 1 <= minimum_recommendation_target <= maximum_recommendations:
            raise ValueError("minimum target must not exceed maximum recommendations")
        self.maximum_recommendations = maximum_recommendations
        self.minimum_recommendation_target = minimum_recommendation_target

    def rank(
        self,
        *,
        project_id: str,
        candidate_discovery: BobaCandidateClipDiscoveryV1 | Mapping[str, Any] | None,
        whole_video_understanding: (
            BobaWholeVideoUnderstandingV1 | Mapping[str, Any] | None
        ) = None,
        virality_artifact: Mapping[str, Any] | None = None,
        story_artifact: Mapping[str, Any] | None = None,
        planning_artifact: Mapping[str, Any] | None = None,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
        source_context: Mapping[str, Any] | None = None,
    ) -> BobaClipRankingV1:
        discovery = self._discovery(candidate_discovery, project_id)
        understanding = _artifact(whole_video_understanding)
        virality = _artifact(virality_artifact)
        story = _artifact(story_artifact)
        planning = _artifact(planning_artifact)
        memory_data = _dict(memory)
        source = _dict(source_context)
        topic_frequency = Counter(item.source_topic for item in discovery.candidates)
        scored = [
            self._score_candidate(
                item,
                understanding=understanding,
                virality=virality,
                story=story,
                planning=planning,
                memory=memory_data,
                source_context=source,
                topic_frequency=topic_frequency,
            )
            for item in discovery.candidates
        ]
        scored, duplicate_rejections = self._remove_duplicates(scored)
        self._apply_overlap_penalties(scored)
        for scored_item in scored:
            scored_item.final = self._final_score(scored_item)
        ranked = [
            self._ranked_clip(project_id, scored_item, rank=1)
            for scored_item in scored
        ]
        ranked.sort(
            key=lambda ranked_item: (ranked_item.total_score, ranked_item.confidence),
            reverse=True,
        )
        recommendations, diversity_warnings = self._recommend(ranked)
        recommendation_ids = [item.candidate_id for item in recommendations]
        recommendation_position = {
            candidate_id: index for index, candidate_id in enumerate(recommendation_ids)
        }
        ranked.sort(
            key=lambda item: (
                0 if item.candidate_id in recommendation_position else 1,
                recommendation_position.get(item.candidate_id, 10_000),
                -item.total_score,
                item.candidate_id,
            )
        )
        for index, ranked_item in enumerate(ranked, start=1):
            score_position = next(
                (
                    position
                    for position, candidate in enumerate(
                        sorted(
                            ranked,
                            key=lambda value: value.total_score,
                            reverse=True,
                        ),
                        start=1,
                    )
                    if candidate.candidate_id == ranked_item.candidate_id
                ),
                index,
            )
            ranked_item.rank = index
            if index < score_position:
                ranked_item.ranking_reasons = _unique(
                    [
                        *ranked_item.ranking_reasons,
                        "Promoted to preserve topic, emotion, or candidate-type diversity.",
                    ],
                    limit=20,
                    maximum=300,
                )
        rejected_details = [*duplicate_rejections]
        for ranked_item in ranked:
            if ranked_item.tier != "reject":
                continue
            rejected_details.append(
                BobaRejectedRankCandidateV1(
                    candidate_id=ranked_item.candidate_id,
                    reason="Candidate fell below the advisory quality/risk floor.",
                    score=ranked_item.total_score,
                    overlap_with_candidate_id=None,
                    warning="; ".join(ranked_item.risk_warnings[:2]),
                )
            )
        rejected_ids = _unique(
            [item.candidate_id for item in rejected_details], limit=100, maximum=128
        )
        backup_ids = [
            ranked_item.candidate_id
            for ranked_item in ranked
            if ranked_item.candidate_id not in recommendation_ids
            and ranked_item.tier
            in {"strong_candidate", "backup_candidate", "needs_revision"}
        ]
        usage = self._signal_usage(
            understanding=understanding,
            virality=virality,
            story=story,
            planning=planning,
            memory=memory_data,
        )
        overlap_count = sum(
            ranked_item.score_breakdown.overlap_penalty > 0.0
            for ranked_item in ranked
        )
        recommended = [
            ranked_item
            for ranked_item in ranked
            if ranked_item.candidate_id in recommendation_ids
        ]
        diversity = self._diversity_summary(
            ranked,
            recommended,
            overlap_count=overlap_count,
            duplicate_count=len(duplicate_rejections),
            warnings=diversity_warnings,
        )
        warnings = [*usage.warnings, *diversity_warnings]
        if len(recommendation_ids) < self.minimum_recommendation_target:
            warnings.append(
                "Fewer than three candidates cleared BOBA's advisory recommendation floor; "
                "lower-quality clips were not promoted to fill a quota."
            )
        if any(
            ranked_item.score_breakdown.rights_safety_penalty >= 50.0
            for ranked_item in ranked
        ):
            warnings.append(
                "At least one external/scout candidate has unconfirmed rights; ranking does "
                "not grant production permission."
            )
        summary = (
            f"BOBA ranked {len(ranked)} distinct candidate(s), recommended "
            f"{len(recommendation_ids)}, retained {len(backup_ids)} backup/revision option(s), "
            f"and rejected {len(rejected_ids)}."
        )
        return BobaClipRankingV1(
            project_id=project_id,
            source_id=discovery.source_id,
            summary=summary,
            ranked_candidates=ranked,
            recommended_clip_ids=recommendation_ids,
            backup_clip_ids=backup_ids,
            rejected_clip_ids=rejected_ids,
            rejected_candidates=rejected_details[:100],
            diversity_summary=diversity,
            signal_usage=usage,
            warnings=_unique(warnings, limit=64, maximum=400),
            limitations=[
                "V1 is an advisory local ranking, not an audience-performance prediction.",
                "Scores are deterministic heuristics over available metadata, not platform data.",
                "Ranking does not select Olympus plans, edit media, or trigger rendering.",
                "Rights penalties are warnings and never establish copyright permission.",
                "Human review remains required before production decisions.",
            ],
        )

    def rank_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        candidate_discovery: BobaCandidateClipDiscoveryV1 | Mapping[str, Any] | None,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
    ) -> BobaClipRankingV1:
        project = _dict(signals.get("project"))
        source_type = _text(
            signals.get("source_type") or project.get("source_type"), maximum=80
        ) or "upload"
        selected_plans = _list(signals.get("selected_plans"))
        planning_candidates = _list(signals.get("planning_candidates"))
        planning_summary = _dict(signals.get("planning_summary"))
        planning = (
            {
                "selected_plans": selected_plans,
                "planning_candidates": planning_candidates,
                "planning_summary": planning_summary,
            }
            if selected_plans or planning_candidates or planning_summary
            else {}
        )
        rights_status = _text(project.get("rights_status"), maximum=80) or (
            "local_upload" if source_type == "upload" else "unknown"
        )
        return self.rank(
            project_id=project_id,
            candidate_discovery=candidate_discovery,
            whole_video_understanding=_dict(
                signals.get("whole_video_understanding")
            ),
            virality_artifact=_dict(signals.get("virality_summary")),
            story_artifact=_dict(signals.get("story_analysis_v2")),
            planning_artifact=planning,
            memory=memory,
            source_context={
                "source_type": source_type,
                "external_source": source_type != "upload",
                "rights_status": rights_status,
            },
        )

    @staticmethod
    def _discovery(
        value: BobaCandidateClipDiscoveryV1 | Mapping[str, Any] | None,
        project_id: str,
    ) -> BobaCandidateClipDiscoveryV1:
        if value is None or not _dict(value):
            raise ValidationError(
                "BOBA clip ranking requires a saved candidate discovery artifact.",
                details={"project_id": project_id, "missing_signal": "candidate_discovery"},
            )
        try:
            discovery = (
                value
                if isinstance(value, BobaCandidateClipDiscoveryV1)
                else BobaCandidateClipDiscoveryV1.model_validate(value)
            )
        except ValueError as exc:
            raise ValidationError(
                "BOBA candidate discovery artifact is invalid.",
                details={"project_id": project_id},
            ) from exc
        if not discovery.candidates:
            raise ValidationError(
                "BOBA clip ranking cannot rank an empty candidate discovery artifact.",
                details={"project_id": project_id, "candidate_count": 0},
            )
        return discovery

    def _score_candidate(
        self,
        candidate: BobaCandidateClipV1,
        *,
        understanding: dict[str, Any],
        virality: dict[str, Any],
        story: dict[str, Any],
        planning: dict[str, Any],
        memory: dict[str, Any],
        source_context: dict[str, Any],
        topic_frequency: Counter[str],
    ) -> _ScoredCandidate:
        start = candidate.start_seconds
        end = candidate.end_seconds
        sections = self._overlapping(
            _list(understanding.get("section_scores")), start, end
        )
        emotions = self._overlapping(
            _list(understanding.get("emotional_beats")), start, end
        )
        links = self._payoff_links(understanding, start, end)
        story_items = self._overlapping(
            [
                *_list(story.get("micro_stories")),
                *_list(story.get("recommended_clip_stories")),
            ],
            start,
            end,
        )
        planning_items = self._planning_matches(planning, start, end)
        virality_reasons = self._virality_text(virality)
        hook = self._hook_score(candidate, virality_reasons)
        payoff = self._payoff_score(candidate, links, story_items)
        standalone, context = self._standalone_context_scores(candidate, links)
        emotional = self._emotional_score(candidate, emotions)
        clarity = self._clarity_score(candidate, sections, story_items, planning_items)
        novelty = self._novelty_score(candidate, sections, topic_frequency)
        pacing = self._pacing_score(candidate)
        retention = self._retention_score(
            candidate,
            hook=hook,
            payoff=payoff,
            emotional=emotional,
            pacing=pacing,
            virality=virality,
        )
        repetition = self._repetition_penalty(candidate, sections, topic_frequency)
        rights = self._rights_penalty(candidate, source_context)
        memory_alignment = self._memory_alignment(candidate, memory)
        return _ScoredCandidate(
            candidate=candidate,
            hook=hook,
            payoff=payoff,
            standalone=standalone,
            emotional=emotional,
            clarity=clarity,
            novelty=novelty,
            pacing=pacing,
            retention=retention,
            context_risk=context,
            repetition=repetition,
            rights=rights,
            memory=memory_alignment,
        )

    @staticmethod
    def _overlapping(values: list[Any], start: float, end: float) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for value in values:
            item = _dict(value)
            item_start, item_end = _range(item)
            if item_end > item_start and _overlap_seconds(
                start, end, item_start, item_end
            ) > 0.0:
                result.append(item)
        return result

    @staticmethod
    def _payoff_links(
        understanding: dict[str, Any], start: float, end: float
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for value in _list(understanding.get("context_payoff_map")):
            item = _dict(value)
            context_start = _number(item.get("context_start_seconds"))
            payoff_end = _number(item.get("payoff_end_seconds"))
            if _overlap_seconds(start, end, context_start, payoff_end) > 0.0:
                result.append(item)
        return result

    @staticmethod
    def _planning_matches(
        planning: dict[str, Any], start: float, end: float
    ) -> list[dict[str, Any]]:
        values: list[Any] = []
        for key in ("selected_plans", "planning_candidates", "plans", "candidates"):
            values.extend(_list(planning.get(key)))
        return BobaClipRankingEngine._overlapping(values, start, end)

    @staticmethod
    def _virality_text(virality: dict[str, Any]) -> str:
        values: list[str] = []
        for key in (
            "why_this_can_work",
            "why_this_clip_works",
            "summary",
            "story_reasoning",
        ):
            values.append(_text(virality.get(key), maximum=400))
        for key in ("recommendations", "strengths", "evidence", "editorial_moments"):
            for value in _list(virality.get(key)):
                item = _dict(value)
                values.append(
                    _text(
                        item.get("reason")
                        or item.get("detail")
                        or item.get("title"),
                        maximum=260,
                    )
                )
        return " ".join(value for value in values if value).casefold()

    @staticmethod
    def _hook_score(candidate: BobaCandidateClipV1, virality_text: str) -> float:
        text = f"{candidate.hook_idea} {' '.join(candidate.virality_cues)}".casefold()
        score = 38.0
        if candidate.candidate_type in {"hook_moment", "curiosity_gap"}:
            score += 24.0
        score += min(24.0, 6.0 * sum(cue in text for cue in _STRONG_HOOK_CUES))
        if 4 <= len(candidate.hook_idea.split()) <= 28:
            score += 10.0
        if any(cue in virality_text for cue in ("hook", "curiosity", "open loop")):
            score += 8.0
        if candidate.boundary_suggestion.abrupt_start_warning:
            score -= 24.0
        return _points(score)

    @staticmethod
    def _payoff_score(
        candidate: BobaCandidateClipV1,
        links: list[dict[str, Any]],
        story_items: list[dict[str, Any]],
    ) -> float:
        score = 78.0 if candidate.payoff_present else 28.0
        if candidate.candidate_type == "payoff_moment":
            score += 12.0
        for link in links:
            payoff_end = _number(link.get("payoff_end_seconds"))
            if candidate.end_seconds + 0.05 >= payoff_end:
                score = max(score, 72.0 + 20.0 * _unit(link.get("confidence"), 0.5))
        for item in story_items:
            payoff = _dict(item.get("payoff") or item.get("payoff_analysis"))
            if payoff.get("payoff_present"):
                score = max(score, 70.0 + 25.0 * _unit(payoff.get("payoff_strength")))
        if candidate.boundary_suggestion.abrupt_end_warning:
            score -= 18.0
        return _points(score)

    @staticmethod
    def _standalone_context_scores(
        candidate: BobaCandidateClipV1, links: list[dict[str, Any]]
    ) -> tuple[float, float]:
        standalone = 100.0 * candidate.standalone_score
        context = 15.0
        if candidate.setup_required:
            context += 28.0
            standalone -= 12.0
        if candidate.context_needed:
            context += 30.0
            standalone -= 18.0
        for link in links:
            if not link.get("setup_required"):
                continue
            context_start = _number(link.get("context_start_seconds"))
            payoff_end = _number(link.get("payoff_end_seconds"))
            includes_setup = (
                candidate.start_seconds <= context_start + 0.5
                and candidate.end_seconds + 0.05 >= payoff_end
            )
            if includes_setup:
                context -= 28.0
                standalone += 14.0
            else:
                context += 18.0
        return _points(standalone), _points(context)

    @staticmethod
    def _emotional_score(
        candidate: BobaCandidateClipV1, emotions: list[dict[str, Any]]
    ) -> float:
        text = f"{candidate.emotion_label} {candidate.story_angle}".casefold()
        score = 35.0 if candidate.emotion_label == "unknown" else 58.0
        if candidate.candidate_type in {
            "emotional_beat",
            "motivational_moment",
            "funny_moment",
            "controversial_moment",
        }:
            score += 16.0
        if any(cue in text for cue in _EMOTIONAL_CUES):
            score += 12.0
        if emotions:
            score = max(
                score,
                45.0 + 50.0 * max(_unit(item.get("intensity")) for item in emotions),
            )
        return _points(score)

    @staticmethod
    def _clarity_score(
        candidate: BobaCandidateClipV1,
        sections: list[dict[str, Any]],
        story_items: list[dict[str, Any]],
        planning_items: list[dict[str, Any]],
    ) -> float:
        score = 56.0
        if candidate.source_topic != "unknown":
            score += 10.0
        if len(candidate.story_angle.split()) >= 5:
            score += 10.0
        if sections:
            score = max(
                score,
                100.0 * max(_unit(item.get("clarity_score"), 0.5) for item in sections),
            )
        if story_items:
            score += 6.0 * max(
                _unit(item.get("completeness_score"), 0.5) for item in story_items
            )
        if planning_items:
            score += 5.0
        score -= min(24.0, 5.0 * len(candidate.warnings))
        if candidate.context_needed:
            score -= 14.0
        return _points(score)

    @staticmethod
    def _novelty_score(
        candidate: BobaCandidateClipV1,
        sections: list[dict[str, Any]],
        topic_frequency: Counter[str],
    ) -> float:
        score = 52.0
        if sections:
            score = max(
                score,
                100.0 * max(_unit(item.get("novelty_score"), 0.5) for item in sections),
            )
        if topic_frequency[candidate.source_topic] == 1:
            score += 12.0
        elif topic_frequency[candidate.source_topic] >= 3:
            score -= 10.0
        if candidate.candidate_type in {
            "curiosity_gap",
            "controversial_moment",
            "story_turn",
        }:
            score += 8.0
        return _points(score)

    @staticmethod
    def _pacing_score(candidate: BobaCandidateClipV1) -> float:
        duration = candidate.duration_seconds
        if 25.0 <= duration <= 45.0:
            score = 92.0
        elif 18.0 <= duration < 25.0:
            score = 72.0 + (duration - 18.0) * 2.5
        elif 45.0 < duration <= 60.0:
            score = 92.0 - (duration - 45.0) * 1.8
        elif duration < 18.0:
            score = 48.0 + max(0.0, duration - 12.0) * 4.0
        else:
            score = max(35.0, 65.0 - (duration - 60.0))
        if candidate.candidate_type == "high_energy_section":
            score += 6.0
        if "analysis_signals_v2_audio_energy" in candidate.evidence.source_signals:
            score += 6.0
        return _points(score)

    @staticmethod
    def _retention_score(
        candidate: BobaCandidateClipV1,
        *,
        hook: float,
        payoff: float,
        emotional: float,
        pacing: float,
        virality: dict[str, Any],
    ) -> float:
        score = 0.34 * hook + 0.28 * payoff + 0.2 * emotional + 0.18 * pacing
        category_scores = _list(virality.get("category_scores"))
        for value in category_scores:
            item = _dict(value)
            category = _text(item.get("category") or item.get("label"), maximum=80)
            if "retention" in category.casefold():
                score = max(score, 100.0 * _unit(item.get("score")))
        if candidate.context_needed:
            score -= 8.0
        return _points(score)

    @staticmethod
    def _repetition_penalty(
        candidate: BobaCandidateClipV1,
        sections: list[dict[str, Any]],
        topic_frequency: Counter[str],
    ) -> float:
        penalty = 0.0
        if sections:
            penalty = max(
                100.0
                * max(
                    _unit(item.get("repetition_score")) for item in sections
                ),
                70.0 * max(_unit(item.get("filler_score")) for item in sections),
            )
        frequency = topic_frequency[candidate.source_topic]
        if candidate.source_topic != "unknown" and frequency > 2:
            penalty += min(25.0, (frequency - 2) * 8.0)
        return _points(penalty)

    @staticmethod
    def _rights_penalty(
        candidate: BobaCandidateClipV1, source_context: dict[str, Any]
    ) -> float:
        source_type = _text(source_context.get("source_type"), maximum=80).casefold()
        rights = _text(source_context.get("rights_status"), maximum=80).casefold()
        source_signals = " ".join(candidate.evidence.source_signals).casefold()
        external = bool(source_context.get("external_source")) or source_type in {
            "external",
            "youtube",
            "link",
            "scout",
        }
        external = external or "scout" in source_signals or "external" in source_signals
        if rights in {"denied", "not_authorized", "rejected"}:
            return 100.0
        if external and rights not in _CONFIRMED_RIGHTS:
            return 58.0
        return 0.0

    @staticmethod
    def _memory_alignment(
        candidate: BobaCandidateClipV1, memory: dict[str, Any]
    ) -> float:
        if not memory:
            return 50.0
        values: list[str] = []
        for key in ("source_summary", "summary", "preferred_patterns"):
            value = memory.get(key)
            if isinstance(value, str):
                values.append(value)
            else:
                values.extend(_text(item, maximum=180) for item in _list(value))
        for value in _list(memory.get("memory_records")):
            item = _dict(value)
            values.append(_text(item.get("summary"), maximum=180))
            values.extend(_text(entry, maximum=180) for entry in _list(item.get("evidence")))
        memory_text = " ".join(values).casefold()
        candidate_text = (
            f"{candidate.candidate_type} {candidate.emotion_label} "
            f"{candidate.hook_idea} {candidate.story_angle}"
        ).casefold()
        score = 50.0
        positive = any(term in memory_text for term in ("like", "prefer", "approve", "more"))
        negative = any(term in memory_text for term in ("reject", "avoid", "dislike", "less"))
        for trait in ("motiv", "emotion", "fast hook", "payoff", "curiosity", "funny"):
            if trait in memory_text and trait in candidate_text:
                score += 14.0 if positive else 7.0
            elif trait in memory_text and negative and trait in candidate_text:
                score -= 14.0
        if "reject" in memory_text and "low emotion" in memory_text:
            score += 10.0 if candidate.emotion_label != "unknown" else -14.0
        return _points(score)

    @staticmethod
    def _preliminary(item: _ScoredCandidate) -> float:
        return (
            0.15 * item.hook
            + 0.14 * item.payoff
            + 0.13 * item.standalone
            + 0.09 * item.emotional
            + 0.11 * item.clarity
            + 0.08 * item.novelty
            + 0.09 * item.pacing
            + 0.11 * item.retention
        ) / 0.9

    def _remove_duplicates(
        self, values: list[_ScoredCandidate]
    ) -> tuple[list[_ScoredCandidate], list[BobaRejectedRankCandidateV1]]:
        kept: list[_ScoredCandidate] = []
        rejected: list[BobaRejectedRankCandidateV1] = []
        for item in sorted(values, key=self._preliminary, reverse=True):
            duplicate = next(
                (
                    existing
                    for existing in kept
                    if existing.candidate.candidate_id == item.candidate.candidate_id
                    or (
                        abs(
                            existing.candidate.start_seconds
                            - item.candidate.start_seconds
                        )
                        <= 0.01
                        and abs(
                            existing.candidate.end_seconds - item.candidate.end_seconds
                        )
                        <= 0.01
                    )
                ),
                None,
            )
            if duplicate is None:
                kept.append(item)
                continue
            rejected.append(
                BobaRejectedRankCandidateV1(
                    candidate_id=item.candidate.candidate_id,
                    reason="Exact duplicate candidate removed before ranking.",
                    score=round(self._preliminary(item), 3),
                    overlap_with_candidate_id=duplicate.candidate.candidate_id,
                    warning="Duplicate promotion was prevented.",
                )
            )
        return kept, rejected

    def _apply_overlap_penalties(self, values: list[_ScoredCandidate]) -> None:
        ordered = sorted(values, key=self._preliminary, reverse=True)
        for index, item in enumerate(ordered):
            for stronger in ordered[:index]:
                ratio = _overlap_ratio(
                    item.candidate.start_seconds,
                    item.candidate.end_seconds,
                    stronger.candidate.start_seconds,
                    stronger.candidate.end_seconds,
                )
                if ratio < 0.5:
                    continue
                penalty = 70.0 * ratio if ratio > 0.8 else 42.0 * ratio
                if self._meaningfully_different(item.candidate, stronger.candidate):
                    penalty *= 0.55
                if penalty > item.overlap:
                    item.overlap = _points(penalty)
                    item.overlap_with = stronger.candidate.candidate_id

    @staticmethod
    def _meaningfully_different(
        left: BobaCandidateClipV1, right: BobaCandidateClipV1
    ) -> bool:
        return bool(
            left.source_topic != right.source_topic
            or left.emotion_label != right.emotion_label
            or left.candidate_type != right.candidate_type
            or left.payoff_present != right.payoff_present
        )

    @staticmethod
    def _final_score(item: _ScoredCandidate) -> float:
        score = BobaClipRankingEngine._preliminary(item)
        score += (item.memory - 50.0) * 0.04
        score -= 0.1 * item.context_risk
        score -= 0.07 * item.repetition
        score -= 0.1 * item.overlap
        score -= 0.08 * item.rights
        score *= 0.85 + 0.15 * item.candidate.confidence
        return round(_points(score), 3)

    @staticmethod
    def tier_for_score(
        score: float,
        *,
        hook_score: float = 0.0,
        payoff_present: bool = False,
        context_risk_score: float = 0.0,
        overlap_penalty: float = 0.0,
    ) -> BobaRankingTier:
        if overlap_penalty >= 80.0:
            return "reject"
        if score >= 85.0:
            if (payoff_present or hook_score >= 88.0) and context_risk_score < 45.0:
                return "must_make"
            return "strong_candidate"
        if score >= 70.0:
            return "strong_candidate"
        if score >= 55.0:
            return "backup_candidate"
        if score >= 40.0:
            return "needs_revision"
        return "reject"

    @staticmethod
    def _priority(
        tier: BobaRankingTier,
        *,
        context_risk: float,
        rights_penalty: float,
    ) -> BobaProductionPriority:
        if tier == "reject":
            return "do_not_produce"
        if tier == "needs_revision":
            return "low"
        if tier == "backup_candidate":
            return "medium"
        if tier == "must_make" and context_risk < 35.0 and rights_penalty < 50.0:
            return "immediate"
        return "high"

    def _ranked_clip(
        self, project_id: str, item: _ScoredCandidate, *, rank: int
    ) -> BobaRankedClipV1:
        candidate = item.candidate
        tier = self.tier_for_score(
            item.final,
            hook_score=item.hook,
            payoff_present=candidate.payoff_present,
            context_risk_score=item.context_risk,
            overlap_penalty=item.overlap,
        )
        reasons = self._reasons(item)
        risks = self._risks(item)
        improvements = self._improvements(item)
        return BobaRankedClipV1(
            candidate_id=candidate.candidate_id,
            project_id=project_id,
            rank=rank,
            tier=tier,
            total_score=item.final,
            confidence=round(
                _unit(candidate.confidence * (0.85 if risks else 1.0)), 3
            ),
            production_priority=self._priority(
                tier,
                context_risk=item.context_risk,
                rights_penalty=item.rights,
            ),
            score_breakdown=BobaClipScoreBreakdownV1(
                hook_score=round(item.hook, 3),
                payoff_score=round(item.payoff, 3),
                standalone_score=round(item.standalone, 3),
                emotional_score=round(item.emotional, 3),
                clarity_score=round(item.clarity, 3),
                novelty_score=round(item.novelty, 3),
                pacing_score=round(item.pacing, 3),
                retention_score=round(item.retention, 3),
                context_risk_score=round(item.context_risk, 3),
                repetition_penalty=round(item.repetition, 3),
                overlap_penalty=round(item.overlap, 3),
                rights_safety_penalty=round(item.rights, 3),
                memory_alignment_score=round(item.memory, 3),
                final_score=item.final,
            ),
            ranking_reasons=reasons,
            risk_warnings=risks,
            improvement_suggestions=improvements,
            source_window={
                "start_seconds": candidate.start_seconds,
                "end_seconds": candidate.end_seconds,
                "duration_seconds": candidate.duration_seconds,
            },
            candidate_type=candidate.candidate_type,
            suggested_title=candidate.suggested_title,
            hook_idea=candidate.hook_idea,
            story_angle=candidate.story_angle,
            source_topic=candidate.source_topic,
            emotion_label=candidate.emotion_label,
        )

    @staticmethod
    def _reasons(item: _ScoredCandidate) -> list[str]:
        components = {
            "Hook opens with a strong attention cue.": item.hook,
            "Payoff is present and protected by the candidate boundary.": item.payoff,
            "Candidate can stand alone with limited setup dependency.": item.standalone,
            "Emotional signal supports viewer interest.": item.emotional,
            "Story angle and topic are clear.": item.clarity,
            "Duration and energy fit a practical Short.": item.pacing,
            "Hook-to-payoff structure supports retention.": item.retention,
        }
        reasons = [reason for reason, score in components.items() if score >= 72.0]
        if not reasons:
            reasons.append("Candidate remains a lower-confidence editorial option.")
        return reasons[:20]

    @staticmethod
    def _risks(item: _ScoredCandidate) -> list[str]:
        risks = list(item.candidate.warnings)
        if item.context_risk >= 50.0:
            risks.append("High setup/context dependency may reduce standalone clarity.")
        if item.repetition >= 50.0:
            risks.append("Filler or repetition lowers extraction value.")
        if item.overlap >= 35.0:
            overlap_suffix = f" ({item.overlap_with})" if item.overlap_with else ""
            risks.append(
                f"Overlaps a stronger candidate{overlap_suffix}."
            )
        if item.rights >= 50.0:
            risks.append("External/scout source rights are not confirmed for production.")
        if not item.candidate.payoff_present:
            risks.append("No confirmed payoff is present.")
        return _unique(risks, limit=20, maximum=300)

    @staticmethod
    def _improvements(item: _ScoredCandidate) -> list[str]:
        values: list[str] = []
        if item.hook < 60.0:
            values.append("Strengthen or move the clearest hook into the opening seconds.")
        if item.payoff < 60.0:
            values.append("Extend the boundary to include a complete payoff if available.")
        if item.context_risk >= 50.0:
            values.append("Include compact setup or add a truthful context caption.")
        if item.pacing < 60.0:
            values.append("Review the suggested duration and remove nonessential pauses.")
        if item.repetition >= 50.0:
            values.append("Trim repeated or filler material before downstream planning.")
        if item.rights >= 50.0:
            values.append("Confirm ownership or permission before any production action.")
        return values[:20]

    def _recommend(
        self, ranked: list[BobaRankedClipV1]
    ) -> tuple[list[BobaRankedClipV1], list[str]]:
        eligible = [
            item
            for item in ranked
            if item.tier in {"must_make", "strong_candidate", "backup_candidate"}
        ]
        selected: list[BobaRankedClipV1] = []
        topics: set[str] = set()
        emotions: set[str] = set()
        candidate_types: set[str] = set()
        warnings: list[str] = []
        remaining = list(eligible)
        while remaining and len(selected) < self.maximum_recommendations:
            best = max(
                remaining,
                key=lambda item: (
                    item.total_score
                    + 4.0 * int(item.source_topic not in topics)
                    + 2.5 * int(item.emotion_label not in emotions)
                    + 3.0 * int(item.candidate_type not in candidate_types),
                    item.confidence,
                    -item.source_window["start_seconds"],
                ),
            )
            remaining.remove(best)
            severe_overlap = next(
                (
                    item
                    for item in selected
                    if _overlap_ratio(
                        best.source_window["start_seconds"],
                        best.source_window["end_seconds"],
                        item.source_window["start_seconds"],
                        item.source_window["end_seconds"],
                    )
                    > 0.8
                    and best.source_topic == item.source_topic
                    and best.candidate_type == item.candidate_type
                ),
                None,
            )
            if severe_overlap is not None:
                continue
            selected.append(best)
            topics.add(best.source_topic)
            emotions.add(best.emotion_label)
            candidate_types.add(best.candidate_type)
        score_order = [item.candidate_id for item in eligible]
        selected_order = [item.candidate_id for item in selected]
        if selected_order != score_order[: len(selected_order)]:
            warnings.append(
                "Recommendation order promoted a slightly lower-scoring candidate to "
                "preserve topic, emotion, or candidate-type diversity."
            )
        return selected, warnings

    @staticmethod
    def _diversity_summary(
        ranked: list[BobaRankedClipV1],
        recommended: list[BobaRankedClipV1],
        *,
        overlap_count: int,
        duplicate_count: int,
        warnings: list[str],
    ) -> BobaRankingDiversitySummaryV1:
        topics = {item.source_topic for item in recommended if item.source_topic != "unknown"}
        emotions = {
            item.emotion_label for item in recommended if item.emotion_label != "unknown"
        }
        candidate_types = {item.candidate_type for item in recommended}
        diversity_warnings = list(warnings)
        if len(recommended) >= 3 and len(topics) <= 1:
            diversity_warnings.append("Top recommendations have limited topic diversity.")
        if len(recommended) >= 3 and len(candidate_types) <= 1:
            diversity_warnings.append("Top recommendations have limited candidate-type diversity.")
        return BobaRankingDiversitySummaryV1(
            ranked_count=len(ranked),
            recommended_count=len(recommended),
            topic_count=len(topics),
            emotion_count=len(emotions),
            candidate_type_count=len(candidate_types),
            overlap_penalties_applied=overlap_count,
            duplicate_candidates_removed=duplicate_count,
            diversity_warnings=_unique(diversity_warnings, limit=24, maximum=300),
        )

    @staticmethod
    def _signal_usage(
        *,
        understanding: dict[str, Any],
        virality: dict[str, Any],
        story: dict[str, Any],
        planning: dict[str, Any],
        memory: dict[str, Any],
    ) -> BobaRankingSignalUsageV1:
        availability = {
            "whole_video_understanding": bool(understanding),
            "virality_v2": bool(virality),
            "story_analysis_v2": bool(story),
            "planning_v2": bool(planning),
            "boba_memory": bool(memory),
        }
        unavailable = [name for name, available in availability.items() if not available]
        warnings: list[str] = []
        if unavailable:
            warnings.append(
                "Ranking used deterministic fallback scores for unavailable optional signals: "
                + ", ".join(unavailable)
                + "."
            )
        return BobaRankingSignalUsageV1(
            candidate_discovery_used=True,
            whole_video_understanding_used=bool(understanding),
            virality_used=bool(virality),
            story_used=bool(story),
            planning_used=bool(planning),
            memory_used=bool(memory),
            fallback_used=bool(unavailable),
            unavailable_signals=unavailable,
            warnings=warnings,
        )

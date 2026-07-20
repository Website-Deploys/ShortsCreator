"""Deterministic, evidence-bound explanations over saved BOBA artifacts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field

from olympus.boba.clip_discovery import (
    BobaCandidateClipDiscoveryV1,
    BobaCandidateClipV1,
)
from olympus.boba.clip_ranking import (
    BobaClipRankingV1,
    BobaRankedClipV1,
    BobaRejectedRankCandidateV1,
)
from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.creative_director import BobaCreativeBriefV1
from olympus.boba.editorial_decision import (
    BobaEditorialDecisionSetV1,
    BobaEditorialDecisionV1,
)
from olympus.boba.memory_contracts import BobaProjectMemoryV1
from olympus.boba.whole_video import BobaWholeVideoUnderstandingV1
from olympus.platform.errors import ValidationError

BobaExplanationType = Literal[
    "discovery",
    "ranking",
    "editorial",
    "render_readiness",
    "rejection",
    "project_summary",
]
BobaEvidenceType = Literal[
    "transcript_snippet",
    "score",
    "signal",
    "warning",
    "memory_lesson",
    "context_payoff",
    "emotional_beat",
    "ranking_factor",
    "editorial_risk",
]
BobaUncertaintyLevel = Literal["low", "medium", "high"]

ModelT = TypeVar("ModelT", bound=BaseModel)


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: Any, *, maximum: int = 300) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if len(normalized) <= maximum:
        return normalized
    return normalized[: max(0, maximum - 3)].rstrip() + "..."


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
    number = _number(value, default)
    if 1.0 < number <= 100.0:
        number /= 100.0
    return round(max(0.0, min(1.0, number)), 3)


def _unique(values: Sequence[str], *, limit: int, maximum: int = 400) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _text(value, maximum=maximum)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _model(
    value: ModelT | Mapping[str, Any] | None,
    model: type[ModelT],
    *,
    label: str,
    project_id: str,
) -> ModelT | None:
    if value is None or not _dict(value):
        return None
    try:
        return value if isinstance(value, model) else model.model_validate(value)
    except ValueError as exc:
        raise ValidationError(
            f"BOBA {label} artifact is invalid.",
            details={"project_id": project_id, "artifact": label},
        ) from exc


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


class BobaExplanationEvidenceV1(BobaContract):
    evidence_type: BobaEvidenceType
    source_artifact: str = Field(min_length=1, max_length=80)
    source_field: str = Field(min_length=1, max_length=160)
    snippet: str = Field(min_length=1, max_length=300)
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    timestamp_seconds: float | None = Field(default=None, ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)


class BobaClipExplanationV1(BobaContract):
    clip_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    explanation_type: BobaExplanationType
    short_summary: str = Field(min_length=1, max_length=400)
    detailed_explanation: str = Field(min_length=1, max_length=1200)
    key_reasons: list[str] = Field(default_factory=list, max_length=24)
    evidence: list[BobaExplanationEvidenceV1] = Field(default_factory=list, max_length=40)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaProjectExplanationV1(BobaContract):
    overall_summary: str = Field(min_length=1, max_length=1200)
    top_recommendation_reason: str = Field(min_length=1, max_length=800)
    strongest_clip_types: list[str] = Field(default_factory=list, max_length=16)
    weakest_clip_types: list[str] = Field(default_factory=list, max_length=16)
    unavailable_signals: list[str] = Field(default_factory=list, max_length=48)
    main_uncertainties: list[str] = Field(default_factory=list, max_length=32)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)


class BobaSignalExplanationV1(BobaContract):
    signals_used: list[str] = Field(default_factory=list, max_length=48)
    signals_missing: list[str] = Field(default_factory=list, max_length=48)
    fallback_signals: list[str] = Field(default_factory=list, max_length=32)
    how_signals_affected_decisions: list[str] = Field(default_factory=list, max_length=48)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaUncertaintySummaryV1(BobaContract):
    uncertainty_level: BobaUncertaintyLevel
    reasons: list[str] = Field(default_factory=list, max_length=32)
    missing_evidence: list[str] = Field(default_factory=list, max_length=48)
    recommended_human_checks: list[str] = Field(default_factory=list, max_length=32)


class BobaExplanationSetV1(BobaContract):
    schema_version: Literal["boba_explanation_engine_v1"] = "boba_explanation_engine_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    project_summary: BobaProjectExplanationV1
    candidate_explanations: list[BobaClipExplanationV1] = Field(
        default_factory=list, max_length=100
    )
    ranking_explanations: list[BobaClipExplanationV1] = Field(
        default_factory=list, max_length=200
    )
    editorial_explanations: list[BobaClipExplanationV1] = Field(
        default_factory=list, max_length=200
    )
    signal_explanation: BobaSignalExplanationV1
    uncertainty_summary: BobaUncertaintySummaryV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaExplanationEngine:
    """Explain saved BOBA evidence without inferring facts outside its artifacts."""

    def explain(
        self,
        *,
        project_id: str,
        whole_video_understanding: (
            BobaWholeVideoUnderstandingV1 | Mapping[str, Any] | None
        ) = None,
        candidate_discovery: (
            BobaCandidateClipDiscoveryV1 | Mapping[str, Any] | None
        ) = None,
        clip_ranking: BobaClipRankingV1 | Mapping[str, Any] | None = None,
        editorial_decisions: (
            BobaEditorialDecisionSetV1 | Mapping[str, Any] | None
        ) = None,
        creative_briefs: Sequence[BobaCreativeBriefV1 | Mapping[str, Any]] | None = None,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
        analysis_signal_health: Mapping[str, Any] | None = None,
        source_context: Mapping[str, Any] | None = None,
    ) -> BobaExplanationSetV1:
        understanding = _model(
            whole_video_understanding,
            BobaWholeVideoUnderstandingV1,
            label="whole-video understanding",
            project_id=project_id,
        )
        discovery = _model(
            candidate_discovery,
            BobaCandidateClipDiscoveryV1,
            label="candidate discovery",
            project_id=project_id,
        )
        ranking = _model(
            clip_ranking,
            BobaClipRankingV1,
            label="clip ranking",
            project_id=project_id,
        )
        decisions = _model(
            editorial_decisions,
            BobaEditorialDecisionSetV1,
            label="editorial decision",
            project_id=project_id,
        )
        briefs = self._briefs(creative_briefs, project_id)
        memory_data = _dict(memory)
        analysis = _dict(analysis_signal_health)
        source = _dict(source_context)
        signal_explanation = self._signal_explanation(
            understanding=understanding,
            discovery=discovery,
            ranking=ranking,
            decisions=decisions,
            briefs=briefs,
            memory=memory_data,
            analysis=analysis,
        )
        candidate_explanations = self._discovery_explanations(
            discovery,
            understanding=understanding,
        )
        ranking_explanations = self._ranking_explanations(ranking)
        editorial_explanations = self._editorial_explanations(
            decisions,
            briefs=briefs,
        )
        uncertainty = self._uncertainty_summary(
            understanding=understanding,
            discovery=discovery,
            ranking=ranking,
            decisions=decisions,
            analysis=analysis,
            signal_explanation=signal_explanation,
            explanations=[
                *candidate_explanations,
                *ranking_explanations,
                *editorial_explanations,
            ],
        )
        project_summary = self._project_summary(
            understanding=understanding,
            discovery=discovery,
            ranking=ranking,
            decisions=decisions,
            signal_explanation=signal_explanation,
            uncertainty=uncertainty,
        )
        artifact_warnings = self._artifact_text(
            understanding,
            discovery,
            ranking,
            decisions,
            field="warnings",
            limit=64,
        )
        artifact_limitations = self._artifact_text(
            understanding,
            discovery,
            ranking,
            decisions,
            field="limitations",
            limit=24,
        )
        missing_artifacts = [
            f"{name} was unavailable; its claims were not explained."
            for name, value in (
                ("Whole Video Understanding", understanding),
                ("Candidate Clip Discovery", discovery),
                ("Clip Ranking", ranking),
                ("Editorial Decisions", decisions),
            )
            if value is None
        ]
        source_id = next(
            (
                item.source_id
                for item in (decisions, ranking, discovery, understanding)
                if item is not None and item.source_id
            ),
            _text(source.get("source_id") or source.get("storage_key"), maximum=512),
        )
        return BobaExplanationSetV1(
            project_id=project_id,
            source_id=source_id,
            project_summary=project_summary,
            candidate_explanations=candidate_explanations,
            ranking_explanations=ranking_explanations,
            editorial_explanations=editorial_explanations,
            signal_explanation=signal_explanation,
            uncertainty_summary=uncertainty,
            warnings=_unique(
                [*artifact_warnings, *signal_explanation.warnings],
                limit=64,
            ),
            limitations=_unique(
                [
                    *missing_artifacts,
                    *artifact_limitations,
                    "V1 explains saved metadata only; it does not inspect or render media.",
                    "Explanations do not establish copyright safety or predict audience results.",
                    "Human review remains required for meaning, rights, and production choices.",
                ],
                limit=32,
            ),
        )

    def explain_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        whole_video_understanding: (
            BobaWholeVideoUnderstandingV1 | Mapping[str, Any] | None
        ) = None,
        candidate_discovery: (
            BobaCandidateClipDiscoveryV1 | Mapping[str, Any] | None
        ) = None,
        clip_ranking: BobaClipRankingV1 | Mapping[str, Any] | None = None,
        editorial_decisions: (
            BobaEditorialDecisionSetV1 | Mapping[str, Any] | None
        ) = None,
        creative_briefs: Sequence[BobaCreativeBriefV1 | Mapping[str, Any]] | None = None,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
    ) -> BobaExplanationSetV1:
        project = _dict(signals.get("project"))
        analysis = {
            "analysis_signals_v2": _dict(signals.get("analysis_signals_v2")),
            "transcript_available": bool(signals.get("transcript_available")),
            "face_signals_available": bool(signals.get("face_signals_available")),
            "speaker_signals_available": bool(signals.get("speaker_signals_available")),
            "visual_signals_available": bool(signals.get("visual_signals_available")),
        }
        return self.explain(
            project_id=project_id,
            whole_video_understanding=(
                whole_video_understanding or _dict(signals.get("whole_video_understanding"))
            ),
            candidate_discovery=(
                candidate_discovery or _dict(signals.get("candidate_clip_discovery"))
            ),
            clip_ranking=clip_ranking or _dict(signals.get("clip_ranking")),
            editorial_decisions=(
                editorial_decisions or _dict(signals.get("editorial_decisions"))
            ),
            creative_briefs=creative_briefs,
            memory=memory,
            analysis_signal_health=analysis,
            source_context={
                "source_id": project.get("storage_key") or signals.get("storage_key"),
                "source_type": signals.get("source_type") or project.get("source_type"),
            },
        )

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

    def _discovery_explanations(
        self,
        discovery: BobaCandidateClipDiscoveryV1 | None,
        *,
        understanding: BobaWholeVideoUnderstandingV1 | None,
    ) -> list[BobaClipExplanationV1]:
        if discovery is None:
            return []
        return [
            self._discovery_explanation(candidate, understanding=understanding)
            for candidate in discovery.candidates
        ]

    def _discovery_explanation(
        self,
        candidate: BobaCandidateClipV1,
        *,
        understanding: BobaWholeVideoUnderstandingV1 | None,
    ) -> BobaClipExplanationV1:
        evidence: list[BobaExplanationEvidenceV1] = [
            self._evidence(
                "signal",
                "candidate_clip_discovery",
                "candidates[].discovery_reason",
                candidate.discovery_reason,
                timestamp=candidate.start_seconds,
                confidence=candidate.confidence,
            )
        ]
        for snippet in candidate.evidence.transcript_snippets[:3]:
            evidence.append(
                self._evidence(
                    "transcript_snippet",
                    "candidate_clip_discovery",
                    "candidates[].evidence.transcript_snippets",
                    snippet,
                    timestamp=candidate.start_seconds,
                    confidence=candidate.confidence,
                )
            )
        for signal in candidate.evidence.source_signals[:8]:
            evidence.append(
                self._evidence(
                    "signal",
                    "candidate_clip_discovery",
                    "candidates[].evidence.source_signals",
                    signal,
                    timestamp=candidate.start_seconds,
                    confidence=candidate.confidence,
                )
            )
        evidence.extend(
            [
                self._evidence(
                    "score",
                    "candidate_clip_discovery",
                    "candidates[].standalone_score",
                    f"Standalone score {candidate.standalone_score * 100:.1f}/100",
                    score=candidate.standalone_score * 100,
                    timestamp=candidate.start_seconds,
                    confidence=candidate.confidence,
                ),
                self._evidence(
                    "signal",
                    "candidate_clip_discovery",
                    "candidates[].boundary_suggestion.reason",
                    candidate.boundary_suggestion.reason,
                    timestamp=candidate.boundary_suggestion.recommended_start_seconds,
                    confidence=candidate.confidence,
                ),
            ]
        )
        context_reasons: list[str] = []
        if understanding is not None:
            links = {
                item.link_id: item for item in understanding.context_payoff_map
            }
            for link_id in candidate.evidence.context_payoff_link_ids[:6]:
                link = links.get(link_id)
                if link is None:
                    continue
                context_reasons.append(link.description)
                evidence.append(
                    self._evidence(
                        "context_payoff",
                        "whole_video_understanding",
                        "context_payoff_map",
                        link.description,
                        timestamp=link.payoff_start_seconds,
                        confidence=link.confidence,
                    )
                )
            beats = {item.beat_id: item for item in understanding.emotional_beats}
            for beat_id in candidate.evidence.emotional_beat_ids[:6]:
                beat = beats.get(beat_id)
                if beat is None:
                    continue
                evidence.append(
                    self._evidence(
                        "emotional_beat",
                        "whole_video_understanding",
                        "emotional_beats",
                        f"{beat.emotion_label}: {beat.reason}",
                        score=beat.intensity * 100,
                        timestamp=beat.start_seconds,
                        confidence=beat.confidence,
                    )
                )
            for hint in understanding.shortability_hints:
                if not _overlaps(
                    hint.model_dump(mode="json"),
                    candidate.start_seconds,
                    candidate.end_seconds,
                ):
                    continue
                evidence.append(
                    self._evidence(
                        "signal",
                        "whole_video_understanding",
                        "shortability_hints",
                        hint.reason,
                        score=hint.hook_potential * 100,
                        timestamp=hint.start_seconds,
                        confidence=candidate.confidence,
                    )
                )
                break
        warnings = list(candidate.warnings)
        if candidate.boundary_suggestion.abrupt_start_warning:
            warnings.append("The suggested window may start abruptly.")
        if candidate.boundary_suggestion.abrupt_end_warning:
            warnings.append("The suggested window may end abruptly.")
        limitations: list[str] = []
        if not candidate.evidence.transcript_snippets:
            limitations.append(
                "No bounded transcript snippet supported this discovery explanation."
            )
        if understanding is None:
            limitations.append(
                "Whole Video Understanding was unavailable for context/payoff checks."
            )
        key_reasons = [
            candidate.discovery_reason,
            f"Candidate type: {candidate.candidate_type.replace('_', ' ')}.",
            (
                "A payoff is marked present in the discovery artifact."
                if candidate.payoff_present
                else "The discovery artifact does not confirm a payoff."
            ),
            candidate.boundary_suggestion.reason,
            *context_reasons,
        ]
        short_summary = (
            f"BOBA noticed {candidate.suggested_title} because "
            f"{_text(candidate.discovery_reason, maximum=240)}"
        )
        detail = (
            f"The saved discovery artifact suggests {candidate.start_seconds:.2f}s to "
            f"{candidate.end_seconds:.2f}s as a {candidate.candidate_type.replace('_', ' ')}. "
            f"Its stated reason is: {candidate.discovery_reason} The boundary reason is: "
            f"{candidate.boundary_suggestion.reason} Payoff present is "
            f"{str(candidate.payoff_present).lower()}, setup required is "
            f"{str(candidate.setup_required).lower()}, and context needed is "
            f"{str(candidate.context_needed).lower()}."
        )
        return BobaClipExplanationV1(
            clip_id=candidate.candidate_id,
            candidate_id=candidate.candidate_id,
            explanation_type="discovery",
            short_summary=_text(short_summary, maximum=400),
            detailed_explanation=_text(detail, maximum=1200),
            key_reasons=_unique(key_reasons, limit=24),
            evidence=self._dedupe_evidence(evidence),
            confidence=candidate.confidence,
            warnings=_unique(warnings, limit=32),
            limitations=_unique(limitations, limit=24),
        )

    def _ranking_explanations(
        self,
        ranking: BobaClipRankingV1 | None,
    ) -> list[BobaClipExplanationV1]:
        if ranking is None:
            return []
        diversity = ranking.diversity_summary.model_dump(mode="json")
        result = [
            self._ranking_explanation(
                item,
                total=len(ranking.ranked_candidates),
                diversity=diversity,
            )
            for item in ranking.ranked_candidates
        ]
        ranked_ids = {item.candidate_id for item in ranking.ranked_candidates}
        result.extend(
            self._ranking_rejection_explanation(item)
            for item in ranking.rejected_candidates
            if item.candidate_id not in ranked_ids
        )
        return result

    def _ranking_explanation(
        self,
        ranked: BobaRankedClipV1,
        *,
        total: int,
        diversity: Mapping[str, Any],
    ) -> BobaClipExplanationV1:
        breakdown = ranked.score_breakdown.model_dump(mode="json")
        positive_fields = (
            "hook_score",
            "payoff_score",
            "standalone_score",
            "emotional_score",
            "clarity_score",
            "novelty_score",
            "pacing_score",
            "retention_score",
        )
        penalty_fields = (
            "context_risk_score",
            "repetition_penalty",
            "overlap_penalty",
            "rights_safety_penalty",
        )
        positive = sorted(
            ((field, _number(breakdown.get(field))) for field in positive_fields),
            key=lambda item: item[1],
            reverse=True,
        )
        penalties = sorted(
            ((field, _number(breakdown.get(field))) for field in penalty_fields),
            key=lambda item: item[1],
            reverse=True,
        )
        strongest = positive[:3]
        weakest = sorted(positive, key=lambda item: item[1])[:2]
        evidence = [
            self._evidence(
                "score",
                "clip_ranking",
                "ranked_candidates[].total_score",
                f"Total score {ranked.total_score:.1f}/100 at rank {ranked.rank} of {total}",
                score=ranked.total_score,
                timestamp=ranked.source_window.get("start_seconds"),
                confidence=ranked.confidence,
            )
        ]
        evidence.extend(
            self._evidence(
                "ranking_factor",
                "clip_ranking",
                f"ranked_candidates[].score_breakdown.{field}",
                f"{field.replace('_', ' ')}: {score:.1f}/100",
                score=score,
                timestamp=ranked.source_window.get("start_seconds"),
                confidence=ranked.confidence,
            )
            for field, score in [*strongest, *weakest, *penalties[:2]]
        )
        if ranked.score_breakdown.memory_alignment_score > 0.0:
            evidence.append(
                self._evidence(
                    "memory_lesson",
                    "clip_ranking",
                    "score_breakdown.memory_alignment_score",
                    (
                        "Bounded memory alignment score: "
                        f"{ranked.score_breakdown.memory_alignment_score:.1f}/100"
                    ),
                    score=ranked.score_breakdown.memory_alignment_score,
                    timestamp=ranked.source_window.get("start_seconds"),
                    confidence=ranked.confidence,
                )
            )
        warnings = list(ranked.risk_warnings)
        if ranked.score_breakdown.overlap_penalty > 0.0:
            warnings.append(
                "The ranking artifact applied an overlap penalty, so diversity affected this score."
            )
        if ranked.score_breakdown.repetition_penalty > 0.0:
            warnings.append("The ranking artifact applied a repetition penalty.")
        overlap_penalties = int(_number(diversity.get("overlap_penalties_applied")))
        duplicates_removed = int(_number(diversity.get("duplicate_candidates_removed")))
        diversity_text = (
            f"The ranking diversity summary reports {overlap_penalties} overlap penalty(s) "
            f"and {duplicates_removed} duplicate candidate(s) removed."
        )
        evidence.append(
            self._evidence(
                "ranking_factor",
                "clip_ranking",
                "diversity_summary",
                diversity_text,
                timestamp=ranked.source_window.get("start_seconds"),
                confidence=ranked.confidence,
            )
        )
        if overlap_penalties or duplicates_removed:
            warnings.append("Global ranking diversity controls affected the candidate set.")
        strongest_text = ", ".join(
            f"{field.replace('_', ' ')} {score:.1f}" for field, score in strongest
        )
        weakest_text = ", ".join(
            f"{field.replace('_', ' ')} {score:.1f}" for field, score in weakest
        )
        penalty_text = ", ".join(
            f"{field.replace('_', ' ')} {score:.1f}" for field, score in penalties if score > 0
        ) or "no non-zero saved penalties"
        explanation_type: BobaExplanationType = (
            "rejection" if ranked.tier == "reject" else "ranking"
        )
        short_summary = (
            f"{ranked.suggested_title} ranked #{ranked.rank} with "
            f"{ranked.total_score:.1f}/100 in the {ranked.tier.replace('_', ' ')} tier."
        )
        detail = (
            f"The saved ranking places this candidate at rank {ranked.rank} of {total}. "
            f"Its strongest saved factors are {strongest_text}; its weakest positive factors are "
            f"{weakest_text}. Saved penalties are {penalty_text}. BOBA reports these ranking "
            f"fields as the basis of the order. {diversity_text} This explanation does not infer "
            "audience behavior."
        )
        key_reasons = [
            *ranked.ranking_reasons,
            f"Ranking tier: {ranked.tier.replace('_', ' ')}.",
            f"Strongest factors: {strongest_text}.",
            f"Weakest factors: {weakest_text}.",
            diversity_text,
        ]
        if ranked.score_breakdown.memory_alignment_score > 0.0:
            key_reasons.append(
                "A bounded memory-alignment factor was present; it is advisory rather than proof."
            )
        return BobaClipExplanationV1(
            clip_id=ranked.candidate_id,
            candidate_id=ranked.candidate_id,
            explanation_type=explanation_type,
            short_summary=short_summary,
            detailed_explanation=_text(detail, maximum=1200),
            key_reasons=_unique(key_reasons, limit=24),
            evidence=self._dedupe_evidence(evidence),
            confidence=ranked.confidence,
            warnings=_unique(warnings, limit=32),
            limitations=_unique(ranked.improvement_suggestions, limit=24),
        )

    def _ranking_rejection_explanation(
        self,
        rejected: BobaRejectedRankCandidateV1,
    ) -> BobaClipExplanationV1:
        evidence = [
            self._evidence(
                "warning",
                "clip_ranking",
                "rejected_candidates[].reason",
                rejected.reason,
                score=rejected.score,
                confidence=0.8,
            )
        ]
        if rejected.overlap_with_candidate_id:
            evidence.append(
                self._evidence(
                    "ranking_factor",
                    "clip_ranking",
                    "rejected_candidates[].overlap_with_candidate_id",
                    f"Overlaps stronger candidate {rejected.overlap_with_candidate_id}",
                    confidence=0.8,
                )
            )
        return BobaClipExplanationV1(
            clip_id=rejected.candidate_id,
            candidate_id=rejected.candidate_id,
            explanation_type="rejection",
            short_summary=_text(
                f"BOBA ranking rejected this candidate because {rejected.reason}",
                maximum=400,
            ),
            detailed_explanation=_text(
                f"The saved ranking artifact records a rejection score of {rejected.score:.1f}/100 "
                f"and the reason: {rejected.reason} No additional rejection cause is inferred.",
                maximum=1200,
            ),
            key_reasons=[rejected.reason],
            evidence=evidence,
            confidence=0.8,
            warnings=[rejected.warning] if rejected.warning else [],
            limitations=["No editorial decision exists for this ranking-only rejection."],
        )

    def _editorial_explanations(
        self,
        decisions: BobaEditorialDecisionSetV1 | None,
        *,
        briefs: list[BobaCreativeBriefV1],
    ) -> list[BobaClipExplanationV1]:
        if decisions is None:
            return []
        brief_by_id = {item.clip_id: item for item in briefs}
        result: list[BobaClipExplanationV1] = []
        for decision in decisions.decisions:
            result.append(
                self._editorial_explanation(
                    decision,
                    brief=brief_by_id.get(decision.candidate_id),
                )
            )
            result.append(self._readiness_explanation(decision))
        return result

    def _editorial_explanation(
        self,
        decision: BobaEditorialDecisionV1,
        *,
        brief: BobaCreativeBriefV1 | None,
    ) -> BobaClipExplanationV1:
        explanation_type: BobaExplanationType = (
            "editorial" if decision.selected else "rejection"
        )
        selection_label = "selected" if decision.selected else "not selected"
        key_reasons = [
            *decision.decision_reasons,
            f"Production priority: {decision.production_priority.replace('_', ' ')}.",
            f"Story angle: {decision.final_story_angle}",
            f"Hook strategy: {decision.final_hook_strategy.replace('_', ' ')}.",
            f"Pacing: {decision.pacing_intensity}; captions: "
            f"{decision.caption_style.replace('_', ' ')}; motion: "
            f"{decision.motion_style.replace('_', ' ')}.",
            f"Music mood: {decision.music_mood}; SFX intensity: {decision.sfx_intensity}.",
        ]
        if brief is not None:
            key_reasons.append("A saved Creative Director brief informed this candidate.")
        evidence = [
            self._evidence(
                "signal",
                "editorial_decision",
                "decisions[].selected",
                f"Candidate is {selection_label}",
                score=100.0 if decision.selected else 0.0,
                timestamp=decision.source_window.get("start_seconds"),
                confidence=decision.confidence,
            ),
            self._evidence(
                "signal",
                "editorial_decision",
                "decisions[].final_hook_strategy",
                decision.final_hook_strategy.replace("_", " "),
                timestamp=decision.source_window.get("start_seconds"),
                confidence=decision.confidence,
            ),
            self._evidence(
                "signal",
                "editorial_decision",
                "decisions[].editing_instruction_packet",
                decision.editing_instruction_packet.hook_instruction,
                timestamp=decision.source_window.get("start_seconds"),
                confidence=decision.confidence,
            ),
        ]
        evidence.extend(self._risk_evidence(decision))
        short_summary = (
            f"BOBA {selection_label} {decision.suggested_title} and recommends "
            f"{decision.final_hook_strategy.replace('_', ' ')} with "
            f"{decision.pacing_intensity} pacing."
        )
        detail = (
            f"The saved editorial decision marks this candidate {selection_label} with "
            f"{decision.production_priority.replace('_', ' ')} priority. It recommends the "
            f"story angle '{decision.final_story_angle}', a "
            f"{decision.final_hook_strategy.replace('_', ' ')} opening, "
            f"{decision.caption_style.replace('_', ' ')} captions, "
            f"{decision.motion_style.replace('_', ' ')} motion, {decision.music_mood} music "
            f"mood metadata, and {decision.sfx_intensity} SFX intensity. These are advisory "
            "instructions, not evidence that an edit was rendered."
        )
        warnings = [
            *decision.risk_review.warnings,
            *decision.risk_review.blockers,
        ]
        return BobaClipExplanationV1(
            clip_id=decision.candidate_id,
            candidate_id=decision.candidate_id,
            explanation_type=explanation_type,
            short_summary=_text(short_summary, maximum=400),
            detailed_explanation=_text(detail, maximum=1200),
            key_reasons=_unique(key_reasons, limit=24),
            evidence=self._dedupe_evidence(evidence),
            confidence=decision.confidence,
            warnings=_unique(warnings, limit=32),
            limitations=_unique(decision.improvement_notes, limit=24),
        )

    def _readiness_explanation(
        self,
        decision: BobaEditorialDecisionV1,
    ) -> BobaClipExplanationV1:
        reasons = [
            decision.render_readiness_reason,
            *decision.risk_review.blockers,
            *decision.risk_review.warnings,
        ]
        required_fixes = list(decision.improvement_notes)
        if decision.render_readiness == "ready_for_render":
            required_fixes = [
                "Normal human meaning, rights, and technical validation still remain."
            ]
        short_summary = (
            f"Render preflight is {decision.render_readiness.replace('_', ' ')} because "
            f"{decision.render_readiness_reason}"
        )
        detail = (
            f"The editorial artifact marks this candidate {decision.render_readiness}. "
            f"Its saved reason is: {decision.render_readiness_reason} "
            f"Recorded blockers are: {'; '.join(decision.risk_review.blockers) or 'none'}. "
            f"Recorded improvements are: {'; '.join(required_fixes) or 'none'}. This status is "
            "an advisory preflight and is not proof that rendering succeeded."
        )
        evidence = [
            self._evidence(
                "signal",
                "editorial_decision",
                "decisions[].render_readiness",
                decision.render_readiness.replace("_", " "),
                timestamp=decision.source_window.get("start_seconds"),
                confidence=decision.confidence,
            ),
            self._evidence(
                "editorial_risk",
                "editorial_decision",
                "decisions[].render_readiness_reason",
                decision.render_readiness_reason,
                timestamp=decision.source_window.get("start_seconds"),
                confidence=decision.confidence,
            ),
            *self._risk_evidence(decision),
        ]
        return BobaClipExplanationV1(
            clip_id=decision.candidate_id,
            candidate_id=decision.candidate_id,
            explanation_type="render_readiness",
            short_summary=_text(short_summary, maximum=400),
            detailed_explanation=_text(detail, maximum=1200),
            key_reasons=_unique(reasons, limit=24),
            evidence=self._dedupe_evidence(evidence),
            confidence=decision.confidence,
            warnings=_unique(
                [*decision.risk_review.blockers, *decision.risk_review.warnings],
                limit=32,
            ),
            limitations=_unique(required_fixes, limit=24),
        )

    def _risk_evidence(
        self,
        decision: BobaEditorialDecisionV1,
    ) -> list[BobaExplanationEvidenceV1]:
        review = decision.risk_review
        labels = (
            ("weak_hook", review.weak_hook),
            ("missing_context", review.missing_context),
            ("weak_payoff", review.weak_payoff),
            ("filler_risk", review.filler_risk),
            ("duplicate_risk", review.duplicate_risk),
            ("rights_risk", review.rights_risk),
            ("audio_risk", review.audio_risk),
            ("visual_layout_risk", review.visual_layout_risk),
            ("unavailable_signal_risk", review.unavailable_signal_risk),
        )
        evidence = [
            self._evidence(
                "editorial_risk",
                "editorial_decision",
                f"decisions[].risk_review.{label}",
                label.replace("_", " "),
                timestamp=decision.source_window.get("start_seconds"),
                confidence=decision.confidence,
            )
            for label, active in labels
            if active
        ]
        evidence.extend(
            self._evidence(
                "editorial_risk",
                "editorial_decision",
                "decisions[].risk_review.blockers",
                blocker,
                timestamp=decision.source_window.get("start_seconds"),
                confidence=decision.confidence,
            )
            for blocker in review.blockers[:8]
        )
        return evidence

    def _project_summary(
        self,
        *,
        understanding: BobaWholeVideoUnderstandingV1 | None,
        discovery: BobaCandidateClipDiscoveryV1 | None,
        ranking: BobaClipRankingV1 | None,
        decisions: BobaEditorialDecisionSetV1 | None,
        signal_explanation: BobaSignalExplanationV1,
        uncertainty: BobaUncertaintySummaryV1,
    ) -> BobaProjectExplanationV1:
        if understanding is not None:
            overall = (
                f"BOBA's saved whole-video view describes this as {understanding.video_type} "
                f"about {understanding.primary_topic}. {understanding.overall_summary}"
            )
        else:
            overall = (
                "Whole Video Understanding is unavailable, so BOBA cannot safely summarize the "
                "entire video's topic or story."
            )
        top_reason = "No ranked or selected recommendation is available."
        if decisions is not None and decisions.selected_clip_ids:
            selected = next(
                (
                    item
                    for item in decisions.decisions
                    if item.candidate_id == decisions.selected_clip_ids[0]
                ),
                None,
            )
            if selected is not None:
                reason = selected.decision_reasons[0] if selected.decision_reasons else (
                    selected.render_readiness_reason
                )
                top_reason = f"Top selected clip {selected.suggested_title}: {reason}"
        elif ranking is not None and ranking.ranked_candidates:
            top = ranking.ranked_candidates[0]
            reason = top.ranking_reasons[0] if top.ranking_reasons else ranking.summary
            top_reason = f"Top ranked clip {top.suggested_title}: {reason}"
        elif discovery is not None and discovery.candidates:
            top_candidate = discovery.candidates[0]
            top_reason = (
                f"First discovered candidate {top_candidate.suggested_title}: "
                f"{top_candidate.discovery_reason}"
            )
        strong_types: list[str] = []
        weak_types: list[str] = []
        if decisions is not None:
            strong_types.extend(
                item.candidate_type
                for item in decisions.decisions
                if item.selected or item.render_readiness == "ready_for_render"
            )
            weak_types.extend(
                item.candidate_type
                for item in decisions.decisions
                if item.render_readiness == "blocked" or item.ranking_tier == "reject"
            )
        elif ranking is not None:
            strong_types.extend(
                item.candidate_type
                for item in ranking.ranked_candidates[:5]
                if item.tier in {"must_make", "strong_candidate"}
            )
            weak_types.extend(
                item.candidate_type
                for item in ranking.ranked_candidates
                if item.tier in {"needs_revision", "reject"}
            )
        human_notes = [
            "Verify that each explanation matches the source meaning and complete payoff.",
            "Confirm ownership or permission before production or publication.",
            "Review blocked and needs-revision clips before any render handoff.",
        ]
        if "face_signals" in " ".join(signal_explanation.signals_missing):
            human_notes.append(
                "Review speaker identity and framing because face evidence is missing."
            )
        return BobaProjectExplanationV1(
            overall_summary=_text(overall, maximum=1200),
            top_recommendation_reason=_text(top_reason, maximum=800),
            strongest_clip_types=self._common_types(strong_types),
            weakest_clip_types=self._common_types(weak_types),
            unavailable_signals=signal_explanation.signals_missing,
            main_uncertainties=uncertainty.reasons,
            human_review_notes=_unique(human_notes, limit=32),
        )

    def _signal_explanation(
        self,
        *,
        understanding: BobaWholeVideoUnderstandingV1 | None,
        discovery: BobaCandidateClipDiscoveryV1 | None,
        ranking: BobaClipRankingV1 | None,
        decisions: BobaEditorialDecisionSetV1 | None,
        briefs: list[BobaCreativeBriefV1],
        memory: dict[str, Any],
        analysis: dict[str, Any],
    ) -> BobaSignalExplanationV1:
        artifacts = (
            ("whole_video_understanding", understanding),
            ("candidate_clip_discovery", discovery),
            ("clip_ranking", ranking),
            ("editorial_decision", decisions),
            ("creative_briefs", briefs if briefs else None),
            ("boba_project_memory", memory if memory else None),
            ("analysis_signal_health", analysis if analysis else None),
        )
        used = [name for name, value in artifacts if value is not None]
        missing = [name for name, value in artifacts if value is None]
        fallback: list[str] = []
        warnings: list[str] = []
        effects: list[str] = []
        for name, artifact in (
            ("whole_video_understanding", understanding),
            ("candidate_clip_discovery", discovery),
            ("clip_ranking", ranking),
            ("editorial_decision", decisions),
        ):
            if artifact is None:
                effects.append(f"{name} was unavailable and contributed no explanation claims.")
                continue
            usage = _dict(getattr(artifact, "signal_usage", None))
            missing.extend(str(item) for item in _list(usage.get("unavailable_signals")))
            warnings.extend(str(item) for item in _list(usage.get("warnings")))
            if usage.get("fallback_used"):
                fallback.append(name)
        analysis_missing = self._analysis_missing(analysis)
        missing.extend(analysis_missing)
        if understanding is not None:
            effects.append(
                "Whole Video Understanding supplied project topic, story, emotional, and "
                "context/payoff evidence."
            )
        if discovery is not None:
            effects.append(
                "Candidate Discovery supplied window reasons, boundaries, snippets, and source "
                "signal references."
            )
        if ranking is not None:
            effects.append(
                "Clip Ranking supplied order, score factors, diversity penalties, and "
                "ranking risks."
            )
        if decisions is not None:
            effects.append(
                "Editorial Decisions supplied selection, readiness, edit direction, blockers, and "
                "improvement notes."
            )
        if briefs:
            effects.append("Creative Director briefs supplied saved advisory treatment context.")
        if memory:
            effects.append(
                "Project memory supplied only bounded advisory summaries; it did not replace "
                "source evidence."
            )
        return BobaSignalExplanationV1(
            signals_used=_unique(used, limit=48, maximum=120),
            signals_missing=_unique(missing, limit=48, maximum=160),
            fallback_signals=_unique(fallback, limit=32, maximum=120),
            how_signals_affected_decisions=_unique(effects, limit=48),
            warnings=_unique(warnings, limit=32),
        )

    def _uncertainty_summary(
        self,
        *,
        understanding: BobaWholeVideoUnderstandingV1 | None,
        discovery: BobaCandidateClipDiscoveryV1 | None,
        ranking: BobaClipRankingV1 | None,
        decisions: BobaEditorialDecisionSetV1 | None,
        analysis: dict[str, Any],
        signal_explanation: BobaSignalExplanationV1,
        explanations: list[BobaClipExplanationV1],
    ) -> BobaUncertaintySummaryV1:
        points = 1
        reasons = [
            "The explanation engine did not inspect source media; it summarizes saved metadata."
        ]
        missing_evidence = list(signal_explanation.signals_missing)
        for label, artifact in (
            ("Whole Video Understanding", understanding),
            ("Candidate Clip Discovery", discovery),
            ("Clip Ranking", ranking),
            ("Editorial Decisions", decisions),
        ):
            if artifact is None:
                points += 2
                reasons.append(f"{label} is unavailable.")
        if analysis and not bool(analysis.get("transcript_available", True)):
            points += 2
            reasons.append("Transcript evidence is unavailable.")
        if not analysis:
            points += 2
            reasons.append("Analysis signal health is unavailable.")
        provider_missing = self._analysis_missing(analysis)
        if provider_missing:
            points += min(3, len(provider_missing))
            reasons.append(
                "One or more analysis providers are unavailable: "
                + ", ".join(provider_missing[:6])
                + "."
            )
        artifact_text = " ".join(
            self._artifact_text(
                understanding,
                discovery,
                ranking,
                decisions,
                field="limitations",
                limit=64,
            )
        ).casefold()
        if "synthetic" in artifact_text:
            points += 3
            reasons.append("One or more source artifacts identify their evidence as synthetic.")
        low_confidence = sum(item.confidence < 0.55 for item in explanations)
        if low_confidence:
            points += min(3, low_confidence)
            reasons.append(f"{low_confidence} explanation(s) have confidence below 0.55.")
        warning_count = sum(len(item.warnings) for item in explanations)
        if warning_count >= 8:
            points += 2
            reasons.append("Many candidate-level warnings reduce explanation certainty.")
        elif warning_count:
            points += 1
            reasons.append("Candidate-level warnings remain unresolved.")
        if points <= 2:
            level: BobaUncertaintyLevel = "low"
        elif points <= 6:
            level = "medium"
        else:
            level = "high"
        checks = [
            "Compare the explanation with the original source meaning and surrounding context.",
            "Verify complete setup and payoff boundaries before approving a clip.",
            "Confirm rights and permission independently; BOBA cannot establish copyright safety.",
        ]
        if provider_missing:
            checks.append("Manually review missing visual, face, OCR, object, or audio evidence.")
        if low_confidence:
            checks.append("Review low-confidence candidates before accepting their explanation.")
        return BobaUncertaintySummaryV1(
            uncertainty_level=level,
            reasons=_unique(
                reasons or ["Available artifacts are internally consistent but still advisory."],
                limit=32,
            ),
            missing_evidence=_unique(missing_evidence, limit=48, maximum=160),
            recommended_human_checks=_unique(checks, limit=32),
        )

    @staticmethod
    def _analysis_missing(analysis: Mapping[str, Any]) -> list[str]:
        if not analysis:
            return []
        missing: list[str] = []
        availability = (
            ("transcript", analysis.get("transcript_available")),
            ("face_signals", analysis.get("face_signals_available")),
            ("speaker_signals", analysis.get("speaker_signals_available")),
            ("visual_signals", analysis.get("visual_signals_available")),
        )
        missing.extend(name for name, available in availability if available is False)
        root = _dict(analysis.get("analysis_signals_v2")) or dict(analysis)

        def visit(value: Mapping[str, Any], path: str = "") -> None:
            for key, item in value.items():
                name = f"{path}.{key}".strip(".")
                if isinstance(item, Mapping):
                    status = str(item.get("status") or "").casefold()
                    available = item.get("available")
                    if available is False or status in {
                        "unavailable",
                        "missing",
                        "disabled",
                        "failed",
                        "error",
                    }:
                        missing.append(name)
                    if len(name.split(".")) < 4:
                        visit(item, name)

        visit(root)
        return _unique(missing, limit=32, maximum=160)

    @staticmethod
    def _artifact_text(
        *artifacts: BaseModel | None,
        field: str,
        limit: int,
    ) -> list[str]:
        values: list[str] = []
        for artifact in artifacts:
            if artifact is None:
                continue
            values.extend(str(item) for item in _list(getattr(artifact, field, [])))
        return _unique(values, limit=limit)

    @staticmethod
    def _common_types(values: Sequence[str]) -> list[str]:
        counts = Counter(value for value in values if value)
        return [value for value, _count in counts.most_common(16)]

    @staticmethod
    def _evidence(
        evidence_type: BobaEvidenceType,
        source_artifact: str,
        source_field: str,
        snippet: Any,
        *,
        score: float | None = None,
        timestamp: float | None = None,
        confidence: float = 0.5,
    ) -> BobaExplanationEvidenceV1:
        return BobaExplanationEvidenceV1(
            evidence_type=evidence_type,
            source_artifact=source_artifact,
            source_field=source_field,
            snippet=_text(snippet, maximum=300) or "Evidence value unavailable.",
            score=(max(0.0, min(100.0, score)) if score is not None else None),
            timestamp_seconds=(max(0.0, timestamp) if timestamp is not None else None),
            confidence=_unit(confidence, 0.5),
        )

    @staticmethod
    def _dedupe_evidence(
        values: Sequence[BobaExplanationEvidenceV1],
    ) -> list[BobaExplanationEvidenceV1]:
        result: list[BobaExplanationEvidenceV1] = []
        seen: set[tuple[str, str, str, str]] = set()
        for item in values:
            key = (
                item.evidence_type,
                item.source_artifact,
                item.source_field,
                item.snippet.casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
            if len(result) >= 40:
                break
        return result

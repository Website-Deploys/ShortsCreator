"""Deterministic advisory hook and retention analysis over saved BOBA artifacts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from olympus.boba.clip_brief import BobaSourceWindowV1
from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

BobaHookType = Literal[
    "curiosity_gap",
    "emotional_reveal",
    "contradiction",
    "shocking_truth",
    "problem_solution",
    "motivational_payoff",
    "story_turn",
    "educational_open_loop",
    "direct_value",
    "mystery",
    "tension",
    "humor",
    "unknown",
]
BobaHookRecommendationLabel = Literal["best", "safest", "boldest", "backup", "avoid"]

_HOOK_TYPES: set[str] = {
    "curiosity_gap",
    "emotional_reveal",
    "contradiction",
    "shocking_truth",
    "problem_solution",
    "motivational_payoff",
    "story_turn",
    "educational_open_loop",
    "direct_value",
    "mystery",
    "tension",
    "humor",
    "unknown",
}
_CURIOSITY_CUES = (
    "why",
    "how",
    "what happened",
    "the reason",
    "secret",
    "truth",
    "mistake",
    "until",
    "but",
    "changed",
    "?",
)
_DIRECT_VALUE_CUES = (
    "here is",
    "here's",
    "learn",
    "use this",
    "do this",
    "the rule",
    "the lesson",
    "the answer",
    "how to",
)
_SLOW_START_CUES = (
    "slow start",
    "slow opening",
    "long intro",
    "broad setup",
    "setup before",
    "ease into",
    "introduce the topic",
    "background first",
)
_UNCLEAR_CONTEXT_CUES = (
    "missing context",
    "needs context",
    "unclear context",
    "context dependency",
    "fragment",
)
_WEAK_PAYOFF_CUES = (
    "missing payoff",
    "weak payoff",
    "no payoff",
    "payoff is unclear",
    "ends before",
)
_FILLER_CUES = (
    "filler risk",
    "remove filler",
    "too much setup",
    "repetition",
    "rambling",
)
_OVER_EDITING_CUES = (
    "over-edit",
    "too many effects",
    "high motion",
    "aggressive motion",
    "constant zoom",
    "rapid cuts",
)
_CAPTION_OVERLOAD_CUES = (
    "caption overload",
    "too much text",
    "dense caption",
    "too many words",
    "unreadable caption",
)
_AUDIO_DISTRACTION_CUES = (
    "audio distraction",
    "audio risk",
    "overpower speech",
    "mask speech",
    "noisy sfx",
    "static",
)


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _artifact(value: Mapping[str, Any] | BaseModel | None) -> dict[str, Any]:
    raw = _dict(value)
    return _dict(raw.get("data")) or raw


def _text(value: Any, *, maximum: int = 500) -> str:
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


def _points(value: Any, default: float = 0.0) -> float:
    number = _number(value, default)
    if 0.0 <= number <= 1.0:
        number *= 100.0
    return round(max(0.0, min(100.0, number)), 2)


def _optional_points(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | str):
        try:
            return _points(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, Mapping):
        for key in ("score", "value", "overall_score", "final_score"):
            if key in value:
                return _optional_points(value.get(key))
    return None


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _unit(value: Any, default: float = 0.0) -> float:
    number = _number(value, default)
    if 1.0 < number <= 100.0:
        number /= 100.0
    return round(max(0.0, min(1.0, number)), 3)


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


def _joined(*values: Any, maximum: int = 4_000) -> str:
    flattened: list[str] = []
    for value in values:
        if isinstance(value, Mapping | BaseModel):
            flattened.extend(_flatten_strings(_dict(value)))
        elif isinstance(value, list | tuple):
            flattened.extend(_flatten_strings(value))
        else:
            clean = _text(value, maximum=800)
            if clean:
                flattened.append(clean)
    return " ".join(flattened)[:maximum].casefold()


def _flatten_strings(value: Any, *, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_flatten_strings(item, depth=depth + 1))
        return result
    if isinstance(value, list | tuple):
        result = []
        for item in value:
            result.extend(_flatten_strings(item, depth=depth + 1))
        return result
    clean = _text(value, maximum=500)
    return [clean] if clean else []


def _contains(text: str, cues: Sequence[str]) -> bool:
    return any(cue in text for cue in cues)


def _weighted(values: Sequence[tuple[float | None, float]], default: float) -> float:
    available = [(value, weight) for value, weight in values if value is not None]
    if not available:
        return _clamp(default)
    total_weight = sum(weight for _value, weight in available)
    if total_weight <= 0.0:
        return _clamp(default)
    return _clamp(
        sum(float(value) * weight for value, weight in available) / total_weight
    )


def _by_id(values: Any, field: str = "candidate_id") -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in _list(values):
        item = _dict(value)
        identifier = _text(item.get(field), maximum=128)
        if identifier:
            result[identifier] = item
    return result


def _explanations_by_id(values: Any) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for value in _list(values):
        item = _dict(value)
        identifier = _text(
            item.get("candidate_id") or item.get("clip_id"), maximum=128
        )
        if identifier:
            result.setdefault(identifier, []).append(item)
    return result


def _find_points(
    value: Any,
    keys: Sequence[str],
    *,
    depth: int = 0,
) -> float | None:
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        for key in keys:
            if key in value:
                found = _optional_points(value.get(key))
                if found is not None:
                    return found
        for nested in value.values():
            found = _find_points(nested, keys, depth=depth + 1)
            if found is not None:
                return found
    elif isinstance(value, list | tuple):
        for nested in value:
            found = _find_points(nested, keys, depth=depth + 1)
            if found is not None:
                return found
    return None


def _source_window(value: Mapping[str, Any]) -> BobaSourceWindowV1:
    raw = _dict(value.get("source_window"))
    start = max(
        0.0,
        _number(
            raw.get("start_seconds")
            if raw.get("start_seconds") is not None
            else raw.get("start") or value.get("start_seconds")
        ),
    )
    end = max(
        start,
        _number(
            raw.get("end_seconds")
            if raw.get("end_seconds") is not None
            else raw.get("end") or value.get("end_seconds"),
            start,
        ),
    )
    duration = max(0.0, min(180.0, _number(raw.get("duration_seconds"), end - start)))
    if end <= start and duration > 0.0:
        end = start + duration
    return BobaSourceWindowV1(
        start_seconds=round(start, 3),
        end_seconds=round(end, 3),
        duration_seconds=round(max(0.0, end - start), 3),
    )


def _overlap(
    value: Mapping[str, Any], source_window: BobaSourceWindowV1
) -> bool:
    start = _number(value.get("start_seconds") or value.get("start"))
    end = _number(value.get("end_seconds") or value.get("end"), start)
    return end > start and min(end, source_window.end_seconds) > max(
        start, source_window.start_seconds
    )


class BobaHookAnalysisV1(BobaContract):
    hook_type: BobaHookType
    hook_strength: float = Field(ge=0.0, le=100.0)
    curiosity_gap: str = Field(min_length=1, max_length=600)
    first_three_second_clarity: float = Field(ge=0.0, le=100.0)
    pattern_interrupt: str = Field(min_length=1, max_length=600)
    opening_line_direction: str = Field(min_length=1, max_length=700)
    visual_opening_direction: str = Field(min_length=1, max_length=700)
    hook_risk: str = Field(min_length=1, max_length=700)
    improved_hook_direction: str = Field(min_length=1, max_length=800)
    reason: str = Field(min_length=1, max_length=1000)


class BobaHookAlternativeV1(BobaContract):
    alternative_id: str = Field(min_length=1, max_length=180)
    hook_type: BobaHookType
    opening_line_direction: str = Field(min_length=1, max_length=700)
    caption_direction: str = Field(min_length=1, max_length=600)
    visual_direction: str = Field(min_length=1, max_length=600)
    strength_score: float = Field(ge=0.0, le=100.0)
    risk_score: float = Field(ge=0.0, le=100.0)
    why_it_may_work: str = Field(min_length=1, max_length=800)
    why_it_may_fail: str = Field(min_length=1, max_length=800)
    recommendation_label: BobaHookRecommendationLabel


class BobaRetentionPlanV1(BobaContract):
    seconds_0_to_3: str = Field(min_length=1, max_length=800)
    seconds_3_to_10: str = Field(min_length=1, max_length=800)
    middle_hold_strategy: str = Field(min_length=1, max_length=800)
    payoff_timing_strategy: str = Field(min_length=1, max_length=800)
    ending_replay_trigger: str = Field(min_length=1, max_length=800)
    pacing_notes: list[str] = Field(default_factory=list, max_length=20)
    retention_tactics: list[str] = Field(default_factory=list, max_length=24)


class BobaRetentionRiskReviewV1(BobaContract):
    slow_start_risk: bool
    unclear_context_risk: bool
    weak_payoff_risk: bool
    filler_risk: bool
    over_editing_risk: bool
    under_editing_risk: bool
    caption_overload_risk: bool
    audio_distraction_risk: bool
    risk_fixes: list[str] = Field(default_factory=list, max_length=24)
    blockers: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRetentionScoreV1(BobaContract):
    hook_score: float = Field(ge=0.0, le=100.0)
    curiosity_score: float = Field(ge=0.0, le=100.0)
    clarity_score: float = Field(ge=0.0, le=100.0)
    momentum_score: float = Field(ge=0.0, le=100.0)
    payoff_score: float = Field(ge=0.0, le=100.0)
    replay_score: float = Field(ge=0.0, le=100.0)
    dropoff_risk_score: float = Field(ge=0.0, le=100.0)
    overall_retention_score: float = Field(ge=0.0, le=100.0)


class BobaBriefHookEnhancementV1(BobaContract):
    brief_id: str = Field(min_length=1, max_length=160)
    enhanced_opening_line_direction: str = Field(min_length=1, max_length=700)
    enhanced_pattern_interrupt: str = Field(min_length=1, max_length=700)
    enhanced_caption_hook: str = Field(min_length=1, max_length=600)
    enhanced_payoff_timing: str = Field(min_length=1, max_length=700)
    enhanced_replay_trigger: str = Field(min_length=1, max_length=700)
    retention_warning: str = Field(min_length=1, max_length=700)
    apply_suggestion: Literal[False] = False


class BobaHookRetentionSignalUsageV1(BobaContract):
    clip_briefs_used: bool
    creative_direction_used: bool
    editorial_decision_used: bool
    clip_ranking_used: bool
    candidate_discovery_used: bool
    whole_video_understanding_used: bool
    explanation_used: bool
    virality_used: bool
    memory_used: bool
    fallback_used: bool
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaHookRetentionAnalysisV1(BobaContract):
    analysis_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=160)
    source_window: BobaSourceWindowV1
    hook_analysis: BobaHookAnalysisV1
    hook_alternatives: list[BobaHookAlternativeV1] = Field(
        min_length=3, max_length=5
    )
    retention_plan: BobaRetentionPlanV1
    retention_risk_review: BobaRetentionRiskReviewV1
    retention_score: BobaRetentionScoreV1
    brief_enhancements: BobaBriefHookEnhancementV1
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaHookRetentionSetV1(BobaContract):
    schema_version: Literal["boba_hook_retention_brain_v1"] = (
        "boba_hook_retention_brain_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    analyses: list[BobaHookRetentionAnalysisV1] = Field(
        default_factory=list, max_length=10
    )
    project_retention_summary: str = Field(min_length=1, max_length=1500)
    signal_usage: BobaHookRetentionSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaHookRetentionBrainV1:
    """Create bounded hook and retention advice without editing or rendering media."""

    def analyze(
        self,
        *,
        project_id: str,
        clip_briefs: Mapping[str, Any] | BaseModel | None,
        creative_direction_v2: Mapping[str, Any] | BaseModel | None = None,
        editorial_decisions: Mapping[str, Any] | BaseModel | None = None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        virality: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaHookRetentionSetV1:
        briefs = _artifact(clip_briefs)
        if not briefs:
            raise ValidationError(
                "BOBA Hook + Retention Brain requires saved clip briefs.",
                details={
                    "project_id": project_id,
                    "required_artifact": "clip_briefs",
                },
            )
        self._validate_project(project_id, briefs, "clip_briefs")

        creative = _artifact(creative_direction_v2)
        editorial = _artifact(editorial_decisions)
        ranking = _artifact(clip_ranking)
        discovery = _artifact(candidate_discovery)
        understanding = _artifact(whole_video_understanding)
        explanation_set = _artifact(explanations)
        virality_data = _artifact(virality)
        memory_data = _artifact(memory)
        for artifact, label in (
            (creative, "creative_direction_v2"),
            (editorial, "editorial_decisions"),
            (ranking, "clip_ranking"),
            (discovery, "candidate_discovery"),
            (understanding, "whole_video_understanding"),
            (explanation_set, "explanations"),
            (memory_data, "memory"),
        ):
            self._validate_project(project_id, artifact, label)

        creative_by_id = _by_id(creative.get("clip_directions"))
        editorial_by_id = _by_id(editorial.get("decisions"))
        ranking_by_id = _by_id(ranking.get("ranked_candidates"))
        discovery_by_id = _by_id(discovery.get("candidates"))
        explanations_by_id = _explanations_by_id(
            explanation_set.get("candidate_explanations")
        )
        virality_by_id = self._virality_by_id(virality_data)
        analyses: list[BobaHookRetentionAnalysisV1] = []
        for value in _list(briefs.get("selected_briefs"))[:10]:
            brief = _dict(value)
            candidate_id = _text(brief.get("candidate_id"), maximum=128)
            if not candidate_id:
                continue
            analyses.append(
                self._analyze_brief(
                    project_id=project_id,
                    brief=brief,
                    creative=creative_by_id.get(candidate_id, {}),
                    editorial=editorial_by_id.get(candidate_id, {}),
                    ranking=ranking_by_id.get(candidate_id, {}),
                    discovery=discovery_by_id.get(candidate_id, {}),
                    understanding=understanding,
                    explanations=explanations_by_id.get(candidate_id, []),
                    virality=virality_by_id.get(candidate_id, virality_data),
                    memory=memory_data,
                )
            )

        unavailable = [
            label
            for available, label in (
                (bool(creative), "creative_direction_v2"),
                (bool(editorial), "editorial_decisions"),
                (bool(ranking), "clip_ranking"),
                (bool(discovery), "candidate_discovery"),
                (bool(understanding), "whole_video_understanding"),
                (bool(explanation_set), "explanations"),
                (bool(virality_data), "virality"),
                (bool(memory_data), "memory"),
            )
            if not available
        ]
        warnings = _unique(
            [
                *(
                    [
                        "No selected clip briefs were available; no per-clip analysis "
                        "was fabricated."
                    ]
                    if not analyses
                    else []
                ),
                *(
                    [
                        "Optional upstream artifacts were unavailable; deterministic "
                        "clip-brief fallbacks were used."
                    ]
                    if unavailable
                    else []
                ),
                *_list(briefs.get("warnings")),
            ],
            limit=64,
            maximum=700,
        )
        signal_usage = BobaHookRetentionSignalUsageV1(
            clip_briefs_used=True,
            creative_direction_used=bool(creative),
            editorial_decision_used=bool(editorial),
            clip_ranking_used=bool(ranking),
            candidate_discovery_used=bool(discovery),
            whole_video_understanding_used=bool(understanding),
            explanation_used=bool(explanation_set),
            virality_used=bool(virality_data),
            memory_used=bool(memory_data),
            fallback_used=bool(unavailable),
            unavailable_signals=unavailable,
            warnings=_unique(
                [
                    *(
                        [
                            "Missing optional signals lower confidence but do not block "
                            "advisory analysis."
                        ]
                        if unavailable
                        else []
                    ),
                    *(
                        [
                            "Memory was consulted only for bounded warnings and never "
                            "overrode clip evidence."
                        ]
                        if memory_data
                        else []
                    ),
                ],
                limit=32,
            ),
        )
        return BobaHookRetentionSetV1(
            project_id=project_id,
            source_id=_text(
                briefs.get("source_id")
                or creative.get("source_id")
                or editorial.get("source_id")
                or ranking.get("source_id")
                or discovery.get("source_id")
                or understanding.get("source_id"),
                maximum=512,
            ),
            analyses=analyses,
            project_retention_summary=self._project_summary(analyses),
            signal_usage=signal_usage,
            warnings=warnings,
            limitations=[
                "Hook + Retention Brain V1 is advisory metadata and does not edit, "
                "download, or render media.",
                "Scores compare saved local signals; they are not audience predictions, "
                "watch-time measurements, or guarantees of virality.",
                "Alternatives paraphrase saved angles and instructions without inventing "
                "transcript facts.",
                "No music asset, copyrighted material, raw transcript, or media payload is "
                "stored in this artifact.",
                "A human must review source meaning, hook accuracy, pacing, captions, "
                "payoff, rights, and the final rendered output.",
            ],
        )

    def analyze_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        clip_briefs: Mapping[str, Any] | BaseModel | None = None,
        creative_direction_v2: Mapping[str, Any] | BaseModel | None = None,
        editorial_decisions: Mapping[str, Any] | BaseModel | None = None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        virality: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaHookRetentionSetV1:
        return self.analyze(
            project_id=project_id,
            clip_briefs=clip_briefs or _dict(signals.get("clip_briefs")),
            creative_direction_v2=(
                creative_direction_v2 or _dict(signals.get("creative_direction_v2"))
            ),
            editorial_decisions=(
                editorial_decisions or _dict(signals.get("editorial_decisions"))
            ),
            clip_ranking=clip_ranking or _dict(signals.get("clip_ranking")),
            candidate_discovery=(
                candidate_discovery
                or _dict(signals.get("candidate_clip_discovery"))
            ),
            whole_video_understanding=(
                whole_video_understanding
                or _dict(signals.get("whole_video_understanding"))
            ),
            explanations=explanations or _dict(signals.get("explanations")),
            virality=virality or _dict(signals.get("virality_summary")),
            memory=memory or _dict(signals.get("project_memory")),
        )

    def _analyze_brief(
        self,
        *,
        project_id: str,
        brief: dict[str, Any],
        creative: dict[str, Any],
        editorial: dict[str, Any],
        ranking: dict[str, Any],
        discovery: dict[str, Any],
        understanding: dict[str, Any],
        explanations: list[dict[str, Any]],
        virality: dict[str, Any],
        memory: dict[str, Any],
    ) -> BobaHookRetentionAnalysisV1:
        candidate_id = _text(brief.get("candidate_id"), maximum=128)
        brief_id = _text(
            brief.get("brief_id") or f"brief_{candidate_id}", maximum=160
        )
        source_window = _source_window(brief)
        hook_instruction = _dict(brief.get("hook_instruction"))
        opening_instruction = _dict(brief.get("opening_three_second_instruction"))
        caption_instruction = _dict(brief.get("caption_instruction"))
        motion_instruction = _dict(brief.get("motion_instruction"))
        audio_instruction = _dict(brief.get("audio_instruction"))
        retention_instruction = _dict(brief.get("retention_instruction"))
        hook_treatment = _dict(creative.get("hook_treatment"))
        opening_plan = _dict(creative.get("opening_three_second_plan"))
        pacing_map = _dict(creative.get("pacing_map"))
        retention_v2 = _dict(creative.get("retention_plan"))
        creative_quality = _dict(creative.get("creative_quality_score"))
        score_breakdown = _dict(ranking.get("score_breakdown"))
        editorial_risk = _dict(editorial.get("risk_review"))

        current_text = _joined(
            brief.get("final_clip_angle"),
            hook_instruction.get("summary"),
            hook_instruction.get("do_this"),
            opening_instruction.get("summary"),
            opening_instruction.get("do_this"),
            hook_treatment.get("hook_type"),
            hook_treatment.get("opening_line_direction"),
            hook_treatment.get("first_visual_emphasis"),
            hook_treatment.get("curiosity_trigger"),
            hook_treatment.get("pattern_interrupt"),
            opening_plan.get("what_viewer_sees_first"),
            opening_plan.get("caption_implication"),
            opening_plan.get("curiosity_gap"),
            opening_plan.get("motion_choice"),
            editorial.get("opening_line_direction"),
            ranking.get("hook_idea"),
            discovery.get("hook_idea"),
        )
        warning_text = _joined(
            brief.get("warnings"),
            brief.get("human_review_notes"),
            creative.get("warnings"),
            creative.get("risk_fixes"),
            hook_treatment.get("hook_risk"),
            ranking.get("risk_warnings"),
            editorial_risk.get("warnings"),
            memory.get("known_limitations"),
            memory.get("warnings"),
        )
        hook_type = self._hook_type(
            hook_treatment.get("hook_type")
            or editorial.get("final_hook_strategy")
            or ranking.get("hook_idea")
            or current_text
        )
        opening_line = _text(
            hook_treatment.get("opening_line_direction")
            or editorial.get("opening_line_direction")
            or hook_instruction.get("do_this")
            or hook_instruction.get("summary")
            or brief.get("final_clip_angle")
            or "Open directly on the saved clip angle.",
            maximum=700,
        )
        curiosity_gap = _text(
            hook_treatment.get("curiosity_trigger")
            or opening_plan.get("curiosity_gap")
            or retention_v2.get("curiosity_loop")
            or hook_instruction.get("reason")
            or "Create a clear, evidence-backed question that the saved payoff resolves.",
            maximum=600,
        )
        pattern_interrupt = _text(
            hook_treatment.get("pattern_interrupt")
            or opening_plan.get("motion_choice")
            or "Use one restrained visual or caption emphasis on the saved opening idea.",
            maximum=600,
        )
        visual_opening = _text(
            hook_treatment.get("first_visual_emphasis")
            or opening_plan.get("what_viewer_sees_first")
            or "; ".join(
                _text(item, maximum=180)
                for item in _list(editorial.get("visual_emphasis"))[:3]
                if _text(item, maximum=180)
            )
            or opening_instruction.get("summary")
            or "Show the clearest supported subject immediately.",
            maximum=700,
        )

        heuristic_hook = 42.0
        heuristic_hook += min(
            24.0, 6.0 * sum(cue in current_text for cue in _CURIOSITY_CUES)
        )
        heuristic_hook += min(
            16.0, 4.0 * sum(cue in current_text for cue in _DIRECT_VALUE_CUES)
        )
        heuristic_hook += 10.0 if hook_type != "unknown" else 0.0
        heuristic_hook += (
            8.0
            if pattern_interrupt
            and "no pattern" not in pattern_interrupt.casefold()
            and pattern_interrupt.casefold() != "none"
            else 0.0
        )
        if _contains(current_text, _SLOW_START_CUES):
            heuristic_hook -= 22.0
        if bool(editorial_risk.get("weak_hook")):
            heuristic_hook -= 24.0

        ranking_hook = _find_points(
            score_breakdown or ranking,
            ("hook_score", "hook_strength_score", "hook_strength"),
        )
        creative_hook = _find_points(
            creative_quality, ("hook_quality", "hook_score")
        )
        virality_hook = _find_points(
            virality, ("hook_score", "hook_strength_score", "hook_strength")
        )
        hook_score = _weighted(
            (
                (ranking_hook, 0.35),
                (creative_hook, 0.25),
                (virality_hook, 0.15),
                (_clamp(heuristic_hook), 0.25),
            ),
            _clamp(heuristic_hook),
        )

        curiosity_heuristic = 35.0 + min(
            45.0, 7.5 * sum(cue in current_text for cue in _CURIOSITY_CUES)
        )
        if curiosity_gap:
            curiosity_heuristic += 10.0
        curiosity_score = _weighted(
            (
                (
                    _find_points(
                        virality,
                        ("curiosity_score", "curiosity_gap_score", "curiosity_gap"),
                    ),
                    0.35,
                ),
                (_clamp(curiosity_heuristic), 0.65),
            ),
            curiosity_heuristic,
        )

        clarity_heuristic = 70.0
        opening_word_count = len(opening_line.split())
        if opening_word_count > 36:
            clarity_heuristic -= min(28.0, float(opening_word_count - 36))
        if _contains(warning_text, _UNCLEAR_CONTEXT_CUES):
            clarity_heuristic -= 25.0
        if discovery.get("context_needed") is True:
            clarity_heuristic -= 20.0
        if _contains(current_text, _DIRECT_VALUE_CUES):
            clarity_heuristic += 10.0
        clarity_score = _weighted(
            (
                (
                    _find_points(
                        score_breakdown or ranking,
                        ("clarity_score", "standalone_score"),
                    ),
                    0.35,
                ),
                (_find_points(creative_quality, ("clarity",)), 0.3),
                (
                    _find_points(
                        virality, ("clarity_score", "first_three_second_clarity")
                    ),
                    0.1,
                ),
                (_clamp(clarity_heuristic), 0.25),
            ),
            clarity_heuristic,
        )

        duration = source_window.duration_seconds
        pacing_label = _text(
            pacing_map.get("pacing_intensity")
            or editorial.get("pacing_intensity")
            or "moderate",
            maximum=80,
        ).casefold()
        momentum_heuristic = 68.0
        if duration > 50.0 and pacing_label in {"calm", "moderate"}:
            momentum_heuristic -= 18.0
        if _contains(current_text, _SLOW_START_CUES):
            momentum_heuristic -= 25.0
        if pacing_label in {"fast", "aggressive"}:
            momentum_heuristic += 8.0
        momentum_score = _weighted(
            (
                (
                    _find_points(
                        score_breakdown or ranking,
                        ("retention_score", "pacing_score", "momentum_score"),
                    ),
                    0.35,
                ),
                (
                    _find_points(creative_quality, ("pacing_strength",)),
                    0.25,
                ),
                (
                    _find_points(
                        virality,
                        ("momentum_score", "retention_score", "retention_potential"),
                    ),
                    0.15,
                ),
                (_clamp(momentum_heuristic), 0.25),
            ),
            momentum_heuristic,
        )

        payoff_heuristic = 58.0
        if discovery.get("payoff_present") is True:
            payoff_heuristic += 24.0
        elif discovery.get("payoff_present") is False:
            payoff_heuristic -= 35.0
        if bool(editorial_risk.get("weak_payoff")):
            payoff_heuristic -= 30.0
        payoff_score = _weighted(
            (
                (
                    _find_points(
                        score_breakdown or ranking,
                        ("payoff_score", "payoff_strength"),
                    ),
                    0.4,
                ),
                (
                    _find_points(
                        virality, ("payoff_score", "payoff_strength", "ending_strength")
                    ),
                    0.15,
                ),
                (_clamp(payoff_heuristic), 0.45),
            ),
            payoff_heuristic,
        )
        replay_heuristic = 42.0
        if _text(retention_v2.get("replay_trigger")):
            replay_heuristic += 25.0
        if payoff_score >= 70.0:
            replay_heuristic += 15.0
        replay_score = _weighted(
            (
                (
                    _find_points(
                        virality,
                        ("replay_score", "replay_potential", "replay_potential_score"),
                    ),
                    0.35,
                ),
                (_clamp(replay_heuristic), 0.65),
            ),
            replay_heuristic,
        )

        section_scores = [
            _dict(item)
            for item in _list(understanding.get("section_scores"))
            if _dict(item) and _overlap(_dict(item), source_window)
        ]
        filler_signal = max(
            (
                _unit(item.get("filler_score"))
                for item in section_scores
                if item.get("filler_score") is not None
            ),
            default=0.0,
        )
        risks = self._risk_review(
            brief=brief,
            editorial_risk=editorial_risk,
            discovery=discovery,
            ranking=ranking,
            current_text=current_text,
            warning_text=warning_text,
            motion_text=_joined(
                motion_instruction.get("summary"),
                motion_instruction.get("do_this"),
                creative.get("motion_direction"),
            ),
            caption_text=_joined(
                caption_instruction.get("summary"),
                caption_instruction.get("do_this"),
                creative.get("caption_direction"),
            ),
            audio_text=_joined(
                audio_instruction.get("summary"),
                audio_instruction.get("do_this"),
                _dict(brief.get("sfx_instruction")).get("summary"),
                _dict(brief.get("sfx_instruction")).get("do_this"),
                creative.get("audio_direction"),
                warning_text,
            ),
            hook_score=hook_score,
            payoff_score=payoff_score,
            clarity_score=clarity_score,
            duration=duration,
            filler_signal=filler_signal,
            pattern_interrupt=pattern_interrupt,
        )
        risk_flags = (
            (risks.slow_start_risk, 18.0),
            (risks.unclear_context_risk, 16.0),
            (risks.weak_payoff_risk, 20.0),
            (risks.filler_risk, 15.0),
            (risks.over_editing_risk, 9.0),
            (risks.under_editing_risk, 11.0),
            (risks.caption_overload_risk, 7.0),
            (risks.audio_distraction_risk, 8.0),
        )
        dropoff_risk = _clamp(
            sum(weight for enabled, weight in risk_flags if enabled)
        )
        overall_retention = _clamp(
            0.22 * hook_score
            + 0.15 * curiosity_score
            + 0.14 * clarity_score
            + 0.17 * momentum_score
            + 0.19 * payoff_score
            + 0.13 * replay_score
            - 0.22 * dropoff_risk
        )
        scores = BobaRetentionScoreV1(
            hook_score=hook_score,
            curiosity_score=curiosity_score,
            clarity_score=clarity_score,
            momentum_score=momentum_score,
            payoff_score=payoff_score,
            replay_score=replay_score,
            dropoff_risk_score=dropoff_risk,
            overall_retention_score=overall_retention,
        )
        improved_hook = self._improved_hook_direction(
            hook_type=hook_type,
            angle=_text(brief.get("final_clip_angle"), maximum=500),
            opening_line=opening_line,
            risks=risks,
        )
        hook_risk = self._hook_risk(risks, hook_score)
        hook_analysis = BobaHookAnalysisV1(
            hook_type=hook_type,
            hook_strength=hook_score,
            curiosity_gap=curiosity_gap,
            first_three_second_clarity=clarity_score,
            pattern_interrupt=pattern_interrupt,
            opening_line_direction=opening_line,
            visual_opening_direction=visual_opening,
            hook_risk=hook_risk,
            improved_hook_direction=improved_hook,
            reason=self._hook_reason(
                hook_score,
                curiosity_score,
                clarity_score,
                explanations,
                risks,
            ),
        )
        retention_plan = self._retention_plan(
            brief=brief,
            opening_instruction=opening_instruction,
            retention_instruction=retention_instruction,
            pacing_map=pacing_map,
            retention_v2=retention_v2,
            risks=risks,
            improved_hook=improved_hook,
            payoff_score=payoff_score,
        )
        alternatives = self._alternatives(
            candidate_id=candidate_id,
            hook_type=hook_type,
            angle=_text(
                brief.get("final_clip_angle")
                or discovery.get("story_angle")
                or ranking.get("story_angle")
                or brief.get("brief_title"),
                maximum=500,
            ),
            opening_line=opening_line,
            visual_opening=visual_opening,
            hook_score=hook_score,
            clarity_score=clarity_score,
            improved_hook=improved_hook,
        )
        enhancement = BobaBriefHookEnhancementV1(
            brief_id=brief_id,
            enhanced_opening_line_direction=improved_hook,
            enhanced_pattern_interrupt=self._enhanced_pattern_interrupt(
                pattern_interrupt, risks
            ),
            enhanced_caption_hook=self._enhanced_caption(
                caption_instruction, hook_type
            ),
            enhanced_payoff_timing=self._enhanced_payoff_timing(
                retention_plan.payoff_timing_strategy, risks
            ),
            enhanced_replay_trigger=retention_plan.ending_replay_trigger,
            retention_warning=hook_risk,
            apply_suggestion=False,
        )
        upstream_count = sum(
            bool(item)
            for item in (
                creative,
                editorial,
                ranking,
                discovery,
                understanding,
                explanations,
                virality,
                memory,
            )
        )
        confidence = _unit(
            0.55 * _unit(brief.get("confidence"), 0.5)
            + 0.45 * min(1.0, upstream_count / 8.0),
            0.5,
        )
        analysis_warnings = _unique(
            [
                *risks.warnings,
                *(
                    [
                        "Hook revision is recommended before production because the "
                        "bounded hook score is below 55."
                    ]
                    if hook_score < 55.0
                    else []
                ),
                *(
                    [
                        "Overall retention guidance has multiple drop-off risks and "
                        "requires human review."
                    ]
                    if dropoff_risk >= 35.0
                    else []
                ),
            ],
            limit=32,
            maximum=700,
        )
        return BobaHookRetentionAnalysisV1(
            analysis_id=f"hook_retention_{candidate_id}",
            project_id=project_id,
            candidate_id=candidate_id,
            brief_id=brief_id,
            source_window=source_window,
            hook_analysis=hook_analysis,
            hook_alternatives=alternatives,
            retention_plan=retention_plan,
            retention_risk_review=risks,
            retention_score=scores,
            brief_enhancements=enhancement,
            confidence=confidence,
            warnings=analysis_warnings,
            limitations=[
                "This analysis evaluates saved metadata, not actual viewer behavior.",
                "Suggested wording is a direction; the editor must verify it against the "
                "source before use.",
                "The original clip brief remains unchanged and no rendering is triggered.",
            ],
        )

    def _risk_review(
        self,
        *,
        brief: dict[str, Any],
        editorial_risk: dict[str, Any],
        discovery: dict[str, Any],
        ranking: dict[str, Any],
        current_text: str,
        warning_text: str,
        motion_text: str,
        caption_text: str,
        audio_text: str,
        hook_score: float,
        payoff_score: float,
        clarity_score: float,
        duration: float,
        filler_signal: float,
        pattern_interrupt: str,
    ) -> BobaRetentionRiskReviewV1:
        slow_start = bool(
            _contains(current_text, _SLOW_START_CUES)
            or _contains(warning_text, _SLOW_START_CUES)
            or (hook_score < 50.0 and duration > 25.0)
        )
        unclear_context = bool(
            editorial_risk.get("missing_context")
            or discovery.get("context_needed") is True
            or _contains(warning_text, _UNCLEAR_CONTEXT_CUES)
            or clarity_score < 45.0
        )
        weak_payoff = bool(
            editorial_risk.get("weak_payoff")
            or discovery.get("payoff_present") is False
            or _contains(warning_text, _WEAK_PAYOFF_CUES)
            or payoff_score < 45.0
        )
        filler = bool(
            editorial_risk.get("filler_risk")
            or _contains(warning_text, _FILLER_CUES)
            or filler_signal >= 0.55
        )
        over_editing = bool(
            _contains(motion_text, _OVER_EDITING_CUES)
            or _contains(warning_text, _OVER_EDITING_CUES)
        )
        pattern_missing = not pattern_interrupt or pattern_interrupt.casefold() in {
            "none",
            "not available",
        }
        under_editing = bool(
            (pattern_missing and hook_score < 60.0)
            or (
                ("static" in current_text or "minimal" in motion_text)
                and hook_score < 55.0
            )
        )
        caption_overload = _contains(
            f"{caption_text} {warning_text}", _CAPTION_OVERLOAD_CUES
        )
        audio_distraction = bool(
            editorial_risk.get("audio_risk")
            or _contains(audio_text, _AUDIO_DISTRACTION_CUES)
        )
        risk_fixes = _unique(
            [
                *(
                    ["Start on the strongest supported claim or tension; remove broad setup."]
                    if slow_start
                    else []
                ),
                *(
                    [
                        "Add only the minimum context needed to understand the hook, then "
                        "return to forward motion."
                    ]
                    if unclear_context
                    else []
                ),
                *(
                    [
                        "Preserve the confirmed payoff and do not end the clip before it "
                        "lands."
                    ]
                    if weak_payoff
                    else []
                ),
                *(
                    ["Remove repeated setup and filler without changing source meaning."]
                    if filler
                    else []
                ),
                *(
                    ["Use one intentional emphasis at a time; protect speech and readability."]
                    if over_editing
                    else []
                ),
                *(
                    [
                        "Add one restrained opening pattern interrupt and one payoff "
                        "emphasis instead of leaving the clip visually flat."
                    ]
                    if under_editing
                    else []
                ),
                *(
                    ["Shorten the first caption and keep one readable idea per beat."]
                    if caption_overload
                    else []
                ),
                *(
                    ["Keep music and SFX subordinate to speech; remove distracting sounds."]
                    if audio_distraction
                    else []
                ),
            ],
            limit=24,
            maximum=700,
        )
        blockers = _unique(
            [
                *_list(editorial_risk.get("blockers")),
                *[
                    _text(item.get("reason"), maximum=500)
                    for item in (
                        _dict(value)
                        for value in _list(brief.get("editor_checklist"))
                    )
                    if item.get("status") == "blocked"
                ],
            ],
            limit=24,
        )
        warnings = _unique(
            [
                *(
                    ["Slow-start risk may cause the opening promise to arrive too late."]
                    if slow_start
                    else []
                ),
                *(
                    ["Context is not fully self-contained in the saved evidence."]
                    if unclear_context
                    else []
                ),
                *(
                    ["The saved evidence does not confirm a strong complete payoff."]
                    if weak_payoff
                    else []
                ),
                *(
                    ["Filler or repetition may weaken the middle hold."]
                    if filler
                    else []
                ),
                *(
                    ["Motion or effect density may compete with comprehension."]
                    if over_editing
                    else []
                ),
                *(
                    ["The opening may remain visually static without one clear emphasis."]
                    if under_editing
                    else []
                ),
                *(
                    ["Caption density may reduce first-three-second readability."]
                    if caption_overload
                    else []
                ),
                *(
                    ["Audio or SFX guidance may distract from important speech."]
                    if audio_distraction
                    else []
                ),
                *_list(ranking.get("risk_warnings"))[:4],
            ],
            limit=32,
            maximum=700,
        )
        return BobaRetentionRiskReviewV1(
            slow_start_risk=slow_start,
            unclear_context_risk=unclear_context,
            weak_payoff_risk=weak_payoff,
            filler_risk=filler,
            over_editing_risk=over_editing,
            under_editing_risk=under_editing,
            caption_overload_risk=caption_overload,
            audio_distraction_risk=audio_distraction,
            risk_fixes=risk_fixes,
            blockers=blockers,
            warnings=warnings,
        )

    def _retention_plan(
        self,
        *,
        brief: dict[str, Any],
        opening_instruction: dict[str, Any],
        retention_instruction: dict[str, Any],
        pacing_map: dict[str, Any],
        retention_v2: dict[str, Any],
        risks: BobaRetentionRiskReviewV1,
        improved_hook: str,
        payoff_score: float,
    ) -> BobaRetentionPlanV1:
        seconds_0_to_3 = _text(
            pacing_map.get("first_3_seconds")
            or opening_instruction.get("do_this")
            or improved_hook,
            maximum=800,
        )
        seconds_3_to_10 = _text(
            pacing_map.get("seconds_3_to_10")
            or "Give only the context needed to understand the saved angle while "
            "keeping the central question open.",
            maximum=800,
        )
        middle = _text(
            pacing_map.get("middle_section")
            or retention_v2.get("mid_clip_hold")
            or retention_instruction.get("do_this")
            or "Advance one new idea per beat and remove repetition without changing meaning.",
            maximum=800,
        )
        payoff = _text(
            pacing_map.get("payoff_section")
            or retention_v2.get("payoff_delivery")
            or (
                "Deliver the confirmed payoff in the final 20% and leave enough tail "
                "for the thought to finish."
            ),
            maximum=800,
        )
        ending = _text(
            pacing_map.get("ending")
            or retention_v2.get("replay_trigger")
            or "End on the clearest supported final line or visual echo; do not invent "
            "a new claim.",
            maximum=800,
        )
        pacing_notes = _unique(
            [
                pacing_map.get("pacing_intensity")
                and f"Pacing intensity: {pacing_map.get('pacing_intensity')}.",
                *_list(pacing_map.get("filler_cut_notes")),
                *risks.risk_fixes,
            ],
            limit=20,
            maximum=600,
        )
        retention_tactics = _unique(
            [
                retention_v2.get("opening_hook"),
                retention_v2.get("curiosity_loop"),
                retention_v2.get("mid_clip_hold"),
                retention_v2.get("payoff_delivery"),
                retention_v2.get("replay_trigger"),
                retention_instruction.get("summary"),
                *(
                    [
                        "Have a human verify that the payoff exists before delaying it."
                    ]
                    if payoff_score < 45.0
                    else []
                ),
                "Keep source meaning intact and verify the complete thought before production.",
            ],
            limit=24,
            maximum=700,
        )
        return BobaRetentionPlanV1(
            seconds_0_to_3=seconds_0_to_3,
            seconds_3_to_10=seconds_3_to_10,
            middle_hold_strategy=middle,
            payoff_timing_strategy=payoff,
            ending_replay_trigger=ending,
            pacing_notes=pacing_notes,
            retention_tactics=retention_tactics,
        )

    def _alternatives(
        self,
        *,
        candidate_id: str,
        hook_type: BobaHookType,
        angle: str,
        opening_line: str,
        visual_opening: str,
        hook_score: float,
        clarity_score: float,
        improved_hook: str,
    ) -> list[BobaHookAlternativeV1]:
        safe_angle = angle or "the verified saved clip angle"
        bold_type: BobaHookType = (
            "contradiction"
            if hook_type not in {"contradiction", "shocking_truth", "mystery", "tension"}
            else hook_type
        )
        alternatives = [
            BobaHookAlternativeV1(
                alternative_id=f"hook_alt_{candidate_id}_best",
                hook_type=hook_type,
                opening_line_direction=improved_hook,
                caption_direction=(
                    "Use one short first caption that names the strongest supported hook "
                    "word from the saved angle."
                ),
                visual_direction=visual_opening,
                strength_score=_clamp(max(hook_score, clarity_score) + 6.0),
                risk_score=_clamp(22.0 + max(0.0, 55.0 - clarity_score) * 0.4),
                why_it_may_work=(
                    "It preserves the existing BOBA angle while moving the promise or "
                    "tension into the first three seconds."
                ),
                why_it_may_fail=(
                    "It still requires source review; an unsupported or incomplete opening "
                    "would weaken clarity."
                ),
                recommendation_label="best",
            ),
            BobaHookAlternativeV1(
                alternative_id=f"hook_alt_{candidate_id}_safest",
                hook_type="direct_value",
                opening_line_direction=(
                    "State the verified viewer value immediately using only this saved "
                    f"angle: {safe_angle}"
                ),
                caption_direction=(
                    "Use a literal, readable value statement with no superlative or "
                    "unsupported promise."
                ),
                visual_direction=(
                    "Open on the clearest stable subject and avoid distracting effects."
                ),
                strength_score=_clamp(0.55 * hook_score + 0.45 * clarity_score),
                risk_score=12.0,
                why_it_may_work=(
                    "Direct value minimizes confusion and stays closest to the saved evidence."
                ),
                why_it_may_fail=(
                    "It may create less curiosity than a tension-led opening if the value "
                    "statement is generic."
                ),
                recommendation_label="safest",
            ),
            BobaHookAlternativeV1(
                alternative_id=f"hook_alt_{candidate_id}_boldest",
                hook_type=bold_type,
                opening_line_direction=(
                    "Lead with the strongest supported contrast already present in the "
                    f"saved angle, then resolve it without adding facts: {safe_angle}"
                ),
                caption_direction=(
                    "Highlight the contrast in one short caption; avoid clickbait or "
                    "absolute claims."
                ),
                visual_direction=(
                    "Use one restrained punch-in or visual change on the supported contrast."
                ),
                strength_score=_clamp(hook_score + 10.0),
                risk_score=_clamp(46.0 + max(0.0, 60.0 - clarity_score) * 0.5),
                why_it_may_work=(
                    "A supported contrast can create immediate tension and a clear reason "
                    "to continue."
                ),
                why_it_may_fail=(
                    "If the source does not clearly support the contrast, it can become "
                    "misleading; human verification is required."
                ),
                recommendation_label="boldest",
            ),
            BobaHookAlternativeV1(
                alternative_id=f"hook_alt_{candidate_id}_backup",
                hook_type="educational_open_loop",
                opening_line_direction=(
                    "Frame the saved angle as one practical question, give only essential "
                    f"context, and resolve it at the confirmed payoff: {safe_angle}"
                ),
                caption_direction=(
                    "Caption the question first, then reserve the answer wording for the payoff."
                ),
                visual_direction=(
                    "Keep the subject stable while one simple emphasis marks the open loop."
                ),
                strength_score=_clamp(0.7 * hook_score + 0.3 * 62.0),
                risk_score=24.0,
                why_it_may_work=(
                    "It creates a structured knowledge gap without changing the source claim."
                ),
                why_it_may_fail=(
                    "It can feel formulaic if the saved payoff is weak or already stated."
                ),
                recommendation_label="backup",
            ),
            BobaHookAlternativeV1(
                alternative_id=f"hook_alt_{candidate_id}_avoid",
                hook_type="unknown",
                opening_line_direction=(
                    "Avoid a generic teaser, unsupported superlative, or delayed introduction "
                    f"before this saved angle: {safe_angle}"
                ),
                caption_direction=(
                    "Do not use vague clickbait text such as an unverified absolute promise."
                ),
                visual_direction=(
                    "Do not hide a weak opening behind constant zooms, flashes, or noisy effects."
                ),
                strength_score=_clamp(hook_score - 30.0),
                risk_score=88.0,
                why_it_may_work=(
                    "A vague teaser might briefly attract attention, but no benefit is "
                    "supported by the saved evidence."
                ),
                why_it_may_fail=(
                    "It risks confusion, mistrust, unsupported claims, and a delayed value "
                    "promise."
                ),
                recommendation_label="avoid",
            ),
        ]
        return alternatives

    @staticmethod
    def _hook_type(value: Any) -> BobaHookType:
        normalized = _text(value, maximum=500).casefold().replace("-", "_")
        normalized = "_".join(normalized.split())
        if normalized in _HOOK_TYPES:
            return normalized  # type: ignore[return-value]
        mappings: tuple[tuple[tuple[str, ...], BobaHookType], ...] = (
            (("humor", "funny", "joke", "laugh"), "humor"),
            (("contrad", "opposite", "myth"), "contradiction"),
            (("shock", "truth", "nobody"), "shocking_truth"),
            (("problem", "solution"), "problem_solution"),
            (("motivat", "transform", "payoff"), "motivational_payoff"),
            (("emotion", "reveal", "personal"), "emotional_reveal"),
            (("story", "turn"), "story_turn"),
            (("educat", "learn", "lesson"), "educational_open_loop"),
            (("mystery", "unknown", "secret"), "mystery"),
            (("tension", "risk", "struggle"), "tension"),
            (("direct", "value", "how to"), "direct_value"),
            (("curiosity", "question", "why", "how"), "curiosity_gap"),
        )
        for cues, hook_type in mappings:
            if any(cue in normalized for cue in cues):
                return hook_type
        return "unknown"

    @staticmethod
    def _hook_risk(
        risks: BobaRetentionRiskReviewV1, hook_score: float
    ) -> str:
        active = [
            label
            for enabled, label in (
                (risks.slow_start_risk, "slow start"),
                (risks.unclear_context_risk, "unclear context"),
                (risks.weak_payoff_risk, "weak payoff"),
                (risks.under_editing_risk, "static opening"),
                (risks.caption_overload_risk, "caption overload"),
                (risks.audio_distraction_risk, "audio distraction"),
            )
            if enabled
        ]
        if active:
            return _text(
                "Human review required for " + ", ".join(active) + ".", maximum=700
            )
        if hook_score < 60.0:
            return "The opening is usable but not yet distinctive; strengthen it before production."
        return (
            "No major hook-specific risk was detected from saved metadata; "
            "verify against source."
        )

    @staticmethod
    def _improved_hook_direction(
        *,
        hook_type: BobaHookType,
        angle: str,
        opening_line: str,
        risks: BobaRetentionRiskReviewV1,
    ) -> str:
        source_angle = angle or opening_line
        if risks.slow_start_risk:
            return _text(
                "Start closer to the strongest supported tension or payoff, then add only "
                f"essential context: {source_angle}",
                maximum=800,
            )
        if risks.unclear_context_risk:
            return _text(
                "Open with a plain-language value promise, add one context clause, and "
                f"preserve the saved angle: {source_angle}",
                maximum=800,
            )
        if hook_type in {"contradiction", "shocking_truth", "tension", "mystery"}:
            return _text(
                "Lead with the supported contrast or tension before explanation, without "
                f"adding claims: {source_angle}",
                maximum=800,
            )
        return _text(
            "Deliver the saved hook direction in the first sentence, foreground the viewer "
            f"value, and leave the confirmed payoff unresolved: {opening_line}",
            maximum=800,
        )

    @staticmethod
    def _hook_reason(
        hook_score: float,
        curiosity_score: float,
        clarity_score: float,
        explanations: Sequence[Mapping[str, Any]],
        risks: BobaRetentionRiskReviewV1,
    ) -> str:
        evidence_note = (
            "Saved BOBA explanation evidence was available."
            if explanations
            else "No separate explanation evidence was available, so brief metadata was used."
        )
        risk_count = sum(
            (
                risks.slow_start_risk,
                risks.unclear_context_risk,
                risks.weak_payoff_risk,
                risks.under_editing_risk,
            )
        )
        return _text(
            f"Bounded hook {hook_score:.1f}/100, curiosity {curiosity_score:.1f}/100, "
            f"and first-three-second clarity {clarity_score:.1f}/100 were combined from "
            f"saved local guidance. {risk_count} primary opening risk(s) were detected. "
            f"{evidence_note}",
            maximum=1000,
        )

    @staticmethod
    def _enhanced_pattern_interrupt(
        pattern_interrupt: str, risks: BobaRetentionRiskReviewV1
    ) -> str:
        if risks.over_editing_risk:
            return "Reduce to one clean opening emphasis; remove competing motion and effects."
        if risks.under_editing_risk:
            return (
                "Add one restrained punch-in or keyword reveal on the strongest supported "
                "hook beat."
            )
        return _text(
            f"Keep one intentional opening emphasis: {pattern_interrupt}", maximum=700
        )

    @staticmethod
    def _enhanced_caption(
        caption_instruction: Mapping[str, Any], hook_type: BobaHookType
    ) -> str:
        existing = _text(
            caption_instruction.get("do_this")
            or caption_instruction.get("summary"),
            maximum=450,
        )
        return _text(
            "Use one short, readable first caption with the strongest supported keyword; "
            f"treat it as a {hook_type.replace('_', ' ')} hook. {existing}",
            maximum=600,
        )

    @staticmethod
    def _enhanced_payoff_timing(
        payoff: str, risks: BobaRetentionRiskReviewV1
    ) -> str:
        if risks.weak_payoff_risk:
            return (
                "Do not promise or delay an unconfirmed payoff; verify the source and "
                "preserve the complete supported ending first."
            )
        return _text(
            f"Keep the payoff unresolved until the final 20% when source meaning allows. {payoff}",
            maximum=700,
        )

    @staticmethod
    def _virality_by_id(virality: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for key in (
            "candidates",
            "ranked_candidates",
            "analyses",
            "clips",
            "clip_scores",
            "results",
        ):
            for value in _list(virality.get(key)):
                item = _dict(value)
                identifier = _text(
                    item.get("candidate_id") or item.get("clip_id") or item.get("id"),
                    maximum=128,
                )
                if identifier:
                    result[identifier] = item
        return result

    @staticmethod
    def _project_summary(
        analyses: Sequence[BobaHookRetentionAnalysisV1],
    ) -> str:
        if not analyses:
            return (
                "No selected clip briefs were available, so BOBA produced no hook or "
                "retention ranking. Generate selected clip briefs and retry."
            )
        ordered = sorted(
            analyses,
            key=lambda item: (
                item.retention_score.hook_score,
                item.retention_score.overall_retention_score,
                item.candidate_id,
            ),
            reverse=True,
        )
        strongest = ", ".join(item.candidate_id for item in ordered[:2])
        weakest_items = sorted(
            analyses,
            key=lambda item: (
                item.retention_score.hook_score,
                item.retention_score.overall_retention_score,
                item.candidate_id,
            ),
        )[:2]
        weakest = ", ".join(item.candidate_id for item in weakest_items)
        risk_counter: Counter[str] = Counter()
        revision_ids: list[str] = []
        for item in analyses:
            review = item.retention_risk_review
            for enabled, label in (
                (review.slow_start_risk, "slow start"),
                (review.unclear_context_risk, "unclear context"),
                (review.weak_payoff_risk, "weak payoff"),
                (review.filler_risk, "filler"),
                (review.over_editing_risk, "over-editing"),
                (review.under_editing_risk, "under-editing"),
                (review.caption_overload_risk, "caption overload"),
                (review.audio_distraction_risk, "audio distraction"),
            ):
                if enabled:
                    risk_counter[label] += 1
            if (
                item.retention_score.hook_score < 60.0
                or item.retention_score.dropoff_risk_score >= 35.0
            ):
                revision_ids.append(item.candidate_id)
        common_risks = ", ".join(
            f"{label} ({count})" for label, count in risk_counter.most_common(4)
        )
        return _text(
            f"Strongest bounded hooks: {strongest}. Weakest hooks: {weakest}. "
            f"Common drop-off risks: {common_risks or 'none detected from saved metadata'}. "
            f"Hook revision recommended for: {', '.join(revision_ids) or 'none'}. "
            "Human checks: verify every opening against source evidence, confirm essential "
            "context and payoff, protect caption readability and speech, and review the "
            "final edit before production.",
            maximum=1500,
        )

    @staticmethod
    def _validate_project(
        project_id: str, artifact: Mapping[str, Any], label: str
    ) -> None:
        if not artifact:
            return
        artifact_project = _text(artifact.get("project_id"), maximum=128)
        if artifact_project and artifact_project != project_id:
            raise ValidationError(
                f"BOBA {label} belongs to a different project.",
                details={
                    "project_id": project_id,
                    "artifact_project_id": artifact_project,
                    "artifact": label,
                },
            )

"""Explainable advisory ranking over existing Olympus planning candidates."""

from __future__ import annotations

from typing import Any

from olympus.boba.contracts import BobaCandidateInsightV1, BobaClipRankingV1


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _time(candidate: dict[str, Any], primary: str, fallback: str) -> float:
    try:
        return max(0.0, float(candidate.get(primary, candidate.get(fallback, 0.0))))
    except (TypeError, ValueError):
        return 0.0


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    intersection = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return 0.0 if union <= 0 else intersection / union


def _signals(candidate: dict[str, Any]) -> dict[str, float]:
    scores = _dict(candidate.get("scores"))
    blueprint = _dict(candidate.get("blueprint"))
    viral = _dict(blueprint.get("viral_score_v2"))
    story = _dict(blueprint.get("story_v2_guidance"))
    hook = _dict(blueprint.get("hook_analysis_v2") or blueprint.get("hook_v2"))
    return {
        "hook": _number(scores.get("hook", viral.get("hook_score", hook.get("score")))),
        "story": _number(
            scores.get("story_completion", story.get("completeness_score", scores.get("story")))
        ),
        "payoff": _number(scores.get("payoff", story.get("payoff_strength"))),
        "curiosity": _number(scores.get("curiosity", hook.get("curiosity_strength"))),
        "emotion": _number(scores.get("emotion")),
        "context": _number(story.get("context_risk", candidate.get("context_requirement"))),
        "editing": _number(
            candidate.get("editing_opportunity", 1.0 - _number(scores.get("editing_complexity")))
        ),
        "safety": _number(candidate.get("safety_risk")),
        "creator": _number(scores.get("creator_fit", candidate.get("creator_fit", 0.5)), 0.5),
        "trend": _number(scores.get("trend_fit", candidate.get("trend_fit"))),
        "boundary": _number(candidate.get("boundary_quality", 0.65), 0.65),
    }


def rank_candidates(
    project_id: str,
    candidates: list[dict[str, Any]],
    *,
    used_source_ranges: list[dict[str, Any]] | None = None,
) -> BobaClipRankingV1:
    used = [
        (_time(item, "start", "source_start"), _time(item, "end", "source_end"))
        for item in (used_source_ranges or [])
    ]
    spans = [
        (_time(item, "source_start", "start"), _time(item, "source_end", "end"))
        for item in candidates
    ]
    preliminary_quality = [
        sum(_signals(candidate)[name] for name in ("hook", "story", "payoff"))
        for candidate in candidates
    ]
    duplicate_groups: list[list[str]] = []
    duplicate_risks = [0.0] * len(candidates)
    for index, span in enumerate(spans):
        group = [str(candidates[index].get("candidate_id") or f"candidate_{index}")]
        duplicate_risks[index] = max((_overlap(span, prior) for prior in used), default=0.0)
        for other in range(index):
            overlap = _overlap(span, spans[other])
            if overlap >= 0.55:
                weaker = (
                    index
                    if preliminary_quality[index] <= preliminary_quality[other]
                    else other
                )
                duplicate_risks[weaker] = max(duplicate_risks[weaker], overlap)
                group.append(str(candidates[other].get("candidate_id") or f"candidate_{other}"))
        if len(group) > 1:
            normalized = sorted(set(group))
            if normalized not in duplicate_groups:
                duplicate_groups.append(normalized)

    insights: list[BobaCandidateInsightV1] = []
    for index, candidate in enumerate(candidates):
        signal = _signals(candidate)
        start, end = spans[index]
        duration = max(0.0, end - start)
        duplicate = duplicate_risks[index]
        recommendation = (
            0.17 * signal["hook"]
            + 0.18 * signal["story"]
            + 0.15 * signal["payoff"]
            + 0.08 * signal["curiosity"]
            + 0.07 * signal["emotion"]
            + 0.08 * (1.0 - signal["context"])
            + 0.06 * (1.0 - duplicate)
            + 0.05 * signal["editing"]
            + 0.04 * (1.0 - signal["safety"])
            + 0.04 * signal["creator"]
            + 0.04 * signal["trend"]
            + 0.04 * signal["boundary"]
        )
        candidate_warnings: list[str] = []
        reasons: list[str] = []
        if signal["hook"] >= 0.65:
            reasons.append("clear hook evidence in the opening")
        if signal["story"] >= 0.6:
            reasons.append("complete story arc")
        if signal["payoff"] >= 0.6:
            reasons.append("payoff is preserved")
        else:
            candidate_warnings.append("weak or missing payoff")
        if signal["context"] > 0.55:
            candidate_warnings.append("high context requirement")
        if duplicate >= 0.55:
            candidate_warnings.append("overlaps a stronger or already-used source range")
        if signal["safety"] >= 0.7:
            candidate_warnings.append("safety or manual-review risk is high")
        boundary_risk = bool(
            candidate.get("ends_mid_sentence")
            or candidate.get("boundary_risk")
            or signal["boundary"] < 0.4
        )
        if boundary_risk:
            candidate_warnings.append("boundary may cut a sentence or payoff")
        if duration and duration < 8:
            candidate_warnings.append("candidate is unusually short")
        if not reasons:
            reasons.append("usable only as a lower-confidence editorial option")
        blueprint = _dict(candidate.get("blueprint"))
        hook_data = _dict(blueprint.get("hook_analysis_v2") or blueprint.get("hook_v2"))
        story_data = _dict(blueprint.get("story_v2_guidance"))
        insights.append(
            BobaCandidateInsightV1(
                candidate_id=str(
                    candidate.get("candidate_id")
                    or candidate.get("id")
                    or f"candidate_{index}"
                ),
                clip_id=str(candidate.get("clip_id") or candidate.get("id") or "") or None,
                source_start=round(start, 3),
                source_end=round(end, 3),
                duration=round(duration, 3),
                hook_summary=str(
                    candidate.get("hook_line") or hook_data.get("hook_line") or ""
                )[:300],
                payoff_summary=str(
                    candidate.get("payoff_line") or story_data.get("payoff") or ""
                )[:300],
                story_completeness=round(signal["story"], 3),
                curiosity_strength=round(signal["curiosity"], 3),
                emotional_strength=round(signal["emotion"], 3),
                context_requirement=round(signal["context"], 3),
                duplicate_risk=round(duplicate, 3),
                editing_opportunity=round(signal["editing"], 3),
                safety_risk=round(signal["safety"], 3),
                creator_fit=round(signal["creator"], 3),
                trend_fit=round(signal["trend"], 3),
                overall_recommendation=round(max(0.0, min(1.0, recommendation)), 3),
                reasons=reasons,
                warnings=candidate_warnings,
            )
        )

    ordered = sorted(insights, key=lambda item: item.overall_recommendation, reverse=True)
    rejected = [
        item
        for item in ordered
        if item.overall_recommendation < 0.4
        or item.safety_risk >= 0.85
        or item.duplicate_risk >= 0.8
    ]
    ranked = [item for item in ordered if item not in rejected]
    timeline_bins = sorted({int(item.source_start // 300) for item in ranked})
    ranking_warnings: list[str] = []
    if len(ranked) > 1 and len(timeline_bins) == 1:
        ranking_warnings.append("Recommended clips cluster in one source-timeline region.")
    if not ranked and candidates:
        ranking_warnings.append(
            "No candidate cleared BOBA's advisory quality and safety floor."
        )
    return BobaClipRankingV1(
        project_id=project_id,
        candidate_count=len(candidates),
        ranked_candidates=ranked,
        rejected_candidates=rejected,
        duplicate_groups=duplicate_groups,
        coverage_summary={
            "recommended_count": len(ranked),
            "rejected_count": len(rejected),
            "timeline_regions": timeline_bins,
            "first_start": ranked[0].source_start if ranked else None,
            "last_end": max((item.source_end for item in ranked), default=None),
        },
        reasoning_summary=(
            "BOBA ranked candidates by hook, complete story, payoff, context independence, "
            "diversity, safety, creator fit, trend fit, editing opportunity, and boundary quality."
        ),
        warnings=ranking_warnings,
    )

"""The seven Clip Planner stages.

Each stage is an isolated, replaceable module behind the :class:`PlanningAnalyzer`
contract. None imports another; they communicate only through the structured
:class:`PlanningStageContext`. Together they turn the Cognitive + Story +
Virality outputs into ranked, fully-specified editing blueprints.

Honesty rules (enforced by construction):
- When the evidence needed to locate clip-worthy moments is missing, a stage
  returns ``UNAVAILABLE`` with a detailed reason. The planner never forces a clip
  into existence; it returns **zero clips with an explanation** when appropriate.
- Every plan, boundary, score, and recommendation carries confidence and the
  supporting evidence it was derived from.
- The summary always completes, honestly reporting the plan count (possibly zero),
  the reason, and which upstream signals were available vs. pending.
"""

from __future__ import annotations

from typing import Any

from olympus.domain.contracts.planning import (
    PlanningAnalyzer,
    PlanningOutcome,
    PlanningProgressReporter,
    PlanningStageContext,
)
from olympus.integration import clip_intelligence as CI  # noqa: N812 (module alias is intentional)
from olympus.personalization import apply as P  # noqa: N812 (module alias is intentional)
from olympus.planning import boundary_quality as BQ  # noqa: N812 (module alias is intentional)
from olympus.planning import scoring as S  # noqa: N812 (module alias is intentional)
from olympus.planning import v2 as V2  # noqa: N812 (module alias is intentional)
from olympus.platform.config import get_settings
from olympus.trends import build_editing_trend_guidance

# Tunable, transparent thresholds.
MIN_CLIP_SECONDS = 8.0
MAX_CLIP_SECONDS = 75.0
HEAT_THRESHOLD = 0.45
DUPLICATE_IOU = 0.5
_PLATFORM_SPECS = {
    "youtube_shorts": (15.0, 45.0, 180.0),
    "tiktok": (15.0, 60.0, 600.0),
    "instagram_reels": (15.0, 30.0, 90.0),
}

_NO_SIGNALS = (
    "The Clip Planner needs localized signals to locate clip-worthy moments - a "
    "Virality heatmap, Story payoffs, or a transcript - none of which are "
    "available for this video (no transcript was produced upstream). No clips are "
    "invented without evidence."
)


# --------------------------------------------------------------------------- #
# Small local helpers (pure)
# --------------------------------------------------------------------------- #
def _seg_start(seg: dict[str, Any]) -> float:
    return S.as_float(seg.get("start"))


def _seg_end(seg: dict[str, Any]) -> float:
    end = seg.get("end")
    return S.as_float(end) if end is not None else _seg_start(seg)


def _seg_text(seg: dict[str, Any]) -> str:
    return S.as_str(seg.get("text"))


def _heat_runs(heatmap: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    """Contiguous runs of heatmap cells at/above ``threshold`` -> candidate spans."""

    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for cell in heatmap:
        heat = S.as_float(cell.get("heat"))
        if heat >= threshold:
            if current is None:
                current = {
                    "start": S.as_float(cell.get("start")),
                    "end": S.as_float(cell.get("end")),
                    "peak": heat,
                }
            else:
                current["end"] = S.as_float(cell.get("end"))
                current["peak"] = max(current["peak"], heat)
        elif current is not None:
            runs.append(current)
            current = None
    if current is not None:
        runs.append(current)
    return runs


def _platform_suitability(duration: float, vertical: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for plat, (lo, hi, hard) in _PLATFORM_SPECS.items():
        if lo <= duration <= hi:
            fit = 1.0
        elif duration < lo:
            fit = S.clamp01(duration / lo)
        elif duration <= hard:
            fit = S.clamp01(1.0 - (duration - hi) / (hard - hi))
        else:
            fit = 0.0
        score = S.clamp01(fit + (0.0 if not vertical else 0.1))
        out[plat] = {
            "score": S.round3(score),
            "reason": f"{int(duration)}s vs ideal {int(lo)}-{int(hi)}s; "
            + ("vertical" if vertical else "needs reframing to vertical"),
        }
    return out


def _candidate_coverage(candidates: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    """Summarise where candidate windows landed across the source timeline."""

    if not candidates or duration <= 0:
        return {"coverage_ratio": 0.0, "first_timestamp": None, "last_timestamp": None}
    starts = [S.as_float(c.get("raw_start")) for c in candidates]
    ends = [S.as_float(c.get("raw_end")) for c in candidates]
    covered = sum(max(0.0, e - s) for s, e in zip(starts, ends, strict=False))
    return {
        "coverage_ratio": S.round3(min(1.0, covered / duration)),
        "first_timestamp": S.round3(min(starts)),
        "last_timestamp": S.round3(max(ends)),
        "source_count": {
            source: sum(1 for c in candidates if c.get("source") == source)
            for source in sorted({S.as_str(c.get("source")) for c in candidates})
        },
    }


# --------------------------------------------------------------------------- #
# 1. Candidate Generation - find clip-worthy moments from upstream signals.
# --------------------------------------------------------------------------- #
class CandidateGenerationAnalyzer(PlanningAnalyzer):
    name = "candidate_generation"
    version = "4"

    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        summary = ctx.virality_data("virality_summary") or {}
        heatmap = S.as_list(summary.get("heatmap"))
        payoffs = S.as_list((ctx.story_data("payoff_detection") or {}).get("relationships"))
        story_v2 = ctx.story_data("story_analysis_v2") or {}
        hook = ctx.story_data("hook_detection") or {}
        segments = ctx.transcript_segments() or []

        if not heatmap and not payoffs and not segments:
            return PlanningOutcome.unavailable(_NO_SIGNALS)

        duration = ctx.video_duration() or (segments and _seg_end(segments[-1])) or 0.0
        strategy = V2.clip_count_strategy(duration, ctx.project.desired_clip_count)
        transcript_text = " ".join(_seg_text(seg) for seg in segments)
        trend_stage = ctx.virality_data("trend_research") or {}
        trend_snapshot = trend_stage.get("internet_trend_research_v2")
        viral_research = (
            trend_snapshot if isinstance(trend_snapshot, dict) else {}
        )
        detected_niche = viral_research.get("detected_niche")
        content_niche = (
            detected_niche
            if isinstance(detected_niche, dict)
            else V2.detect_content_niche(transcript_text, ctx.project.content_category)
        )
        if not viral_research:
            viral_research = V2.viral_research_snapshot(content_niche)
        candidates: list[dict[str, Any]] = []

        # (a) High-heat regions from the virality heatmap.
        for run in _heat_runs(heatmap, HEAT_THRESHOLD):
            candidates.append(
                {
                    "raw_start": run["start"],
                    "raw_end": run["end"],
                    "source": "heat_region",
                    "candidate_type": "heat_region",
                    "peak_heat": S.round3(run["peak"]),
                    "evidence": [
                        {
                            "type": "heat_region",
                            "detail": f"peak heat {S.round3(run['peak'])}",
                            "timestamp": run["start"],
                        }
                    ],
                }
            )

        # (b) Self-contained arcs from story setup->payoff relationships.
        for rel in payoffs:
            s = S.as_float(rel.get("setup_timestamp"))
            e = S.as_float(rel.get("payoff_timestamp")) + 3.0
            if e > s:
                candidates.append(
                    {
                        "raw_start": max(0.0, s - 1.0),
                        "raw_end": e,
                        "source": "payoff_arc",
                        "candidate_type": "payoff_arc",
                        "peak_heat": None,
                        "evidence": [
                            {
                                "type": "payoff_arc",
                                "timestamp": s,
                                "detail": S.as_str(rel.get("payoff_excerpt"))[:120],
                            }
                        ],
                    }
                )

        # (c) Story V2 complete micro-stories. These become first-class
        # candidates when available, but legacy signals remain valid fallback.
        story_candidates = []
        if CI.story_v2_available(story_v2):
            for story in CI.story_recommendations(story_v2)[:20]:
                candidate = CI.story_candidate(story, story_v2)
                if candidate["raw_end"] > candidate["raw_start"]:
                    story_candidates.append(candidate)
            candidates.extend(story_candidates)

        # (c) The opening hook (a natural self-contained clip start).
        if hook.get("has_hook"):
            window = S.as_dict(hook.get("window"))
            hs = S.as_float(window.get("start"))
            candidates.append(
                {
                    "raw_start": hs,
                    "raw_end": hs + 30.0,
                    "source": "hook",
                    "candidate_type": "hook",
                    "peak_heat": None,
                    "evidence": [
                        {"type": "hook", "timestamp": hs, "detail": S.as_str(hook.get("why"))}
                    ],
                }
            )

        # (d) V2 transcript windows across the full video, used when sparse
        # heat/payoff/hook signals would otherwise collapse the output to one
        # clip. These still come from real transcript spans and carry evidence.
        if segments:
            candidates.extend(
                V2.transcript_window_candidates(
                    segments,
                    duration_seconds=float(duration),
                    target=strategy.target,
                    existing=candidates,
                    strategy=strategy,
                    research_snapshot=viral_research,
                    content_niche=content_niche,
                )
            )

        candidates = [
            V2.enrich_candidate(
                candidate,
                segments,
                viral_research,
                content_niche,
                float(duration),
            )
            for candidate in candidates
        ]
        if CI.story_v2_available(story_v2):
            for candidate in candidates:
                guidance = S.as_dict(candidate.get("story_v2_guidance"))
                if not guidance.get("story_guidance_used"):
                    guidance = CI.story_guidance_for_window(
                        story_v2,
                        S.as_float(candidate.get("raw_start")),
                        S.as_float(candidate.get("raw_end")),
                    )
                    if guidance.get("story_guidance_used"):
                        candidate["story_v2_guidance"] = guidance
                        candidate["story_id"] = guidance.get("story_id")
                        candidate.setdefault("evidence", []).append(
                            {
                                "type": "story_analysis_v2",
                                "timestamp": guidance.get("recommended_start"),
                                "detail": "Candidate overlaps a Story V2 micro-story",
                            }
                        )

        report(1.0)
        return PlanningOutcome.completed(
            {
                "candidate_count": len(candidates),
                "candidates": candidates,
                "story_candidate_count": len(story_candidates),
                "story_guidance_available": CI.story_v2_available(story_v2),
                "video_duration": S.round3(float(duration)),
                "content_niche": content_niche,
                "viral_research_snapshot": viral_research,
                "internet_trend_research_v2": viral_research,
                "trend_guidance_source": (
                    "virality_v2_trend_research"
                    if isinstance(trend_snapshot, dict)
                    else "planning_compatibility_fallback"
                ),
                "internet_research_available": viral_research.get(
                    "internet_research_available", False
                ),
                "thresholds": {"heat_threshold": HEAT_THRESHOLD},
                "target_clip_strategy": V2.strategy_dict(strategy),
                "coverage": _candidate_coverage(candidates, float(duration)),
                "note": (
                    "Candidates are clip-worthy moments located from the virality "
                    "heatmap, story payoff arcs, the opening hook, and V2 multi-pass "
                    "transcript analysis across the full video, then enriched with "
                    "niche, research fallback, hook, story, ending, and trend metadata."
                    if candidates
                    else "No region met the heat threshold and no self-contained arcs "
                    "or hook were found, so no candidates were proposed."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 2. Boundary Refinement - snap to sentence/scene boundaries; exact frames.
# --------------------------------------------------------------------------- #
class BoundaryRefinementAnalyzer(PlanningAnalyzer):
    name = "boundary_refinement"
    version = "4"
    depends_on = ("candidate_generation",)

    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        gen = ctx.planning_data("candidate_generation")
        if gen is None:
            return PlanningOutcome.unavailable(
                "Requires candidate generation, which is unavailable."
            )
        candidates = S.as_list(gen.get("candidates"))
        segments = ctx.transcript_segments() or []
        fps = ctx.fps()
        duration = ctx.video_duration() or S.as_float(gen.get("video_duration"))
        story_v2 = ctx.story_data("story_analysis_v2") or {}
        hook_signal = ctx.story_data("hook_detection") or {}
        payoff_signals = S.as_list(
            (ctx.story_data("payoff_detection") or {}).get("relationships")
        )

        refined: list[dict[str, Any]] = []
        for candidate_index, cand in enumerate(candidates):
            original_start = S.as_float(cand.get("raw_start"))
            original_end = S.as_float(cand.get("raw_end"))
            raw_start, raw_end = original_start, original_end
            story_guidance = S.as_dict(cand.get("story_v2_guidance"))
            story_boundary_used = False
            if story_guidance.get("story_guidance_used") is True:
                story_start = CI.as_float(story_guidance.get("recommended_start"), raw_start)
                story_end = CI.as_float(story_guidance.get("recommended_end"), raw_end)
                if story_end > story_start:
                    raw_start, raw_end = story_start, story_end
                    story_boundary_used = True
            start, end = self._snap(raw_start, raw_end, segments, duration)
            boundary_optimization = V2.optimize_boundaries(start, end, segments, float(duration))
            start = S.as_float(boundary_optimization.get("optimized_start"), start)
            end = S.as_float(boundary_optimization.get("optimized_end"), end)
            boundary_quality = BQ.recommend_clip_boundaries(
                {
                    **cand,
                    "clip_id": cand.get("candidate_id") or cand.get("id"),
                    "requested_start_seconds": original_start,
                    "requested_end_seconds": original_end,
                    "start": start,
                    "end": end,
                },
                {
                    "project_id": ctx.project.id,
                    "transcript_segments": segments,
                    "story_analysis_v2": story_v2,
                    "story_guidance": story_guidance,
                    "hook_signal": hook_signal,
                    "payoff_signals": payoff_signals,
                    "overlap_ranges": [
                        {
                            "start": S.as_float(other.get("raw_start")),
                            "end": S.as_float(other.get("raw_end")),
                        }
                        for index, other in enumerate(candidates)
                        if index != candidate_index
                    ],
                    "source_duration_seconds": float(duration),
                    "minimum_duration_seconds": MIN_CLIP_SECONDS,
                    "maximum_duration_seconds": MAX_CLIP_SECONDS,
                },
            )
            boundary_quality_data = boundary_quality.to_dict()
            start = boundary_quality.recommended_start_seconds
            end = boundary_quality.recommended_end_seconds
            if end - start < MIN_CLIP_SECONDS:
                continue  # too short to be a viable Short after snapping
            refined.append(
                {
                    **cand,
                    "start": S.round3(start),
                    "end": S.round3(end),
                    "duration": S.round3(end - start),
                    "start_frame": round(start * fps),
                    "end_frame": round(end * fps),
                    "fps": fps,
                    "boundary_basis": (
                        "Story V2 boundary, then snapped to transcript sentence boundaries"
                        if story_boundary_used and segments
                        else (
                            "snapped to transcript sentence boundaries"
                            if segments
                            else "raw candidate boundaries (no transcript to snap to)"
                        )
                    ),
                    "boundary_optimization": boundary_optimization,
                    "boundary_quality": boundary_quality_data,
                    "boundary_quality_decision": boundary_quality_data.get("decision"),
                    "planning_story_integration": CI.build_planning_story_integration(
                        cand,
                        original_start=original_start,
                        original_end=original_end,
                        final_start=start,
                        final_end=end,
                        boundary_used=story_boundary_used,
                    ),
                }
            )

        report(1.0)
        return PlanningOutcome.completed(
            {
                "refined_count": len(refined),
                "candidates": refined,
                "fps": fps,
                "note": "Boundaries snapped to sentence edges and clamped to a viable "
                "short-form length, then scored and recommended for editorial hook/context/"
                "payoff completeness; exact frames are computed from the source fps.",
            }
        )

    def _snap(
        self, raw_start: float, raw_end: float, segments: list[dict[str, Any]], duration: float
    ) -> tuple[float, float]:
        start, end = raw_start, raw_end
        if segments:
            # Snap start back to the start of the containing/preceding segment.
            starts = [s for s in segments if _seg_start(s) <= raw_start]
            if starts:
                start = _seg_start(starts[-1])
            # Snap end forward to the end of the containing/following segment.
            ends = [s for s in segments if _seg_end(s) >= raw_end]
            if ends:
                end = _seg_end(ends[0])
        start = max(0.0, start)
        if duration:
            end = min(end, float(duration))
        # Clamp to the maximum short length at a sensible boundary.
        if end - start > MAX_CLIP_SECONDS:
            end = start + MAX_CLIP_SECONDS
            if segments:
                inside = [s for s in segments if _seg_end(s) <= end and _seg_end(s) > start]
                if inside:
                    end = _seg_end(inside[-1])
        return start, end


# --------------------------------------------------------------------------- #
# 3. Clip Scoring - multi-dimensional quality from localized real signals.
# --------------------------------------------------------------------------- #
class ClipScoringAnalyzer(PlanningAnalyzer):
    name = "clip_scoring"
    version = "5"
    depends_on = ("boundary_refinement",)

    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        refine = ctx.planning_data("boundary_refinement")
        if refine is None:
            return PlanningOutcome.unavailable(
                "Requires boundary refinement, which is unavailable."
            )
        candidates = S.as_list(refine.get("candidates"))
        signals = _gather_signals(ctx)
        personalization_settings = get_settings().creator_personalization
        scored: list[dict[str, Any]] = []
        for cand in candidates:
            scores, confidence, evidence = _score_window(cand["start"], cand["end"], signals)
            boundary_quality = S.as_dict(cand.get("boundary_quality"))
            if boundary_quality:
                scores["hook"] = S.round3(
                    0.65 * S.as_float(scores.get("hook"))
                    + 0.35 * S.as_float(boundary_quality.get("hook_score"))
                )
                scores["clarity"] = S.round3(
                    0.65 * S.as_float(scores.get("clarity"))
                    + 0.35 * S.as_float(boundary_quality.get("context_score"))
                )
                scores["payoff"] = S.round3(
                    0.6 * S.as_float(scores.get("payoff"))
                    + 0.4 * S.as_float(boundary_quality.get("payoff_score"))
                )
                scores["story_completion"] = S.round3(
                    0.55 * S.as_float(scores.get("story_completion"))
                    + 0.45 * S.as_float(boundary_quality.get("completeness_score"))
                )
                scores["ending"] = S.round3(
                    max(
                        0.0,
                        0.75 * S.as_float(scores.get("ending"))
                        + 0.25
                        * (1.0 - S.as_float(boundary_quality.get("abrupt_end_risk"))),
                    )
                )
                scores["uniqueness"] = S.round3(
                    0.75 * S.as_float(scores.get("uniqueness"))
                    + 0.25 * (1.0 - S.as_float(boundary_quality.get("duplicate_risk")))
                )
                confidence = min(
                    1.0,
                    confidence
                    + 0.1 * S.as_float(boundary_quality.get("boundary_confidence")),
                )
                evidence.append(
                    {
                        "type": "boundary_quality_v1",
                        "detail": (
                            "editorial boundary quality "
                            f"{S.as_float(boundary_quality.get('quality_score'))}"
                        ),
                    }
                )
            story_guidance = S.as_dict(cand.get("story_v2_guidance"))
            story_used = story_guidance.get("story_guidance_used") is True
            if story_used:
                scores = CI.apply_story_scores(scores, story_guidance)
                evidence.append(
                    {
                        "type": "story_analysis_v2",
                        "detail": (
                            "Story V2 adjusted completeness/payoff/context scores "
                            f"for {story_guidance.get('story_id')}"
                        ),
                    }
                )
            planning_personalization = P.empty_application()
            if personalization_settings.apply_to_planning:
                scores, planning_personalization = P.apply_planning_personalization(
                    scores,
                    cand,
                    S.as_dict(signals.get("personalization_directives_v2")) or None,
                    max_score_delta=personalization_settings.max_score_delta,
                )
                if planning_personalization.get("applied"):
                    evidence.append(
                        {
                            "type": "creator_personalization_v2",
                            "detail": (
                                "bounded profile preferences adjusted candidate scoring"
                            ),
                        }
                    )
            scored.append(
                {
                    **cand,
                    "scores": scores,
                    "quality_score": S.round3(S.compute_overall(scores)),
                    "confidence": S.round3(min(1.0, confidence + (0.08 if story_used else 0.0))),
                    "score_evidence": evidence,
                    "planning_personalization": planning_personalization,
                }
            )
        report(1.0)
        return PlanningOutcome.completed(
            {
                "scored_count": len(scored),
                "candidates": scored,
                "dimensions": list(S.CLIP_DIMENSIONS),
                "note": "Each clip is scored across quality dimensions from signals "
                "localized to its time window; the overall is a weighted blend of the "
                "available dimensions (editing complexity is reported but not counted "
                "as quality).",
            }
        )


# --------------------------------------------------------------------------- #
# 4. Duplicate Detection - merge overlapping/near-identical candidates.
# --------------------------------------------------------------------------- #
class DuplicateDetectionAnalyzer(PlanningAnalyzer):
    name = "duplicate_detection"
    version = "4"
    depends_on = ("clip_scoring",)

    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        scoring = ctx.planning_data("clip_scoring")
        if scoring is None:
            return PlanningOutcome.unavailable("Requires clip scoring, which is unavailable.")
        candidates = sorted(
            S.as_list(scoring.get("candidates")),
            key=lambda c: S.as_float(c.get("quality_score")),
            reverse=True,
        )
        survivors: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        for cand in candidates:
            cs, ce = S.as_float(cand.get("start")), S.as_float(cand.get("end"))
            clash = None
            best_iou = 0.0
            best_similarity = 0.0
            for keep in survivors:
                iou = S.temporal_iou(
                    cs, ce, S.as_float(keep.get("start")), S.as_float(keep.get("end"))
                )
                if iou > best_iou:
                    best_iou, clash = iou, keep
                similarity = _candidate_similarity(cand, keep)
                if similarity > best_similarity:
                    best_similarity, clash = similarity, keep
            if clash is not None and (best_iou >= DUPLICATE_IOU or best_similarity >= 0.82):
                reason = (
                    f"overlaps a higher-scoring clip by IoU {S.round3(best_iou)}"
                    if best_iou >= DUPLICATE_IOU
                    else (
                        "repeats a higher-scoring clip by transcript similarity "
                        f"{S.round3(best_similarity)}"
                    )
                )
                duplicates.append(
                    {
                        "id": S.plan_id(cs, ce),
                        "duplicate_of": S.plan_id(
                            S.as_float(clash["start"]), S.as_float(clash["end"])
                        ),
                        "iou": S.round3(best_iou),
                        "similarity": S.round3(best_similarity),
                        "reason": reason,
                    }
                )
                clash["duplicate_group"] = clash.get("duplicate_group") or clash.get("id")
                clash.setdefault("alternatives", []).append(
                    {
                        "id": S.plan_id(cs, ce),
                        "iou": S.round3(best_iou),
                        "similarity": S.round3(best_similarity),
                        "quality_score": S.as_float(cand.get("quality_score")),
                    }
                )
            else:
                cand["id"] = S.plan_id(cs, ce)
                survivors.append(cand)
        report(1.0)
        return PlanningOutcome.completed(
            {
                "survivor_count": len(survivors),
                "duplicate_count": len(duplicates),
                "candidates": survivors,
                "duplicates": duplicates,
                "iou_threshold": DUPLICATE_IOU,
                "repetition_control": {
                    "temporal_iou_threshold": DUPLICATE_IOU,
                    "transcript_similarity_threshold": 0.82,
                    "policy": (
                        "keep the highest-scoring version of repeated moments and store "
                        "near-duplicates as alternatives"
                    ),
                },
                "note": "Near-identical moments are merged: the highest-scoring clip is "
                "kept and overlapping ones become ranked alternatives.",
            }
        )


# --------------------------------------------------------------------------- #
# 5. Blueprint Generation - the complete, executable editing instructions.
# --------------------------------------------------------------------------- #
class BlueprintGenerationAnalyzer(PlanningAnalyzer):
    name = "blueprint_generation"
    version = "6"
    depends_on = ("duplicate_detection",)

    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        dedup = ctx.planning_data("duplicate_detection")
        if dedup is None:
            return PlanningOutcome.unavailable(
                "Requires duplicate detection, which is unavailable."
            )
        survivors = S.as_list(dedup.get("candidates"))
        signals = _gather_signals(ctx)
        plans = [_build_plan(ctx, cand, signals) for cand in survivors]
        report(1.0)
        return PlanningOutcome.completed(
            {
                "plan_count": len(plans),
                "plans": plans,
                "note": "Each surviving clip is expanded into a complete editing "
                "blueprint a future Editing Engine can execute without ambiguity."
                if plans
                else "No clips survived scoring and de-duplication, so no blueprints "
                "were produced.",
            }
        )


# --------------------------------------------------------------------------- #
# 6. Ranking - order the plans with explicit reasoning.
# --------------------------------------------------------------------------- #
class RankingAnalyzer(PlanningAnalyzer):
    name = "ranking"
    version = "5"
    depends_on = ("blueprint_generation",)

    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        blueprint = ctx.planning_data("blueprint_generation")
        if blueprint is None:
            return PlanningOutcome.unavailable(
                "Requires blueprint generation, which is unavailable."
            )
        ranked = sorted(
            S.as_list(blueprint.get("plans")),
            key=lambda p: (
                S.as_float(p.get("quality_score")),
                S.as_float(p.get("confidence")),
                -S.as_float(S.as_dict(p.get("scores")).get("editing_complexity")),
            ),
            reverse=True,
        )
        strategy = _selection_strategy(ctx)
        plans = _select_ranked_plans(
            ranked,
            strategy,
            threshold=S.as_float(strategy.get("primary_threshold")),
        )
        selected_floor = S.as_float(strategy.get("primary_threshold"))
        used_secondary = False
        if len(plans) < int(strategy.get("minimum", 1)):
            plans = _select_ranked_plans(
                ranked,
                strategy,
                threshold=S.as_float(strategy.get("secondary_threshold")),
            )
            selected_floor = S.as_float(strategy.get("secondary_threshold"))
            used_secondary = True
            for plan in plans:
                if S.as_float(plan.get("quality_score")) < S.as_float(
                    strategy.get("primary_threshold")
                ):
                    plan["lower_confidence_selection"] = True
        selected_ids = {p.get("id") for p in plans}
        overflow = [p for p in ranked if p.get("id") not in selected_ids]
        reasons: list[dict[str, Any]] = []
        for i, plan in enumerate(plans):
            plan["rank"] = i + 1
            if i + 1 < len(plans):
                reasons.append(_rank_reason(plan, plans[i + 1]))
        report(1.0)
        return PlanningOutcome.completed(
            {
                "plan_count": len(plans),
                "plans": plans,
                "ranking_reasons": reasons,
                "over_target": [
                    {
                        "id": p.get("id"),
                        "quality_score": p.get("quality_score"),
                        "reason": (
                            "below the automatic quality floor or beyond the safe workload cap"
                        ),
                    }
                    for p in overflow
                ],
                "selection_strategy": strategy,
                "selected_quality_floor": selected_floor,
                "used_secondary_threshold": used_secondary,
                "low_clip_count_explanation": V2.low_clip_count_explanation(
                    plans,
                    ranked,
                    strategy,
                ),
                "note": "Plans are ranked by overall quality, then confidence, then "
                "lower editing complexity. The final set is automatic: all clips above "
                "the quality floor are kept up to the safe workload cap, with a lower "
                "secondary floor only when the source duration would otherwise be "
                "severely underrepresented.",
            }
        )


# --------------------------------------------------------------------------- #
# 7. Planning Summary - aggregate, with an honest zero-clip explanation.
# --------------------------------------------------------------------------- #
class PlanningSummaryAnalyzer(PlanningAnalyzer):
    name = "planning_summary"
    version = "5"
    depends_on = (
        "candidate_generation",
        "boundary_refinement",
        "clip_scoring",
        "duplicate_detection",
        "blueprint_generation",
        "ranking",
    )

    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        ranking = ctx.planning_data("ranking") or {}
        generation = ctx.planning_data("candidate_generation") or {}
        plans = S.as_list(ranking.get("plans"))
        available, pending = _signal_inventory(ctx)

        summaries = [
            {
                "id": p.get("id"),
                "story_id": p.get("story_id"),
                "candidate_id": p.get("candidate_id"),
                "rank": p.get("rank"),
                "start": p.get("start"),
                "end": p.get("end"),
                "duration": p.get("duration"),
                "quality_score": p.get("quality_score"),
                "hook_score": p.get("hook_score"),
                "retention_score": p.get("retention_score"),
                "clarity_score": p.get("clarity_score"),
                "payoff_score": p.get("payoff_score"),
                "virality_score": p.get("virality_score"),
                "story_score": p.get("story_score"),
                "story_completion_score": p.get("story_completion_score"),
                "ending_score": p.get("ending_score"),
                "trend_score": p.get("trend_score"),
                "viral_score_v2": p.get("viral_score_v2"),
                "uniqueness_score": p.get("uniqueness_score"),
                "platform_score": p.get("platform_score"),
                "confidence": p.get("confidence"),
                "content_niche": p.get("content_niche"),
                "title": S.as_dict(S.as_dict(p.get("blueprint")).get("title_suggestion")).get(
                    "text"
                ),
                "hook_line": p.get("hook_line"),
                "source_candidate_type": p.get("source_candidate_type"),
                "planning_story_integration": S.as_dict(p.get("planning_story_integration")),
                "planning_trend_integration": S.as_dict(p.get("planning_trend_integration")),
                "unified_clip_intelligence": S.as_dict(p.get("unified_clip_intelligence")),
                "explanation": p.get("explanation"),
            }
            for p in plans
        ]
        distribution = {"high": 0, "moderate": 0, "low": 0}
        for p in plans:
            q = S.as_float(p.get("quality_score"))
            distribution["high" if q >= 0.66 else "moderate" if q >= 0.4 else "low"] += 1

        zero_reason = None
        if not plans:
            zero_reason = _zero_reason(ctx)

        report(1.0)
        return PlanningOutcome.completed(
            {
                "plan_count": len(plans),
                "plans": summaries,
                "zero_reason": zero_reason,
                "score_distribution": distribution,
                "target_clip_strategy": S.as_dict(generation.get("target_clip_strategy")),
                "selection_strategy": S.as_dict(ranking.get("selection_strategy")),
                "content_niche": S.as_dict(generation.get("content_niche")),
                "viral_research_snapshot": S.as_dict(generation.get("viral_research_snapshot")),
                "internet_trend_research_v2": S.as_dict(
                    generation.get("internet_trend_research_v2")
                ),
                "internet_research_available": generation.get("internet_research_available"),
                "low_clip_count_explanation": S.as_dict(ranking.get("low_clip_count_explanation")),
                "low_output_reason": _low_output_reason(ctx, generation, ranking),
                "selected_quality_floor": ranking.get("selected_quality_floor"),
                "used_secondary_threshold": ranking.get("used_secondary_threshold"),
                "candidate_coverage": S.as_dict(generation.get("coverage")),
                "story_guidance_available": generation.get("story_guidance_available"),
                "story_candidate_count": generation.get("story_candidate_count"),
                "available_signals": available,
                "pending_signals": pending,
                "confidence": S.round3(
                    S.coverage_confidence(len(available), len(available) + len(pending))
                ),
                "note": "Aggregated planning report. Zero clips is a valid, honest "
                "outcome - the planner never forces low-quality plans.",
            }
        )


# --------------------------------------------------------------------------- #
# Shared, pure signal/scoring/blueprint helpers.
# --------------------------------------------------------------------------- #
def _gather_signals(ctx: PlanningStageContext) -> dict[str, Any]:
    summary = ctx.virality_data("virality_summary") or {}
    generation = ctx.planning_data("candidate_generation") or {}
    personalization = get_settings().creator_personalization
    directives = P.load_runtime_directives() if personalization.enabled else None
    return {
        "heatmap": S.as_list(summary.get("heatmap")),
        "category_scores": S.as_dict(summary.get("category_scores")),
        "density": S.as_list((ctx.story_data("information_density") or {}).get("windows")),
        "turns": S.as_list(
            (ctx.story_data("emotional_turning_points") or {}).get("turning_points")
        ),
        "payoffs": S.as_list((ctx.story_data("payoff_detection") or {}).get("relationships")),
        "sections": S.as_list((ctx.story_data("narrative_segmentation") or {}).get("sections")),
        "hook": ctx.story_data("hook_detection") or {},
        "segments": ctx.transcript_segments() or [],
        "inspection": ctx.cognitive_data("video_inspection") or {},
        "content_niche": S.as_dict(generation.get("content_niche")),
        "viral_research_snapshot": S.as_dict(generation.get("viral_research_snapshot")),
        "internet_trend_research_v2": S.as_dict(
            generation.get("internet_trend_research_v2")
        ),
        "story_analysis_v2": ctx.story_data("story_analysis_v2") or {},
        "personalization_directives_v2": directives or {},
    }


def _category_prior(category_scores: dict[str, Any], name: str) -> float | None:
    entry = category_scores.get(name)
    if isinstance(entry, dict) and "score" in entry:
        return S.as_float(entry.get("score"))
    return None


def _blend(local: float, prior: float | None) -> float:
    """Blend a localized value with an optional global prior (transparent)."""

    if prior is None:
        return S.clamp01(local)
    return S.clamp01(0.6 * local + 0.4 * prior)


def _score_window(
    start: float, end: float, sig: dict[str, Any]
) -> tuple[dict[str, float], float, list[dict[str, Any]]]:
    cats = sig["category_scores"]
    heat_cells = S.localize_spans(sig["heatmap"], start, end)
    dens = S.localize_spans(sig["density"], start, end)
    turns_in = S.localize(sig["turns"], "timestamp", start, end)
    payoffs_in = [
        r for r in sig["payoffs"] if S.in_window(S.as_float(r.get("payoff_timestamp")), start, end)
    ]
    conflict_secs = [
        s
        for s in S.localize_spans(sig["sections"], start, end)
        if S.as_str(s.get("role")) in ("conflict", "problem")
    ]
    segs_in = S.localize_spans(sig["segments"], start, end)
    transcript_text = " ".join(_seg_text(s) for s in segs_in).strip()
    opening_text = _seg_text(segs_in[0]) if segs_in else transcript_text[:220]
    hook_v2 = V2.hook_analysis(
        opening_text or transcript_text[:220],
        sig["viral_research_snapshot"],
    )
    story_v2 = V2.storytelling_analysis(transcript_text)
    ending_v2 = V2.ending_analysis(transcript_text, payoffs_in)
    trend_v2 = V2.trend_pattern_match(
        transcript_text,
        sig["viral_research_snapshot"],
        sig["content_niche"],
    )
    hook = sig["hook"]
    hook_start = (
        S.as_float(S.as_dict(hook.get("window")).get("start")) if hook.get("has_hook") else None
    )

    mean_heat = S.mean([S.as_float(c.get("heat")) for c in heat_cells])
    mean_density = S.mean([S.as_float(w.get("density")) for w in dens])
    mean_entity = S.mean(
        [S.as_float(S.as_dict(w.get("metrics")).get("entity_density")) for w in dens]
    )
    mean_div = S.mean(
        [S.as_float(S.as_dict(w.get("metrics")).get("lexical_diversity")) for w in dens]
    )

    hook_local = (
        1.0
        if hook_start is not None and start <= hook_start < start + 3
        else (0.6 if hook_start is not None and start <= hook_start < end else 0.0)
    )
    hook_local = max(hook_local, S.as_float(hook_v2.get("score")))
    emotion_local = S.clamp01(len(turns_in) / 2)
    payoff_local = _payoff_score(payoffs_in, transcript_text)
    clarity_local = _clarity_score(transcript_text)
    platform_local = _platform_score(end - start)
    story_local = max(
        payoff_local,
        S.as_float(story_v2.get("score")),
        0.4 if conflict_secs else 0.2,
    )
    conflict_local = S.clamp01(len(conflict_secs) / 1)
    info_local = S.clamp01(0.5 * mean_entity + 0.5 * mean_div)
    novelty_local = S.clamp01(max(mean_entity, mean_div * 0.7))
    uniqueness_local = S.clamp01(0.45 + 0.35 * mean_div + 0.2 * (1.0 if not conflict_secs else 0.7))
    replay_local = 0.7 if payoffs_in else 0.2
    share_local = S.mean([emotion_local, novelty_local, info_local, payoff_local])

    scores: dict[str, float] = {
        "hook": S.round3(_blend(hook_local, _category_prior(cats, "hook"))),
        "retention": S.round3(_blend(mean_density, _category_prior(cats, "retention"))),
        "clarity": S.round3(clarity_local),
        "payoff": S.round3(payoff_local),
        "emotion": S.round3(_blend(emotion_local, _category_prior(cats, "emotion"))),
        "virality": S.round3(mean_heat),
        "uniqueness": S.round3(uniqueness_local),
        "platform": S.round3(platform_local),
        "information": S.round3(_blend(info_local, _category_prior(cats, "information"))),
        "novelty": S.round3(_blend(novelty_local, _category_prior(cats, "novelty"))),
        "shareability": S.round3(_blend(share_local, _category_prior(cats, "sharing"))),
        "story": S.round3(story_local),
        "story_completion": S.round3(S.as_float(story_v2.get("score"))),
        "ending": S.round3(S.as_float(ending_v2.get("score"))),
        "trend_fit": S.round3(S.as_float(trend_v2.get("score"))),
        "conflict": S.round3(_blend(conflict_local, _category_prior(cats, "conflict"))),
        "replay": S.round3(_blend(replay_local, _category_prior(cats, "replay"))),
    }
    # Editing complexity (a cost): more sentences/cuts, slow gaps, emphasis = harder.
    slow = [w for w in dens if S.as_str(w.get("classification")) in ("slow", "filler")]
    complexity = S.clamp01(0.06 * len(segs_in) + 0.1 * len(slow) + 0.08 * len(turns_in))
    scores["editing_complexity"] = S.round3(complexity)

    available = sum(
        bool(x)
        for x in (
            heat_cells,
            dens,
            turns_in,
            payoffs_in,
            segs_in,
            hook_start is not None,
            sig["viral_research_snapshot"],
            sig["content_niche"],
        )
    )
    confidence = S.coverage_confidence(available, 8)
    evidence = [
        {
            "type": "local_heat",
            "detail": f"mean heat {S.round3(mean_heat)} over {len(heat_cells)} cell(s)",
        },
        {
            "type": "pacing",
            "detail": f"mean density {S.round3(mean_density)} over {len(dens)} window(s)",
        },
        {
            "type": "hook_v2",
            "detail": (
                f"{S.as_str(hook_v2.get('category'))} hook {S.as_float(hook_v2.get('score'))}"
            ),
        },
        {"type": "clarity", "detail": f"standalone clarity {S.round3(clarity_local)}"},
        {"type": "payoff", "detail": f"payoff strength {S.round3(payoff_local)}"},
        {
            "type": "storytelling_v2",
            "detail": (
                f"{S.as_str(story_v2.get('story_shape'))} story {S.as_float(story_v2.get('score'))}"
            ),
        },
        {
            "type": "ending_v2",
            "detail": (
                f"{S.as_str(ending_v2.get('ending_type'))} ending "
                f"{S.as_float(ending_v2.get('score'))}"
            ),
        },
        {
            "type": "trend_fit_v2",
            "detail": f"trend/pattern fit {S.as_float(trend_v2.get('score'))}",
        },
        {"type": "emotion", "detail": f"{len(turns_in)} emotional shift(s) in window"},
        {"type": "platform", "detail": f"short-form duration fit {S.round3(platform_local)}"},
    ]
    return scores, confidence, evidence


def _clarity_score(text: str) -> float:
    words = text.split()
    if not words:
        return 0.0
    word_count = len(words)
    enough_context = S.clamp01(word_count / 28)
    concise = 1.0 if word_count <= 160 else S.clamp01(1.0 - (word_count - 160) / 120)
    low = text.lower().strip()
    context_penalty = 0.15 if low.startswith(("and ", "but ", "so ", "then ")) else 0.0
    unresolved = sum(
        1 for token in words[:18] if token.lower().strip(".,!?") in {"he", "she", "they", "it"}
    )
    pronoun_penalty = min(0.2, unresolved * 0.05)
    return S.clamp01(0.55 * enough_context + 0.45 * concise - context_penalty - pronoun_penalty)


def _payoff_score(payoffs: list[dict[str, Any]], text: str) -> float:
    if payoffs:
        return 0.86
    low = text.lower()
    if any(
        cue in low
        for cue in (
            "because",
            "finally",
            "lesson",
            "so the",
            "that's why",
            "therefore",
            "turns out",
            "what changed",
        )
    ):
        return 0.68
    if any(cue in low for cue in ("problem", "mistake", "solution", "reason")):
        return 0.52
    return 0.32


def _platform_score(duration: float) -> float:
    if 15.0 <= duration <= 60.0:
        return 1.0
    if duration < 15.0:
        return S.clamp01(duration / 15.0)
    if duration <= 90.0:
        return S.clamp01(1.0 - (duration - 60.0) / 60.0)
    return 0.35


def _candidate_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_words = _candidate_words(a)
    b_words = _candidate_words(b)
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / max(1, len(a_words | b_words))


def _candidate_words(candidate: dict[str, Any]) -> set[str]:
    text = " ".join(
        filter(
            None,
            [
                S.as_str(candidate.get("uniqueness_fingerprint")),
                S.as_str(candidate.get("transcript_excerpt")),
            ],
        )
    )
    stop = {
        "about",
        "actually",
        "because",
        "could",
        "every",
        "from",
        "have",
        "just",
        "like",
        "really",
        "that",
        "their",
        "there",
        "this",
        "what",
        "when",
        "with",
        "would",
        "your",
    }
    words: set[str] = set()
    for raw in text.lower().split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) >= 4 and token not in stop:
            words.add(token)
    return words


def _build_plan(
    ctx: PlanningStageContext, cand: dict[str, Any], sig: dict[str, Any]
) -> dict[str, Any]:
    start, end = S.as_float(cand.get("start")), S.as_float(cand.get("end"))
    duration = S.round3(end - start)
    scores = S.as_dict(cand.get("scores"))
    inspection = sig["inspection"]
    width, height = S.as_float(inspection.get("width")), S.as_float(inspection.get("height"))
    vertical = bool(height and width and height >= width)

    segs_in = S.localize_spans(sig["segments"], start, end)
    dens_in = S.localize_spans(sig["density"], start, end)
    turns_in = S.localize(sig["turns"], "timestamp", start, end)
    payoffs_in = [
        r for r in sig["payoffs"] if S.in_window(S.as_float(r.get("payoff_timestamp")), start, end)
    ]
    slow = [w for w in dens_in if S.as_str(w.get("classification")) in ("slow", "filler")]
    dense = [w for w in dens_in if S.as_str(w.get("classification")) == "dense"]
    hook = sig["hook"]
    hook_in_window = (
        hook.get("has_hook")
        and start <= S.as_float(S.as_dict(hook.get("window")).get("start")) < end
    )

    mean_density = S.mean([S.as_float(w.get("density")) for w in dens_in])
    pacing = "fast" if mean_density >= 0.5 else "slow" if mean_density <= 0.2 else "medium"
    keywords = _window_keywords(segs_in)
    opening_text = _seg_text(segs_in[0]) if segs_in else ""
    transcript_text = " ".join(_seg_text(s) for s in segs_in)
    content_niche = S.as_dict(sig.get("content_niche"))
    viral_research = S.as_dict(sig.get("internet_trend_research_v2")) or S.as_dict(
        sig.get("viral_research_snapshot")
    )
    candidate_v2 = S.as_dict(cand.get("v2_candidate_metadata"))
    hook_v2 = S.as_dict(candidate_v2.get("hook_analysis")) or V2.hook_analysis(
        opening_text,
        viral_research,
    )
    story_v2 = S.as_dict(candidate_v2.get("storytelling")) or V2.storytelling_analysis(
        transcript_text,
    )
    ending_v2 = S.as_dict(candidate_v2.get("ending")) or V2.ending_analysis(
        transcript_text,
        payoffs_in,
    )
    trend_v2 = S.as_dict(cand.get("viral_pattern_match")) or V2.trend_pattern_match(
        transcript_text,
        viral_research,
        content_niche,
    )
    planning_trend = _planning_trend_integration(viral_research, trend_v2)
    editing_trend = build_editing_trend_guidance(
        viral_research,
        content_niche,
        trend_v2,
    )
    story_guidance = S.as_dict(cand.get("story_v2_guidance"))
    boundary_quality = S.as_dict(cand.get("boundary_quality"))
    if not story_guidance.get("story_guidance_used"):
        story_guidance = CI.story_guidance_for_window(
            S.as_dict(sig.get("story_analysis_v2")),
            start,
            end,
        )
    if story_guidance.get("story_guidance_used"):
        story_v2 = {
            **story_v2,
            "source": "story_analysis_v2",
            "story_id": story_guidance.get("story_id"),
            "story_shape": story_guidance.get("story_shape") or story_v2.get("story_shape"),
            "score": story_guidance.get("completeness_score") or story_v2.get("score"),
            "payoff_line": story_guidance.get("payoff"),
            "context_risk": story_guidance.get("context_risk"),
            "why_story_works": story_guidance.get("why_story_works"),
        }
        ending_v2 = {
            **ending_v2,
            "source": "story_analysis_v2",
            "ending_line": story_guidance.get("payoff") or ending_v2.get("ending_line"),
            "score": story_guidance.get("ending_strength") or ending_v2.get("score"),
            "ending_type": story_guidance.get("ending_reason") or ending_v2.get("ending_type"),
        }
    viral_score_v2 = V2.viral_score_v2(scores, hook_v2, story_v2, ending_v2, trend_v2)
    editing_guidance_v2 = V2.editing_guidance(hook_v2, story_v2, ending_v2, trend_v2)
    if story_guidance.get("story_guidance_used"):
        editing_guidance_v2 = {
            **editing_guidance_v2,
            "source": "story_analysis_v2+planning_v2",
            "story_id": story_guidance.get("story_id"),
            "caption_emphasis_words": S.as_list(
                S.as_dict(story_guidance.get("editing_guidance")).get("caption_emphasis_words")
            ),
            "music_mood": S.as_dict(story_guidance.get("editing_guidance")).get("music_mood"),
            "ending_hold": S.as_dict(story_guidance.get("editing_guidance")).get(
                "ending_hold_recommendation"
            ),
            "context_caption": S.as_dict(story_guidance.get("planning_guidance")).get(
                "context_caption"
            ),
        }
    content_category = ctx.project.content_category or "auto"
    music_decision = V2.music_decision(content_category, enabled=ctx.project.music_enabled)
    sfx_decision = V2.sfx_decision(hook_v2, enabled=ctx.project.sfx_enabled)
    caption_decision = V2.caption_decision(
        content_category,
        hook_v2,
        enabled=ctx.project.captions_enabled,
    )
    edit_decision = _edit_decision(
        content_category,
        ctx.project.editing_intensity,
        scores,
        hook_v2,
        pacing,
    )
    personalization_directives = S.as_dict(sig.get("personalization_directives_v2"))
    planning_personalization = S.as_dict(cand.get("planning_personalization"))

    blueprint = {
        "opening_hook": _opening_hook(hook, hook_in_window, segs_in),
        "hook_v2": {
            **hook_v2,
            "first_three_second_editing": {
                "punch_in": bool(S.as_float(hook_v2.get("score")) >= 0.65),
                "caption_emphasis": bool(S.as_float(hook_v2.get("score")) >= 0.65),
                "reason": "first 1-3 seconds need stronger retention pressure",
            },
        },
        "hook_analysis_v2": hook_v2,
        "storytelling_v2": story_v2,
        "ending_payoff_v2": ending_v2,
        "trend_match_v2": trend_v2,
        "viral_score_v2": viral_score_v2,
        "editing_guidance_v2": editing_guidance_v2,
        "story_v2_guidance": story_guidance,
        "story_trend_guidance": _story_trend_guidance(
            viral_research,
            S.as_str(story_guidance.get("story_id")),
        ),
        "planning_story_integration": S.as_dict(cand.get("planning_story_integration")),
        "planning_trend_integration": planning_trend,
        "editing_trend_guidance": editing_trend,
        "personalization_directives_v2": personalization_directives,
        "planning_personalization": planning_personalization,
        "content_niche": content_niche,
        "viral_research_snapshot": viral_research,
        "internet_trend_research_v2": viral_research,
        "boundary_optimization_v2": S.as_dict(cand.get("boundary_optimization")),
        "boundary_quality": boundary_quality,
        "boundary_quality_decision": S.as_dict(cand.get("boundary_quality_decision")),
        "closing_payoff": _closing_payoff(payoffs_in, segs_in),
        "title_suggestion": {
            "text": (
                _seg_text(segs_in[0])[:70]
                if hook_in_window and segs_in
                else " ".join(keywords[:5]).title()
            ),
            "basis": "opening hook line" if hook_in_window else "top keywords",
            "evidence": keywords[:6],
            "trend_pattern": _first_pattern_label(viral_research, "title"),
            "trend_safety": "curiosity without unsupported claims",
        },
        "subtitle_style": {
            "style": "word-by-word (karaoke), bold, high-contrast"
            if pacing == "fast"
            else "phrase-by-phrase, clean sans-serif",
            "reason": f"matches {pacing} pacing",
        },
        "caption_decision_v2": caption_decision,
        "edit_decision_v2": edit_decision,
        "aspect_ratio": {
            "value": "9:16",
            "reason": "vertical source preserved"
            if vertical
            else "reframe to vertical for short-form",
        },
        "pacing": {"value": pacing, "reason": f"mean information density {S.round3(mean_density)}"},
        "silence_removal": [
            {
                "start": S.as_float(w.get("start")),
                "end": S.as_float(w.get("end")),
                "reason": S.as_str(w.get("reason")) or "low-engagement passage",
            }
            for w in slow
        ],
        "jump_cuts": [
            {"timestamp": S.as_float(w.get("start")), "reason": "tighten a slow/filler passage"}
            for w in slow
        ],
        "scene_cuts": _scene_cuts(ctx, start, end),
        "zoom_suggestions": [
            {
                "timestamp": S.as_float(w.get("start")),
                "reason": "emphasize an information-dense moment",
            }
            for w in dense
        ]
        + [
            {
                "timestamp": S.as_float(t.get("timestamp")),
                "reason": "punch in on an emotional shift",
            }
            for t in turns_in
        ],
        "crop_suggestions": [
            {
                "type": "center-safe 9:16 crop" if not vertical else "none (already vertical)",
                "reason": "keep the speaker framed" if not vertical else "source is vertical",
            }
        ],
        "speaker_switches": _speaker_switches(ctx, start, end),
        "camera_focus": {
            "value": "center / active speaker (default)",
            "reason": "no face/scene model is available to localize focus precisely",
        },
        "caption_timing": [
            {
                "start": _seg_start(s),
                "end": _seg_end(s),
                "rel_start": S.round3(_seg_start(s) - start),
                "text": _seg_text(s),
            }
            for s in segs_in
        ],
        "emphasis_moments": [
            {"timestamp": S.as_float(w.get("start")), "reason": "information-dense"} for w in dense
        ],
        "replay_moments": [
            {"timestamp": S.as_float(r.get("payoff_timestamp")), "reason": "satisfying payoff"}
            for r in payoffs_in
        ],
        "music_decision_v2": music_decision,
        "sound_effect_plan_v2": sfx_decision,
        "retention_risks": [
            {
                "timestamp": S.as_float(w.get("start")),
                "reason": S.as_str(w.get("reason")) or "slow passage may lose viewers",
            }
            for w in slow
        ],
        "continuation_possibility": _continuation(sig, end),
        "estimated_complexity": _complexity(
            scores.get("editing_complexity", 0.0), len(slow), len(turns_in)
        ),
        "platform_suitability": _platform_suitability(duration, vertical),
        "v2_metadata": {
            "content_category": content_category,
            "content_niche": content_niche,
            "internet_research_available": viral_research.get("internet_research_available", False),
            "trend_research_status": viral_research.get("research_status"),
            "trend_cache_status": viral_research.get("cache_status"),
            "trend_fallback_used": viral_research.get("fallback_used"),
            "research_confidence": viral_research.get("confidence"),
            "editing_intensity": edit_decision["edit_intensity"],
            "editing_style_chosen": edit_decision["transition_style"],
            "music_mood_chosen": music_decision.get("category"),
            "sfx_plan_status": sfx_decision.get("status"),
            "caption_style": caption_decision.get("style"),
            "why_selected": _why_selected_v2(
                cand,
                hook_v2,
                scores,
                payoffs_in,
                story_v2=story_v2,
                ending_v2=ending_v2,
                trend_v2=trend_v2,
            ),
            "risk_notes": _risk_notes_v2(hook_v2, music_decision, sfx_decision),
            "source_timestamps": {"start": start, "end": end},
            "boundary_quality": boundary_quality,
            "source_candidate_metadata": {
                "candidate_id": cand.get("candidate_id"),
                "story_id": story_guidance.get("story_id") or cand.get("story_id"),
                "candidate_type": cand.get("candidate_type") or cand.get("source"),
                "source_reason": cand.get("source_reason"),
                "topic_cluster": cand.get("topic_cluster"),
            },
        },
    }

    plan = {
        "id": cand.get("id") or S.plan_id(start, end),
        "story_id": story_guidance.get("story_id") or cand.get("story_id"),
        "candidate_id": cand.get("candidate_id"),
        "source_video": {
            "filename": ctx.project.source_filename,
            "storage_key": ctx.project.storage_key,
        },
        "start": start,
        "end": end,
        "duration": duration,
        "start_frame": cand.get("start_frame"),
        "end_frame": cand.get("end_frame"),
        "fps": cand.get("fps"),
        "scores": scores,
        "overall_score": S.as_float(cand.get("quality_score")),
        "hook_score": S.as_float(hook_v2.get("score")),
        "retention_score": S.as_float(scores.get("retention")),
        "clarity_score": S.as_float(scores.get("clarity")),
        "payoff_score": S.as_float(scores.get("payoff")),
        "virality_score": S.as_float(scores.get("virality")),
        "emotion_score": S.as_float(scores.get("emotion")),
        "story_score": S.as_float(scores.get("story")),
        "story_completion_score": S.as_float(scores.get("story_completion")),
        "ending_score": S.as_float(scores.get("ending")),
        "trend_score": S.as_float(scores.get("trend_fit")),
        "uniqueness_score": S.as_float(scores.get("uniqueness")),
        "platform_score": S.as_float(scores.get("platform")),
        "quality_score": S.as_float(cand.get("quality_score")),
        "viral_score_v2": viral_score_v2,
        "content_niche": content_niche,
        "confidence": S.as_float(cand.get("confidence")),
        "source": cand.get("source"),
        "source_candidate_type": cand.get("source_candidate_type") or cand.get("source"),
        "planning_story_integration": S.as_dict(cand.get("planning_story_integration")),
        "planning_trend_integration": planning_trend,
        "editing_trend_guidance": editing_trend,
        "personalization_directives_v2": personalization_directives,
        "planning_personalization": planning_personalization,
        "internet_trend_research_v2": viral_research,
        "story_v2_guidance": story_guidance,
        "boundary_quality": boundary_quality,
        "boundary_quality_decision": S.as_dict(cand.get("boundary_quality_decision")),
        "transcript_excerpt": cand.get("transcript_excerpt")
        or " ".join(_seg_text(s) for s in segs_in),
        "hook_line": S.as_dict(cand.get("hook_candidate")).get("text")
        or S.as_dict(blueprint["opening_hook"]).get("text"),
        "duplicate_group": cand.get("duplicate_group"),
        "explanation": _explanation(cand, hook_in_window, payoffs_in),
        "evidence": S.as_list(cand.get("evidence")) + S.as_list(cand.get("score_evidence")),
        "alternatives": S.as_list(cand.get("alternatives")),
        "blueprint": blueprint,
    }
    plan["unified_clip_intelligence"] = CI.unified_clip_intelligence(
        plan=plan,
        blueprint=blueprint,
    )
    return plan


def _planning_trend_integration(
    snapshot: dict[str, Any],
    trend_match: dict[str, Any],
) -> dict[str, Any]:
    matched = [
        S.as_dict(item)
        for item in S.as_list(trend_match.get("matched_patterns"))
        if S.as_dict(item)
    ]
    fit = S.as_float(trend_match.get("trend_fit_score"), S.as_float(trend_match.get("score")))
    fallback = snapshot.get("fallback_used") is True
    if fallback:
        effect = "fallback"
    elif fit >= 0.62:
        effect = "boosted"
    elif fit <= 0.3:
        effect = "penalized"
    else:
        effect = "neutral"
    return {
        "trend_snapshot_id": snapshot.get("snapshot_id"),
        "trend_guidance_used": bool(snapshot),
        "trend_patterns_used": [
            item.get("pattern_id") or item.get("id") for item in matched[:5]
        ],
        "pattern_diversity_reason": "Set during ranked selection across candidate patterns.",
        "trend_fit_score": S.round3(fit),
        "selection_effect": effect,
        "warning": (
            "Evergreen fallback influenced only the small trend-fit component."
            if fallback
            else None
        ),
    }


def _story_trend_guidance(snapshot: dict[str, Any], story_id: str) -> dict[str, Any]:
    if not story_id:
        return {}
    for item in S.as_list(snapshot.get("story_trend_guidance")):
        guidance = S.as_dict(item)
        if S.as_str(guidance.get("story_id")) == story_id:
            return guidance
    return {}


def _first_pattern_label(snapshot: dict[str, Any], category: str) -> str | None:
    for item in S.as_list(snapshot.get("extracted_patterns")):
        pattern = S.as_dict(item)
        if S.as_str(pattern.get("category")) == category:
            return S.as_str(pattern.get("label")) or None
    return None


def _why_selected_v2(
    cand: dict[str, Any],
    hook: dict[str, Any],
    scores: dict[str, Any],
    payoffs_in: list[dict[str, Any]],
    *,
    story_v2: dict[str, Any] | None = None,
    ending_v2: dict[str, Any] | None = None,
    trend_v2: dict[str, Any] | None = None,
) -> str:
    bits = [f"candidate came from {S.as_str(cand.get('source')).replace('_', ' ')}"]
    hook_score = S.as_float(hook.get("score"))
    if hook_score >= 0.65:
        bits.append(f"strong {S.as_str(hook.get('category')).replace('_', ' ')} hook")
    if payoffs_in:
        bits.append("contains a payoff")
    story = S.as_dict(story_v2)
    ending = S.as_dict(ending_v2)
    trend = S.as_dict(trend_v2)
    if S.as_float(story.get("score")) >= 0.65:
        bits.append(f"{S.as_str(story.get('story_shape')).replace('_', ' ')} story shape")
    if S.as_float(ending.get("score")) >= 0.65:
        bits.append(f"{S.as_str(ending.get('ending_type')).replace('_', ' ')} ending")
    matched = S.as_list(trend.get("matched_patterns"))
    if matched:
        label = S.as_str(S.as_dict(matched[0]).get("label"))
        bits.append(f"matches {label.lower() if label else 'evergreen'} viral pattern")
    if S.as_float(scores.get("retention")) >= 0.55:
        bits.append("good retention potential")
    if S.as_float(scores.get("clarity")) >= 0.55:
        bits.append("understandable without heavy context")
    return "; ".join(bits) + "."


def _edit_decision(
    content_category: str,
    requested_intensity: str | None,
    scores: dict[str, Any],
    hook: dict[str, Any],
    pacing: str,
) -> dict[str, Any]:
    category = (content_category or "auto").lower()
    requested = (requested_intensity or "auto").lower()
    hook_score = S.as_float(hook.get("score"))
    energy = S.mean(
        [
            S.as_float(scores.get("retention")),
            S.as_float(scores.get("emotion")),
            S.as_float(scores.get("shareability")),
            hook_score,
        ]
    )
    if requested in {"clean", "balanced", "high-energy", "aggressive viral", "cinematic"}:
        intensity = "high-energy" if requested == "aggressive viral" else requested
        reason = "user/editor intent selected this intensity"
    elif category in {"stream", "entertainment", "gaming", "funny"} or energy >= 0.68:
        intensity = "high-energy"
        reason = "content has high retention/emotion/shareability signals"
    elif category in {"motivation", "motivational", "emotional"}:
        intensity = "cinematic"
        reason = "content category benefits from cinematic pacing"
    elif category in {"educational", "podcast", "podcast / talking", "interview", "business"}:
        intensity = "balanced"
        reason = "talking/educational content needs clarity-first editing"
    else:
        intensity = "balanced" if energy >= 0.45 else "clean"
        reason = "auto mode inferred intensity from clip scores"

    zoom_frequency = {
        "clean": "low",
        "balanced": "medium",
        "cinematic": "medium",
        "high-energy": "high",
    }.get(intensity, "medium")
    return {
        "edit_intensity": intensity,
        "pacing": "fast" if intensity == "high-energy" else pacing,
        "zoom_frequency": zoom_frequency,
        "caption_style": "bold viral" if intensity == "high-energy" else "clean emphasis",
        "transition_style": "fast punch-ins" if intensity == "high-energy" else "clean cuts",
        "music_style": "cinematic" if intensity == "cinematic" else "subtle bed",
        "sfx_density": "medium" if intensity == "high-energy" else "low",
        "reason": reason,
    }


def _risk_notes_v2(
    hook: dict[str, Any],
    music_decision: dict[str, Any],
    sfx_decision: dict[str, Any],
) -> list[str]:
    notes: list[str] = []
    if S.as_float(hook.get("score")) < 0.55:
        notes.append("Hook is moderate; cold-open overlay or tighter first cut may be needed.")
    if hook.get("clickbait_risk"):
        notes.append("Hook contains clickbait-like phrasing; keep captions faithful to transcript.")
    if music_decision.get("status") == "unavailable":
        notes.append(S.as_str(music_decision.get("reason")))
    if sfx_decision.get("status") == "unavailable":
        notes.append(S.as_str(sfx_decision.get("reason")))
    return notes


def _selection_strategy(ctx: PlanningStageContext) -> dict[str, Any]:
    generation = ctx.planning_data("candidate_generation") or {}
    strategy = S.as_dict(generation.get("target_clip_strategy"))
    if strategy:
        return strategy
    return V2.strategy_dict(V2.clip_count_strategy(ctx.video_duration(), None))


def _select_ranked_plans(
    plans: list[dict[str, Any]],
    strategy: dict[str, Any],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    maximum = max(1, int(S.as_float(strategy.get("maximum"), 10)))
    bins = max(1, int(S.as_float(strategy.get("coverage_bins"), 6)))
    duration = max((S.as_float(p.get("end")) for p in plans), default=0.0)
    per_bucket_limit = max(2, (maximum // bins) + 2)
    bucket_counts: dict[int, int] = {}
    pattern_counts: dict[str, int] = {}
    pattern_limit = max(1, (maximum + 1) // 2)
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for plan in plans:
        if S.as_float(plan.get("quality_score")) < threshold:
            continue
        bucket = _timeline_bucket(S.as_float(plan.get("start")), duration, bins)
        if bucket_counts.get(bucket, 0) >= per_bucket_limit:
            continue
        pattern_id = _primary_trend_pattern(plan)
        if pattern_id and pattern_counts.get(pattern_id, 0) >= pattern_limit:
            deferred.append(plan)
            continue
        selected.append(plan)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        if pattern_id:
            pattern_counts[pattern_id] = pattern_counts.get(pattern_id, 0) + 1
        _mark_pattern_diversity(plan, pattern_id, repeated=False)
        if len(selected) >= maximum:
            break
    for plan in deferred:
        if len(selected) >= maximum:
            break
        bucket = _timeline_bucket(S.as_float(plan.get("start")), duration, bins)
        if bucket_counts.get(bucket, 0) >= per_bucket_limit:
            continue
        pattern_id = _primary_trend_pattern(plan)
        selected.append(plan)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        if pattern_id:
            pattern_counts[pattern_id] = pattern_counts.get(pattern_id, 0) + 1
        _mark_pattern_diversity(plan, pattern_id, repeated=True)
    return selected


def _primary_trend_pattern(plan: dict[str, Any]) -> str:
    integration = S.as_dict(plan.get("planning_trend_integration"))
    patterns = S.as_list(integration.get("trend_patterns_used"))
    return S.as_str(patterns[0]) if patterns else ""


def _mark_pattern_diversity(
    plan: dict[str, Any], pattern_id: str, *, repeated: bool
) -> None:
    integration = S.as_dict(plan.get("planning_trend_integration"))
    if not integration:
        return
    if not pattern_id:
        reason = "No matched trend pattern; quality and timeline coverage decided selection."
    elif repeated:
        reason = (
            f"Repeated {pattern_id.replace('_', ' ')} only after diverse candidates were used."
        )
    else:
        reason = f"Selected early to preserve diversity around {pattern_id.replace('_', ' ')}."
    integration["pattern_diversity_reason"] = reason
    plan["planning_trend_integration"] = integration
    plan["timeline_diversity_reason"] = reason


def _timeline_bucket(start: float, duration: float, bins: int) -> int:
    if duration <= 0 or bins <= 1:
        return 0
    return max(0, min(bins - 1, int((start / duration) * bins)))


def _opening_hook(
    hook: dict[str, Any], in_window: bool, segs: list[dict[str, Any]]
) -> dict[str, Any]:
    if in_window:
        return {
            "text": S.as_str(hook.get("supporting_excerpt")),
            "timestamp": S.as_float(S.as_dict(hook.get("window")).get("start")),
            "evidence": f"detected {S.as_str(hook.get('hook_type'))} hook",
        }
    if segs:
        return {
            "text": _seg_text(segs[0]),
            "timestamp": _seg_start(segs[0]),
            "evidence": "opens on the first line of the clip",
        }
    return {"text": "", "timestamp": None, "evidence": "no transcript line available"}


def _closing_payoff(payoffs: list[dict[str, Any]], segs: list[dict[str, Any]]) -> dict[str, Any]:
    if payoffs:
        last = payoffs[-1]
        return {
            "text": S.as_str(last.get("payoff_excerpt")),
            "timestamp": S.as_float(last.get("payoff_timestamp")),
            "evidence": "story payoff lands inside the clip",
        }
    if segs:
        return {
            "text": _seg_text(segs[-1]),
            "timestamp": _seg_start(segs[-1]),
            "evidence": "closes on the last line of the clip",
        }
    return {"text": "", "timestamp": None, "evidence": "no transcript line available"}


def _window_keywords(segs: list[dict[str, Any]]) -> list[str]:
    from collections import Counter

    stop = {
        "the",
        "and",
        "that",
        "this",
        "with",
        "from",
        "your",
        "you",
        "have",
        "what",
        "just",
        "they",
        "for",
    }
    counts: Counter[str] = Counter()
    for s in segs:
        for tok in _seg_text(s).lower().split():
            tok = "".join(ch for ch in tok if ch.isalnum())
            if len(tok) > 3 and tok not in stop:
                counts[tok] += 1
    return [w for w, _ in counts.most_common(6)]


def _scene_cuts(ctx: PlanningStageContext, start: float, end: float) -> dict[str, Any]:
    scenes = (ctx.cognitive_data("scene_detection") or {}).get("scenes")
    if isinstance(scenes, list) and scenes:
        cuts = [
            {"timestamp": S.as_float(sc.get("start"))}
            for sc in scenes
            if S.in_window(S.as_float(sc.get("start")), start, end)
        ]
        return {"cuts": cuts, "note": "from the Cognitive Engine's scene detection"}
    return {"cuts": [], "note": "scene detection is unavailable (no scene model); no cuts asserted"}


def _speaker_switches(ctx: PlanningStageContext, start: float, end: float) -> dict[str, Any]:
    seg = (ctx.cognitive_data("speaker_segmentation") or {}).get("timeline")
    if isinstance(seg, list) and seg:
        switches = [
            {"timestamp": S.as_float(t.get("start")), "speaker": S.as_str(t.get("speaker"))}
            for t in seg
            if S.in_window(S.as_float(t.get("start")), start, end)
        ]
        return {"switches": switches, "note": "from the Cognitive Engine's speaker segmentation"}
    return {"switches": [], "note": "speaker segmentation is unavailable; assume a single speaker"}


def _continuation(sig: dict[str, Any], end: float) -> dict[str, Any]:
    later_payoff = any(S.as_float(r.get("payoff_timestamp")) > end for r in sig["payoffs"])
    return {
        "possible": bool(later_payoff),
        "reason": "a further payoff occurs after this clip, so a part 2 is plausible"
        if later_payoff
        else "no strong follow-on payoff detected after this clip",
    }


def _complexity(score: float, slow_count: int, emotion_count: int) -> dict[str, Any]:
    level = "high" if score >= 0.6 else "low" if score <= 0.3 else "medium"
    return {
        "level": level,
        "score": S.round3(score),
        "factors": {"silence_removals": slow_count, "emotional_punch_ins": emotion_count},
    }


def _explanation(
    cand: dict[str, Any], hook_in_window: bool, payoffs_in: list[dict[str, Any]]
) -> str:
    bits = [f"sourced from a {S.as_str(cand.get('source')).replace('_', ' ')}"]
    if hook_in_window:
        bits.append("opens on a detected hook")
    if payoffs_in:
        bits.append("contains a self-contained payoff")
    bits.append(f"overall quality {S.as_float(cand.get('quality_score'))}")
    return "; ".join(bits) + "."


def _rank_reason(higher: dict[str, Any], lower: dict[str, Any]) -> dict[str, Any]:
    hs, ls = S.as_dict(higher.get("scores")), S.as_dict(lower.get("scores"))
    diffs = sorted(
        (
            (dim, S.as_float(hs.get(dim)) - S.as_float(ls.get(dim)))
            for dim in S.CLIP_QUALITY_WEIGHTS
        ),
        key=lambda kv: kv[1],
        reverse=True,
    )
    top = [d for d, v in diffs if v > 0.03][:2]
    detail = f"stronger {', '.join(top)}" if top else "a higher overall quality blend"
    return {
        "higher": higher.get("id"),
        "lower": lower.get("id"),
        "reason": f"#{higher.get('rank')} outranks #{lower.get('rank')} due to {detail} "
        f"({S.as_float(higher.get('quality_score'))} vs {S.as_float(lower.get('quality_score'))}).",
    }


def _signal_inventory(ctx: PlanningStageContext) -> tuple[list[str], list[dict[str, str]]]:
    checks = {
        "trend_research": ctx.virality_data("trend_research") is not None,
        "virality_heatmap": bool(
            S.as_list((ctx.virality_data("virality_summary") or {}).get("heatmap"))
        ),
        "story_payoffs": bool(
            S.as_list((ctx.story_data("payoff_detection") or {}).get("relationships"))
        ),
        "information_density": ctx.story_data("information_density") is not None,
        "transcript": ctx.transcript_segments() is not None,
    }
    available = [k for k, ok in checks.items() if ok]
    pending = [
        {"signal": k, "reason": "not produced upstream (requires a transcript)"}
        for k, ok in checks.items()
        if not ok
    ]
    return available, pending


def _zero_reason(ctx: PlanningStageContext) -> str:
    gen = ctx.results.get("candidate_generation")
    if gen is not None and gen.status.value == "unavailable":
        return gen.reason or _NO_SIGNALS
    gen_data = ctx.planning_data("candidate_generation") or {}
    if S.as_float(gen_data.get("candidate_count")) == 0:
        return (
            "No clip-worthy moments met the quality bar: no region reached the heat "
            "threshold and no self-contained story arcs or hook were found."
        )
    return (
        "Candidates were found but none survived boundary refinement, scoring, and "
        "de-duplication at a quality worth proposing."
    )


def _low_output_reason(
    ctx: PlanningStageContext,
    generation: dict[str, Any],
    ranking: dict[str, Any],
) -> dict[str, Any] | None:
    plans = S.as_list(ranking.get("plans"))
    strategy = S.as_dict(generation.get("target_clip_strategy"))
    target = int(S.as_float(strategy.get("target"), 0.0))
    minimum = int(S.as_float(strategy.get("minimum"), 1.0))
    if plans and (target <= 0 or len(plans) >= max(1, min(target, minimum))):
        return None
    story_v2 = ctx.story_data("story_analysis_v2") or {}
    summary = ctx.virality_data("virality_summary") or {}
    rejected: list[str] = []
    rejected.extend(
        S.as_str(item.get("reason"))
        for item in S.as_list(ranking.get("over_target"))
        if S.as_str(item.get("reason"))
    )
    low_clip = S.as_dict(ranking.get("low_clip_count_explanation"))
    if low_clip.get("explanation"):
        rejected.append(S.as_str(low_clip.get("explanation")))
    return {
        "source_duration": generation.get("video_duration") or ctx.video_duration(),
        "story_candidate_count": generation.get("story_candidate_count", 0),
        "viral_candidate_count": len(S.as_list(summary.get("heatmap"))),
        "planned_clip_count": len(plans),
        "rendered_clip_count": None,
        "rejected_reasons": rejected[:6],
        "explanation": (
            "Planning produced fewer clips than the target because available Story/Virality "
            "signals did not yield enough distinct high-confidence candidates."
        ),
        "confidence": 0.65 if CI.story_v2_available(story_v2) else 0.45,
    }

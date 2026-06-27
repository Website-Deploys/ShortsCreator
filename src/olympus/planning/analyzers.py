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
from olympus.planning import scoring as S  # noqa: N812 (module alias is intentional)

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


# --------------------------------------------------------------------------- #
# 1. Candidate Generation - find clip-worthy moments from upstream signals.
# --------------------------------------------------------------------------- #
class CandidateGenerationAnalyzer(PlanningAnalyzer):
    name = "candidate_generation"
    version = "1"

    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        summary = ctx.virality_data("virality_summary") or {}
        heatmap = S.as_list(summary.get("heatmap"))
        payoffs = S.as_list((ctx.story_data("payoff_detection") or {}).get("relationships"))
        hook = ctx.story_data("hook_detection") or {}
        segments = ctx.transcript_segments() or []

        if not heatmap and not payoffs and not segments:
            return PlanningOutcome.unavailable(_NO_SIGNALS)

        duration = ctx.video_duration() or (segments and _seg_end(segments[-1])) or 0.0
        candidates: list[dict[str, Any]] = []

        # (a) High-heat regions from the virality heatmap.
        for run in _heat_runs(heatmap, HEAT_THRESHOLD):
            candidates.append(
                {
                    "raw_start": run["start"],
                    "raw_end": run["end"],
                    "source": "heat_region",
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

        # (c) The opening hook (a natural self-contained clip start).
        if hook.get("has_hook"):
            window = S.as_dict(hook.get("window"))
            hs = S.as_float(window.get("start"))
            candidates.append(
                {
                    "raw_start": hs,
                    "raw_end": hs + 30.0,
                    "source": "hook",
                    "peak_heat": None,
                    "evidence": [
                        {"type": "hook", "timestamp": hs, "detail": S.as_str(hook.get("why"))}
                    ],
                }
            )

        report(1.0)
        return PlanningOutcome.completed(
            {
                "candidate_count": len(candidates),
                "candidates": candidates,
                "video_duration": S.round3(float(duration)),
                "thresholds": {"heat_threshold": HEAT_THRESHOLD},
                "note": (
                    "Candidates are clip-worthy moments located from the virality "
                    "heatmap, story payoff arcs, and the opening hook."
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
    version = "1"
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

        refined: list[dict[str, Any]] = []
        for cand in candidates:
            start, end = self._snap(cand["raw_start"], cand["raw_end"], segments, duration)
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
                        "snapped to transcript sentence boundaries"
                        if segments
                        else "raw candidate boundaries (no transcript to snap to)"
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
                "short-form length; exact start/end frames computed from the source fps.",
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
    version = "1"
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
        scored: list[dict[str, Any]] = []
        for cand in candidates:
            scores, confidence, evidence = _score_window(cand["start"], cand["end"], signals)
            scored.append(
                {
                    **cand,
                    "scores": scores,
                    "quality_score": S.round3(S.compute_overall(scores)),
                    "confidence": S.round3(confidence),
                    "score_evidence": evidence,
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
    version = "1"
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
            for keep in survivors:
                iou = S.temporal_iou(
                    cs, ce, S.as_float(keep.get("start")), S.as_float(keep.get("end"))
                )
                if iou > best_iou:
                    best_iou, clash = iou, keep
            if clash is not None and best_iou >= DUPLICATE_IOU:
                duplicates.append(
                    {
                        "id": S.plan_id(cs, ce),
                        "duplicate_of": S.plan_id(
                            S.as_float(clash["start"]), S.as_float(clash["end"])
                        ),
                        "iou": S.round3(best_iou),
                        "reason": f"overlaps a higher-scoring clip by IoU {S.round3(best_iou)}",
                    }
                )
                clash.setdefault("alternatives", []).append(
                    {
                        "id": S.plan_id(cs, ce),
                        "iou": S.round3(best_iou),
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
                "note": "Near-identical moments are merged: the highest-scoring clip is "
                "kept and overlapping ones become ranked alternatives.",
            }
        )


# --------------------------------------------------------------------------- #
# 5. Blueprint Generation - the complete, executable editing instructions.
# --------------------------------------------------------------------------- #
class BlueprintGenerationAnalyzer(PlanningAnalyzer):
    name = "blueprint_generation"
    version = "1"
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
    version = "1"
    depends_on = ("blueprint_generation",)

    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        blueprint = ctx.planning_data("blueprint_generation")
        if blueprint is None:
            return PlanningOutcome.unavailable(
                "Requires blueprint generation, which is unavailable."
            )
        plans = sorted(
            S.as_list(blueprint.get("plans")),
            key=lambda p: (
                S.as_float(p.get("quality_score")),
                S.as_float(p.get("confidence")),
                -S.as_float(S.as_dict(p.get("scores")).get("editing_complexity")),
            ),
            reverse=True,
        )
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
                "note": "Plans are ranked by overall quality, then confidence, then "
                "lower editing complexity; each adjacent pair is explained.",
            }
        )


# --------------------------------------------------------------------------- #
# 7. Planning Summary - aggregate, with an honest zero-clip explanation.
# --------------------------------------------------------------------------- #
class PlanningSummaryAnalyzer(PlanningAnalyzer):
    name = "planning_summary"
    version = "1"
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
        plans = S.as_list(ranking.get("plans"))
        available, pending = _signal_inventory(ctx)

        summaries = [
            {
                "id": p.get("id"),
                "rank": p.get("rank"),
                "start": p.get("start"),
                "end": p.get("end"),
                "duration": p.get("duration"),
                "quality_score": p.get("quality_score"),
                "confidence": p.get("confidence"),
                "title": S.as_dict(S.as_dict(p.get("blueprint")).get("title_suggestion")).get(
                    "text"
                ),
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
    emotion_local = S.clamp01(len(turns_in) / 2)
    story_local = 0.8 if payoffs_in else (0.4 if conflict_secs else 0.2)
    conflict_local = S.clamp01(len(conflict_secs) / 1)
    info_local = S.clamp01(0.5 * mean_entity + 0.5 * mean_div)
    novelty_local = S.clamp01(mean_entity)
    replay_local = 0.7 if payoffs_in else 0.2
    share_local = S.mean([emotion_local, novelty_local, info_local])

    scores: dict[str, float] = {
        "hook": S.round3(_blend(hook_local, _category_prior(cats, "hook"))),
        "retention": S.round3(_blend(mean_density, _category_prior(cats, "retention"))),
        "emotion": S.round3(_blend(emotion_local, _category_prior(cats, "emotion"))),
        "story": S.round3(story_local),
        "virality": S.round3(mean_heat),
        "information": S.round3(_blend(info_local, _category_prior(cats, "information"))),
        "novelty": S.round3(_blend(novelty_local, _category_prior(cats, "novelty"))),
        "shareability": S.round3(_blend(share_local, _category_prior(cats, "sharing"))),
        "conflict": S.round3(_blend(conflict_local, _category_prior(cats, "conflict"))),
        "replay": S.round3(_blend(replay_local, _category_prior(cats, "replay"))),
    }
    # Editing complexity (a cost): more sentences/cuts, slow gaps, emphasis = harder.
    slow = [w for w in dens if S.as_str(w.get("classification")) in ("slow", "filler")]
    complexity = S.clamp01(0.06 * len(segs_in) + 0.1 * len(slow) + 0.08 * len(turns_in))
    scores["editing_complexity"] = S.round3(complexity)

    available = sum(
        bool(x) for x in (heat_cells, dens, turns_in, payoffs_in, segs_in, hook_start is not None)
    )
    confidence = S.coverage_confidence(available, 6)
    evidence = [
        {
            "type": "local_heat",
            "detail": f"mean heat {S.round3(mean_heat)} over {len(heat_cells)} cell(s)",
        },
        {
            "type": "pacing",
            "detail": f"mean density {S.round3(mean_density)} over {len(dens)} window(s)",
        },
        {"type": "emotion", "detail": f"{len(turns_in)} emotional shift(s) in window"},
        {"type": "payoff", "detail": f"{len(payoffs_in)} payoff(s) land in window"},
    ]
    return scores, confidence, evidence


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

    blueprint = {
        "opening_hook": _opening_hook(hook, hook_in_window, segs_in),
        "closing_payoff": _closing_payoff(payoffs_in, segs_in),
        "title_suggestion": {
            "text": (
                _seg_text(segs_in[0])[:70]
                if hook_in_window and segs_in
                else " ".join(keywords[:5]).title()
            ),
            "basis": "opening hook line" if hook_in_window else "top keywords",
            "evidence": keywords[:6],
        },
        "subtitle_style": {
            "style": "word-by-word (karaoke), bold, high-contrast"
            if pacing == "fast"
            else "phrase-by-phrase, clean sans-serif",
            "reason": f"matches {pacing} pacing",
        },
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
    }

    return {
        "id": cand.get("id") or S.plan_id(start, end),
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
        "quality_score": S.as_float(cand.get("quality_score")),
        "confidence": S.as_float(cand.get("confidence")),
        "source": cand.get("source"),
        "explanation": _explanation(cand, hook_in_window, payoffs_in),
        "evidence": S.as_list(cand.get("evidence")) + S.as_list(cand.get("score_evidence")),
        "alternatives": S.as_list(cand.get("alternatives")),
        "blueprint": blueprint,
    }


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

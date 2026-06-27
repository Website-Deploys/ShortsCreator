"""The ten Story Engine stages.

Each analyzer is an isolated, replaceable module behind the
:class:`StoryAnalyzer` contract. None imports another; they communicate only
through the structured :class:`StoryStageContext`. Each consumes the Cognitive
Engine's output (primarily the transcript) and produces evidence-backed
conclusions with explicit confidence.

Honesty rules (enforced by construction):
- When the required input is missing (almost always: no transcript), a stage
  returns ``UNAVAILABLE`` with a clear reason. It never fabricates a narrative.
- Aggregating stages (Story Graph, Story Summary) always complete, but honestly
  report which upstream signals were available vs. pending.
- Every conclusion carries a ``confidence`` in [0, 1] and the supporting
  evidence (transcript excerpts / timestamps) it was derived from. Confidence is
  kept modest because these are transparent heuristics, not certainties.
"""

from __future__ import annotations

import itertools
from typing import Any

from olympus.domain.contracts.story import (
    StoryAnalyzer,
    StoryOutcome,
    StoryProgressReporter,
    StoryStageContext,
)
from olympus.story import heuristics as H  # noqa: N812 (module alias is intentional)

_NO_TRANSCRIPT = (
    "Story analysis requires a transcript from the Cognitive Engine, which is "
    "not available for this video (speech transcription has not produced output "
    "in this environment). No narrative is fabricated without it."
)


# --------------------------------------------------------------------------- #
# 1. Narrative Segmentation - split the transcript by meaning, not by time.
# --------------------------------------------------------------------------- #
class NarrativeSegmentationAnalyzer(StoryAnalyzer):
    name = "narrative_segmentation"
    version = "1"

    #: A new section starts when topical overlap with the running section drops
    #: below this, or a strong discourse cue / long pause appears.
    _similarity_floor = 0.12
    _min_section_seconds = 4.0

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        segments = ctx.transcript_segments()
        if not segments:
            return StoryOutcome.unavailable(_NO_TRANSCRIPT)

        sections: list[dict[str, Any]] = []
        cur_segs: list[dict[str, Any]] = []
        cur_tokens: set[str] = set()
        prev_end = H.seg_start(segments[0])

        def flush() -> None:
            if not cur_segs:
                return
            text = " ".join(H.seg_text(s) for s in cur_segs)
            sections.append(_build_section(len(sections), cur_segs, text))

        for seg in segments:
            text = H.seg_text(seg)
            seg_tokens = set(H.content_tokens(text))
            gap = H.seg_start(seg) - prev_end
            cues = H.find_cues(text)
            strong_cue = any(
                role in cues for role in ("hook", "problem", "conflict", "resolution", "ending")
            )
            duration = H.seg_end(cur_segs[-1]) - H.seg_start(cur_segs[0]) if cur_segs else 0.0

            boundary = False
            if cur_segs and duration >= self._min_section_seconds:
                similarity = H.jaccard(cur_tokens, seg_tokens)
                if similarity < self._similarity_floor or gap > 2.0 or strong_cue:
                    boundary = True

            if boundary:
                flush()
                cur_segs, cur_tokens = [], set()

            cur_segs.append(seg)
            cur_tokens |= seg_tokens
            prev_end = H.seg_end(seg)

        flush()
        _assign_roles(sections)
        report(1.0)
        return StoryOutcome.completed(
            {
                "method": "lexical_cohesion_and_discourse_cues",
                "section_count": len(sections),
                "sections": sections,
                "note": (
                    "Sections are split by meaning (topical cohesion + discourse "
                    "cues), not by fixed time. Roles and confidences are heuristic "
                    "estimates derived from the transcript."
                ),
            }
        )


def _build_section(index: int, segs: list[dict[str, Any]], text: str) -> dict[str, Any]:
    cues = H.find_cues(text)
    # Confidence reflects how clearly this is a coherent unit: cue presence and
    # internal lexical richness raise it; tiny sections lower it.
    base = 0.4 + 0.1 * min(3, len(cues)) + 0.2 * H.lexical_diversity(text)
    return {
        "index": index,
        "start": H.seg_start(segs[0]),
        "end": H.seg_end(segs[-1]),
        "duration": round(H.seg_end(segs[-1]) - H.seg_start(segs[0]), 2),
        "role": "explanation",  # provisional; set by _assign_roles
        "label": "Explanation",
        "keywords": H.keywords(text, 6),
        "cues": cues,
        "confidence": round(H.clamp01(base), 3),
        "reason": "",  # set by _assign_roles
        "supporting_excerpt": H.excerpt(text),
    }


_ROLE_LABELS = {
    "hook": "Hook",
    "introduction": "Introduction",
    "background": "Background",
    "problem": "Problem",
    "explanation": "Explanation",
    "conflict": "Conflict",
    "example": "Example",
    "resolution": "Resolution",
    "ending": "Ending",
}


def _assign_roles(sections: list[dict[str, Any]]) -> None:
    n = len(sections)
    for i, section in enumerate(sections):
        cues: dict[str, list[str]] = section["cues"]
        reason_bits: list[str] = []
        if i == 0:
            # The opening section is setup; a hook cue sharpens it.
            role = "hook" if "hook" in cues else "introduction"
            reason_bits.append("opens the video" + (" with a hook cue" if "hook" in cues else ""))
        elif i == n - 1:
            if "ending" in cues:
                role, note = "ending", "closing cue present"
            elif "resolution" in cues:
                role, note = "resolution", "resolution cue present"
            else:
                role, note = ("ending" if n > 1 else "resolution"), "closes the video"
            reason_bits.append(note)
        else:
            # Middle sections take their role from the strongest discourse cue.
            role = "explanation"
            for candidate in ("problem", "conflict", "example", "background", "resolution"):
                if candidate in cues:
                    role = candidate
                    reason_bits.append(f"discourse cues: {', '.join(cues[candidate][:2])}")
                    break
            else:
                reason_bits.append("no strong cue; explanatory content")
        section["role"] = role
        section["label"] = _ROLE_LABELS.get(role, role.title())
        section["reason"] = "; ".join(reason_bits)


# --------------------------------------------------------------------------- #
# 2. Hook Detection - identify (or honestly deny) the opening hook.
# --------------------------------------------------------------------------- #
class HookDetectionAnalyzer(StoryAnalyzer):
    name = "hook_detection"
    version = "1"
    depends_on = ("narrative_segmentation",)
    _window_seconds = 20.0

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        segments = ctx.transcript_segments()
        if not segments:
            return StoryOutcome.unavailable(_NO_TRANSCRIPT)

        opening = [s for s in segments if H.seg_start(s) <= self._window_seconds] or segments[:1]
        text = " ".join(H.seg_text(s) for s in opening)
        cues = H.find_cues(text)
        shocks = H.shock_terms(text)
        question = H.is_question(text)
        senti = H.sentiment(text)

        hook_type, why, strength = _classify_hook(text, cues, shocks, question, senti)
        has_hook = hook_type is not None
        if not has_hook:
            report(1.0)
            return StoryOutcome.completed(
                {
                    "has_hook": False,
                    "confidence": 0.55,
                    "reason": (
                        "No strong opening hook detected in the first "
                        f"{int(self._window_seconds)}s (no question, bold claim, "
                        "curiosity gap, or emotional opener found)."
                    ),
                    "window": {"start": H.seg_start(opening[0]), "end": H.seg_end(opening[-1])},
                    "supporting_excerpt": H.excerpt(text),
                }
            )
        report(1.0)
        return StoryOutcome.completed(
            {
                "has_hook": True,
                "hook_type": hook_type,
                "why": why,
                "confidence": round(H.clamp01(strength), 3),
                "window": {"start": H.seg_start(opening[0]), "end": H.seg_end(opening[-1])},
                "signals": {
                    "question": question,
                    "shock_terms": shocks,
                    "cues": cues,
                    "sentiment": senti.label,
                },
                "supporting_excerpt": H.excerpt(text),
            }
        )


def _classify_hook(
    text: str,
    cues: dict[str, list[str]],
    shocks: list[str],
    question: bool,
    senti: H.Sentiment,
) -> tuple[str | None, str, float]:
    if question:
        return "question", "Opens with a question that creates a curiosity gap.", 0.7
    if shocks:
        return "shock", f"Opens with attention-grabbing terms: {', '.join(shocks[:3])}.", 0.65
    if "hook" in cues:
        return "curiosity", f"Opens with a curiosity cue: {', '.join(cues['hook'][:2])}.", 0.68
    if senti.arousal >= 0.4 or senti.label in ("excited", "negative", "positive"):
        return "emotion", f"Opens with emotional charge ({senti.label}).", 0.55
    if "background" in cues or text.lower().lstrip().startswith(("when i", "i was", "so i")):
        return "story", "Opens by dropping into a personal story.", 0.5
    # A confident, declarative opener with substance can still be a bold statement.
    if len(H.content_tokens(text)) >= 8 and H.lexical_diversity(text) > 0.6:
        return "bold_statement", "Opens with a dense, declarative statement.", 0.45
    return None, "", 0.0


# --------------------------------------------------------------------------- #
# 3. Topic Segmentation - detect topic shifts via lexical cohesion (TextTiling).
# --------------------------------------------------------------------------- #
class TopicSegmentationAnalyzer(StoryAnalyzer):
    name = "topic_segmentation"
    version = "1"
    _dip_threshold = 0.18

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        segments = ctx.transcript_segments()
        if not segments:
            return StoryOutcome.unavailable(_NO_TRANSCRIPT)
        if len(segments) < 4:
            report(1.0)
            return StoryOutcome.completed(
                {
                    "method": "lexical_cohesion_dips",
                    "topic_count": 1,
                    "shifts": [],
                    "note": "Transcript too short to detect reliable topic shifts.",
                }
            )

        # Adjacent-block similarity; a dip below threshold marks a shift.
        sims: list[float] = []
        for i in range(len(segments) - 1):
            a = set(H.content_tokens(H.seg_text(segments[i])))
            b = set(H.content_tokens(H.seg_text(segments[i + 1])))
            sims.append(H.jaccard(a, b))

        shifts: list[dict[str, Any]] = []
        for i, sim in enumerate(sims):
            if sim <= self._dip_threshold:
                before = " ".join(H.seg_text(s) for s in segments[max(0, i - 2) : i + 1])
                after = " ".join(H.seg_text(s) for s in segments[i + 1 : i + 4])
                old_kw, new_kw = H.keywords(before, 5), H.keywords(after, 5)
                if set(old_kw) == set(new_kw):
                    continue
                shifts.append(
                    {
                        "timestamp": H.seg_end(segments[i]),
                        "old_topic": old_kw,
                        "new_topic": new_kw,
                        "confidence": round(H.clamp01(0.4 + (self._dip_threshold - sim)), 3),
                        "reason": (
                            f"Lexical overlap dropped to {round(sim, 2)} between "
                            "adjacent passages, indicating a topic change."
                        ),
                    }
                )
        report(1.0)
        return StoryOutcome.completed(
            {
                "method": "lexical_cohesion_dips",
                "topic_count": len(shifts) + 1,
                "shifts": shifts,
            }
        )


# --------------------------------------------------------------------------- #
# 4. Narrative Arc - map sections onto beginning/middle/end + dramatic roles.
# --------------------------------------------------------------------------- #
class NarrativeArcAnalyzer(StoryAnalyzer):
    name = "narrative_arc"
    version = "1"
    depends_on = ("narrative_segmentation",)

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        seg = ctx.story_data("narrative_segmentation")
        if not seg or not seg.get("sections"):
            return StoryOutcome.unavailable(
                "Requires narrative segmentation, which is unavailable (no transcript)."
            )
        sections = seg["sections"]
        roles = [s["role"] for s in sections]
        n = len(sections)
        third = max(1, n // 3)
        beginning = roles[:third]
        end = roles[-third:] if n >= 3 else roles[-1:]
        middle = roles[third : n - third] if n >= 3 else []

        has_setup = bool({"hook", "introduction", "background"} & set(beginning))
        has_conflict = "conflict" in roles or "problem" in roles
        has_resolution = bool({"resolution", "ending"} & set(end))

        if has_setup and has_conflict and has_resolution:
            arc_type, conf = "classic_setup_conflict_resolution", 0.65
        elif has_setup and has_resolution:
            arc_type, conf = "setup_and_resolution", 0.55
        elif n >= 5 and not has_conflict:
            arc_type, conf = "list_or_explainer", 0.5
        else:
            arc_type, conf = "loosely_structured", 0.4

        report(1.0)
        return StoryOutcome.completed(
            {
                "arc_type": arc_type,
                "confidence": conf,
                "beginning": beginning,
                "middle": middle,
                "end": end,
                "has_setup": has_setup,
                "has_conflict": has_conflict,
                "has_resolution": has_resolution,
                "role_sequence": roles,
                "reason": (
                    f"Derived from {n} narrative section(s): setup={has_setup}, "
                    f"conflict={has_conflict}, resolution={has_resolution}."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 5. Payoff Detection - link early setups/questions to later answers/reveals.
# --------------------------------------------------------------------------- #
class PayoffDetectionAnalyzer(StoryAnalyzer):
    name = "payoff_detection"
    version = "1"
    depends_on = ("narrative_segmentation",)
    _min_gap_seconds = 5.0

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        segments = ctx.transcript_segments()
        if not segments:
            return StoryOutcome.unavailable(_NO_TRANSCRIPT)

        setups = [
            s
            for s in segments
            if H.is_question(H.seg_text(s)) or H.find_cues(H.seg_text(s)).get("hook")
        ]
        relationships: list[dict[str, Any]] = []
        for setup in setups:
            setup_kw = set(H.keywords(H.seg_text(setup), 6))
            if not setup_kw:
                continue
            for cand in segments:
                if H.seg_start(cand) - H.seg_end(setup) < self._min_gap_seconds:
                    continue
                cand_text = H.seg_text(cand)
                payoff_cues = H.find_phrases(cand_text, H.PAYOFF_CUES)
                overlap = len(setup_kw & set(H.content_tokens(cand_text)))
                if payoff_cues and overlap >= 1:
                    conf = H.clamp01(0.4 + 0.1 * overlap + 0.1 * len(payoff_cues))
                    relationships.append(
                        {
                            "type": "question_answered"
                            if H.is_question(H.seg_text(setup))
                            else "promise_fulfilled",
                            "setup_timestamp": H.seg_start(setup),
                            "setup_excerpt": H.excerpt(H.seg_text(setup), 160),
                            "payoff_timestamp": H.seg_start(cand),
                            "payoff_excerpt": H.excerpt(cand_text, 160),
                            "confidence": round(conf, 3),
                            "evidence": {
                                "shared_keywords": sorted(
                                    setup_kw & set(H.content_tokens(cand_text))
                                ),
                                "payoff_cues": payoff_cues,
                            },
                        }
                    )
                    break  # first plausible payoff per setup
        report(1.0)
        return StoryOutcome.completed(
            {
                "payoff_count": len(relationships),
                "relationships": relationships,
                "note": (
                    "Payoffs link an earlier question/promise to a later passage "
                    "that shares its keywords and uses answer/reveal language."
                    if relationships
                    else "No clear setup\u2192payoff relationships were detected."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 6. Emotional Turning Points - prefer cognitive emotion data, else estimate.
# --------------------------------------------------------------------------- #
class EmotionalTurningPointsAnalyzer(StoryAnalyzer):
    name = "emotional_turning_points"
    version = "1"
    depends_on = ("narrative_segmentation",)

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        emotion = ctx.cognitive_data("emotion_timeline")
        if emotion and emotion.get("timeline"):
            return self._from_emotion_timeline(emotion["timeline"], report)

        seg = ctx.story_data("narrative_segmentation")
        if not seg or not seg.get("sections"):
            return StoryOutcome.unavailable(
                "Emotional turning points need either the Cognitive Engine's "
                "emotion timeline (unavailable) or a transcript (unavailable). "
                "Emotion is an estimate and is never fabricated."
            )
        return self._estimate_from_sections(seg["sections"], report)

    def _from_emotion_timeline(
        self, timeline: list[dict[str, Any]], report: StoryProgressReporter
    ) -> StoryOutcome:
        points: list[dict[str, Any]] = []
        prev: str | None = None
        for entry in timeline:
            label = str(entry.get("emotion") or entry.get("label") or "neutral")
            if prev is not None and label != prev:
                points.append(
                    {
                        "previous_emotion": prev,
                        "new_emotion": label,
                        "timestamp": entry.get("start") or entry.get("timestamp"),
                        "confidence": round(H.clamp01(float(entry.get("confidence", 0.6))), 3),
                        "method": "cognitive_emotion_timeline",
                    }
                )
            prev = label
        report(1.0)
        return StoryOutcome.completed(
            {
                "method": "cognitive_emotion_timeline",
                "turning_point_count": len(points),
                "turning_points": points,
            }
        )

    def _estimate_from_sections(
        self, sections: list[dict[str, Any]], report: StoryProgressReporter
    ) -> StoryOutcome:
        points: list[dict[str, Any]] = []
        prev: str | None = None
        for section in sections:
            senti = H.sentiment(section.get("supporting_excerpt", ""))
            label = senti.label
            if prev is not None and label != prev and label != "neutral":
                points.append(
                    {
                        "previous_emotion": prev,
                        "new_emotion": label,
                        "timestamp": section["start"],
                        "confidence": round(H.clamp01(0.3 + 0.2 * senti.arousal), 3),
                        "method": "estimated_from_transcript",
                        "evidence": H.excerpt(section.get("supporting_excerpt", ""), 140),
                    }
                )
            prev = label
        report(1.0)
        return StoryOutcome.completed(
            {
                "method": "estimated_from_transcript",
                "turning_point_count": len(points),
                "turning_points": points,
                "note": (
                    "Estimated from transcript sentiment lexicons because no "
                    "emotion model is configured. Confidence is intentionally low."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 7. Information Density - dense vs. slow vs. filler vs. repetitive passages.
# --------------------------------------------------------------------------- #
class InformationDensityAnalyzer(StoryAnalyzer):
    name = "information_density"
    version = "1"
    _window_seconds = 15.0

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        segments = ctx.transcript_segments()
        if not segments:
            return StoryOutcome.unavailable(_NO_TRANSCRIPT)

        windows = _time_windows(segments, self._window_seconds)
        out: list[dict[str, Any]] = []
        for start, end, segs in windows:
            text = " ".join(H.seg_text(s) for s in segs)
            diversity = H.lexical_diversity(text)
            entities = H.entity_density(text)
            filler = H.filler_ratio(text)
            repetition = H.repetition_ratio(text)
            density = H.clamp01(
                0.55 * diversity + 0.45 * entities - 0.3 * filler - 0.3 * repetition
            )
            classification = _classify_density(density, filler, repetition)
            out.append(
                {
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "density": round(density, 3),
                    "classification": classification,
                    "confidence": 0.5,
                    "metrics": {
                        "lexical_diversity": round(diversity, 3),
                        "entity_density": round(entities, 3),
                        "filler_ratio": round(filler, 3),
                        "repetition_ratio": round(repetition, 3),
                    },
                    "reason": _density_reason(classification),
                }
            )
        report(1.0)
        dense = [w for w in out if w["classification"] == "dense"]
        return StoryOutcome.completed(
            {
                "method": "lexical_and_filler_metrics",
                "window_seconds": self._window_seconds,
                "windows": out,
                "dense_window_count": len(dense),
                "note": "Density is a transparent estimate from word-level metrics, not a model.",
            }
        )


def _classify_density(density: float, filler: float, repetition: float) -> str:
    if filler >= 0.18:
        return "filler"
    if repetition >= 0.4:
        return "repetition"
    if density >= 0.5:
        return "dense"
    if density <= 0.2:
        return "slow"
    return "moderate"


def _density_reason(classification: str) -> str:
    return {
        "dense": "High lexical variety and factual markers; information-rich.",
        "slow": "Low lexical variety; little new information.",
        "filler": "High proportion of filler/hedge words.",
        "repetition": "High repetition of phrasing.",
        "moderate": "A balanced mix of new information and connective language.",
    }[classification]


def _time_windows(
    segments: list[dict[str, Any]], window: float
) -> list[tuple[float, float, list[dict[str, Any]]]]:
    if not segments:
        return []
    start0 = H.seg_start(segments[0])
    end_total = H.seg_end(segments[-1])
    out: list[tuple[float, float, list[dict[str, Any]]]] = []
    t = start0
    while t < end_total or not out:
        w_end = t + window
        bucket = [s for s in segments if H.seg_start(s) < w_end and H.seg_end(s) > t]
        if bucket:
            out.append((t, min(w_end, end_total), bucket))
        t = w_end
        if t >= end_total:
            break
    return out


# --------------------------------------------------------------------------- #
# 8. Context Dependencies - where later moments rely on earlier ones.
# --------------------------------------------------------------------------- #
class ContextDependenciesAnalyzer(StoryAnalyzer):
    name = "context_dependencies"
    version = "1"
    _min_gap_seconds = 30.0

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        segments = ctx.transcript_segments()
        if not segments:
            return StoryOutcome.unavailable(_NO_TRANSCRIPT)

        first_seen: dict[str, float] = {}
        references: list[dict[str, Any]] = []
        for seg in segments:
            text = H.seg_text(seg)
            now = H.seg_start(seg)
            backrefs = H.find_phrases(text, H.BACKREFERENCE_CUES)
            terms = H.content_tokens(text)

            if backrefs:
                # Find the most recent salient earlier term to attribute it to.
                earlier = [
                    (term, first_seen[term])
                    for term in set(terms)
                    if term in first_seen and now - first_seen[term] >= self._min_gap_seconds
                ]
                target = max(earlier, key=lambda x: x[1]) if earlier else None
                references.append(
                    {
                        "type": "explicit_backreference",
                        "from_timestamp": now,
                        "from_excerpt": H.excerpt(text, 160),
                        "depends_on_timestamp": target[1] if target else None,
                        "term": target[0] if target else None,
                        "confidence": round(0.6 if target else 0.4, 3),
                        "evidence": {"cues": backrefs},
                    }
                )

            for term in set(terms):
                if term in first_seen:
                    gap = now - first_seen[term]
                    if gap >= self._min_gap_seconds and len(term) >= 5:
                        references.append(
                            {
                                "type": "term_reintroduction",
                                "from_timestamp": now,
                                "from_excerpt": H.excerpt(text, 140),
                                "depends_on_timestamp": first_seen[term],
                                "term": term,
                                "confidence": 0.35,
                                "evidence": {
                                    "reintroduced_term": term,
                                    "gap_seconds": round(gap, 1),
                                },
                            }
                        )
                else:
                    first_seen[term] = now

        # Keep the strongest, de-duplicated references.
        references.sort(key=lambda r: r["confidence"], reverse=True)
        report(1.0)
        return StoryOutcome.completed(
            {
                "method": "backreference_cues_and_term_reintroduction",
                "reference_count": len(references),
                "references": references[:50],
                "note": "Dependencies show where later passages rely on earlier context.",
            }
        )


# --------------------------------------------------------------------------- #
# 9. Story Graph - aggregate everything into one structured graph.
# --------------------------------------------------------------------------- #
class StoryGraphAnalyzer(StoryAnalyzer):
    name = "story_graph"
    version = "1"
    depends_on = (
        "narrative_segmentation",
        "hook_detection",
        "topic_segmentation",
        "narrative_arc",
        "payoff_detection",
        "emotional_turning_points",
        "context_dependencies",
    )

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        available, pending = _signal_inventory(ctx, self.depends_on)
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        sections = (ctx.story_data("narrative_segmentation") or {}).get("sections", [])
        for s in sections:
            nodes.append(
                {
                    "id": f"section:{s['index']}",
                    "kind": "section",
                    "role": s["role"],
                    "start": s["start"],
                    "end": s["end"],
                }
            )
        for a, b in itertools.pairwise(sections):
            edges.append(
                {"from": f"section:{a['index']}", "to": f"section:{b['index']}", "kind": "follows"}
            )

        hook = ctx.story_data("hook_detection")
        if hook and hook.get("has_hook"):
            nodes.append(
                {
                    "id": "hook",
                    "kind": "hook",
                    "hook_type": hook.get("hook_type"),
                    "start": hook["window"]["start"],
                }
            )

        for i, shift in enumerate((ctx.story_data("topic_segmentation") or {}).get("shifts", [])):
            nodes.append(
                {
                    "id": f"topic_shift:{i}",
                    "kind": "topic_shift",
                    "timestamp": shift["timestamp"],
                    "new_topic": shift["new_topic"],
                }
            )

        for i, rel in enumerate(
            (ctx.story_data("payoff_detection") or {}).get("relationships", [])
        ):
            nodes.append(
                {"id": f"payoff:{i}", "kind": "payoff", "timestamp": rel["payoff_timestamp"]}
            )
            edges.append(
                {
                    "from": f"payoff:{i}",
                    "to": f"payoff:{i}",
                    "kind": "setup_to_payoff",
                    "setup_timestamp": rel["setup_timestamp"],
                }
            )

        for i, tp in enumerate(
            (ctx.story_data("emotional_turning_points") or {}).get("turning_points", [])
        ):
            nodes.append(
                {
                    "id": f"emotion_shift:{i}",
                    "kind": "emotion_shift",
                    "timestamp": tp.get("timestamp"),
                    "from": tp["previous_emotion"],
                    "to": tp["new_emotion"],
                }
            )

        for i, ref in enumerate(
            (ctx.story_data("context_dependencies") or {}).get("references", [])
        ):
            edges.append(
                {
                    "from": f"ref:{i}",
                    "to": "context",
                    "kind": "depends_on",
                    "from_timestamp": ref["from_timestamp"],
                    "depends_on_timestamp": ref["depends_on_timestamp"],
                }
            )

        report(1.0)
        return StoryOutcome.completed(
            {
                "available_signals": available,
                "pending_signals": pending,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "nodes": nodes,
                "edges": edges,
                "confidence": round(
                    _aggregate_confidence(len(available), len(available) + len(pending)), 3
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 10. Story Summary - an internal engineering summary (not marketing copy).
# --------------------------------------------------------------------------- #
class StorySummaryAnalyzer(StoryAnalyzer):
    name = "story_summary"
    version = "1"
    depends_on = (
        "narrative_segmentation",
        "hook_detection",
        "topic_segmentation",
        "narrative_arc",
        "payoff_detection",
        "emotional_turning_points",
        "information_density",
        "context_dependencies",
    )

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        available, pending = _signal_inventory(ctx, self.depends_on)
        segments = ctx.transcript_segments()
        sections = (ctx.story_data("narrative_segmentation") or {}).get("sections", [])
        arc = ctx.story_data("narrative_arc") or {}
        payoffs = (ctx.story_data("payoff_detection") or {}).get("relationships", [])
        density = (ctx.story_data("information_density") or {}).get("windows", [])
        turning = (ctx.story_data("emotional_turning_points") or {}).get("turning_points", [])

        full_text = " ".join(H.seg_text(s) for s in segments) if segments else ""
        main_subject = H.keywords(full_text, 8) if full_text else []
        secondary = [
            s["new_topic"] for s in (ctx.story_data("topic_segmentation") or {}).get("shifts", [])
        ]
        key_lessons = [
            H.excerpt(s.get("supporting_excerpt", ""), 160)
            for s in sections
            if s["role"] in ("resolution", "ending")
        ]
        important_moments = _important_moments(sections, payoffs, density, turning)

        summary = {
            "main_subject": main_subject,
            "primary_narrative": {
                "arc_type": arc.get("arc_type"),
                "role_sequence": arc.get("role_sequence", [s["role"] for s in sections]),
            },
            "secondary_topics": secondary[:8],
            "key_lessons": key_lessons[:5],
            "major_events": [
                {
                    "type": "payoff",
                    "timestamp": p["payoff_timestamp"],
                    "excerpt": p["payoff_excerpt"],
                }
                for p in payoffs[:5]
            ],
            "story_flow": [
                {
                    "role": s["role"],
                    "start": s["start"],
                    "end": s["end"],
                    "keywords": s["keywords"][:4],
                }
                for s in sections
            ],
            "important_moments": important_moments,
            "available_signals": available,
            "pending_signals": pending,
            "confidence": round(
                _aggregate_confidence(len(available), len(available) + len(pending)), 3
            ),
            "note": (
                "Engineering summary of the story for downstream use; not marketing "
                "copy. Empty fields mean the underlying signal was unavailable, not "
                "that it was analyzed and found absent."
            ),
        }
        report(1.0)
        return StoryOutcome.completed(summary)


# --------------------------------------------------------------------------- #
# Shared aggregation helpers (pure; not stage-to-stage coupling).
# --------------------------------------------------------------------------- #
def _signal_inventory(
    ctx: StoryStageContext, deps: tuple[str, ...]
) -> tuple[list[str], list[dict[str, str]]]:
    available: list[str] = []
    pending: list[dict[str, str]] = []
    for name in deps:
        result = ctx.results.get(name)
        if result is not None and result.status.value == "completed":
            available.append(name)
        else:
            reason = (result.reason or result.error or "not available") if result else "did not run"
            pending.append({"stage": name, "reason": reason})
    return available, pending


def _aggregate_confidence(available: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return H.clamp01(available / total)


def _important_moments(
    sections: list[dict[str, Any]],
    payoffs: list[dict[str, Any]],
    density: list[dict[str, Any]],
    turning: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    moments: list[dict[str, Any]] = []
    if sections:
        moments.append({"type": "opening", "timestamp": sections[0]["start"], "confidence": 0.5})
    for p in payoffs[:3]:
        moments.append(
            {"type": "payoff", "timestamp": p["payoff_timestamp"], "confidence": p["confidence"]}
        )
    dense_windows = [w for w in density if w["classification"] == "dense"][:3]
    for w in dense_windows:
        moments.append(
            {"type": "dense_passage", "timestamp": w["start"], "confidence": w["confidence"]}
        )
    for t in turning[:3]:
        moments.append(
            {
                "type": "emotional_shift",
                "timestamp": t.get("timestamp"),
                "confidence": t["confidence"],
            }
        )
    moments.sort(key=lambda m: m["timestamp"] if m["timestamp"] is not None else 0)
    return moments

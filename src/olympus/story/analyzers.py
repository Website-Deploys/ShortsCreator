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
# 9. Story Analysis V2 - micro-stories, completeness, repair, guidance.
# --------------------------------------------------------------------------- #
class StoryAnalysisV2Analyzer(StoryAnalyzer):
    name = "story_analysis_v2"
    version = "1"
    depends_on = (
        "narrative_segmentation",
        "topic_segmentation",
        "narrative_arc",
        "payoff_detection",
        "emotional_turning_points",
        "information_density",
        "context_dependencies",
    )

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        segments = ctx.transcript_segments()
        if not segments:
            return StoryOutcome.unavailable(_NO_TRANSCRIPT)

        source_duration = ctx.project.duration_seconds or H.seg_end(segments[-1])
        transcript_coverage = _transcript_coverage(segments, source_duration)
        narrative = ctx.story_data("narrative_segmentation") or {}
        topics = ctx.story_data("topic_segmentation") or {}
        arc = ctx.story_data("narrative_arc") or {}
        payoff_data = ctx.story_data("payoff_detection") or {}
        emotion = ctx.story_data("emotional_turning_points") or {}
        density = ctx.story_data("information_density") or {}
        context = ctx.story_data("context_dependencies") or {}

        sections = _topic_sections_v2(
            segments,
            H.as_list(narrative.get("sections")),
            H.as_list(topics.get("shifts")),
            H.as_list(density.get("windows")),
        )
        filler_sections = _filler_sections_v2(segments, H.as_list(density.get("windows")))
        repeated_sections = _repeated_sections_v2(sections)
        speaker_intents = _speaker_intents_v2(segments)
        conflict_points = _conflict_points_v2(segments)
        turning_points = _turning_points_v2(
            segments,
            H.as_list(emotion.get("turning_points")),
        )
        payoff_points = _payoff_points_v2(
            segments,
            H.as_list(payoff_data.get("relationships")),
        )
        emotional_timeline = _emotional_timeline_v2(sections, turning_points)

        candidate_windows = _micro_story_windows(
            sections,
            turning_points,
            payoff_points,
            float(source_duration),
        )
        micro_stories = [
            _build_micro_story_v2(
                idx,
                window,
                segments,
                H.as_list(payoff_data.get("relationships")),
                turning_points,
                H.as_list(context.get("references")),
                filler_sections,
                float(source_duration),
            )
            for idx, window in enumerate(candidate_windows)
        ]
        micro_stories = _dedupe_micro_stories(micro_stories)
        weak_sections = _weak_sections_v2(sections, micro_stories, filler_sections)
        recommended = [
            story
            for story in micro_stories
            if story["recommended_for_planning"] and not story["rejection_reason"]
        ][:20]
        long_map = _long_video_story_map(
            float(source_duration),
            sections,
            micro_stories,
            filler_sections,
        )
        low_count_reason = _low_story_count_reason(
            float(source_duration),
            transcript_coverage,
            sections,
            micro_stories,
        )

        report(1.0)
        return StoryOutcome.completed(
            {
                "schema": "story_analysis_v2",
                "project_id": ctx.project.id,
                "source_duration": round(float(source_duration), 3),
                "transcript_coverage": transcript_coverage,
                "primary_themes": H.keywords(" ".join(H.seg_text(s) for s in segments), 10),
                "topic_sections": sections,
                "narrative_arcs": [
                    {
                        "arc_type": arc.get("arc_type"),
                        "role_sequence": arc.get("role_sequence", []),
                        "confidence": arc.get("confidence", 0.0),
                        "reason": arc.get("reason", ""),
                    }
                ],
                "micro_stories": micro_stories,
                "emotional_timeline": emotional_timeline,
                "speaker_intents": speaker_intents,
                "conflict_points": conflict_points,
                "turning_points": turning_points,
                "payoff_points": payoff_points,
                "filler_sections": filler_sections,
                "repeated_sections": repeated_sections,
                "weak_sections": weak_sections,
                "recommended_clip_stories": recommended,
                "story_quality_summary": _story_quality_summary(micro_stories),
                "long_video_story_map": long_map,
                "low_story_count_reason": low_count_reason,
                "virality_story_guidance": _virality_story_guidance(recommended),
                "planning_story_guidance": _planning_story_guidance(recommended),
                "editing_story_guidance": _editing_story_guidance(recommended),
                "warnings": _story_v2_warnings(
                    transcript_coverage,
                    micro_stories,
                    low_count_reason,
                ),
                "note": (
                    "Story V2 is deterministic transcript analysis. It marks missing setup, "
                    "missing payoff, context risk, and weak endings instead of inventing arcs."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 10. Story Graph - aggregate everything into one structured graph.
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
        "story_analysis_v2",
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
        v2 = ctx.story_data("story_analysis_v2") or {}
        for story in v2.get("recommended_clip_stories", [])[:20]:
            nodes.append(
                {
                    "id": story.get("story_id"),
                    "kind": "micro_story",
                    "start": story.get("start"),
                    "end": story.get("end"),
                    "shape": story.get("story_shape"),
                    "completeness": story.get("completeness_score"),
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
        "story_analysis_v2",
    )

    async def analyze(self, ctx: StoryStageContext, report: StoryProgressReporter) -> StoryOutcome:
        available, pending = _signal_inventory(ctx, self.depends_on)
        segments = ctx.transcript_segments()
        sections = (ctx.story_data("narrative_segmentation") or {}).get("sections", [])
        arc = ctx.story_data("narrative_arc") or {}
        payoffs = (ctx.story_data("payoff_detection") or {}).get("relationships", [])
        density = (ctx.story_data("information_density") or {}).get("windows", [])
        turning = (ctx.story_data("emotional_turning_points") or {}).get("turning_points", [])
        story_v2 = ctx.story_data("story_analysis_v2") or {}

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
            "story_analysis_v2": {
                "micro_story_count": len(story_v2.get("micro_stories", [])),
                "recommended_count": len(story_v2.get("recommended_clip_stories", [])),
                "quality_summary": story_v2.get("story_quality_summary", {}),
                "warnings": story_v2.get("warnings", []),
            },
            "top_micro_stories": [
                {
                    "story_id": story.get("story_id"),
                    "title": story.get("title"),
                    "start": story.get("start"),
                    "end": story.get("end"),
                    "story_shape": story.get("story_shape"),
                    "completeness_score": story.get("completeness_score"),
                    "payoff": (story.get("payoff") or {}).get("payoff_text")
                    if isinstance(story.get("payoff"), dict)
                    else "",
                }
                for story in story_v2.get("recommended_clip_stories", [])[:5]
            ],
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


# --------------------------------------------------------------------------- #
# Story Analysis V2 helpers.
# --------------------------------------------------------------------------- #
def _transcript_coverage(segments: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    covered = sum(max(0.0, H.seg_end(seg) - H.seg_start(seg)) for seg in segments)
    return {
        "segment_count": len(segments),
        "covered_seconds": round(covered, 3),
        "source_duration": round(duration, 3),
        "coverage_ratio": round(H.clamp01(covered / duration if duration > 0 else 0.0), 3),
        "first_timestamp": round(H.seg_start(segments[0]), 3) if segments else None,
        "last_timestamp": round(H.seg_end(segments[-1]), 3) if segments else None,
    }


def _topic_sections_v2(
    segments: list[dict[str, Any]],
    narrative_sections: list[Any],
    topic_shifts: list[Any],
    density_windows: list[Any],
) -> list[dict[str, Any]]:
    boundaries = [H.seg_start(segments[0])]
    for shift in topic_shifts:
        if isinstance(shift, dict):
            boundaries.append(float(shift.get("timestamp") or boundaries[-1]))
    boundaries.append(H.seg_end(segments[-1]))
    boundaries = sorted({round(boundary, 3) for boundary in boundaries})
    if len(boundaries) <= 2 and len(narrative_sections) > 1:
        boundaries = sorted(
            {
                round(float(section.get("start") or 0.0), 3)
                for section in narrative_sections
                if isinstance(section, dict)
            }
            | {round(H.seg_end(segments[-1]), 3)}
        )

    sections: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(itertools.pairwise(boundaries)):
        if end <= start:
            continue
        segs = _segments_between(segments, start, end)
        if not segs:
            continue
        text = _span_text(segs)
        keywords = H.keywords(text, 6)
        intent = _intent_for_text(text)
        tone = H.sentiment(text)
        density = _density_for_span(start, end, density_windows)
        story_potential = _story_potential_for_text(text, density)
        sections.append(
            {
                "section_id": f"topic_{index}",
                "start": round(start, 3),
                "end": round(end, 3),
                "title": _section_title(intent, keywords),
                "summary": H.excerpt(text, 180),
                "keywords": keywords,
                "speaker_ids": _speaker_ids(segs),
                "intent": intent,
                "emotional_tone": tone.label,
                "density_score": round(density, 3),
                "story_potential": round(story_potential, 3),
                "viral_potential_handoff": {
                    "hookable": bool(H.is_question(text) or H.find_cues(text).get("hook")),
                    "payoff_cues": H.find_phrases(text, H.PAYOFF_CUES)[:4],
                    "keywords": keywords[:4],
                },
                "recommended_for_clips": story_potential >= 0.45,
                "evidence": [H.excerpt(text, 220)],
            }
        )
    return sections


def _segments_between(
    segments: list[dict[str, Any]],
    start: float,
    end: float,
) -> list[dict[str, Any]]:
    return [
        seg
        for seg in segments
        if max(0.0, min(H.seg_end(seg), end) - max(H.seg_start(seg), start)) > 0
    ]


def _span_text(segments: list[dict[str, Any]]) -> str:
    return " ".join(H.seg_text(seg) for seg in segments).strip()


def _speaker_ids(segments: list[dict[str, Any]]) -> list[str]:
    speakers = {
        str(seg.get("speaker"))
        for seg in segments
        if seg.get("speaker") not in (None, "", "unknown")
    }
    return sorted(speakers)


def _section_title(intent: str, keywords: list[str]) -> str:
    topic = " ".join(keywords[:4]).title() if keywords else "Story Section"
    return f"{intent.replace('_', ' ').title()}: {topic}"


def _intent_for_text(text: str) -> str:
    low = text.lower()
    if H.filler_ratio(text) >= 0.16:
        return "filler"
    if H.is_question(text):
        return "answering"
    if any(cue in low for cue in ("warning", "avoid", "don't", "stop ")):
        return "warning"
    if any(cue in low for cue in ("i realized", "honestly", "i struggled", "i felt")):
        return "confessing"
    if any(cue in low for cue in ("joke", "funny", "laugh", "no way")):
        return "joking"
    if any(cue in low for cue in ("the lesson", "what i learned", "discipline", "dream")):
        return "motivating"
    if any(cue in low for cue in ("the reason", "this is how", "for example", "because")):
        return "teaching"
    if any(cue in low for cue in ("but then", "the problem", "however", "challenge")):
        return "storytelling"
    if any(cue in low for cue in ("so", "to summarize", "in conclusion")):
        return "summarizing"
    return "explaining"


def _density_for_span(start: float, end: float, density_windows: list[Any]) -> float:
    scores = [
        float(window.get("density") or 0.0)
        for window in density_windows
        if isinstance(window, dict)
        and max(
            0.0,
            min(float(window.get("end") or 0.0), end)
            - max(float(window.get("start") or 0.0), start),
        )
        > 0
    ]
    return sum(scores) / len(scores) if scores else 0.35


def _story_potential_for_text(text: str, density: float) -> float:
    cues = H.find_cues(text)
    payoff = 1.0 if H.find_phrases(text, H.PAYOFF_CUES) else 0.0
    tension = 1.0 if {"problem", "conflict", "hook"} & set(cues) or H.is_question(text) else 0.0
    filler_penalty = H.filler_ratio(text) * 0.7
    return H.clamp01(0.35 * density + 0.25 * payoff + 0.3 * tension + 0.1 - filler_penalty)


def _filler_sections_v2(
    segments: list[dict[str, Any]], density_windows: list[Any]
) -> list[dict[str, Any]]:
    filler: list[dict[str, Any]] = []
    for window in density_windows:
        if not isinstance(window, dict):
            continue
        classification = str(window.get("classification") or "")
        if classification not in {"filler", "slow", "repetition"}:
            continue
        start = float(window.get("start") or 0.0)
        end = float(window.get("end") or start)
        text = _span_text(_segments_between(segments, start, end))
        severity = 0.75 if classification == "filler" else 0.55
        filler.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "type": classification,
                "text": H.excerpt(text, 180),
                "severity": severity,
                "should_remove": classification in {"filler", "repetition"},
                "reason": str(window.get("reason") or _density_reason(classification)),
            }
        )
    for seg in segments:
        text = H.seg_text(seg)
        if H.filler_ratio(text) >= 0.22:
            filler.append(
                {
                    "start": H.seg_start(seg),
                    "end": H.seg_end(seg),
                    "type": "filler_words",
                    "text": H.excerpt(text, 160),
                    "severity": round(H.clamp01(H.filler_ratio(text) * 3), 3),
                    "should_remove": True,
                    "reason": "high filler-word ratio in transcript segment",
                }
            )
    return filler[:80]


def _repeated_sections_v2(topic_sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repeated: list[dict[str, Any]] = []
    seen: list[tuple[str, set[str], dict[str, Any]]] = []
    for section in topic_sections:
        words = set(section.get("keywords", []))
        for earlier_id, earlier_words, earlier in seen:
            if not words or not earlier_words:
                continue
            overlap = len(words & earlier_words) / max(1, len(words | earlier_words))
            if overlap >= 0.72:
                repeated.append(
                    {
                        "section_id": section["section_id"],
                        "repeats_section_id": earlier_id,
                        "start": section["start"],
                        "end": section["end"],
                        "similarity": round(overlap, 3),
                        "reason": "topic keywords heavily overlap with an earlier section",
                        "evidence": {
                            "current_keywords": sorted(words),
                            "earlier_keywords": earlier.get("keywords", []),
                        },
                    }
                )
                break
        seen.append((section["section_id"], words, section))
    return repeated


def _speaker_intents_v2(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for seg in segments:
        text = H.seg_text(seg)
        intent = _intent_for_text(text)
        spans.append(
            {
                "start": H.seg_start(seg),
                "end": H.seg_end(seg),
                "intent": intent,
                "confidence": 0.62 if intent != "explaining" else 0.45,
                "evidence": H.excerpt(text, 160),
                "story_value": _intent_story_value(intent),
            }
        )
    return spans


def _intent_story_value(intent: str) -> float:
    return {
        "confessing": 0.78,
        "warning": 0.74,
        "storytelling": 0.72,
        "teaching": 0.62,
        "motivating": 0.66,
        "answering": 0.58,
        "joking": 0.6,
        "summarizing": 0.55,
        "explaining": 0.45,
        "filler": 0.12,
    }.get(intent, 0.4)


def _conflict_points_v2(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for seg in segments:
        text = H.seg_text(seg)
        cues = H.find_cues(text)
        if not ({"problem", "conflict"} & set(cues)):
            continue
        points.append(
            {
                "time": H.seg_start(seg),
                "text": H.excerpt(text, 180),
                "type": "conflict" if "conflict" in cues else "problem",
                "confidence": 0.62,
                "evidence": cues.get("conflict") or cues.get("problem") or [],
            }
        )
    return points


TURNING_POINT_CUES: tuple[tuple[str, str], ...] = (
    ("but then", "reversal"),
    ("however", "contrast"),
    ("until", "threshold"),
    ("that's when", "realization"),
    ("i realized", "realization"),
    ("the problem was", "diagnosis"),
    ("the truth is", "reveal"),
    ("everything changed", "transformation"),
    ("the reason is", "explanation"),
    ("then i found out", "reveal"),
    ("suddenly", "surprise"),
    ("but the real lesson", "lesson"),
    ("nobody tells you", "hard_truth"),
)


def _turning_points_v2(
    segments: list[dict[str, Any]], emotion_turns: list[Any]
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for seg in segments:
        text = H.seg_text(seg)
        low = text.lower()
        for cue, turn_type in TURNING_POINT_CUES:
            if cue in low:
                points.append(
                    {
                        "time": H.seg_start(seg),
                        "text": H.excerpt(text, 180),
                        "type": turn_type,
                        "before_state": "state before this line",
                        "after_state": "state implied by this line",
                        "confidence": 0.68,
                        "story_importance": 0.74,
                        "evidence": cue,
                    }
                )
                break
    for turn in emotion_turns:
        if isinstance(turn, dict):
            points.append(
                {
                    "time": float(turn.get("timestamp") or 0.0),
                    "text": str(turn.get("evidence") or ""),
                    "type": "emotional_shift",
                    "before_state": str(turn.get("previous_emotion") or "unknown"),
                    "after_state": str(turn.get("new_emotion") or "unknown"),
                    "confidence": float(turn.get("confidence") or 0.35),
                    "story_importance": 0.55,
                    "evidence": "emotional turning point",
                }
            )
    points.sort(key=lambda item: item["time"])
    return points[:60]


def _payoff_points_v2(
    segments: list[dict[str, Any]], relationships: list[Any]
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        points.append(
            {
                "payoff_present": True,
                "payoff_type": str(rel.get("type") or "payoff"),
                "payoff_start": float(rel.get("payoff_timestamp") or 0.0),
                "payoff_end": float(rel.get("payoff_timestamp") or 0.0) + 4.0,
                "payoff_text": str(rel.get("payoff_excerpt") or ""),
                "payoff_strength": round(H.clamp01(float(rel.get("confidence") or 0.5) + 0.2), 3),
                "emotional_release": False,
                "informational_reward": True,
                "ending_candidate": True,
                "confidence": float(rel.get("confidence") or 0.5),
            }
        )
    existing_times = {round(point["payoff_start"], 1) for point in points}
    for seg in segments:
        text = H.seg_text(seg)
        cues = H.find_phrases(text, H.PAYOFF_CUES)
        if cues and round(H.seg_start(seg), 1) not in existing_times:
            points.append(
                {
                    "payoff_present": True,
                    "payoff_type": "lesson_or_reveal",
                    "payoff_start": H.seg_start(seg),
                    "payoff_end": H.seg_end(seg),
                    "payoff_text": H.excerpt(text, 180),
                    "payoff_strength": 0.64,
                    "emotional_release": H.sentiment(text).label in {"positive", "calm"},
                    "informational_reward": True,
                    "ending_candidate": True,
                    "confidence": 0.56,
                }
            )
    points.sort(key=lambda point: point["payoff_start"])
    return points[:80]


def _emotional_timeline_v2(
    sections: list[dict[str, Any]], turning_points: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    timeline = [
        {
            "start": section["start"],
            "end": section["end"],
            "emotion": section["emotional_tone"],
            "intensity": round(H.clamp01(section["story_potential"]), 3),
            "evidence": section["summary"],
        }
        for section in sections
    ]
    for point in turning_points:
        timeline.append(
            {
                "start": point["time"],
                "end": point["time"],
                "emotion": str(point.get("after_state") or point.get("type")),
                "intensity": point["story_importance"],
                "evidence": point["text"],
            }
        )
    timeline.sort(key=lambda item: item["start"])
    return timeline[:100]


def _micro_story_windows(
    sections: list[dict[str, Any]],
    turning_points: list[dict[str, Any]],
    payoff_points: list[dict[str, Any]],
    duration: float,
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for section in sections:
        windows.append(
            {
                "source_type": "topic_section",
                "start": float(section["start"]),
                "end": float(section["end"]),
                "source_id": section["section_id"],
            }
        )
    for point in turning_points:
        start = max(0.0, float(point["time"]) - 30.0)
        windows.append(
            {
                "source_type": "turning_point",
                "start": start,
                "end": min(duration, start + 60.0),
                "source_id": f"turn_{round(float(point['time']) * 1000)}",
            }
        )
    for point in payoff_points:
        payoff_time = float(point["payoff_start"])
        windows.append(
            {
                "source_type": "payoff_point",
                "start": max(0.0, payoff_time - 55.0),
                "end": min(duration, payoff_time + 6.0),
                "source_id": f"payoff_{round(payoff_time * 1000)}",
            }
        )
    if not windows and duration > 0:
        bucket = 60.0 if duration > 180 else min(75.0, duration)
        current = 0.0
        while current < duration:
            windows.append(
                {
                    "source_type": "coverage_fallback",
                    "start": current,
                    "end": min(duration, current + bucket),
                    "source_id": f"fallback_{round(current)}",
                }
            )
            current += bucket
    return windows[:120]


def _build_micro_story_v2(
    index: int,
    window: dict[str, Any],
    segments: list[dict[str, Any]],
    payoff_relationships: list[Any],
    turning_points: list[dict[str, Any]],
    context_refs: list[Any],
    filler_sections: list[dict[str, Any]],
    source_duration: float,
) -> dict[str, Any]:
    start = float(window["start"])
    end = min(source_duration, float(window["end"]))
    if end - start > 75.0:
        end = start + 75.0
    segs = _segments_between(segments, start, end)
    if not segs:
        segs = [min(segments, key=lambda seg: abs(H.seg_start(seg) - start))]
        start, end = H.seg_start(segs[0]), H.seg_end(segs[-1])
    text = _span_text(segs)
    setup = _setup_analysis(start, end, segments, segs)
    tension = _tension_analysis(segs)
    turn = _turning_point_for_span(start, end, turning_points)
    payoff = _payoff_analysis(start, end, segs, payoff_relationships)
    ending = _ending_quality(segs, payoff)
    context = _context_dependency(start, end, segs, context_refs)
    emotional = _emotional_arc(segs, turning_points)
    shape = _story_shape_analysis(segs, setup, tension, turn, payoff, ending)
    filler_ratio = _span_filler_risk(start, end, text, filler_sections)
    completeness = _story_completeness(
        setup,
        tension,
        turn,
        payoff,
        ending,
        context,
        emotional,
        filler_ratio,
    )
    repair = _boundary_repair(start, end, segments, setup, payoff, ending, filler_sections)
    rejection = _rejection_reason(completeness, payoff, context, ending, filler_ratio)
    recommended = rejection is None and completeness["overall"] >= 0.55
    title_words = H.keywords(text, 5)
    story_id = f"story_{index}_{round(start * 1000)}_{round(end * 1000)}"
    return {
        "story_id": story_id,
        "candidate_id": story_id,
        "source_type": window.get("source_type"),
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 3),
        "title": " ".join(title_words).title() or "Micro Story",
        "one_sentence_summary": H.excerpt(text, 180),
        "summary": H.excerpt(text, 180),
        "viewer_promise": tension["viewer_question"],
        "setup": setup,
        "hook": _hook_for_micro_story(segs),
        "context": context,
        "conflict_or_question": tension["unresolved_question"],
        "tension": tension,
        "tension_beats": tension["evidence"],
        "turning_point": turn,
        "payoff": payoff,
        "ending": ending,
        "lesson_or_takeaway": payoff["payoff_text"] or ending["final_line"],
        "emotional_arc": emotional,
        "story_shape": shape["shape"],
        "story_shape_analysis": shape,
        "standalone_score": completeness["standalone"],
        "completeness_score": completeness["overall"],
        "payoff_score": completeness["payoff"],
        "context_dependency_score": context["score"],
        "clarity_score": completeness["standalone"],
        "recommended_start": repair["repaired_start"],
        "recommended_end": repair["repaired_end"],
        "boundary_reasoning": repair["reason"],
        "missing_context_risk": setup["missing_context_risk"],
        "cutoff_risk": ending["cutoff_risk"],
        "filler_risk": round(filler_ratio, 3),
        "story_completeness_score": completeness,
        "setup_analysis": setup,
        "tension_analysis": tension,
        "payoff_analysis": payoff,
        "ending_quality": ending,
        "context_dependency": context,
        "boundary_repair": repair,
        "scores": {
            "completeness": completeness["overall"],
            "standalone": completeness["standalone"],
            "payoff": completeness["payoff"],
            "context_independence": completeness["context_independence"],
            "filler_risk": round(filler_ratio, 3),
        },
        "risks": _micro_story_risks(setup, payoff, context, ending, filler_ratio),
        "recommended_for_planning": recommended,
        "rejection_reason": rejection,
        "downstream_guidance": _downstream_guidance(story_id, setup, tension, turn, payoff, ending),
    }


def _setup_analysis(
    start: float,
    end: float,
    all_segments: list[dict[str, Any]],
    segs: list[dict[str, Any]],
) -> dict[str, Any]:
    first = segs[0]
    text = H.seg_text(first)
    low = text.lower().strip()
    missing = (
        low.startswith(("so ", "and ", "then ", "but ", "because "))
        or _pronoun_risk(text) > 0.35
    )
    previous = [seg for seg in all_segments if H.seg_end(seg) <= start]
    recommended_start = start
    required_context: list[str] = []
    if missing and previous:
        recommended_start = max(0.0, H.seg_start(previous[-1]))
        required_context.append(H.excerpt(H.seg_text(previous[-1]), 120))
    context_caption = ""
    if missing and not previous:
        context_caption = _context_caption_from_text(_span_text(segs))
    return {
        "setup_present": not missing,
        "setup_start": H.seg_start(first),
        "setup_end": H.seg_end(first),
        "setup_text": H.excerpt(text, 180),
        "required_context": required_context,
        "missing_context_risk": round(0.68 if missing else 0.18, 3),
        "context_can_be_implied": bool(context_caption or required_context),
        "suggested_context_caption": context_caption,
        "recommended_start": round(recommended_start, 3),
        "evidence": H.excerpt(_span_text(_segments_between(all_segments, start, end)), 220),
    }


def _tension_analysis(segs: list[dict[str, Any]]) -> dict[str, Any]:
    text = _span_text(segs)
    low = text.lower()
    cues = H.find_cues(text)
    tension_type = "none"
    if H.is_question(text):
        tension_type = "unresolved_question"
    elif "conflict" in cues:
        tension_type = "conflict"
    elif "problem" in cues:
        tension_type = "problem"
    elif any(cue in low for cue in ("risk", "challenge", "wrong", "mistake", "truth")):
        tension_type = "curiosity_gap"
    evidence = (cues.get("conflict") or cues.get("problem") or H.shock_terms(text))[:4]
    score = 0.72 if tension_type != "none" else 0.28
    peak = max(segs, key=lambda seg: _story_potential_for_text(H.seg_text(seg), 0.4))
    question = _viewer_question(tension_type, text)
    return {
        "tension_type": tension_type,
        "tension_start": H.seg_start(peak) if tension_type != "none" else None,
        "tension_peak": H.seg_start(peak) if tension_type != "none" else None,
        "unresolved_question": question,
        "open_loop_strength": round(score, 3),
        "viewer_question": question,
        "retention_reason": "viewer wants the resolution" if score >= 0.5 else "weak open loop",
        "tension_score": round(score, 3),
        "evidence": evidence or [H.excerpt(text, 120)],
    }


def _viewer_question(tension_type: str, text: str) -> str:
    if tension_type == "unresolved_question":
        return H.excerpt(text.split("?")[0] + "?", 120) if "?" in text else "What is the answer?"
    if tension_type == "problem":
        return "How does this problem get solved?"
    if tension_type == "conflict":
        return "How does this conflict resolve?"
    if tension_type == "curiosity_gap":
        return "What is the truth or consequence?"
    return "Why should the viewer keep watching?"


def _turning_point_for_span(
    start: float, end: float, turning_points: list[dict[str, Any]]
) -> dict[str, Any]:
    inside = [point for point in turning_points if start <= float(point["time"]) < end]
    if not inside:
        return {
            "time": None,
            "text": "",
            "type": "none",
            "before_state": "",
            "after_state": "",
            "confidence": 0.0,
            "story_importance": 0.0,
        }
    best = max(inside, key=lambda point: float(point.get("story_importance") or 0.0))
    return best


def _payoff_analysis(
    start: float,
    end: float,
    segs: list[dict[str, Any]],
    payoff_relationships: list[Any],
) -> dict[str, Any]:
    relationships = [
        rel
        for rel in payoff_relationships
        if isinstance(rel, dict) and start <= float(rel.get("payoff_timestamp") or -1.0) < end
    ]
    if relationships:
        rel = max(relationships, key=lambda item: float(item.get("confidence") or 0.0))
        payoff_time = float(rel.get("payoff_timestamp") or end)
        return {
            "payoff_present": True,
            "payoff_type": str(rel.get("type") or "payoff"),
            "payoff_start": payoff_time,
            "payoff_end": min(end, payoff_time + 4.0),
            "payoff_text": str(rel.get("payoff_excerpt") or ""),
            "payoff_strength": round(H.clamp01(float(rel.get("confidence") or 0.5) + 0.22), 3),
            "emotional_release": False,
            "informational_reward": True,
            "ending_candidate": True,
            "confidence": float(rel.get("confidence") or 0.5),
        }
    for seg in reversed(segs):
        cues = H.find_phrases(H.seg_text(seg), H.PAYOFF_CUES)
        if cues:
            return {
                "payoff_present": True,
                "payoff_type": "lesson_or_reveal",
                "payoff_start": H.seg_start(seg),
                "payoff_end": H.seg_end(seg),
                "payoff_text": H.excerpt(H.seg_text(seg), 180),
                "payoff_strength": 0.62,
                "emotional_release": H.sentiment(H.seg_text(seg)).label in {"positive", "calm"},
                "informational_reward": True,
                "ending_candidate": True,
                "confidence": 0.52,
            }
    return {
        "payoff_present": False,
        "payoff_type": "missing",
        "payoff_start": None,
        "payoff_end": None,
        "payoff_text": "",
        "payoff_strength": 0.16,
        "emotional_release": False,
        "informational_reward": False,
        "ending_candidate": False,
        "confidence": 0.45,
    }


def _ending_quality(segs: list[dict[str, Any]], payoff: dict[str, Any]) -> dict[str, Any]:
    final_line = H.seg_text(segs[-1])
    low = final_line.lower().strip()
    complete_sentence = bool(final_line.strip().endswith((".", "!", "?"))) or len(
        final_line.split()
    ) >= 5
    filler_after = H.filler_ratio(final_line) >= 0.18 or low in {"and yeah", "yeah", "okay"}
    payoff_preserved = bool(payoff["payoff_present"]) and (
        payoff["payoff_start"] is None or float(payoff["payoff_start"]) <= H.seg_end(segs[-1])
    )
    cutoff_risk = 0.72 if low.endswith(("and", "but", "so", ",")) else 0.18
    strength = H.clamp01(
        0.25
        + 0.25 * float(complete_sentence)
        + 0.3 * float(payoff_preserved)
        - 0.25 * float(filler_after)
        - 0.2 * float(cutoff_risk > 0.5)
    )
    ending_type = (
        "lesson_lands"
        if payoff_preserved
        else "clean_sentence_end"
        if complete_sentence and not filler_after
        else "weak_or_incomplete"
    )
    return {
        "recommended_end": H.seg_end(segs[-1]),
        "ending_type": ending_type,
        "final_line": H.excerpt(final_line, 180),
        "final_line_strength": round(strength, 3),
        "complete_sentence": complete_sentence,
        "payoff_preserved": payoff_preserved,
        "filler_after_payoff": filler_after,
        "cutoff_risk": round(cutoff_risk, 3),
        "end_reason": "payoff preserved" if payoff_preserved else "final transcript line evaluated",
        "tail_padding_recommendation": 0.25 if payoff_preserved else 0.15,
    }


def _context_dependency(
    start: float,
    end: float,
    segs: list[dict[str, Any]],
    references: list[Any],
) -> dict[str, Any]:
    first_text = H.seg_text(segs[0])
    pronoun = _pronoun_risk(first_text)
    refs = [
        ref
        for ref in references
        if isinstance(ref, dict) and start <= float(ref.get("from_timestamp") or -1.0) < end
    ]
    previous_needed = bool(
        first_text.lower().strip().startswith(("so ", "and ", "then "))
    ) or bool(refs)
    score = H.clamp01(0.45 * pronoun + 0.35 * float(previous_needed) + 0.1 * len(refs))
    caption = _context_caption_from_text(_span_text(segs)) if score >= 0.45 else ""
    action = "accept"
    if score >= 0.72:
        action = "expand_start"
    elif score >= 0.45:
        action = "add_context_caption"
    return {
        "score": round(score, 3),
        "missing_references": [
            str(ref.get("term") or ref.get("from_excerpt") or "") for ref in refs[:4]
        ],
        "pronoun_risk": round(pronoun, 3),
        "previous_context_needed": previous_needed,
        "can_be_fixed_with_caption": bool(caption),
        "suggested_context_caption": caption,
        "recommended_action": action,
    }


def _pronoun_risk(text: str) -> float:
    pronouns = {"this", "that", "he", "she", "they", "it", "them", "those"}
    words = H.tokens(text)[:14]
    if not words:
        return 0.0
    hits = sum(1 for word in words if word in pronouns)
    return H.clamp01(hits / 4)


def _context_caption_from_text(text: str) -> str:
    keywords = H.keywords(text, 4)
    return f"Context: {' '.join(keywords).title()}" if keywords else ""


def _emotional_arc(
    segs: list[dict[str, Any]], turning_points: list[dict[str, Any]]
) -> dict[str, Any]:
    first = H.sentiment(H.seg_text(segs[0]))
    all_text = _span_text(segs)
    peak = H.sentiment(all_text)
    end = H.sentiment(H.seg_text(segs[-1]))
    turns = [
        point
        for point in turning_points
        if H.seg_start(segs[0]) <= float(point["time"]) < H.seg_end(segs[-1])
    ]
    shift = first.label != end.label or bool(turns)
    return {
        "start_emotion": first.label,
        "peak_emotion": peak.label,
        "end_emotion": end.label,
        "emotional_shift": shift,
        "emotional_intensity": round(max(first.arousal, peak.arousal, end.arousal), 3),
        "peak_time": turns[0]["time"] if turns else H.seg_start(segs[0]),
        "emotional_payoff": shift and end.label in {"positive", "calm"},
        "evidence": H.excerpt(all_text, 180),
    }


def _story_shape_analysis(
    segs: list[dict[str, Any]],
    setup: dict[str, Any],
    tension: dict[str, Any],
    turn: dict[str, Any],
    payoff: dict[str, Any],
    ending: dict[str, Any],
) -> dict[str, Any]:
    text = _span_text(segs).lower()
    shape = "setup_payoff"
    if "mistake" in text and any(cue in text for cue in ("lesson", "learned", "that's why")):
        shape = "mistake_lesson"
    elif H.is_question(_span_text(segs)) and payoff["payoff_present"]:
        shape = "question_answer"
    elif any(cue in text for cue in ("problem", "challenge")) and payoff["payoff_present"]:
        shape = "problem_solution"
    elif tension["tension_type"] != "none" and ending["payoff_preserved"]:
        shape = "tension_release"
    elif any(cue in text for cue in ("before", "after", "changed")):
        shape = "before_after"
    elif any(cue in text for cue in ("wrong", "truth", "actually")):
        shape = "belief_contradiction"
    confidence = H.clamp01(
        0.25
        + 0.2 * float(setup["setup_present"])
        + 0.2 * float(tension["tension_score"] >= 0.5)
        + 0.15 * float(turn["confidence"] > 0)
        + 0.2 * float(payoff["payoff_present"])
    )
    return {
        "shape": shape,
        "confidence": round(confidence, 3),
        "setup_span": {"start": setup["setup_start"], "end": setup["setup_end"]},
        "tension_span": {
            "start": tension["tension_start"],
            "end": tension["tension_peak"],
        },
        "turn_span": {"start": turn["time"], "end": turn["time"]},
        "payoff_span": {"start": payoff["payoff_start"], "end": payoff["payoff_end"]},
        "ending_span": {"start": ending["recommended_end"], "end": ending["recommended_end"]},
        "evidence_lines": [setup["setup_text"], payoff["payoff_text"] or ending["final_line"]],
        "weak_points": _shape_weak_points(setup, tension, payoff, ending),
    }


def _shape_weak_points(
    setup: dict[str, Any],
    tension: dict[str, Any],
    payoff: dict[str, Any],
    ending: dict[str, Any],
) -> list[str]:
    weak: list[str] = []
    if not setup["setup_present"]:
        weak.append("missing setup")
    if tension["tension_score"] < 0.45:
        weak.append("weak tension")
    if not payoff["payoff_present"]:
        weak.append("missing payoff")
    if ending["cutoff_risk"] > 0.5:
        weak.append("cutoff risk")
    return weak


def _span_filler_risk(
    start: float,
    end: float,
    text: str,
    filler_sections: list[dict[str, Any]],
) -> float:
    overlap = sum(
        max(0.0, min(float(section["end"]), end) - max(float(section["start"]), start))
        for section in filler_sections
    )
    duration = max(1.0, end - start)
    return H.clamp01(0.5 * H.filler_ratio(text) + 0.5 * (overlap / duration))


def _story_completeness(
    setup: dict[str, Any],
    tension: dict[str, Any],
    turn: dict[str, Any],
    payoff: dict[str, Any],
    ending: dict[str, Any],
    context: dict[str, Any],
    emotional: dict[str, Any],
    filler_ratio: float,
) -> dict[str, Any]:
    setup_score = 1.0 - float(setup["missing_context_risk"])
    hook_score = max(0.35, float(tension["open_loop_strength"]))
    tension_score = float(tension["tension_score"])
    turn_score = float(turn["story_importance"])
    payoff_score = float(payoff["payoff_strength"])
    ending_score = float(ending["final_line_strength"])
    standalone = H.clamp01(1.0 - float(context["score"]))
    emotional_score = 0.7 if emotional["emotional_shift"] else 0.35
    sentence_score = 1.0 if ending["complete_sentence"] else 0.35
    progression = H.clamp01((setup_score + tension_score + payoff_score) / 3)
    overall = H.clamp01(
        0.12 * setup_score
        + 0.1 * hook_score
        + 0.12 * tension_score
        + 0.08 * progression
        + 0.08 * turn_score
        + 0.18 * payoff_score
        + 0.12 * ending_score
        + 0.1 * standalone
        + 0.05 * emotional_score
        + 0.03 * (1.0 - filler_ratio)
        + 0.02 * sentence_score
    )
    if not payoff["payoff_present"]:
        overall = min(overall, 0.54)
    if context["score"] >= 0.7:
        overall = min(overall, 0.48)
    return {
        "overall": round(overall, 3),
        "setup": round(setup_score, 3),
        "hook": round(hook_score, 3),
        "tension": round(tension_score, 3),
        "progression": round(progression, 3),
        "turn": round(turn_score, 3),
        "payoff": round(payoff_score, 3),
        "ending": round(ending_score, 3),
        "standalone": round(standalone, 3),
        "context_independence": round(standalone, 3),
        "emotional_arc": round(emotional_score, 3),
        "filler_ratio": round(filler_ratio, 3),
        "sentence_completeness": round(sentence_score, 3),
        "explanation": (
            "complete micro-story"
            if overall >= 0.65
            else "usable but needs care"
            if overall >= 0.5
            else "weak or incomplete story fragment"
        ),
    }


def _boundary_repair(
    start: float,
    end: float,
    segments: list[dict[str, Any]],
    setup: dict[str, Any],
    payoff: dict[str, Any],
    ending: dict[str, Any],
    filler_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    repaired_start = start
    repaired_end = end
    changes: list[str] = []
    if not setup["setup_present"] and setup["recommended_start"] < start:
        repaired_start = float(setup["recommended_start"])
        changes.append("expanded_start_for_setup")
    if payoff["payoff_present"] and payoff["payoff_end"] and float(payoff["payoff_end"]) > end:
        repaired_end = float(payoff["payoff_end"])
        changes.append("expanded_end_for_payoff")
    if ending["filler_after_payoff"] and payoff["payoff_end"]:
        repaired_end = min(repaired_end, float(payoff["payoff_end"]) + 0.25)
        changes.append("trimmed_filler_after_payoff")
    for filler in filler_sections:
        if abs(float(filler["start"]) - repaired_start) <= 0.2 and float(filler["end"]) < end:
            repaired_start = float(filler["end"])
            changes.append("trimmed_filler_start")
            break
    risk = "low" if not changes else "medium"
    return {
        "original_start": round(start, 3),
        "original_end": round(end, 3),
        "repaired_start": round(repaired_start, 3),
        "repaired_end": round(repaired_end, 3),
        "changes": changes,
        "reason": "; ".join(changes) if changes else "candidate boundaries already preserve story",
        "setup_added": "expanded_start_for_setup" in changes,
        "filler_removed": any("filler" in change for change in changes),
        "payoff_added": "expanded_end_for_payoff" in changes,
        "context_caption_suggested": setup["suggested_context_caption"],
        "risk_after_repair": risk,
    }


def _hook_for_micro_story(segs: list[dict[str, Any]]) -> dict[str, Any]:
    text = H.seg_text(segs[0])
    cues = H.find_cues(text)
    return {
        "text": H.excerpt(text, 160),
        "hook_type": (
            "question" if H.is_question(text) else "curiosity" if cues.get("hook") else "context"
        ),
        "strength": 0.72 if H.is_question(text) or cues.get("hook") else 0.38,
    }


def _rejection_reason(
    completeness: dict[str, Any],
    payoff: dict[str, Any],
    context: dict[str, Any],
    ending: dict[str, Any],
    filler_ratio: float,
) -> str | None:
    if not payoff["payoff_present"]:
        return "missing payoff"
    if context["score"] >= 0.72:
        return "too dependent on unseen context"
    if ending["cutoff_risk"] >= 0.7:
        return "cutoff risk at ending"
    if filler_ratio >= 0.45:
        return "filler-heavy story"
    if completeness["overall"] < 0.45:
        return "low story completeness"
    return None


def _micro_story_risks(
    setup: dict[str, Any],
    payoff: dict[str, Any],
    context: dict[str, Any],
    ending: dict[str, Any],
    filler_ratio: float,
) -> list[str]:
    risks: list[str] = []
    if setup["missing_context_risk"] >= 0.5:
        risks.append("missing setup")
    if not payoff["payoff_present"]:
        risks.append("missing payoff")
    if context["score"] >= 0.45:
        risks.append("context dependency")
    if ending["cutoff_risk"] >= 0.5:
        risks.append("cutoff risk")
    if filler_ratio >= 0.3:
        risks.append("filler risk")
    return risks


def _downstream_guidance(
    story_id: str,
    setup: dict[str, Any],
    tension: dict[str, Any],
    turn: dict[str, Any],
    payoff: dict[str, Any],
    ending: dict[str, Any],
) -> dict[str, Any]:
    key_words = H.keywords(" ".join([setup["setup_text"], payoff["payoff_text"]]), 4)
    return {
        "virality": {
            "story_id": story_id,
            "hook_context": setup["setup_text"],
            "strongest_tension": tension["unresolved_question"],
            "payoff_line": payoff["payoff_text"],
            "recommended_hook_angle": tension["viewer_question"],
            "reasons_to_select": ["clear payoff"] if payoff["payoff_present"] else [],
            "reasons_to_reject": ["missing payoff"] if not payoff["payoff_present"] else [],
        },
        "planning": {
            "story_id": story_id,
            "recommended_start": setup["recommended_start"],
            "recommended_end": ending["recommended_end"],
            "must_include_spans": [
                {"kind": "setup", "start": setup["setup_start"], "end": setup["setup_end"]},
                {
                    "kind": "payoff",
                    "start": payoff["payoff_start"],
                    "end": payoff["payoff_end"],
                },
            ],
            "context_caption": setup["suggested_context_caption"],
            "tail_padding": ending["tail_padding_recommendation"],
            "boundary_confidence": ending["final_line_strength"],
        },
        "editing": {
            "story_id": story_id,
            "tension_beats": tension["evidence"],
            "turn_beats": [turn] if turn["time"] is not None else [],
            "payoff_beats": [payoff] if payoff["payoff_present"] else [],
            "caption_emphasis_words": key_words,
            "music_mood": _music_mood_from_tension(tension),
            "pacing_recommendation": (
                "tight and forward" if tension["tension_score"] >= 0.5 else "clean"
            ),
            "hook_visual_treatment": "caption-pop on viewer question",
            "ending_hold_recommendation": ending["tail_padding_recommendation"],
        },
    }


def _music_mood_from_tension(tension: dict[str, Any]) -> str:
    return "subtle tension" if tension["tension_score"] >= 0.5 else "neutral bed"


def _dedupe_micro_stories(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for story in sorted(stories, key=lambda item: item["completeness_score"], reverse=True):
        if any(
            _temporal_iou(story["start"], story["end"], other["start"], other["end"]) >= 0.72
            for other in kept
        ):
            continue
        kept.append(story)
    return sorted(kept, key=lambda item: item["start"])


def _temporal_iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = (a_end - a_start) + (b_end - b_start) - overlap
    return overlap / union if union > 0 else 0.0


def _weak_sections_v2(
    sections: list[dict[str, Any]],
    micro_stories: list[dict[str, Any]],
    filler_sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    weak: list[dict[str, Any]] = []
    for section in sections:
        stories = [
            story
            for story in micro_stories
            if _temporal_iou(section["start"], section["end"], story["start"], story["end"]) > 0.2
        ]
        best = max((story["completeness_score"] for story in stories), default=0.0)
        if best < 0.45 or section["story_potential"] < 0.3:
            weak.append(
                {
                    "start": section["start"],
                    "end": section["end"],
                    "type": "weak_story_section",
                    "story_potential": section["story_potential"],
                    "best_completeness": round(best, 3),
                    "reason": "low story potential or no complete micro-story found",
                }
            )
    for filler in filler_sections:
        weak.append(
            {
                "start": filler["start"],
                "end": filler["end"],
                "type": "filler_section",
                "story_potential": 0.1,
                "best_completeness": 0.0,
                "reason": filler["reason"],
            }
        )
    return weak[:80]


def _story_quality_summary(micro_stories: list[dict[str, Any]]) -> dict[str, Any]:
    if not micro_stories:
        return {
            "micro_story_count": 0,
            "recommended_count": 0,
            "average_completeness": 0.0,
            "strongest_story_id": None,
            "warnings": ["no micro-stories were generated"],
        }
    recommended = [story for story in micro_stories if story["recommended_for_planning"]]
    average = sum(float(story["completeness_score"]) for story in micro_stories) / len(
        micro_stories
    )
    strongest = max(micro_stories, key=lambda story: story["completeness_score"])
    return {
        "micro_story_count": len(micro_stories),
        "recommended_count": len(recommended),
        "average_completeness": round(average, 3),
        "strongest_story_id": strongest["story_id"],
        "strongest_score": strongest["completeness_score"],
        "warnings": [
            "few recommended stories; source may be low density"
            if len(recommended) < max(1, len(micro_stories) // 4)
            else ""
        ],
    }


def _long_video_story_map(
    duration: float,
    sections: list[dict[str, Any]],
    micro_stories: list[dict[str, Any]],
    filler_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    bins = max(1, min(12, int(duration // 300) or 1))
    coverage: list[dict[str, Any]] = []
    for bucket in range(bins):
        start = duration * bucket / bins
        end = duration * (bucket + 1) / bins
        stories = [story for story in micro_stories if start <= story["start"] < end]
        coverage.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "candidate_count": len(stories),
                "best_score": max((story["completeness_score"] for story in stories), default=0.0),
            }
        )
    high = [section for section in sections if section["story_potential"] >= 0.5]
    low = [section for section in sections if section["story_potential"] < 0.25]
    return {
        "source_duration": round(duration, 3),
        "section_count": len(sections),
        "sections": [
            {
                "section_id": section["section_id"],
                "start": section["start"],
                "end": section["end"],
                "title": section["title"],
                "story_potential": section["story_potential"],
            }
            for section in sections
        ],
        "strongest_arcs": [
            {
                "story_id": story["story_id"],
                "start": story["start"],
                "end": story["end"],
                "score": story["completeness_score"],
            }
            for story in sorted(
                micro_stories,
                key=lambda item: item["completeness_score"],
                reverse=True,
            )[:10]
        ],
        "coverage_by_time": coverage,
        "coverage_by_topic": [
            {"topic": section["title"], "story_potential": section["story_potential"]}
            for section in sections
        ],
        "low_story_density_sections": [section["section_id"] for section in low],
        "high_story_density_sections": [section["section_id"] for section in high],
        "recommended_clip_distribution": [
            item for item in coverage if item["candidate_count"] > 0
        ],
        "filler_section_count": len(filler_sections),
    }


def _low_story_count_reason(
    duration: float,
    transcript_coverage: dict[str, Any],
    sections: list[dict[str, Any]],
    micro_stories: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if duration < 1800:
        return None
    recommended = [story for story in micro_stories if story["recommended_for_planning"]]
    if len(recommended) >= max(3, len(sections) // 3):
        return None
    reasons = []
    if transcript_coverage["coverage_ratio"] < 0.6:
        reasons.append("low transcript coverage")
    if not recommended:
        reasons.append("no complete setup-to-payoff micro-stories passed quality checks")
    if len(sections) < 4:
        reasons.append("few distinct topic sections detected")
    return {
        "source_duration": round(duration, 3),
        "transcript_density": transcript_coverage["coverage_ratio"],
        "sections_analyzed": len(sections),
        "candidate_count": len(recommended),
        "reasons": reasons or ["story density was low after completeness filtering"],
        "confidence": 0.62,
    }


def _virality_story_guidance(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "story_id": story["story_id"],
            "hook_context": story["setup"]["setup_text"],
            "strongest_tension": story["tension"]["unresolved_question"],
            "payoff_line": story["payoff"]["payoff_text"],
            "story_shape": story["story_shape"],
            "story_completeness_score": story["completeness_score"],
            "emotional_arc": story["emotional_arc"],
            "standalone_score": story["standalone_score"],
            "context_risk": story["context_dependency_score"],
            "recommended_hook_angle": story["tension"]["viewer_question"],
            "recommended_viral_angle": story["viewer_promise"],
            "reasons_to_select": story["downstream_guidance"]["virality"]["reasons_to_select"],
            "reasons_to_reject": story["downstream_guidance"]["virality"]["reasons_to_reject"],
        }
        for story in stories
    ]


def _planning_story_guidance(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [story["downstream_guidance"]["planning"] for story in stories]


def _editing_story_guidance(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [story["downstream_guidance"]["editing"] for story in stories]


def _story_v2_warnings(
    transcript_coverage: dict[str, Any],
    micro_stories: list[dict[str, Any]],
    low_count_reason: dict[str, Any] | None,
) -> list[str]:
    warnings: list[str] = []
    if transcript_coverage["coverage_ratio"] < 0.8:
        warnings.append("transcript coverage is partial; story map may miss silent/visual context")
    if not any(story["recommended_for_planning"] for story in micro_stories):
        warnings.append("no recommended micro-stories passed completeness and payoff checks")
    if low_count_reason is not None:
        warnings.append("long video has fewer story candidates than expected")
    return warnings

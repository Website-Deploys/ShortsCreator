"""The fifteen Virality Engine stages.

Each analyzer is an isolated, replaceable module behind the
:class:`ViralityAnalyzer` contract. None imports another; they communicate only
through the structured :class:`ViralityStageContext`. Each consumes the Cognitive
and Story engines' outputs and produces an evidence-backed score with explicit
confidence and limitations.

Honesty rules (enforced by construction):
- When the required evidence is missing, a stage returns ``UNAVAILABLE`` with a
  detailed reason. It never estimates a missing score or invents confidence.
- Every score in ``data`` carries a ``confidence``, an ``evidence`` list, and a
  ``limitations`` string. Confidence reflects how much real evidence was used and
  is kept modest because these are transparent heuristics over upstream signals.
- The aggregating summary always completes, but honestly reports which category
  scores were available vs. pending (and why).
"""

from __future__ import annotations

from typing import Any, ClassVar

from olympus.domain.contracts.virality import (
    ViralityAnalyzer,
    ViralityOutcome,
    ViralityProgressReporter,
    ViralityStageContext,
)
from olympus.virality import scoring as S  # noqa: N812 (module alias is intentional)


# --------------------------------------------------------------------------- #
# Small local helpers (pure)
# --------------------------------------------------------------------------- #
def _seg_text(seg: dict[str, Any]) -> str:
    return str(seg.get("text") or "")


def _seg_start(seg: dict[str, Any]) -> float:
    return S.as_float(seg.get("start"))


def _seg_end(seg: dict[str, Any]) -> float:
    end = seg.get("end")
    return S.as_float(end) if end is not None else _seg_start(seg)


def _emotion_transition(turn: dict[str, Any]) -> str:
    return f"{S.as_str(turn.get('previous_emotion'))} -> {S.as_str(turn.get('new_emotion'))}"


def _duration_fit(duration: float, lo: float, hi: float, hard_max: float) -> float:
    """1.0 inside the ideal [lo, hi] window, decaying outside, 0 past hard_max."""

    if duration <= 0:
        return 0.0
    if lo <= duration <= hi:
        return 1.0
    if duration < lo:
        return S.clamp01(duration / lo)
    if duration <= hard_max:
        return S.clamp01(1.0 - (duration - hi) / (hard_max - hi))
    return 0.0


_NO_TRANSCRIPT = (
    "Requires a transcript from the Cognitive Engine, which is not available for "
    "this video (speech transcription produced no output in this environment). "
    "No score is estimated without it."
)


# --------------------------------------------------------------------------- #
# 1. Hook Strength - opening attention / stop-scroll potential.
# --------------------------------------------------------------------------- #
class HookStrengthAnalyzer(ViralityAnalyzer):
    name = "hook_strength"
    version = "1"
    _TYPE_WEIGHT: ClassVar[dict[str, float]] = {
        "question": 0.9,
        "curiosity": 0.85,
        "shock": 0.85,
        "bold_statement": 0.7,
        "emotion": 0.7,
        "story": 0.6,
    }

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        hook = ctx.story_data("hook_detection")
        if hook is None:
            return ViralityOutcome.unavailable(
                "Requires the Story Engine's hook detection, which is unavailable "
                "(no transcript), so opening attention cannot be assessed."
            )
        limitations = (
            "Hook strength is derived from transcript opening cues only; on-screen "
            "visual hooks and audio energy are not analyzed (no frame/audio models)."
        )
        if not hook.get("has_hook"):
            report(1.0)
            return ViralityOutcome.completed(
                {
                    "score": 0.2,
                    "confidence": S.round3(S.as_float(hook.get("confidence"), 0.5)),
                    "evidence": [{"type": "no_hook", "detail": S.as_str(hook.get("reason"))}],
                    "limitations": limitations,
                    "has_hook": False,
                }
            )
        htype = S.as_str(hook.get("hook_type"))
        hconf = S.as_float(hook.get("confidence"), 0.5)
        weight = self._TYPE_WEIGHT.get(htype, 0.6)
        score = S.clamp01(weight * (0.55 + 0.45 * hconf))
        window = hook.get("window") if isinstance(hook.get("window"), dict) else {}
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": S.round3(hconf),
                "hook_type": htype,
                "evidence": [
                    {
                        "type": "hook",
                        "hook_type": htype,
                        "timestamp": window.get("start"),
                        "excerpt": S.as_str(hook.get("supporting_excerpt")),
                        "detail": S.as_str(hook.get("why")),
                    }
                ],
                "limitations": limitations,
            }
        )


# --------------------------------------------------------------------------- #
# 2. Curiosity Gap - unanswered questions, suspense, delayed payoff.
# --------------------------------------------------------------------------- #
class CuriosityGapAnalyzer(ViralityAnalyzer):
    name = "curiosity_gap"
    version = "1"
    _DELAY_SECONDS = 10.0

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        segments = ctx.transcript_segments()
        if not segments:
            return ViralityOutcome.unavailable(_NO_TRANSCRIPT)

        questions = [s for s in segments if S.is_question(_seg_text(s))]
        payoff = ctx.story_data("payoff_detection") or {}
        relationships = S.as_list(payoff.get("relationships"))
        resolved = {round(S.as_float(r.get("setup_timestamp")), 1) for r in relationships}
        open_questions = [q for q in questions if round(_seg_start(q), 1) not in resolved]
        delayed = [
            r
            for r in relationships
            if S.as_float(r.get("payoff_timestamp")) - S.as_float(r.get("setup_timestamp"))
            >= self._DELAY_SECONDS
        ]
        hook = ctx.story_data("hook_detection") or {}
        hook_curiosity = (
            1.0 if S.as_str(hook.get("hook_type")) in ("question", "curiosity") else 0.0
        )

        score = S.clamp01(
            0.35 * min(1.0, len(questions) / 2)
            + 0.4 * min(1.0, len(delayed) / 2)
            + 0.25 * hook_curiosity
        )
        evidence: list[dict[str, Any]] = [
            {
                "type": "open_question",
                "timestamp": _seg_start(q),
                "excerpt": S.as_str(_seg_text(q))[:160],
            }
            for q in open_questions[:5]
        ]
        evidence += [
            {
                "type": "delayed_payoff",
                "timestamp": S.as_float(r.get("setup_timestamp")),
                "detail": f"answered at {S.as_float(r.get('payoff_timestamp'))}s",
            }
            for r in delayed[:5]
        ]
        confidence = 0.35 + (0.25 if relationships else 0.0)
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": S.round3(confidence),
                "open_question_count": len(open_questions),
                "delayed_payoff_count": len(delayed),
                "evidence": evidence,
                "limitations": (
                    "Curiosity is proxied by unanswered questions and delayed payoffs "
                    "in the transcript; viewer curiosity is not measured directly."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 3. Emotional Impact - surprise/joy/sadness/fear/excitement/tension/etc.
# --------------------------------------------------------------------------- #
class EmotionalImpactAnalyzer(ViralityAnalyzer):
    name = "emotional_impact"
    version = "1"

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        etp = ctx.story_data("emotional_turning_points")
        if etp is None:
            return ViralityOutcome.unavailable(
                "Requires the Story Engine's emotional turning points, which are "
                "unavailable (no transcript and no emotion model)."
            )
        method = S.as_str(etp.get("method"))
        limitations = (
            "Emotion is estimated from transcript sentiment lexicons; audio tone and "
            "facial expressions are not analyzed (no audio/vision emotion model)."
            if method == "estimated_from_transcript"
            else "Emotion taken from the Cognitive Engine's emotion timeline."
        )
        turns = S.as_list(etp.get("turning_points"))
        if not turns:
            report(1.0)
            return ViralityOutcome.completed(
                {
                    "score": 0.2,
                    "confidence": 0.4,
                    "emotion_shift_count": 0,
                    "evidence": [],
                    "limitations": limitations,
                }
            )
        confidences = [S.as_float(t.get("confidence")) for t in turns]
        avg_conf = S.mean(confidences)
        magnitude = S.clamp01(len(turns) / 4)
        score = S.clamp01(magnitude * (0.5 + 0.5 * avg_conf))
        evidence = [
            {
                "type": "emotional_shift",
                "timestamp": t.get("timestamp"),
                "detail": _emotion_transition(t),
                "confidence": S.round3(S.as_float(t.get("confidence"))),
            }
            for t in turns[:8]
        ]
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": S.round3(avg_conf),
                "emotion_shift_count": len(turns),
                "method": method,
                "evidence": evidence,
                "limitations": limitations,
            }
        )


# --------------------------------------------------------------------------- #
# 4. Conflict - disagreements, problems, challenges, obstacles.
# --------------------------------------------------------------------------- #
class ConflictAnalyzer(ViralityAnalyzer):
    name = "conflict"
    version = "1"

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        seg = ctx.story_data("narrative_segmentation")
        if seg is None:
            return ViralityOutcome.unavailable(
                "Requires the Story Engine's narrative segmentation (no transcript) "
                "to locate problems, conflicts, and obstacles."
            )
        sections = S.as_list(seg.get("sections"))
        conflict_secs = [s for s in sections if S.as_str(s.get("role")) in ("conflict", "problem")]
        duration = ctx.video_duration() or (sections[-1].get("end") if sections else 0) or 1
        covered = sum(S.as_float(s.get("end")) - S.as_float(s.get("start")) for s in conflict_secs)
        coverage = S.clamp01(covered / float(duration)) if duration else 0.0
        limitations = (
            "Conflict is inferred from narrative roles and discourse cues in the "
            "transcript; vocal tension and on-screen conflict are not analyzed."
        )
        if not conflict_secs:
            report(1.0)
            return ViralityOutcome.completed(
                {
                    "score": 0.15,
                    "confidence": 0.45,
                    "conflict_section_count": 0,
                    "evidence": [],
                    "limitations": limitations,
                }
            )
        score = S.clamp01(0.4 * min(1.0, len(conflict_secs) / 2) + 0.6 * coverage)
        confidence = S.mean([S.as_float(s.get("confidence")) for s in conflict_secs])
        evidence = [
            {
                "type": S.as_str(s.get("role")),
                "timestamp": S.as_float(s.get("start")),
                "excerpt": S.as_str(s.get("supporting_excerpt"))[:160],
            }
            for s in conflict_secs[:5]
        ]
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": S.round3(confidence),
                "conflict_section_count": len(conflict_secs),
                "evidence": evidence,
                "limitations": limitations,
            }
        )


# --------------------------------------------------------------------------- #
# 5. Novelty - unusual info, unexpected facts, uncommon perspectives.
# --------------------------------------------------------------------------- #
class NoveltyAnalyzer(ViralityAnalyzer):
    name = "novelty"
    version = "1"

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        density = ctx.story_data("information_density")
        if density is None:
            return ViralityOutcome.unavailable(
                "Requires the Story Engine's information density (no transcript) to "
                "estimate unusual/factual content."
            )
        windows = S.as_list(density.get("windows"))
        topic = ctx.story_data("topic_segmentation") or {}
        topic_count = S.as_float(topic.get("topic_count"), 1)
        avg_entity = S.mean([S.as_float(_metric(w, "entity_density")) for w in windows])
        avg_div = S.mean([S.as_float(_metric(w, "lexical_diversity")) for w in windows])
        topic_factor = S.clamp01((topic_count - 1) / 4)
        score = S.clamp01(0.4 * avg_entity + 0.4 * avg_div + 0.2 * topic_factor)
        top = sorted(windows, key=lambda w: S.as_float(_metric(w, "entity_density")), reverse=True)
        evidence = [
            {
                "type": "factual_dense_passage",
                "timestamp": S.as_float(w.get("start")),
                "detail": f"entity density {S.round3(S.as_float(_metric(w, 'entity_density')))}",
            }
            for w in top[:3]
        ]
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": 0.4,
                "topic_count": int(topic_count),
                "evidence": evidence,
                "limitations": (
                    "Novelty is proxied by factual/lexical density and topic variety; "
                    "it is not a world-knowledge novelty model and cannot judge whether "
                    "facts are genuinely new to an audience."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 6. Information Value - educational density, usefulness, lessons.
# --------------------------------------------------------------------------- #
class InformationValueAnalyzer(ViralityAnalyzer):
    name = "information_value"
    version = "1"

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        density = ctx.story_data("information_density")
        if density is None:
            return ViralityOutcome.unavailable(
                "Requires the Story Engine's information density (no transcript) to "
                "estimate educational value."
            )
        windows = S.as_list(density.get("windows"))
        dense_count = S.as_float(density.get("dense_window_count"))
        dense_ratio = S.clamp01(dense_count / len(windows)) if windows else 0.0
        avg_div = S.mean([S.as_float(_metric(w, "lexical_diversity")) for w in windows])
        summary = ctx.story_data("story_summary") or {}
        lessons = S.as_list(summary.get("key_lessons"))
        score = S.clamp01(0.55 * dense_ratio + 0.25 * min(1.0, len(lessons) / 2) + 0.2 * avg_div)
        evidence: list[dict[str, Any]] = [
            {"type": "lesson", "excerpt": S.as_str(lesson)[:160]} for lesson in lessons[:3]
        ]
        evidence.append({"type": "dense_windows", "detail": f"{int(dense_count)} dense passage(s)"})
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": 0.45,
                "dense_window_count": int(dense_count),
                "lesson_count": len(lessons),
                "evidence": evidence,
                "limitations": (
                    "Educational value is proxied by information density and detected "
                    "lessons; factual correctness and practical usefulness are not verified."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 7. Audience Relatability - first/second-person address as a transparent proxy.
# --------------------------------------------------------------------------- #
class AudienceRelatabilityAnalyzer(ViralityAnalyzer):
    name = "audience_relatability"
    version = "1"

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        segments = ctx.transcript_segments()
        if not segments:
            return ViralityOutcome.unavailable(_NO_TRANSCRIPT)
        full = " ".join(_seg_text(s) for s in segments)
        first_ratio, second_ratio = S.personal_address_ratio(full)
        score = S.clamp01((first_ratio + second_ratio) * 10)
        examples = [
            {"type": "personal_address", "timestamp": _seg_start(s), "excerpt": _seg_text(s)[:140]}
            for s in segments
            if any(p in S.tokens(_seg_text(s)) for p in ("you", "your", "we", "i"))
        ][:4]
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": 0.4,
                "first_person_ratio": S.round3(first_ratio),
                "second_person_ratio": S.round3(second_ratio),
                "evidence": examples,
                "limitations": (
                    "Relatability is proxied by first/second-person address only; it "
                    "does not model specific audience demographics or lived experience."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 8. Momentum - pacing, acceleration, slow moments.
# --------------------------------------------------------------------------- #
class MomentumAnalyzer(ViralityAnalyzer):
    name = "momentum"
    version = "1"

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        density = ctx.story_data("information_density")
        if density is None:
            return ViralityOutcome.unavailable(
                "Requires the Story Engine's information density (no transcript) to "
                "estimate pacing and momentum."
            )
        windows = S.as_list(density.get("windows"))
        slow = [w for w in windows if S.as_str(w.get("classification")) in ("slow", "filler")]
        slow_ratio = (len(slow) / len(windows)) if windows else 0.0
        avg_density = S.mean([S.as_float(w.get("density")) for w in windows])
        score = S.clamp01(0.6 * avg_density + 0.4 * (1 - slow_ratio))
        evidence = [
            {
                "type": "slow_moment",
                "timestamp": S.as_float(w.get("start")),
                "detail": S.as_str(w.get("reason")) or S.as_str(w.get("classification")),
            }
            for w in slow[:5]
        ]
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": 0.45,
                "slow_moment_count": len(slow),
                "evidence": evidence,
                "limitations": (
                    "Pacing is proxied by transcript information density per window; "
                    "visual cut rhythm and audio energy are not analyzed."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 9. Retention - where viewers may leave, and WHY.
# --------------------------------------------------------------------------- #
class RetentionAnalyzer(ViralityAnalyzer):
    name = "retention"
    version = "1"

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        density = ctx.story_data("information_density")
        if density is None:
            return ViralityOutcome.unavailable(
                "Requires the Story Engine's information density (no transcript) to "
                "predict where viewers may drop off."
            )
        windows = S.as_list(density.get("windows"))
        duration = ctx.video_duration() or (windows[-1].get("end") if windows else 0) or 1
        slow = [w for w in windows if S.as_str(w.get("classification")) in ("slow", "filler")]
        early_slow = any(S.as_float(w.get("start")) < 0.2 * float(duration) for w in slow)
        slow_ratio = (len(slow) / len(windows)) if windows else 0.0
        score = S.clamp01(1.0 - 0.6 * slow_ratio - (0.2 if early_slow else 0.0))
        drop_points = [
            {
                "type": "likely_drop_off",
                "timestamp": S.as_float(w.get("start")),
                "why": S.as_str(w.get("reason"))
                or f"low engagement passage ({w.get('classification')})",
            }
            for w in slow[:6]
        ]
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": 0.45,
                "early_drop_risk": early_slow,
                "drop_point_count": len(slow),
                "evidence": drop_points,
                "limitations": (
                    "Retention is predicted from transcript pacing only; real watch-time "
                    "retention curves and audience behaviour are not available."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 10. Replay Potential - satisfying payoffs, dense info, emotional peaks.
# --------------------------------------------------------------------------- #
class ReplayPotentialAnalyzer(ViralityAnalyzer):
    name = "replay_potential"
    version = "1"

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        payoff = ctx.story_data("payoff_detection")
        density = ctx.story_data("information_density")
        etp = ctx.story_data("emotional_turning_points")
        if payoff is None and density is None and etp is None:
            return ViralityOutcome.unavailable(
                "Requires payoff, information-density, or emotional signals from the "
                "Story Engine (no transcript), so replay potential cannot be assessed."
            )
        payoffs = S.as_list((payoff or {}).get("relationships"))
        dense = S.as_float((density or {}).get("dense_window_count"))
        emo = len(S.as_list((etp or {}).get("turning_points")))
        score = S.clamp01(
            0.4 * min(1.0, len(payoffs) / 2) + 0.4 * min(1.0, dense / 3) + 0.2 * min(1.0, emo / 3)
        )
        available = sum(x is not None for x in (payoff, density, etp))
        evidence = [
            {"type": "payoff", "detail": f"{len(payoffs)} satisfying payoff(s)"},
            {"type": "dense_info", "detail": f"{int(dense)} dense passage(s)"},
            {"type": "emotional_peaks", "detail": f"{emo} emotional shift(s)"},
        ]
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": S.round3(S.coverage_confidence(available, 3)),
                "evidence": evidence,
                "limitations": (
                    "Replay potential is inferred from payoffs, dense information, and "
                    "emotional peaks; no actual replay/loop metrics are available."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 11. Shareability - aggregate of emotion, novelty, information value.
# --------------------------------------------------------------------------- #
class ShareabilityAnalyzer(ViralityAnalyzer):
    name = "shareability"
    version = "1"
    depends_on = ("emotional_impact", "novelty", "information_value")
    _WEIGHTS: ClassVar[dict[str, float]] = {
        "emotional_impact": 0.4,
        "novelty": 0.35,
        "information_value": 0.25,
    }

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        pairs, evidence = _gather_dependencies(ctx, self._WEIGHTS)
        if not pairs:
            return ViralityOutcome.unavailable(
                "Requires emotional impact, novelty, or information value, none of "
                "which are available (no transcript)."
            )
        score = S.weighted_mean(pairs)
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": S.round3(S.coverage_confidence(len(pairs), len(self._WEIGHTS))),
                "evidence": evidence,
                "limitations": (
                    "Shareability is derived from emotional impact, novelty, and "
                    "information value; no real share-rate data is available."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 12. Comment Potential - aggregate of conflict and curiosity.
# --------------------------------------------------------------------------- #
class CommentPotentialAnalyzer(ViralityAnalyzer):
    name = "comment_potential"
    version = "1"
    depends_on = ("conflict", "curiosity_gap")
    _WEIGHTS: ClassVar[dict[str, float]] = {"conflict": 0.5, "curiosity_gap": 0.5}

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        pairs, evidence = _gather_dependencies(ctx, self._WEIGHTS)
        if not pairs:
            return ViralityOutcome.unavailable(
                "Requires conflict and/or curiosity signals, which are unavailable (no transcript)."
            )
        score = S.weighted_mean(pairs)
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": S.round3(S.coverage_confidence(len(pairs), len(self._WEIGHTS))),
                "evidence": evidence,
                "limitations": (
                    "Discussion potential is inferred from conflict and unanswered "
                    "questions; no actual comment-rate data is available."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 13. Platform Fit - YouTube Shorts / TikTok / Instagram Reels.
# --------------------------------------------------------------------------- #
class PlatformFitAnalyzer(ViralityAnalyzer):
    name = "platform_fit"
    version = "1"
    # (ideal_lo, ideal_hi, hard_max) seconds per platform.
    _SPECS: ClassVar[dict[str, tuple[float, float, float]]] = {
        "youtube_shorts": (15.0, 45.0, 180.0),
        "tiktok": (15.0, 60.0, 600.0),
        "instagram_reels": (15.0, 30.0, 90.0),
    }
    _PLATFORM_NOTES: ClassVar[dict[str, str]] = {
        "youtube_shorts": "Shorts rewards strong retention; longer explainers can work.",
        "tiktok": "TikTok rewards a fast hook and trend/community fit; tolerates length.",
        "instagram_reels": "Reels favours short, polished, aesthetic clips.",
    }

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        duration = ctx.video_duration()
        if duration is None:
            return ViralityOutcome.unavailable(
                "Requires the video duration (Cognitive Engine video inspection) to "
                "assess platform format fit."
            )
        inspection = ctx.cognitive_data("video_inspection") or {}
        width = S.as_float(inspection.get("width"))
        height = S.as_float(inspection.get("height"))
        vertical = bool(height and width and height >= width)
        vertical_bonus = 0.0 if not (width and height) else (0.15 if vertical else -0.2)

        # Optional content factors (only used if genuinely available).
        hook = ctx.virality_data("hook_strength")
        momentum = ctx.virality_data("momentum")
        content_factors: list[float] = []
        if hook and "score" in hook:
            content_factors.append(S.as_float(hook.get("score")))
        if momentum and "score" in momentum:
            content_factors.append(S.as_float(momentum.get("score")))
        content_avg = S.mean(content_factors) if content_factors else None

        platforms: dict[str, Any] = {}
        for plat, (lo, hi, hard) in self._SPECS.items():
            fmt = _duration_fit(duration, lo, hi, hard)
            base = S.clamp01(fmt + vertical_bonus)
            blended = base if content_avg is None else S.clamp01(0.6 * base + 0.4 * content_avg)
            platforms[plat] = {
                "score": S.round3(blended),
                "format_fit": S.round3(fmt),
                "reason": (
                    f"{int(duration)}s vs ideal {int(lo)}-{int(hi)}s; "
                    f"{'vertical' if vertical else 'non-vertical'} aspect. "
                    + self._PLATFORM_NOTES[plat]
                ),
            }
        overall = S.mean([p["score"] for p in platforms.values()])
        evidence: list[dict[str, Any]] = [
            {"type": "duration", "detail": f"{int(duration)}s"},
            {
                "type": "aspect",
                "detail": f"{int(width)}x{int(height)}" if width and height else "unknown",
            },
        ]
        limitations = (
            "Platform fit is based on format facts (duration, aspect ratio)"
            + (
                ""
                if content_avg is not None
                else " only; content factors (hook, pacing) were unavailable (no transcript)"
            )
            + ". It does not model trends, audio, or each platform's ranking algorithm."
        )
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(overall),
                "confidence": S.round3(0.5 if content_avg is None else 0.65),
                "platforms": platforms,
                "vertical": vertical,
                "evidence": evidence,
                "limitations": limitations,
            }
        )


# --------------------------------------------------------------------------- #
# 14. Audience Fit - best audience segments, from topic keywords only.
# --------------------------------------------------------------------------- #
class AudienceFitAnalyzer(ViralityAnalyzer):
    name = "audience_fit"
    version = "1"
    _SEGMENTS: ClassVar[dict[str, frozenset[str]]] = {
        "Productivity & self-improvement": frozenset(
            {
                "productivity",
                "focus",
                "habits",
                "habit",
                "goals",
                "discipline",
                "motivation",
                "mindset",
            }
        ),
        "Personal finance": frozenset(
            {
                "money",
                "invest",
                "investing",
                "finance",
                "budget",
                "wealth",
                "income",
                "savings",
                "stocks",
            }
        ),
        "Technology & software": frozenset(
            {
                "code",
                "coding",
                "software",
                "developer",
                "programming",
                "tech",
                "data",
                "computer",
                "app",
            }
        ),
        "Health & fitness": frozenset(
            {"fitness", "workout", "gym", "health", "diet", "nutrition", "training", "exercise"}
        ),
        "Business & entrepreneurship": frozenset(
            {
                "business",
                "startup",
                "entrepreneur",
                "marketing",
                "sales",
                "company",
                "brand",
                "customers",
            }
        ),
        "Education & learning": frozenset(
            {
                "learn",
                "learning",
                "study",
                "science",
                "history",
                "language",
                "education",
                "knowledge",
            }
        ),
        "Lifestyle & vlog": frozenset(
            {"life", "day", "routine", "travel", "food", "home", "family"}
        ),
    }

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        summary = ctx.story_data("story_summary")
        if summary is None:
            return ViralityOutcome.unavailable(
                "Requires the Story Engine's summary (no transcript) to infer audience "
                "segments from topic keywords."
            )
        keywords = [S.as_str(k).lower() for k in S.as_list(summary.get("main_subject"))]
        for group in S.as_list(summary.get("secondary_topics")):
            keywords += (
                [S.as_str(k).lower() for k in S.as_list(group)]
                if isinstance(group, list)
                else [S.as_str(group).lower()]
            )
        keywords = [k for k in keywords if k]
        if not keywords:
            return ViralityOutcome.unavailable(
                "No topic keywords are available (requires a transcript), so audience "
                "segments cannot be inferred from evidence."
            )

        matched: list[dict[str, Any]] = []
        for segment, vocab in self._SEGMENTS.items():
            hits = sorted(set(keywords) & vocab)
            if hits:
                matched.append(
                    {"segment": segment, "matched_keywords": hits, "strength": len(hits)}
                )
        matched.sort(key=lambda m: m["strength"], reverse=True)
        score = S.clamp01(len(matched) / 2) if matched else 0.1
        report(1.0)
        return ViralityOutcome.completed(
            {
                "score": S.round3(score),
                "confidence": 0.4 if matched else 0.3,
                "segments": matched[:4],
                "evidence": [{"type": "topic_keywords", "detail": ", ".join(keywords[:8])}],
                "limitations": (
                    "Audience segments are inferred from topic keywords only; no "
                    "demographic, geographic, or engagement data is used. Absence of a "
                    "match means the topics did not map to a known segment, not that no "
                    "audience exists."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 15. Virality Summary - aggregate everything into one explainable report.
# --------------------------------------------------------------------------- #
class ViralitySummaryAnalyzer(ViralityAnalyzer):
    name = "virality_summary"
    version = "1"
    depends_on = tuple(S.CATEGORY_FOR_STAGE.keys())

    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        category_scores: dict[str, Any] = {}
        available: list[str] = []
        pending: list[dict[str, str]] = []
        from olympus.domain.entities.virality import VIRALITY_STAGE_LABELS

        for stage_name, category in S.CATEGORY_FOR_STAGE.items():
            data = ctx.virality_data(stage_name)
            result = ctx.results.get(stage_name)
            if data is not None and "score" in data:
                category_scores[category] = {
                    "score": S.as_float(data.get("score")),
                    "confidence": S.as_float(data.get("confidence")),
                    "label": VIRALITY_STAGE_LABELS.get(stage_name, stage_name),
                    "stage": stage_name,
                }
                available.append(category)
            else:
                reason = (result.reason or result.error) if result else "did not run"
                pending.append(
                    {"category": category, "stage": stage_name, "reason": reason or "unavailable"}
                )

        pairs = [(category_scores[c]["score"], S.CATEGORY_WEIGHTS.get(c, 0.02)) for c in available]
        overall = S.round3(S.weighted_mean(pairs)) if pairs else None
        overall_conf = S.coverage_confidence(len(available), len(S.CATEGORY_FOR_STAGE))

        strengths, weaknesses, risks, missed = _assess(category_scores)
        recommendations = _recommendations(ctx, category_scores)
        timeline = _build_timeline(ctx)
        heatmap, heat_note = _build_heatmap(ctx)

        report(1.0)
        return ViralityOutcome.completed(
            {
                "overall_score": overall,
                "overall_confidence": S.round3(overall_conf),
                "category_scores": category_scores,
                "available_categories": available,
                "pending_categories": pending,
                "strengths": strengths,
                "weaknesses": weaknesses,
                "risks": risks,
                "missed_opportunities": missed,
                "recommendations": recommendations,
                "timeline": timeline,
                "heatmap": heatmap,
                "heatmap_note": heat_note,
                "limitations": (
                    "The overall score is a weighted blend of only the categories that "
                    "were available; missing categories are listed as pending and never "
                    "counted as zero. All inputs are transparent heuristics over the "
                    "transcript and story structure, not trained engagement models."
                ),
                "note": (
                    "Aggregated virality assessment. Empty fields mean the underlying "
                    "signal was unavailable, not that it was analyzed and found absent."
                ),
            }
        )


# --------------------------------------------------------------------------- #
# Shared, pure aggregation helpers (not stage-to-stage coupling).
# --------------------------------------------------------------------------- #
def _metric(window: dict[str, Any], key: str) -> Any:
    metrics = window.get("metrics")
    return metrics.get(key) if isinstance(metrics, dict) else None


def _gather_dependencies(
    ctx: ViralityStageContext, weights: dict[str, float]
) -> tuple[list[tuple[float, float]], list[dict[str, Any]]]:
    pairs: list[tuple[float, float]] = []
    evidence: list[dict[str, Any]] = []
    for stage_name, weight in weights.items():
        data = ctx.virality_data(stage_name)
        if data is not None and "score" in data:
            score = S.as_float(data.get("score"))
            pairs.append((score, weight))
            evidence.append({"type": "category", "category": stage_name, "score": S.round3(score)})
    return pairs, evidence


def _assess(
    category_scores: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    strengths: list[dict[str, Any]] = []
    weaknesses: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    missed: list[dict[str, Any]] = []

    def score(cat: str) -> float | None:
        return category_scores[cat]["score"] if cat in category_scores else None

    for category, info in category_scores.items():
        if info["score"] >= 0.66:
            strengths.append(
                {
                    "category": category,
                    "score": info["score"],
                    "evidence": f"high {info['label']} score",
                }
            )
        elif info["score"] <= 0.33:
            weaknesses.append(
                {
                    "category": category,
                    "score": info["score"],
                    "evidence": f"low {info['label']} score",
                }
            )

    hook, retention = score("hook"), score("retention")
    if hook is not None and hook <= 0.4:
        risks.append(
            {"category": "hook", "evidence": "weak opening risks an immediate scroll-past"}
        )
    if retention is not None and retention <= 0.45:
        risks.append({"category": "retention", "evidence": "predicted early drop-off in pacing"})

    emotion, info_v = score("emotion"), score("information")
    if emotion is not None and hook is not None and emotion >= 0.6 and hook <= 0.4:
        missed.append({"evidence": "strong emotional content is undercut by a weak opening hook"})
    if (
        info_v is not None
        and score("sharing") is not None
        and info_v >= 0.6
        and score("sharing") <= 0.4
    ):
        missed.append({"evidence": "high information value is not being packaged for sharing"})
    return strengths, weaknesses, risks, missed


def _recommendations(
    ctx: ViralityStageContext, category_scores: dict[str, Any]
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    hook = category_scores.get("hook")
    if hook is not None and hook["score"] < 0.5:
        recs.append(
            {
                "title": "Strengthen the opening hook",
                "reason": (
                    "the detected hook is weak (low strength/confidence from the "
                    "transcript opening)"
                ),
                "evidence_stage": "hook_strength",
            }
        )
    # A late payoff is a concrete, evidence-backed recommendation.
    payoff = ctx.story_data("payoff_detection") or {}
    for rel in S.as_list(payoff.get("relationships")):
        setup = S.as_float(rel.get("setup_timestamp"))
        pay = S.as_float(rel.get("payoff_timestamp"))
        if pay - setup >= 30:
            recs.append(
                {
                    "title": "A key payoff arrives late",
                    "reason": (
                        f"the setup at {int(setup)}s is only paid off at {int(pay)}s; "
                        "consider front-loading it"
                    ),
                    "evidence_stage": "payoff_detection",
                }
            )
            break
    emotion = category_scores.get("emotion")
    if emotion is not None and emotion["score"] >= 0.6:
        etp = ctx.story_data("emotional_turning_points") or {}
        turns = S.as_list(etp.get("turning_points"))
        if turns:
            at = int(S.as_float(turns[0].get("timestamp")))
            recs.append(
                {
                    "title": "High clipping potential at an emotional spike",
                    "reason": f"a notable emotional shift occurs around {at}s",
                    "evidence_stage": "emotional_impact",
                }
            )
    return recs


def _build_timeline(ctx: ViralityStageContext) -> list[dict[str, Any]]:
    """Timeline events derived from real story signals (sorted by time)."""

    events: list[dict[str, Any]] = []
    hook = ctx.story_data("hook_detection") or {}
    if hook.get("has_hook"):
        window = hook.get("window") if isinstance(hook.get("window"), dict) else {}
        events.append(
            {
                "timestamp": S.as_float(window.get("start")),
                "type": "interest_rise",
                "label": "Opening hook",
                "detail": S.as_str(hook.get("why")),
                "confidence": S.as_float(hook.get("confidence")),
            }
        )
    for t in S.as_list((ctx.story_data("emotional_turning_points") or {}).get("turning_points")):
        events.append(
            {
                "timestamp": S.as_float(t.get("timestamp")),
                "type": "emotion_spike",
                "label": "Emotional shift",
                "detail": _emotion_transition(t),
                "confidence": S.as_float(t.get("confidence")),
            }
        )
    payoff = ctx.story_data("payoff_detection") or {}
    for rel in S.as_list(payoff.get("relationships")):
        events.append(
            {
                "timestamp": S.as_float(rel.get("setup_timestamp")),
                "type": "curiosity",
                "label": "Curiosity opened",
                "detail": S.as_str(rel.get("setup_excerpt"))[:120],
                "confidence": S.as_float(rel.get("confidence")),
            }
        )
        events.append(
            {
                "timestamp": S.as_float(rel.get("payoff_timestamp")),
                "type": "payoff",
                "label": "Payoff",
                "detail": S.as_str(rel.get("payoff_excerpt"))[:120],
                "confidence": S.as_float(rel.get("confidence")),
            }
        )
    for sec in S.as_list((ctx.story_data("narrative_segmentation") or {}).get("sections")):
        if S.as_str(sec.get("role")) in ("conflict", "problem"):
            events.append(
                {
                    "timestamp": S.as_float(sec.get("start")),
                    "type": "conflict",
                    "label": "Conflict / problem",
                    "detail": S.as_str(sec.get("supporting_excerpt"))[:120],
                    "confidence": S.as_float(sec.get("confidence")),
                }
            )
    for w in S.as_list((ctx.story_data("information_density") or {}).get("windows")):
        if S.as_str(w.get("classification")) in ("slow", "filler"):
            events.append(
                {
                    "timestamp": S.as_float(w.get("start")),
                    "type": "attention_drop",
                    "label": "Attention may weaken",
                    "detail": S.as_str(w.get("reason")),
                    "confidence": S.as_float(w.get("confidence"), 0.4),
                }
            )
    events.sort(key=lambda e: e["timestamp"])
    return events


def _build_heatmap(ctx: ViralityStageContext) -> tuple[list[dict[str, Any]], str]:
    """Per-window heat intensity computed from REAL analysis signals.

    Heat = information density + emotional activity + payoff presence + an early
    hook boost, per time window. Returns ([], note) when no density windows
    exist (i.e. no transcript) - the heatmap is never fabricated.
    """

    density = ctx.story_data("information_density")
    windows = S.as_list((density or {}).get("windows"))
    if not windows:
        return [], (
            "No heatmap is available because information density (which requires a "
            "transcript) was not produced. Heat is never fabricated."
        )
    emo_ts = [
        S.as_float(t.get("timestamp"))
        for t in S.as_list((ctx.story_data("emotional_turning_points") or {}).get("turning_points"))
    ]
    payoff_ts = [
        S.as_float(r.get("payoff_timestamp"))
        for r in S.as_list((ctx.story_data("payoff_detection") or {}).get("relationships"))
    ]
    hook = ctx.story_data("hook_detection") or {}
    hook_start = (
        S.as_float((hook.get("window") or {}).get("start")) if hook.get("has_hook") else None
    )

    cells: list[dict[str, Any]] = []
    for w in windows:
        start, end = S.as_float(w.get("start")), S.as_float(w.get("end"))
        d = S.as_float(w.get("density"))
        emo_near = 1.0 if any(start <= ts < end for ts in emo_ts) else 0.0
        payoff_near = 1.0 if any(start <= ts < end for ts in payoff_ts) else 0.0
        hook_boost = 1.0 if hook_start is not None and start <= hook_start < end else 0.0
        heat = S.clamp01(0.5 * d + 0.2 * emo_near + 0.2 * payoff_near + 0.1 * hook_boost)
        cells.append(
            {
                "start": start,
                "end": end,
                "heat": S.round3(heat),
                "components": {
                    "density": S.round3(d),
                    "emotion": emo_near,
                    "payoff": payoff_near,
                    "hook": hook_boost,
                },
            }
        )
    return (
        cells,
        "Heat intensity is derived from information density, emotional shifts, and "
        "payoffs per time window.",
    )

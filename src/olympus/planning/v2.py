"""V2 clip-planning helpers.

Pure, auditable heuristics for the V2 planner layer. These helpers do not call
models or fabricate scores; they turn transcript timing/text and project intent
into transparent candidate windows, hook metadata, and editing-style decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from olympus.planning import scoring as S  # noqa: N812
from olympus.trends import (
    build_evergreen_snapshot,
    detect_content_niche_v2,
    match_trend_patterns,
)
from olympus.trends.library import normalize_niche
from olympus.trends.store import snapshot_is_fresh


@dataclass(frozen=True, slots=True)
class ClipCountStrategy:
    """Duration-aware internal guidance for automatic Short selection."""

    target: int
    minimum: int
    maximum: int
    primary_threshold: float
    secondary_threshold: float
    candidate_budget: int
    coverage_bins: int
    reason: str


HOOK_PATTERNS: tuple[tuple[str, tuple[str, ...], float, str], ...] = (
    (
        "contrarian_statement",
        ("everyone is wrong", "most people are wrong", "the truth is", "actually"),
        0.84,
        "contrarian framing",
    ),
    (
        "mistake_warning",
        ("biggest mistake", "stop doing", "don't do", "warning", "avoid this"),
        0.83,
        "mistake/warning framing",
    ),
    (
        "unexpected_truth",
        ("nobody tells you", "no one tells you", "unexpected truth", "hidden"),
        0.82,
        "unexpected truth cue",
    ),
    (
        "social_proof",
        ("everyone", "millions", "top creators", "the best", "professionals"),
        0.72,
        "social proof cue",
    ),
    (
        "tension_line",
        ("almost", "risk", "pressure", "high stakes", "before it was too late"),
        0.78,
        "tension cue",
    ),
    (
        "shock",
        ("shocking", "insane", "crazy", "unbelievable", "nobody expected"),
        0.88,
        "surprise language",
    ),
    ("curiosity", ("why", "how", "what if", "secret", "here's", "wait"), 0.78, "curiosity gap"),
    (
        "emotional",
        ("afraid", "heart", "cried", "broke", "lost", "alone"),
        0.76,
        "emotional stakes",
    ),
    (
        "conflict",
        ("versus", "against", "fight", "argument", "problem", "wrong"),
        0.74,
        "conflict/problem",
    ),
    (
        "transformation",
        ("changed", "became", "from", "to", "before", "after"),
        0.73,
        "transformation",
    ),
    ("question", ("?", "do you", "have you", "did you", "can you"), 0.72, "direct question"),
    (
        "mistake_failure",
        ("mistake", "failed", "failure", "gave up", "almost quit"),
        0.76,
        "failure/recovery",
    ),
    (
        "money_status",
        ("money", "rich", "broke", "status", "million", "luxury"),
        0.75,
        "money/status",
    ),
    (
        "motivational",
        ("discipline", "dream", "believe", "mindset", "never give up"),
        0.72,
        "motivation",
    ),
    (
        "stream_funny",
        ("laugh", "chat", "bro", "no way", "clip it", "funny"),
        0.72,
        "stream/funny reaction",
    ),
    ("wait_for_it", ("wait for it", "watch this", "look at this"), 0.82, "delayed payoff"),
    ("nobody_expected", ("nobody expected", "no one expected"), 0.84, "unexpected outcome"),
    (
        "this_changed_everything",
        ("changed everything", "everything changed"),
        0.82,
        "turning point",
    ),
    ("he_almost_gave_up", ("almost gave up", "almost quit"), 0.81, "near-failure tension"),
    (
        "the_moment_it_clicked",
        ("moment it clicked", "finally clicked", "realized"),
        0.78,
        "realization",
    ),
)

NICHE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "business": (
        "business",
        "customer",
        "founder",
        "market",
        "money",
        "product",
        "revenue",
        "sales",
        "startup",
    ),
    "creator_education": (
        "audience",
        "clip",
        "content",
        "creator",
        "edit",
        "hook",
        "shorts",
        "thumbnail",
        "viral",
        "youtube",
    ),
    "education": (
        "because",
        "example",
        "explain",
        "learn",
        "lesson",
        "means",
        "reason",
        "study",
    ),
    "gaming_streaming": (
        "chat",
        "clip it",
        "game",
        "gaming",
        "level",
        "no way",
        "stream",
        "win",
    ),
    "motivation": (
        "belief",
        "discipline",
        "dream",
        "fail",
        "gave up",
        "mindset",
        "motivation",
        "never",
    ),
    "podcast_interview": (
        "conversation",
        "episode",
        "guest",
        "interview",
        "podcast",
        "question",
        "said",
        "talked",
    ),
    "productivity": (
        "calendar",
        "email",
        "focus",
        "productivity",
        "structure",
        "task",
        "time blocking",
        "urgent",
    ),
}

EVERGREEN_RESEARCH: dict[str, Any] = {
    "trend_patterns": [
        {
            "id": "contrarian_truth",
            "label": "Contrarian truth",
            "cues": ("most people are wrong", "the truth is", "actually", "nobody tells you"),
            "why_it_works": "Creates a fast belief gap without promising facts not in the clip.",
        },
        {
            "id": "mistake_to_fix",
            "label": "Mistake to fix",
            "cues": ("biggest mistake", "stop doing", "avoid this", "wrong"),
            "why_it_works": "Frames the clip as useful and immediately stakes a consequence.",
        },
        {
            "id": "setup_to_payoff",
            "label": "Setup to payoff",
            "cues": ("because", "finally", "turns out", "that's why", "what changed"),
            "why_it_works": "Rewards retention with a clear answer, reveal, or lesson.",
        },
        {
            "id": "moment_of_change",
            "label": "Moment of change",
            "cues": ("changed everything", "realized", "moment it clicked", "then I discovered"),
            "why_it_works": "Anchors the Short on a before/after turn.",
        },
    ],
    "hook_patterns": [
        "Open on tension, contradiction, or a pointed question in the first sentence.",
        "Use faithful wording from the transcript; do not invent a bigger promise.",
        "Make the first caption a compressed thesis, not a generic title.",
    ],
    "retention_patterns": [
        "Resolve one question at a time; avoid long context before the first payoff.",
        "Prefer clips that move from setup to tension to answer within 15-60 seconds.",
        "Cut filler before the first meaningful word when the transcript supports it.",
    ],
    "ending_patterns": [
        "End on the payoff, lesson, reversal, or clean next-step line.",
        "Avoid stopping on setup-only sentences or mid-thought connective phrases.",
        "Allow a tiny tail after the payoff so the final word is not clipped.",
    ],
    "title_patterns": [
        "The mistake behind {topic}",
        "Why {topic} finally clicked",
        "Most people miss this about {topic}",
    ],
}

CLICKBAIT_CUES = (
    "you won't believe",
    "doctors hate",
    "secret they don't want",
    "shocking truth revealed",
    "gone wrong",
)


def clip_count_strategy(
    duration_seconds: float | None,
    requested: int | None = None,
) -> ClipCountStrategy:
    """Return automatic V2 clip-count guidance without forcing filler clips."""

    duration = max(0.0, float(duration_seconds or 0.0))
    if requested is not None and requested > 0:
        target = max(1, min(40, int(requested)))
        return ClipCountStrategy(
            target=target,
            minimum=max(1, min(target, target // 2 or 1)),
            maximum=max(target, min(40, target * 2)),
            primary_threshold=0.42,
            secondary_threshold=0.32,
            candidate_budget=max(target * 5, target + 8),
            coverage_bins=max(3, min(24, target)),
            reason=(
                f"internal override requested {target} clip(s); automatic quality gates "
                "may return fewer or more within the safe band"
            ),
        )
    if duration <= 180:
        return ClipCountStrategy(
            3,
            1,
            3,
            0.44,
            0.34,
            14,
            3,
            "0-3 minutes: automatically keep 1-3 strong clips if the source supports them",
        )
    if duration <= 600:
        return ClipCountStrategy(
            4,
            2,
            5,
            0.42,
            0.32,
            24,
            5,
            "3-10 minutes: automatically keep 2-5 strong clips after quality filtering",
        )
    if duration <= 1800:
        return ClipCountStrategy(
            7,
            4,
            10,
            0.4,
            0.3,
            44,
            8,
            "10-30 minutes: automatically keep 4-10 strong clips when enough moments exist",
        )
    if duration <= 3600:
        return ClipCountStrategy(
            12,
            6,
            15,
            0.38,
            0.29,
            70,
            12,
            "30-60 minutes: automatically keep 6-15 strong clips with timeline diversity",
        )
    if duration <= 7200:
        return ClipCountStrategy(
            20,
            10,
            30,
            0.36,
            0.28,
            120,
            18,
            "60-120 minutes: automatically keep 10-30 strong clips when the source has them",
        )
    return ClipCountStrategy(
        28,
        15,
        40,
        0.35,
        0.27,
        160,
        24,
        "120+ minutes: automatically keep 15-40 strong clips, capped for local workload",
    )


def strategy_dict(strategy: ClipCountStrategy) -> dict[str, Any]:
    """JSON-safe representation for planning artifacts and UI diagnostics."""

    return {
        "mode": "automatic",
        "target": strategy.target,
        "minimum": strategy.minimum,
        "maximum": strategy.maximum,
        "primary_threshold": strategy.primary_threshold,
        "secondary_threshold": strategy.secondary_threshold,
        "candidate_budget": strategy.candidate_budget,
        "coverage_bins": strategy.coverage_bins,
        "reason": strategy.reason,
    }


def detect_content_niche(text: str, content_category: str | None = None) -> dict[str, Any]:
    """Compatibility wrapper around the canonical multi-signal niche detector."""

    return detect_content_niche_v2(text, content_category=content_category)


def viral_research_snapshot(
    content_niche: dict[str, Any] | str | None,
    *,
    now: datetime | None = None,
    cached: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for old callers that need a synchronous fallback."""

    current = now or datetime.now(UTC)
    niche_name = normalize_niche(
        S.as_str(content_niche.get("primary"))
        if isinstance(content_niche, dict)
        else S.as_str(content_niche)
    )
    if cached and snapshot_is_fresh(cached, current):
        cached_niches = [S.as_str(n) for n in S.as_list(cached.get("niches_detected"))]
        detected = S.as_dict(cached.get("detected_niche"))
        primary = S.as_str(detected.get("primary"))
        if not cached_niches or niche_name in cached_niches or primary == niche_name:
            return {**cached, "cache_hit": True}
    return build_evergreen_snapshot(
        content_niche or niche_name,
        now=current,
        fallback_reason=(
            "Planning compatibility fallback used because no Virality trend snapshot exists"
        ),
    )


def trend_pattern_match(
    text: str,
    research_snapshot: dict[str, Any] | None,
    content_niche: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper around canonical candidate pattern matching."""

    return match_trend_patterns(text, research_snapshot, content_niche)


def hook_analysis(text: str, research_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hook Engine V2: score first-line quality without clickbait inflation."""

    raw = " ".join(text.split())
    base = classify_hook(raw)
    words = raw.split()
    low = raw.lower()
    clickbait_hits = [cue for cue in CLICKBAIT_CUES if cue in low]
    has_specificity = any(char.isdigit() for char in raw) or any(
        cue in low for cue in ("because", "how", "why", "mistake", "problem", "reason")
    )
    faithful_line = raw[:140]
    research_hooks = S.as_list(S.as_dict(research_snapshot).get("hook_patterns"))
    curiosity = 0.7 if any(cue in low for cue in ("why", "how", "what if", "secret")) else 0.35
    clarity = (
        S.clamp01(len(words) / 12)
        if len(words) <= 24
        else S.clamp01(1 - (len(words) - 24) / 30)
    )
    novelty = S.as_float(base.get("score"))
    promise_payoff = (
        0.72
        if any(cue in low for cue in ("because", "turns out", "finally"))
        else 0.42
    )
    no_clickbait = 0.25 if clickbait_hits else 1.0
    score = S.clamp01(
        0.34 * novelty
        + 0.2 * curiosity
        + 0.18 * clarity
        + 0.18 * promise_payoff
        + 0.1 * no_clickbait
    )
    return {
        **base,
        "engine": "hook_engine_v2",
        "category": base.get("category"),
        "faithful_hook_line": faithful_line,
        "clickbait_risk": bool(clickbait_hits),
        "clickbait_cues": clickbait_hits,
        "score": S.round3(score),
        "scores": {
            "curiosity": S.round3(curiosity),
            "clarity": S.round3(clarity),
            "specificity": S.round3(0.72 if has_specificity else 0.38),
            "novelty": S.round3(novelty),
            "promise_payoff": S.round3(promise_payoff),
            "no_clickbait": S.round3(no_clickbait),
        },
        "reason": "faithful transcript hook with V2 curiosity/clarity/payoff checks",
        "research_alignment": research_hooks[:2],
        "editing_instructions": {
            "first_three_seconds": "punch in or caption-pop on the faithful hook line",
            "highlight_word": _strongest_word(faithful_line),
            "avoid": "do not rewrite the hook into a bigger claim than the transcript supports",
        },
    }


def storytelling_analysis(text: str) -> dict[str, Any]:
    """Storytelling Engine V2 metadata for a candidate window."""

    sentences = _sentences(text)
    low = text.lower()
    setup = sentences[0] if sentences else ""
    tension = next(
        (
            sentence
            for sentence in sentences
            if any(
                cue in sentence.lower()
                for cue in ("problem", "mistake", "but", "wrong", "failed")
            )
        ),
        "",
    )
    payoff = next(
        (
            sentence
            for sentence in reversed(sentences)
            if any(
                cue in sentence.lower()
                for cue in ("because", "finally", "turns out", "that's why", "learned", "fixed")
            )
        ),
        sentences[-1] if sentences else "",
    )
    has_setup = bool(setup)
    has_tension = bool(tension)
    has_payoff = bool(payoff) and payoff != setup
    if has_setup and has_tension and has_payoff:
        shape = "setup_tension_payoff"
    elif has_setup and has_payoff:
        shape = "setup_payoff"
    elif has_tension:
        shape = "tension_only"
    else:
        shape = "context_slice"
    missing = [
        label
        for label, present in (
            ("setup", has_setup),
            ("tension", has_tension),
            ("payoff", has_payoff),
        )
        if not present
    ]
    score = S.clamp01(
        0.28 * float(has_setup)
        + 0.27 * float(has_tension)
        + 0.35 * float(has_payoff)
        + 0.1 * (1.0 if len(sentences) <= 6 else 0.6)
    )
    return {
        "engine": "storytelling_engine_v2",
        "story_shape": shape,
        "setup_line": setup[:220],
        "tension_line": tension[:220],
        "payoff_line": payoff[:220],
        "score": S.round3(score),
        "missing_parts": missing,
        "retention_question": _retention_question(low, setup),
        "reason": "candidate evaluated for setup, tension, and payoff completeness",
    }


def ending_analysis(text: str, payoffs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Ending/Payoff Engine V2 metadata for candidate finish quality."""

    sentences = _sentences(text)
    ending = sentences[-1] if sentences else ""
    low = ending.lower()
    payoff_list = payoffs or []
    has_story_payoff = bool(payoff_list)
    has_language_payoff = any(
        cue in low
        for cue in (
            "because",
            "finally",
            "turns out",
            "that's why",
            "learned",
            "fixed",
            "therefore",
        )
    )
    weak_finish = low.startswith(("and ", "but ", "so ", "then ")) or low.endswith(
        (",", "and", "but")
    )
    ending_type = (
        "story_payoff"
        if has_story_payoff
        else "lesson_or_reveal"
        if has_language_payoff
        else "clean_final_line"
        if ending and not weak_finish
        else "weak_or_incomplete"
    )
    score = (
        0.86
        if has_story_payoff
        else 0.72
        if has_language_payoff
        else 0.52
        if not weak_finish
        else 0.24
    )
    warnings = []
    if weak_finish:
        warnings.append("candidate appears to end on a connective or incomplete thought")
    if not has_story_payoff and not has_language_payoff:
        warnings.append("no explicit payoff language detected in the final line")
    return {
        "engine": "ending_payoff_engine_v2",
        "ending_type": ending_type,
        "ending_line": ending[:220],
        "payoff_present": bool(has_story_payoff or has_language_payoff),
        "score": S.round3(score),
        "reason": (
            "story payoff relationship"
            if has_story_payoff
            else "final transcript line analysis"
        ),
        "boundary_advice": "hold 0.15-0.35s after the final word when rendering",
        "warnings": warnings,
    }


def viral_score_v2(
    scores: dict[str, Any],
    hook: dict[str, Any],
    story: dict[str, Any],
    ending: dict[str, Any],
    trend: dict[str, Any],
) -> dict[str, Any]:
    """Transparent Viral Score V2 formula for ranking/explanation."""

    components = {
        "hook": S.as_float(hook.get("score")),
        "retention": S.as_float(scores.get("retention")),
        "story": S.as_float(story.get("score")),
        "payoff": max(S.as_float(scores.get("payoff")), S.as_float(ending.get("score"))),
        "clarity": S.as_float(scores.get("clarity")),
        "trend_fit": S.as_float(trend.get("score")),
        "emotion": S.as_float(scores.get("emotion")),
        "uniqueness": S.as_float(scores.get("uniqueness")),
    }
    weights = {
        "hook": 0.2,
        "retention": 0.16,
        "story": 0.14,
        "payoff": 0.14,
        "clarity": 0.11,
        "trend_fit": 0.09,
        "emotion": 0.08,
        "uniqueness": 0.08,
    }
    overall = S.weighted_mean([(components[key], weight) for key, weight in weights.items()])
    return {
        "overall": S.round3(overall),
        "components": {key: S.round3(value) for key, value in components.items()},
        "weights": weights,
        "formula": (
            "0.20 hook + 0.16 retention + 0.14 story + 0.14 payoff + 0.11 clarity "
            "+ 0.09 trend_fit + 0.08 emotion + 0.08 uniqueness"
        ),
        "confidence": S.round3(
            S.mean(
                [
                    S.as_float(hook.get("score")),
                    S.as_float(story.get("score")),
                    S.as_float(ending.get("score")),
                    S.as_float(trend.get("confidence")),
                ]
            )
        ),
    }


def optimize_boundaries(
    start: float,
    end: float,
    segments: list[dict[str, Any]],
    duration_seconds: float,
) -> dict[str, Any]:
    """Small, safe boundary optimization around transcript evidence."""

    original_start, original_end = start, end
    warnings: list[str] = []
    segs = _segments_in_window(segments, start, end)
    if segs:
        first = segs[0]
        first_text = S.as_str(first.get("text")).lower().strip()
        filler_prefixes = ("um ", "uh ", "honestly, um", "like ", "you know ")
        if first_text.startswith(filler_prefixes) and len(segs) > 1:
            next_start = S.as_float(segs[1].get("start"))
            if 0.0 <= next_start - start <= 2.5:
                start = next_start
        last_end = S.as_float(segs[-1].get("end")) or end
        if last_end > end - 0.05:
            end = min(duration_seconds or last_end, last_end + 0.25)
    if end <= start:
        start, end = original_start, original_end
        warnings.append("boundary optimization reverted because it would invert the clip")
    changed = abs(start - original_start) > 0.01 or abs(end - original_end) > 0.01
    return {
        "original_start": S.round3(original_start),
        "original_end": S.round3(original_end),
        "optimized_start": S.round3(start),
        "optimized_end": S.round3(end),
        "changed": changed,
        "reason": "trimmed filler start or held final word tail when transcript allowed"
        if changed
        else "existing transcript boundaries were already clean",
        "warnings": warnings,
    }


def editing_guidance(
    hook: dict[str, Any],
    story: dict[str, Any],
    ending: dict[str, Any],
    trend: dict[str, Any],
) -> dict[str, Any]:
    """Senior-editor metadata for the Editing Engine without changing rendering here."""

    hook_score = S.as_float(hook.get("score"))
    return {
        "first_3_seconds": {
            "motion": "clean punch-in" if hook_score >= 0.62 else "tight cold open",
            "caption": "bold faithful hook caption",
            "highlight_word": S.as_str(
                S.as_dict(hook.get("editing_instructions")).get("highlight_word")
            ),
            "sfx": "subtle clean hit only if SFX safety approves it",
        },
        "middle": {
            "story_shape": story.get("story_shape"),
            "retention_question": story.get("retention_question"),
            "matched_patterns": [
                match.get("label") for match in S.as_list(trend.get("matched_patterns"))
            ],
        },
        "ending": {
            "type": ending.get("ending_type"),
            "line": ending.get("ending_line"),
            "advice": ending.get("boundary_advice"),
        },
    }


def enrich_candidate(
    candidate: dict[str, Any],
    segments: list[dict[str, Any]],
    research_snapshot: dict[str, Any],
    content_niche: dict[str, Any],
    duration_seconds: float,
) -> dict[str, Any]:
    """Attach V2 candidate discovery metadata while preserving existing fields."""

    start = S.as_float(candidate.get("raw_start"))
    end = S.as_float(candidate.get("raw_end"))
    segs = _segments_in_window(segments, start, end)
    text = S.as_str(candidate.get("transcript_excerpt")) or " ".join(
        S.as_str(seg.get("text")) for seg in segs
    )
    hook = hook_analysis(_first_sentence(text), research_snapshot)
    story = storytelling_analysis(text)
    ending = ending_analysis(text)
    trend = trend_pattern_match(text, research_snapshot, content_niche)
    source = S.as_str(candidate.get("source")) or "unknown"
    candidate_id = S.as_str(candidate.get("candidate_id")) or (
        f"cand_{source}_{round(start * 1000)}_{round(end * 1000)}"
    )
    topic_words = _fingerprint(text).split()[:5]
    return {
        **candidate,
        "candidate_id": candidate_id,
        "candidate_type": source,
        "source_candidate_type": candidate.get("source_candidate_type") or source,
        "opening_line": _first_sentence(text),
        "ending_line": S.as_str(ending.get("ending_line")),
        "story_shape": story.get("story_shape"),
        "hook_potential": S.as_float(hook.get("score")),
        "payoff_potential": S.as_float(ending.get("score")),
        "emotion_profile": _emotion_profile(text),
        "topic_cluster": topic_words,
        "niche_match": {
            "primary": content_niche.get("primary"),
            "confidence": content_niche.get("confidence"),
            "evidence": content_niche.get("evidence"),
        },
        "viral_pattern_match": trend,
        "source_reason": candidate.get("why_selected")
        or candidate.get("source_reason")
        or f"{source.replace('_', ' ')} candidate",
        "confidence": S.round3(
            max(S.as_float(candidate.get("confidence")), S.mean([hook["score"], trend["score"]]))
        ),
        "v2_candidate_metadata": {
            "hook_analysis": hook,
            "storytelling": story,
            "ending": ending,
            "duration_seconds": S.round3(max(0.0, min(duration_seconds, end) - start)),
        },
    }


def low_clip_count_explanation(
    selected: list[dict[str, Any]],
    ranked: list[dict[str, Any]],
    strategy: dict[str, Any],
) -> dict[str, Any]:
    """Explain when automatic strategy returns fewer clips than the duration target."""

    minimum = int(S.as_float(strategy.get("minimum"), 1))
    if len(selected) >= minimum:
        return {
            "applies": False,
            "reason": "selected clip count satisfies the automatic duration strategy",
        }
    threshold = S.as_float(strategy.get("primary_threshold"))
    below = sum(1 for plan in ranked if S.as_float(plan.get("quality_score")) < threshold)
    return {
        "applies": True,
        "selected": len(selected),
        "minimum": minimum,
        "quality_floor": threshold,
        "below_quality_floor": below,
        "reason": (
            "Olympus found fewer strong clips than the duration target because candidates "
            "below the quality floor were rejected instead of padding with filler."
        ),
    }


def classify_hook(text: str) -> dict[str, Any]:
    """Classify and score a hook line with transparent lexical evidence."""

    raw = " ".join(text.split())
    low = raw.lower()
    best: tuple[str, float, str, list[str]] | None = None
    for category, phrases, base, reason in HOOK_PATTERNS:
        hits = [phrase for phrase in phrases if phrase in low]
        if not hits:
            continue
        score = min(0.98, base + 0.03 * (len(hits) - 1))
        if best is None or score > best[1]:
            best = (category, score, reason, hits[:3])
    if best is None:
        words = len(raw.split())
        score = 0.42 if words >= 8 else 0.28
        return {
            "category": "context",
            "score": S.round3(score),
            "is_strong": score >= 0.65,
            "explanation": "No strong V2 hook cue detected; relies on context.",
            "evidence": [],
            "hook_line": raw[:220],
            "hook_reason": "contextual opening line",
            "overlay_text": raw[:72],
            "caption_hook_text": raw[:72],
            "cold_open_offset_seconds": 0.0,
        }
    category, score, reason, hits = best
    return {
        "category": category,
        "score": S.round3(score),
        "is_strong": score >= 0.65,
        "explanation": f"Detected a {category.replace('_', ' ')} hook from {reason}.",
        "evidence": hits,
        "hook_line": raw[:220],
        "hook_reason": reason,
        "overlay_text": _hook_overlay(raw, category),
        "caption_hook_text": _hook_overlay(raw, category),
        "cold_open_offset_seconds": 0.0,
    }


def transcript_window_candidates(
    segments: list[dict[str, Any]],
    *,
    duration_seconds: float,
    target: int,
    existing: list[dict[str, Any]],
    strategy: ClipCountStrategy | None = None,
    research_snapshot: dict[str, Any] | None = None,
    content_niche: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build diverse transcript-backed candidate windows across the whole video.

    Multi-pass V2 generator:
    - rolling transcript windows,
    - topic shifts,
    - emotional/energy spikes,
    - fallback coverage windows across the whole source.
    """

    if not segments:
        return []
    strategy = strategy or clip_count_strategy(duration_seconds)
    ideal = _ideal_window_seconds(duration_seconds)
    ordered = sorted(segments, key=lambda seg: S.as_float(seg.get("start")))
    scored: list[dict[str, Any]] = []

    # PASS A: rolling transcript windows with overlap.
    stride = max(8.0, ideal * 0.45)
    next_start = 0.0
    for index, seg in enumerate(ordered):
        start = S.as_float(seg.get("start"))
        if start + 0.001 < next_start:
            continue
        cand = _candidate_from_index(
            ordered,
            index,
            duration_seconds=duration_seconds,
            window_seconds=ideal,
            source="transcript_window",
            reason="rolling transcript window across the full source",
            research_snapshot=research_snapshot,
            content_niche=content_niche,
        )
        if cand is not None:
            scored.append(cand)
        next_start = start + stride

    # PASS D: topic shifts from lexical/cue changes.
    for index in range(1, len(ordered)):
        previous = S.as_str(ordered[index - 1].get("text"))
        current = S.as_str(ordered[index].get("text"))
        if not _topic_shift(previous, current):
            continue
        cand = _candidate_from_index(
            ordered,
            index,
            duration_seconds=duration_seconds,
            window_seconds=max(ideal * 0.9, 24.0),
            source="topic_shift",
            reason="topic boundary or strong transition phrase",
            research_snapshot=research_snapshot,
            content_niche=content_niche,
        )
        if cand is not None:
            scored.append(cand)

    # PASS E: emotional/energy spikes.
    for index, seg in enumerate(ordered):
        text = S.as_str(seg.get("text"))
        energy = _energy_score(text)
        if energy < 0.45:
            continue
        cand = _candidate_from_index(
            ordered,
            index,
            duration_seconds=duration_seconds,
            window_seconds=max(ideal * 0.8, 22.0),
            source="emotional_spike",
            reason=f"emotional or high-energy language score {S.round3(energy)}",
            score_boost=min(0.16, energy * 0.12),
            research_snapshot=research_snapshot,
            content_niche=content_niche,
        )
        if cand is not None:
            scored.append(cand)

    # PASS F: fallback coverage, one reasonable window per timeline bucket.
    bins = max(1, strategy.coverage_bins)
    for bucket in range(bins):
        start = duration_seconds * (bucket / bins)
        index = _first_segment_at_or_after(ordered, start)
        cand = _candidate_from_index(
            ordered,
            index,
            duration_seconds=duration_seconds,
            window_seconds=ideal,
            source="fallback_coverage",
            reason=f"coverage fallback bucket {bucket + 1}/{bins}",
            minimum_score=0.18,
            research_snapshot=research_snapshot,
            content_niche=content_niche,
        )
        if cand is not None:
            scored.append(cand)

    scored.sort(key=lambda c: S.as_float(c.get("v2_window_score")), reverse=True)
    selected: list[dict[str, Any]] = []
    max_needed = max(strategy.candidate_budget, target * 4, target + 8)
    for cand in scored:
        if _too_close(cand, existing + selected) or _too_similar(cand, selected):
            continue
        selected.append(cand)
        if len(selected) >= max_needed:
            break
    return selected


def music_decision(content_category: str, *, enabled: bool) -> dict[str, Any]:
    """Choose a music mood honestly; asset availability is handled later."""

    category = (content_category or "auto").lower()
    mood = {
        "motivation": "inspirational",
        "motivational": "inspirational",
        "emotional": "soft piano",
        "entertainment": "energetic",
        "stream": "energetic",
        "gaming": "energetic",
        "funny": "funny",
        "business": "corporate motivation",
        "educational": "educational",
        "podcast / talking": "subtle ambient",
        "podcast": "subtle ambient",
        "interview": "subtle ambient",
    }.get(category, "subtle ambient")
    if not enabled:
        return {
            "status": "disabled",
            "category": "none",
            "reason": "music disabled by user setting",
        }
    return {
        "status": "unavailable",
        "category": mood,
        "reason": (
            "No local royalty-free music asset has been selected yet; add assets under "
            "assets/music to render music."
        ),
        "ducking": {"speech_priority": True, "target_under_speech_db": -18},
    }


def sfx_decision(hook: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    """Plan sparse SFX from the hook category without claiming assets exist."""

    if not enabled:
        return {
            "status": "disabled",
            "effects": [],
            "reason": "sound effects disabled by user setting",
        }
    category = S.as_str(hook.get("category"))
    effect = (
        "impact"
        if category
        in {"shock", "conflict", "mistake_failure", "mistake_warning", "contrarian_statement"}
        else "subtle hit"
    )
    if category in {"wait_for_it", "nobody_expected", "tension_line"}:
        effect = "riser"
    return {
        "status": "unavailable",
        "effects": [
            {
                "type": effect,
                "at": 0.0,
                "reason": (
                    f"support the {category.replace('_', ' ') or 'opening'} hook "
                    "without covering speech"
                ),
                "volume_db": -16,
            }
        ],
        "reason": (
            "No local royalty-free SFX asset has been selected yet; add assets under "
            "assets/sfx to render SFX."
        ),
    }


def caption_decision(
    content_category: str,
    hook: dict[str, Any],
    *,
    enabled: bool,
) -> dict[str, Any]:
    """Return a V2 caption style plan derived from content type and hook strength."""

    if not enabled:
        return {
            "status": "disabled",
            "style": "none",
            "reason": "captions disabled by user setting",
        }
    category = (content_category or "auto").lower()
    style = {
        "motivation": "motivational",
        "motivational": "motivational",
        "entertainment": "bold viral",
        "stream": "gaming/stream",
        "gaming": "gaming/stream",
        "emotional": "cinematic",
        "business": "clean",
        "educational": "educational",
        "podcast / talking": "podcast",
        "podcast": "podcast",
        "interview": "podcast",
    }.get(category, "bold viral" if S.as_float(hook.get("score")) >= 0.7 else "clean")
    return {
        "status": "planned",
        "style": style,
        "hook_emphasis": S.as_float(hook.get("score")) >= 0.65,
        "safe_zone": "lower-middle, above Shorts/Reels/TikTok UI controls",
        "animation": "pop" if S.as_float(hook.get("score")) >= 0.7 else "fade",
        "highlighted_words": list(hook.get("evidence") or [])[:3],
        "reason": "caption style follows content type and hook intensity",
    }


def _ideal_window_seconds(duration: float) -> float:
    if duration <= 180:
        return 24.0
    if duration <= 600:
        return 36.0
    if duration <= 1800:
        return 45.0
    if duration <= 3600:
        return 60.0
    return 75.0


def _candidate_from_index(
    segments: list[dict[str, Any]],
    index: int,
    *,
    duration_seconds: float,
    window_seconds: float,
    source: str,
    reason: str,
    score_boost: float = 0.0,
    minimum_score: float = 0.24,
    research_snapshot: dict[str, Any] | None = None,
    content_niche: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not segments:
        return None
    index = max(0, min(index, len(segments) - 1))
    start = S.as_float(segments[index].get("start"))
    end = start
    text_parts: list[str] = []
    for nxt in segments[index:]:
        end = S.as_float(nxt.get("end")) or S.as_float(nxt.get("start"))
        text_parts.append(S.as_str(nxt.get("text")))
        if end - start >= window_seconds:
            break
    if end <= start:
        return None
    text = " ".join(text_parts).strip()
    if len(text.split()) < 8:
        return None
    score, evidence = _window_score(text, end - start)
    score = S.clamp01(score + score_boost)
    if score < minimum_score:
        return None
    hook = hook_analysis(_first_sentence(text), research_snapshot)
    payoff = _payoff_candidate(text)
    story = storytelling_analysis(text)
    ending = ending_analysis(text)
    trend = trend_pattern_match(text, research_snapshot, content_niche)
    safe_end = min(duration_seconds or end, end)
    candidate_id = f"cand_{source}_{round(start * 1000)}_{round(safe_end * 1000)}"
    return {
        "candidate_id": candidate_id,
        "raw_start": max(0.0, start),
        "raw_end": safe_end,
        "source": source,
        "candidate_type": source,
        "source_candidate_type": source,
        "peak_heat": None,
        "v2_window_score": S.round3(score),
        "transcript_excerpt": text[:700],
        "opening_line": _first_sentence(text),
        "ending_line": S.as_str(ending.get("ending_line")),
        "story_shape": story.get("story_shape"),
        "hook_potential": hook["score"],
        "payoff_potential": ending.get("score"),
        "emotion_profile": _emotion_profile(text),
        "topic_cluster": _fingerprint(text).split()[:5],
        "niche_match": {
            "primary": S.as_dict(content_niche).get("primary"),
            "confidence": S.as_dict(content_niche).get("confidence"),
            "evidence": S.as_dict(content_niche).get("evidence"),
        },
        "viral_pattern_match": trend,
        "source_reason": reason,
        "hook_candidate": {
            "text": _first_sentence(text),
            "category": hook["category"],
            "score": hook["score"],
        },
        "payoff_candidate": payoff,
        "uniqueness_fingerprint": _fingerprint(text),
        "confidence": S.round3(min(0.95, 0.45 + score * 0.5)),
        "why_selected": f"{reason}; {evidence}",
        "v2_candidate_metadata": {
            "hook_analysis": hook,
            "storytelling": story,
            "ending": ending,
            "trend_match": trend,
        },
        "evidence": [
            {
                "type": source,
                "timestamp": start,
                "detail": f"{reason}; {evidence}",
            }
        ],
    }


def _first_segment_at_or_after(segments: list[dict[str, Any]], timestamp: float) -> int:
    for index, seg in enumerate(segments):
        if S.as_float(seg.get("start")) >= timestamp:
            return index
    return max(0, len(segments) - 1)


def _topic_shift(previous: str, current: str) -> bool:
    low = current.lower().strip()
    if low.startswith(
        (
            "but ",
            "however",
            "the next",
            "another",
            "now ",
            "so ",
            "then ",
            "the problem",
            "the reason",
            "the lesson",
            "what changed",
        )
    ):
        return True
    prev_words = _keyword_set(previous)
    curr_words = _keyword_set(current)
    if len(prev_words) < 3 or len(curr_words) < 3:
        return False
    overlap = len(prev_words & curr_words) / max(1, len(prev_words | curr_words))
    return overlap <= 0.12


def _energy_score(text: str) -> float:
    low = text.lower()
    cues = (
        "amazing",
        "angry",
        "breakthrough",
        "changed",
        "crazy",
        "dream",
        "fail",
        "funny",
        "hate",
        "huge",
        "insane",
        "laugh",
        "love",
        "mistake",
        "never",
        "no way",
        "nobody",
        "shocking",
        "terrified",
        "unbelievable",
        "wait",
        "win",
        "wrong",
    )
    hits = sum(1 for cue in cues if cue in low)
    punctuation = 0.15 if any(mark in text for mark in ("?", "!")) else 0.0
    return S.clamp01(0.18 * hits + punctuation)


def _payoff_candidate(text: str) -> dict[str, Any]:
    sentences = _sentences(text)
    if not sentences:
        return {"text": "", "score": 0.0, "reason": "no transcript sentence available"}
    tail = sentences[-1]
    low = tail.lower()
    has_payoff = any(
        cue in low
        for cue in (
            "because",
            "finally",
            "lesson",
            "so ",
            "that's why",
            "therefore",
            "turns out",
            "what changed",
        )
    )
    return {
        "text": tail[:220],
        "score": 0.72 if has_payoff else 0.42,
        "reason": "contains payoff language" if has_payoff else "uses final transcript line",
    }


def _first_sentence(text: str) -> str:
    sentences = _sentences(text)
    return sentences[0][:220] if sentences else text[:220]


def _sentences(text: str) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    pieces: list[str] = []
    current: list[str] = []
    for char in normalized:
        current.append(char)
        if char in ".?!":
            sentence = "".join(current).strip()
            if sentence:
                pieces.append(sentence)
            current = []
    rest = "".join(current).strip()
    if rest:
        pieces.append(rest)
    return pieces


def _keyword_set(text: str) -> set[str]:
    stop = {
        "about",
        "actually",
        "again",
        "also",
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
        "then",
        "there",
        "this",
        "what",
        "when",
        "with",
        "would",
        "your",
    }
    out: set[str] = set()
    for raw in text.lower().split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) >= 4 and token not in stop:
            out.add(token)
    return out


def _fingerprint(text: str) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    keywords = _keyword_set(text)
    for raw in text.lower().split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) < 4 or token in seen or token not in keywords:
            continue
        seen.add(token)
        ordered.append(token)
        if len(ordered) >= 24:
            break
    return " ".join(ordered)


def _window_score(text: str, window_duration: float) -> tuple[float, str]:
    hook = classify_hook(text[:220])
    words = text.split()
    density = min(1.0, len(words) / max(1.0, window_duration * 2.4))
    low = text.lower()
    payoff = (
        1.0
        if any(p in low for p in ("so", "therefore", "turns out", "finally", "because"))
        else 0.0
    )
    emotion = (
        1.0
        if any(p in low for p in ("love", "hate", "afraid", "dream", "fail", "win"))
        else 0.0
    )
    score = 0.35 * S.as_float(hook.get("score")) + 0.3 * density + 0.2 * payoff + 0.15 * emotion
    details = [
        f"hook {S.as_float(hook.get('score'))}",
        f"density {S.round3(density)}",
    ]
    if payoff:
        details.append("payoff cue")
    if emotion:
        details.append("emotion cue")
    return S.clamp01(score), ", ".join(details)


def _too_close(candidate: dict[str, Any], existing: list[dict[str, Any]]) -> bool:
    cs, ce = S.as_float(candidate.get("raw_start")), S.as_float(candidate.get("raw_end"))
    for other in existing:
        os, oe = S.as_float(other.get("raw_start")), S.as_float(other.get("raw_end"))
        if S.temporal_iou(cs, ce, os, oe) > 0.28:
            return True
    return False


def _too_similar(candidate: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    current = set(S.as_str(candidate.get("uniqueness_fingerprint")).split())
    if not current:
        return False
    for other in selected:
        existing = set(S.as_str(other.get("uniqueness_fingerprint")).split())
        if not existing:
            continue
        overlap = len(current & existing) / max(1, len(current | existing))
        if overlap >= 0.9:
            return True
    return False


def _cache_is_fresh(cached: dict[str, Any], now: datetime) -> bool:
    expires = _parse_iso(S.as_str(cached.get("expires_at")))
    return expires is not None and expires > now


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _segments_in_window(
    segments: list[dict[str, Any]], start: float, end: float
) -> list[dict[str, Any]]:
    return [
        seg
        for seg in segments
        if S.overlap_seconds(
            S.as_float(seg.get("start")),
            S.as_float(seg.get("end"), S.as_float(seg.get("start"))),
            start,
            end,
        )
        > 0
    ]


def _strongest_word(text: str) -> str:
    priority = (
        "wrong",
        "mistake",
        "truth",
        "why",
        "finally",
        "changed",
        "fail",
        "secret",
        "problem",
        "because",
    )
    low_words = {word.strip(".,!?").lower(): word.strip(".,!?") for word in text.split()}
    for cue in priority:
        if cue in low_words:
            return low_words[cue]
    words = [word.strip(".,!?") for word in text.split() if len(word.strip(".,!?")) >= 5]
    return words[0] if words else ""


def _retention_question(low_text: str, setup: str) -> str:
    if "why" in low_text:
        return "Why is this true?"
    if "how" in low_text:
        return "How does this work?"
    if any(cue in low_text for cue in ("mistake", "wrong", "problem")):
        return "What is the fix?"
    if setup:
        return f"What happens after: {setup[:48]}?"
    return "What is the payoff?"


def _emotion_profile(text: str) -> dict[str, Any]:
    low = text.lower()
    cues = {
        "tension": ("problem", "risk", "wrong", "mistake", "pressure", "failed"),
        "surprise": ("turns out", "unexpected", "nobody", "no way", "actually"),
        "aspiration": ("dream", "freedom", "better", "win", "changed"),
        "relief": ("fixed", "finally", "solved", "learned", "worked"),
    }
    scores = {
        name: S.round3(min(1.0, 0.34 * sum(1 for cue in cue_list if cue in low)))
        for name, cue_list in cues.items()
    }
    dominant = max(scores, key=lambda name: scores[name]) if any(scores.values()) else "neutral"
    return {"dominant": dominant, "scores": scores}


def _hook_overlay(text: str, category: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    if category == "wait_for_it":
        return "Wait for it..."
    if category == "nobody_expected":
        return "Nobody expected this"
    if category == "this_changed_everything":
        return "This changed everything"
    if category == "mistake_warning":
        return "Stop making this mistake"
    if category == "unexpected_truth":
        return "Nobody tells you this"
    if category == "contrarian_statement":
        return "Most people get this wrong"
    if category == "tension_line":
        return "This is the tense part"
    return cleaned[:72]

"""Pure, explainable helpers for the Optimization Engine.

Deterministic, inspectable functions - not a black box. They derive a music
brief from upstream emotional/pacing signals, measure caption reading speed,
re-balance caption line breaks, extract keywords/hashtags from the real
transcript, build standards-compliant subtitle files (SRT/VTT) from real caption
events, and aggregate quality from real signals. Everything here is transparent
so it can be unit-tested and audited; nothing invents an enhancement - a value
only exists when a real upstream signal supports it, and anything that cannot be
determined is left to the caller to record as ``UNKNOWN``.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from olympus.domain.contracts.music import MusicQuery

# Reading-speed thresholds (characters per second). ~17 CPS is a widely-used
# subtitle comfort target; above ~20 CPS captions are hard to read in time.
COMFORTABLE_CPS = 17.0
MAX_CPS = 20.0

_MAX_CAPTION_CHARS_PER_LINE = 21
_WORD_RE = re.compile(r"[a-zA-Z']+")

# Common English stopwords excluded from keyword/hashtag extraction.
_STOPWORD_TEXT = (
    "the a an and or but if then than that this these those of to in on at for with from by "
    "as is are was were be been being it its it's i you he she they we me my your our their "
    "them his her so do does did done not no yes can will would could should have has had "
    "about into over under just like really very much many more most some any all out up down "
    "off again once here there what when where why how who whom which while because there's "
    "i'm you're we're they're going get got make made one two three also too only own same "
    "other new know think see say said thing things"
)
_STOPWORDS: frozenset[str] = frozenset(_STOPWORD_TEXT.split())

# Conservative, unambiguous emoji cues (keyword -> emoji). Used only as optional
# suggestions, never auto-applied; kept small to avoid noise/misfires.
_EMOJI_CUES: dict[str, str] = {
    "money": "\U0001f4b0",
    "fire": "\U0001f525",
    "idea": "\U0001f4a1",
    "warning": "\u26a0\ufe0f",
    "time": "\u23f0",
    "growth": "\U0001f4c8",
    "love": "\u2764\ufe0f",
    "win": "\U0001f3c6",
}


# -- coercion ----------------------------------------------------------------
def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_float(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def round3(value: float) -> float:
    return round(value, 3)


# -- reading speed -----------------------------------------------------------
def reading_speed_cps(text: str, duration: float) -> float | None:
    """Characters-per-second for a caption, or ``None`` if duration is unusable."""

    if duration <= 0:
        return None
    return round3(len(text.strip()) / duration)


def caption_speed_rating(cps: float | None) -> str:
    """Classify a caption's reading speed honestly (``unknown`` when no CPS)."""

    if cps is None:
        return "unknown"
    if cps <= COMFORTABLE_CPS:
        return "comfortable"
    if cps <= MAX_CPS:
        return "brisk"
    return "too_fast"


# -- caption line breaks -----------------------------------------------------
def balance_line_breaks(
    text: str, max_chars_per_line: int = _MAX_CAPTION_CHARS_PER_LINE
) -> list[str]:
    """Re-flow a caption into balanced lines (1-2) for vertical legibility.

    Greedy packing that prefers two near-even lines over one long line; returns a
    single line when the text fits comfortably. Deterministic and reversible.
    """

    words = text.split()
    if not words:
        return []
    if len(text) <= max_chars_per_line:
        return [text.strip()]
    # Two-line balance: find the split point closest to the middle.
    target = len(text) / 2
    best_idx, best_delta = 1, float("inf")
    running = 0
    for i, word in enumerate(words[:-1], start=1):
        running += len(word) + 1
        delta = abs(running - target)
        if delta < best_delta:
            best_delta, best_idx = delta, i
    line1 = " ".join(words[:best_idx]).strip()
    line2 = " ".join(words[best_idx:]).strip()
    return [line1, line2] if line2 else [line1]


# -- keyword & hashtag extraction --------------------------------------------
def extract_keywords(texts: list[str], *, limit: int = 12) -> list[tuple[str, int]]:
    """Return the most frequent meaningful words across ``texts`` (word, count)."""

    counter: Counter[str] = Counter()
    for text in texts:
        for token in _WORD_RE.findall(text.lower()):
            if len(token) > 3 and token not in _STOPWORDS:
                counter[token] += 1
    return counter.most_common(limit)


def to_hashtags(keywords: list[str], *, limit: int = 10) -> list[str]:
    """Convert keywords into deduplicated hashtags (alphanumeric, lowercased)."""

    seen: set[str] = set()
    tags: list[str] = []
    for word in keywords:
        cleaned = re.sub(r"[^a-z0-9]", "", word.lower())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            tags.append(f"#{cleaned}")
        if len(tags) >= limit:
            break
    return tags


def suggest_emoji(text: str) -> str | None:
    """Return a conservative emoji cue for a caption, or ``None`` (never forced)."""

    low = text.lower()
    for cue, emoji in _EMOJI_CUES.items():
        if cue in low:
            return emoji
    return None


# -- subtitle file generation ------------------------------------------------
def _ts_srt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = round((seconds - int(seconds)) * 1000)
    if ms == 1000:  # rounding guard
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_vtt(seconds: float) -> str:
    return _ts_srt(seconds).replace(",", ".")


def build_srt(captions: list[dict[str, Any]]) -> str:
    """Build a standards-compliant SRT document from real caption events."""

    ordered = sorted(captions, key=lambda c: as_float(c.get("start")))
    lines: list[str] = []
    for i, cap in enumerate(ordered, start=1):
        text = as_str(cap.get("text")).strip()
        if not text:
            continue
        start, end = as_float(cap.get("start")), as_float(cap.get("end"))
        lines.append(str(i))
        lines.append(f"{_ts_srt(start)} --> {_ts_srt(end)}")
        lines.append("\n".join(balance_line_breaks(text)))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_vtt(captions: list[dict[str, Any]]) -> str:
    """Build a standards-compliant WebVTT document from real caption events."""

    ordered = sorted(captions, key=lambda c: as_float(c.get("start")))
    lines: list[str] = ["WEBVTT", ""]
    for cap in ordered:
        text = as_str(cap.get("text")).strip()
        if not text:
            continue
        start, end = as_float(cap.get("start")), as_float(cap.get("end"))
        lines.append(f"{_ts_vtt(start)} --> {_ts_vtt(end)}")
        lines.append("\n".join(balance_line_breaks(text)))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# -- music brief -------------------------------------------------------------
def derive_music_query(
    *, moods: list[str], energy: float | None, pacing: str | None, platform: str | None
) -> MusicQuery:
    """Translate upstream emotional/pacing signals into a provider-agnostic brief.

    Pacing maps to a target tempo band deterministically; energy passes through.
    Anything unknown is left as ``None`` so providers degrade rather than guess.
    """

    bpm_by_pacing = {"fast": 130, "medium": 105, "slow": 85}
    target_bpm = bpm_by_pacing.get((pacing or "").lower())
    # When energy is unknown but pacing is known, derive a coarse energy hint.
    if energy is None and pacing:
        energy = {"fast": 0.8, "medium": 0.55, "slow": 0.35}.get(pacing.lower())
    return MusicQuery(
        mood=tuple(dict.fromkeys(m.lower() for m in moods if m)),
        energy=energy,
        target_bpm=target_bpm,
        genres=(),
        platform=platform,
    )


# -- quality aggregation -----------------------------------------------------
def aggregate_quality(dimensions: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate graded dimensions into an overall score (UNKNOWN dims excluded).

    Each dimension has ``score`` (0..1 or ``None`` for UNKNOWN) and ``confidence``.
    The overall score is the confidence-weighted mean of the *graded* dimensions;
    UNKNOWN dimensions are reported separately and never silently treated as zero.
    """

    graded = [d for d in dimensions if d.get("score") is not None]
    unknown = [d["dimension"] for d in dimensions if d.get("score") is None]
    if not graded:
        return {
            "overall_score": None,
            "graded_count": 0,
            "unknown_dimensions": unknown,
            "note": "No dimension could be graded from available evidence; overall "
            "quality is UNKNOWN rather than fabricated.",
        }
    weight_sum = sum(as_float(d.get("confidence"), 0.0) or 0.0 for d in graded)
    if weight_sum <= 0:
        overall = round3(sum(as_float(d.get("score")) for d in graded) / len(graded))
    else:
        overall = round3(
            sum(as_float(d.get("score")) * (as_float(d.get("confidence")) or 0.0) for d in graded)
            / weight_sum
        )
    return {
        "overall_score": overall,
        "graded_count": len(graded),
        "unknown_dimensions": unknown,
        "note": "Confidence-weighted mean of graded dimensions only. UNKNOWN "
        "dimensions (needing the rendered media or a model) are excluded, not zeroed.",
    }

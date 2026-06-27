"""Pure, explainable helpers for the Editing Engine.

Deterministic, inspectable functions - not a black box. They convert upstream
signals (in source time) into **clip-relative** timeline events, split captions
at linguistic boundaries, detect filler/silence from the real transcript, build
typed events/markers, and validate timeline continuity. Everything here is
transparent so it can be unit-tested and audited; nothing invents an edit - an
event only exists when a real upstream signal supports it, and anything that
cannot be determined is recorded as ``UNKNOWN`` rather than guessed.

All event times are clip-relative seconds (0 = clip start). The mapping back to
the source video is preserved on the base clip event so a future Editing/Render
engine can execute the timeline exactly.
"""

from __future__ import annotations

import itertools
import re
from typing import Any

# Filler / hedge tokens (single words) the speech-cleanup stage identifies.
FILLER_WORDS: frozenset[str] = frozenset(
    {"um", "umm", "uh", "uhh", "uhm", "hmm", "mm", "mmm", "er", "erm", "ah", "eh"}
)
# Hedge phrases identified as soft filler (substring match, lowercased).
FILLER_PHRASES: tuple[str, ...] = (
    "you know",
    "i mean",
    "sort of",
    "kind of",
    "i guess",
)

_WORD_RE = re.compile(r"[a-zA-Z']+")
_CLAUSE_RE = re.compile(r"[^.!?;,]+[.!?;,]?")
_MAX_CAPTION_WORDS = 7
_MAX_CAPTION_CHARS = 42


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


def ms(value: float) -> int:
    return round(value * 1000)


# -- event / marker builders -------------------------------------------------
def event(
    kind: str,
    start: float,
    end: float,
    *,
    reason: str,
    confidence: float | None,
    evidence: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a timestamped timeline event (clip-relative seconds).

    ``confidence`` may be ``None`` to honestly signal UNKNOWN. Every event has a
    stable id, a type, start/end/duration, a reason, and supporting evidence.
    """

    s, e = round3(start), round3(max(start, end))
    return {
        "id": f"{kind}_{ms(s)}_{ms(e)}",
        "type": kind,
        "start": s,
        "end": e,
        "duration": round3(e - s),
        "reason": reason,
        "confidence": confidence,
        "evidence": evidence or [],
        **extra,
    }


def marker(
    kind: str,
    at: float,
    *,
    reason: str,
    confidence: float | None,
    evidence: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a point-in-time marker (zero-duration event)."""

    return event(kind, at, at, reason=reason, confidence=confidence, evidence=evidence, **extra)


# -- transcript localization -------------------------------------------------
def clip_segments(
    segments: list[dict[str, Any]], clip_start: float, clip_end: float
) -> list[dict[str, Any]]:
    """Transcript segments overlapping [clip_start, clip_end], clip-relative.

    Each returned segment has clip-relative ``start``/``end`` (clamped to the
    clip), plus ``text``, ``speaker``, and the original ``source_start``/
    ``source_end`` for exact reproducibility.
    """

    out: list[dict[str, Any]] = []
    for seg in segments:
        s = as_float(seg.get("start"))
        e = as_float(seg.get("end")) if seg.get("end") is not None else s
        if e <= clip_start or s >= clip_end:
            continue
        rel_start = round3(max(0.0, s - clip_start))
        rel_end = round3(min(clip_end, e) - clip_start)
        if rel_end <= rel_start:
            continue
        out.append(
            {
                "start": rel_start,
                "end": rel_end,
                "text": as_str(seg.get("text")),
                "speaker": as_str(seg.get("speaker")),
                "source_start": round3(s),
                "source_end": round3(e),
            }
        )
    return out


def to_clip_relative(timestamp: float, clip_start: float, clip_duration: float) -> float | None:
    """Map a source-time timestamp into the clip window, or None if outside it."""

    rel = timestamp - clip_start
    if rel < -0.05 or rel > clip_duration + 0.05:
        return None
    return round3(clamp(rel, 0.0, clip_duration))


# -- linguistic caption splitting -------------------------------------------
def split_caption(text: str) -> list[str]:
    """Split a transcript line into caption-sized chunks at clause boundaries.

    Not a fixed time slice: splits at punctuation/clauses first, then packs words
    up to a readable length. Returns the original (trimmed) text as one chunk when
    it is already short enough.
    """

    text = " ".join(text.split())
    if not text:
        return []
    clauses = [c.strip() for c in _CLAUSE_RE.findall(text) if c.strip()]
    chunks: list[str] = []
    for clause in clauses or [text]:
        words = clause.split()
        current: list[str] = []
        for word in words:
            tentative = [*current, word]
            if len(tentative) > _MAX_CAPTION_WORDS or len(" ".join(tentative)) > _MAX_CAPTION_CHARS:
                if current:
                    chunks.append(" ".join(current))
                current = [word]
            else:
                current = tentative
        if current:
            chunks.append(" ".join(current))
    return chunks


def distribute_timing(chunks: list[str], start: float, end: float) -> list[dict[str, Any]]:
    """Assign each caption chunk a time slice proportional to its word count."""

    if not chunks:
        return []
    weights = [max(1, len(c.split())) for c in chunks]
    total_w = sum(weights)
    span = max(0.0, end - start)
    out: list[dict[str, Any]] = []
    cursor = start
    for chunk, w in zip(chunks, weights, strict=True):
        slice_dur = span * (w / total_w)
        seg_end = min(end, cursor + slice_dur)
        out.append({"text": chunk, "start": round3(cursor), "end": round3(seg_end)})
        cursor = seg_end
    if out:
        out[-1]["end"] = round3(end)
    return out


# -- speech-cleanup detection ------------------------------------------------
def find_fillers(text: str) -> list[str]:
    """Return filler tokens/phrases present in ``text`` (identification only)."""

    low = f" {text.lower()} "
    found = [w for w in _WORD_RE.findall(text.lower()) if w in FILLER_WORDS]
    found += [p for p in FILLER_PHRASES if f" {p} " in low]
    return found


def find_repeated_words(text: str) -> list[str]:
    """Return immediately-repeated content words (e.g. 'the the')."""

    tokens = _WORD_RE.findall(text.lower())
    repeats: list[str] = []
    for a, b in itertools.pairwise(tokens):
        if a == b and len(a) > 2:
            repeats.append(a)
    return repeats


def gaps_between(
    segments: list[dict[str, Any]], clip_duration: float, *, min_gap: float
) -> list[dict[str, Any]]:
    """Return silence gaps (clip-relative) between consecutive clip segments.

    Silence is *inferred* from transcript timing - it is not measured from the
    audio waveform (which would require an audio model). Callers must label its
    confidence accordingly. Includes lead-in and tail-out silence.
    """

    gaps: list[dict[str, Any]] = []
    cursor = 0.0
    for seg in sorted(segments, key=lambda s: as_float(s.get("start"))):
        s = as_float(seg.get("start"))
        if s - cursor >= min_gap:
            gaps.append({"start": round3(cursor), "end": round3(s)})
        cursor = max(cursor, as_float(seg.get("end")))
    if clip_duration - cursor >= min_gap:
        gaps.append({"start": round3(cursor), "end": round3(clip_duration)})
    return gaps


# -- validation --------------------------------------------------------------
def intervals_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two events overlap in time (touching endpoints do not count)."""

    return max(as_float(a.get("start")), as_float(b.get("start"))) < min(
        as_float(a.get("end")), as_float(b.get("end"))
    )


def find_overlaps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return overlapping event pairs (used to validate exclusive tracks)."""

    issues: list[dict[str, Any]] = []
    ordered = sorted(events, key=lambda e: as_float(e.get("start")))
    for a, b in itertools.pairwise(ordered):
        if intervals_overlap(a, b):
            issues.append(
                {"a": a.get("id"), "b": b.get("id"), "detail": "overlapping caption events"}
            )
    return issues


def validate_event_bounds(events: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    """Return issues for events with broken or out-of-bounds timestamps."""

    issues: list[dict[str, Any]] = []
    for ev in events:
        s, e = as_float(ev.get("start")), as_float(ev.get("end"))
        if e < s:
            issues.append({"event": ev.get("id"), "detail": "end precedes start"})
        if s < -0.001 or e > duration + 0.05:
            issues.append({"event": ev.get("id"), "detail": "event falls outside the clip"})
    return issues

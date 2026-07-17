"""Repair planned clip boundaries before any clip-relative edit is created."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from olympus.editing.timeline_contracts import ClipSourceWindowV1

_START_PREROLL_SECONDS = 0.25
_END_POSTROLL_SECONDS = 0.45
_FALLBACK_POSTROLL_SECONDS = 0.5
_MAX_START_REPAIR_SECONDS = 0.8
_MAX_END_REPAIR_SECONDS = 1.0
_MIN_TAIL_SECONDS = 0.3
_EPSILON = 0.001


def _number(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


@dataclass(frozen=True, slots=True)
class _Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class _Segment:
    text: str
    start: float
    end: float


def _transcript_words(segments: list[dict[str, Any]]) -> list[_Word]:
    words: list[_Word] = []
    for segment in segments:
        for item in _items(segment.get("words")):
            start = _number(item.get("start"), -1.0)
            end = _number(item.get("end"), -1.0)
            text = str(item.get("word") or item.get("text") or "").strip()
            if text and start >= 0.0 and end > start:
                words.append(_Word(text=text, start=start, end=end))
    return sorted(words, key=lambda item: (item.start, item.end))


def _transcript_segments(segments: list[dict[str, Any]]) -> list[_Segment]:
    output: list[_Segment] = []
    for item in segments:
        start = _number(item.get("start"), -1.0)
        end = _number(item.get("end"), -1.0)
        if start >= 0.0 and end > start:
            output.append(_Segment(str(item.get("text") or "").strip(), start, end))
    return sorted(output, key=lambda item: (item.start, item.end))


def _metadata_end_hint(*values: dict[str, Any] | None) -> float | None:
    paths = (
        ("planning_story_integration", "story_recommended_end"),
        ("planning_story_integration", "final_end"),
        ("story_v2_guidance", "recommended_end"),
        ("story_v2_guidance", "payoff_end"),
        ("boundary_repair", "recommended_end"),
        ("payoff", "end"),
    )
    hints: list[float] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        for parent, child in paths:
            nested = value.get(parent)
            if isinstance(nested, dict) and isinstance(nested.get(child), int | float):
                hints.append(float(nested[child]))
        if isinstance(value.get("recommended_end"), int | float):
            hints.append(float(value["recommended_end"]))
    return max(hints) if hints else None


def _repair_start(
    requested_start: float,
    words: list[_Word],
    segments: list[_Segment],
) -> tuple[float, str]:
    containing_word = next(
        (word for word in words if word.start + _EPSILON < requested_start < word.end - _EPSILON),
        None,
    )
    if containing_word is not None:
        repaired = max(0.0, containing_word.start - _START_PREROLL_SECONDS)
        return repaired, "moved before the first clipped word with safe preroll"

    containing_segment = next(
        (
            segment
            for segment in segments
            if segment.start + _EPSILON < requested_start < segment.end - _EPSILON
            and requested_start - segment.start <= _MAX_START_REPAIR_SECONDS
        ),
        None,
    )
    if containing_segment is not None:
        repaired = max(
            0.0,
            requested_start - _MAX_START_REPAIR_SECONDS,
            containing_segment.start - _START_PREROLL_SECONDS,
        )
        return repaired, "moved to a nearby transcript-segment boundary with safe preroll"

    return requested_start, "planning start was already a safe speech boundary"


def _continuous_words_after(words: list[_Word], requested_end: float) -> list[_Word]:
    following = [
        word
        for word in words
        if requested_end - _EPSILON <= word.start <= requested_end + _MAX_END_REPAIR_SECONDS
    ]
    if not following or following[0].start - requested_end > 0.2:
        return []
    selected: list[_Word] = []
    previous_end = requested_end
    for word in following:
        if word.start - previous_end > 0.3:
            break
        if word.end > requested_end + _MAX_END_REPAIR_SECONDS:
            break
        selected.append(word)
        previous_end = word.end
        if word.text.rstrip().endswith((".", "!", "?")):
            break
    return selected


def _repair_end(
    requested_end: float,
    words: list[_Word],
    segments: list[_Segment],
    metadata_hint: float | None,
) -> tuple[float, float | None, str]:
    target = requested_end
    final_spoken_end: float | None = None
    reasons: list[str] = []
    containing_word = next(
        (word for word in words if word.start + _EPSILON < requested_end < word.end - _EPSILON),
        None,
    )
    if containing_word is not None:
        final_spoken_end = containing_word.end
        target = max(target, containing_word.end + _END_POSTROLL_SECONDS)
        reasons.append("extended through a word cut by the planned end")
    elif words:
        preceding = [word for word in words if word.end <= requested_end + _EPSILON]
        last_word = preceding[-1] if preceding else None
        following = _continuous_words_after(words, requested_end)
        if following:
            final_spoken_end = following[-1].end
            target = max(target, final_spoken_end + _END_POSTROLL_SECONDS)
            reasons.append("extended through continuous speech near the planned end")
        elif last_word is not None and requested_end - last_word.end < _MIN_TAIL_SECONDS:
            final_spoken_end = last_word.end
            target = max(target, last_word.end + _END_POSTROLL_SECONDS)
            reasons.append("added breathing room after the final spoken word")
    elif segments:
        containing_segment = next(
            (
                segment
                for segment in segments
                if segment.start < requested_end < segment.end - _EPSILON
            ),
            None,
        )
        preceding_segments = [
            segment for segment in segments if segment.end <= requested_end + _EPSILON
        ]
        last_segment = preceding_segments[-1] if preceding_segments else None
        if containing_segment is not None:
            final_spoken_end = containing_segment.end
            if containing_segment.end <= requested_end + _MAX_END_REPAIR_SECONDS:
                target = max(target, containing_segment.end + _END_POSTROLL_SECONDS)
                reasons.append("extended through the active transcript segment")
            else:
                target = max(target, requested_end + _FALLBACK_POSTROLL_SECONDS)
                reasons.append(
                    "added conservative postroll because segment-only timing could not "
                    "safely finish nearby speech"
                )
        elif last_segment is not None and requested_end - last_segment.end < _MIN_TAIL_SECONDS:
            final_spoken_end = last_segment.end
            target = max(target, last_segment.end + _END_POSTROLL_SECONDS)
            reasons.append("added breathing room after the final transcript segment")
    else:
        target = requested_end + _FALLBACK_POSTROLL_SECONDS
        reasons.append("added conservative postroll because transcript timing was unavailable")

    if metadata_hint is not None and requested_end < metadata_hint <= requested_end + 1.5:
        final_spoken_end = max(final_spoken_end or 0.0, metadata_hint)
        target = max(target, metadata_hint + _END_POSTROLL_SECONDS)
        reasons.append("preserved the nearby story/payoff boundary")
    return target, final_spoken_end, "; ".join(reasons) or "planning end already included safe tail"


def repair_clip_source_window(
    *,
    project_id: str | None,
    clip_id: str,
    requested_start_seconds: float,
    requested_end_seconds: float,
    transcript_segments: list[dict[str, Any]] | None = None,
    source_duration_seconds: float | None = None,
    planning_metadata: dict[str, Any] | None = None,
    story_metadata: dict[str, Any] | None = None,
) -> ClipSourceWindowV1:
    """Return the final source window that all editing and rendering must use."""

    warnings: list[str] = []
    requested_start = max(0.0, _number(requested_start_seconds))
    requested_end = max(0.0, _number(requested_end_seconds))
    working_start = requested_start
    working_end = requested_end
    source_duration = (
        max(0.0, _number(source_duration_seconds))
        if source_duration_seconds is not None
        else None
    )
    if source_duration is not None:
        working_start = min(working_start, source_duration)
    if working_end <= working_start:
        working_end = working_start + 0.1
        warnings.append("Planning supplied a non-positive clip window; a minimum window was used.")

    segments = _transcript_segments(transcript_segments or [])
    words = _transcript_words(transcript_segments or [])
    repaired_start, start_reason = _repair_start(working_start, words, segments)
    repaired_end, final_spoken_end, end_reason = _repair_end(
        working_end,
        words,
        segments,
        _metadata_end_hint(planning_metadata, story_metadata),
    )

    if source_duration is not None:
        if repaired_end > source_duration + _EPSILON:
            warnings.append("Boundary repair was clamped to the source duration.")
        repaired_end = min(repaired_end, source_duration)
        repaired_start = min(repaired_start, max(0.0, repaired_end - 0.1))
    if repaired_end <= repaired_start:
        repaired_end = repaired_start + 0.1
        if source_duration is not None:
            repaired_end = min(repaired_end, source_duration)

    if (
        final_spoken_end is not None
        and repaired_end + _EPSILON < final_spoken_end + _MIN_TAIL_SECONDS
    ):
        warnings.append(
            "Abrupt end remains unavoidable because the available source or timing "
            "repair budget cannot provide safe final-word postroll."
        )
    elif not words and not segments and repaired_end + _EPSILON < working_end + _MIN_TAIL_SECONDS:
        warnings.append(
            "Abrupt end remains possible because transcript timing was unavailable and source "
            "duration prevented conservative postroll."
        )

    preroll = max(0.0, requested_start - repaired_start)
    postroll = max(0.0, repaired_end - requested_end)
    applied = abs(repaired_start - requested_start) > _EPSILON or abs(
        repaired_end - requested_end
    ) > _EPSILON
    return ClipSourceWindowV1(
        project_id=project_id,
        clip_id=clip_id,
        requested_start_seconds=requested_start,
        requested_end_seconds=requested_end,
        repaired_start_seconds=repaired_start,
        repaired_end_seconds=repaired_end,
        duration_seconds=repaired_end - repaired_start,
        preroll_seconds=preroll,
        postroll_seconds=postroll,
        boundary_repair_applied=applied,
        start_reason=start_reason,
        end_reason=end_reason,
        warnings=tuple(warnings),
    )


def validate_clip_source_window(
    window: ClipSourceWindowV1,
    transcript_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate that repaired boundaries do not omit a word crossed by the request."""

    warnings = list(window.warnings)
    words = _transcript_words(transcript_segments or [])
    missing_words = [
        word.text
        for word in words
        if word.start < window.requested_end_seconds < word.end
        and window.repaired_end_seconds < word.end - _EPSILON
    ]
    if missing_words:
        warnings.append("Repaired end still omits the final word: " + ", ".join(missing_words))
    starts_mid_word = any(
        word.start + _EPSILON
        < window.repaired_start_seconds
        < word.end - _EPSILON
        for word in words
    )
    if starts_mid_word:
        warnings.append("Repaired start still intersects a spoken word.")
    return {
        "passed": not missing_words and not starts_mid_word,
        "missing_final_words": missing_words,
        "starts_mid_word": starts_mid_word,
        "warnings": list(dict.fromkeys(warnings)),
    }

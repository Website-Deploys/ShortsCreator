"""Deterministic editorial boundary scoring before technical A/V repair."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

from olympus.planning import scoring as S  # noqa: N812

_EPSILON = 0.05
_START_SEARCH_SECONDS = 8.0
_END_SEARCH_SECONDS = 12.0
_CONNECTIVE_PREFIXES = ("and ", "but ", "because ", "so ", "then ", "this ", "that ")
_FILLER_PREFIXES = ("um ", "uh ", "like ", "you know ", "honestly, um")


def _number(value: object, default: float = 0.0) -> float:
    if not isinstance(value, int | float):
        return default
    parsed = float(value)
    return parsed if math.isfinite(parsed) else default


def _optional_number(value: object) -> float | None:
    if not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _bounded(value: object) -> float:
    return round(S.clamp01(_number(value)), 3)


def _window(value: object) -> dict[str, float]:
    data = S.as_dict(value)
    start = max(0.0, _number(data.get("start_seconds"), _number(data.get("start"))))
    end = max(start, _number(data.get("end_seconds"), _number(data.get("end"), start)))
    return {"start_seconds": round(start, 3), "end_seconds": round(end, 3)}


@dataclass(frozen=True, slots=True)
class BoundaryQualityDecisionV1:
    """Auditable recommendation decision for one planning candidate."""

    decision_id: str
    clip_id: str
    original_window: dict[str, float]
    recommended_window: dict[str, float]
    changes: tuple[str, ...] = field(default_factory=tuple)
    reason: str = "candidate boundaries retained"
    confidence: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "original_window", _window(self.original_window))
        object.__setattr__(self, "recommended_window", _window(self.recommended_window))
        object.__setattr__(self, "changes", tuple(dict.fromkeys(map(str, self.changes))))
        object.__setattr__(self, "warnings", tuple(dict.fromkeys(map(str, self.warnings))))
        object.__setattr__(self, "confidence", _bounded(self.confidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "1",
            "decision_id": self.decision_id,
            "clip_id": self.clip_id,
            "original_window": dict(self.original_window),
            "recommended_window": dict(self.recommended_window),
            "changes": list(self.changes),
            "reason": self.reason,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BoundaryQualityDecisionV1:
        return cls(
            decision_id=str(value.get("decision_id") or ""),
            clip_id=str(value.get("clip_id") or ""),
            original_window=_window(value.get("original_window")),
            recommended_window=_window(value.get("recommended_window")),
            changes=tuple(str(item) for item in S.as_list(value.get("changes"))),
            reason=str(value.get("reason") or "candidate boundaries retained"),
            confidence=_number(value.get("confidence")),
            warnings=tuple(str(item) for item in S.as_list(value.get("warnings"))),
        )


@dataclass(frozen=True, slots=True)
class ClipBoundaryQualityV1:
    """Editorial boundary quality scores and the recommended source window."""

    project_id: str | None
    clip_id: str
    requested_start_seconds: float
    requested_end_seconds: float
    recommended_start_seconds: float
    recommended_end_seconds: float
    hook_start_seconds: float | None
    payoff_end_seconds: float | None
    context_start_seconds: float | None
    quality_score: float
    hook_score: float
    context_score: float
    payoff_score: float
    completeness_score: float
    pacing_score: float
    duplicate_risk: float
    abrupt_start_risk: float
    abrupt_end_risk: float
    dead_air_risk: float
    drag_after_payoff_risk: float
    boundary_confidence: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    decision: BoundaryQualityDecisionV1 | None = None

    def __post_init__(self) -> None:
        requested_start = max(0.0, _number(self.requested_start_seconds))
        requested_end = max(requested_start, _number(self.requested_end_seconds))
        recommended_start = max(0.0, _number(self.recommended_start_seconds))
        recommended_end = max(recommended_start, _number(self.recommended_end_seconds))
        for name, value in (
            ("requested_start_seconds", requested_start),
            ("requested_end_seconds", requested_end),
            ("recommended_start_seconds", recommended_start),
            ("recommended_end_seconds", recommended_end),
        ):
            object.__setattr__(self, name, round(value, 3))
        for name in (
            "quality_score",
            "hook_score",
            "context_score",
            "payoff_score",
            "completeness_score",
            "pacing_score",
            "duplicate_risk",
            "abrupt_start_risk",
            "abrupt_end_risk",
            "dead_air_risk",
            "drag_after_payoff_risk",
            "boundary_confidence",
        ):
            object.__setattr__(self, name, _bounded(getattr(self, name)))
        for name in ("hook_start_seconds", "payoff_end_seconds", "context_start_seconds"):
            optional_value = _optional_number(getattr(self, name))
            object.__setattr__(
                self,
                name,
                round(optional_value, 3) if optional_value is not None else None,
            )
        object.__setattr__(self, "reasons", tuple(dict.fromkeys(map(str, self.reasons))))
        object.__setattr__(self, "warnings", tuple(dict.fromkeys(map(str, self.warnings))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "1",
            "project_id": self.project_id,
            "clip_id": self.clip_id,
            "requested_start_seconds": self.requested_start_seconds,
            "requested_end_seconds": self.requested_end_seconds,
            "recommended_start_seconds": self.recommended_start_seconds,
            "recommended_end_seconds": self.recommended_end_seconds,
            "hook_start_seconds": self.hook_start_seconds,
            "payoff_end_seconds": self.payoff_end_seconds,
            "context_start_seconds": self.context_start_seconds,
            "quality_score": self.quality_score,
            "hook_score": self.hook_score,
            "context_score": self.context_score,
            "payoff_score": self.payoff_score,
            "completeness_score": self.completeness_score,
            "pacing_score": self.pacing_score,
            "duplicate_risk": self.duplicate_risk,
            "abrupt_start_risk": self.abrupt_start_risk,
            "abrupt_end_risk": self.abrupt_end_risk,
            "dead_air_risk": self.dead_air_risk,
            "drag_after_payoff_risk": self.drag_after_payoff_risk,
            "boundary_confidence": self.boundary_confidence,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "decision": self.decision.to_dict() if self.decision else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ClipBoundaryQualityV1:
        decision = S.as_dict(value.get("decision"))
        return cls(
            project_id=str(value["project_id"]) if value.get("project_id") is not None else None,
            clip_id=str(value.get("clip_id") or ""),
            requested_start_seconds=_number(value.get("requested_start_seconds")),
            requested_end_seconds=_number(value.get("requested_end_seconds")),
            recommended_start_seconds=_number(value.get("recommended_start_seconds")),
            recommended_end_seconds=_number(value.get("recommended_end_seconds")),
            hook_start_seconds=_optional_number(value.get("hook_start_seconds")),
            payoff_end_seconds=_optional_number(value.get("payoff_end_seconds")),
            context_start_seconds=_optional_number(value.get("context_start_seconds")),
            quality_score=_number(value.get("quality_score")),
            hook_score=_number(value.get("hook_score")),
            context_score=_number(value.get("context_score")),
            payoff_score=_number(value.get("payoff_score")),
            completeness_score=_number(value.get("completeness_score")),
            pacing_score=_number(value.get("pacing_score")),
            duplicate_risk=_number(value.get("duplicate_risk")),
            abrupt_start_risk=_number(value.get("abrupt_start_risk")),
            abrupt_end_risk=_number(value.get("abrupt_end_risk")),
            dead_air_risk=_number(value.get("dead_air_risk")),
            drag_after_payoff_risk=_number(value.get("drag_after_payoff_risk")),
            boundary_confidence=_number(value.get("boundary_confidence")),
            reasons=tuple(str(item) for item in S.as_list(value.get("reasons"))),
            warnings=tuple(str(item) for item in S.as_list(value.get("warnings"))),
            decision=BoundaryQualityDecisionV1.from_dict(decision) if decision else None,
        )


def recommend_clip_boundaries(
    candidate: dict[str, Any],
    context: dict[str, Any],
) -> ClipBoundaryQualityV1:
    """Score and recommend editorial boundaries without doing technical trim repair."""

    clip_id = str(
        candidate.get("clip_id")
        or candidate.get("candidate_id")
        or candidate.get("id")
        or ""
    )
    requested_start = max(
        0.0,
        _number(candidate.get("requested_start_seconds"), _number(candidate.get("raw_start"))),
    )
    requested_end = max(
        requested_start,
        _number(candidate.get("requested_end_seconds"), _number(candidate.get("raw_end"))),
    )
    start = max(0.0, _number(candidate.get("start"), requested_start))
    end = max(start, _number(candidate.get("end"), requested_end))
    source_duration_value = _number(context.get("source_duration_seconds"))
    source_duration = source_duration_value if source_duration_value > 0 else end
    minimum_duration = max(0.1, _number(context.get("minimum_duration_seconds"), 8.0))
    maximum_duration = max(minimum_duration, _number(context.get("maximum_duration_seconds"), 75.0))
    segments = _segments(context.get("transcript_segments"))
    words = _words(segments)
    story = S.as_dict(context.get("story_guidance") or candidate.get("story_v2_guidance"))
    hook_start = _hook_start(candidate, context, story, start, end)
    context_start = _context_start(candidate, context, story, start)
    payoff_end = _payoff_end(candidate, context, story, segments, start, end)
    story_confidence = _story_confidence(candidate, context, story)
    story_completeness = _first_score(
        story.get("completeness_score"),
        candidate.get("story_completion_score"),
        S.as_dict(S.as_dict(candidate.get("v2_candidate_metadata")).get("storytelling")).get(
            "score"
        ),
    )
    context_risk = _first_score(
        story.get("context_risk"),
        candidate.get("context_risk"),
        default=0.18,
    )

    changes: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []
    if not words:
        warnings.append("word-level transcript unavailable; segment timing fallback used")
    if story and story_confidence < 0.45:
        warnings.append("story boundary signal is low confidence; recommendation is conservative")

    first_segment = _first_overlapping_segment(segments, start, end)
    first_text = _text(first_segment).lower().strip() if first_segment else ""
    start_inside = _inside_span(requested_start, words or segments)
    end_inside = _inside_span(requested_end, words or segments)
    starts_after_hook = bool(
        hook_start is not None
        and hook_start + _EPSILON < requested_start
        and requested_start - hook_start <= _START_SEARCH_SECONDS
    )
    missing_context = bool(
        context_start is not None
        and context_start + _EPSILON < requested_start
        and requested_start - context_start <= _START_SEARCH_SECONDS
    ) or context_risk >= 0.55
    ends_before_payoff = bool(
        payoff_end is not None
        and requested_end + _EPSILON < payoff_end
        and payoff_end - requested_end <= _END_SEARCH_SECONDS
    )
    drag_after_payoff = (
        max(0.0, requested_end - payoff_end) if payoff_end is not None else 0.0
    )

    if starts_after_hook and hook_start is not None:
        start = min(start, _segment_start_at_or_before(segments, hook_start, hook_start))
        changes.append("pulled_start_earlier_for_hook")
        reasons.append("original start followed a nearby detected hook")
    if missing_context and context_start is not None and context_start < start:
        start = _segment_start_at_or_before(segments, context_start, context_start)
        changes.append("pulled_start_earlier_for_context")
        reasons.append("added nearby setup required to understand the opening")

    first_segment = _first_overlapping_segment(segments, start, end)
    if first_segment:
        segment_start = _start(first_segment)
        dead_intro = segment_start - start
        if dead_intro > 0.75 and not _signal_between(
            start,
            segment_start,
            hook_start,
            context_start,
        ):
            start = segment_start
            changes.append("trimmed_dead_intro")
            reasons.append("removed transcript-free lead-in before the first meaningful line")
        elif _text(first_segment).lower().strip().startswith(_FILLER_PREFIXES):
            following = _next_segment(segments, first_segment)
            if following and _start(following) - start <= 2.5:
                start = _start(following)
                changes.append("trimmed_filler_intro")
                reasons.append("removed a short filler-only opening")

    if ends_before_payoff and payoff_end is not None:
        end = max(end, _segment_end_at_or_after(segments, payoff_end, payoff_end))
        changes.append("extended_end_for_payoff")
        reasons.append("original end stopped before the nearby payoff landed")
    elif (
        payoff_end is not None
        and drag_after_payoff > 2.5
        and payoff_end - start >= minimum_duration
    ):
        tightened = min(end, _segment_end_at_or_after(segments, payoff_end, payoff_end) + 0.25)
        if tightened + _EPSILON < end:
            end = tightened
            changes.append("tightened_end_after_payoff")
            reasons.append("removed low-value tail after the payoff")
    elif end_inside:
        clean_end = _segment_end_at_or_after(segments, end, end)
        if clean_end - end <= 3.0:
            end = clean_end
            changes.append("extended_end_to_sentence_boundary")
            reasons.append("moved the ending to the enclosing transcript boundary")

    previous_ranges = [
        _window(item) for item in S.as_list(context.get("previous_selected_ranges"))
    ]
    comparison_ranges = [
        _window(item) for item in S.as_list(context.get("overlap_ranges"))
    ]
    risk_ranges = [*previous_ranges, *comparison_ranges]
    duplicate_risk = max(
        (
            _temporal_iou(start, end, item["start_seconds"], item["end_seconds"])
            for item in risk_ranges
        ),
        default=0.0,
    )
    if duplicate_risk >= 0.45:
        shifted = _non_overlapping_start(start, end, previous_ranges, segments, minimum_duration)
        if shifted is not None and (hook_start is None or hook_start >= shifted - _EPSILON):
            start = shifted
            changes.append("shifted_start_to_reduce_duplicate_overlap")
            reasons.append("reduced overlap with an already selected source range")
            duplicate_risk = max(
                (
                    _temporal_iou(
                        start,
                        end,
                        item["start_seconds"],
                        item["end_seconds"],
                    )
                    for item in risk_ranges
                ),
                default=0.0,
            )
        else:
            warnings.append("candidate substantially overlaps another candidate or selected range")
            reasons.append(f"duplicate overlap risk is {duplicate_risk:.2f}")

    start, end = _enforce_duration(
        start,
        end,
        source_duration=source_duration,
        minimum_duration=minimum_duration,
        maximum_duration=maximum_duration,
        payoff_end=payoff_end,
        changes=changes,
        warnings=warnings,
    )

    dead_air_risk = _dead_air_risk(requested_start, requested_end, segments)
    abrupt_start_risk = max(
        0.72 if start_inside else 0.0,
        0.78 if starts_after_hook else 0.0,
        0.82 if missing_context else 0.0,
        0.62 if first_text.startswith(_CONNECTIVE_PREFIXES) else 0.0,
    )
    abrupt_end_risk = max(
        0.78 if end_inside else 0.0,
        0.88 if ends_before_payoff else 0.0,
        0.68 if _ending_is_open(segments, requested_end) else 0.0,
    )
    drag_risk = S.clamp01(drag_after_payoff / 8.0)
    hook_score = _hook_score(start, hook_start, candidate)
    context_score = _context_score(start, context_start, context_risk)
    payoff_score = _payoff_score(end, payoff_end, candidate, story)
    completeness_score = _completeness_score(
        story_completeness,
        hook_score,
        context_score,
        payoff_score,
    )
    pacing_score = _pacing_score(start, end, segments, dead_air_risk)
    boundary_confidence = _boundary_confidence(
        hook_start,
        payoff_end,
        context_start,
        words,
        story_confidence,
    )
    quality_score = S.clamp01(
        0.17 * hook_score
        + 0.16 * context_score
        + 0.21 * payoff_score
        + 0.21 * completeness_score
        + 0.11 * pacing_score
        + 0.07 * (1.0 - abrupt_start_risk)
        + 0.07 * (1.0 - abrupt_end_risk)
        - 0.12 * duplicate_risk
        - 0.05 * drag_risk
    )
    if not reasons:
        reasons.append("candidate already starts with context and ends on a complete thought")
    if hook_start is None:
        warnings.append("hook timestamp unavailable; hook score uses candidate evidence only")
    if payoff_end is None:
        warnings.append("payoff timestamp unavailable; payoff score uses candidate evidence only")

    original_window = {
        "start_seconds": requested_start,
        "end_seconds": requested_end,
    }
    recommended_window = {"start_seconds": start, "end_seconds": end}
    decision_seed = (
        f"{clip_id}:{requested_start:.3f}:{requested_end:.3f}:{start:.3f}:{end:.3f}"
    )
    decision = BoundaryQualityDecisionV1(
        decision_id=f"bqd_{hashlib.sha1(decision_seed.encode('utf-8')).hexdigest()[:16]}",
        clip_id=clip_id,
        original_window=original_window,
        recommended_window=recommended_window,
        changes=tuple(changes),
        reason="; ".join(reasons),
        confidence=boundary_confidence,
        warnings=tuple(warnings),
    )
    return ClipBoundaryQualityV1(
        project_id=str(context["project_id"]) if context.get("project_id") is not None else None,
        clip_id=clip_id,
        requested_start_seconds=requested_start,
        requested_end_seconds=requested_end,
        recommended_start_seconds=start,
        recommended_end_seconds=end,
        hook_start_seconds=hook_start,
        payoff_end_seconds=payoff_end,
        context_start_seconds=context_start,
        quality_score=quality_score,
        hook_score=hook_score,
        context_score=context_score,
        payoff_score=payoff_score,
        completeness_score=completeness_score,
        pacing_score=pacing_score,
        duplicate_risk=duplicate_risk,
        abrupt_start_risk=abrupt_start_risk,
        abrupt_end_risk=abrupt_end_risk,
        dead_air_risk=dead_air_risk,
        drag_after_payoff_risk=drag_risk,
        boundary_confidence=boundary_confidence,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
        decision=decision,
    )


def _segments(value: object) -> list[dict[str, Any]]:
    return sorted(
        [S.as_dict(item) for item in S.as_list(value) if S.as_dict(item)],
        key=_start,
    )


def _words(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for segment in segments:
        for item in S.as_list(segment.get("words")):
            word = S.as_dict(item)
            if _optional_number(word.get("start")) is not None and _optional_number(
                word.get("end")
            ) is not None:
                words.append(word)
    return sorted(words, key=_start)


def _start(item: dict[str, Any]) -> float:
    return max(0.0, _number(item.get("start")))


def _end(item: dict[str, Any]) -> float:
    return max(_start(item), _number(item.get("end"), _start(item)))


def _text(item: dict[str, Any] | None) -> str:
    return str(S.as_dict(item).get("text") or "")


def _first_score(*values: object, default: float = 0.0) -> float:
    for value in values:
        parsed = _optional_number(value)
        if parsed is not None:
            return S.clamp01(parsed)
    return S.clamp01(default)


def _hook_start(
    candidate: dict[str, Any],
    context: dict[str, Any],
    story: dict[str, Any],
    start: float,
    end: float,
) -> float | None:
    hook_signal = S.as_dict(context.get("hook_signal"))
    hook_window = S.as_dict(hook_signal.get("window"))
    hook_candidate = S.as_dict(candidate.get("hook_candidate"))
    values = (
        context.get("hook_start_seconds"),
        candidate.get("hook_start_seconds"),
        hook_candidate.get("timestamp"),
        hook_candidate.get("start"),
        story.get("hook_start_seconds"),
        hook_window.get("start") if hook_signal.get("has_hook") is True else None,
    )
    for value in values:
        parsed = _optional_number(value)
        if parsed is not None and start - _START_SEARCH_SECONDS <= parsed < end:
            return max(0.0, parsed)
    return None


def _context_start(
    candidate: dict[str, Any],
    context: dict[str, Any],
    story: dict[str, Any],
    start: float,
) -> float | None:
    planning = S.as_dict(story.get("planning_guidance"))
    repair = S.as_dict(story.get("boundary_repair"))
    values = (
        context.get("context_start_seconds"),
        candidate.get("context_start_seconds"),
        story.get("context_start_seconds"),
        planning.get("recommended_start"),
        repair.get("repaired_start"),
        story.get("recommended_start"),
    )
    for value in values:
        parsed = _optional_number(value)
        if parsed is not None and start - _START_SEARCH_SECONDS <= parsed <= start + _EPSILON:
            return max(0.0, parsed)
    return None


def _payoff_end(
    candidate: dict[str, Any],
    context: dict[str, Any],
    story: dict[str, Any],
    segments: list[dict[str, Any]],
    start: float,
    end: float,
) -> float | None:
    planning = S.as_dict(story.get("planning_guidance"))
    payoff_spans = [
        S.as_dict(item)
        for item in S.as_list(planning.get("must_include_spans"))
        if S.as_dict(item).get("kind") == "payoff"
    ]
    values: list[object] = [
        context.get("payoff_end_seconds"),
        candidate.get("payoff_end_seconds"),
        story.get("payoff_end_seconds"),
    ]
    values.extend(span.get("end") for span in payoff_spans)
    for signal in S.as_list(context.get("payoff_signals")):
        payoff = S.as_dict(signal)
        payoff_start = _optional_number(
            payoff.get("payoff_timestamp") or payoff.get("payoff_start")
        )
        if payoff_start is None or not (start - 1.0 <= payoff_start <= end + _END_SEARCH_SECONDS):
            continue
        explicit_end = _optional_number(payoff.get("payoff_end"))
        values.append(
            explicit_end
            if explicit_end is not None
            else _segment_end_at_or_after(segments, payoff_start, payoff_start + 4.0)
        )
    for value in values:
        parsed = _optional_number(value)
        if parsed is not None and start < parsed <= end + _END_SEARCH_SECONDS:
            return parsed
    return None


def _story_confidence(
    candidate: dict[str, Any], context: dict[str, Any], story: dict[str, Any]
) -> float:
    planning = S.as_dict(story.get("planning_guidance"))
    return _first_score(
        context.get("story_confidence"),
        planning.get("boundary_confidence"),
        story.get("ending_strength"),
        story.get("confidence"),
        candidate.get("confidence"),
        default=0.5,
    )


def _inside_span(timestamp: float, spans: list[dict[str, Any]]) -> bool:
    return any(_start(item) + _EPSILON < timestamp < _end(item) - _EPSILON for item in spans)


def _first_overlapping_segment(
    segments: list[dict[str, Any]], start: float, end: float
) -> dict[str, Any] | None:
    return next((item for item in segments if _end(item) > start and _start(item) < end), None)


def _next_segment(
    segments: list[dict[str, Any]], current: dict[str, Any]
) -> dict[str, Any] | None:
    try:
        index = segments.index(current)
    except ValueError:
        return None
    return segments[index + 1] if index + 1 < len(segments) else None


def _segment_start_at_or_before(
    segments: list[dict[str, Any]], timestamp: float, fallback: float
) -> float:
    candidates = [item for item in segments if _start(item) <= timestamp + _EPSILON]
    return _start(candidates[-1]) if candidates else max(0.0, fallback)


def _segment_end_at_or_after(
    segments: list[dict[str, Any]], timestamp: float, fallback: float
) -> float:
    candidate = next((item for item in segments if _end(item) >= timestamp - _EPSILON), None)
    return _end(candidate) if candidate else max(timestamp, fallback)


def _signal_between(
    start: float,
    end: float,
    hook_start: float | None,
    context_start: float | None,
) -> bool:
    return any(value is not None and start <= value < end for value in (hook_start, context_start))


def _temporal_iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    intersection = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return intersection / union if union > 0 else 0.0


def _non_overlapping_start(
    start: float,
    end: float,
    previous: list[dict[str, float]],
    segments: list[dict[str, Any]],
    minimum_duration: float,
) -> float | None:
    latest_end = max(
        (
            item["end_seconds"]
            for item in previous
            if _temporal_iou(start, end, item["start_seconds"], item["end_seconds"]) >= 0.45
        ),
        default=start,
    )
    candidate = next((_start(item) for item in segments if _start(item) >= latest_end + 0.1), None)
    return candidate if candidate is not None and end - candidate >= minimum_duration else None


def _enforce_duration(
    start: float,
    end: float,
    *,
    source_duration: float,
    minimum_duration: float,
    maximum_duration: float,
    payoff_end: float | None,
    changes: list[str],
    warnings: list[str],
) -> tuple[float, float]:
    bounded_start = max(0.0, min(start, source_duration))
    bounded_end = max(bounded_start, min(end, source_duration))
    if abs(bounded_start - start) > _EPSILON or abs(bounded_end - end) > _EPSILON:
        changes.append("clamped_to_source_duration")
        warnings.append("recommended window was clamped to the available source duration")
    start, end = bounded_start, bounded_end
    if end - start > maximum_duration:
        if payoff_end is not None and payoff_end <= end and payoff_end - maximum_duration >= 0:
            start = max(start, payoff_end - maximum_duration)
            end = min(end, start + maximum_duration)
        else:
            end = start + maximum_duration
        changes.append("clamped_to_maximum_duration")
    if end - start < minimum_duration:
        expanded_end = min(source_duration, start + minimum_duration)
        if expanded_end - start >= minimum_duration - _EPSILON:
            end = expanded_end
        else:
            start = max(0.0, end - minimum_duration)
        changes.append("expanded_to_minimum_duration")
        if end - start < minimum_duration - _EPSILON:
            warnings.append("source duration cannot satisfy the configured minimum clip duration")
    return round(start, 3), round(end, 3)


def _dead_air_risk(start: float, end: float, segments: list[dict[str, Any]]) -> float:
    first = _first_overlapping_segment(segments, start, end)
    if not first:
        return 1.0 if segments else 0.5
    gap = max(0.0, _start(first) - start)
    filler = 0.45 if _text(first).lower().strip().startswith(_FILLER_PREFIXES) else 0.0
    return S.clamp01(max(gap / 3.0, filler))


def _ending_is_open(segments: list[dict[str, Any]], end: float) -> bool:
    inside = [item for item in segments if _start(item) < end + _EPSILON]
    if not inside:
        return False
    text = _text(inside[-1]).lower().strip()
    return text.endswith((" and", " but", " so", ","))


def _hook_score(start: float, hook_start: float | None, candidate: dict[str, Any]) -> float:
    if hook_start is None:
        metadata = S.as_dict(S.as_dict(candidate.get("v2_candidate_metadata")).get("hook_analysis"))
        return _first_score(
            candidate.get("hook_potential"),
            S.as_dict(candidate.get("hook_candidate")).get("score"),
            metadata.get("score"),
            default=0.45,
        )
    if start > hook_start + _EPSILON:
        return 0.2
    lead = hook_start - start
    return 0.98 if lead <= 3.0 else 0.78 if lead <= 6.0 else 0.58


def _context_score(start: float, context_start: float | None, context_risk: float) -> float:
    base = 1.0 - context_risk
    if context_start is None:
        return S.clamp01(base)
    return max(base, 0.9) if start <= context_start + _EPSILON else min(base, 0.3)


def _payoff_score(
    end: float,
    payoff_end: float | None,
    candidate: dict[str, Any],
    story: dict[str, Any],
) -> float:
    strength = _first_score(
        story.get("payoff_strength"),
        candidate.get("payoff_potential"),
        candidate.get("payoff_score"),
        default=0.45,
    )
    if payoff_end is None:
        return strength
    return max(0.9, strength) if end + _EPSILON >= payoff_end else min(0.2, strength)


def _completeness_score(
    story_score: float,
    hook_score: float,
    context_score: float,
    payoff_score: float,
) -> float:
    if story_score > 0:
        return S.clamp01(
            0.5 * story_score + 0.15 * hook_score + 0.15 * context_score + 0.2 * payoff_score
        )
    return S.clamp01(0.2 * hook_score + 0.35 * context_score + 0.45 * payoff_score)


def _pacing_score(
    start: float,
    end: float,
    segments: list[dict[str, Any]],
    dead_air_risk: float,
) -> float:
    duration = max(0.1, end - start)
    word_count = sum(
        len(_text(item).split())
        for item in segments
        if _end(item) > start and _start(item) < end
    )
    rate = word_count / duration
    density = 1.0 if 1.3 <= rate <= 3.8 else 0.75 if 0.7 <= rate <= 5.0 else 0.4
    return S.clamp01(density - 0.35 * dead_air_risk)


def _boundary_confidence(
    hook_start: float | None,
    payoff_end: float | None,
    context_start: float | None,
    words: list[dict[str, Any]],
    story_confidence: float,
) -> float:
    available = sum(value is not None for value in (hook_start, payoff_end, context_start))
    confidence = 0.34 + 0.12 * available + (0.1 if words else 0.03) + 0.25 * story_confidence
    return S.clamp01(confidence)


__all__ = [
    "BoundaryQualityDecisionV1",
    "ClipBoundaryQualityV1",
    "recommend_clip_boundaries",
]

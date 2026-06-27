"""Pure, explainable helpers for the Clip Planner.

Deterministic, inspectable functions - not a black box. They turn the upstream
engines' *real* signals into clip boundaries, multi-dimensional quality scores,
overlap measurements, and stable ids. Everything here is transparent so it can be
unit-tested and audited; nothing invents data (a dimension only scores when the
signals it needs exist, and confidence reflects how much was actually available).

This mirrors the Story/Virality engines' scoring modules: transparent computation
behind the analyzer contract, swappable for stronger models later.
"""

from __future__ import annotations

from typing import Any

# Weights for the overall clip-quality score (short-form priorities). Only the
# *available* dimensions are used; weights are renormalized over them so a missing
# dimension is never silently counted as zero. ``editing_complexity`` is reported
# but excluded here (it is a cost, not a quality dimension).
CLIP_QUALITY_WEIGHTS: dict[str, float] = {
    "hook": 0.18,
    "retention": 0.15,
    "emotion": 0.12,
    "story": 0.10,
    "virality": 0.10,
    "information": 0.08,
    "novelty": 0.07,
    "shareability": 0.06,
    "conflict": 0.05,
    "replay": 0.05,
}

#: All reported quality dimensions (in display order), including the cost one.
CLIP_DIMENSIONS: tuple[str, ...] = (
    *CLIP_QUALITY_WEIGHTS.keys(),
    "editing_complexity",
)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def round3(value: float) -> float:
    return round(value, 3)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def weighted_mean(pairs: list[tuple[float, float]]) -> float:
    total = sum(w for _, w in pairs)
    if total <= 0:
        return 0.0
    return sum(v * w for v, w in pairs) / total


def coverage_confidence(available: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return clamp01(available / total)


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Seconds of temporal overlap between two [start, end] windows (>= 0)."""

    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def temporal_iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Intersection-over-union of two time windows (0 = disjoint, 1 = identical)."""

    inter = overlap_seconds(a_start, a_end, b_start, b_end)
    union = (a_end - a_start) + (b_end - b_start) - inter
    return inter / union if union > 0 else 0.0


def plan_id(start: float, end: float) -> str:
    """A stable id derived from the clip's boundaries (so reruns don't churn)."""

    return f"clip_{round(start * 1000)}_{round(end * 1000)}"


def in_window(timestamp: float, start: float, end: float) -> bool:
    return start <= timestamp < end


def localize(
    items: list[dict[str, Any]], key: str, start: float, end: float
) -> list[dict[str, Any]]:
    """Filter ``items`` to those whose ``key`` timestamp falls within [start, end)."""

    out: list[dict[str, Any]] = []
    for item in items:
        ts = item.get(key)
        if isinstance(ts, int | float) and in_window(float(ts), start, end):
            out.append(item)
    return out


def localize_spans(
    items: list[dict[str, Any]],
    start: float,
    end: float,
    *,
    start_key: str = "start",
    end_key: str = "end",
) -> list[dict[str, Any]]:
    """Filter span items that overlap the [start, end] window at all."""

    out: list[dict[str, Any]] = []
    for item in items:
        s, e = item.get(start_key), item.get(end_key)
        if (
            isinstance(s, int | float)
            and isinstance(e, int | float)
            and overlap_seconds(float(s), float(e), start, end) > 0
        ):
            out.append(item)
    return out


def compute_overall(scores: dict[str, float]) -> float:
    """Weighted mean of the available quality dimensions (excludes complexity)."""

    pairs = [(scores[dim], weight) for dim, weight in CLIP_QUALITY_WEIGHTS.items() if dim in scores]
    return weighted_mean(pairs)


# -- safe coercion (stage data is loosely-typed JSON) -------------------------
def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_float(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""

"""Pure, explainable scoring helpers for the Virality Engine.

These are deterministic, inspectable functions - not a black-box model. They
combine the *real* signals produced by the Cognitive and Story engines into
0-1 scores, and they make the combination transparent so it can be unit-tested
and audited. Nothing here invents data: a score only exists when the evidence it
is computed from exists, and confidence is kept honest (it reflects how much of
the needed evidence was actually available).

This mirrors the Story Engine's `heuristics` module: transparent computation that
can be swapped for a stronger model behind the analyzer contract later.
"""

from __future__ import annotations

import re
from typing import Any

# Maps each scoring analyzer to the public category it contributes to.
CATEGORY_FOR_STAGE: dict[str, str] = {
    "trend_research": "trend_fit",
    "hook_strength": "hook",
    "curiosity_gap": "curiosity",
    "emotional_impact": "emotion",
    "conflict": "conflict",
    "novelty": "novelty",
    "information_value": "information",
    "audience_relatability": "relatability",
    "momentum": "momentum",
    "retention": "retention",
    "replay_potential": "replay",
    "shareability": "sharing",
    "comment_potential": "commenting",
    "platform_fit": "platform_fit",
    "audience_fit": "audience_match",
}

# Importance weights for the overall virality score (short-form priorities).
# Only the *available* categories are used; weights are renormalized over them,
# so a missing category never silently counts as zero.
CATEGORY_WEIGHTS: dict[str, float] = {
    "trend_fit": 0.06,
    "hook": 0.18,
    "retention": 0.15,
    "emotion": 0.12,
    "curiosity": 0.10,
    "information": 0.08,
    "novelty": 0.08,
    "sharing": 0.07,
    "replay": 0.05,
    "momentum": 0.05,
    "conflict": 0.04,
    "commenting": 0.03,
    "relatability": 0.03,
    "platform_fit": 0.01,
    "audience_match": 0.01,
}

_WORD_RE = re.compile(r"[a-zA-Z']+")
_QUESTION_STARTERS = frozenset(
    {
        "what",
        "why",
        "how",
        "when",
        "where",
        "who",
        "which",
        "is",
        "are",
        "do",
        "does",
        "can",
        "could",
    }
)
# First/second-person address — a transparent proxy for relatability.
_PERSONAL_PRONOUNS = frozenset({"i", "i'm", "i've", "we", "we're", "my", "me", "us", "our"})
_SECOND_PERSON = frozenset({"you", "you're", "you've", "your", "yours"})


def clamp01(value: float) -> float:
    """Clamp a value into [0, 1]."""

    return max(0.0, min(1.0, value))


def round3(value: float) -> float:
    return round(value, 3)


def mean(values: list[float]) -> float:
    """Arithmetic mean, or 0.0 for an empty list."""

    return sum(values) / len(values) if values else 0.0


def weighted_mean(pairs: list[tuple[float, float]]) -> float:
    """Weighted mean of (value, weight) pairs; 0.0 if total weight is 0."""

    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return 0.0
    return sum(v * w for v, w in pairs) / total_w


def coverage_confidence(available: int, total: int) -> float:
    """Confidence as the fraction of needed evidence that was available."""

    if total <= 0:
        return 0.0
    return clamp01(available / total)


def tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def is_question(text: str) -> bool:
    """Whether the text looks like a question (mark or interrogative opener)."""

    stripped = text.strip()
    if "?" in stripped:
        return True
    first = tokens(stripped)[:1]
    return bool(first and first[0] in _QUESTION_STARTERS)


def personal_address_ratio(text: str) -> tuple[float, float]:
    """Return (first-person ratio, second-person ratio) over all tokens."""

    toks = tokens(text)
    if not toks:
        return 0.0, 0.0
    first = sum(1 for t in toks if t in _PERSONAL_PRONOUNS)
    second = sum(1 for t in toks if t in _SECOND_PERSON)
    return first / len(toks), second / len(toks)


# -- safe coercion (stage data is loosely-typed JSON) -------------------------
def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_float(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""

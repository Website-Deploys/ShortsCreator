"""Pure, explainable language heuristics for the Story Engine.

These are deterministic, inspectable text utilities - not a black-box model.
They operate on the *real* transcript produced by the Cognitive Engine and
produce conclusions that always come with supporting evidence and a confidence
that reflects how strong the textual signal actually is.

This is deliberately transparent linguistic analysis rather than a hidden model:
when a stronger model becomes available it can replace these analyzers behind
the same contract. Nothing here invents content - every signal is computed from
words that genuinely appear in the transcript, and confidence is kept modest
because heuristics are estimates, never certainties.
"""
# The word-list lexicons below are intentionally written as readable, wrapped
# ``"...".split()`` strings rather than long list literals (SIM905) so they stay
# easy to scan and extend.
# ruff: noqa: SIM905

from __future__ import annotations

import itertools
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# Lexicons (small, transparent, English-leaning). Easily extended/replaced.
# --------------------------------------------------------------------------- #
STOPWORDS: frozenset[str] = frozenset(
    (
        "a an the and or but if then else of to in on at for with from by as is "
        "are was were be been being it its this that these those i you he she we "
        "they them his her their our your my me us do does did done have has had "
        "having will would can could should may might must shall not no yes so "
        "just very really too also about into over under again more most much "
        "many few some any what which who whom whose when where why how all both "
        "each other than there here out up down off am pm"
    ).split()
)

# Filler / hedge words that signal low information density when frequent.
FILLER_WORDS: frozenset[str] = frozenset(
    (
        "um uh er erm hmm like basically actually literally honestly obviously "
        "simply kinda sorta gonna wanna stuff things yeah okay ok right anyway "
        "whatever"
    ).split()
)

# Discourse cues mapped to the narrative role they tend to signal. These are
# matched as substrings against lowercased text, so multi-word cues work.
DISCOURSE_CUES: dict[str, tuple[str, ...]] = {
    "hook": (
        "what if",
        "did you know",
        "have you ever",
        "imagine",
        "let me tell you",
        "here's the thing",
        "the truth is",
        "nobody tells you",
        "i'm going to show",
        "in this video",
        "this is why",
        "stop ",
        "watch this",
    ),
    "background": (
        "back when",
        "a few years ago",
        "originally",
        "it started",
        "the history",
        "some context",
        "to understand",
        "growing up",
        "at first",
    ),
    "problem": (
        "the problem",
        "the issue",
        "the challenge",
        "struggle",
        "the hard part",
        "unfortunately",
        "the trouble",
        "what went wrong",
        "it broke",
    ),
    "explanation": (
        "the reason",
        "this is how",
        "here's how",
        "in other words",
        "what this means",
        "the way it works",
        "let me explain",
        "essentially",
    ),
    "conflict": (
        "however",
        "the catch",
        "the problem is",
        "on the other hand",
        "despite",
        "even though",
        "but then",
        "the twist",
    ),
    "example": (
        "for example",
        "for instance",
        "like when",
        "consider",
        "say you",
        "take ",
        "case in point",
    ),
    "resolution": (
        "as a result",
        "the solution",
        "in the end",
        "finally",
        "that's why",
        "the takeaway",
        "what i learned",
        "the lesson",
        "so the point",
    ),
    "ending": (
        "thanks for watching",
        "subscribe",
        "that's it",
        "in conclusion",
        "to wrap up",
        "that's all",
        "see you",
        "until next time",
    ),
}

# Cues that signal an explicit back-reference (context dependency).
BACKREFERENCE_CUES: tuple[str, ...] = (
    "as i mentioned",
    "as i said",
    "like i said",
    "earlier",
    "remember when",
    "remember",
    "going back",
    "as we discussed",
    "i told you",
    "previously",
    "that thing",
    "the thing i",
    "what i said",
)

# Cues that often introduce a payoff (an answer / reveal / conclusion).
PAYOFF_CUES: tuple[str, ...] = (
    "the answer is",
    "turns out",
    "that's why",
    "the reason is",
    "what i found",
    "the result",
    "it turns out",
    "here's the answer",
    "the secret is",
    "so it",
    "which is why",
    "the truth is",
)

# Sentiment / arousal lexicons (small, transparent).
POSITIVE_WORDS: frozenset[str] = frozenset(
    (
        "love great amazing awesome incredible wonderful best fantastic happy "
        "excited beautiful perfect win winning success successful good better "
        "brilliant proud joy grateful fun"
    ).split()
)
NEGATIVE_WORDS: frozenset[str] = frozenset(
    (
        "hate terrible awful worst horrible sad angry afraid fear fail failed "
        "failure problem pain hard difficult struggle wrong bad worse broken "
        "lost lose losing scared frustrated disaster"
    ).split()
)
HIGH_AROUSAL_WORDS: frozenset[str] = frozenset(
    (
        "insane crazy unbelievable shocking massive huge explosive wild epic "
        "intense extreme urgent now immediately fast rush boom wow"
    ).split()
)
CALM_WORDS: frozenset[str] = frozenset(
    (
        "calm slow gentle quiet steady relax relaxed peaceful simple easy patient careful gradually"
    ).split()
)

_WORD_RE = re.compile(r"[a-zA-Z']+")
_SHOCK_WORDS: frozenset[str] = HIGH_AROUSAL_WORDS | frozenset(
    {"secret", "never", "nobody", "everyone", "shocking", "mistake", "warning"}
)
_QUESTION_STARTERS: frozenset[str] = frozenset(
    ("what why how when where who which is are do does can could").split()
)


def tokens(text: str) -> list[str]:
    """Lowercased word tokens."""

    return _WORD_RE.findall(text.lower())


def content_tokens(text: str) -> list[str]:
    """Tokens with stopwords and very short words removed (the 'aboutness')."""

    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 2]


def keywords(text: str, k: int = 6) -> list[str]:
    """The ``k`` most frequent content tokens (a transparent topic fingerprint)."""

    counts = Counter(content_tokens(text))
    return [word for word, _ in counts.most_common(k)]


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets (0 = disjoint, 1 = identical)."""

    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def find_cues(text: str) -> dict[str, list[str]]:
    """Return the discourse cues present in ``text``, grouped by role."""

    low = f" {text.lower()} "
    found: dict[str, list[str]] = {}
    for role, phrases in DISCOURSE_CUES.items():
        hits = [p.strip() for p in phrases if p in low]
        if hits:
            found[role] = hits
    return found


def find_phrases(text: str, phrases: tuple[str, ...]) -> list[str]:
    """Return which of ``phrases`` appear in ``text`` (substring match)."""

    low = f" {text.lower()} "
    return [p.strip() for p in phrases if p in low]


def is_question(text: str) -> bool:
    """Whether the text looks like a question (mark or interrogative opener)."""

    stripped = text.strip()
    if "?" in stripped:
        return True
    first = tokens(stripped)[:1]
    return bool(first and first[0] in _QUESTION_STARTERS)


def shock_terms(text: str) -> list[str]:
    """Shock / curiosity terms present in the text."""

    return sorted({t for t in tokens(text) if t in _SHOCK_WORDS})


def filler_ratio(text: str) -> float:
    """Fraction of tokens that are filler/hedge words (0-1)."""

    toks = tokens(text)
    if not toks:
        return 0.0
    fillers = sum(1 for t in toks if t in FILLER_WORDS)
    return fillers / len(toks)


def lexical_diversity(text: str) -> float:
    """Unique-content-token ratio (a transparent information-richness proxy)."""

    content = content_tokens(text)
    if not content:
        return 0.0
    return len(set(content)) / len(content)


def repetition_ratio(text: str) -> float:
    """How repetitive the content is (1 - distinct-bigram ratio), 0-1."""

    content = content_tokens(text)
    if len(content) < 2:
        return 0.0
    bigrams = list(itertools.pairwise(content))
    if not bigrams:
        return 0.0
    return 1.0 - (len(set(bigrams)) / len(bigrams))


def entity_density(text: str) -> float:
    """Proxy for factual density: capitalized words + numbers per token (0-1)."""

    raw = text.split()
    if not raw:
        return 0.0
    hits = 0
    for i, word in enumerate(raw):
        cleaned = word.strip(".,!?;:'\"")
        if not cleaned:
            continue
        if any(ch.isdigit() for ch in cleaned) or (i > 0 and cleaned[0].isupper()):
            hits += 1
    return min(1.0, hits / len(raw))


@dataclass(slots=True)
class Sentiment:
    """A transparent sentiment/arousal reading of a span of text."""

    label: str  # one of: positive, negative, excited, calm, neutral
    score: float  # signed valence in [-1, 1]
    arousal: float  # 0-1
    counts: dict[str, int]


def sentiment(text: str) -> Sentiment:
    """Estimate a coarse emotion label from transparent lexicon counts.

    This is explicitly an *estimate* - the returned label should always be paired
    with a modest confidence by the caller, and never presented as certain.
    """

    toks = tokens(text)
    counts = {
        "positive": sum(1 for t in toks if t in POSITIVE_WORDS),
        "negative": sum(1 for t in toks if t in NEGATIVE_WORDS),
        "excited": sum(1 for t in toks if t in HIGH_AROUSAL_WORDS),
        "calm": sum(1 for t in toks if t in CALM_WORDS),
    }
    total = len(toks) or 1
    valence = (counts["positive"] - counts["negative"]) / total
    arousal = min(1.0, (counts["excited"] + counts["positive"] + counts["negative"]) / total * 4)

    emotional = counts["positive"] + counts["negative"]
    if counts["excited"] >= max(1, emotional):
        label = "excited"
    elif counts["calm"] > emotional and counts["calm"] > 0:
        label = "calm"
    elif valence > 0.01:
        label = "positive"
    elif valence < -0.01:
        label = "negative"
    else:
        label = "neutral"
    return Sentiment(label=label, score=round(valence, 3), arousal=round(arousal, 3), counts=counts)


def clamp01(value: float) -> float:
    """Clamp a value into [0, 1]."""

    return max(0.0, min(1.0, value))


def excerpt(text: str, limit: int = 220) -> str:
    """A trimmed, single-line evidence excerpt."""

    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "\u2026"


def seg_text(segment: dict[str, Any]) -> str:
    """Safely read a transcript segment's text."""

    return str(segment.get("text") or "")


def seg_start(segment: dict[str, Any]) -> float:
    return float(segment.get("start") or 0.0)


def seg_end(segment: dict[str, Any]) -> float:
    value = segment.get("end")
    return float(value) if value is not None else seg_start(segment)


def as_list(value: Any) -> list[Any]:
    """Safely coerce loose JSON stage data into a list."""

    return value if isinstance(value, list) else []

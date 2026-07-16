"""Focused, non-spam hashtag planning for Upload Metadata V2."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from olympus.metadata.platforms import PlatformRules

_TAG_TOKEN = re.compile(r"[^a-z0-9]+")
_STOPWORDS = {
    "about",
    "after",
    "again",
    "because",
    "before",
    "being",
    "could",
    "every",
    "from",
    "have",
    "into",
    "just",
    "matters",
    "more",
    "most",
    "nobody",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "those",
    "what",
    "when",
    "where",
    "which",
    "while",
    "why",
    "with",
    "watching",
    "would",
    "your",
}
_BLOCKED_TAGS = {
    "adult",
    "bodycheck",
    "copyrightsafe",
    "dangerouschallenge",
    "foryou",
    "foryoupage",
    "fyp",
    "guaranteedviral",
    "nsfw",
    "thinspo",
    "trending",
    "trendingnow",
    "viral",
    "viralclip",
}
_DISPLAY: dict[str, str] = {
    "ai": "AI",
    "business": "Business",
    "discipline": "Discipline",
    "education": "Education",
    "emotional": "Emotional",
    "gaming": "Gaming",
    "inspiration": "Inspiration",
    "lifelessons": "LifeLessons",
    "mindset": "Mindset",
    "motivation": "Motivation",
    "music": "Music",
    "musiccover": "MusicCover",
    "podcast": "Podcast",
    "reels": "Reels",
    "selfimprovement": "SelfImprovement",
    "shortformvideo": "ShortFormVideo",
    "shorts": "Shorts",
    "singing": "Singing",
    "sports": "Sports",
    "storytime": "Storytime",
    "success": "Success",
    "tiktok": "TikTok",
}
_NICHE_TAGS: dict[str, tuple[str, ...]] = {
    "business": ("#Business", "#Mindset", "#Success"),
    "education": ("#Education", "#Learn", "#Explained"),
    "gaming": ("#Gaming", "#Gameplay", "#GamingMoments"),
    "motivational": ("#Motivation", "#Mindset", "#SelfImprovement"),
    "motivation": ("#Motivation", "#Mindset", "#SelfImprovement"),
    "music": ("#Music", "#Performance", "#MusicShorts"),
    "musicsinging": ("#Music", "#Singing", "#Performance"),
    "singing": ("#Singing", "#Music", "#Performance"),
    "podcast": ("#Podcast", "#Conversation", "#Ideas"),
    "podcastinterview": ("#Podcast", "#Interview", "#Conversation"),
    "sports": ("#Sports", "#SportsMoments", "#Performance"),
    "storytime": ("#Storytime", "#LifeLessons", "#Story"),
}
_FORMAT_TAGS: dict[str, tuple[str, ...]] = {
    "instagram_reels": ("#ShortFormVideo",),
}


def _token(value: str) -> str:
    return _TAG_TOKEN.sub("", value.casefold())


def _canonical(value: str) -> str | None:
    token = _token(value.lstrip("#"))
    if len(token) < 2 or len(token) > 28 or token in _STOPWORDS or token in _BLOCKED_TAGS:
        return None
    display = _DISPLAY.get(token)
    if display is None:
        display = token[0].upper() + token[1:]
    return f"#{display}"


def _topic_candidates(keywords: Iterable[str]) -> list[str]:
    tags: list[str] = []
    for keyword in keywords:
        for part in re.findall(r"[A-Za-z0-9]+", str(keyword)):
            tag = _canonical(part)
            if tag and tag.casefold() not in {item.casefold() for item in tags}:
                tags.append(tag)
    return tags


def build_hashtag_plan(
    *,
    rules: PlatformRules,
    niche: str,
    keywords: Iterable[str],
    emotion: str | None = None,
    requested_tags: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a bounded hashtag plan using only relevant supplied signals."""

    normalized_niche = _token(niche)
    niche_tags = [
        tag
        for tag in _NICHE_TAGS.get(normalized_niche, ())
        if _canonical(tag) is not None
    ]
    if not niche_tags and normalized_niche:
        fallback_niche = _canonical(normalized_niche)
        niche_tags = [fallback_niche] if fallback_niche else []

    topic_tags = _topic_candidates(keywords)
    emotional_tags: list[str] = []
    if emotion:
        emotional = _canonical(emotion)
        if emotional:
            emotional_tags.append(emotional)

    format_tags = list(_FORMAT_TAGS.get(rules.platform, ()))
    candidates = [
        *niche_tags,
        rules.platform_tag,
        *format_tags,
        *topic_tags,
        *emotional_tags,
    ]
    candidates.extend(str(tag) for tag in requested_tags)
    selected: list[str] = []
    removed: list[dict[str, str]] = []
    for raw in candidates:
        tag = _canonical(raw)
        if tag is None:
            removed.append({"tag": str(raw), "reason": "blocked_or_invalid"})
            continue
        if tag.casefold() in {item.casefold() for item in selected}:
            removed.append({"tag": tag, "reason": "duplicate"})
            continue
        if len(selected) >= rules.hashtag_max:
            removed.append({"tag": tag, "reason": "platform_limit"})
            continue
        selected.append(tag)

    warnings: list[str] = []
    if len(selected) < rules.hashtag_min:
        warnings.append(
            "Fewer hashtags were emitted than the platform target because Olympus did not "
            "have enough relevant signals."
        )
    relevant_count = sum(
        1 for tag in selected if tag.casefold() != rules.platform_tag.casefold()
    )
    relevance = round(relevant_count / max(1, len(selected)), 3)
    return {
        "platform": rules.platform,
        "hashtags": selected,
        "niche_tags": [tag for tag in selected if tag in niche_tags],
        "topic_tags": [tag for tag in selected if tag in topic_tags],
        "trend_tags": [],
        "format_tags": [tag for tag in selected if tag in format_tags or tag == rules.platform_tag],
        "emotional_tags": [tag for tag in selected if tag in emotional_tags],
        "removed_tags": removed,
        "relevance_score": relevance,
        "warnings": warnings,
    }


def blocked_hashtag_tokens() -> frozenset[str]:
    """Expose the normalized blocklist to the validator and diagnostics."""

    return frozenset(_BLOCKED_TAGS)

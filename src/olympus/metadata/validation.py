"""Conservative validation for generated or imported upload metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from olympus.metadata.hashtags import blocked_hashtag_tokens
from olympus.metadata.platforms import PlatformName, platform_rules

_SPACE = re.compile(r"\s+")
_PUNCTUATION_RUN = re.compile(r"[!?]{3,}")
_BANNED_PHRASES = (
    "copyright safe",
    "guaranteed viral",
    "safe to upload",
    "trending now",
)
_ENGAGEMENT_BAIT = (
    "like if",
    "comment yes",
    "share this or",
    "tag three friends",
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalized(value: str) -> str:
    return _SPACE.sub(" ", value.casefold()).strip()


def _all_caps(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    return len(letters) >= 5 and all(char.isupper() for char in letters)


def _candidate_texts(value: Any) -> list[str]:
    texts: list[str] = []
    for item in _list(value):
        text = _text(_dict(item).get("text")) or _text(item)
        if text:
            texts.append(text)
    return texts


def _copied_long_text(texts: list[str], source_text: str) -> bool:
    source = _normalized(source_text)
    if not source:
        return False
    for text in texts:
        normalized = _normalized(text)
        if len(normalized) >= 90 and len(normalized.split()) >= 14 and normalized in source:
            return True
    return False


def _rules_for(platform: PlatformName, settings: Mapping[str, Any]) -> Any:
    return platform_rules(
        platform,
        max_title_length=int(settings.get("max_title_length", 70)),
        max_youtube_hashtags=int(settings.get("max_youtube_hashtags", 8)),
        max_instagram_hashtags=int(settings.get("max_instagram_hashtags", 12)),
        max_tiktok_hashtags=int(settings.get("max_tiktok_hashtags", 8)),
    )


def validate_upload_metadata(
    metadata: Mapping[str, Any],
    *,
    source_text: str = "",
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate truth-language, bounds, hashtag hygiene, and safety disclosure."""

    config = settings or {}
    inputs = _dict(metadata.get("input_signals"))
    youtube = _dict(metadata.get("youtube_shorts"))
    instagram = _dict(metadata.get("instagram_reels"))
    tiktok = _dict(metadata.get("tiktok"))
    universal = _dict(metadata.get("universal"))
    youtube_enabled = bool(config.get("generate_youtube", True))
    instagram_enabled = bool(config.get("generate_instagram", True))
    tiktok_enabled = bool(config.get("generate_tiktok", True))

    title = _text(youtube.get("title"))
    youtube_rules = _rules_for("youtube_shorts", config)
    title_errors: list[str] = []
    title_warnings: list[str] = []
    if youtube_enabled and not title:
        title_errors.append("YouTube title is empty.")
    if youtube_enabled and title and len(title) > youtube_rules.title_max_chars:
        title_errors.append(
            f"YouTube title exceeds {youtube_rules.title_max_chars} characters."
        )
    if youtube_enabled and _all_caps(title):
        title_errors.append("YouTube title is all caps.")
    if youtube_enabled and _PUNCTUATION_RUN.search(title):
        title_errors.append("YouTube title uses excessive punctuation.")

    bodies: list[str] = []
    if youtube_enabled:
        bodies.extend(
            [
                title,
                *_candidate_texts(youtube.get("title_variants")),
                _text(youtube.get("description")),
                _text(youtube.get("pinned_comment")),
            ]
        )
    if instagram_enabled:
        bodies.extend(
            [
                _text(instagram.get("caption")),
                *_candidate_texts(instagram.get("caption_variants")),
            ]
        )
    if tiktok_enabled:
        bodies.extend(
            [_text(tiktok.get("caption")), *_candidate_texts(tiktok.get("caption_variants"))]
        )
    normalized_bodies = [_normalized(body) for body in bodies if body]
    banned_hits = sorted(
        phrase for phrase in _BANNED_PHRASES if any(phrase in body for body in normalized_bodies)
    )
    bait_hits = sorted(
        phrase for phrase in _ENGAGEMENT_BAIT if any(phrase in body for body in normalized_bodies)
    )
    if banned_hits:
        title_errors.append(f"Banned claim language found: {', '.join(banned_hits)}.")
    if bait_hits:
        title_errors.append(f"Manipulative engagement language found: {', '.join(bait_hits)}.")

    copied_long = _copied_long_text(bodies, source_text)
    if copied_long:
        title_errors.append("A long metadata passage appears copied from the source text.")
    niche = _text(inputs.get("content_niche")).casefold()
    lyric_like = niche in {"music", "singing", "music_singing"} and copied_long
    if lyric_like:
        title_errors.append("Music metadata appears to reproduce a long source passage.")

    hashtag_errors: list[str] = []
    hashtag_warnings: list[str] = []
    normalized_blocked = blocked_hashtag_tokens()
    platform_values: list[tuple[PlatformName, dict[str, Any]]] = []
    if youtube_enabled:
        platform_values.append(("youtube_shorts", youtube))
    if instagram_enabled:
        platform_values.append(("instagram_reels", instagram))
    if tiktok_enabled:
        platform_values.append(("tiktok", tiktok))
    for platform, payload in platform_values:
        rules = _rules_for(platform, config)
        tags = [_text(item) for item in _list(payload.get("hashtags")) if _text(item)]
        normalized_tags = [re.sub(r"[^a-z0-9]+", "", tag.casefold()) for tag in tags]
        if len(tags) > rules.hashtag_max:
            hashtag_errors.append(
                f"{platform} has {len(tags)} hashtags; limit is {rules.hashtag_max}."
            )
        if len(set(normalized_tags)) != len(normalized_tags):
            hashtag_errors.append(f"{platform} contains duplicate hashtags.")
        blocked = sorted({tag for tag in normalized_tags if tag in normalized_blocked})
        if blocked:
            hashtag_errors.append(f"{platform} contains blocked hashtags: {', '.join(blocked)}.")
        if len(tags) < rules.hashtag_min:
            hashtag_warnings.append(
                f"{platform} has fewer than the target {rules.hashtag_min} relevant hashtags."
            )

    risk = _text(inputs.get("safety_risk_level")).casefold() or "unknown"
    readiness = _text(inputs.get("upload_readiness")).casefold() or "unknown"
    manual_review = universal.get("manual_review_required") is True
    safety_warnings = [
        _text(item)
        for payload in (youtube, instagram, tiktok)
        for item in _list(payload.get("safety_warnings"))
        if _text(item)
    ]
    safety_errors: list[str] = []
    safety_notices: list[str] = []
    if risk == "blocked" or readiness in {"blocked", "not_ready"}:
        safety_errors.append("Safety assessment marks this metadata as not ready for upload.")
    if risk in {"unknown", "medium", "high", "blocked"} and not manual_review:
        safety_errors.append("Manual review is required but not marked in universal metadata.")
    if manual_review and not safety_warnings:
        safety_errors.append("Manual review is required but platform safety warnings are missing.")
    if manual_review:
        safety_notices.append("Manual review is required before publishing.")

    grounding_available = any(
        _text(inputs.get(field))
        for field in ("clip_title_source", "transcript_excerpt_used", "hook_line", "content_niche")
    )
    if not grounding_available:
        title_warnings.append("No strong grounding signal was available for metadata generation.")

    errors = list(dict.fromkeys([*title_errors, *hashtag_errors, *safety_errors]))
    warnings = list(
        dict.fromkeys([*title_warnings, *hashtag_warnings, *safety_notices])
    )
    title_truthful = not banned_hits and grounding_available
    description_truthful = not banned_hits and not copied_long
    hashtags_relevant = not hashtag_errors
    no_spam_tags = not hashtag_errors
    safety_checked = inputs.get("safety_check_available") is True
    return {
        "passed": not errors,
        "title_truthful": title_truthful,
        "description_truthful": description_truthful,
        "hashtags_relevant": hashtags_relevant,
        "no_copied_content": not copied_long,
        "no_spam_tags": no_spam_tags,
        "safety_checked": safety_checked,
        "title_validation": {
            "passed": not title_errors,
            "length": len(title),
            "max_length": youtube_rules.title_max_chars,
            "truthful": title_truthful,
            "all_caps": _all_caps(title),
            "excessive_punctuation": bool(_PUNCTUATION_RUN.search(title)),
            "warnings": title_warnings,
            "errors": title_errors,
        },
        "description_validation": {
            "passed": description_truthful and not bait_hits,
            "truthful": description_truthful,
            "engagement_bait": bool(bait_hits),
            "warnings": [],
            "errors": [error for error in title_errors if "engagement" in error.casefold()],
        },
        "hashtag_validation": {
            "passed": not hashtag_errors,
            "relevant": hashtags_relevant,
            "warnings": hashtag_warnings,
            "errors": hashtag_errors,
        },
        "safety_validation": {
            "passed": not safety_errors,
            "risk_level": risk,
            "upload_readiness": readiness,
            "manual_review_required": manual_review,
            "warnings": safety_notices,
            "errors": safety_errors,
        },
        "platform_validation": {
            "passed": not hashtag_errors and not title_errors,
            "platforms": [platform for platform, _payload in platform_values],
        },
        "warnings": warnings,
        "errors": errors,
    }

"""Bounded platform rules for Upload Metadata V2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PlatformName = Literal["youtube_shorts", "instagram_reels", "tiktok"]


@dataclass(frozen=True, slots=True)
class PlatformRules:
    """Limits and tone constraints for one supported platform."""

    platform: PlatformName
    title_max_chars: int
    caption_max_chars: int
    hashtag_min: int
    hashtag_max: int
    platform_tag: str
    tone: str


DEFAULT_PLATFORM_RULES: dict[PlatformName, PlatformRules] = {
    "youtube_shorts": PlatformRules(
        platform="youtube_shorts",
        title_max_chars=70,
        caption_max_chars=320,
        hashtag_min=3,
        hashtag_max=8,
        platform_tag="#Shorts",
        tone="specific and concise",
    ),
    "instagram_reels": PlatformRules(
        platform="instagram_reels",
        title_max_chars=0,
        caption_max_chars=420,
        hashtag_min=5,
        hashtag_max=12,
        platform_tag="#Reels",
        tone="conversational and reflective",
    ),
    "tiktok": PlatformRules(
        platform="tiktok",
        title_max_chars=0,
        caption_max_chars=220,
        hashtag_min=3,
        hashtag_max=8,
        platform_tag="#TikTok",
        tone="short and direct",
    ),
}


def platform_rules(
    platform: PlatformName,
    *,
    max_title_length: int = 70,
    max_youtube_hashtags: int = 8,
    max_instagram_hashtags: int = 12,
    max_tiktok_hashtags: int = 8,
) -> PlatformRules:
    """Return defaults with operator-configured upper bounds applied."""

    base = DEFAULT_PLATFORM_RULES[platform]
    hashtag_limits = {
        "youtube_shorts": max_youtube_hashtags,
        "instagram_reels": max_instagram_hashtags,
        "tiktok": max_tiktok_hashtags,
    }
    title_limit = min(base.title_max_chars, max_title_length) if base.title_max_chars else 0
    return PlatformRules(
        platform=base.platform,
        title_max_chars=max(20, title_limit) if title_limit else 0,
        caption_max_chars=base.caption_max_chars,
        hashtag_min=base.hashtag_min,
        hashtag_max=max(1, min(base.hashtag_max, hashtag_limits[platform])),
        platform_tag=base.platform_tag,
        tone=base.tone,
    )

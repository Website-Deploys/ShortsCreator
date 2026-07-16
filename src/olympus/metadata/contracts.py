"""Stable JSON-safe contracts for Title / Description / Hashtag V2."""

from __future__ import annotations

from typing import Any, TypedDict

UPLOAD_METADATA_V2_VERSION = "2"


class TitleCandidate(TypedDict):
    """One ranked, bounded title candidate."""

    text: str
    platform: str
    pattern: str
    hook_category: str
    truth_score: float
    curiosity_score: float
    clarity_score: float
    safety_score: float
    length: int
    warnings: list[str]


class YouTubeShortsMetadata(TypedDict):
    """Copy-ready YouTube Shorts metadata."""

    title: str
    title_variants: list[TitleCandidate]
    description: str
    hashtags: list[str]
    hashtag_plan: dict[str, Any]
    pinned_comment: str | None
    safety_warnings: list[str]
    confidence: float


class SocialCaptionMetadata(TypedDict):
    """Copy-ready Instagram Reels or TikTok metadata."""

    caption: str
    caption_variants: list[str]
    hashtags: list[str]
    hashtag_plan: dict[str, Any]
    safety_warnings: list[str]
    confidence: float


class UploadMetadataV2(TypedDict):
    """Canonical per-render metadata payload persisted by Olympus."""

    metadata_id: str
    project_id: str
    clip_id: str
    render_id: str | None
    created_at: str
    generator_version: str
    status: str
    reason: str | None
    input_signals: dict[str, Any]
    youtube_shorts: YouTubeShortsMetadata
    instagram_reels: SocialCaptionMetadata
    tiktok: SocialCaptionMetadata
    universal: dict[str, Any]
    upload_metadata_personalization: dict[str, Any]
    validation: dict[str, Any]
    artifact: dict[str, Any]

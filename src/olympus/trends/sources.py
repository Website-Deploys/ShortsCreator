"""Small updateable registry of official public trend-guidance sources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OfficialTrendSource:
    """An allowlisted source whose body is never persisted by Olympus."""

    source_id: str
    url: str
    title: str
    platform: str
    source_type: str
    niche_relevance: tuple[str, ...]
    refresh_ttl_hours: int
    credibility: float
    patterns_supported: tuple[str, ...]
    pattern_summary: str
    notes: str


OFFICIAL_TREND_SOURCES: tuple[OfficialTrendSource, ...] = (
    OfficialTrendSource(
        source_id="youtube_shorts_discovery_guidance",
        url="https://support.google.com/youtube/answer/11914225?hl=en",
        title="YouTube Shorts search and discovery guidance",
        platform="youtube_shorts",
        source_type="official_platform_docs",
        niche_relevance=("all",),
        refresh_ttl_hours=168,
        credibility=0.96,
        patterns_supported=(
            "fast_first_sentence",
            "avoid_filler",
            "satisfying_answer",
            "replay_worthy_moment",
        ),
        pattern_summary=(
            "Official guidance supports viewer-first openings, concise delivery, "
            "and complete payoffs rather than copied formats."
        ),
        notes="Living official guidance; retrieval confirms availability, not a virality claim.",
    ),
    OfficialTrendSource(
        source_id="youtube_recommendation_guidance",
        url="https://support.google.com/youtube/answer/16559651?hl=en",
        title="YouTube recommendation guidance",
        platform="youtube_shorts",
        source_type="official_platform_docs",
        niche_relevance=("all",),
        refresh_ttl_hours=168,
        credibility=0.96,
        patterns_supported=("tight_clarity", "quick_context", "avoid_filler"),
        pattern_summary=(
            "Official guidance supports using only the length needed for a clear idea "
            "and learning from retention without chasing a copied template."
        ),
        notes="Living official guidance; no creator content is collected.",
    ),
    OfficialTrendSource(
        source_id="instagram_ranking_guidance",
        url="https://about.instagram.com/blog/announcements/instagram-ranking-explained",
        title="Instagram ranking explained",
        platform="instagram_reels",
        source_type="official_platform_docs",
        niche_relevance=("all",),
        refresh_ttl_hours=168,
        credibility=0.93,
        patterns_supported=("fast_first_sentence", "avoid_filler", "replay_worthy_moment"),
        pattern_summary=(
            "Official platform guidance supports clear viewer value and sustained interest "
            "without copying another creator's expression."
        ),
        notes="Public platform explanation; only pattern-level metadata is retained.",
    ),
    OfficialTrendSource(
        source_id="tiktok_recommendation_guidance",
        url="https://newsroom.tiktok.com/en-us/how-tiktok-recommends-videos-for-you",
        title="How TikTok recommends videos",
        platform="tiktok",
        source_type="official_platform_docs",
        niche_relevance=("all",),
        refresh_ttl_hours=168,
        credibility=0.93,
        patterns_supported=("short_high_contrast", "avoid_filler", "satisfying_answer"),
        pattern_summary=(
            "Official platform guidance supports clear, relevant short-form communication "
            "and complete viewer value rather than copied creator material."
        ),
        notes="Public newsroom guidance; no videos, captions, or scripts are fetched.",
    ),
)

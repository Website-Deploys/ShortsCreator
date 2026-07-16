"""Shared Internet Trend Research V2 intelligence layer."""

from olympus.trends.contracts import TrendResearchProvider, TrendSearchResult
from olympus.trends.providers import (
    CascadingTrendResearchProvider,
    ConfiguredWebSearchTrendProvider,
    ConfiguredWebTrendResearchProvider,
    DisabledTrendProvider,
    EvergreenTrendProvider,
    MockTrendResearchProvider,
    OfficialSourceTrendProvider,
    StaticEvergreenTrendProvider,
    build_trend_research_provider,
    score_source_credibility,
)
from olympus.trends.research import (
    TREND_RESEARCH_V2_VERSION,
    TrendResearchEngine,
    build_editing_trend_guidance,
    build_evergreen_snapshot,
    build_story_trend_guidance,
    build_trend_query_plan,
    default_platform_focus,
    detect_content_niche_v2,
    match_trend_patterns,
)
from olympus.trends.store import (
    TrendSnapshotStore,
    snapshot_is_fresh,
    snapshot_is_stale_usable,
)
from olympus.trends.url_safety import TrendUrlSafetyError, validate_trend_url

__all__ = [
    "TREND_RESEARCH_V2_VERSION",
    "CascadingTrendResearchProvider",
    "ConfiguredWebSearchTrendProvider",
    "ConfiguredWebTrendResearchProvider",
    "DisabledTrendProvider",
    "EvergreenTrendProvider",
    "MockTrendResearchProvider",
    "OfficialSourceTrendProvider",
    "StaticEvergreenTrendProvider",
    "TrendResearchEngine",
    "TrendResearchProvider",
    "TrendSearchResult",
    "TrendSnapshotStore",
    "TrendUrlSafetyError",
    "build_editing_trend_guidance",
    "build_evergreen_snapshot",
    "build_story_trend_guidance",
    "build_trend_query_plan",
    "build_trend_research_provider",
    "default_platform_focus",
    "detect_content_niche_v2",
    "match_trend_patterns",
    "score_source_credibility",
    "snapshot_is_fresh",
    "snapshot_is_stale_usable",
    "validate_trend_url",
]

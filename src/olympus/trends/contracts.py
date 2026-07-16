"""Contracts for safe, pattern-level trend research providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class TrendSearchResult:
    """A concise public-source search result safe to persist.

    ``summary`` is intentionally bounded again before persistence. Providers must
    never put article bodies, video transcripts, captions, or creator scripts here.
    """

    url: str
    title: str
    summary: str
    source_type: str = "search_result_summary"
    credibility: float = 0.5
    credibility_level: str = "unknown"
    published_at: str | None = None
    recency_score: float = 0.5
    provider: str | None = None
    patterns_supported: tuple[str, ...] = ()
    warning: str | None = None
    warnings: tuple[str, ...] = ()


class TrendResearchProvider(Protocol):
    """Replaceable runtime source of public trend-research summaries."""

    @property
    def name(self) -> str:
        """Stable provider identifier used in artifacts and diagnostics."""

    @property
    def provider_name(self) -> str:
        """Compatibility alias used by live-provider diagnostics."""

    @property
    def live(self) -> bool:
        """Whether this provider performs fresh network research."""

    @property
    def internet_available(self) -> bool:
        """Whether this run completed real public-network I/O successfully."""

    async def is_available(self) -> bool:
        """Return whether the provider can be used in this runtime."""

    async def search(self, query: str, *, max_results: int) -> list[TrendSearchResult]:
        """Return concise public-source results for one safe query."""

    async def fetch(self, url: str) -> TrendSearchResult | None:
        """Fetch one explicitly allowed source without retaining its full body."""

    async def fetch_summary(self, url: str) -> str | None:
        """Return a concise summary already available to the provider.

        Implementations must not bypass paywalls, login walls, robots controls,
        or fetch arbitrary result pages merely because a URL appeared in search.
        """

    def extract_patterns(
        self,
        source_documents: list[TrendSearchResult],
        niche: str,
    ) -> list[TrendSearchResult]:
        """Return source documents enriched only with high-level pattern identifiers."""

    def diagnostics(self) -> dict[str, Any]:
        """Return JSON-safe provider attempts, warnings, and errors."""

    async def close(self) -> None:
        """Release provider resources without requiring callers to know its implementation."""

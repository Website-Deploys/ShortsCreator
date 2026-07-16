"""Safe trend-research provider implementations and factory."""

from __future__ import annotations

import html
import os
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from olympus.platform.config.settings import TrendResearchSettings
from olympus.trends.contracts import TrendResearchProvider, TrendSearchResult
from olympus.trends.library import PATTERN_LIBRARY
from olympus.trends.live_http import SafeTrendHttpClient, TrendFetchError
from olympus.trends.sources import OFFICIAL_TREND_SOURCES, OfficialTrendSource
from olympus.trends.url_safety import (
    AddressResolver,
    TrendUrlSafetyError,
    domain_matches,
    validate_trend_url,
)

_SOURCE_TYPES = frozenset(
    {
        "official_platform_docs",
        "creator_platform_blog",
        "industry_report",
        "social_media_marketing_blog",
        "public_article",
        "search_result_summary",
        "evergreen_fallback",
        "internal_heuristic",
    }
)


class _ProviderBase:
    """Shared diagnostics and compatibility methods for provider implementations."""

    name = "base"
    live = False

    def __init__(self) -> None:
        self._internet_available = False
        self._attempted = False
        self._warnings: list[str] = []
        self._errors: list[str] = []

    @property
    def provider_name(self) -> str:
        return self.name

    @property
    def internet_available(self) -> bool:
        return self._internet_available

    async def fetch(self, url: str) -> TrendSearchResult | None:
        summary = await self.fetch_summary(url)
        if summary is None:
            return None
        return TrendSearchResult(
            url=url,
            title="Public trend source",
            summary=summary,
            provider=self.name,
        )

    async def fetch_summary(self, url: str) -> str | None:
        del url
        return None

    def extract_patterns(
        self,
        source_documents: list[TrendSearchResult],
        niche: str,
    ) -> list[TrendSearchResult]:
        del niche
        return source_documents

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "attempted": self._attempted,
            "internet_available": self._internet_available,
            "warnings": list(self._warnings),
            "errors": list(self._errors),
        }

    async def close(self) -> None:
        return None


class StaticEvergreenTrendProvider(_ProviderBase):
    """Offline provider marker used by the bundled evergreen library."""

    name = "evergreen"
    live = False

    def __init__(self) -> None:
        super().__init__()

    async def is_available(self) -> bool:
        return True

    async def search(self, query: str, *, max_results: int) -> list[TrendSearchResult]:
        del query, max_results
        return []

    async def fetch_summary(self, url: str) -> str | None:
        del url
        return None


class MockTrendResearchProvider(_ProviderBase):
    """Deterministic provider for tests; it never performs network I/O."""

    name = "mock"
    live = True

    def __init__(
        self,
        results: list[TrendSearchResult] | None = None,
        *,
        available: bool = True,
        fail: bool = False,
    ) -> None:
        super().__init__()
        self._results = list(results or [])
        self._available = available
        self._fail = fail

    async def is_available(self) -> bool:
        return self._available

    async def search(self, query: str, *, max_results: int) -> list[TrendSearchResult]:
        del query
        self._attempted = True
        if self._fail:
            raise RuntimeError("mock trend provider failure")
        return self._results[: max(0, max_results)]

    async def fetch_summary(self, url: str) -> str | None:
        for result in self._results:
            if result.url == url:
                return result.summary
        return None


class DisabledTrendProvider(_ProviderBase):
    """Explicit provider used when trend research is disabled."""

    name = "disabled"
    live = False

    def __init__(self) -> None:
        super().__init__()

    async def is_available(self) -> bool:
        return False

    async def search(self, query: str, *, max_results: int) -> list[TrendSearchResult]:
        del query, max_results
        return []

    async def fetch_summary(self, url: str) -> str | None:
        del url
        return None


class OfficialSourceTrendProvider(_ProviderBase):
    """Refresh a small allowlisted registry of public official guidance pages."""

    name = "official_source"
    live = True

    def __init__(
        self,
        settings: TrendResearchSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: AddressResolver | None = None,
        sources: Sequence[OfficialTrendSource] = OFFICIAL_TREND_SOURCES,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._sources = tuple(sources)
        self._http = SafeTrendHttpClient(
            settings,
            transport=transport,
            resolver=resolver,
        )
        self._results: dict[str, TrendSearchResult] = {}
        self._refreshed = False

    async def is_available(self) -> bool:
        if not self._settings.enabled or not self._settings.allow_official_source_refresh:
            return False
        return any(self._source_is_allowed(source.url) for source in self._sources)

    async def search(self, query: str, *, max_results: int) -> list[TrendSearchResult]:
        self._attempted = True
        if not self._refreshed:
            await self._refresh_sources()
        query_lower = query.lower()
        matching = [
            result
            for result in self._results.values()
            if _query_matches_source(query_lower, result)
        ]
        candidates = matching or list(self._results.values())
        return candidates[: max(0, max_results)]

    async def fetch(self, url: str) -> TrendSearchResult | None:
        if not self._refreshed:
            await self._refresh_sources()
        return self._results.get(url)

    async def fetch_summary(self, url: str) -> str | None:
        result = await self.fetch(url)
        return result.summary if result is not None else None

    async def _refresh_sources(self) -> None:
        self._refreshed = True
        for source in self._sources[: self._settings.max_sources_per_snapshot]:
            if not self._source_is_allowed(source.url):
                self._warnings.append(f"{source.source_id}: source rejected by URL policy")
                continue
            try:
                document = await self._http.fetch_text(source.url, enforce_allowlist=True)
                visible = _transient_visible_text(document.text)
                if len(visible) < 80:
                    raise TrendFetchError(
                        "INSUFFICIENT_PUBLIC_TEXT",
                        "The official source did not expose enough public text to validate.",
                    )
                if _looks_restricted(visible):
                    raise TrendFetchError(
                        "RESTRICTED_SOURCE",
                        "The official source presented a login or access restriction.",
                    )
                published_at = _http_date_to_iso(document.last_modified)
                level, credibility, recency = score_source_credibility(
                    source.url,
                    source.source_type,
                    published_at=published_at,
                    declared_credibility=source.credibility,
                )
                self._results[source.url] = TrendSearchResult(
                    url=source.url,
                    title=source.title,
                    summary=source.pattern_summary,
                    source_type=source.source_type,
                    credibility=credibility,
                    credibility_level=level,
                    published_at=published_at,
                    recency_score=recency,
                    provider=self.name,
                    patterns_supported=source.patterns_supported,
                    warning=(
                        "Live official source fetched; only an original pattern-level "
                        "summary was persisted."
                    ),
                    warnings=(source.notes,),
                )
            except (TrendFetchError, TrendUrlSafetyError) as exc:
                code = getattr(exc, "code", type(exc).__name__)
                self._warnings.append(f"{source.source_id}: {code}")
        self._internet_available = bool(self._results)
        if not self._results:
            self._errors.append("No official source could be refreshed safely.")

    def _source_is_allowed(self, url: str) -> bool:
        try:
            validate_trend_url(
                url,
                allowed_domains=self._settings.allowed_domains,
                blocked_domains=self._settings.blocked_domains,
                allowlist_enabled=self._settings.source_allowlist_enabled,
            )
        except TrendUrlSafetyError:
            return False
        return True


class ConfiguredWebTrendResearchProvider(_ProviderBase):
    """Optional adapter for an administrator-configured JSON search endpoint.

    Olympus calls only the configured search endpoint and persists short result
    summaries. It deliberately does not fetch arbitrary result pages, supply
    cookies, bypass access controls, or ingest article/video bodies.

    Expected response shape::

        {"results": [{"url": "https://...", "title": "...", "snippet": "..."}]}

    A top-level list of result objects is also accepted.
    """

    name = "configured_web"
    live = True

    def __init__(
        self,
        settings: TrendResearchSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: AddressResolver | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._http = SafeTrendHttpClient(
            settings,
            transport=transport,
            resolver=resolver,
        )
        self._summaries: dict[str, str] = {}
        self._results: dict[str, TrendSearchResult] = {}

    async def is_available(self) -> bool:
        endpoint = self._endpoint()
        enabled = (
            self._settings.allow_configured_web_search
            or self._settings.allow_live_web_provider
        )
        if not enabled or not endpoint or not _safe_configured_endpoint(
            endpoint,
            self._settings,
        ):
            return False
        key_env = self._settings.configured_search_api_key_env.strip()
        return not key_env or bool(_configured_api_key(self._settings))

    async def search(self, query: str, *, max_results: int) -> list[TrendSearchResult]:
        if not await self.is_available():
            return []
        endpoint = self._endpoint()
        if not endpoint:
            return []
        self._attempted = True
        headers = {
            "Accept": "application/json",
        }
        api_key = _configured_api_key(self._settings)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload: Any = await self._http.fetch_json(
            endpoint,
            params={"q": query, "limit": max(1, max_results)},
            headers=headers,
            enforce_allowlist=False,
        )
        self._internet_available = True
        raw_results = payload.get("results", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_results, list):
            self._warnings.append("Configured search returned no result list.")
            return []
        results: list[TrendSearchResult] = []
        for raw in raw_results[: max(0, max_results)]:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            if not _safe_public_result_url(url, self._settings):
                self._warnings.append("A configured search result was rejected by URL policy.")
                continue
            title = str(raw.get("title") or "Public trend source").strip()
            source_type = str(raw.get("source_type") or "search_result_summary")
            if source_type not in _SOURCE_TYPES:
                source_type = "search_result_summary"
            supported = raw.get("patterns_supported")
            declared_patterns = (
                tuple(
                    str(item)
                    for item in supported
                    if isinstance(item, str) and item in PATTERN_LIBRARY
                )
                if isinstance(supported, list)
                else ()
            )
            transient_text = str(raw.get("summary") or raw.get("snippet") or "").strip()
            fetched_warning: str | None = None
            if self._settings.fetch_configured_result_pages:
                try:
                    document = await self._http.fetch_text(url, enforce_allowlist=True)
                    visible = _transient_visible_text(document.text)
                    if _looks_restricted(visible):
                        raise TrendFetchError(
                            "RESTRICTED_SOURCE",
                            "The configured result requires login or restricted access.",
                        )
                    transient_text = f"{transient_text} {visible[:50_000]}"
                    fetched_warning = (
                        "The allowlisted public page was fetched transiently; "
                        "its body was not stored."
                    )
                except (TrendFetchError, TrendUrlSafetyError) as exc:
                    code = getattr(exc, "code", type(exc).__name__)
                    fetched_warning = (
                        f"Target page fetch skipped safely ({code})."
                    )
            summary, inferred_patterns = _pattern_level_summary(
                f"{title} {transient_text}",
                declared_patterns,
            )
            pattern_ids = tuple(dict.fromkeys((*declared_patterns, *inferred_patterns)))
            published_at = _normalize_published_at(
                raw.get("published_date") or raw.get("published_at")
            )
            declared_credibility = raw.get("credibility")
            level, credibility, recency = score_source_credibility(
                url,
                source_type,
                published_at=published_at,
                declared_credibility=(
                    float(declared_credibility)
                    if isinstance(declared_credibility, int | float)
                    else None
                ),
            )
            result = TrendSearchResult(
                url=url,
                title=title,
                summary=summary,
                source_type=source_type,
                credibility=credibility,
                credibility_level=level,
                published_at=published_at,
                recency_score=recency,
                provider=self._settings.configured_search_provider_name or self.name,
                patterns_supported=pattern_ids,
                warning=(
                    fetched_warning
                    or "Search metadata was reduced to an original pattern-level summary; "
                    "Olympus did not fetch the target page."
                ),
            )
            results.append(result)
            self._summaries[url] = summary
            self._results[url] = result
        return results

    async def fetch(self, url: str) -> TrendSearchResult | None:
        return self._results.get(url)

    async def fetch_summary(self, url: str) -> str | None:
        return self._summaries.get(url)

    def diagnostics(self) -> dict[str, Any]:
        return {
            **super().diagnostics(),
            "configured_provider_name": self._settings.configured_search_provider_name,
        }

    def _endpoint(self) -> str | None:
        return self._settings.configured_search_endpoint or self._settings.web_search_endpoint


class CascadingTrendResearchProvider(_ProviderBase):
    """Try configured live research first, then the official-source provider."""

    live = True
    name = "live_cascade"

    def __init__(self, providers: Sequence[TrendResearchProvider]) -> None:
        super().__init__()
        self._providers = tuple(providers)
        self._available: list[TrendResearchProvider] = []
        self._active: TrendResearchProvider | None = None

    @property
    def internet_available(self) -> bool:
        return bool(self._active and self._active.internet_available)

    async def is_available(self) -> bool:
        self._available = []
        for provider in self._providers:
            if await provider.is_available():
                self._available.append(provider)
        self._active = self._available[0] if self._available else None
        self.name = self._active.name if self._active is not None else "live_cascade"
        return bool(self._available)

    async def search(self, query: str, *, max_results: int) -> list[TrendSearchResult]:
        self._attempted = True
        providers = self._available or list(self._providers)
        for provider in providers:
            try:
                results = await provider.search(query, max_results=max_results)
            except Exception as exc:
                self._warnings.append(
                    f"Provider '{provider.name}' failed safely ({type(exc).__name__})."
                )
                continue
            if results:
                self._active = provider
                self.name = provider.name
                return results
            self._warnings.append(f"Provider '{provider.name}' returned no safe sources.")
        return []

    async def fetch(self, url: str) -> TrendSearchResult | None:
        return await self._active.fetch(url) if self._active is not None else None

    async def fetch_summary(self, url: str) -> str | None:
        return await self._active.fetch_summary(url) if self._active is not None else None

    def extract_patterns(
        self,
        source_documents: list[TrendSearchResult],
        niche: str,
    ) -> list[TrendSearchResult]:
        if self._active is None:
            return source_documents
        return self._active.extract_patterns(source_documents, niche)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "attempted": self._attempted,
            "internet_available": self.internet_available,
            "attempted_providers": [provider.name for provider in self._providers],
            "warnings": [
                *self._warnings,
                *[
                    warning
                    for provider in self._providers
                    for warning in provider.diagnostics().get("warnings", [])
                    if isinstance(warning, str)
                ],
            ],
            "errors": [
                error
                for provider in self._providers
                for error in provider.diagnostics().get("errors", [])
                if isinstance(error, str)
            ],
        }

    async def close(self) -> None:
        for provider in self._providers:
            await provider.close()


def build_trend_research_provider(
    settings: TrendResearchSettings,
) -> TrendResearchProvider:
    """Build the configured provider without making network requests."""

    if not settings.enabled:
        return DisabledTrendProvider()
    provider_name = settings.provider.strip().lower()
    if provider_name in {"configured_web", "configured_search"}:
        configured = ConfiguredWebTrendResearchProvider(settings)
        if settings.allow_official_source_refresh:
            return CascadingTrendResearchProvider(
                (configured, OfficialSourceTrendProvider(settings))
            )
        return configured
    if provider_name in {"official", "official_source"}:
        return OfficialSourceTrendProvider(settings)
    return StaticEvergreenTrendProvider()


def _safe_configured_endpoint(
    url: str,
    settings: TrendResearchSettings | None = None,
) -> bool:
    try:
        validate_trend_url(
            url,
            blocked_domains=settings.blocked_domains if settings is not None else (),
            allowlist_enabled=False,
            require_https=True,
        )
    except TrendUrlSafetyError:
        return False
    return True


def _safe_public_result_url(url: str, settings: TrendResearchSettings) -> bool:
    try:
        validate_trend_url(
            url,
            allowed_domains=settings.allowed_domains,
            blocked_domains=settings.blocked_domains,
            allowlist_enabled=settings.source_allowlist_enabled,
        )
    except TrendUrlSafetyError:
        return False
    return True


def score_source_credibility(
    url: str,
    source_type: str,
    *,
    published_at: str | None,
    declared_credibility: float | None = None,
    now: datetime | None = None,
) -> tuple[str, float, float]:
    """Return credibility label, bounded score, and recency score."""

    domain = (urlparse(url).hostname or "").lower()
    official = any(
        domain_matches(domain, candidate)
        for candidate in (
            "youtube.com",
            "support.google.com",
            "blog.youtube",
            "creatoracademy.youtube.com",
            "about.instagram.com",
            "creators.instagram.com",
            "newsroom.tiktok.com",
            "ads.tiktok.com",
        )
    )
    if official and source_type in {"official_platform_docs", "creator_platform_blog"}:
        level, baseline = "high", 0.93
    elif source_type in {"industry_report", "social_media_marketing_blog"}:
        level, baseline = "medium", 0.7
    elif source_type == "public_article":
        level, baseline = "low", 0.45
    else:
        level, baseline = "unknown", 0.35
    declared = (
        max(0.0, min(1.0, declared_credibility))
        if declared_credibility is not None
        else baseline
    )
    if level == "high":
        credibility = max(0.85, min(0.98, declared))
    elif level == "medium":
        credibility = max(0.55, min(0.79, declared))
    elif level == "low":
        credibility = max(0.25, min(0.49, declared))
    else:
        credibility = max(0.2, min(0.45, declared))
    recency = _recency_score(published_at, official=official, now=now)
    return level, round(credibility, 3), round(recency, 3)


def _configured_api_key(settings: TrendResearchSettings) -> str | None:
    variable = settings.configured_search_api_key_env.strip()
    if variable:
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]{1,127}", variable):
            return None
        return os.getenv(variable) or None
    if settings.web_search_api_key is not None:
        return settings.web_search_api_key.get_secret_value()
    return None


def _pattern_level_summary(
    transient_text: str,
    declared_patterns: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    normalized = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", transient_text)).lower().split())
    pattern_ids = list(declared_patterns)
    for pattern_id, pattern in PATTERN_LIBRARY.items():
        cues = pattern.get("match_cues") or pattern.get("cues") or []
        if any(str(cue).lower() in normalized for cue in cues if str(cue).strip()):
            pattern_ids.append(pattern_id)
    supported = tuple(dict.fromkeys(pattern_ids))[:12]
    labels = [
        str(PATTERN_LIBRARY[pattern_id].get("label") or pattern_id.replace("_", " "))
        for pattern_id in supported[:4]
    ]
    if labels:
        summary = (
            "The public source metadata supports high-level guidance around "
            + ", ".join(labels)
            + ". Olympus retained this structural summary instead of source wording."
        )
    else:
        summary = (
            "The public source metadata concerns short-form guidance, but no specific "
            "high-level pattern was verified from its bounded metadata."
        )
    return summary, supported


def _transient_visible_text(value: str) -> str:
    without_scripts = re.sub(
        r"<(script|style|noscript)\b[^>]*>.*?</\1>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", without_scripts)).split())[:50_000]


def _looks_restricted(value: str) -> bool:
    prefix = value[:2_000].lower()
    return any(
        marker in prefix
        for marker in (
            "sign in to continue",
            "log in to continue",
            "access denied",
            "members only",
            "subscription required",
            "enable cookies to continue",
        )
    )


def _query_matches_source(query: str, result: TrendSearchResult) -> bool:
    domain = (urlparse(result.url).hostname or "").lower()
    if "youtube" in query:
        return "youtube" in domain or "google.com" in domain
    if "instagram" in query:
        return "instagram.com" in domain
    if "tiktok" in query:
        return "tiktok.com" in domain
    return True


def _http_date_to_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _normalize_published_at(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _recency_score(
    published_at: str | None,
    *,
    official: bool,
    now: datetime | None,
) -> float:
    if not published_at:
        return 0.72 if official else 0.35
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.72 if official else 0.35
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    age_days = max(0.0, ((now or datetime.now(UTC)) - published).total_seconds() / 86_400)
    if age_days <= 30:
        return 0.95
    if age_days <= 90:
        return 0.82
    if age_days <= 365:
        return 0.62
    return 0.38 if official else 0.25


EvergreenTrendProvider = StaticEvergreenTrendProvider
ConfiguredWebSearchTrendProvider = ConfiguredWebTrendResearchProvider

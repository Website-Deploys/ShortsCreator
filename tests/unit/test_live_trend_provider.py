"""Live Runtime Internet Trend Provider V2 safety and integration tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from olympus.data.storage.local import LocalStorage
from olympus.platform.config.settings import TrendResearchSettings
from olympus.trends import (
    CascadingTrendResearchProvider,
    ConfiguredWebTrendResearchProvider,
    DisabledTrendProvider,
    OfficialSourceTrendProvider,
    StaticEvergreenTrendProvider,
    TrendResearchEngine,
    TrendSearchResult,
    TrendSnapshotStore,
    build_evergreen_snapshot,
    build_trend_query_plan,
    build_trend_research_provider,
    score_source_credibility,
    validate_trend_url,
)
from olympus.trends.live_http import SafeTrendHttpClient, TrendFetchError
from olympus.trends.sources import OfficialTrendSource
from olympus.trends.url_safety import TrendUrlSafetyError

_PUBLIC_IP = "142.250.72.206"
_OFFICIAL_URL = "https://support.google.com/youtube/answer/11914225?hl=en"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


def _resolver(hostname: str) -> tuple[str, ...]:
    del hostname
    return (_PUBLIC_IP,)


def _official_source(url: str = _OFFICIAL_URL) -> OfficialTrendSource:
    return OfficialTrendSource(
        source_id="official_test",
        url=url,
        title="Official short-form guidance",
        platform="youtube_shorts",
        source_type="official_platform_docs",
        niche_relevance=("all",),
        refresh_ttl_hours=168,
        credibility=0.96,
        patterns_supported=("question_hook", "quick_context"),
        pattern_summary=(
            "Official guidance supports a clear question, concise context, and a complete answer."
        ),
        notes="Mocked official source for deterministic tests.",
    )


def _official_settings(**updates: object) -> TrendResearchSettings:
    defaults: dict[str, object] = {
        "provider": "official_source",
        "allow_official_source_refresh": True,
        "allowed_domains": ["support.google.com"],
        "source_allowlist_enabled": True,
    }
    defaults.update(updates)
    return TrendResearchSettings(**defaults)


def test_provider_selection_disabled_evergreen_official_and_configured() -> None:
    disabled = build_trend_research_provider(TrendResearchSettings(enabled=False))
    evergreen = build_trend_research_provider(TrendResearchSettings(provider="evergreen"))
    official = build_trend_research_provider(_official_settings())
    configured = build_trend_research_provider(
        TrendResearchSettings(
            provider="configured_web",
            allow_configured_web_search=True,
            allow_official_source_refresh=True,
            configured_search_endpoint="https://search.example.net/v1",
        )
    )

    assert isinstance(disabled, DisabledTrendProvider)
    assert isinstance(evergreen, StaticEvergreenTrendProvider)
    assert isinstance(official, OfficialSourceTrendProvider)
    assert isinstance(configured, CascadingTrendResearchProvider)


async def test_configured_search_unavailable_without_endpoint_or_required_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_endpoint = ConfiguredWebTrendResearchProvider(
        TrendResearchSettings(
            provider="configured_web",
            allow_configured_web_search=True,
        )
    )
    monkeypatch.delenv("OLYMPUS_TEST_SEARCH_KEY", raising=False)
    missing_key = ConfiguredWebTrendResearchProvider(
        TrendResearchSettings(
            provider="configured_web",
            allow_configured_web_search=True,
            configured_search_endpoint="https://search.example.net/v1",
            configured_search_api_key_env="OLYMPUS_TEST_SEARCH_KEY",
        )
    )

    assert await missing_endpoint.is_available() is False
    assert await missing_key.is_available() is False


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/private",
        "http://127.0.0.1/private",
        "http://10.0.0.4/private",
        "http://169.254.1.1/private",
        "file:///etc/passwd",
        "data:text/plain,private",
        "javascript:alert(1)",
        "ftp://example.com/file",
    ],
)
def test_url_safety_rejects_local_private_and_unsupported_urls(url: str) -> None:
    with pytest.raises(TrendUrlSafetyError):
        validate_trend_url(url, allowlist_enabled=False)


def test_url_safety_enforces_allowlist_and_accepts_official_domain() -> None:
    assert (
        validate_trend_url(
            _OFFICIAL_URL,
            allowed_domains=["support.google.com"],
            allowlist_enabled=True,
        )
        == "support.google.com"
    )
    with pytest.raises(TrendUrlSafetyError, match="allowlist"):
        validate_trend_url(
            "https://untrusted.example.org/report",
            allowed_domains=["support.google.com"],
            allowlist_enabled=True,
        )


async def test_redirect_to_private_host_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client = SafeTrendHttpClient(
        _official_settings(source_allowlist_enabled=False),
        transport=httpx.MockTransport(handler),
        resolver=_resolver,
    )
    with pytest.raises(TrendUrlSafetyError):
        await client.fetch_text("https://public.example.org/start", enforce_allowlist=False)


async def test_official_provider_fetches_but_persists_only_pattern_summary() -> None:
    copied_marker = "UNIQUE_SOURCE_SENTENCE_THAT_MUST_NOT_BE_PERSISTED"

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            "<html><body><main>Official creator guidance "
            + copied_marker
            + " "
            + ("viewer retention and clear answers " * 10)
            + "</main></body></html>"
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "last-modified": "Wed, 01 Jul 2026 10:00:00 GMT"},
            text=body,
        )

    provider = OfficialSourceTrendProvider(
        _official_settings(),
        transport=httpx.MockTransport(handler),
        resolver=_resolver,
        sources=(_official_source(),),
    )
    results = await provider.search("YouTube Shorts official guidance", max_results=3)

    assert provider.internet_available is True
    assert len(results) == 1
    assert copied_marker not in results[0].summary
    assert results[0].summary == _official_source().pattern_summary
    assert results[0].credibility_level == "high"
    assert results[0].patterns_supported


async def test_official_provider_handles_timeout_huge_and_partial_sources() -> None:
    second_url = "https://support.google.com/youtube/answer/16559651?hl=en"

    def partial_handler(request: httpx.Request) -> httpx.Response:
        if "16559651" in str(request.url):
            return httpx.Response(500, headers={"content-type": "text/html"}, text="failed")
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>" + ("clear official guidance " * 10) + "</body></html>",
        )

    partial = OfficialSourceTrendProvider(
        _official_settings(),
        transport=httpx.MockTransport(partial_handler),
        resolver=_resolver,
        sources=(_official_source(), _official_source(second_url)),
    )
    partial_results = await partial.search("official", max_results=4)

    def huge_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": "300000"},
            text="small",
        )

    huge = OfficialSourceTrendProvider(
        _official_settings(max_fetch_bytes=20_000),
        transport=httpx.MockTransport(huge_handler),
        resolver=_resolver,
        sources=(_official_source(),),
    )
    huge_results = await huge.search("official", max_results=2)

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    timeout = OfficialSourceTrendProvider(
        _official_settings(),
        transport=httpx.MockTransport(timeout_handler),
        resolver=_resolver,
        sources=(_official_source(),),
    )
    timeout_results = await timeout.search("official", max_results=2)

    assert len(partial_results) == 1
    assert partial.diagnostics()["warnings"]
    assert huge_results == []
    assert "RESPONSE_TOO_LARGE" in " ".join(huge.diagnostics()["warnings"])
    assert timeout_results == []
    assert "REQUEST_TIMEOUT" in " ".join(timeout.diagnostics()["warnings"])


async def test_configured_search_maps_safe_metadata_without_copying_snippet() -> None:
    copied_marker = "EXACT_SEARCH_SNIPPET_MUST_NOT_SURVIVE"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "results": [
                {
                    "url": _OFFICIAL_URL,
                    "title": "Official retention guidance",
                    "snippet": f"Why quick context helps {copied_marker}",
                    "published_date": "2026-07-01T00:00:00Z",
                    "source_type": "official_platform_docs",
                },
                {
                    "url": "https://untrusted.example.org/listicle",
                    "title": "Rejected result",
                    "snippet": "copy this exact title",
                },
            ]
        }
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=payload,
        )

    settings = TrendResearchSettings(
        provider="configured_web",
        allow_configured_web_search=True,
        configured_search_endpoint="https://search.example.net/v1",
        allowed_domains=["support.google.com"],
    )
    provider = ConfiguredWebTrendResearchProvider(
        settings,
        transport=httpx.MockTransport(handler),
        resolver=_resolver,
    )
    results = await provider.search("retention patterns", max_results=5)

    assert provider.internet_available is True
    assert len(results) == 1
    assert copied_marker not in results[0].summary
    assert len(results[0].summary) < 320
    assert results[0].patterns_supported
    assert results[0].credibility_level == "high"
    assert results[0].provider == "custom"


async def test_configured_search_malformed_json_fails_safely() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"not-json",
        )

    provider = ConfiguredWebTrendResearchProvider(
        TrendResearchSettings(
            provider="configured_web",
            allow_configured_web_search=True,
            configured_search_endpoint="https://search.example.net/v1",
        ),
        transport=httpx.MockTransport(handler),
        resolver=_resolver,
    )
    with pytest.raises(TrendFetchError, match="malformed JSON"):
        await provider.search("patterns", max_results=2)


def test_source_credibility_uses_domain_type_and_recency() -> None:
    high = score_source_credibility(
        _OFFICIAL_URL,
        "official_platform_docs",
        published_at="2026-07-01T00:00:00+00:00",
        now=datetime(2026, 7, 13, tzinfo=UTC),
    )
    low = score_source_credibility(
        "https://random-blog.example.org/post",
        "public_article",
        published_at=None,
        declared_credibility=0.95,
        now=datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert high[0] == "high"
    assert high[1] > low[1]
    assert high[2] > low[2]


async def test_engine_truth_cache_force_refresh_and_stale_fallback(
    storage: LocalStorage,
) -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    settings = TrendResearchSettings(provider="mock", stale_cache_allowed_hours=336)
    first = await TrendResearchEngine(
        settings,
        MockProviderResult("https://example.org/first"),
    ).research(
        storage,
        project_id=None,
        transcript="Why quick context leads to the answer.",
        detected_niche={"primary": "education_tutorial"},
        now=now,
    )
    refreshed = await TrendResearchEngine(
        settings,
        MockProviderResult("https://example.org/second"),
    ).research(
        storage,
        project_id=None,
        transcript="Why quick context leads to the answer.",
        detected_niche={"primary": "education_tutorial"},
        force_refresh=True,
        now=now + timedelta(hours=1),
    )
    stale = await TrendResearchEngine(
        settings,
        MockProviderResult("https://example.org/unused", available=False),
    ).research(
        storage,
        project_id=None,
        transcript="Why quick context leads to the answer.",
        detected_niche={"primary": "education_tutorial"},
        now=now + timedelta(hours=74),
    )

    assert first["cache_status"] == "live_refreshed"
    assert refreshed["cache_status"] == "live_refreshed"
    assert refreshed["snapshot_id"] != first["snapshot_id"]
    assert stale["cache_status"] == "stale_fallback"
    assert stale["live_research_attempted"] is True
    assert stale["live_research_succeeded"] is False
    assert stale["internet_available"] is False


class MockProviderResult:
    """Minimal deterministic provider used to exercise engine cache semantics."""

    name = "mock_live"
    live = True
    internet_available = False

    def __init__(self, url: str, *, available: bool = True) -> None:
        self._url = url
        self._available = available

    @property
    def provider_name(self) -> str:
        return self.name

    async def is_available(self) -> bool:
        return self._available

    async def search(self, query: str, *, max_results: int) -> list[TrendSearchResult]:
        del query, max_results
        return [
            TrendSearchResult(
                url=self._url,
                title="Pattern report",
                summary="Why quick context supports a satisfying answer.",
                credibility=0.8,
                credibility_level="medium",
                recency_score=0.9,
                patterns_supported=("question_hook", "quick_context", "satisfying_answer"),
            )
        ]

    async def fetch(self, url: str) -> TrendSearchResult | None:
        del url
        return None

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

    def diagnostics(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "attempted": True,
            "internet_available": False,
            "warnings": [],
            "errors": [],
        }

    async def close(self) -> None:
        return None


def test_live_provider_cli_self_check_and_offline_modes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "tools/validate_live_trend_provider.py"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["OLYMPUS_STORAGE__LOCAL_ROOT"] = str(tmp_path / "storage")
    env["OLYMPUS_TREND_RESEARCH__CACHE_DIR"] = "trend_cache"
    report_dir = tmp_path / "reports"

    self_check = subprocess.run(
        [*command, "--self-check", "--report-dir", str(report_dir)],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    offline = subprocess.run(
        [
            *command,
            "--offline",
            "--niche",
            "motivational",
            "--report-dir",
            str(report_dir),
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert self_check.returncode == 0, self_check.stderr
    assert offline.returncode == 0, offline.stderr
    self_report = json.loads(self_check.stdout[self_check.stdout.find("{") :])
    offline_report = json.loads(offline.stdout[offline.stdout.find("{") :])
    assert self_report["live_trend_provider_validation_v2"]["live_attempted"] is False
    assert offline_report["live_trend_provider_validation_v2"]["fallback_used"] is True
    assert offline_report["live_trend_provider_validation_v2"]["internet_available"] is False
    assert (report_dir / "live_trend_provider_validation_v2_self_check.json").is_file()


async def test_live_provider_cli_cache_mode_reports_no_current_network(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    storage_root = tmp_path / "storage"
    settings = TrendResearchSettings(provider="official_source", cache_dir="trend_cache")
    niche = {"primary": "motivational", "secondary": [], "confidence": 1.0}
    plan = build_trend_query_plan(niche, provider_scope="official_source")
    snapshot = build_evergreen_snapshot(niche, query_plan=plan)
    await TrendSnapshotStore(
        LocalStorage(root=str(storage_root)),
        cache_dir=settings.cache_dir,
    ).save_cache(str(plan["cache_key"]), snapshot)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["OLYMPUS_STORAGE__LOCAL_ROOT"] = str(storage_root)
    env["OLYMPUS_TREND_RESEARCH__CACHE_DIR"] = settings.cache_dir
    process = subprocess.run(
        [
            sys.executable,
            "tools/validate_live_trend_provider.py",
            "--cache",
            "--niche",
            "motivational",
            "--report-dir",
            str(tmp_path / "reports"),
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout[process.stdout.find("{") :])[
        "live_trend_provider_validation_v2"
    ]
    assert report["cache_status"] == "cached"
    assert report["internet_available"] is False
    assert report["live_attempted"] is False

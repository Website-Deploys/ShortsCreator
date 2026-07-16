"""Internet Trend Research V2 contract, cache, provider, and integration tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from olympus.data.storage.local import LocalStorage
from olympus.integration import clip_intelligence as CI  # noqa: N812
from olympus.platform.config.settings import TrendResearchSettings
from olympus.trends import (
    ConfiguredWebTrendResearchProvider,
    MockTrendResearchProvider,
    TrendResearchEngine,
    TrendSearchResult,
    TrendSnapshotStore,
    build_editing_trend_guidance,
    build_evergreen_snapshot,
    build_trend_query_plan,
    detect_content_niche_v2,
    match_trend_patterns,
)
from olympus.trends.library import SUPPORTED_NICHES


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Discipline, failure, mindset and purpose changed my life.", "motivational"),
        ("Our podcast guest answered the interview host's question.", "podcast_interview"),
        ("This tutorial explains how to learn the lesson step by step.", "education_tutorial"),
        ("The gaming stream hit a clutch boss fight and chat said no way.", "gaming_stream"),
        ("I sing this song cover before the final high note.", "music_singing"),
        ("The startup improved revenue, profit, marketing and customer sales.", "business_money"),
        ("Quartz umbrellas crossed a silent orange room.", "unknown_mixed"),
    ],
)
def test_niche_detection_uses_canonical_niches(text: str, expected: str) -> None:
    niche = detect_content_niche_v2(text)

    assert niche["primary"] == expected
    assert niche["primary"] in SUPPORTED_NICHES
    assert 0.0 <= niche["confidence"] <= 1.0
    assert "source_fields_used" in niche


def test_query_plan_is_stable_niche_specific_and_safe() -> None:
    niche = {"primary": "education_tutorial", "confidence": 0.9}
    first = build_trend_query_plan(
        niche,
        max_queries=4,
        now=datetime(2026, 7, 10, tzinfo=UTC),
    )
    second = build_trend_query_plan(
        niche,
        max_queries=4,
        now=datetime(2026, 7, 11, tzinfo=UTC),
    )

    queries = [item["query"].lower() for item in first["queries"]]
    assert len(queries) == 4
    assert "education" in queries[0]
    assert any("official" in query for query in queries)
    assert not any("download viral" in query or "copy script" in query for query in queries)
    assert first["cache_key"] == second["cache_key"]
    assert first["plan_id"] == second["plan_id"]


def _live_result(*, summary: str = "") -> TrendSearchResult:
    return TrendSearchResult(
        url="https://example.org/current-short-form-report",
        title="Current short-form retention report",
        summary=summary
        or "Question hooks, quick context, and satisfying answers support clear retention.",
        source_type="industry_report",
        credibility=0.78,
        patterns_supported=("question_hook", "quick_context", "satisfying_answer"),
    )


async def test_mock_live_provider_builds_attributed_bounded_snapshot(
    storage: LocalStorage,
) -> None:
    provider = MockTrendResearchProvider([_live_result(summary="pattern " * 200)])
    settings = TrendResearchSettings(provider="mock")
    snapshot = await TrendResearchEngine(settings, provider).research(
        storage,
        project_id="proj_trend_live",
        transcript="Why does this work? Here is quick context because the answer matters.",
        content_category="education",
        force_refresh=True,
        now=datetime(2026, 7, 10, tzinfo=UTC),
    )

    assert snapshot["internet_available"] is False
    assert snapshot["live_research_attempted"] is True
    assert snapshot["live_research_succeeded"] is True
    assert snapshot["provider_used"] == "mock"
    assert snapshot["research_status"] in {"completed", "partial"}
    assert snapshot["sources"]
    assert all(len(source["summary"]) <= 320 for source in snapshot["sources"])
    assert all(source["patterns_supported"] for source in snapshot["sources"])
    assert snapshot["extracted_patterns"]
    assert all(pattern["evidence_source_ids"] for pattern in snapshot["extracted_patterns"])
    assert await storage.exists("trend/proj_trend_live/trend_research_v2.json")


async def test_unavailable_and_failing_providers_fall_back_honestly(
    storage: LocalStorage,
) -> None:
    settings = TrendResearchSettings(provider="mock")
    unavailable = await TrendResearchEngine(
        settings,
        MockTrendResearchProvider(available=False),
    ).research(
        storage,
        project_id="proj_unavailable",
        transcript="Discipline and mindset helped after failure.",
        force_refresh=True,
    )
    failed = await TrendResearchEngine(
        settings,
        MockTrendResearchProvider(fail=True),
    ).research(
        storage,
        project_id="proj_failed",
        transcript="Discipline and mindset helped after failure.",
        force_refresh=True,
    )

    for snapshot in (unavailable, failed):
        assert snapshot["fallback_used"] is True
        assert snapshot["cache_status"] == "evergreen_fallback"
        assert snapshot["internet_available"] is False
        assert snapshot["sources"][0]["source_type"] == "evergreen_fallback"
        assert snapshot["fallback_reason"]


async def test_cache_hit_and_expired_refresh_fallback(storage: LocalStorage) -> None:
    settings = TrendResearchSettings(provider="mock")
    now = datetime(2026, 7, 10, tzinfo=UTC)
    first = await TrendResearchEngine(
        settings,
        MockTrendResearchProvider([_live_result()]),
    ).research(
        storage,
        project_id=None,
        transcript="Why does this work? Here is quick context and the answer.",
        content_category="education",
        now=now,
    )
    cached = await TrendResearchEngine(
        settings,
        MockTrendResearchProvider(fail=True),
    ).research(
        storage,
        project_id=None,
        transcript="Why does this work? Here is quick context and the answer.",
        content_category="education",
        now=now + timedelta(hours=1),
    )
    expired = await TrendResearchEngine(
        settings,
        MockTrendResearchProvider(available=False),
    ).research(
        storage,
        project_id=None,
        transcript="Why does this work? Here is quick context and the answer.",
        content_category="education",
        now=now + timedelta(hours=73),
    )

    assert first["cache_status"] == "live_refreshed"
    assert cached["cache_status"] == "cached"
    assert cached["cache_hit"] is True
    assert cached["internet_available"] is False
    assert cached["snapshot_id"] == first["snapshot_id"]
    assert expired["fallback_used"] is True
    assert expired["cache_status"] == "stale_fallback"
    assert "stale" in expired["fallback_reason"]


def test_story_match_editing_and_unified_metadata_are_connected() -> None:
    story = {
        "micro_stories": [
            {
                "story_id": "story_1",
                "story_shape": "problem_solution",
                "completeness_score": 0.88,
                "context_dependency_score": 0.1,
            }
        ]
    }
    niche = detect_content_niche_v2(
        "The biggest mistake was the problem. Because I changed it, that's why it worked.",
        content_category="education",
    )
    snapshot = build_evergreen_snapshot(niche, story_data=story)
    match = match_trend_patterns(
        "The biggest mistake was the problem. Because I changed it, that's why it worked.",
        snapshot,
        niche,
        story_shape="problem_solution",
    )
    editing = build_editing_trend_guidance(snapshot, niche, match)
    unified = CI.unified_clip_intelligence(
        plan={
            "id": "clip_1",
            "scores": {"trend_fit": match["trend_fit_score"]},
            "planning_trend_integration": {"selection_effect": "fallback"},
        },
        blueprint={
            "content_niche": niche,
            "internet_trend_research_v2": snapshot,
            "trend_match_v2": match,
            "editing_trend_guidance": editing,
        },
        editing_v2={"editing_trend_guidance": editing},
    )

    assert snapshot["story_trend_guidance"][0]["story_id"] == "story_1"
    assert match["matched_patterns"]
    assert editing["caption_style"] == "clean_educational_keywords"
    assert editing["sfx_density"] == "low"
    assert unified["trend_research"]["snapshot_id"] == snapshot["snapshot_id"]
    assert unified["trend_research"]["fallback_used"] is True
    assert unified["planning"]["planning_trend_integration"]["selection_effect"] == "fallback"
    assert unified["editing"]["editing_trend_guidance"]["music_mood"]
    json.dumps(unified)


async def test_cache_store_rejects_corrupt_json(storage: LocalStorage) -> None:
    store = TrendSnapshotStore(storage)
    cache_key = "a" * 64
    await storage.put(store.cache_key(cache_key), b"not-json")

    assert await store.load_cache(cache_key) is None


async def test_configured_web_provider_is_disabled_without_safe_endpoint() -> None:
    settings = TrendResearchSettings(
        provider="configured_web",
        allow_live_web_provider=True,
        web_search_endpoint="http://127.0.0.1/private-search",
    )

    assert await ConfiguredWebTrendResearchProvider(settings).is_available() is False


def test_validation_cli_offline_and_cache_modes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "tools/validate_trend_research.py", "--niche", "motivational"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["OLYMPUS_STORAGE__LOCAL_ROOT"] = str(tmp_path / "storage")
    env["OLYMPUS_TREND_RESEARCH__CACHE_DIR"] = "trend_cache"

    offline = subprocess.run(
        [*command, "--offline"],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    cached = subprocess.run(
        [*command, "--cache-only"],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert offline.returncode == 0, offline.stderr
    assert cached.returncode == 0, cached.stderr
    offline_report = json.loads(offline.stdout[offline.stdout.find("{") :])
    cache_report = json.loads(cached.stdout[cached.stdout.find("{") :])
    assert offline_report["trend_validation_report"]["fallback_used"] is True
    assert cache_report["trend_validation_report"]["cache_status"] == "cached"

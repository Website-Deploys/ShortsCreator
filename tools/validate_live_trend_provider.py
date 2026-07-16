"""Validate Live Runtime Internet Trend Provider V2 without processing a video."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from olympus.data.storage import build_storage
from olympus.platform.config import get_settings
from olympus.trends import (
    ConfiguredWebTrendResearchProvider,
    OfficialSourceTrendProvider,
    TrendResearchEngine,
    TrendResearchProvider,
    TrendSnapshotStore,
    build_trend_query_plan,
    build_trend_research_provider,
    snapshot_is_fresh,
    snapshot_is_stale_usable,
    validate_trend_url,
)
from olympus.trends.sources import OFFICIAL_TREND_SOURCES
from olympus.trends.url_safety import TrendUrlSafetyError
from olympus.utils import utc_now

_REPORT_NAME = "live_trend_provider_validation_v2"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--official-source", action="store_true")
    modes.add_argument("--configured-search", action="store_true")
    modes.add_argument("--offline", action="store_true")
    modes.add_argument("--cache", action="store_true")
    parser.add_argument("--niche", default="unknown_mixed")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("work/validation_reports/live_trends"),
    )
    return parser.parse_args()


def _base_report(mode: str, provider_requested: str) -> dict[str, Any]:
    return {
        _REPORT_NAME: {
            "mode": mode,
            "provider_requested": provider_requested,
            "provider_used": None,
            "internet_available": False,
            "live_attempted": False,
            "live_succeeded": False,
            "cache_status": None,
            "fallback_used": False,
            "source_count": 0,
            "domains": [],
            "patterns_count": 0,
            "confidence": 0.0,
            "warnings": [],
            "errors": [],
            "pass_fail": False,
        }
    }


async def run_validation(args: argparse.Namespace) -> dict[str, Any]:
    mode = _mode(args)
    requested = {
        "self_check": "self_check",
        "official_source": "official_source",
        "configured_search": "configured_web",
        "offline": "evergreen",
        "cache": "official_source",
    }[mode]
    report = _base_report(mode, requested)
    output = report[_REPORT_NAME]
    try:
        settings = get_settings().trend_research
        if mode == "self_check":
            _run_self_check(output, settings)
            return report

        trend_settings = settings.model_copy(
            update={
                "enabled": True,
                "provider": requested,
                "fallback_to_evergreen": True,
                "allow_official_source_refresh": True,
                "allow_configured_web_search": mode == "configured_search",
            }
        )
        storage = build_storage()
        niche = {
            "primary": str(args.niche),
            "secondary": [],
            "confidence": 1.0,
            "evidence": ["explicit validation niche"],
            "source": "validation_cli",
        }
        if mode == "cache":
            await _validate_cache(output, storage, trend_settings, niche)
            return report
        provider: TrendResearchProvider
        if mode == "configured_search":
            provider = ConfiguredWebTrendResearchProvider(trend_settings)
            if not await provider.is_available():
                output.update(
                    {
                        "provider_used": provider.name,
                        "warnings": ["CONFIGURED_SEARCH_NOT_CONFIGURED"],
                        "pass_fail": True,
                    }
                )
                return report
        elif mode == "official_source":
            provider = OfficialSourceTrendProvider(trend_settings)
        else:
            provider = build_trend_research_provider(trend_settings)

        snapshot = await TrendResearchEngine(trend_settings, provider).research(
            storage,
            project_id=None,
            transcript="",
            detected_niche=niche,
            force_refresh=args.force_refresh or mode == "offline",
        )
        _apply_snapshot(output, snapshot)
        output["pass_fail"] = bool(snapshot.get("snapshot_id")) and bool(
            snapshot.get("extracted_patterns")
        )
        if mode == "official_source" and not output["live_succeeded"]:
            output["warnings"] = list(
                dict.fromkeys(
                    [
                        *output["warnings"],
                        "Official-source live refresh did not succeed; "
                        "fallback truth is preserved.",
                    ]
                )
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        output["errors"].append(f"{type(exc).__name__}: {exc}")
    return report


def _run_self_check(output: dict[str, Any], settings: Any) -> None:
    default_provider = build_trend_research_provider(type(settings)())
    checks: dict[str, bool] = {
        "default_provider_is_offline": default_provider.live is False,
        "official_registry_present": bool(OFFICIAL_TREND_SOURCES),
    }
    for source in OFFICIAL_TREND_SOURCES:
        try:
            validate_trend_url(
                source.url,
                allowed_domains=settings.allowed_domains,
                blocked_domains=settings.blocked_domains,
                allowlist_enabled=settings.source_allowlist_enabled,
            )
        except TrendUrlSafetyError:
            checks["official_registry_urls_allowed"] = False
            break
    else:
        checks["official_registry_urls_allowed"] = True
    rejected = []
    for unsafe in (
        "http://127.0.0.1/private",
        "http://10.0.0.1/private",
        "file:///etc/passwd",
        "data:text/plain,private",
    ):
        try:
            validate_trend_url(unsafe, allowlist_enabled=False)
        except TrendUrlSafetyError:
            rejected.append(unsafe)
    checks["unsafe_urls_rejected"] = len(rejected) == 4
    output.update(
        {
            "provider_used": "self_check",
            "warnings": [
                "Self-check performs no network request and does not validate current trends."
            ],
            "checks": checks,
            "source_count": len(OFFICIAL_TREND_SOURCES),
            "pass_fail": all(checks.values()),
        }
    )


async def _validate_cache(
    output: dict[str, Any],
    storage: Any,
    settings: Any,
    niche: dict[str, Any],
) -> None:
    plan = build_trend_query_plan(
        niche,
        max_queries=settings.max_queries_per_video,
        max_sources=settings.max_sources_per_snapshot,
        recency_window_days=settings.recency_window_days,
        language=settings.language,
        region=settings.region,
        provider_scope=settings.provider,
    )
    snapshot = await TrendSnapshotStore(storage, cache_dir=settings.cache_dir).load_cache(
        str(plan["cache_key"])
    )
    if snapshot is None:
        output["errors"].append("No official-source cache snapshot exists for this query plan.")
        return
    _apply_snapshot(output, snapshot)
    output["internet_available"] = False
    output["live_attempted"] = False
    output["live_succeeded"] = False
    output["warnings"] = list(
        dict.fromkeys(
            [*output["warnings"], "Cache validation performed no live network request."]
        )
    )
    now = utc_now()
    if snapshot_is_fresh(snapshot, now):
        output["cache_status"] = "cached"
        output["pass_fail"] = True
    elif snapshot_is_stale_usable(
        snapshot,
        now,
        allowed_hours=settings.stale_cache_allowed_hours,
    ):
        output["cache_status"] = "stale"
        output["warnings"].append("The matching cache is stale but inside the allowed window.")
        output["pass_fail"] = True
    else:
        output["cache_status"] = "failed"
        output["errors"].append("The matching cache is expired beyond the allowed stale window.")


def _apply_snapshot(output: dict[str, Any], snapshot: dict[str, Any]) -> None:
    output.update(
        {
            "provider_used": snapshot.get("provider_used"),
            "internet_available": snapshot.get("internet_available") is True,
            "live_attempted": snapshot.get("live_research_attempted") is True,
            "live_succeeded": snapshot.get("live_research_succeeded") is True,
            "cache_status": snapshot.get("cache_status"),
            "fallback_used": snapshot.get("fallback_used") is True,
            "source_count": int(snapshot.get("source_count") or 0),
            "domains": [
                str(domain)
                for domain in snapshot.get("source_domains", [])
                if isinstance(domain, str)
            ],
            "patterns_count": len(snapshot.get("extracted_patterns", [])),
            "confidence": float(snapshot.get("confidence") or 0.0),
            "warnings": [
                str(item) for item in snapshot.get("warnings", []) if isinstance(item, str)
            ],
        }
    )


def _mode(args: argparse.Namespace) -> str:
    if args.self_check:
        return "self_check"
    if args.official_source:
        return "official_source"
    if args.configured_search:
        return "configured_search"
    if args.cache:
        return "cache"
    return "offline"


def _write_report(report: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    mode = str(report[_REPORT_NAME]["mode"])
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (report_dir / f"{_REPORT_NAME}_{mode}.json").write_text(rendered, encoding="utf-8")
    (report_dir / f"{_REPORT_NAME}.json").write_text(rendered, encoding="utf-8")


def main() -> int:
    args = _parse_args()
    report = asyncio.run(run_validation(args))
    _write_report(report, args.report_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report[_REPORT_NAME]["pass_fail"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

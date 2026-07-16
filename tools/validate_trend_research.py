"""Validate Internet Trend Research V2 without processing a video."""

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
    StaticEvergreenTrendProvider,
    TrendResearchEngine,
    TrendResearchProvider,
    TrendSnapshotStore,
    build_trend_query_plan,
    detect_content_niche_v2,
    snapshot_is_fresh,
)
from olympus.utils import utc_now


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--niche", default="unknown_mixed")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--offline", action="store_true")
    modes.add_argument("--cache-only", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--transcript-file", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def _transcript_text(path: Path | None) -> str:
    if path is None:
        return ""
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("segments") or raw.get("transcript") or raw.get("text") or raw
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return " ".join(
            str(item.get("text") or "") if isinstance(item, dict) else str(item)
            for item in raw
        )
    raise ValueError("Transcript file must contain text, a segment list, or a segments object.")


def _base_report(mode: str, niche: str) -> dict[str, Any]:
    return {
        "trend_validation_report": {
            "mode": mode,
            "niche": niche,
            "internet_available": False,
            "live_research_attempted": False,
            "live_research_succeeded": False,
            "provider_used": None,
            "cache_status": None,
            "fallback_used": False,
            "snapshot_created": False,
            "source_count": 0,
            "pattern_count": 0,
            "warnings": [],
            "errors": [],
            "pass_fail": False,
        }
    }


async def run_validation(args: argparse.Namespace) -> dict[str, Any]:
    """Run one validation mode and return the stable report contract."""

    mode = "live" if args.live else "cache_only" if args.cache_only else "offline"
    report = _base_report(mode, str(args.niche))
    output = report["trend_validation_report"]
    try:
        transcript = _transcript_text(args.transcript_file)
        detected = (
            detect_content_niche_v2(transcript)
            if transcript
            else {
                "primary": str(args.niche),
                "secondary": [],
                "confidence": 1.0,
                "evidence": ["explicit validation niche"],
                "source": "validation_cli",
            }
        )
        output["niche"] = detected.get("primary")
        settings = get_settings()
        trend_settings = settings.trend_research.model_copy(
            update={"enabled": True, "fallback_to_evergreen": True}
        )
        storage = build_storage()
        plan = build_trend_query_plan(
            detected,
            max_queries=trend_settings.max_queries_per_video,
            max_sources=trend_settings.max_sources_per_snapshot,
            recency_window_days=trend_settings.recency_window_days,
            language=trend_settings.language,
            region=trend_settings.region,
            provider_scope=trend_settings.provider,
        )
        store = TrendSnapshotStore(storage, cache_dir=trend_settings.cache_dir)

        if args.cache_only:
            snapshot = await store.load_cache(str(plan["cache_key"]))
            if snapshot is None:
                output["errors"].append("No cache snapshot exists for this niche/query plan.")
                return report
            cache_status = "cached" if snapshot_is_fresh(snapshot, utc_now()) else "stale"
            _apply_snapshot(output, snapshot)
            output["cache_status"] = cache_status
            if output["cache_status"] == "stale":
                output["errors"].append("The matching trend cache snapshot is stale.")
            output["snapshot_created"] = False
            output["pass_fail"] = output["cache_status"] == "cached"
            return report

        provider: TrendResearchProvider
        if args.live:
            configured = ConfiguredWebTrendResearchProvider(trend_settings)
            if (
                trend_settings.provider in {"configured_web", "configured_search"}
                and await configured.is_available()
            ):
                provider = configured
            else:
                trend_settings = trend_settings.model_copy(
                    update={
                        "provider": "official_source",
                        "allow_official_source_refresh": True,
                    }
                )
                provider = OfficialSourceTrendProvider(trend_settings)
        else:
            provider = StaticEvergreenTrendProvider()
            trend_settings = trend_settings.model_copy(update={"provider": "evergreen"})

        snapshot = await TrendResearchEngine(trend_settings, provider).research(
            storage,
            project_id=None,
            transcript=transcript,
            detected_niche=detected,
            force_refresh=not args.cache_only,
        )
        _apply_snapshot(output, snapshot)
        output["snapshot_created"] = True
        output["pass_fail"] = bool(snapshot.get("snapshot_id")) and bool(
            snapshot.get("extracted_patterns")
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        output["errors"].append(f"{type(exc).__name__}: {exc}")
    return report


def _apply_snapshot(output: dict[str, Any], snapshot: dict[str, Any]) -> None:
    output["internet_available"] = snapshot.get("internet_available") is True
    output["live_research_attempted"] = snapshot.get("live_research_attempted") is True
    output["live_research_succeeded"] = snapshot.get("live_research_succeeded") is True
    output["provider_used"] = snapshot.get("provider_used")
    output["cache_status"] = snapshot.get("cache_status")
    output["fallback_used"] = snapshot.get("fallback_used") is True
    output["source_count"] = len(snapshot.get("sources", []))
    output["pattern_count"] = len(snapshot.get("extracted_patterns", []))
    output["warnings"] = [
        str(item) for item in snapshot.get("warnings", []) if isinstance(item, str)
    ]


def main() -> int:
    args = _parse_args()
    report = asyncio.run(run_validation(args))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["trend_validation_report"]["pass_fail"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

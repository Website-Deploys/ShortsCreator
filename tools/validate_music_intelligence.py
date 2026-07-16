"""Validate Music Intelligence V2 assets, decisions, and rendered metadata."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from olympus.music import load_music_assets, plan_music_intelligence, resolve_music_intelligence
from olympus.platform.config import get_settings


def _probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        return {"available": False, "reason": completed.stderr.strip() or "ffprobe failed"}
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"available": False, "reason": "ffprobe returned invalid JSON"}
    return {"available": True, **value}


def _simulate(niche: str, story_shape: str, root: Path) -> dict[str, Any]:
    clip = {"clip_id": "simulation", "duration": 30.0}
    blueprint = {
        "content_niche": {"primary": niche},
        "storytelling_v2": {"story_shape": story_shape},
        "hook_analysis_v2": {"category": "curiosity_question"},
        "ending_payoff_v2": {"ending_type": "payoff"},
        "music_decision_v2": {"status": "unavailable", "category": niche},
        "viral_score_v2": {"overall": 0.75},
    }
    bundle = {
        "caption_timing": {
            "captions": [
                {"start": 0.0, "end": 5.0},
                {"start": 5.2, "end": 10.0},
                {"start": 10.4, "end": 16.0},
                {"start": 16.3, "end": 23.0},
                {"start": 23.2, "end": 29.0},
            ]
        },
        "silence_detection": {"silences": [{"start": 10.0, "end": 10.4}]},
    }
    planned = plan_music_intelligence(
        clip=clip,
        blueprint=blueprint,
        bundle=bundle,
        project_id="simulation",
    )
    registry = load_music_assets(root)
    return resolve_music_intelligence(
        planned,
        list(registry.get("safe_assets") or []),
        rejected_assets=list(registry.get("unsafe_assets") or []),
        library_metadata=registry,
    )


def _manifest_music(manifest_path: Path) -> dict[str, Any]:
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}
    if isinstance(value, dict) and isinstance(value.get("data"), dict):
        stage_data = value["data"]
        if isinstance(stage_data.get("manifest"), dict):
            value = stage_data["manifest"]
    renders = value.get("renders") if isinstance(value, dict) else None
    if isinstance(renders, list) and renders:
        metadata = renders[0].get("metadata") if isinstance(renders[0], dict) else None
        if isinstance(metadata, dict):
            return {
                "music_intelligence_v2": metadata.get("music_intelligence_v2"),
                "music_validation": metadata.get("music_validation"),
                "music_mixed": metadata.get("music_mixed"),
            }
    metadata = value.get("metadata") if isinstance(value, dict) else None
    return metadata if isinstance(metadata, dict) else {}


def _report(args: argparse.Namespace) -> dict[str, Any]:
    root = args.asset_root.resolve()
    registry = load_music_assets(root)
    report: dict[str, Any] = {
        "mode": "unknown",
        "assets_found": len(registry.get("assets") or []),
        "safe_assets": len(registry.get("safe_assets") or []),
        "unsafe_assets": len(registry.get("unsafe_assets") or []),
        "curated_assets": len(registry.get("curated_assets") or []),
        "generated_assets": len(registry.get("generated_assets") or []),
        "user_assets": len(registry.get("user_assets") or []),
        "library_version": registry.get("version"),
        "decision": None,
        "selected_asset": None,
        "mix_plan": None,
        "validation": None,
        "warnings": [],
        "pass_fail": False,
    }
    if args.list_assets:
        report.update(
            {
                "mode": "list_assets",
                "assets": registry.get("assets"),
                "pass_fail": bool(registry.get("safe_assets")),
            }
        )
    elif args.analyze_assets:
        analyses = []
        for asset in registry.get("assets") or []:
            path = Path(str(asset.get("path") or ""))
            analyses.append(
                {
                    "asset_id": asset.get("asset_id"),
                    "automatic_use_allowed": asset.get("automatic_use_allowed"),
                    "probe": _probe(path) if path.is_file() else {"available": False},
                    "warnings": asset.get("warnings") or asset.get("rejection_reasons") or [],
                }
            )
        report.update(
            {
                "mode": "analyze_assets",
                "analyses": analyses,
                "pass_fail": bool(analyses)
                and all(item["probe"].get("available") for item in analyses),
            }
        )
    elif args.simulate:
        intelligence = _simulate(args.niche, args.story_shape, root)
        report.update(
            {
                "mode": "simulate",
                "decision": intelligence.get("decision"),
                "selected_asset": intelligence.get("selected_asset"),
                "music_library_selection": intelligence.get(
                    "music_library_selection"
                ),
                "mix_plan": intelligence.get("mix_plan"),
                "music_story_events": intelligence.get("music_story_events"),
                "pass_fail": bool(
                    not intelligence.get("decision", {}).get("should_use_music")
                    or intelligence.get("selected_asset")
                ),
            }
        )
    elif args.rendered_file:
        manifest = _manifest_music(args.manifest) if args.manifest else {}
        validation = manifest.get("music_validation") if isinstance(manifest, dict) else None
        rendered_intelligence = (
            manifest.get("music_intelligence_v2")
            if isinstance(manifest.get("music_intelligence_v2"), dict)
            else {}
        )
        report.update(
            {
                "mode": "rendered_file",
                "render_probe": _probe(args.rendered_file),
                "validation": validation,
                "decision": rendered_intelligence.get("decision"),
                "selected_asset": rendered_intelligence.get("selected_asset"),
                "mix_plan": rendered_intelligence.get("mix_plan"),
                "pass_fail": bool(
                    _probe(args.rendered_file).get("available")
                    and isinstance(validation, dict)
                    and validation.get("passed") is True
                ),
            }
        )
    elif args.project_id:
        storage_root = Path(get_settings().storage.local_root)
        candidates = [
            storage_root / "render" / args.project_id / "manifest.json",
            storage_root
            / "render"
            / args.project_id
            / "run"
            / "stages"
            / "generate_render_manifest.json",
        ]
        manifest_path = next((path for path in candidates if path.exists()), candidates[0])
        project_validation = _manifest_music(manifest_path) if manifest_path.exists() else None
        project_intelligence = (
            project_validation.get("music_intelligence_v2")
            if isinstance(project_validation, dict)
            and isinstance(project_validation.get("music_intelligence_v2"), dict)
            else {}
        )
        report.update(
            {
                "mode": "project",
                "project_id": args.project_id,
                "manifest_path": str(manifest_path),
                "decision": project_intelligence.get("decision"),
                "selected_asset": project_intelligence.get("selected_asset"),
                "mix_plan": project_intelligence.get("mix_plan"),
                "validation": (
                    project_validation.get("music_validation")
                    if isinstance(project_validation, dict)
                    else None
                ),
                "pass_fail": manifest_path.exists(),
            }
        )
        if not manifest_path.exists():
            report["warnings"].append("Project render manifest was not found at the local path.")
    return {"music_validation_report": report}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--list-assets", action="store_true")
    modes.add_argument("--analyze-assets", action="store_true")
    modes.add_argument("--simulate", action="store_true")
    modes.add_argument("--rendered-file", type=Path)
    modes.add_argument("--project-id")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--asset-root", type=Path, default=Path("assets"))
    parser.add_argument("--niche", default="motivational")
    parser.add_argument("--story-shape", default="pain_transformation")
    return parser.parse_args()


def main() -> int:
    report = _report(_parse_args())
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["music_validation_report"]["pass_fail"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

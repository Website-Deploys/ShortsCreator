"""Validate Olympus copyright and platform-readiness risk metadata.

This tool does not fetch media, bypass access controls, determine fair use, or
predict Content ID. It evaluates only supplied/local provenance and manifests.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from olympus.music import load_music_assets
from olympus.platform.config import get_settings
from olympus.safety import CopyrightSafetyChecker, write_copyright_safety_reports
from olympus.safety.contracts import (
    COPYRIGHT_SAFETY_DISCLAIMER,
    CopyrightSafetyReport,
    RiskLevel,
)
from olympus.safety.copyright import check_music

JsonDict = dict[str, Any]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an honest technical copyright/safety risk report.",
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--project-id")
    modes.add_argument("--rendered-file", type=Path)
    modes.add_argument("--music-library", action="store_true")
    modes.add_argument("--source-url")
    modes.add_argument("--simulate", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument(
        "--source",
        choices=("third_party_youtube", "local_user_owned", "generated_test", "unknown"),
        default="third_party_youtube",
    )
    parser.add_argument(
        "--music",
        choices=("generated_safe", "curated_verified", "unknown_license", "none"),
        default="generated_safe",
    )
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("work/validation_reports/copyright_safety"),
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.rendered_file and args.manifest is None:
        parser.error("--rendered-file requires --manifest")
    if args.manifest and args.rendered_file is None:
        parser.error("--manifest requires --rendered-file")
    return args


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    checker = CopyrightSafetyChecker(settings.copyright_safety)
    storage_root = (args.storage_root or Path(settings.storage.local_root)).resolve()
    asset_root = (args.asset_root or Path(settings.rendering.asset_root)).resolve()
    try:
        if args.simulate:
            payload = _simulate(checker, args.source, args.music, args.rights_confirmed)
            mode = "simulate"
        elif args.music_library:
            payload = _music_library(checker, asset_root)
            mode = "music_library"
        elif args.source_url:
            payload = _source_url(checker, args.source_url, args.rights_confirmed)
            mode = "source_url"
        elif args.rendered_file:
            payload = _rendered_manifest(checker, args.rendered_file, args.manifest, storage_root)
            mode = "rendered_manifest"
        else:
            payload = _project(checker, str(args.project_id), storage_root)
            mode = "project"
        payload["validation"] = {
            "mode": mode,
            "completed": True,
            "disclaimer": COPYRIGHT_SAFETY_DISCLAIMER,
        }
        reports = write_copyright_safety_reports(payload, args.report_dir.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        error = {
            "completed": False,
            "error": str(exc),
            "disclaimer": COPYRIGHT_SAFETY_DISCLAIMER,
        }
        if args.debug:
            raise
        print(json.dumps(error, indent=2))
        return 2
    primary = _dict(payload.get("copyright_safety_v2"))
    print(
        json.dumps(
            {
                "mode": mode,
                "risk_level": _dict(primary.get("overall")).get("risk_level"),
                "upload_readiness": _dict(primary.get("overall")).get("upload_readiness"),
                "manual_review_required": _dict(primary.get("manual_review")).get("required"),
                "reports": reports,
                "disclaimer": COPYRIGHT_SAFETY_DISCLAIMER,
            },
            indent=2,
        )
    )
    return 0


def _simulate(
    checker: CopyrightSafetyChecker,
    source_name: str,
    music_name: str,
    rights_confirmed: bool,
) -> JsonDict:
    source = _simulated_source(source_name, rights_confirmed)
    music = _simulated_music(music_name)
    report = checker.check(
        project={"id": "simulation"},
        clip_id="simulation_clip",
        source=source,
        music_asset=music,
        assessment_phase="simulation",
    )
    return {
        "copyright_safety_v2": report,
        "simulation": {
            "source": source_name,
            "music": music_name,
            "rights_confirmed": rights_confirmed,
            "real_project_validation": False,
        },
    }


def _source_url(
    checker: CopyrightSafetyChecker,
    source_url: str,
    rights_confirmed: bool,
) -> JsonDict:
    parsed = urlparse(source_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--source-url must be a valid public http(s) URL; no URL was fetched.")
    report = checker.check(
        project={"id": "source_url_check"},
        source={
            "source_type": "link",
            "source_url": source_url,
            "rights_confirmed": rights_confirmed,
            "rights_basis": "cli_user_confirmation" if rights_confirmed else None,
        },
        assessment_phase="source_only",
    )
    return {
        "copyright_safety_v2": report,
        "source_url_check": {"url_fetched": False, "metadata_only": True},
    }


def _music_library(checker: CopyrightSafetyChecker, asset_root: Path) -> JsonDict:
    library = load_music_assets(asset_root)
    safe_assets = [_dict(item) for item in _list(library.get("safe_assets")) if _dict(item)]
    unsafe_assets = [_dict(item) for item in _list(library.get("unsafe_assets")) if _dict(item)]
    policy = checker.policy
    checks = [check_music(item, used=True, policy=policy) for item in safe_assets]
    blocked_safe_assets = [
        item for item in checks if item.get("risk_level") == RiskLevel.BLOCKED.value
    ]
    report = checker.check(
        project={"id": "music_library_validation"},
        source={"source_type": "generated", "rights_confirmed": True},
        assessment_phase="music_library",
    )
    if blocked_safe_assets:
        report["overall"]["risk_level"] = RiskLevel.BLOCKED.value
        report["overall"]["upload_readiness"] = "blocked"
        report["overall"]["requires_manual_review"] = True
        report["overall"]["can_auto_clear"] = False
        report["result"]["passed"] = False
        report["result"]["errors"] = [
            "An asset exposed as safe automatic music failed license verification."
        ]
    return {
        "copyright_safety_v2": report,
        "music_library": {
            "asset_root": str(asset_root),
            "manifest_path": library.get("manifest_path"),
            "safe_assets_checked": len(safe_assets),
            "unsafe_assets_reported": len(unsafe_assets),
            "blocked_safe_assets": len(blocked_safe_assets),
            "generated_assets_are_validation_quality": bool(
                any(item.get("folder_type") == "generated" for item in safe_assets)
            ),
            "asset_checks": checks,
            "passed": not blocked_safe_assets,
        },
    }


def _rendered_manifest(
    checker: CopyrightSafetyChecker,
    rendered_file: Path,
    manifest_path: Path | None,
    storage_root: Path,
) -> JsonDict:
    if manifest_path is None:
        raise ValueError("A manifest path is required.")
    rendered_file = rendered_file.resolve()
    manifest_path = manifest_path.resolve()
    if not rendered_file.is_file():
        raise ValueError(f"Rendered file does not exist: {rendered_file}")
    manifest = _read_json(manifest_path)
    render = _select_render(manifest, rendered_file)
    project_id = _text(manifest.get("project_id"))
    project = _load_project(storage_root, project_id) if project_id else {}
    link_record = _load_link_record(storage_root, project)
    metadata = _dict(render.get("metadata")) or _dict(manifest.get("metadata"))
    report = checker.check(
        project=project,
        clip_id=_text(render.get("clip_id")),
        render_metadata=metadata,
        render_output={
            **render,
            "rendered_file": str(rendered_file),
            "render_exists": True,
        },
        link_record=link_record,
        assessment_phase="final_output",
    )
    return {
        "copyright_safety_v2": report,
        "manifest_validation": {
            "manifest": str(manifest_path),
            "rendered_file": str(rendered_file),
            "real_manifest_validation": True,
        },
    }


def _project(
    checker: CopyrightSafetyChecker,
    project_id: str,
    storage_root: Path,
) -> JsonDict:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
        raise ValueError("Project ID contains unsupported characters.")
    project = _load_project(storage_root, project_id)
    if not project:
        raise ValueError(f"Project not found under {storage_root}: {project_id}")
    link_record = _load_link_record(storage_root, project)
    manifest_path = storage_root / "render" / project_id / "index.json"
    clip_reports: list[CopyrightSafetyReport] = []
    if manifest_path.is_file():
        manifest = _read_json(manifest_path)
        for render in [_dict(item) for item in _list(manifest.get("renders")) if _dict(item)]:
            storage_key = _text(render.get("storage_key"))
            local_file = _storage_path(storage_root, storage_key)
            report = checker.check(
                project=project,
                clip_id=_text(render.get("clip_id")),
                render_metadata=_dict(render.get("metadata")),
                render_output={
                    **render,
                    "rendered_file": str(local_file) if local_file else storage_key,
                    "render_exists": local_file.is_file() if local_file else None,
                },
                link_record=link_record,
                assessment_phase="final_output",
            )
            clip_reports.append(report)
    if clip_reports:
        primary = clip_reports[0]
    else:
        primary = checker.check(
            project=project,
            link_record=link_record,
            assessment_phase="project_pre_render",
        )
    return {
        "copyright_safety_v2": primary,
        "clip_reports": clip_reports,
        "project_validation": {
            "project_id": project_id,
            "manifest_found": manifest_path.is_file(),
            "rendered_clips_checked": len(clip_reports),
            "real_project_validation": True,
        },
    }


def _simulated_source(name: str, rights_confirmed: bool) -> JsonDict:
    if name == "third_party_youtube":
        return {
            "source_type": "link",
            "source_url": "https://www.youtube.com/watch?v=simulation",
            "rights_confirmed": rights_confirmed,
            "rights_basis": "simulation_user_confirmation" if rights_confirmed else None,
        }
    if name == "local_user_owned":
        return {
            "source_type": "upload",
            "rights_confirmed": True,
            "owner_claimed_by_user": True,
            "rights_basis": "user_owned_upload",
        }
    if name == "generated_test":
        return {"source_type": "generated", "rights_confirmed": True}
    return {"source_type": "unknown", "rights_confirmed": False}


def _simulated_music(name: str) -> JsonDict:
    if name == "none":
        return {}
    if name == "unknown_license":
        return {
            "asset_id": "unknown_music",
            "title": "Unknown source",
            "safe_default": False,
            "license_verified": False,
            "source": "unknown",
        }
    if name == "curated_verified":
        return {
            "asset_id": "curated_verified",
            "title": "Verified curated asset",
            "folder_type": "curated",
            "license": "royalty_free_verified",
            "license_verified": True,
            "safe_default": True,
            "auto_select_allowed": True,
            "quality_status": "passed",
            "usage_allowed": True,
            "source": "documented_local_library",
        }
    return {
        "asset_id": "generated_safe",
        "title": "Generated validation bed",
        "folder_type": "generated",
        "license": "project_generated_safe",
        "license_verified": True,
        "safe_default": True,
        "auto_select_allowed": True,
        "quality_status": "passed",
        "usage_allowed": True,
        "source": "generated_validation_asset",
        "source_url": "generated://olympus/music/v2",
    }


def _select_render(manifest: JsonDict, rendered_file: Path) -> JsonDict:
    renders = [_dict(item) for item in _list(manifest.get("renders")) if _dict(item)]
    if not renders:
        return manifest
    lowered = rendered_file.name.lower()
    for render in renders:
        storage_key = _text(render.get("storage_key")) or ""
        if Path(storage_key).name.lower() == lowered:
            return render
    if len(renders) == 1:
        return renders[0]
    raise ValueError("Rendered file could not be matched to a manifest clip.")


def _load_project(storage_root: Path, project_id: str | None) -> JsonDict:
    if not project_id:
        return {}
    path = storage_root / "projects" / project_id / "project.json"
    return _read_json(path) if path.is_file() else {}


def _load_link_record(storage_root: Path, project: JsonDict) -> JsonDict:
    ingestion_id = _text(project.get("link_ingestion_id"))
    if not ingestion_id or not re.fullmatch(r"[A-Za-z0-9_-]+", ingestion_id):
        return {}
    path = storage_root / "link_ingestions" / ingestion_id / "status.json"
    return _read_json(path) if path.is_file() else {}


def _storage_path(storage_root: Path, storage_key: str | None) -> Path | None:
    if not storage_key:
        return None
    root = storage_root.resolve()
    candidate = (root / Path(storage_key)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _read_json(path: Path) -> JsonDict:
    if not path.is_file():
        raise ValueError(f"JSON file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


if __name__ == "__main__":
    sys.exit(main())

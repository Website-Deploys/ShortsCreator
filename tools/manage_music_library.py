"""Manage Olympus's local, license-strict curated music library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.music import MusicLibraryError, MusicLibraryManager  # noqa: E402
from olympus.music.library import (  # noqa: E402
    ENERGY_SCORES,
    INTENSITY_SCORES,
    LIBRARY_FOLDERS,
)
from olympus.platform.config import get_settings  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--init", action="store_true")
    commands.add_argument("--list", dest="list_assets", action="store_true")
    commands.add_argument("--summary", action="store_true")
    commands.add_argument("--import-file", type=Path)
    commands.add_argument("--import-dir", type=Path)
    commands.add_argument("--analyze", action="store_true")
    commands.add_argument("--validate", action="store_true")
    commands.add_argument("--rejected", action="store_true")
    commands.add_argument("--find-duplicates", action="store_true")
    commands.add_argument("--tag", metavar="ASSET_ID")
    commands.add_argument("--disable", metavar="ASSET_ID")
    commands.add_argument("--enable", metavar="ASSET_ID")

    parser.add_argument("--library-root", type=Path, default=ROOT / "assets" / "music")
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--license", dest="license_name")
    parser.add_argument("--license-url")
    parser.add_argument("--license-summary")
    parser.add_argument("--license-verified", action="store_true")
    parser.add_argument("--source")
    parser.add_argument("--source-url")
    parser.add_argument("--rights-holder")
    parser.add_argument("--attribution-required", action="store_true")
    parser.add_argument("--attribution-text")
    parser.add_argument("--mood", action="append", default=[])
    parser.add_argument("--genre", action="append", default=[])
    parser.add_argument("--use-case", action="append", default=[])
    parser.add_argument("--energy", choices=sorted(ENERGY_SCORES))
    parser.add_argument("--intensity", choices=sorted(INTENSITY_SCORES))
    parser.add_argument("--bpm", type=float)
    vocals = parser.add_mutually_exclusive_group()
    vocals.add_argument("--instrumental", action="store_true")
    vocals.add_argument("--has-vocals", action="store_true")
    parser.add_argument("--speech-safe", action="store_true", default=None)
    parser.add_argument("--loopable", action="store_true", default=None)
    parser.add_argument("--safe-default", action="store_true")
    parser.add_argument("--reason")
    return parser.parse_args(argv)


def _manager(args: argparse.Namespace) -> MusicLibraryManager:
    settings = get_settings()
    return MusicLibraryManager(
        args.library_root,
        ffmpeg_binary=settings.rendering.ffmpeg_binary,
        ffprobe_binary=settings.rendering.ffprobe_binary,
        report_root=args.report_dir,
    )


def _import_metadata(args: argparse.Namespace) -> dict[str, Any]:
    instrumental = True if args.instrumental else None
    has_vocals = True if args.has_vocals else None
    return {
        "title": args.title,
        "license_name": args.license_name,
        "license_url": args.license_url,
        "license_summary": args.license_summary,
        "license_verified": args.license_verified,
        "source": args.source,
        "source_url": args.source_url,
        "rights_holder": args.rights_holder,
        "attribution_required": args.attribution_required,
        "attribution_text": args.attribution_text,
        "moods": args.mood,
        "genres": args.genre,
        "use_cases": args.use_case,
        "energy": args.energy,
        "intensity": args.intensity,
        "bpm": args.bpm,
        "instrumental": instrumental,
        "has_vocals": has_vocals,
        "speech_safe": args.speech_safe is True,
        "loopable": args.loopable is True,
        "safe_default": args.safe_default,
    }


def run_command(args: argparse.Namespace) -> dict[str, Any]:
    manager = _manager(args)
    if args.init:
        library = manager.initialize()
        return {
            "command": "init",
            "library_root": str(manager.root),
            "manifest": str(manager.manifest_path),
            "folders": [str(manager.root / folder) for folder in LIBRARY_FOLDERS],
            "stats": library.get("stats"),
            "warnings": library.get("warnings"),
        }
    if args.list_assets:
        library = manager.load()
        return {
            "command": "list",
            "assets": library.get("assets") or [],
            "count": len(library.get("assets") or []),
        }
    if args.summary:
        return {"command": "summary", "summary": manager.summary()}
    if args.import_file:
        result = manager.import_file(args.import_file, **_import_metadata(args))
        report_path = manager.write_import_report(
            {
                "command": "import_file",
                "source_file": str(args.import_file.resolve()),
                "result": result,
            }
        )
        return {
            "command": "import_file",
            "result": result,
            "report": str(report_path),
        }
    if args.import_dir:
        result = manager.import_directory(args.import_dir, **_import_metadata(args))
        report_path = manager.write_import_report(
            {
                "command": "import_directory",
                "source_directory": str(args.import_dir.resolve()),
                "result": result,
            }
        )
        return {
            "command": "import_directory",
            "result": result,
            "report": str(report_path),
        }
    if args.analyze:
        return {"command": "analyze", "analysis": manager.analyze_all()}
    if args.validate:
        return {"command": "validate", "validation": manager.validate()}
    if args.rejected:
        return {"command": "rejected", **manager.rejected()}
    if args.find_duplicates:
        return {"command": "find_duplicates", "duplicates": manager.find_duplicates()}
    if args.tag:
        return {
            "command": "tag",
            "asset": manager.tag(
                args.tag,
                moods=args.mood,
                genres=args.genre,
                use_cases=args.use_case,
                energy=args.energy,
                intensity=args.intensity,
                bpm=args.bpm,
                speech_safe=args.speech_safe,
                loopable=args.loopable,
            ),
        }
    if args.disable:
        if not args.reason:
            raise MusicLibraryError(
                "DISABLE_REASON_REQUIRED",
                "--disable requires --reason.",
            )
        return {
            "command": "disable",
            "asset": manager.disable(args.disable, args.reason),
        }
    if args.enable:
        return {
            "command": "enable",
            "asset": manager.enable(
                args.enable,
                safe_default=args.safe_default,
                license_verified=args.license_verified,
            ),
        }
    raise MusicLibraryError("COMMAND_REQUIRED", "Choose one music-library command.")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_command(args)
    except MusicLibraryError as exc:
        print(
            json.dumps(
                {
                    "curated_music_library_v2": {
                        "passed": False,
                        "error": {"code": exc.code, "message": exc.message},
                    }
                },
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "curated_music_library_v2": {
                    "passed": True,
                    **result,
                }
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

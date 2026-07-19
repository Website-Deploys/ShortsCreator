"""Validate rights-safe test assets and optional dependency behavior."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.dependencies import get_optional_dependency_status  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "test_assets_dependencies"
REPORT_NAME = "test_assets_dependencies_report.json"
SUMMARY_NAME = "test_assets_dependencies_summary.md"
MUSIC_MANIFEST = Path("assets") / "music" / "music_manifest.json"
MEDIA_EXTENSIONS = frozenset(
    {".aac", ".avi", ".flac", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".ogg", ".wav", ".webm"}
)
OPTIONAL_IMPORT_ROOTS = frozenset(
    {
        "ctranslate2",
        "cv2",
        "easyocr",
        "faster_whisper",
        "pyannote",
        "pytesseract",
        "torchvision",
        "ultralytics",
        "yt_dlp",
    }
)
VALIDATORS = (
    Path("tools/validate_analysis_signals.py"),
    Path("tools/validate_real_rendering_e2e.py"),
    Path("tools/validate_long_video_full_render.py"),
    Path("tools/validate_durable_restart_resume.py"),
    Path("tools/validate_test_assets_dependencies.py"),
)
_ABSOLUTE_USER_PATH = re.compile(
    r"(?:^[A-Za-z]:[\\/]|^/(?:Users|home)/|^\\\\[^\\]+\\[^\\]+)",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _git_lines(root: Path, arguments: list[str]) -> tuple[list[str], str | None]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"git command failed: {type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        return [], f"git {' '.join(arguments)} failed: {detail or completed.returncode}"
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()], None


def _is_media(path: str) -> bool:
    return Path(path.replace("\\", "/")).suffix.lower() in MEDIA_EXTENSIONS


def _is_forbidden_generated_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./").lower()
    prefixes = (
        ".venv/",
        "frontend/.next/",
        "frontend/node_modules/",
        "media/",
        "node_modules/",
        "storage_data/",
        "work/",
    )
    if normalized == ".env" or (
        normalized.startswith(".env.") and normalized != ".env.example"
    ):
        return True
    return _is_media(normalized) or any(normalized.startswith(prefix) for prefix in prefixes)


def _iter_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_strings(key)
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def inspect_music_manifest(root: Path) -> dict[str, Any]:
    path = (root / MUSIC_MANIFEST).resolve()
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "valid_json": False,
        "schema_valid": False,
        "track_count": 0,
        "absolute_user_paths": [],
        "remote_references": [],
        "errors": [],
    }
    if not path.is_file():
        result["errors"] = [f"Required safe music manifest is missing: {MUSIC_MANIFEST}"]
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        result["errors"] = [f"Music manifest is invalid JSON: {exc}"]
        return result
    result["valid_json"] = True
    if not isinstance(payload, dict):
        result["errors"] = ["Music manifest must contain a JSON object."]
        return result
    library = payload.get("music_library_v2", payload)
    if not isinstance(library, dict) or not isinstance(library.get("assets"), list):
        result["errors"] = ["Music manifest must provide an assets list."]
        return result
    result["schema_valid"] = True
    result["track_count"] = len(library["assets"])
    strings = list(_iter_strings(payload))
    absolute = sorted({item for item in strings if _ABSOLUTE_USER_PATH.search(item.strip())})
    remote = sorted(
        {
            item
            for item in strings
            if item.strip().lower().startswith(("http://", "https://"))
        }
    )
    result["absolute_user_paths"] = absolute
    result["remote_references"] = remote
    errors: list[str] = []
    if absolute:
        errors.append("Music manifest contains absolute user paths.")
    if remote:
        errors.append("Music manifest contains remote asset references.")
    result["errors"] = errors
    return result


def _report_directory_writable(report_dir: Path) -> tuple[bool, str | None]:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=report_dir,
            prefix=".write-check-",
            suffix=".tmp",
            delete=True,
        ) as handle:
            handle.write("ok")
            handle.flush()
        return True, None
    except OSError as exc:
        return False, f"Report directory is not writable: {exc}"


def _tracked_media(root: Path) -> tuple[list[str], str | None]:
    tracked, error = _git_lines(root, ["ls-files"])
    return sorted(path for path in tracked if _is_media(path)), error


def _staged_forbidden(root: Path) -> tuple[list[str], str | None]:
    staged, error = _git_lines(root, ["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return sorted(path for path in staged if _is_forbidden_generated_path(path)), error


def _top_level_optional_imports(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    source_root = root / "src" / "olympus"
    if not source_root.is_dir():
        return [{"path": str(source_root), "module": "source_tree_missing"}]
    for path in sorted(source_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            findings.append(
                {"path": str(path.relative_to(root)), "module": f"parse_error:{exc}"}
            )
            continue
        for node in tree.body:
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.split(".", 1)[0] in OPTIONAL_IMPORT_ROOTS:
                    findings.append(
                        {
                            "path": str(path.relative_to(root)).replace("\\", "/"),
                            "module": module,
                        }
                    )
    return findings


def _validator_imports(root: Path) -> dict[str, dict[str, Any]]:
    status: dict[str, dict[str, Any]] = {}
    for relative in VALIDATORS:
        path = root / relative
        item: dict[str, Any] = {
            "exists": path.is_file(),
            "importable": False,
            "error": None,
        }
        if path.is_file():
            try:
                runpy.run_path(str(path), run_name=f"__validator_check_{path.stem}__")
                item["importable"] = True
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
        else:
            item["error"] = "validator file is missing"
        status[str(relative).replace("\\", "/")] = item
    return status


def _base_report(mode: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": mode,
        "generated_at": _utc_now(),
        "passed": False,
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
        },
        "warnings": [],
        "errors": [],
    }


def self_check(
    *,
    root: Path = ROOT,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> dict[str, Any]:
    root = root.resolve()
    report_dir = report_dir.resolve()
    report = _base_report("self_check")
    tools = {
        name: {"available": bool(path := shutil.which(name)), "path": path}
        for name in ("ffmpeg", "ffprobe")
    }
    tools["tesseract"] = {
        "available": bool(tesseract := shutil.which("tesseract")),
        "path": tesseract,
        "required": False,
    }
    dependencies = get_optional_dependency_status()
    manifest = inspect_music_manifest(root)
    tracked_media, git_error = _tracked_media(root)
    writable, writable_error = _report_directory_writable(report_dir)
    errors = [str(item) for item in manifest["errors"]]
    if not tools["ffmpeg"]["available"]:
        errors.append("Required local tool ffmpeg is unavailable.")
    if not tools["ffprobe"]["available"]:
        errors.append("Required local tool ffprobe is unavailable.")
    if tracked_media:
        errors.append("Generated or copyrighted media is tracked by Git.")
    if git_error:
        errors.append(git_error)
    if not writable:
        errors.append(writable_error or "Validation report directory is not writable.")
    warnings = [
        f"{name} unavailable; {details['feature']} remains optional."
        for name, details in dependencies.items()
        if not details["available"]
    ]
    report.update(
        {
            "tools": tools,
            "optional_dependencies": dependencies,
            "music_manifest": manifest,
            "repository_hygiene": {
                "tracked_media": tracked_media,
                "git_error": git_error,
            },
            "report_directory": {
                "path": str(report_dir),
                "writable": writable,
                "error": writable_error,
            },
            "warnings": warnings,
            "errors": errors,
            "passed": not errors,
        }
    )
    return report


def repo_check(
    *,
    root: Path = ROOT,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> dict[str, Any]:
    root = root.resolve()
    report_dir = report_dir.resolve()
    report = _base_report("repo_check")
    manifest = inspect_music_manifest(root)
    tracked_media, tracked_error = _tracked_media(root)
    staged_forbidden, staged_error = _staged_forbidden(root)
    optional_imports = _top_level_optional_imports(root)
    validators = _validator_imports(root)
    writable, writable_error = _report_directory_writable(report_dir)
    validator_failures = [
        path
        for path, details in validators.items()
        if not details["exists"] or not details["importable"]
    ]
    errors = [str(item) for item in manifest["errors"]]
    if tracked_media:
        errors.append("Tracked media violates repository policy.")
    if staged_forbidden:
        errors.append("Generated artifacts or media are staged.")
    if optional_imports:
        errors.append("Optional dependencies are imported at module top level.")
    if validator_failures:
        errors.append("One or more required validators are missing or not importable.")
    for git_error in (tracked_error, staged_error):
        if git_error:
            errors.append(git_error)
    if not writable:
        errors.append(writable_error or "Validation report directory is not writable.")
    report.update(
        {
            "required_test_assets": {
                str(MUSIC_MANIFEST).replace("\\", "/"): manifest["schema_valid"]
            },
            "music_manifest": manifest,
            "repository_hygiene": {
                "tracked_media": tracked_media,
                "staged_forbidden_paths": staged_forbidden,
                "tracked_git_error": tracked_error,
                "staged_git_error": staged_error,
            },
            "optional_top_level_imports": optional_imports,
            "validators": validators,
            "report_directory": {
                "path": str(report_dir),
                "writable": writable,
                "error": writable_error,
            },
            "warnings": [],
            "errors": errors,
            "passed": not errors,
        }
    )
    return report


def _summary(report: dict[str, Any]) -> str:
    status = "PASS" if report.get("passed") else "FAIL"
    lines = [
        "# Test Assets and Optional Dependencies Validation",
        "",
        f"- Status: **{status}**",
        f"- Mode: `{report.get('mode')}`",
        f"- Python: `{report.get('python', {}).get('version')}`",
        f"- Errors: `{len(report.get('errors', []))}`",
        f"- Warnings: `{len(report.get('warnings', []))}`",
        "",
        "## Errors",
        "",
    ]
    errors = report.get("errors") or []
    lines.extend(f"- {item}" for item in errors)
    if not errors:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    warnings = report.get("warnings") or []
    lines.extend(f"- {item}" for item in warnings)
    if not warnings:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], report_dir: Path) -> dict[str, str]:
    report_dir = report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / REPORT_NAME
    summary_path = report_dir / SUMMARY_NAME
    paths = {"json": str(json_path), "summary": str(summary_path)}
    report["report_paths"] = paths
    json_temporary = json_path.with_suffix(".json.tmp")
    summary_temporary = summary_path.with_suffix(".md.tmp")
    json_temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary_temporary.write_text(_summary(report), encoding="utf-8")
    os.replace(json_temporary, json_path)
    os.replace(summary_temporary, summary_path)
    return paths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate safe test assets and optional dependency behavior.",
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--repo-check", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = (
            self_check(report_dir=args.report_dir)
            if args.self_check
            else repo_check(report_dir=args.report_dir)
        )
        paths = write_reports(report, args.report_dir)
    except Exception as exc:
        if args.debug:
            raise
        report = _base_report("self_check" if args.self_check else "repo_check")
        report["errors"] = [f"Validator failed: {type(exc).__name__}: {exc}"]
        report["passed"] = False
        try:
            paths = write_reports(report, args.report_dir)
        except OSError:
            paths = {}
    print(
        json.dumps(
            {
                "mode": report["mode"],
                "passed": report["passed"],
                "errors": report["errors"],
                "warnings": report["warnings"],
                "reports": paths,
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

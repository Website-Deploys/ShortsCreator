"""Diagnose and validate Olympus YouTube Link Ingestion V2 safely."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.data.storage.local import LocalStorage  # noqa: E402
from olympus.platform.config.settings import get_settings  # noqa: E402
from olympus.platform.errors import ValidationError  # noqa: E402
from olympus.rendering.command import build_ffprobe_command  # noqa: E402
from olympus.services.intake import (  # noqa: E402
    LinkDownloadRecord,
    LinkDownloadStatus,
    LinkIngestionMode,
    VideoLinkIntakeService,
)

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "link_ingestion"
DEFAULT_WORK_DIR = ROOT / "work"
REPORT_JSON_NAME = "link_ingestion_validation_report.json"
REPORT_MARKDOWN_NAME = "link_ingestion_validation_summary.md"
EXPECTED_API_ROUTES = (
    "/api/v1/projects/from-link",
    "/api/v1/projects/link-ingestions/{ingestion_id}",
)
TERMINAL_PIPELINE_STATUSES = {"failed", "cancelled", "dead", "blocked"}


@dataclass(slots=True)
class ValidationIssue:
    """One stable, actionable validator failure."""

    code: str
    message: str
    likely_cause: str
    next_action: str
    command_to_try: str
    raw_error: str | None = None


class BackendConnectionError(RuntimeError):
    """The configured backend could not be reached."""

    def __init__(self, url: str, reason: object) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"{url}: {reason}")


class HttpStatusError(RuntimeError):
    """An HTTP request completed with a non-success response."""

    def __init__(self, status: int, url: str, body: object) -> None:
        self.status = status
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status} from {url}: {body}")


def _request_json(
    base: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Request one JSON object without collapsing local and remote failures."""

    data = None if payload is None else json.dumps(payload).encode("utf-8")
    url = urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        try:
            body: object = json.loads(raw_error)
        except json.JSONDecodeError:
            body = raw_error
        raise HttpStatusError(exc.code, url, body) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        raise BackendConnectionError(url, reason) from exc
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HttpStatusError(502, url, f"Backend returned invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise HttpStatusError(502, url, "Backend returned non-object JSON.")
    return body


def _request_file(
    base: str,
    path: str,
    destination: Path,
    *,
    timeout_seconds: float,
) -> int:
    """Download one API-owned render into a validator temp directory."""

    url = urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url, method="GET")
    partial = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with (
            urllib.request.urlopen(request, timeout=timeout_seconds) as response,
            partial.open("wb") as handle,
        ):
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                total += len(chunk)
        if total <= 0:
            raise RuntimeError("The backend returned an empty rendered clip.")
        os.replace(partial, destination)
        return total
    except urllib.error.HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        raise HttpStatusError(exc.code, url, raw_error) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        raise BackendConnectionError(url, reason) from exc
    finally:
        partial.unlink(missing_ok=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--diagnose", action="store_true")
    modes.add_argument("--metadata-only", action="store_true")
    modes.add_argument("--download-only", action="store_true")
    modes.add_argument("--full-pipeline", action="store_true")
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument("--direct", action="store_true")
    execution.add_argument("--api", action="store_true")
    parser.add_argument("--url", help="Public YouTube URL you may process")
    parser.add_argument(
        "--confirm-rights",
        action="store_true",
        help="Confirm you own, have permission for, or may process the source",
    )
    parser.add_argument(
        "--backend-url",
        "--base",
        dest="backend_url",
        default=DEFAULT_BACKEND_URL,
        help="Olympus backend base URL",
    )
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--keep-download", action="store_true")
    cleanup = parser.add_mutually_exclusive_group()
    cleanup.add_argument("--cleanup", dest="cleanup", action="store_true", default=True)
    cleanup.add_argument("--no-cleanup", dest="cleanup", action="store_false")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def _mode(args: argparse.Namespace) -> str:
    if args.self_check:
        return "self_check"
    if args.diagnose:
        return "diagnose"
    if args.download_only:
        return LinkIngestionMode.DOWNLOAD_ONLY.value
    if args.full_pipeline:
        return LinkIngestionMode.FULL_PIPELINE.value
    return LinkIngestionMode.METADATA_ONLY.value


def _execution_mode(args: argparse.Namespace) -> str:
    if args.self_check or args.diagnose:
        return "none"
    if args.full_pipeline:
        return "api"
    if args.direct:
        return "direct"
    return "api"


def _empty_report(
    *,
    url: str | None,
    mode: str,
    backend_url: str,
    rights_confirmed: bool,
    execution_mode: str,
) -> dict[str, Any]:
    return {
        "link_ingestion_validation_v2": {
            "created_at": datetime.now(UTC).isoformat(),
            "workspace": str(ROOT),
            "branch": _git_branch(),
            "mode": mode,
            "url": url,
            "backend_url": backend_url,
            "rights_confirmed": rights_confirmed,
            "direct_mode": execution_mode == "direct",
            "api_mode": execution_mode == "api",
            "environment": {
                "python": sys.executable,
                "python_version": sys.version.split()[0],
                "virtual_environment": None,
                "project_root_valid": Path(r"D:\Olympus") == ROOT,
                "olympus_imported": False,
                "ytdlp_installed": False,
                "ytdlp_version": None,
                "ffmpeg_available": False,
                "ffmpeg_version": None,
                "ffprobe_available": False,
                "ffprobe_version": None,
                "backend_reachable": False,
                "backend_health_passed": False,
                "api_routes_found": [],
                "workdir_writable": False,
                "report_dir_writable": False,
                "windows_path_safe": False,
                "warnings": [],
            },
            "url_validation": {
                "passed": False,
                "canonical_url": None,
                "source_type": None,
                "warnings": [],
            },
            "metadata": {
                "attempted": False,
                "passed": False,
                "title": None,
                "duration_seconds": None,
                "uploader": None,
                "channel": None,
                "live_status": None,
                "availability": None,
                "age_limit": None,
                "formats_count": 0,
                "selected_quality": None,
                "warnings": [],
            },
            "download": {
                "attempted": False,
                "started": False,
                "completed": False,
                "file_path": None,
                "file_size_bytes": None,
                "stored_file_exists": False,
                "kept": False,
                "cleaned_up": False,
                "partial_files": [],
                "warnings": [],
            },
            "ffprobe": {
                "attempted": False,
                "passed": False,
                "width": None,
                "height": None,
                "video_codec": None,
                "audio_codec": None,
                "audio_sample_rate": None,
                "duration": None,
                "has_video": False,
                "has_audio": False,
                "audio_video_delta": None,
                "warnings": [],
            },
            "api": {
                "attempted": False,
                "backend_health_passed": False,
                "ingestion_id": None,
                "project_id": None,
                "last_status": None,
                "last_stage": None,
                "pipeline_started": False,
                "project_status": None,
                "workflow_status": None,
                "render_status": None,
                "clips_rendered": 0,
                "frontend_payload_passed": False,
                "warnings": [],
            },
            "clips": [],
            "stages": [],
            "errors": [],
            "result": {
                "passed": False,
                "status": "PENDING",
                "failed_step": None,
                "error_code": None,
                "message": "Validation has not completed.",
                "next_action": None,
                "command_to_try": None,
            },
        }
    }


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    value = report.get("link_ingestion_validation_v2")
    if not isinstance(value, dict):
        raise ValueError("Invalid Link Ingestion V2 report.")
    return value


def _git_branch() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    branch = completed.stdout.strip()
    return branch or None


def _progress(index: int, total: int, label: str, status: str, detail: str = "") -> None:
    suffix = f", {detail}" if detail else ""
    print(f"[{index}/{total}] {label}: {status}{suffix}", file=sys.stderr, flush=True)


def _record_stage(
    report: dict[str, Any],
    name: str,
    status: str,
    detail: str | None = None,
) -> None:
    _summary(report)["stages"].append(
        {
            "stage": name,
            "status": status,
            "detail": detail,
            "at": datetime.now(UTC).isoformat(),
        }
    )


def _backend_start_command() -> str:
    return (
        f"cd {ROOT}\n"
        r".\.venv\Scripts\python.exe -m uvicorn olympus.api.app:app "
        r"--app-dir src --host 127.0.0.1 --port 8000"
    )


def _validator_command(report: dict[str, Any], *, include_rights: bool = True) -> str:
    summary = _summary(report)
    mode = str(summary["mode"])
    url = str(summary.get("url") or "URL").replace('"', "")
    backend = str(summary.get("backend_url") or DEFAULT_BACKEND_URL)
    python = r".\.venv\Scripts\python.exe"
    if mode == "self_check":
        return f"{python} tools\\validate_link_ingestion.py --self-check"
    if mode == "diagnose":
        return f'{python} tools\\validate_link_ingestion.py --url "{url}" --diagnose'
    mode_flag = "--" + mode.replace("_", "-")
    execution = " --direct" if summary.get("direct_mode") else ""
    if summary.get("api_mode") and mode != "full_pipeline":
        execution = " --api"
    backend_flag = f" --backend-url {backend}" if summary.get("api_mode") else ""
    rights = " --confirm-rights" if include_rights else ""
    return (
        f'{python} tools\\validate_link_ingestion.py --url "{url}" '
        f"{mode_flag}{execution}{backend_flag}{rights}"
    )


def _diagnose_command(report: dict[str, Any]) -> str:
    url = str(_summary(report).get("url") or "URL").replace('"', "")
    return (
        r".\.venv\Scripts\python.exe tools\validate_link_ingestion.py "
        f'--url "{url}" --diagnose'
    )


def _guidance(
    code: str,
    report: dict[str, Any],
) -> tuple[str, str, str]:
    self_check = (
        r".\.venv\Scripts\python.exe tools\validate_link_ingestion.py --self-check"
    )
    guidance: dict[str, tuple[str, str, str]] = {
        "LOCAL_BACKEND_UNAVAILABLE": (
            "The Olympus process is not listening at the configured host and port.",
            "Start the backend without reload, then rerun the API validation.",
            _backend_start_command(),
        ),
        "BACKEND_HEALTH_FAILED": (
            "A process answered, but Olympus liveness or OpenAPI checks failed.",
            "Verify that the Olympus API app is running at the configured URL.",
            _backend_start_command(),
        ),
        "API_ROUTE_UNAVAILABLE": (
            "The backend OpenAPI document does not expose the Link Ingestion V2 routes.",
            "Start the current Olympus API build and inspect its OpenAPI document.",
            _backend_start_command(),
        ),
        "YTDLP_NOT_INSTALLED": (
            "The current Python environment cannot import yt-dlp.",
            "Install the repository video-links extra in the active environment.",
            r'.\.venv\Scripts\python.exe -m pip install -e ".[video-links]"',
        ),
        "YTDLP_METADATA_FAILED": (
            "yt-dlp could not read safe public metadata for this URL.",
            "Check public availability and connectivity, then retry direct metadata.",
            _validator_command(report),
        ),
        "URL_INVALID": (
            "The URL is malformed or is not an individual supported video URL.",
            "Use a YouTube watch, youtu.be, or Shorts URL without a playlist.",
            _diagnose_command(report),
        ),
        "RIGHTS_CONFIRMATION_REQUIRED": (
            "The validator was not given explicit confirmation of processing rights.",
            "Confirm rights only if accurate, then rerun with --confirm-rights.",
            _validator_command(report, include_rights=True),
        ),
        "UNSUPPORTED_SOURCE": (
            "The source is not a supported individual public YouTube video.",
            "Use a supported watch, youtu.be, or Shorts URL.",
            _diagnose_command(report),
        ),
        "VIDEO_UNAVAILABLE": (
            "The video is private, deleted, login-only, restricted, or unavailable.",
            "Use another public video you are authorized to process or upload your file.",
            self_check,
        ),
        "LIVE_VIDEO_UNSUPPORTED": (
            "The URL resolves to a currently live stream.",
            "Wait for an archived recording or upload a finished source file.",
            self_check,
        ),
        "AGE_RESTRICTED_UNSUPPORTED": (
            "The source requires age verification, which this safe validator does not bypass.",
            "Use a non-restricted public source or manually upload an authorized file.",
            self_check,
        ),
        "DURATION_LIMIT_EXCEEDED": (
            "The video exceeds the configured Link Ingestion duration limit.",
            "Use a shorter source or intentionally adjust the configured limit.",
            self_check,
        ),
        "SIZE_LIMIT_EXCEEDED": (
            "The selected media exceeds the configured source size limit.",
            "Use a shorter source or intentionally adjust the configured limit.",
            self_check,
        ),
        "DOWNLOAD_FAILED": (
            "yt-dlp started but did not produce a complete validated media file.",
            "Retry direct metadata first, then retry the download.",
            _validator_command(report),
        ),
        "DOWNLOAD_INCOMPLETE": (
            "The ingestion reported storage, but the expected file was absent or empty.",
            "Inspect the report and backend storage before retrying.",
            self_check,
        ),
        "FFPROBE_FAILED": (
            "FFprobe is unavailable or could not validate the downloaded media.",
            "Install or repair FFmpeg/FFprobe, then run self-check.",
            self_check,
        ),
        "PROJECT_CREATION_FAILED": (
            "The source was stored but the backend did not create a normal project.",
            "Inspect the ingestion ID and backend logs, then retry API mode.",
            self_check,
        ),
        "PIPELINE_START_FAILED": (
            "A project exists, but processing did not start.",
            "Inspect the project and backend logs, then retry the pipeline.",
            self_check,
        ),
        "PIPELINE_FAILED": (
            "The project pipeline or rendering entered a terminal failure state.",
            "Inspect the reported project ID, stage, and backend logs.",
            self_check,
        ),
        "PIPELINE_TIMEOUT": (
            "The full pipeline did not produce a terminal result before the timeout.",
            "Inspect the project status, then rerun with a larger timeout if still active.",
            _validator_command(report),
        ),
        "NO_CLIPS_RENDERED": (
            "Rendering completed or became terminal without any rendered MP4.",
            "Inspect planning and rendering manifests for the reported project.",
            self_check,
        ),
        "CLIP_VALIDATION_FAILED": (
            "At least one rendered clip failed download, FFprobe, sync, or resolution checks.",
            "Inspect the per-clip report and rendering validation metadata.",
            self_check,
        ),
        "FRONTEND_PAYLOAD_FAILED": (
            "The final render payload lacks usable clip IDs or download endpoints.",
            "Inspect the rendering manifest returned for the project.",
            self_check,
        ),
        "UNKNOWN_ERROR": (
            "The validator encountered an unexpected condition.",
            "Run self-check and rerun with --debug for a local traceback.",
            self_check,
        ),
    }
    return guidance.get(code, guidance["UNKNOWN_ERROR"])


def _issue(
    code: str,
    message: str,
    report: dict[str, Any],
    *,
    raw_error: object | None = None,
) -> ValidationIssue:
    likely_cause, next_action, command_to_try = _guidance(code, report)
    raw = None if raw_error is None else str(raw_error)[:4000]
    return ValidationIssue(
        code=code,
        message=message,
        likely_cause=likely_cause,
        next_action=next_action,
        command_to_try=command_to_try,
        raw_error=raw,
    )


def _set_failure(
    report: dict[str, Any],
    issue: ValidationIssue,
    *,
    failed_step: str,
) -> None:
    summary = _summary(report)
    summary["errors"].append(asdict(issue))
    summary["result"] = {
        "passed": False,
        "status": "FAILED",
        "failed_step": failed_step,
        "error_code": issue.code,
        "message": issue.message,
        "next_action": issue.next_action,
        "command_to_try": issue.command_to_try,
    }
    _record_stage(report, failed_step, "FAILED", issue.code)


def _set_success(report: dict[str, Any], message: str) -> None:
    summary = _summary(report)
    summary["result"] = {
        "passed": True,
        "status": "PASSED",
        "failed_step": None,
        "error_code": None,
        "message": message,
        "next_action": None,
        "command_to_try": None,
    }


def _set_warning_result(
    report: dict[str, Any],
    message: str,
    *,
    next_action: str,
    command_to_try: str,
) -> None:
    _summary(report)["result"] = {
        "passed": True,
        "status": "WARNING",
        "failed_step": None,
        "error_code": None,
        "message": message,
        "next_action": next_action,
        "command_to_try": command_to_try,
    }


def classify_exception(
    exc: Exception,
    context: str,
    report: dict[str, Any],
) -> ValidationIssue:
    """Map low-level failures to the validator's stable taxonomy."""

    message = str(exc)
    lowered = message.lower()
    if isinstance(exc, ValidationError):
        code_map = {
            "INVALID_URL": "URL_INVALID",
            "UNSUPPORTED_PLATFORM": "UNSUPPORTED_SOURCE",
            "PLAYLIST_NOT_SUPPORTED": "UNSUPPORTED_SOURCE",
            "RIGHTS_CONFIRMATION_REQUIRED": "RIGHTS_CONFIRMATION_REQUIRED",
        }
        code = code_map.get(str(exc.code).upper(), "URL_INVALID")
        return _issue(code, exc.message, report, raw_error=message)
    if context == "backend":
        if any(
            token in lowered
            for token in ("10061", "actively refused", "connection refused", "winerror 10061")
        ):
            return _issue(
                "LOCAL_BACKEND_UNAVAILABLE",
                "The Olympus backend is not accepting connections at the configured URL.",
                report,
                raw_error=message,
            )
        if isinstance(exc, HttpStatusError):
            return _issue(
                "BACKEND_HEALTH_FAILED",
                "The configured backend did not pass its Olympus health check.",
                report,
                raw_error=message,
            )
        return _issue(
            "LOCAL_BACKEND_UNAVAILABLE",
            "The Olympus backend could not be reached at the configured URL.",
            report,
            raw_error=message,
        )
    if isinstance(exc, TimeoutError) or "timed out" in lowered:
        code = "PIPELINE_TIMEOUT" if context == "pipeline" else "DOWNLOAD_FAILED"
        return _issue(
            code,
            f"{context.replace('_', ' ').title()} timed out.",
            report,
            raw_error=message,
        )
    if context == "metadata":
        return _issue(
            "YTDLP_METADATA_FAILED",
            "yt-dlp could not extract safe public metadata.",
            report,
            raw_error=message,
        )
    if context == "ffprobe":
        return _issue(
            "FFPROBE_FAILED",
            "FFprobe could not validate the media file.",
            report,
            raw_error=message,
        )
    if context == "api_route":
        return _issue(
            "API_ROUTE_UNAVAILABLE",
            "The Link Ingestion V2 API route is unavailable.",
            report,
            raw_error=message,
        )
    if context == "pipeline":
        return _issue(
            "PIPELINE_FAILED",
            "The Olympus processing pipeline failed.",
            report,
            raw_error=message,
        )
    return _issue(
        "UNKNOWN_ERROR",
        "The validator encountered an unexpected error.",
        report,
        raw_error=f"{type(exc).__name__}: {message}",
    )


def _binary_check(binary: str) -> tuple[bool, str | None, str | None]:
    resolved = shutil.which(binary)
    if resolved is None and Path(binary).is_file():
        resolved = str(Path(binary).resolve())
    if resolved is None:
        return False, None, f"{binary} was not found on PATH."
    try:
        completed = subprocess.run(
            [resolved, "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, None, str(exc)
    output = (completed.stdout or completed.stderr).splitlines()
    version = output[0].strip() if output else None
    if completed.returncode != 0:
        return False, version, f"{binary} exited {completed.returncode}."
    return True, version, None


def _writable(path: Path) -> tuple[bool, str | None]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".olympus_link_write_",
            dir=path,
            delete=False,
        ) as handle:
            handle.write("writable\n")
            probe = Path(handle.name)
        probe.unlink()
    except OSError as exc:
        return False, str(exc)
    return True, None


def check_environment(
    report: dict[str, Any],
    *,
    report_dir: Path,
) -> dict[str, Any]:
    """Populate dependency and local path truth without requiring a URL."""

    environment = _summary(report)["environment"]
    environment["virtual_environment"] = (
        sys.prefix if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else None
    )
    try:
        importlib.import_module("olympus")
        environment["olympus_imported"] = True
    except ImportError as exc:
        environment["warnings"].append(f"olympus import failed: {exc}")

    try:
        ytdlp = importlib.import_module("yt_dlp")
        version_module = importlib.import_module("yt_dlp.version")
        environment["ytdlp_installed"] = True
        environment["ytdlp_version"] = getattr(
            version_module,
            "__version__",
            getattr(ytdlp, "__version__", None),
        )
    except ImportError as exc:
        environment["warnings"].append(f"yt-dlp import failed: {exc}")

    settings = get_settings()
    ffmpeg_ok, ffmpeg_version, ffmpeg_error = _binary_check(
        settings.rendering.ffmpeg_binary
    )
    ffprobe_ok, ffprobe_version, ffprobe_error = _binary_check(
        settings.rendering.ffprobe_binary
    )
    environment["ffmpeg_available"] = ffmpeg_ok
    environment["ffmpeg_version"] = ffmpeg_version
    environment["ffprobe_available"] = ffprobe_ok
    environment["ffprobe_version"] = ffprobe_version
    if ffmpeg_error:
        environment["warnings"].append(ffmpeg_error)
    if ffprobe_error:
        environment["warnings"].append(ffprobe_error)

    work_ok, work_error = _writable(DEFAULT_WORK_DIR)
    report_ok, report_error = _writable(report_dir)
    environment["workdir_writable"] = work_ok
    environment["report_dir_writable"] = report_ok
    environment["windows_path_safe"] = (
        os.name != "nt"
        or (ROOT.drive.upper() == "D:" and ROOT.name.lower() == "olympus")
    )
    if work_error:
        environment["warnings"].append(f"Work directory is not writable: {work_error}")
    if report_error:
        environment["warnings"].append(f"Report directory is not writable: {report_error}")
    if not environment["windows_path_safe"]:
        environment["warnings"].append("Workspace path does not match the expected Windows root.")
    return environment


def _tcp_check(backend_url: str, timeout_seconds: float) -> None:
    parsed = urllib.parse.urlparse(backend_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BackendConnectionError(backend_url, "Backend URL must be http(s).")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection(
            (parsed.hostname, port),
            timeout=max(0.1, timeout_seconds),
        ):
            return
    except OSError as exc:
        raise BackendConnectionError(backend_url, exc) from exc


def check_backend_health(
    report: dict[str, Any],
    *,
    backend_url: str,
    timeout_seconds: float = 5.0,
) -> ValidationIssue | None:
    """Check TCP, liveness, OpenAPI, and required routes in that order."""

    environment = _summary(report)["environment"]
    try:
        _tcp_check(backend_url, timeout_seconds)
        environment["backend_reachable"] = True
        health = _request_json(
            backend_url,
            "GET",
            "/api/v1/health/live",
            timeout_seconds=timeout_seconds,
        )
        if not health:
            raise HttpStatusError(502, backend_url, "Empty liveness response.")
    except Exception as exc:
        return classify_exception(exc, "backend", report)
    try:
        openapi = _request_json(
            backend_url,
            "GET",
            "/openapi.json",
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return classify_exception(exc, "api_route", report)

    paths = openapi.get("paths")
    path_map = paths if isinstance(paths, dict) else {}
    found = [path for path in EXPECTED_API_ROUTES if path in path_map]
    environment["api_routes_found"] = found
    if len(found) != len(EXPECTED_API_ROUTES):
        missing = sorted(set(EXPECTED_API_ROUTES) - set(found))
        return _issue(
            "API_ROUTE_UNAVAILABLE",
            f"The backend is missing required Link Ingestion routes: {', '.join(missing)}.",
            report,
            raw_error={"missing_routes": missing},
        )
    environment["backend_health_passed"] = True
    return None


def run_self_check(
    report: dict[str, Any],
    *,
    backend_url: str,
    report_dir: Path,
) -> dict[str, Any]:
    environment = check_environment(report, report_dir=report_dir)
    _progress(1, 5, "Python and Olympus", "PASS" if environment["olympus_imported"] else "FAIL")
    _progress(
        2,
        5,
        "yt-dlp",
        "PASS" if environment["ytdlp_installed"] else "FAIL",
        str(environment.get("ytdlp_version") or ""),
    )
    media_ok = environment["ffmpeg_available"] and environment["ffprobe_available"]
    _progress(3, 5, "FFmpeg and FFprobe", "PASS" if media_ok else "FAIL")
    paths_ok = environment["workdir_writable"] and environment["report_dir_writable"]
    _progress(4, 5, "Writable directories", "PASS" if paths_ok else "FAIL")
    backend_issue = check_backend_health(
        report,
        backend_url=backend_url,
        timeout_seconds=3.0,
    )
    _progress(5, 5, "Backend", "WARN" if backend_issue else "PASS", backend_url)

    missing: list[str] = []
    if not environment["olympus_imported"]:
        missing.append("olympus import")
    if not environment["ytdlp_installed"]:
        missing.append("yt-dlp")
    if not environment["ffmpeg_available"]:
        missing.append("ffmpeg")
    if not environment["ffprobe_available"]:
        missing.append("ffprobe")
    if not paths_ok:
        missing.append("writable directories")
    if not environment["windows_path_safe"]:
        missing.append("expected workspace path")
    if missing:
        if "yt-dlp" in missing:
            code = "YTDLP_NOT_INSTALLED"
        elif "ffmpeg" in missing or "ffprobe" in missing:
            code = "FFPROBE_FAILED"
        else:
            code = "UNKNOWN_ERROR"
        issue = _issue(
            code,
            f"Self-check failed: missing or invalid {', '.join(missing)}.",
            report,
            raw_error="; ".join(environment["warnings"]),
        )
        _set_failure(report, issue, failed_step="self_check")
        return report
    if backend_issue:
        environment["warnings"].append(
            f"{backend_issue.code}: {backend_issue.message}"
        )
        _set_warning_result(
            report,
            "Local dependencies passed; the optional backend check needs attention.",
            next_action=backend_issue.next_action,
            command_to_try=backend_issue.command_to_try,
        )
        _record_stage(report, "self_check", "WARNING", backend_issue.code)
        return report
    _set_success(report, "Self-check passed, including backend routes.")
    _record_stage(report, "self_check", "PASSED")
    return report


def validate_url(
    report: dict[str, Any],
    url: str,
) -> ValidationIssue | None:
    """Reuse the production URL policy without asserting user rights."""

    settings = get_settings().link_ingestion.model_copy(
        update={"require_user_rights_confirmation": False}
    )
    with tempfile.TemporaryDirectory(prefix="olympus_link_url_") as temporary:
        service = VideoLinkIntakeService(
            LocalStorage(temporary),
            settings=settings,
        )
        try:
            source = service.validate_url(url, permission_confirmed=False)
        except ValidationError as exc:
            return classify_exception(exc, "url", report)
    validation = _summary(report)["url_validation"]
    validation["passed"] = True
    validation["canonical_url"] = source.get("normalized_url")
    validation["source_type"] = source.get("url_type")
    validation["warnings"] = list(source.get("validation_warnings") or [])
    _record_stage(report, "url_validation", "PASSED", str(source.get("url_type") or ""))
    return None


def _record_error_issue(
    record: LinkDownloadRecord | dict[str, Any],
    report: dict[str, Any],
) -> ValidationIssue:
    if isinstance(record, LinkDownloadRecord):
        error = record.error or {}
        reason = record.reason
    else:
        raw_error = record.get("error")
        error = raw_error if isinstance(raw_error, dict) else {}
        reason = record.get("reason")
    source_code = str(error.get("code") or "UNKNOWN_ERROR").upper()
    message = str(
        error.get("user_message")
        or error.get("message")
        or reason
        or "Link ingestion failed."
    )
    lowered = " ".join(
        str(error.get(key) or "") for key in ("user_message", "developer_message", "message")
    ).lower()
    mapping = {
        "DOWNLOADER_UNAVAILABLE": "YTDLP_NOT_INSTALLED",
        "METADATA_EXTRACTION_FAILED": "YTDLP_METADATA_FAILED",
        "INVALID_URL": "URL_INVALID",
        "UNSUPPORTED_PLATFORM": "UNSUPPORTED_SOURCE",
        "PLAYLIST_NOT_SUPPORTED": "UNSUPPORTED_SOURCE",
        "RIGHTS_CONFIRMATION_REQUIRED": "RIGHTS_CONFIRMATION_REQUIRED",
        "PRIVATE_VIDEO": "VIDEO_UNAVAILABLE",
        "LOGIN_REQUIRED": (
            "AGE_RESTRICTED_UNSUPPORTED" if "age" in lowered else "VIDEO_UNAVAILABLE"
        ),
        "VIDEO_UNAVAILABLE": "VIDEO_UNAVAILABLE",
        "LIVE_STREAM_NOT_SUPPORTED": "LIVE_VIDEO_UNSUPPORTED",
        "VIDEO_TOO_LONG": "DURATION_LIMIT_EXCEEDED",
        "FILE_TOO_LARGE": "SIZE_LIMIT_EXCEEDED",
        "DOWNLOAD_FAILED": "DOWNLOAD_FAILED",
        "FFPROBE_FAILED": "FFPROBE_FAILED",
        "PIPELINE_START_FAILED": "PIPELINE_START_FAILED",
        "NETWORK_UNAVAILABLE": (
            "YTDLP_METADATA_FAILED"
            if str(error.get("stage") or "").startswith("metadata")
            else "DOWNLOAD_FAILED"
        ),
    }
    code = mapping.get(source_code, "UNKNOWN_ERROR")
    return _issue(code, message, report, raw_error=error or reason)


def _apply_metadata(
    report: dict[str, Any],
    metadata: dict[str, Any],
    selection: dict[str, Any],
    warnings: list[str],
) -> None:
    target = _summary(report)["metadata"]
    target.update(
        {
            "attempted": True,
            "passed": bool(metadata),
            "title": metadata.get("title"),
            "duration_seconds": metadata.get("duration"),
            "uploader": metadata.get("uploader"),
            "channel": metadata.get("channel"),
            "live_status": metadata.get("live_status"),
            "availability": metadata.get("availability"),
            "age_limit": metadata.get("age_limit"),
            "formats_count": metadata.get("formats_available_count") or 0,
            "selected_quality": selection,
            "warnings": warnings,
        }
    )


def _apply_probe(report: dict[str, Any], probe: dict[str, Any] | None) -> None:
    source = probe or {}
    target = _summary(report)["ffprobe"]
    target.update(
        {
            "attempted": True,
            "passed": bool(source.get("passed")),
            "width": source.get("width"),
            "height": source.get("height"),
            "video_codec": source.get("video_codec"),
            "audio_codec": source.get("audio_codec"),
            "audio_sample_rate": source.get("audio_sample_rate"),
            "duration": source.get("container_duration") or source.get("duration"),
            "has_video": bool(source.get("has_video")),
            "has_audio": bool(source.get("has_audio")),
            "audio_video_delta": source.get("audio_video_delta"),
            "warnings": list(source.get("warnings") or source.get("errors") or []),
        }
    )


def _safe_remove_tree(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    allowed = parent.resolve()
    if resolved == allowed or allowed not in resolved.parents:
        raise ValueError(f"Refusing to delete outside validator temp root: {resolved}")
    if not resolved.name.startswith(("direct_", "clips_")):
        raise ValueError(f"Refusing to delete unrecognized validator temp path: {resolved}")
    shutil.rmtree(resolved, ignore_errors=True)


async def run_direct_validation(
    report: dict[str, Any],
    *,
    url: str,
    mode: str,
    report_dir: Path,
    timeout_seconds: float,
    poll_interval_seconds: float,
    keep_download: bool,
    cleanup: bool,
) -> dict[str, Any]:
    """Run metadata or download validation through the canonical service directly."""

    summary = _summary(report)
    environment = summary["environment"]
    if not environment["ytdlp_installed"]:
        issue = _issue(
            "YTDLP_NOT_INSTALLED",
            "Direct validation requires yt-dlp in this Python environment.",
            report,
        )
        _set_failure(report, issue, failed_step="yt_dlp")
        return report
    if mode == LinkIngestionMode.DOWNLOAD_ONLY.value and (
        not environment["ffmpeg_available"] or not environment["ffprobe_available"]
    ):
        issue = _issue(
            "FFPROBE_FAILED",
            "Direct download validation requires FFmpeg and FFprobe.",
            report,
        )
        _set_failure(report, issue, failed_step="dependencies")
        return report

    parent = report_dir / ".direct_work"
    parent.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(
            prefix="direct_",
            dir=parent,
        )
    )
    storage = LocalStorage(str(run_root))
    base_settings = get_settings()
    link_settings = base_settings.link_ingestion.model_copy(
        update={
            "metadata_timeout_seconds": min(
                timeout_seconds,
                base_settings.link_ingestion.metadata_timeout_seconds,
            ),
            "download_timeout_seconds": timeout_seconds,
            "cleanup_partial_downloads": True,
        }
    )
    service = VideoLinkIntakeService(
        storage,
        settings=link_settings,
        ffmpeg_binary=base_settings.rendering.ffmpeg_binary,
        ffprobe_binary=base_settings.rendering.ffprobe_binary,
    )
    summary["metadata"]["attempted"] = True
    _progress(3, 6, "yt-dlp metadata", "RUNNING")
    try:
        record = await service.prepare(
            url,
            permission_confirmed=True,
            start_processing=False,
            mode=mode,
        )
        summary["direct_ingestion_id"] = record.id
        _apply_metadata(
            report,
            record.video_metadata,
            record.download_selection,
            record.warnings,
        )
        if record.status in {LinkDownloadStatus.FAILED, LinkDownloadStatus.UNAVAILABLE}:
            issue = _record_error_issue(record, report)
            _progress(3, 6, "yt-dlp metadata", "FAIL", issue.code)
            _set_failure(report, issue, failed_step="metadata")
            return report
        _progress(
            3,
            6,
            "yt-dlp metadata",
            "PASS",
            _format_duration(record.video_metadata.get("duration")),
        )
        _record_stage(report, "metadata", "PASSED")
        if mode == LinkIngestionMode.METADATA_ONLY.value:
            _set_success(report, "Direct yt-dlp metadata validation passed without a backend.")
            return report

        download = summary["download"]
        download["attempted"] = True
        download["started"] = True
        _progress(4, 6, "Direct download", "RUNNING")
        task = asyncio.create_task(service.ingest_prepared(record.id))
        last_progress: tuple[str, object] | None = None
        while not task.done():
            await asyncio.sleep(max(0.1, min(poll_interval_seconds, 2.0)))
            current = await service.get(record.id)
            status_data = current.link_ingestion_status
            progress_value = (
                str(status_data.get("current_stage") or current.status.value),
                status_data.get("progress_percent"),
            )
            if progress_value != last_progress:
                percent = progress_value[1]
                detail = (
                    f"{progress_value[0]} {float(percent):.1f}%"
                    if isinstance(percent, (int, float))
                    else str(progress_value[0])
                )
                _progress(4, 6, "Direct download", "RUNNING", detail)
                last_progress = progress_value
        record = await task
        if record.status in {LinkDownloadStatus.FAILED, LinkDownloadStatus.UNAVAILABLE}:
            issue = _record_error_issue(record, report)
            _progress(4, 6, "Direct download", "FAIL", issue.code)
            _set_failure(report, issue, failed_step="download")
            return report
        if record.upload is None:
            issue = _issue(
                "DOWNLOAD_INCOMPLETE",
                "Direct ingestion completed without a stored upload record.",
                report,
            )
            _set_failure(report, issue, failed_step="download")
            return report

        local_path_value = storage.local_path(record.upload.storage_key)
        local_path = Path(local_path_value) if local_path_value else None
        exists = bool(local_path and local_path.is_file() and local_path.stat().st_size > 0)
        download.update(
            {
                "completed": exists,
                "file_path": str(local_path) if local_path else None,
                "file_size_bytes": record.upload.size_bytes,
                "stored_file_exists": exists,
            }
        )
        if not exists or local_path is None:
            issue = _issue(
                "DOWNLOAD_INCOMPLETE",
                "The direct download was not present in isolated validator storage.",
                report,
            )
            _set_failure(report, issue, failed_step="stored_file")
            return report
        _progress(4, 6, "Direct download", "PASS", f"{record.upload.size_bytes} bytes")
        _record_stage(report, "download", "PASSED")

        _apply_probe(report, record.media_probe)
        if not summary["ffprobe"]["passed"]:
            issue = _issue(
                "FFPROBE_FAILED",
                "The downloaded media did not pass FFprobe validation.",
                report,
                raw_error=summary["ffprobe"]["warnings"],
            )
            _progress(5, 6, "FFprobe", "FAIL")
            _set_failure(report, issue, failed_step="ffprobe")
            return report
        _progress(
            5,
            6,
            "FFprobe",
            "PASS",
            f"{summary['ffprobe']['width']}x{summary['ffprobe']['height']}",
        )
        _record_stage(report, "ffprobe", "PASSED")

        if keep_download:
            keep_dir = report_dir / "downloads"
            keep_dir.mkdir(parents=True, exist_ok=True)
            destination = keep_dir / f"{record.id}_{Path(record.upload.filename).name}"
            shutil.copy2(local_path, destination)
            download["file_path"] = str(destination.resolve())
            download["kept"] = True
        elif not cleanup:
            download["kept"] = True
        _progress(6, 6, "Cleanup", "KEEP" if download["kept"] else "CLEAN")
        _set_success(report, "Direct download and FFprobe validation passed.")
        return report
    except Exception as exc:
        context = "metadata" if not summary["download"]["attempted"] else "download"
        issue = classify_exception(exc, context, report)
        _set_failure(report, issue, failed_step=context)
        return report
    finally:
        partials = [
            str(path)
            for path in run_root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".part", ".ytdl", ".tmp"}
        ]
        summary["download"]["partial_files"] = partials
        should_remove = cleanup or keep_download
        if should_remove:
            try:
                _safe_remove_tree(run_root, parent)
                summary["download"]["cleaned_up"] = True
                if not keep_download:
                    summary["download"]["file_path"] = None
            except (OSError, ValueError) as exc:
                summary["download"]["warnings"].append(f"Cleanup failed: {exc}")


def _download_dict(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("download")
    return value if isinstance(value, dict) else {}


def _project_dict(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("project")
    return value if isinstance(value, dict) else {}


def _apply_api_record(report: dict[str, Any], download: dict[str, Any]) -> None:
    summary = _summary(report)
    api = summary["api"]
    status_data = download.get("link_ingestion_status")
    status = status_data if isinstance(status_data, dict) else {}
    api["ingestion_id"] = download.get("ingestion_id") or api.get("ingestion_id")
    api["last_status"] = download.get("status")
    api["last_stage"] = status.get("current_stage") or status.get("status")
    api["pipeline_started"] = (
        api["pipeline_started"] or api["last_stage"] == "processing_started"
    )
    metadata = download.get("video_metadata")
    selection = download.get("download_selection")
    if isinstance(metadata, dict):
        _apply_metadata(
            report,
            metadata,
            selection if isinstance(selection, dict) else {},
            [str(item) for item in _list(download.get("warnings"))],
        )
    upload_exists = bool(download.get("storage_key") and download.get("size_bytes"))
    summary["download"].update(
        {
            "attempted": summary["mode"] != LinkIngestionMode.METADATA_ONLY.value,
            "started": api["last_stage"]
            in {"downloading", "merging", "probing", "stored", "processing_started"},
            "completed": upload_exists,
            "file_size_bytes": download.get("size_bytes"),
        }
    )
    probe = download.get("media_probe")
    if isinstance(probe, dict):
        _apply_probe(report, probe)


def _local_api_storage_path(
    backend_url: str,
    storage_key: str,
) -> tuple[bool | None, Path | None, str | None]:
    parsed = urllib.parse.urlparse(backend_url)
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return None, None, "Remote backend storage cannot be inspected from this validator."
    settings = get_settings()
    if str(settings.storage.backend.value) != "local":
        return None, None, "Non-local backend storage cannot be inspected directly."
    root = Path(settings.storage.local_root)
    if not root.is_absolute():
        root = ROOT / root
    root = root.resolve()
    candidate = (root / storage_key).resolve()
    if candidate != root and root not in candidate.parents:
        return False, candidate, "The API returned an unsafe storage key."
    exists = candidate.is_file() and candidate.stat().st_size > 0
    return exists, candidate, None


def _optional_json(
    backend_url: str,
    path: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    try:
        return _request_json(
            backend_url,
            "GET",
            path,
            timeout_seconds=timeout_seconds,
        )
    except HttpStatusError as exc:
        if exc.status == 404:
            return None
        raise


def _probe_file(path: Path) -> dict[str, Any]:
    settings = get_settings()
    binary = shutil.which(settings.rendering.ffprobe_binary)
    if binary is None and Path(settings.rendering.ffprobe_binary).is_file():
        binary = str(Path(settings.rendering.ffprobe_binary).resolve())
    if binary is None:
        return {"passed": False, "errors": ["ffprobe is unavailable"]}
    try:
        completed = subprocess.run(
            build_ffprobe_command(binary=binary, path=str(path)),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": False, "errors": [str(exc)]}
    if completed.returncode != 0:
        return {
            "passed": False,
            "errors": [completed.stderr.strip() or f"ffprobe exited {completed.returncode}"],
        }
    try:
        raw = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"passed": False, "errors": [f"ffprobe returned invalid JSON: {exc}"]}
    streams = [item for item in _list(raw.get("streams")) if isinstance(item, dict)]
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    container = raw.get("format") if isinstance(raw.get("format"), dict) else {}
    container_duration = _as_float(container.get("duration"))
    video_duration = _as_float(video.get("duration")) or container_duration
    audio_duration = _as_float(audio.get("duration")) or container_duration
    delta = (
        abs(video_duration - audio_duration)
        if video_duration is not None and audio_duration is not None
        else None
    )
    passed = bool(video) and bool(audio) and bool(container_duration and container_duration > 0)
    return {
        "passed": passed,
        "container_duration": container_duration,
        "video_duration": video_duration,
        "audio_duration": audio_duration,
        "audio_video_delta": delta,
        "width": _as_int(video.get("width")),
        "height": _as_int(video.get("height")),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "audio_sample_rate": _as_int(audio.get("sample_rate")),
        "has_video": bool(video),
        "has_audio": bool(audio),
        "errors": [],
    }


def _validation_truth(render: dict[str, Any], key: str) -> bool | None:
    metadata = render.get("metadata")
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    value = metadata_dict.get(key)
    if isinstance(value, dict) and isinstance(value.get("passed"), bool):
        return bool(value["passed"])
    return None


def validate_rendered_clips(
    report: dict[str, Any],
    *,
    backend_url: str,
    project_id: str,
    renders: list[dict[str, Any]],
    report_dir: Path,
    timeout_seconds: float,
) -> ValidationIssue | None:
    """Download API render copies, probe them, then remove only those copies."""

    parent = report_dir / ".clip_validation"
    parent.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="clips_", dir=parent))
    all_passed = True
    try:
        for index, render in enumerate(renders, start=1):
            clip_id = str(render.get("clip_id") or "")
            if not clip_id:
                all_passed = False
                _summary(report)["clips"].append(
                    {
                        "path": None,
                        "exists": False,
                        "width": None,
                        "height": None,
                        "duration": None,
                        "video_codec": None,
                        "audio_codec": None,
                        "passed": False,
                        "warnings": ["Render manifest is missing clip_id."],
                    }
                )
                continue
            endpoint = (
                f"/api/v1/projects/{urllib.parse.quote(project_id, safe='')}/rendering/"
                f"clips/{urllib.parse.quote(clip_id, safe='')}/download"
            )
            destination = run_root / f"{index:02d}_{clip_id}.mp4"
            warnings: list[str] = []
            try:
                _request_file(
                    backend_url,
                    endpoint,
                    destination,
                    timeout_seconds=min(120.0, timeout_seconds),
                )
                probe = _probe_file(destination)
            except Exception as exc:
                probe = {"passed": False, "errors": [str(exc)]}
            sync_truth = _validation_truth(render, "sync_validation")
            duration_truth = _validation_truth(render, "duration_validation")
            if sync_truth is False:
                warnings.append("Render manifest sync validation failed.")
            if duration_truth is False:
                warnings.append("Render manifest duration validation failed.")
            delta = _as_float(probe.get("audio_video_delta"))
            if delta is not None and delta > 0.15:
                warnings.append(f"Audio/video duration delta is {delta:.3f}s.")
            if probe.get("width") != 1080 or probe.get("height") != 1920:
                warnings.append(
                    f"Expected 1080x1920, got {probe.get('width')}x{probe.get('height')}."
                )
            warnings.extend(str(item) for item in _list(probe.get("errors")))
            passed = (
                bool(probe.get("passed"))
                and probe.get("width") == 1080
                and probe.get("height") == 1920
                and (delta is None or delta <= 0.15)
                and sync_truth is not False
                and duration_truth is not False
            )
            all_passed = all_passed and passed
            _summary(report)["clips"].append(
                {
                    "path": endpoint,
                    "exists": destination.is_file(),
                    "width": probe.get("width"),
                    "height": probe.get("height"),
                    "duration": probe.get("container_duration"),
                    "video_codec": probe.get("video_codec"),
                    "audio_codec": probe.get("audio_codec"),
                    "audio_sample_rate": probe.get("audio_sample_rate"),
                    "audio_video_delta": delta,
                    "sync_validation_passed": sync_truth,
                    "duration_validation_passed": duration_truth,
                    "passed": passed,
                    "warnings": warnings,
                }
            )
            _progress(
                index,
                len(renders),
                f"Rendered clip {clip_id}",
                "PASS" if passed else "FAIL",
            )
    finally:
        try:
            _safe_remove_tree(run_root, parent)
        except (OSError, ValueError) as exc:
            _summary(report)["api"]["warnings"].append(
                f"Temporary clip cleanup failed: {exc}"
            )
    if not all_passed:
        return _issue(
            "CLIP_VALIDATION_FAILED",
            "One or more rendered clips failed real file validation.",
            report,
        )
    return None


def _manifest_renders(manifest_response: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = manifest_response.get("manifest")
    manifest_dict = manifest if isinstance(manifest, dict) else {}
    return [item for item in _list(manifest_dict.get("renders")) if isinstance(item, dict)]


def run_api_validation(
    report: dict[str, Any],
    *,
    backend_url: str,
    url: str,
    mode: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    report_dir: Path,
) -> dict[str, Any]:
    """Validate Link Ingestion through the running Olympus API."""

    summary = _summary(report)
    api = summary["api"]
    api["attempted"] = True
    _progress(3, 8, "Backend health", "RUNNING", backend_url)
    health_issue = check_backend_health(
        report,
        backend_url=backend_url,
        timeout_seconds=min(5.0, timeout_seconds),
    )
    if health_issue:
        _progress(3, 8, "Backend health", "FAIL", health_issue.code)
        _set_failure(report, health_issue, failed_step="backend_health")
        return report
    api["backend_health_passed"] = True
    _progress(3, 8, "Backend health", "PASS")
    _record_stage(report, "backend_health", "PASSED")

    try:
        response = _request_json(
            backend_url,
            "POST",
            "/api/v1/projects/from-link",
            {
                "url": url,
                "permission_confirmed": True,
                "start_processing": mode == LinkIngestionMode.FULL_PIPELINE.value,
                "quality": "best",
                "mode": mode,
            },
            timeout_seconds=min(120.0, timeout_seconds),
        )
    except HttpStatusError as exc:
        context = "api_route" if exc.status == 404 else "backend"
        issue = classify_exception(exc, context, report)
        _set_failure(report, issue, failed_step="api_request")
        return report
    except Exception as exc:
        issue = classify_exception(exc, "backend", report)
        _set_failure(report, issue, failed_step="api_request")
        return report

    download = _download_dict(response)
    _apply_api_record(report, download)
    ingestion_id = str(api.get("ingestion_id") or "")
    if download.get("error"):
        issue = _record_error_issue(download, report)
        _set_failure(report, issue, failed_step="metadata")
        return report
    if not ingestion_id:
        issue = _issue(
            "YTDLP_METADATA_FAILED",
            "The backend response did not include a link ingestion ID.",
            report,
            raw_error=response,
        )
        _set_failure(report, issue, failed_step="metadata")
        return report
    if not summary["metadata"]["passed"]:
        issue = _issue(
            "YTDLP_METADATA_FAILED",
            "The backend did not return validated video metadata.",
            report,
            raw_error=download,
        )
        _set_failure(report, issue, failed_step="metadata")
        return report
    _progress(
        4,
        8,
        "API metadata",
        "PASS",
        _format_duration(summary["metadata"]["duration_seconds"]),
    )
    _record_stage(report, "metadata", "PASSED")
    if mode == LinkIngestionMode.METADATA_ONLY.value:
        _set_success(report, "API metadata validation passed through the running backend.")
        return report

    deadline = time.monotonic() + timeout_seconds
    last_progress: tuple[str, object] | None = None
    project: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            response = _request_json(
                backend_url,
                "GET",
                f"/api/v1/projects/link-ingestions/{urllib.parse.quote(ingestion_id, safe='')}",
                timeout_seconds=min(60.0, timeout_seconds),
            )
        except Exception as exc:
            if isinstance(exc, BackendConnectionError):
                issue = classify_exception(exc, "backend", report)
            else:
                issue = _issue(
                    "DOWNLOAD_FAILED",
                    "The API ingestion status could not be read.",
                    report,
                    raw_error=exc,
                )
            _set_failure(report, issue, failed_step="ingestion_poll")
            return report
        download = _download_dict(response)
        project = _project_dict(response)
        _apply_api_record(report, download)
        progress_value = (str(api.get("last_stage") or ""), api.get("last_status"))
        if progress_value != last_progress:
            status_data = download.get("link_ingestion_status")
            status_dict = status_data if isinstance(status_data, dict) else {}
            percent = status_dict.get("progress_percent")
            detail = (
                f"{progress_value[0]} {float(percent):.1f}%"
                if isinstance(percent, (int, float))
                else progress_value[0]
            )
            _progress(5, 8, "API ingestion", "RUNNING", detail)
            last_progress = progress_value
        if download.get("error") or download.get("status") in {"failed", "unavailable"}:
            issue = _record_error_issue(download, report)
            _set_failure(report, issue, failed_step=str(api.get("last_stage") or "ingestion"))
            return report
        if summary["download"]["completed"]:
            break
        time.sleep(max(0.1, poll_interval_seconds))
    else:
        issue = _issue(
            "DOWNLOAD_FAILED",
            "API download did not complete before the timeout.",
            report,
        )
        _set_failure(report, issue, failed_step="download")
        return report

    storage_key = str(download.get("storage_key") or "")
    stored, stored_path, storage_warning = _local_api_storage_path(backend_url, storage_key)
    if storage_warning:
        summary["download"]["warnings"].append(storage_warning)
    if stored_path:
        summary["download"]["file_path"] = str(stored_path)
    if stored is not None:
        summary["download"]["stored_file_exists"] = stored
        if not stored:
            issue = _issue(
                "DOWNLOAD_INCOMPLETE",
                "The API reported storage, but the local source file is missing or empty.",
                report,
                raw_error=stored_path,
            )
            _set_failure(report, issue, failed_step="stored_file")
            return report
    else:
        summary["download"]["stored_file_exists"] = bool(storage_key)
    if not summary["ffprobe"]["passed"]:
        issue = _issue(
            "FFPROBE_FAILED",
            "The API download did not include a passing media probe.",
            report,
            raw_error=summary["ffprobe"]["warnings"],
        )
        _set_failure(report, issue, failed_step="ffprobe")
        return report
    _progress(5, 8, "API ingestion", "PASS", str(api.get("last_stage") or "stored"))
    _record_stage(report, "download_and_probe", "PASSED")
    if mode == LinkIngestionMode.DOWNLOAD_ONLY.value:
        _set_success(report, "API download, storage, and FFprobe validation passed.")
        return report

    try:
        while time.monotonic() < deadline and not project.get("id"):
            time.sleep(max(0.1, poll_interval_seconds))
            response = _request_json(
                backend_url,
                "GET",
                f"/api/v1/projects/link-ingestions/{urllib.parse.quote(ingestion_id, safe='')}",
                timeout_seconds=min(60.0, timeout_seconds),
            )
            download = _download_dict(response)
            project = _project_dict(response)
            _apply_api_record(report, download)
            if download.get("error"):
                issue = _record_error_issue(download, report)
                _set_failure(report, issue, failed_step="project_creation")
                return report
    except Exception as exc:
        if isinstance(exc, BackendConnectionError):
            issue = classify_exception(exc, "backend", report)
        else:
            issue = _issue(
                "PROJECT_CREATION_FAILED",
                "Project creation status could not be read.",
                report,
                raw_error=exc,
            )
        _set_failure(report, issue, failed_step="project_creation")
        return report
    project_id = str(project.get("id") or "")
    if not project_id:
        issue = _issue(
            "PROJECT_CREATION_FAILED",
            "The source was stored, but no project was created before timeout.",
            report,
        )
        _set_failure(report, issue, failed_step="project_creation")
        return report
    api["project_id"] = project_id
    api["project_status"] = project.get("status")
    api["pipeline_started"] = api["pipeline_started"] or project.get("status") in {
        "analyzing",
        "analyzed",
        "queued",
        "processing",
        "complete",
    }
    if not api["pipeline_started"]:
        issue = _issue(
            "PIPELINE_START_FAILED",
            "The project exists, but processing did not start.",
            report,
        )
        _set_failure(report, issue, failed_step="pipeline_start")
        return report
    _progress(6, 8, "Project and pipeline", "PASS", project_id)
    _record_stage(report, "pipeline_start", "PASSED", project_id)

    manifest_response: dict[str, Any] | None = None
    try:
        while time.monotonic() < deadline:
            project_payload = _request_json(
                backend_url,
                "GET",
                f"/api/v1/projects/{urllib.parse.quote(project_id, safe='')}",
                timeout_seconds=min(60.0, timeout_seconds),
            )
            api["project_status"] = project_payload.get("status")
            workflow = _optional_json(
                backend_url,
                f"/api/v1/projects/{urllib.parse.quote(project_id, safe='')}/workflow",
                timeout_seconds=min(60.0, timeout_seconds),
            )
            if workflow:
                api["workflow_status"] = workflow.get("status")
                api["last_stage"] = workflow.get("current_stage") or api["last_stage"]
            rendering = _optional_json(
                backend_url,
                f"/api/v1/projects/{urllib.parse.quote(project_id, safe='')}/rendering",
                timeout_seconds=min(60.0, timeout_seconds),
            )
            if rendering:
                api["render_status"] = rendering.get("status")
            if str(api.get("project_status") or "") in TERMINAL_PIPELINE_STATUSES or str(
                api.get("workflow_status") or ""
            ) in TERMINAL_PIPELINE_STATUSES or str(
                api.get("render_status") or ""
            ) in TERMINAL_PIPELINE_STATUSES:
                issue = _issue(
                    "PIPELINE_FAILED",
                    "The project or render pipeline entered a terminal failure state.",
                    report,
                    raw_error={
                        "project": api.get("project_status"),
                        "workflow": api.get("workflow_status"),
                        "render": api.get("render_status"),
                        "last_stage": api.get("last_stage"),
                    },
                )
                _set_failure(report, issue, failed_step="pipeline")
                return report
            manifest_response = _optional_json(
                backend_url,
                f"/api/v1/projects/{urllib.parse.quote(project_id, safe='')}/rendering/manifest",
                timeout_seconds=min(60.0, timeout_seconds),
            )
            if manifest_response is not None:
                renders = _manifest_renders(manifest_response)
                if renders:
                    break
                manifest = manifest_response.get("manifest")
                manifest_dict = manifest if isinstance(manifest, dict) else {}
                if manifest_dict.get("status") == "completed":
                    issue = _issue(
                        "NO_CLIPS_RENDERED",
                        "The render manifest completed with zero clips.",
                        report,
                    )
                    _set_failure(report, issue, failed_step="rendering")
                    return report
            _progress(
                7,
                8,
                "Pipeline",
                "RUNNING",
                str(api.get("last_stage") or api.get("project_status") or "processing"),
            )
            time.sleep(max(0.1, poll_interval_seconds))
        else:
            issue = _issue(
                "PIPELINE_TIMEOUT",
                "The full pipeline did not render clips before the timeout.",
                report,
            )
            _set_failure(report, issue, failed_step="pipeline")
            return report
    except Exception as exc:
        context = "backend" if isinstance(exc, BackendConnectionError) else "pipeline"
        issue = classify_exception(exc, context, report)
        _set_failure(report, issue, failed_step="pipeline_poll")
        return report

    renders = _manifest_renders(manifest_response or {})
    api["clips_rendered"] = len(renders)
    _progress(7, 8, "Pipeline", "PASS", f"{len(renders)} clips")
    _record_stage(report, "rendering", "PASSED", f"{len(renders)} clips")
    clip_issue = validate_rendered_clips(
        report,
        backend_url=backend_url,
        project_id=project_id,
        renders=renders,
        report_dir=report_dir,
        timeout_seconds=max(1.0, deadline - time.monotonic()),
    )
    if clip_issue:
        _set_failure(report, clip_issue, failed_step="clip_validation")
        return report
    frontend_valid = all(
        bool(render.get("clip_id"))
        and isinstance(render.get("metadata"), dict)
        for render in renders
    )
    api["frontend_payload_passed"] = frontend_valid
    if not frontend_valid:
        issue = _issue(
            "FRONTEND_PAYLOAD_FAILED",
            "The render manifest is missing clip IDs or frontend metadata.",
            report,
        )
        _set_failure(report, issue, failed_step="frontend_payload")
        return report
    _progress(8, 8, "Clips and frontend payload", "PASS")
    _record_stage(report, "frontend_payload", "PASSED")
    _set_success(report, "Full API pipeline produced and validated rendered clips.")
    return report


def run_validation(
    *,
    base: str,
    url: str,
    mode: str,
    rights_confirmed: bool,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    """Backward-compatible API helper returning the V2 report contract."""

    report = _empty_report(
        url=url,
        mode=mode,
        backend_url=base,
        rights_confirmed=rights_confirmed,
        execution_mode="api",
    )
    check_environment(report, report_dir=DEFAULT_REPORT_DIR)
    url_issue = validate_url(report, url)
    if url_issue:
        _set_failure(report, url_issue, failed_step="url_validation")
        return report
    if not rights_confirmed:
        rights_issue = _issue(
            "RIGHTS_CONFIRMATION_REQUIRED",
            "Explicit rights confirmation is required for API validation.",
            report,
        )
        _set_failure(report, rights_issue, failed_step="rights_confirmation")
        return report
    return run_api_validation(
        report,
        backend_url=base,
        url=url,
        mode=mode,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        report_dir=DEFAULT_REPORT_DIR,
    )


def write_reports(
    report: dict[str, Any],
    report_dir: Path,
) -> dict[str, str]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / REPORT_JSON_NAME
    markdown_path = report_dir / REPORT_MARKDOWN_NAME
    paths = {
        "json": str(json_path.resolve()),
        "markdown": str(markdown_path.resolve()),
    }
    _summary(report)["report_files"] = paths
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return paths


def _markdown_report(report: dict[str, Any]) -> str:
    summary = _summary(report)
    result = summary["result"]
    environment = summary["environment"]
    metadata = summary["metadata"]
    download = summary["download"]
    api = summary["api"]
    execution = (
        "direct"
        if summary["direct_mode"]
        else "api"
        if summary["api_mode"]
        else "none"
    )
    ytdlp_status = (
        f"{_word(environment['ytdlp_installed'])} "
        f"({environment.get('ytdlp_version') or 'not available'})"
    )
    lines = [
        "# Link Ingestion Validation V2",
        "",
        f"- Status: **{result['status']}**",
        f"- Mode: {summary['mode']}",
        f"- Execution: {execution}",
        f"- Workspace: {summary['workspace']}",
        f"- Branch: {summary.get('branch') or 'unknown'}",
        f"- Backend: {summary['backend_url']}",
        f"- Rights confirmed: {summary['rights_confirmed']}",
        "",
        "## Environment",
        "",
        f"- Python: {environment['python']} ({environment['python_version']})",
        f"- Olympus import: {_word(environment['olympus_imported'])}",
        f"- yt-dlp: {ytdlp_status}",
        f"- FFmpeg: {_word(environment['ffmpeg_available'])}",
        f"- FFprobe: {_word(environment['ffprobe_available'])}",
        f"- Backend reachable: {_word(environment['backend_reachable'])}",
        f"- API routes: {', '.join(environment['api_routes_found']) or 'not verified'}",
        f"- Work directory writable: {_word(environment['workdir_writable'])}",
        "",
        "## Source",
        "",
        f"- URL validation: {_word(summary['url_validation']['passed'])}",
        f"- Canonical URL: {summary['url_validation'].get('canonical_url') or 'not available'}",
        f"- Metadata attempted: {_word(metadata['attempted'])}",
        f"- Metadata passed: {_word(metadata['passed'])}",
        f"- Title: {_md(metadata.get('title') or 'not available')}",
        f"- Duration: {_format_duration(metadata.get('duration_seconds'))}",
        f"- Formats: {metadata.get('formats_count') or 0}",
        "",
        "## Download",
        "",
        f"- Attempted: {_word(download['attempted'])}",
        f"- Completed: {_word(download['completed'])}",
        f"- Stored file verified: {_word(download['stored_file_exists'])}",
        f"- File: {_md(download.get('file_path') or 'not retained')}",
        f"- Kept: {_word(download['kept'])}",
        f"- Validator cleanup: {_word(download['cleaned_up'])}",
        f"- FFprobe: {_word(summary['ffprobe']['passed'])}",
        "",
        "## API",
        "",
        f"- Attempted: {_word(api['attempted'])}",
        f"- Backend health: {_word(api['backend_health_passed'])}",
        f"- Ingestion ID: {api.get('ingestion_id') or 'not available'}",
        f"- Project ID: {api.get('project_id') or 'not available'}",
        f"- Last stage: {api.get('last_stage') or 'not available'}",
        f"- Pipeline started: {_word(api['pipeline_started'])}",
        f"- Clips rendered: {api.get('clips_rendered') or 0}",
        f"- Frontend payload: {_word(api['frontend_payload_passed'])}",
        "",
    ]
    clips = summary["clips"]
    if clips:
        lines.extend(
            [
                "## Rendered Clips",
                "",
                "| Clip | Resolution | Duration | A/V Delta | Passed |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for clip in clips:
            lines.append(
                f"| {_md(clip.get('path') or 'unknown')} | "
                f"{clip.get('width')}x{clip.get('height')} | "
                f"{clip.get('duration') or 'n/a'} | "
                f"{clip.get('audio_video_delta') or 0} | {_word(clip.get('passed'))} |"
            )
        lines.append("")
    if summary["errors"]:
        lines.extend(["## Failure", ""])
        for error in summary["errors"]:
            lines.extend(
                [
                    f"### {error['code']}",
                    "",
                    f"- Message: {_md(error['message'])}",
                    f"- Likely cause: {_md(error['likely_cause'])}",
                    f"- Next action: {_md(error['next_action'])}",
                    "",
                    "Command to try:",
                    "",
                    "    " + str(error["command_to_try"]).replace("\n", "\n    "),
                    "",
                ]
            )
    else:
        lines.extend(["## Result", "", str(result["message"]), ""])
    return "\n".join(lines)


def _word(value: object) -> str:
    return "PASS" if bool(value) else "NO"


def _md(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _format_duration(value: object) -> str:
    duration = _as_float(value)
    if duration is None:
        return "not available"
    total = max(0, round(duration))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _invalid_cli_issue(
    args: argparse.Namespace,
    report: dict[str, Any],
) -> ValidationIssue | None:
    mode = _mode(args)
    if args.timeout_seconds <= 0 or args.poll_interval_seconds <= 0:
        return _issue(
            "UNKNOWN_ERROR",
            "Timeout and poll interval values must be positive.",
            report,
        )
    if mode != "self_check" and not args.url:
        return _issue("URL_INVALID", "--url is required for this mode.", report)
    if args.full_pipeline and args.direct:
        return _issue(
            "API_ROUTE_UNAVAILABLE",
            "Full-pipeline validation requires the Olympus backend and cannot run direct.",
            report,
        )
    if (args.self_check or args.diagnose) and (args.direct or args.api):
        return _issue(
            "UNKNOWN_ERROR",
            "--direct and --api do not apply to self-check or diagnose mode.",
            report,
        )
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = _mode(args)
    execution_mode = _execution_mode(args)
    report_dir = args.report_dir
    if not report_dir.is_absolute():
        report_dir = (ROOT / report_dir).resolve()
    report = _empty_report(
        url=args.url,
        mode=mode,
        backend_url=args.backend_url,
        rights_confirmed=args.confirm_rights,
        execution_mode=execution_mode,
    )
    try:
        cli_issue = _invalid_cli_issue(args, report)
        if cli_issue:
            _set_failure(report, cli_issue, failed_step="arguments")
        elif args.self_check:
            run_self_check(
                report,
                backend_url=args.backend_url,
                report_dir=report_dir,
            )
        else:
            environment = check_environment(report, report_dir=report_dir)
            _progress(1, 6 if execution_mode == "direct" else 8, "Environment", "PASS")
            url_issue = validate_url(report, str(args.url))
            if url_issue:
                _progress(2, 6 if execution_mode == "direct" else 8, "URL validation", "FAIL")
                _set_failure(report, url_issue, failed_step="url_validation")
            else:
                _progress(2, 6 if execution_mode == "direct" else 8, "URL validation", "PASS")
                if args.diagnose:
                    _set_success(
                        report,
                        "URL syntax and source policy validation passed; no metadata was read.",
                    )
                elif not args.confirm_rights:
                    rights_issue = _issue(
                        "RIGHTS_CONFIRMATION_REQUIRED",
                        "Explicit --confirm-rights is required before metadata or download access.",
                        report,
                    )
                    _set_failure(
                        report,
                        rights_issue,
                        failed_step="rights_confirmation",
                    )
                elif execution_mode == "direct":
                    asyncio.run(
                        run_direct_validation(
                            report,
                            url=str(args.url),
                            mode=mode,
                            report_dir=report_dir,
                            timeout_seconds=args.timeout_seconds,
                            poll_interval_seconds=args.poll_interval_seconds,
                            keep_download=args.keep_download,
                            cleanup=args.cleanup,
                        )
                    )
                else:
                    if not environment["olympus_imported"]:
                        raise RuntimeError("Olympus could not be imported.")
                    run_api_validation(
                        report,
                        backend_url=args.backend_url,
                        url=str(args.url),
                        mode=mode,
                        timeout_seconds=args.timeout_seconds,
                        poll_interval_seconds=args.poll_interval_seconds,
                        report_dir=report_dir,
                    )
    except Exception as exc:
        issue = classify_exception(exc, "unknown", report)
        _set_failure(report, issue, failed_step="validator")
        if args.debug:
            _summary(report)["debug_traceback"] = traceback.format_exc()

    try:
        paths = write_reports(report, report_dir)
        _summary(report)["report_files"] = paths
    except OSError as exc:
        print(f"REPORT_WRITE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    result = _summary(report)["result"]
    if result.get("command_to_try"):
        print(
            f"\nNext command:\n{result['command_to_try']}",
            file=sys.stderr,
        )
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())

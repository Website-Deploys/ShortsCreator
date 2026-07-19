"""Run the final Olympus V2 release-candidate QA and write evidence reports."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.validation.real_video import run_ffprobe  # noqa: E402
from olympus.validation.release_candidate import (  # noqa: E402
    DECISION_BLOCKED,
    DECISION_NOT_READY,
    add_blocker,
    audit_validators,
    build_release_candidate_report,
    collect_environment,
    command_result_skipped,
    evaluate_release_candidate,
    inspect_artifacts,
    run_command,
    set_system_result,
    write_release_candidate_report,
)

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "release_candidate"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
REQUIRED_DOCS = (
    "docs/RUNTIME_VALIDATION_V2.md",
    "docs/LINK_INGESTION_V2.md",
    "docs/INTERNET_TREND_RESEARCH_V2.md",
    "docs/LIVE_RUNTIME_INTERNET_TREND_PROVIDER_V2.md",
    "docs/MUSIC_INTELLIGENCE_V2.md",
    "docs/CURATED_MUSIC_LIBRARY_V2.md",
    "docs/MULTI_SPEAKER_LAYOUT_V2.md",
    "docs/CAPTIONS_TYPOGRAPHY_V2.md",
    "docs/MOTION_GRAPHICS_EFFECTS_V2.md",
    "docs/LONG_VIDEO_VALIDATION_V2.md",
    "docs/COPYRIGHT_SAFETY_CHECKER_V2.md",
    "docs/TITLE_DESCRIPTION_HASHTAG_V2.md",
    "docs/CREATOR_PERSONALIZATION_V2.md",
    "docs/DURABLE_JOB_QUEUE_RESUME_V2.md",
    "docs/OLYMPUS_V2_RELEASE_CANDIDATE_QA.md",
    "docs/OLYMPUS_V2_RELEASE_NOTES_DRAFT.md",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--full", action="store_true")
    modes.add_argument("--fast", action="store_true")
    modes.add_argument("--static-only", action="store_true")
    modes.add_argument("--runtime-only", action="store_true")
    modes.add_argument("--from-existing-reports", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--youtube-url")
    parser.add_argument("--confirm-rights", action="store_true")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-slow", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=7200.0)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.sample and not args.sample.is_file():
        parser.error(f"--sample does not exist: {args.sample}")
    if args.youtube_url and not args.confirm_rights:
        parser.error("--youtube-url requires --confirm-rights")
    return args


def _mode(args: argparse.Namespace) -> str:
    if args.full:
        return "full"
    if args.fast:
        return "fast"
    if args.static_only:
        return "static_only"
    if args.runtime_only:
        return "runtime_only"
    return "from_existing_reports"


def _python_executable() -> Path:
    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    return candidate if candidate.is_file() else Path(sys.executable)


def _subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(SRC) if not existing else f"{SRC}{os.pathsep}{existing}"
    return environment


def _run_static_suites(
    report: dict[str, Any],
    *,
    args: argparse.Namespace,
    mode: str,
    python: Path,
) -> None:
    top = report["olympus_v2_release_candidate"]
    if mode not in {"full", "fast", "static_only"}:
        for name in top["test_suites"]:
            top["test_suites"][name] = command_result_skipped(
                name,
                f"Static suites are outside {mode} mode.",
                code="QA_MODE_SKIPPED",
            )
        return

    timeout = min(args.timeout_seconds, 3600.0)
    environment = _subprocess_environment()
    commands = {
        "ruff": (ROOT, [str(python), "-m", "ruff", "check", "src", "tests", "tools"]),
        "pytest": (ROOT, [str(python), "-m", "pytest"]),
        "mypy": (ROOT, [str(python), "-m", "mypy", "src"]),
    }
    for name, (cwd, command) in commands.items():
        top["test_suites"][name] = run_command(
            f"test_suite_{name}",
            command,
            cwd=cwd,
            timeout_seconds=timeout,
            env=environment,
        )

    frontend_commands = {
        "frontend_typecheck": ["run", "typecheck"],
        "frontend_lint": ["run", "lint"],
        "frontend_tests": ["test"],
        "frontend_build": ["run", "build"],
    }
    npm = shutil.which("npm")
    for name, npm_args in frontend_commands.items():
        if args.skip_frontend:
            top["test_suites"][name] = command_result_skipped(
                name,
                "Frontend checks were explicitly skipped.",
                code="FRONTEND_SKIPPED",
            )
        elif npm is None:
            result = command_result_skipped(
                name,
                "npm is unavailable.",
                code="EXECUTABLE_MISSING",
                command=("npm", *npm_args),
            )
            result["passed"] = False
            result["status"] = "failed"
            top["test_suites"][name] = result
        else:
            top["test_suites"][name] = run_command(
                f"test_suite_{name}",
                [npm, *npm_args],
                cwd=ROOT / "frontend",
                timeout_seconds=timeout,
                env=environment,
            )


def _validator_commands(
    python: Path, report_dir: Path
) -> list[tuple[str, str, list[str | Path], bool]]:
    durable_dir = report_dir / "validators" / "durable_jobs"
    return [
        (
            "live_trend_self_check",
            "live_trend_provider_v2",
            [python, "tools/validate_live_trend_provider.py", "--self-check"],
            True,
        ),
        (
            "live_trend_offline",
            "live_trend_provider_v2",
            [
                python,
                "tools/validate_live_trend_provider.py",
                "--offline",
                "--niche",
                "motivational",
            ],
            True,
        ),
        (
            "trend_research_offline",
            "trend_research_v2",
            [
                python,
                "tools/validate_trend_research.py",
                "--offline",
                "--niche",
                "motivational",
                "--report",
                report_dir / "validators" / "trend_research.json",
            ],
            True,
        ),
        (
            "copyright_safety_simulation",
            "copyright_safety_v2",
            [
                python,
                "tools/validate_copyright_safety.py",
                "--simulate",
                "--source",
                "third_party_youtube",
                "--music",
                "generated_safe",
            ],
            True,
        ),
        (
            "upload_metadata_simulation",
            "upload_metadata_v2",
            [
                python,
                "tools/validate_upload_metadata.py",
                "--simulate",
                "--niche",
                "motivational",
                "--hook-category",
                "curiosity_gap",
                "--report",
                report_dir / "validators" / "upload_metadata.json",
            ],
            True,
        ),
        (
            "creator_personalization_self_check",
            "creator_personalization_v2",
            [python, "tools/validate_creator_personalization.py", "--self-check"],
            True,
        ),
        (
            "creator_personalization_simulation",
            "creator_personalization_v2",
            [
                python,
                "tools/validate_creator_personalization.py",
                "--simulate",
                "--profile",
                "motivational_shorts",
                "--niche",
                "motivational",
            ],
            True,
        ),
        (
            "durable_jobs_self_check",
            "durable_jobs_v2",
            [
                python,
                "tools/validate_durable_jobs.py",
                "--self-check",
                "--report-dir",
                durable_dir,
            ],
            True,
        ),
        (
            "durable_jobs_crash",
            "durable_jobs_v2",
            [
                python,
                "tools/validate_durable_jobs.py",
                "--simulate-crash",
                "--report-dir",
                durable_dir,
            ],
            True,
        ),
        (
            "durable_jobs_resume",
            "durable_jobs_v2",
            [
                python,
                "tools/validate_durable_jobs.py",
                "--simulate-resume",
                "--report-dir",
                durable_dir,
            ],
            True,
        ),
        (
            "durable_jobs_cancel",
            "durable_jobs_v2",
            [
                python,
                "tools/validate_durable_jobs.py",
                "--simulate-cancel",
                "--report-dir",
                durable_dir,
            ],
            True,
        ),
        (
            "durable_jobs_retry",
            "durable_jobs_v2",
            [
                python,
                "tools/validate_durable_jobs.py",
                "--simulate-retry",
                "--report-dir",
                durable_dir,
            ],
            True,
        ),
        (
            "durable_jobs_duplicate",
            "durable_jobs_v2",
            [
                python,
                "tools/validate_durable_jobs.py",
                "--simulate-duplicate",
                "--report-dir",
                durable_dir,
            ],
            True,
        ),
        (
            "long_video_discovery",
            "long_video_validation_v2",
            [
                python,
                "tools/validate_long_video.py",
                "--discover",
                "--report-dir",
                report_dir / "validators" / "long_video_discovery",
            ],
            True,
        ),
        (
            "music_intelligence_simulation",
            "music_v2",
            [python, "tools/validate_music_intelligence.py", "--simulate"],
            False,
        ),
        (
            "curated_music_inventory",
            "curated_music_library_v2",
            [python, "tools/validate_music_intelligence.py", "--list-assets"],
            False,
        ),
        (
            "caption_typography_simulation",
            "captions_v2",
            [python, "tools/validate_caption_typography.py", "--simulate"],
            False,
        ),
        (
            "motion_effects_simulation",
            "motion_effects_v2",
            [
                python,
                "tools/validate_motion_effects.py",
                "--simulate",
                "--niche",
                "motivational",
                "--hook-category",
                "curiosity_gap",
            ],
            False,
        ),
        (
            "multi_speaker_layout_simulation",
            "multi_speaker_layout_v2",
            [python, "tools/validate_multi_speaker_layout.py", "--simulate"],
            False,
        ),
        (
            "link_ingestion_self_check",
            "link_ingestion",
            [python, "tools/validate_link_ingestion.py", "--self-check"],
            False,
        ),
    ]


def _run_validators(
    report: dict[str, Any],
    *,
    args: argparse.Namespace,
    mode: str,
    python: Path,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if mode in {"static_only", "from_existing_reports"}:
        for _, system, _, _ in _validator_commands(python, args.report_dir):
            if system not in grouped:
                grouped[system].append(
                    command_result_skipped(
                        f"{system}_validators",
                        f"Subsystem validators are outside {mode} mode.",
                        code="QA_MODE_SKIPPED",
                    )
                )
        for system, checks in grouped.items():
            set_system_result(
                report,
                system,
                checks,
                evidence_kind="not_run",
                warnings=(f"Validators skipped in {mode} mode.",),
            )
        return grouped

    environment = _subprocess_environment()
    timeout = min(args.timeout_seconds, 1800.0)
    for check_id, system, command, required in _validator_commands(python, args.report_dir):
        tool = ROOT / os.fspath(command[1])
        if not tool.is_file():
            result = command_result_skipped(
                check_id,
                f"Validator does not exist: {tool}",
                code="VALIDATOR_MISSING",
                command=[os.fspath(item) for item in command],
            )
            if required:
                result["passed"] = False
                result["status"] = "failed"
                result["errors"] = result.pop("warnings")
                result["warnings"] = []
        else:
            result = run_command(
                check_id,
                command,
                cwd=ROOT,
                timeout_seconds=timeout,
                env=environment,
            )
        grouped[system].append(result)

    missing_synthetic = command_result_skipped(
        "multi_speaker_layout_synthetic_mode",
        (
            "The requested --synthetic mode does not exist; --simulate was run instead. "
            "Add --synthetic as an alias or update the canonical QA command."
        ),
        code="VALIDATOR_MODE_MISSING",
        command=(str(python), "tools/validate_multi_speaker_layout.py", "--synthetic"),
    )
    grouped["multi_speaker_layout_v2"].append(missing_synthetic)

    for system, checks in grouped.items():
        warnings = (
            ("Required validator CLI mode is missing.",)
            if any(item.get("code") == "VALIDATOR_MODE_MISSING" for item in checks)
            else ()
        )
        set_system_result(
            report,
            system,
            checks,
            evidence_kind="simulation_or_structural_validator",
            warnings=warnings,
        )
    return grouped


def _set_source_contract_systems(report: dict[str, Any]) -> None:
    top = report["olympus_v2_release_candidate"]
    pytest_passed = top["test_suites"]["pytest"].get("passed") is True
    ruff_passed = top["test_suites"]["ruff"].get("passed") is True
    backend_imported = top["environment"].get("backend_import_ok") is True
    for system, paths in {
        "story_v2": ("src/olympus/story", "tests/unit/test_story.py"),
        "virality_v2": ("src/olympus/virality", "tests/unit/test_virality.py"),
        "planning_v2": ("src/olympus/planning", "tests/unit/test_planning.py"),
        "editing_rendering_v2": (
            "src/olympus/editing",
            "src/olympus/rendering",
            "tests/unit/test_editing.py",
            "tests/unit/test_rendering.py",
        ),
    }.items():
        present = all((ROOT / path).exists() for path in paths)
        passed = present and pytest_passed and ruff_passed
        top["systems"][system] = {
            "status": "passed" if passed else "warning" if present else "failed",
            "passed": True if passed else None if present else False,
            "evidence_kind": "source_presence_and_full_backend_test_suite",
            "checks": [{"paths": list(paths), "paths_present": present}],
            "warnings": [] if passed else ["Fresh subsystem-specific runtime proof is separate."],
            "errors": [] if present else ["Expected source/test paths are missing."],
        }

    frontend_passed = all(
        top["test_suites"][name].get("passed") is True
        for name in ("frontend_typecheck", "frontend_lint", "frontend_tests", "frontend_build")
    )
    top["systems"]["frontend_results_ui"] = {
        "status": "passed" if frontend_passed else "failed",
        "passed": frontend_passed,
        "evidence_kind": "frontend_typecheck_lint_tests_build",
        "checks": [
            top["test_suites"][name]
            for name in top["test_suites"]
            if name.startswith("frontend")
        ],
        "warnings": ["No manual browser session was performed."],
        "errors": [] if frontend_passed else ["One or more frontend suites did not pass."],
    }
    api_passed = backend_imported and pytest_passed
    top["systems"]["api_contracts"] = {
        "status": "passed" if api_passed else "failed",
        "passed": api_passed,
        "evidence_kind": "backend_import_and_api_unit_tests",
        "checks": [top["environment"]["checks"].get("backend_import", {})],
        "warnings": [],
        "errors": [] if api_passed else ["Backend import or pytest evidence failed."],
    }


def _http_json(base_url: str, path: str, *, timeout: float = 10.0) -> tuple[int, Any]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            if "json" in content_type:
                return response.status, json.loads(body.decode("utf-8"))
            return response.status, body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def _backend_live(base_url: str) -> bool:
    try:
        status, payload = _http_json(base_url, "/api/v1/health/live", timeout=3.0)
        return status == 200 and isinstance(payload, dict)
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _can_bind_backend(base_url: str) -> tuple[bool, str | None, int | None]:
    parsed = urllib.parse.urlsplit(base_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
        return False, host, port
    bind_host = "127.0.0.1" if host == "localhost" else host
    family = socket.AF_INET6 if bind_host == "::1" else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.bind((bind_host, port))
        return True, bind_host, port
    except OSError:
        return False, bind_host, port


def _start_isolated_backend(
    *,
    base_url: str,
    python: Path,
    report_dir: Path,
) -> tuple[subprocess.Popen[str] | None, Any, dict[str, Any]]:
    can_bind, host, port = _can_bind_backend(base_url)
    if not can_bind or host is None or port is None:
        return None, None, {
            "started": False,
            "isolated": False,
            "error": "Backend URL is non-local or its port is occupied; no process was killed.",
            "command": None,
        }
    runtime_root = report_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    log_path = runtime_root / "backend.log"
    log_handle = log_path.open("w", encoding="utf-8")
    environment = _subprocess_environment()
    environment.update(
        {
            "OLYMPUS_STORAGE__LOCAL_ROOT": str(runtime_root / "storage"),
            "OLYMPUS_DURABLE_JOBS__STORAGE_DIR": str(runtime_root / "jobs"),
            "OLYMPUS_CREATOR_PERSONALIZATION__STORAGE_DIR": str(
                runtime_root / "personalization"
            ),
            "OLYMPUS_TREND_RESEARCH__CACHE_DIR": "trend_cache",
        }
    )
    command = [
        str(python),
        "-m",
        "uvicorn",
        "olympus.api.app:app",
        "--app-dir",
        "src",
        "--host",
        host,
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(90):
        if process.poll() is not None:
            break
        if _backend_live(base_url):
            return process, log_handle, {
                "started": True,
                "isolated": True,
                "error": None,
                "command": subprocess.list2cmdline(command),
                "pid": process.pid,
                "log_path": str(log_path),
                "storage_root": str(runtime_root / "storage"),
                "jobs_root": str(runtime_root / "jobs"),
                "trend_cache_key": "trend_cache",
            }
        time.sleep(0.5)
    return process, log_handle, {
        "started": False,
        "isolated": True,
        "error": f"Backend did not become live; exit_code={process.poll()!r}.",
        "command": subprocess.list2cmdline(command),
        "pid": process.pid,
        "log_path": str(log_path),
        "storage_root": str(runtime_root / "storage"),
        "jobs_root": str(runtime_root / "jobs"),
        "trend_cache_key": "trend_cache",
    }


def _stop_owned_backend(process: subprocess.Popen[str] | None, log_handle: Any) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    if log_handle is not None:
        log_handle.close()


def _probe_backend_contracts(base_url: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    openapi: dict[str, Any] = {}
    for path in ("/docs", "/api/v1/health/live", "/api/v1/system/info", "/openapi.json"):
        try:
            status, payload = _http_json(base_url, path)
            checks.append({"path": path, "status": status, "passed": status == 200})
            if path == "/openapi.json" and isinstance(payload, dict):
                openapi = payload
        except (OSError, ValueError, urllib.error.URLError) as exc:
            checks.append({"path": path, "status": None, "passed": False, "error": str(exc)})
    raw_paths = openapi.get("paths")
    paths: dict[str, Any] = dict(raw_paths) if isinstance(raw_paths, dict) else {}
    required_fragments = (
        "/api/v1/projects",
        "/api/v1/jobs",
        "/api/v1/personalization/profiles",
        "/api/v1/projects/{project_id}/optimization",
        "/api/v1/projects/{project_id}/rendering/clips/{clip_id}/download",
    )
    required_paths = {
        fragment: any(path == fragment for path in paths) for fragment in required_fragments
    }
    passed = all(item["passed"] for item in checks) and all(required_paths.values())
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "evidence_kind": "live_openapi_and_health_routes",
        "checks": checks,
        "required_paths": required_paths,
        "warnings": [],
        "errors": [] if passed else ["One or more live API contract checks failed."],
    }


def _discover_samples(explicit: Path | None) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    explicit_resolved = explicit.resolve() if explicit else None
    if explicit_resolved is not None:
        candidates.append(explicit_resolved)
    for directory in (
        ROOT / "validation_samples",
        ROOT / "samples",
        ROOT / "test_media",
        ROOT / "media",
        ROOT / "work" / "validation_samples",
    ):
        if directory.is_dir():
            candidates.extend(
                path for path in directory.rglob("*") if path.suffix.lower() in VIDEO_EXTENSIONS
            )
    uploads = ROOT / "storage_data" / "uploads"
    if uploads.is_dir():
        candidates.extend(
            path
            for path in uploads.glob("**/source.*")
            if path.suffix.lower() in VIDEO_EXTENSIONS
        )
    output: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        probe = run_ffprobe(resolved)
        if not probe.get("passed") or not probe.get("width") or not probe.get("height"):
            continue
        output.append(
            {
                "path": str(resolved),
                "duration_seconds": float(probe.get("container_duration") or 0.0),
                "width": probe.get("width"),
                "height": probe.get("height"),
                "has_audio": probe.get("has_audio"),
                "file_size_bytes": resolved.stat().st_size,
            }
        )
    output.sort(key=lambda item: item["duration_seconds"])
    if explicit_resolved is not None:
        output.sort(key=lambda item: Path(item["path"]) != explicit_resolved)
    return output


def _select_local_sample(samples: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred = [item for item in samples if 180.0 <= item["duration_seconds"] <= 1200.0]
    return (preferred or samples)[0] if (preferred or samples) else None


def _run_local_pipeline(
    report: dict[str, Any],
    *,
    args: argparse.Namespace,
    mode: str,
    python: Path,
    backend_running: bool,
    selected_sample: dict[str, Any] | None,
) -> None:
    top = report["olympus_v2_release_candidate"]
    target = top["end_to_end"]["local_upload_full_pipeline"]
    target["selected_sample"] = selected_sample
    if mode not in {"full", "runtime_only"}:
        target.update(
            status="skipped",
            summary=f"Fresh local render is outside {mode} mode.",
            warnings=["No fresh full pipeline was run."],
        )
        return
    if args.skip_slow:
        target.update(
            status="skipped",
            summary="Fresh local render was explicitly skipped by --skip-slow.",
            warnings=["No fresh full pipeline was run."],
        )
        return
    if not backend_running:
        target.update(
            status="failed",
            passed=False,
            summary="Backend unavailable; local full pipeline could not run.",
            errors=["LOCAL_BACKEND_UNAVAILABLE"],
        )
        return
    if selected_sample is None:
        target.update(
            status="failed",
            passed=False,
            summary="No valid local media sample was available.",
            errors=["LOCAL_VALIDATION_SAMPLE_MISSING"],
        )
        return

    local_dir = args.report_dir / "local_upload"
    command = [
        python,
        "tools/validate_real_video_flow.py",
        "--file",
        selected_sample["path"],
        "--base",
        args.backend_url,
        "--max-videos",
        "1",
        "--require-audio",
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--poll-interval-seconds",
        "2",
        "--report-dir",
        local_dir,
    ]
    command_result = run_command(
        "local_upload_full_pipeline",
        command,
        cwd=ROOT,
        timeout_seconds=args.timeout_seconds + 120.0,
        env=_subprocess_environment(),
        tail_chars=20_000,
    )
    target["evidence"] = [command_result]
    validation_path = local_dir / "validation_report.json"
    if not validation_path.is_file():
        target.update(
            status="failed",
            passed=False,
            fresh=False,
            summary="The runtime validator did not create its canonical report.",
            errors=["RUNTIME_REPORT_MISSING"],
        )
        return
    runtime = json.loads(validation_path.read_text(encoding="utf-8-sig"))
    runtime_top = runtime.get("real_video_validation_report", {})
    videos = runtime.get("videos") if isinstance(runtime.get("videos"), list) else []
    clips = runtime.get("clips") if isinstance(runtime.get("clips"), list) else []
    caption_readability_advisories = [
        {
            "clip_id": clip.get("clip_id"),
            "warning_count": clip.get("validation", {}).get(
                "caption_readability_warning_count", 0
            ),
            "warnings": clip.get("validation", {}).get(
                "caption_readability_warnings", []
            ),
        }
        for clip in clips
        if clip.get("validation", {}).get("caption_readability_passed") is False
        and clip.get("validation", {}).get("caption_readability_blocking") is not True
    ]
    passed = (
        command_result.get("passed") is True
        and runtime_top.get("videos_passed", 0) >= 1
        and runtime_top.get("videos_failed", 0) == 0
        and all(
            video.get("pipeline", {}).get("optimization_passed") is True
            for video in videos
        )
        and bool(clips)
        and all(clip.get("pass_fail") is True for clip in clips)
    )
    project_ids = [str(video.get("video_id")) for video in videos if video.get("video_id")]
    storage_root = args.report_dir / "runtime" / "storage"
    metadata = _project_metadata_evidence(storage_root, project_ids)
    target.update(
        {
            "status": "passed" if passed else "failed",
            "passed": passed,
            "fresh": True,
            "summary": runtime_top.get("summary"),
            "report_path": str(validation_path),
            "project_ids": project_ids,
            "rendered_clip_count": len(clips),
            "valid_mp4_count": sum(
                1 for clip in clips if clip.get("ffprobe_validation", {}).get("passed") is True
            ),
            "pipeline_stage_evidence": [video.get("pipeline") for video in videos],
            "optimization_passed": bool(videos)
            and all(
                video.get("pipeline", {}).get("optimization_passed") is True
                for video in videos
            ),
            "unified_clip_intelligence_present": all(
                clip.get("intelligence", {}).get("unified_clip_intelligence_present") is True
                for clip in clips
            ),
            "safety_metadata_present": metadata["safety_metadata_present"],
            "upload_metadata_present": metadata["upload_metadata_present"],
            "metadata_evidence_paths": metadata["paths"],
            "manual_playback_performed": False,
            "music_audibility_verified": False,
            "real_face_tracking_verified": False,
            "caption_readability_advisories": caption_readability_advisories,
            "warnings": runtime_top.get("warnings", []),
            "errors": runtime_top.get("failures", []),
        }
    )
    final_passed = bool(clips) and all(
        clip.get("ffprobe_validation", {}).get("passed") is True
        and clip.get("validation", {}).get("duration_passed") is True
        and (
            clip.get("validation", {}).get("sync_passed") is True
            if clip.get("validation", {}).get("audio_present")
            else True
        )
        for clip in clips
    )
    top["end_to_end"]["final_mp4_validation"].update(
        {
            "status": "passed" if final_passed else "failed",
            "passed": final_passed,
            "fresh": True,
            "summary": f"Validated {len(clips)} fresh downloaded MP4(s).",
            "evidence": [
                {
                    "clip_id": clip.get("clip_id"),
                    "rendered_path": clip.get("rendered_path"),
                    "ffprobe_validation": clip.get("ffprobe_validation"),
                    "validation": clip.get("validation"),
                }
                for clip in clips
            ],
        }
    )
    top["end_to_end"]["frontend_downloads"].update(
        {
            "status": "passed" if bool(clips) else "failed",
            "passed": bool(clips),
            "fresh": True,
            "summary": f"Downloaded {len(clips)} rendered clip(s) through the API.",
            "evidence": [clip.get("rendered_path") for clip in clips],
        }
    )
    if passed:
        top["systems"]["real_video_runtime"] = {
            "status": "passed",
            "passed": True,
            "evidence_kind": "fresh_local_http_upload_and_render",
            "checks": [command_result],
            "warnings": runtime_top.get("warnings", []),
            "errors": [],
        }


def _project_metadata_evidence(storage_root: Path, project_ids: list[str]) -> dict[str, Any]:
    keys: dict[str, Any] = {
        "safety_metadata_present": False,
        "upload_metadata_present": False,
        "paths": [],
    }
    if not storage_root.is_dir():
        return keys
    for project_id in project_ids:
        for path in storage_root.glob(f"**/{project_id}/**/*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            safety = _contains_key(payload, {"copyright_safety_v2", "copyright_safety"})
            upload = _contains_key(payload, {"upload_metadata_v2", "upload_metadata"})
            if safety or upload:
                keys["paths"].append(str(path))
            keys["safety_metadata_present"] = keys["safety_metadata_present"] or safety
            keys["upload_metadata_present"] = keys["upload_metadata_present"] or upload
    keys["paths"] = sorted(set(keys["paths"]))
    return keys


def _contains_key(value: Any, targets: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            str(key) in targets or _contains_key(item, targets)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_key(item, targets) for item in value)
    return False


def _run_youtube_validation(
    report: dict[str, Any],
    *,
    args: argparse.Namespace,
    mode: str,
    python: Path,
    backend_running: bool,
) -> None:
    target = report["olympus_v2_release_candidate"]["end_to_end"][
        "youtube_link_full_pipeline"
    ]
    if not args.youtube_url:
        target.update(
            status="skipped",
            summary="No rights-confirmed YouTube test URL was provided.",
            real_url_used=False,
            warnings=["REAL_YOUTUBE_LINK_VALIDATION_NOT_RUN"],
        )
        return
    metadata_command = [
        python,
        "tools/validate_link_ingestion.py",
        "--metadata-only",
        "--direct",
        "--url",
        args.youtube_url,
        "--confirm-rights",
        "--report-dir",
        args.report_dir / "youtube_link" / "metadata",
    ]
    evidence = [
        run_command(
            "youtube_metadata_direct",
            metadata_command,
            cwd=ROOT,
            timeout_seconds=min(args.timeout_seconds, 300.0),
            env=_subprocess_environment(),
        )
    ]
    full_allowed = mode in {"full", "runtime_only"} and backend_running and not args.skip_slow
    if full_allowed and evidence[0].get("passed") is True:
        full_command = [
            python,
            "tools/validate_link_ingestion.py",
            "--full-pipeline",
            "--api",
            "--url",
            args.youtube_url,
            "--confirm-rights",
            "--backend-url",
            args.backend_url,
            "--timeout-seconds",
            str(args.timeout_seconds),
            "--report-dir",
            args.report_dir / "youtube_link" / "full_pipeline",
        ]
        evidence.append(
            run_command(
                "youtube_link_full_pipeline",
                full_command,
                cwd=ROOT,
                timeout_seconds=args.timeout_seconds + 120.0,
                env=_subprocess_environment(),
            )
        )
    passed = len(evidence) == 2 and all(item.get("passed") is True for item in evidence)
    target.update(
        {
            "status": "passed" if passed else "warning",
            "passed": passed,
            "fresh": True,
            "summary": (
                "A rights-confirmed real YouTube URL completed metadata and full-pipeline QA."
                if passed
                else "Only partial YouTube link validation completed."
            ),
            "real_url_used": True,
            "rights_confirmed": True,
            "evidence": evidence,
            "warnings": [] if passed else ["REAL_YOUTUBE_LINK_FULL_PIPELINE_INCOMPLETE"],
        }
    )


def _run_long_video_planning(
    report: dict[str, Any],
    *,
    args: argparse.Namespace,
    mode: str,
    python: Path,
    backend_running: bool,
    samples: list[dict[str, Any]],
) -> None:
    top = report["olympus_v2_release_candidate"]
    ten_plus = [item for item in samples if 600.0 <= item["duration_seconds"] < 1800.0]
    thirty_plus = [item for item in samples if item["duration_seconds"] >= 1800.0]
    planning = top["end_to_end"]["planning_only_long_video"]
    full_render = top["end_to_end"]["full_render_long_video"]
    full_render["duration_evidence_seconds"] = (
        max(item["duration_seconds"] for item in thirty_plus) if thirty_plus else 0.0
    )
    if mode not in {"full", "runtime_only"} or args.skip_slow:
        planning.update(
            status="skipped",
            summary="Long-video planning was not run in this mode or was skipped as slow.",
            sample_count=len(ten_plus) + len(thirty_plus),
        )
        return
    candidate = (thirty_plus or ten_plus)[0] if (thirty_plus or ten_plus) else None
    if not backend_running or candidate is None:
        planning.update(
            status="skipped",
            summary="No live backend or 10+ minute source was available for planning-only QA.",
            sample_count=len(ten_plus) + len(thirty_plus),
        )
        return
    command = [
        python,
        "tools/validate_long_video.py",
        "--file",
        candidate["path"],
        "--planning-only",
        "--base",
        args.backend_url,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--report-dir",
        args.report_dir / "long_video_planning",
    ]
    result = run_command(
        "long_video_planning_only",
        command,
        cwd=ROOT,
        timeout_seconds=args.timeout_seconds + 120.0,
        env=_subprocess_environment(),
    )
    planning.update(
        {
            "status": "passed" if result.get("passed") else "failed",
            "passed": result.get("passed"),
            "fresh": True,
            "summary": f"Planning-only validation for {candidate['duration_seconds']:.3f}s source.",
            "duration_evidence_seconds": candidate["duration_seconds"],
            "evidence": [result],
        }
    )


def _set_durable_evidence(
    report: dict[str, Any], grouped: dict[str, list[dict[str, Any]]]
) -> None:
    checks = grouped.get("durable_jobs_v2", [])
    required_ids = {
        "durable_jobs_crash",
        "durable_jobs_resume",
        "durable_jobs_cancel",
        "durable_jobs_retry",
        "durable_jobs_duplicate",
    }
    selected = [item for item in checks if item.get("id") in required_ids]
    passed = len(selected) == len(required_ids) and all(
        item.get("passed") is True for item in selected
    )
    report["olympus_v2_release_candidate"]["end_to_end"]["durable_resume"].update(
        {
            "status": "passed" if passed else "failed",
            "passed": passed,
            "fresh": bool(selected),
            "summary": "Crash/resume/cancel/retry/duplicate simulations all passed."
            if passed
            else "Required durable-job simulations are incomplete or failed.",
            "evidence": selected,
        }
    )
    report["olympus_v2_release_candidate"]["end_to_end"][
        "backend_restart_recovery"
    ].update(
        {
            "status": "not_run",
            "passed": None,
            "fresh": False,
            "real_process_restart": False,
            "summary": "No real backend kill/restart recovery was performed.",
        }
    )


def _set_release_notes(report: dict[str, Any]) -> None:
    top = report["olympus_v2_release_candidate"]
    missing = [path for path in REQUIRED_DOCS if not (ROOT / path).is_file()]
    top["release_notes"].update(
        {
            "completed_features": [
                "Upload and project processing pipeline",
                "Story, virality, planning, editing, rendering, and optimization V2 contracts",
                "Link ingestion safety and validation tooling",
                "Captions, music, motion, multi-speaker, trend, safety, and metadata validators",
                "Creator personalization and local durable-job tooling",
                "Frontend result cards and download surfaces",
            ],
            "known_limitations": [
                "No real 30+ minute full-render evidence in the current sample set",
                "No approved real YouTube URL was supplied for this run",
                "No real backend kill/restart recovery run",
                "No manual playback/listening or objective music-loudness verification",
                "No real face-tracked motion playback validation",
                "Clip-level partial render resume is not proven",
                "Pre-project link download durability is only partially proven",
            ],
            "recommended_user_testing": [
                "Run a rights-confirmed YouTube link metadata check and full pipeline",
                "Run planning and rendering on a real 30+ minute source",
                "Perform controlled backend kill/restart recovery against isolated storage",
                "Watch and listen to fresh face/music/caption-heavy renders",
            ],
            "commands_to_run": [
                str(_python_executable())
                + " tools/validate_olympus_v2_release_candidate.py --fast",
                str(_python_executable())
                + " tools/validate_olympus_v2_release_candidate.py --full --timeout-seconds 7200",
            ],
            "docs_complete": not missing,
            "required_docs": list(REQUIRED_DOCS),
            "missing_docs": missing,
        }
    )


def _merge_artifact_runtime_counts(report: dict[str, Any]) -> None:
    top = report["olympus_v2_release_candidate"]
    final = top["end_to_end"]["final_mp4_validation"]
    evidence = final.get("evidence") if isinstance(final.get("evidence"), list) else []
    fresh_valid = sum(
        1 for item in evidence if item.get("ffprobe_validation", {}).get("passed") is True
    )
    if fresh_valid:
        top["artifacts"]["valid_mp4_count"] = max(
            fresh_valid, int(top["artifacts"].get("valid_mp4_count") or 0)
        )


def main() -> int:
    args = _parse_args()
    args.report_dir = args.report_dir.resolve()
    mode = _mode(args)
    python = _python_executable()
    run_started_epoch = time.time()
    report = build_release_candidate_report(ROOT, mode=mode)
    top = report["olympus_v2_release_candidate"]
    backend_process: subprocess.Popen[str] | None = None
    backend_log: Any = None
    try:
        top["environment"] = collect_environment(ROOT, python_executable=python)
        top["validator_audit"] = audit_validators(ROOT)
        _run_static_suites(report, args=args, mode=mode, python=python)
        grouped = _run_validators(report, args=args, mode=mode, python=python)
        _set_source_contract_systems(report)
        _set_durable_evidence(report, grouped)

        backend_running = _backend_live(args.backend_url)
        startup: dict[str, Any] = {
            "started": False,
            "isolated": False,
            "error": None,
            "command": None,
        }
        if not backend_running and mode in {"full", "runtime_only"}:
            backend_process, backend_log, startup = _start_isolated_backend(
                base_url=args.backend_url,
                python=python,
                report_dir=args.report_dir,
            )
            backend_running = _backend_live(args.backend_url)
        top["environment"]["backend_running"] = backend_running
        top["environment"]["backend_startup"] = startup
        if backend_running:
            top["systems"]["api_contracts"] = _probe_backend_contracts(args.backend_url)

        samples = _discover_samples(args.sample)
        selected = _select_local_sample(samples)
        top["artifacts"]["validation_samples"] = samples
        top["artifacts"]["selected_local_sample"] = selected
        top["artifacts"]["real_30_plus_sample_available"] = any(
            item["duration_seconds"] >= 1800.0 for item in samples
        )

        _run_local_pipeline(
            report,
            args=args,
            mode=mode,
            python=python,
            backend_running=backend_running,
            selected_sample=selected,
        )
        _run_youtube_validation(
            report,
            args=args,
            mode=mode,
            python=python,
            backend_running=backend_running,
        )
        _run_long_video_planning(
            report,
            args=args,
            mode=mode,
            python=python,
            backend_running=backend_running,
            samples=samples,
        )
        _set_release_notes(report)
        top["artifacts"].update(
            inspect_artifacts(ROOT, run_started_epoch=run_started_epoch)
        )
        _merge_artifact_runtime_counts(report)
    except Exception as exc:
        add_blocker(
            report,
            "RC_ORCHESTRATOR_CRASHED",
            system="release_candidate_qa",
            title="The release-candidate orchestrator crashed.",
            evidence=f"{type(exc).__name__}: {exc}",
            recommended_fix="Fix the reported exception and rerun the same QA mode.",
        )
        top["environment"].setdefault("errors", []).append(f"{type(exc).__name__}: {exc}")
        _set_release_notes(report)
    finally:
        _stop_owned_backend(backend_process, backend_log)

    evaluate_release_candidate(report)
    paths = write_release_candidate_report(report, args.report_dir)
    decision = top["decision"]
    print(
        json.dumps(
            {
                "decision": decision,
                "reports": paths,
                "blockers": top["blockers"],
                "warnings": top["warnings"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if decision["status"] == DECISION_BLOCKED:
        return 2
    if decision["status"] == DECISION_NOT_READY:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

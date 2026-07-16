"""Release-candidate evidence, gate evaluation, and report helpers for Olympus V2."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from olympus.validation.real_video import run_ffprobe

DECISION_PASS = "PASS_RELEASE_CANDIDATE"
DECISION_WARN = "PASS_WITH_WARNINGS"
DECISION_NOT_READY = "NOT_RELEASE_READY"
DECISION_BLOCKED = "BLOCKED"

TEST_SUITE_KEYS = (
    "ruff",
    "mypy",
    "pytest",
    "frontend_typecheck",
    "frontend_lint",
    "frontend_tests",
    "frontend_build",
)

SYSTEM_KEYS = (
    "link_ingestion",
    "real_video_runtime",
    "story_v2",
    "virality_v2",
    "planning_v2",
    "editing_rendering_v2",
    "captions_v2",
    "music_v2",
    "curated_music_library_v2",
    "multi_speaker_layout_v2",
    "motion_effects_v2",
    "trend_research_v2",
    "live_trend_provider_v2",
    "copyright_safety_v2",
    "upload_metadata_v2",
    "creator_personalization_v2",
    "durable_jobs_v2",
    "long_video_validation_v2",
    "frontend_results_ui",
    "api_contracts",
)

END_TO_END_KEYS = (
    "local_upload_full_pipeline",
    "youtube_link_full_pipeline",
    "planning_only_long_video",
    "full_render_long_video",
    "durable_resume",
    "backend_restart_recovery",
    "frontend_downloads",
    "final_mp4_validation",
)

CRITICAL_SYSTEMS = {
    "link_ingestion": "Link ingestion basic validation failed.",
    "copyright_safety_v2": "Copyright/safety validation failed or overclaimed safety.",
    "upload_metadata_v2": "Upload metadata validation failed.",
    "durable_jobs_v2": "Durable-job validation failed.",
    "frontend_results_ui": "Frontend results UI validation failed.",
    "api_contracts": "API contract validation failed.",
}


@dataclass(frozen=True)
class ValidatorAuditSpec:
    """Static inventory entry for one existing subsystem validator."""

    name: str
    system: str
    proof: str
    does_not_prove: str
    report_globs: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()


VALIDATOR_AUDIT_SPECS = (
    ValidatorAuditSpec(
        "validate_runtime_flow.py",
        "real_video_runtime",
        "A live local HTTP upload can produce downloadable, ffprobe-readable vertical MP4s.",
        "It does not prove every V2 metadata contract or subjective playback quality.",
        ("validation_report.json",),
        ("docs/RUNTIME_VALIDATION_V2.md",),
        ("tests/unit/test_real_video_validation.py",),
    ),
    ValidatorAuditSpec(
        "validate_real_video_flow.py",
        "real_video_runtime",
        "Upload-to-render stage completion, downloads, MP4 shape, duration, sync, and metadata.",
        "It does not prove manual visual quality, audibility, or broad codec/device coverage.",
        ("validation_report.json",),
        ("docs/RUNTIME_VALIDATION_V2.md",),
        ("tests/unit/test_real_video_validation.py",),
    ),
    ValidatorAuditSpec(
        "validate_link_ingestion.py",
        "link_ingestion",
        "URL policy, local dependencies, metadata/download/API modes when explicitly invoked.",
        "Self-check does not prove a real public YouTube download or full pipeline.",
        ("**/link_ingestion_validation_report.json",),
        ("docs/LINK_INGESTION_V2.md", "docs/REAL_YOUTUBE_LINK_VALIDATION_FIX_V2.md"),
        ("tests/unit/test_link_validation.py",),
    ),
    ValidatorAuditSpec(
        "validate_trend_research.py",
        "trend_research_v2",
        "Offline/cache/live provider contracts and source-attributed trend snapshots.",
        "Offline mode does not prove current internet research or trend accuracy.",
        ("**/*trend*research*.json",),
        ("docs/INTERNET_TREND_RESEARCH_V2.md",),
        ("tests/unit/test_trend_research.py",),
    ),
    ValidatorAuditSpec(
        "validate_live_trend_provider.py",
        "live_trend_provider_v2",
        "Provider configuration, offline fallback, cache, and optional live source behavior.",
        "Self-check/offline modes do not prove a configured live search provider.",
        ("**/live_trend_provider_validation_v2*.json",),
        ("docs/LIVE_RUNTIME_INTERNET_TREND_PROVIDER_V2.md",),
        ("tests/unit/test_live_trend_provider.py",),
    ),
    ValidatorAuditSpec(
        "validate_music_intelligence.py",
        "music_v2",
        "Music policy, asset eligibility, mix-plan metadata, and rendered manifest checks.",
        "Simulation does not prove final perceived loudness or speech clarity.",
        ("**/*music*validation*.json",),
        ("docs/MUSIC_INTELLIGENCE_V2.md", "docs/CURATED_MUSIC_LIBRARY_V2.md"),
        ("tests/unit/test_music_intelligence.py", "tests/unit/test_music_library.py"),
    ),
    ValidatorAuditSpec(
        "validate_caption_typography.py",
        "captions_v2",
        "Caption plan, ASS safety/readability metadata, and optional rendered-file evidence.",
        "Simulation does not prove captions are visually readable on real footage/devices.",
        ("**/*caption*validation*.json",),
        ("docs/CAPTIONS_TYPOGRAPHY_V2.md",),
        ("tests/unit/test_caption_typography.py",),
    ),
    ValidatorAuditSpec(
        "validate_motion_effects.py",
        "motion_effects_v2",
        "Motion planning, synthetic render, and optional manifest/rendered-file truth.",
        "Synthetic mode does not prove real face-tracked motion is visually correct.",
        ("**/*motion*validation*.json",),
        ("docs/MOTION_GRAPHICS_EFFECTS_V2.md",),
        ("tests/unit/test_motion_effects.py",),
    ),
    ValidatorAuditSpec(
        "validate_multi_speaker_layout.py",
        "multi_speaker_layout_v2",
        "Layout decisions and optional render-manifest truth for speaker regions/switches.",
        "Simulation does not prove real speaker association or subjective layout quality.",
        ("**/*multi*speaker*.json",),
        ("docs/MULTI_SPEAKER_LAYOUT_V2.md",),
        ("tests/unit/test_multi_speaker_layout.py",),
    ),
    ValidatorAuditSpec(
        "validate_long_video.py",
        "long_video_validation_v2",
        "Discovery, metadata, planning coverage, and optional full render validation.",
        "Discovery or a sub-30-minute source does not prove 30+ minute behavior.",
        ("**/long_video_validation_report.json",),
        ("docs/LONG_VIDEO_VALIDATION_V2.md",),
        ("tests/unit/test_long_video_validation.py",),
    ),
    ValidatorAuditSpec(
        "validate_copyright_safety.py",
        "copyright_safety_v2",
        "Conservative provenance/license/rights metadata and non-overclaiming policy.",
        "It cannot guarantee copyright safety, legal compliance, or Content ID outcomes.",
        ("**/*copyright*safety*.json",),
        ("docs/COPYRIGHT_SAFETY_CHECKER_V2.md",),
        ("tests/unit/test_copyright_safety.py",),
    ),
    ValidatorAuditSpec(
        "validate_upload_metadata.py",
        "upload_metadata_v2",
        "JSON-safe title, description, hashtag, safety, and platform validation contracts.",
        "Simulation does not prove platform performance or publication success.",
        ("**/upload_metadata/**/*.json",),
        ("docs/TITLE_DESCRIPTION_HASHTAG_V2.md",),
        ("tests/unit/test_upload_metadata.py",),
    ),
    ValidatorAuditSpec(
        "validate_creator_personalization.py",
        "creator_personalization_v2",
        "Profile storage, selection, feedback, export/reset, and guidance contracts.",
        "Simulation does not prove long-term recommendation quality for a real creator.",
        ("**/*personalization*.json",),
        ("docs/CREATOR_PERSONALIZATION_V2.md",),
        ("tests/unit/test_creator_personalization.py",),
    ),
    ValidatorAuditSpec(
        "validate_durable_jobs.py",
        "durable_jobs_v2",
        "Durable storage, checkpoint, crash/resume/cancel/retry/duplicate simulations.",
        "Simulation does not prove recovery across a real backend process kill/restart.",
        ("**/durable_jobs/*.json",),
        ("docs/DURABLE_JOB_QUEUE_RESUME_V2.md",),
        ("tests/unit/test_durable_jobs.py",),
    ),
)


def utc_now_iso() -> str:
    """Return a stable UTC timestamp."""

    return datetime.now(UTC).isoformat()


def command_result_skipped(
    check_id: str,
    reason: str,
    *,
    code: str = "CHECK_SKIPPED",
    command: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a JSON-safe skipped-command result."""

    return {
        "id": check_id,
        "command": _display_command(command),
        "cwd": None,
        "started_at": None,
        "completed_at": None,
        "duration_seconds": 0.0,
        "exit_code": None,
        "passed": None,
        "status": "skipped",
        "timed_out": False,
        "stdout_tail": "",
        "stderr_tail": "",
        "warnings": [reason],
        "errors": [],
        "code": code,
    }


def run_command(
    check_id: str,
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    timeout_seconds: float,
    env: dict[str, str] | None = None,
    tail_chars: int = 8_000,
) -> dict[str, Any]:
    """Run one command without a shell and preserve bounded diagnostic output."""

    normalized = [os.fspath(item) for item in command]
    started_at = utc_now_iso()
    started = time.monotonic()
    try:
        completed = subprocess.run(
            normalized,
            cwd=cwd,
            env=env,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
        duration = round(time.monotonic() - started, 3)
        passed = completed.returncode == 0
        return {
            "id": check_id,
            "command": _display_command(normalized),
            "cwd": str(cwd),
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "duration_seconds": duration,
            "exit_code": completed.returncode,
            "passed": passed,
            "status": "passed" if passed else "failed",
            "timed_out": False,
            "stdout_tail": _tail(completed.stdout, tail_chars),
            "stderr_tail": _tail(completed.stderr, tail_chars),
            "warnings": [],
            "errors": [] if passed else [f"Command exited with code {completed.returncode}."],
            "code": None if passed else "COMMAND_FAILED",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "id": check_id,
            "command": _display_command(normalized),
            "cwd": str(cwd),
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "duration_seconds": round(time.monotonic() - started, 3),
            "exit_code": None,
            "passed": False,
            "status": "failed",
            "timed_out": True,
            "stdout_tail": _tail(_as_text(exc.stdout), tail_chars),
            "stderr_tail": _tail(_as_text(exc.stderr), tail_chars),
            "warnings": [],
            "errors": [f"Command timed out after {timeout_seconds:g} seconds."],
            "code": "COMMAND_TIMEOUT",
        }
    except OSError as exc:
        return {
            "id": check_id,
            "command": _display_command(normalized),
            "cwd": str(cwd),
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "duration_seconds": round(time.monotonic() - started, 3),
            "exit_code": None,
            "passed": False,
            "status": "failed",
            "timed_out": False,
            "stdout_tail": "",
            "stderr_tail": "",
            "warnings": [],
            "errors": [str(exc)],
            "code": "COMMAND_START_FAILED",
        }


def build_release_candidate_report(workspace: Path, *, mode: str) -> dict[str, Any]:
    """Create the complete JSON-safe release-candidate report skeleton."""

    workspace = workspace.resolve()
    return {
        "olympus_v2_release_candidate": {
            "schema_version": "olympus_v2_release_candidate_v1",
            "created_at": utc_now_iso(),
            "workspace": str(workspace),
            "branch": _git_value(workspace, "branch", "--show-current"),
            "commit_sha": _git_value(workspace, "rev-parse", "HEAD"),
            "mode": mode,
            "dirty_worktree_summary": git_worktree_summary(workspace),
            "decision": {
                "status": DECISION_NOT_READY,
                "release_candidate_ready": False,
                "confidence": "low",
                "blocker_count": 0,
                "warning_count": 0,
                "summary": "Release gates have not been evaluated.",
                "next_action": "Run release-candidate validation.",
            },
            "environment": {
                "python_ok": None,
                "ffmpeg_ok": None,
                "ffprobe_ok": None,
                "node_ok": None,
                "npm_ok": None,
                "backend_import_ok": None,
                "backend_running": None,
                "backend_settings_ok": None,
                "frontend_dependencies_ok": None,
                "storage_writable": None,
                "storage_locations": {},
                "yt_dlp_installed": None,
                "versions": {},
                "checks": {},
                "warnings": [],
                "errors": [],
            },
            "test_suites": {
                key: command_result_skipped(key, "Test suite has not run.")
                for key in TEST_SUITE_KEYS
            },
            "systems": {key: _empty_system_result() for key in SYSTEM_KEYS},
            "end_to_end": {key: _empty_evidence_result() for key in END_TO_END_KEYS},
            "artifacts": {
                "rendered_clip_count": 0,
                "valid_mp4_count": 0,
                "invalid_mp4_count": 0,
                "inspected_mp4_count": 0,
                "latest_manifest_paths": [],
                "latest_report_paths": [],
                "fresh_manifest_paths": [],
                "stale_artifact_warnings": [],
                "mp4_validation_scope": "No rendered MP4s inspected.",
                "mp4_evidence": [],
            },
            "validator_audit": [],
            "release_gates": {},
            "blockers": [],
            "warnings": [],
            "release_notes": {
                "completed_features": [],
                "known_limitations": [],
                "not_claimed": [
                    "Guaranteed virality",
                    "Copyright or legal safety guarantee",
                    "Content ID outcome prediction",
                    "Cloud-scale durability or Redis/Celery operation",
                    "Manual visual or listening validation unless explicitly recorded",
                ],
                "recommended_user_testing": [],
                "commands_to_run": [],
                "docs_complete": False,
                "required_docs": [],
                "missing_docs": [],
            },
        }
    }


def git_worktree_summary(workspace: Path) -> dict[str, Any]:
    """Return staged/unstaged/untracked counts without modifying the worktree."""

    completed = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=workspace,
        capture_output=True,
        check=False,
        text=True,
        shell=False,
    )
    if completed.returncode != 0:
        return {
            "staged_file_count": None,
            "unstaged_tracked_file_count": None,
            "untracked_file_count": None,
            "protected_dirty_v2_baseline": None,
            "error": completed.stderr.strip() or "git status failed",
        }
    staged = 0
    unstaged = 0
    untracked = 0
    for line in completed.stdout.splitlines():
        if line.startswith("??"):
            untracked += 1
            continue
        if len(line) >= 2 and line[0] != " ":
            staged += 1
        if len(line) >= 2 and line[1] != " ":
            unstaged += 1
    return {
        "staged_file_count": staged,
        "unstaged_tracked_file_count": unstaged,
        "untracked_file_count": untracked,
        "protected_dirty_v2_baseline": bool(staged or unstaged or untracked),
        "error": None,
    }


def collect_environment(
    workspace: Path,
    *,
    python_executable: Path,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Collect environment readiness while preserving exact command evidence."""

    checks: dict[str, dict[str, Any]] = {}
    checks["python"] = run_command(
        "environment_python",
        [python_executable, "--version"],
        cwd=workspace,
        timeout_seconds=timeout_seconds,
    )
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    node = shutil.which("node")
    npm = shutil.which("npm")
    checks["ffmpeg"] = (
        run_command(
            "environment_ffmpeg",
            [ffmpeg, "-version"],
            cwd=workspace,
            timeout_seconds=timeout_seconds,
        )
        if ffmpeg
        else _missing_executable("environment_ffmpeg", "ffmpeg")
    )
    checks["ffprobe"] = (
        run_command(
            "environment_ffprobe",
            [ffprobe, "-version"],
            cwd=workspace,
            timeout_seconds=timeout_seconds,
        )
        if ffprobe
        else _missing_executable("environment_ffprobe", "ffprobe")
    )
    checks["node"] = (
        run_command(
            "environment_node",
            [node, "--version"],
            cwd=workspace,
            timeout_seconds=timeout_seconds,
        )
        if node
        else _missing_executable("environment_node", "node")
    )
    checks["npm"] = (
        run_command(
            "environment_npm",
            [npm, "--version"],
            cwd=workspace,
            timeout_seconds=timeout_seconds,
        )
        if npm
        else _missing_executable("environment_npm", "npm")
    )
    checks["backend_import"] = run_command(
        "environment_backend_import",
        [
            python_executable,
            "-c",
            "from olympus.api.app import app; print(app.title)",
        ],
        cwd=workspace,
        timeout_seconds=timeout_seconds,
    )
    checks["backend_settings"] = run_command(
        "environment_backend_settings",
        [
            python_executable,
            "-c",
            (
                "from olympus.platform.config import get_settings; "
                "s=get_settings(); print(s.environment.value, s.storage.backend.value)"
            ),
        ],
        cwd=workspace,
        timeout_seconds=timeout_seconds,
    )
    checks["yt_dlp"] = run_command(
        "environment_yt_dlp",
        [python_executable, "-m", "yt_dlp", "--version"],
        cwd=workspace,
        timeout_seconds=timeout_seconds,
    )

    writable: dict[str, dict[str, Any]] = {}
    for name, path in (
        ("workspace", workspace),
        ("storage_data", workspace / "storage_data"),
        ("validation_reports", workspace / "work" / "validation_reports"),
        ("durable_jobs", workspace / "work" / "jobs"),
    ):
        writable[name] = _writable_check(path)
    storage_writable = all(item["passed"] for item in writable.values())
    frontend_dependencies = (workspace / "frontend" / "node_modules").is_dir()

    warnings: list[str] = []
    errors: list[str] = []
    if not checks["yt_dlp"]["passed"]:
        warnings.append("yt-dlp is unavailable; real video-link validation cannot run.")
    if not frontend_dependencies:
        errors.append("frontend/node_modules is missing.")
    if not storage_writable:
        errors.append("One or more required local storage locations are not writable.")
    for key in ("python", "ffmpeg", "ffprobe", "node", "npm", "backend_import"):
        if not checks[key]["passed"]:
            errors.extend(str(item) for item in checks[key].get("errors", []))

    return {
        "python_ok": checks["python"]["passed"],
        "ffmpeg_ok": checks["ffmpeg"]["passed"],
        "ffprobe_ok": checks["ffprobe"]["passed"],
        "node_ok": checks["node"]["passed"],
        "npm_ok": checks["npm"]["passed"],
        "backend_import_ok": checks["backend_import"]["passed"],
        "backend_running": None,
        "backend_settings_ok": checks["backend_settings"]["passed"],
        "frontend_dependencies_ok": frontend_dependencies,
        "storage_writable": storage_writable,
        "storage_locations": writable,
        "yt_dlp_installed": checks["yt_dlp"]["passed"],
        "versions": {
            key: _first_output_line(value)
            for key, value in checks.items()
            if key in {"python", "ffmpeg", "ffprobe", "node", "npm", "yt_dlp"}
        },
        "checks": checks,
        "warnings": warnings,
        "errors": _unique(errors),
    }


def audit_validators(workspace: Path) -> list[dict[str, Any]]:
    """Inventory validators, docs, tests, and report freshness."""

    report_root = workspace / "work" / "validation_reports"
    output: list[dict[str, Any]] = []
    for spec in VALIDATOR_AUDIT_SPECS:
        tool = workspace / "tools" / spec.name
        reports: list[Path] = []
        for pattern in spec.report_globs:
            reports.extend(path for path in report_root.glob(pattern) if path.is_file())
        reports = sorted(set(reports), key=lambda item: item.stat().st_mtime, reverse=True)
        latest = reports[0] if reports else None
        stale = bool(latest and tool.exists() and latest.stat().st_mtime < tool.stat().st_mtime)
        output.append(
            {
                "validator": spec.name,
                "system": spec.system,
                "exists": tool.is_file(),
                "proof": spec.proof,
                "does_not_prove": spec.does_not_prove,
                "latest_report": str(latest) if latest else None,
                "latest_report_stale": stale,
                "docs": [
                    {"path": path, "exists": (workspace / path).is_file()}
                    for path in spec.docs
                ],
                "tests": [
                    {"path": path, "exists": (workspace / path).is_file()} for path in spec.tests
                ],
            }
        )
    return output


def inspect_artifacts(
    workspace: Path,
    *,
    run_started_epoch: float,
    max_mp4_probes: int = 20,
) -> dict[str, Any]:
    """Inspect bounded local render/report evidence without treating sources as outputs."""

    manifests = _newest_paths(
        [
            *(workspace / "storage_data").glob("**/generate_render_manifest.json"),
            *(workspace / "storage_data").glob("render/**/index.json"),
            *(workspace / "work").glob("**/generate_render_manifest.json"),
        ],
        limit=25,
    )
    reports = _newest_paths(
        (workspace / "work" / "validation_reports").glob("**/*.json"),
        limit=30,
    )
    candidates = _newest_paths(
        (
            path
            for root in (workspace / "storage_data", workspace / "work" / "validation_reports")
            if root.exists()
            for path in root.glob("**/*.mp4")
            if _looks_like_render(path)
        ),
        limit=10_000,
    )
    inspected = candidates[:max_mp4_probes]
    evidence: list[dict[str, Any]] = []
    valid = 0
    invalid = 0
    for path in inspected:
        probe = run_ffprobe(path)
        passed = bool(probe.get("passed")) and bool(probe.get("width")) and bool(
            probe.get("height")
        )
        valid += int(passed)
        invalid += int(not passed)
        evidence.append(
            {
                "path": str(path),
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "fresh_for_this_run": path.stat().st_mtime >= run_started_epoch,
                "passed": passed,
                "width": probe.get("width"),
                "height": probe.get("height"),
                "video_codec": probe.get("video_codec"),
                "audio_codec": probe.get("audio_codec"),
                "container_duration": probe.get("container_duration"),
                "audio_video_delta": (
                    round(float(probe["audio_duration"]) - float(probe["video_duration"]), 3)
                    if probe.get("audio_duration") is not None
                    and probe.get("video_duration") is not None
                    else None
                ),
                "errors": probe.get("errors", []),
            }
        )
    stale_warnings = [
        f"Existing report predates its validator: {item['latest_report']}"
        for item in audit_validators(workspace)
        if item.get("latest_report_stale")
    ]
    if len(candidates) > len(inspected):
        stale_warnings.append(
            f"Only the {len(inspected)} newest of {len(candidates)} rendered MP4 "
            "candidates were probed."
        )
    return {
        "rendered_clip_count": len(candidates),
        "valid_mp4_count": valid,
        "invalid_mp4_count": invalid,
        "inspected_mp4_count": len(inspected),
        "latest_manifest_paths": [str(path) for path in manifests],
        "latest_report_paths": [str(path) for path in reports],
        "fresh_manifest_paths": [
            str(path) for path in manifests if path.stat().st_mtime >= run_started_epoch
        ],
        "stale_artifact_warnings": stale_warnings,
        "mp4_validation_scope": (
            f"Probed {len(inspected)} newest rendered-output candidates; "
            f"{len(candidates)} candidates were discovered."
        ),
        "mp4_evidence": evidence,
    }


def set_system_result(
    report: dict[str, Any],
    system: str,
    checks: Sequence[dict[str, Any]],
    *,
    evidence_kind: str,
    warnings: Sequence[str] = (),
) -> None:
    """Set one normalized system result from one or more command checks."""

    top = _top(report)
    actual = [item for item in checks if item.get("passed") is not None]
    passed = bool(actual) and all(item.get("passed") is True for item in actual)
    failed = any(item.get("passed") is False for item in actual)
    combined_warnings = [
        *warnings,
        *(
            str(warning)
            for item in checks
            for warning in item.get("warnings", [])
            if warning
        ),
    ]
    status = (
        "failed"
        if failed
        else "warning"
        if combined_warnings
        else "passed"
        if passed
        else "not_run"
    )
    top["systems"][system] = {
        "status": status,
        "passed": False if failed else True if passed else None,
        "evidence_kind": evidence_kind,
        "checks": list(checks),
        "warnings": _unique(combined_warnings),
        "errors": _unique(
            str(error)
            for item in checks
            for error in item.get("errors", [])
            if error
        ),
    }


def add_blocker(
    report: dict[str, Any],
    blocker_id: str,
    *,
    system: str,
    title: str,
    evidence: str,
    recommended_fix: str,
    command_to_reproduce: str = "",
    severity: str = "blocker",
) -> None:
    """Append one blocker unless that stable identifier already exists."""

    blockers = _top(report)["blockers"]
    if any(item.get("id") == blocker_id for item in blockers):
        return
    blockers.append(
        {
            "id": blocker_id,
            "severity": severity,
            "system": system,
            "title": title,
            "evidence": evidence,
            "recommended_fix": recommended_fix,
            "command_to_reproduce": command_to_reproduce,
        }
    )


def add_warning(
    report: dict[str, Any],
    warning_id: str,
    *,
    system: str,
    title: str,
    evidence: str,
    recommended_followup: str,
) -> None:
    """Append one warning unless that stable identifier already exists."""

    warnings = _top(report)["warnings"]
    if any(item.get("id") == warning_id for item in warnings):
        return
    warnings.append(
        {
            "id": warning_id,
            "system": system,
            "title": title,
            "evidence": evidence,
            "recommended_followup": recommended_followup,
        }
    )


def evaluate_release_candidate(report: dict[str, Any]) -> dict[str, Any]:
    """Apply release gates and return the updated report."""

    top = _top(report)
    environment = top["environment"]
    mode = str(top.get("mode") or "unknown")
    fatal_environment = False

    if environment.get("python_ok") is not True:
        fatal_environment = True
        add_blocker(
            report,
            "PYTHON_ENVIRONMENT_UNAVAILABLE",
            system="environment",
            title="Python validation environment is unavailable.",
            evidence="The configured Python executable did not run successfully.",
            recommended_fix="Repair the local .venv before rerunning QA.",
        )
    for key, title in (
        ("ffmpeg_ok", "FFmpeg is unavailable."),
        ("ffprobe_ok", "FFprobe is unavailable."),
        ("node_ok", "Node.js is unavailable."),
        ("npm_ok", "npm is unavailable."),
        ("backend_import_ok", "The Olympus backend cannot import."),
        ("frontend_dependencies_ok", "Frontend dependencies are unavailable."),
        ("storage_writable", "Required local storage is not writable."),
    ):
        if environment.get(key) is not True:
            add_blocker(
                report,
                key.upper(),
                system="environment",
                title=title,
                evidence=f"environment.{key}={environment.get(key)!r}",
                recommended_fix="Resolve the environment check and rerun the exact failed command.",
            )

    backend_running = environment.get("backend_running")
    if backend_running is not True:
        if mode in {"full", "runtime_only"}:
            add_blocker(
                report,
                "LOCAL_BACKEND_UNAVAILABLE",
                system="backend",
                title="The local backend was unavailable for runtime QA.",
                evidence=f"environment.backend_running={backend_running!r}",
                recommended_fix=(
                    "Start the backend without reload or allow the isolated QA backend to start."
                ),
            )
        else:
            add_warning(
                report,
                "LOCAL_BACKEND_NOT_CHECKED",
                system="backend",
                title="A live backend was not exercised in this QA mode.",
                evidence=f"mode={mode}; backend_running={backend_running!r}",
                recommended_followup="Run --full or --runtime-only with a local backend.",
            )

    missing_suites: list[str] = []
    for name in TEST_SUITE_KEYS:
        result = top["test_suites"].get(name, {})
        if result.get("passed") is False:
            add_blocker(
                report,
                f"TEST_SUITE_{name.upper()}_FAILED",
                system="test_suites",
                title=f"Required test suite '{name}' failed.",
                evidence=result.get("stderr_tail") or result.get("stdout_tail") or str(result),
                recommended_fix=f"Run and fix the captured {name} command.",
                command_to_reproduce=str(result.get("command") or ""),
            )
        elif result.get("passed") is not True:
            missing_suites.append(name)
            add_warning(
                report,
                f"TEST_SUITE_{name.upper()}_NOT_RUN",
                system="test_suites",
                title=f"Required test suite '{name}' was not run.",
                evidence=str(result.get("warnings") or result.get("status")),
                recommended_followup=f"Run {name} before release-candidate approval.",
            )
    if missing_suites:
        add_blocker(
            report,
            "REQUIRED_TEST_EVIDENCE_INCOMPLETE",
            system="test_suites",
            title="Required static/frontend test evidence is incomplete.",
            evidence=", ".join(missing_suites),
            recommended_fix="Run the full backend and frontend test suite.",
        )

    for system, title in CRITICAL_SYSTEMS.items():
        status = top["systems"].get(system, {})
        if status.get("passed") is False:
            add_blocker(
                report,
                f"SYSTEM_{system.upper()}_FAILED",
                system=system,
                title=title,
                evidence=str(status.get("errors") or status.get("checks") or status),
                recommended_fix=f"Fix and rerun the {system} validator.",
            )
        elif status.get("passed") is not True:
            add_blocker(
                report,
                f"SYSTEM_{system.upper()}_NOT_VERIFIED",
                system=system,
                title=f"Required system '{system}' was not verified.",
                evidence=str(status.get("status") or "not_run"),
                recommended_fix=f"Run the {system} release-candidate check.",
            )

    multi_speaker_checks = top["systems"].get("multi_speaker_layout_v2", {}).get(
        "checks", []
    )
    if any(check.get("code") == "VALIDATOR_MODE_MISSING" for check in multi_speaker_checks):
        add_warning(
            report,
            "VALIDATOR_MODE_MISSING_MULTI_SPEAKER_SYNTHETIC",
            system="multi_speaker_layout_v2",
            title="The requested multi-speaker --synthetic validator mode is unavailable.",
            evidence="The equivalent --simulate validator ran; --synthetic was recorded missing.",
            recommended_followup="Add --synthetic as an alias or update the canonical QA command.",
        )

    local_pipeline = top["end_to_end"]["local_upload_full_pipeline"]
    caption_advisories = local_pipeline.get("caption_readability_advisories", [])
    if caption_advisories:
        add_warning(
            report,
            "CAPTION_READABILITY_ADVISORIES_REMAIN",
            system="captions_v2",
            title="Fresh renders contain non-blocking caption readability advisories.",
            evidence=str(caption_advisories),
            recommended_followup=(
                "Tune short final caption events and reading speed, then visually inspect captions."
            ),
        )
    fresh_render = bool(local_pipeline.get("fresh")) and local_pipeline.get("passed") is True
    if not fresh_render:
        add_blocker(
            report,
            "FRESH_FULL_PIPELINE_RENDER_MISSING",
            system="real_video_runtime",
            title="No fresh passing local upload-to-render pipeline evidence exists.",
            evidence=str(local_pipeline),
            recommended_fix="Run --full with a valid local source and validate the downloaded MP4.",
        )

    final_mp4 = top["end_to_end"]["final_mp4_validation"]
    if final_mp4.get("passed") is not True or top["artifacts"].get("valid_mp4_count", 0) < 1:
        add_blocker(
            report,
            "FINAL_MP4_VALIDATION_MISSING",
            system="editing_rendering_v2",
            title="No fresh final MP4 has complete passing validation evidence.",
            evidence=str(final_mp4),
            recommended_fix=(
                "Download a fresh render and pass ffprobe, duration, sync, and metadata checks."
            ),
        )

    if local_pipeline.get("safety_metadata_present") is not True:
        add_blocker(
            report,
            "RENDERED_SAFETY_METADATA_MISSING",
            system="copyright_safety_v2",
            title="Fresh rendered output lacks verified safety metadata evidence.",
            evidence=str(local_pipeline.get("safety_metadata_present")),
            recommended_fix=(
                "Persist copyright/safety output into the final render/package metadata."
            ),
        )
    if local_pipeline.get("upload_metadata_present") is not True:
        add_blocker(
            report,
            "RENDERED_UPLOAD_METADATA_MISSING",
            system="upload_metadata_v2",
            title="Fresh pipeline output lacks upload metadata evidence.",
            evidence=str(local_pipeline.get("upload_metadata_present")),
            recommended_fix="Run and preserve upload metadata generation in the final package.",
        )

    if top["end_to_end"]["durable_resume"].get("passed") is not True:
        add_blocker(
            report,
            "DURABLE_SIMULATIONS_INCOMPLETE",
            system="durable_jobs_v2",
            title="Required durable-job simulations did not all pass.",
            evidence=str(top["end_to_end"]["durable_resume"]),
            recommended_fix="Rerun crash, resume, cancel, retry, and duplicate simulations.",
        )

    long_render = top["end_to_end"]["full_render_long_video"]
    duration_evidence = _as_float(long_render.get("duration_evidence_seconds"))
    validated_30_plus = long_render.get("passed") is True and duration_evidence >= 1800.0
    top["release_gates"]["real_30_plus_minute_validation"] = validated_30_plus
    if not validated_30_plus:
        add_warning(
            report,
            "REAL_30_PLUS_MINUTE_VALIDATION_NOT_RUN",
            system="long_video_validation_v2",
            title="No real 30+ minute full-render validation is proven.",
            evidence=(
                f"duration_evidence_seconds={duration_evidence}; "
                f"passed={long_render.get('passed')!r}"
            ),
            recommended_followup=(
                "Run planning and full render on an actual source of at least 1800 seconds."
            ),
        )

    youtube = top["end_to_end"]["youtube_link_full_pipeline"]
    if youtube.get("passed") is not True or youtube.get("real_url_used") is not True:
        add_warning(
            report,
            "REAL_YOUTUBE_LINK_VALIDATION_NOT_RUN",
            system="link_ingestion",
            title="No approved real YouTube link completed the full pipeline.",
            evidence=str(youtube),
            recommended_followup=(
                "Use a rights-confirmed public URL, metadata-only first, then full pipeline."
            ),
        )

    restart = top["end_to_end"]["backend_restart_recovery"]
    if restart.get("passed") is not True or restart.get("real_process_restart") is not True:
        add_warning(
            report,
            "REAL_BACKEND_RESTART_RECOVERY_NOT_RUN",
            system="durable_jobs_v2",
            title="Durable recovery was not proven across a real backend process restart.",
            evidence=str(restart),
            recommended_followup=(
                "Run a controlled kill/restart/resume test on an isolated job store."
            ),
        )

    _add_known_evidence_warnings(report)

    missing_docs = top["release_notes"].get("missing_docs", [])
    if top["release_notes"].get("docs_complete") is not True or missing_docs:
        add_blocker(
            report,
            "REQUIRED_V2_DOCUMENTATION_MISSING",
            system="documentation",
            title="Required V2 documentation is incomplete.",
            evidence=str(missing_docs),
            recommended_fix="Add the missing major-system documentation and rerun QA.",
        )

    for warning in top["artifacts"].get("stale_artifact_warnings", []):
        warning_digest = hashlib.sha256(str(warning).encode()).hexdigest()[:12].upper()
        add_warning(
            report,
            f"STALE_ARTIFACT_{warning_digest}",
            system="artifacts",
            title="Stale or partial artifact evidence was found.",
            evidence=str(warning),
            recommended_followup="Regenerate affected evidence against the current worktree.",
        )

    blockers = top["blockers"]
    warnings = top["warnings"]
    if fatal_environment:
        status = DECISION_BLOCKED
        summary = "QA is blocked because the Python validation environment is unavailable."
    elif blockers:
        status = DECISION_NOT_READY
        summary = f"Olympus V2 is not release ready: {len(blockers)} blocker(s) remain."
    elif warnings:
        status = DECISION_WARN
        summary = f"Release gates pass with {len(warnings)} documented warning(s)."
    else:
        status = DECISION_PASS
        summary = "All implemented release-candidate gates pass with fresh runtime evidence."
    ready = status in {DECISION_PASS, DECISION_WARN}
    confidence = "high" if status == DECISION_PASS else "medium" if ready else "low"
    top["decision"] = {
        "status": status,
        "release_candidate_ready": ready,
        "confidence": confidence,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "summary": summary,
        "next_action": (
            "Proceed only with explicit release approval."
            if status == DECISION_PASS
            else "Review documented warnings before explicit release approval."
            if status == DECISION_WARN
            else "Resolve blockers and rerun full release-candidate QA."
        ),
    }
    top["release_gates"].update(
        {
            "fresh_local_upload_full_pipeline": fresh_render,
            "final_mp4_validation": final_mp4.get("passed") is True,
            "required_test_suites": not missing_suites
            and all(top["test_suites"][key].get("passed") is True for key in TEST_SUITE_KEYS),
            "frontend_build": top["test_suites"]["frontend_build"].get("passed") is True,
            "backend_import": environment.get("backend_import_ok") is True,
            "safety_metadata": local_pipeline.get("safety_metadata_present") is True,
            "upload_metadata": local_pipeline.get("upload_metadata_present") is True,
            "durable_simulations": top["end_to_end"]["durable_resume"].get("passed") is True,
            "limitations_documented": bool(top["release_notes"].get("known_limitations")),
        }
    )
    return report


def write_release_candidate_report(
    report: dict[str, Any], report_dir: Path
) -> dict[str, str]:
    """Write the canonical JSON and Markdown reports atomically."""

    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "olympus_v2_release_candidate_report.json"
    markdown_path = report_dir / "olympus_v2_release_candidate_summary.md"
    _atomic_write(json_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    _atomic_write(markdown_path, release_candidate_markdown(report))
    return {"json": str(json_path), "markdown": str(markdown_path)}


def release_candidate_markdown(report: dict[str, Any]) -> str:
    """Render the human-readable release-candidate summary."""

    top = _top(report)
    decision = top["decision"]
    lines = [
        "# Olympus V2 Release Candidate QA",
        "",
        f"- Decision: **{decision.get('status')}**",
        f"- Release-candidate ready: `{decision.get('release_candidate_ready')}`",
        f"- Confidence: `{decision.get('confidence')}`",
        f"- Branch: `{top.get('branch')}`",
        f"- Commit: `{top.get('commit_sha')}`",
        f"- Mode: `{top.get('mode')}`",
        f"- Created: `{top.get('created_at')}`",
        "",
        decision.get("summary", ""),
        "",
        "## Blockers",
        "",
    ]
    blockers = top.get("blockers", [])
    if blockers:
        lines.extend(
            f"- **{item.get('id')}** ({item.get('system')}): {item.get('title')} "
            f"Evidence: {item.get('evidence')}"
            for item in blockers
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Warnings", ""])
    warnings = top.get("warnings", [])
    if warnings:
        lines.extend(
            f"- **{item.get('id')}** ({item.get('system')}): {item.get('title')} "
            f"Evidence: {item.get('evidence')}"
            for item in warnings
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Test Suites", ""])
    lines.extend(
        f"- `{name}`: `{result.get('status')}` (exit `{result.get('exit_code')}`, "
        f"{result.get('duration_seconds')}s)"
        for name, result in top["test_suites"].items()
    )
    lines.extend(["", "## Systems", ""])
    lines.extend(
        f"- `{name}`: `{result.get('status')}` — {result.get('evidence_kind') or 'no evidence'}"
        for name, result in top["systems"].items()
    )
    lines.extend(["", "## End-to-End Evidence", ""])
    lines.extend(
        f"- `{name}`: `{result.get('status')}` — {result.get('summary') or 'not recorded'}"
        for name, result in top["end_to_end"].items()
    )
    artifacts = top["artifacts"]
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Render candidates discovered: `{artifacts.get('rendered_clip_count')}`",
            f"- MP4s inspected: `{artifacts.get('inspected_mp4_count')}`",
            f"- Valid inspected MP4s: `{artifacts.get('valid_mp4_count')}`",
            f"- Invalid inspected MP4s: `{artifacts.get('invalid_mp4_count')}`",
            f"- Scope: {artifacts.get('mp4_validation_scope')}",
            "",
            "## Not Claimed",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in top["release_notes"].get("not_claimed", []))
    lines.extend(["", "## Next Action", "", str(decision.get("next_action") or "")])
    return "\n".join(lines) + "\n"


def _add_known_evidence_warnings(report: dict[str, Any]) -> None:
    top = _top(report)
    local_pipeline = top["end_to_end"]["local_upload_full_pipeline"]
    warning_specs = (
        (
            local_pipeline.get("manual_playback_performed") is not True,
            "MANUAL_PLAYBACK_LISTENING_NOT_RUN",
            "editing_rendering_v2",
            "No manual playback/listening validation is recorded.",
            "Perform visual playback and listen on at least one fresh final MP4.",
        ),
        (
            local_pipeline.get("music_audibility_verified") is not True,
            "MUSIC_AUDIBILITY_NOT_VERIFIED_BY_AUDIO_ANALYSIS",
            "music_v2",
            "Music audibility and speech clarity were not verified by listening/audio analysis.",
            "Run objective loudness analysis and manual listening on a fresh render.",
        ),
        (
            local_pipeline.get("real_face_tracking_verified") is not True,
            "REAL_FACE_TRACKED_MOTION_NOT_VALIDATED",
            "motion_effects_v2",
            "No real face-tracked render was visually validated.",
            "Render a real face sample and inspect tracking stability and framing.",
        ),
        (
            top["systems"].get("live_trend_provider_v2", {}).get("live_provider_used")
            is not True,
            "CONFIGURED_LIVE_SEARCH_PROVIDER_NOT_USED",
            "live_trend_provider_v2",
            "No configured live search provider evidence is present.",
            "Configure an approved provider or keep the evergreen/cache fallback label visible.",
        ),
        (
            top["systems"].get("curated_music_library_v2", {}).get(
                "production_assets_available"
            )
            is not True,
            "CURATED_PRODUCTION_MUSIC_LIBRARY_NOT_PROVEN",
            "curated_music_library_v2",
            "A production-quality curated music inventory was not proven.",
            "Audit licensed production tracks separately from generated starter assets.",
        ),
        (
            top["systems"].get("durable_jobs_v2", {}).get("clip_level_partial_resume")
            is not True,
            "CLIP_LEVEL_PARTIAL_RENDER_RESUME_UNSUPPORTED",
            "durable_jobs_v2",
            "Clip-level partial render resume is not proven.",
            "Document stage-level checkpoint behavior and add clip-level resume only if required.",
        ),
        (
            top["systems"].get("link_ingestion", {}).get("pre_project_download_durable")
            is not True,
            "PRE_PROJECT_LINK_DOWNLOAD_DURABILITY_PARTIAL",
            "link_ingestion",
            "Pre-project link download durability is not proven end to end.",
            "Test interruption/recovery during the pre-project download phase.",
        ),
    )
    for condition, warning_id, system, title, followup in warning_specs:
        if condition:
            add_warning(
                report,
                warning_id,
                system=system,
                title=title,
                evidence="No qualifying evidence was recorded in this report.",
                recommended_followup=followup,
            )


def _empty_system_result() -> dict[str, Any]:
    return {
        "status": "not_run",
        "passed": None,
        "evidence_kind": None,
        "checks": [],
        "warnings": [],
        "errors": [],
    }


def _empty_evidence_result() -> dict[str, Any]:
    return {
        "status": "not_run",
        "passed": None,
        "fresh": False,
        "summary": None,
        "evidence": [],
        "warnings": [],
        "errors": [],
    }


def _top(report: dict[str, Any]) -> dict[str, Any]:
    value = report.get("olympus_v2_release_candidate")
    if not isinstance(value, dict):
        raise ValueError("Missing olympus_v2_release_candidate report contract.")
    return value


def _git_value(workspace: Path, *arguments: str) -> str | None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=workspace,
        capture_output=True,
        check=False,
        text=True,
        shell=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _writable_check(path: Path) -> dict[str, Any]:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".olympus_rc_write_{os.getpid()}_{time.time_ns()}.tmp"
    try:
        probe.write_text("olympus-release-candidate-write-check\n", encoding="utf-8")
        probe.unlink()
        return {"path": str(path), "passed": True, "error": None}
    except OSError as exc:
        with suppress(OSError):
            probe.unlink(missing_ok=True)
        return {"path": str(path), "passed": False, "error": str(exc)}


def _missing_executable(check_id: str, executable: str) -> dict[str, Any]:
    result = command_result_skipped(
        check_id,
        f"Executable '{executable}' was not found on PATH.",
        code="EXECUTABLE_MISSING",
        command=(executable,),
    )
    result.update({"passed": False, "status": "failed", "errors": result.pop("warnings")})
    result["warnings"] = []
    return result


def _looks_like_render(path: Path) -> bool:
    lowered = {part.lower() for part in path.parts}
    name = path.name.lower()
    return bool(
        {"render", "renders", "clips", "downloads"} & lowered
        or name.startswith(("validated_", "clip_", "render_"))
    ) and "uploads" not in lowered


def _newest_paths(paths: Any, *, limit: int) -> list[Path]:
    existing = [Path(path) for path in paths if Path(path).is_file()]
    return sorted(set(existing), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]


def _display_command(command: Sequence[str]) -> str:
    if not command:
        return ""
    return subprocess.list2cmdline(list(command)) if os.name == "nt" else " ".join(command)


def _tail(value: str | None, limit: int) -> str:
    text = value or ""
    return text[-limit:]


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _first_output_line(result: dict[str, Any]) -> str | None:
    output = str(result.get("stdout_tail") or result.get("stderr_tail") or "").strip()
    return output.splitlines()[0] if output else None


def _unique(values: Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)

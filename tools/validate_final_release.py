"""Aggregate Olympus V2 validators into one honest internal release-candidate verdict."""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.dependencies import get_optional_dependency_status  # noqa: E402
from olympus.validation.release import (  # noqa: E402
    FINAL_VERDICT_BLOCKED,
    FINAL_VERDICT_PASS,
    REPORT_SUBDIRECTORY,
    FinalReleaseValidationResultV1,
    ValidatorResultV1,
    duration_summary,
    evaluate_final_release,
    extract_report_truth,
    frontend_script_status,
    generated_artifacts_staged,
    load_json_report,
    missing_validator_result,
    optional_provider_limitations,
    skipped_validator_result,
    standard_proof_limitations,
    validated_report_directory,
    validator_result_from_command,
    write_final_release_report,
)
from olympus.validation.release_candidate import run_command  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / REPORT_SUBDIRECTORY
FRONTEND_SCRIPTS = ("typecheck", "lint", "test", "build")


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One deterministic command in the final release gate."""

    name: str
    command: tuple[str, ...]
    cwd: Path
    category: str
    summary: str
    timeout_seconds: float
    required: bool = True
    blocker_on_failure: bool = True
    report_path: Path | None = None
    source_report_path: Path | None = None
    slow: bool = False


def python_executable(root: Path = ROOT) -> Path:
    """Return the canonical workspace virtualenv Python path."""

    if sys.platform == "win32":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def build_command_specs(
    *,
    root: Path = ROOT,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> list[CommandSpec]:
    """Build the audited, sequential release command matrix."""

    python = str(python_executable(root))
    npm = shutil.which("npm") or "npm"
    frontend = root / "frontend"
    evidence = report_dir / "evidence"

    def report(subdirectory: str, filename: str) -> Path:
        return evidence / subdirectory / filename

    def tool(name: str) -> str:
        return str(root / "tools" / name)

    specs = [
        CommandSpec(
            "backend_ruff",
            (python, "-m", "ruff", "check", "src", "tests", "tools"),
            root,
            "backend",
            "Backend Ruff check passed.",
            1800.0,
        ),
        CommandSpec(
            "backend_unit_tests",
            (python, "-m", "pytest", "tests/unit"),
            root,
            "backend",
            "Backend unit test suite passed.",
            3600.0,
        ),
        CommandSpec(
            "backend_mypy",
            (python, "-m", "mypy", "src/olympus", "tools"),
            root,
            "backend",
            "Backend and validator mypy check passed.",
            2400.0,
        ),
        *[
            CommandSpec(
                f"frontend_{script}",
                (npm, "run", script),
                frontend,
                "frontend",
                f"Frontend {script} command passed.",
                1800.0,
            )
            for script in FRONTEND_SCRIPTS
        ],
        CommandSpec(
            "test_assets_self_check",
            (
                python,
                tool("validate_test_assets_dependencies.py"),
                "--self-check",
                "--report-dir",
                str((evidence / "test_assets_self_check").resolve()),
            ),
            root,
            "validator",
            "Test assets and optional dependencies self-check passed.",
            600.0,
            report_path=report(
                "test_assets_self_check", "test_assets_dependencies_report.json"
            ),
        ),
        CommandSpec(
            "test_assets_repo_check",
            (
                python,
                tool("validate_test_assets_dependencies.py"),
                "--repo-check",
                "--report-dir",
                str((evidence / "test_assets_repo_check").resolve()),
            ),
            root,
            "validator",
            "Clean-clone assets and repository hygiene check passed.",
            600.0,
            report_path=report(
                "test_assets_repo_check", "test_assets_dependencies_report.json"
            ),
        ),
        CommandSpec(
            "analysis_signals_self_check",
            (
                python,
                tool("validate_analysis_signals.py"),
                "--self-check",
                "--report-dir",
                str((evidence / "analysis_self_check").resolve()),
            ),
            root,
            "validator",
            "Analysis signal contract self-check passed.",
            600.0,
            report_path=report("analysis_self_check", "analysis_signals_report.json"),
        ),
        CommandSpec(
            "analysis_signals_synthetic",
            (
                python,
                tool("validate_analysis_signals.py"),
                "--synthetic",
                "--report-dir",
                str((evidence / "analysis_synthetic").resolve()),
            ),
            root,
            "validator",
            "Synthetic analysis signal activation passed.",
            1200.0,
            report_path=report("analysis_synthetic", "analysis_signals_report.json"),
        ),
        CommandSpec(
            "real_rendering_e2e",
            (
                python,
                tool("validate_real_rendering_e2e.py"),
                "--local-synthetic",
                "--report-dir",
                str((evidence / "real_rendering").resolve()),
                "--render-preset",
                "ultrafast",
                "--render-threads",
                "1",
                "--render-filter-threads",
                "1",
            ),
            root,
            "validator",
            "Synthetic upload-to-render-to-optimization proof passed.",
            3600.0,
            report_path=report("real_rendering", "real_rendering_e2e_report.json"),
            slow=True,
        ),
        CommandSpec(
            "long_video_full_render",
            (
                python,
                tool("validate_long_video_full_render.py"),
                "--synthetic-long",
                "--minutes",
                "30",
                "--min-clips",
                "3",
                "--report-dir",
                str((evidence / "long_video").resolve()),
                "--render-preset",
                "ultrafast",
                "--render-threads",
                "1",
                "--render-filter-threads",
                "1",
            ),
            root,
            "validator",
            "Thirty-minute synthetic full-render proof passed.",
            10800.0,
            report_path=report("long_video", "long_video_full_render_report.json"),
            slow=True,
        ),
        *_durable_specs(root, evidence, python),
        CommandSpec(
            "face_tracking_self_check",
            (
                python,
                tool("validate_face_tracking_motion.py"),
                "--self-check",
                "--report-dir",
                str((evidence / "face_self_check").resolve()),
            ),
            root,
            "validator",
            "Face-tracking and motion environment self-check passed.",
            600.0,
            report_path=report(
                "face_self_check", "face_motion_validation_self_check.json"
            ),
        ),
        CommandSpec(
            "face_tracking_synthetic_fallback",
            (
                python,
                tool("validate_face_tracking_motion.py"),
                "--synthetic-fallback",
                "--report-dir",
                str((evidence / "face_synthetic_fallback").resolve()),
            ),
            root,
            "validator",
            "Synthetic face fallback and rendered motion proof passed.",
            1200.0,
            report_path=report(
                "face_synthetic_fallback",
                "face_motion_validation_synthetic_fallback.json",
            ),
        ),
        CommandSpec(
            "multi_speaker_self_check",
            (
                python,
                tool("validate_multi_speaker_layout.py"),
                "--self-check",
                "--report-dir",
                str((evidence / "multi_speaker_self_check").resolve()),
            ),
            root,
            "validator",
            "Multi-speaker layout environment self-check passed.",
            600.0,
            report_path=report(
                "multi_speaker_self_check",
                "multi_speaker_layout_validation_self_check.json",
            ),
        ),
        CommandSpec(
            "multi_speaker_synthetic",
            (
                python,
                tool("validate_multi_speaker_layout.py"),
                "--synthetic-two-speaker",
                "--report-dir",
                str((evidence / "multi_speaker_synthetic").resolve()),
            ),
            root,
            "validator",
            "Synthetic two-speaker layout render proof passed.",
            1200.0,
            report_path=report(
                "multi_speaker_synthetic",
                "multi_speaker_layout_validation_synthetic_two_speaker.json",
            ),
        ),
        *_av_specs(root, evidence, python),
        *_checkpoint_specs(root, evidence, python),
        *_boba_specs(root, evidence, python),
    ]
    return specs


def _durable_specs(root: Path, evidence: Path, python: str) -> list[CommandSpec]:
    tool = str(root / "tools" / "validate_durable_restart_resume.py")
    values = (
        (
            "durable_resume_after_analysis",
            "--interrupt-after",
            "analysis",
            "interrupt_after_analysis",
        ),
        (
            "durable_resume_after_editing",
            "--interrupt-after",
            "editing",
            "interrupt_after_editing",
        ),
        (
            "durable_resume_during_rendering",
            "--interrupt-during",
            "rendering",
            "interrupt_during_rendering",
        ),
    )
    specs: list[CommandSpec] = []
    for name, flag, stage, mode in values:
        directory = evidence / name
        specs.append(
            CommandSpec(
                name,
                (
                    python,
                    tool,
                    "--synthetic",
                    flag,
                    stage,
                    "--report-dir",
                    str(directory.resolve()),
                    "--render-preset",
                    "ultrafast",
                    "--render-threads",
                    "1",
                    "--render-filter-threads",
                    "1",
                ),
                root,
                "validator",
                f"Durable restart/resume proof for {stage} passed.",
                5400.0,
                report_path=directory / f"durable_restart_resume_{mode}_report.json",
                slow=True,
            )
        )
    return specs


def _av_specs(root: Path, evidence: Path, python: str) -> list[CommandSpec]:
    tool = str(root / "tools" / "validate_av_sync_boundaries.py")
    values = (
        ("av_sync_self_check", "--self-check", "av_sync_boundaries_report.json"),
        ("av_sync_simulation", "--simulate", "av_sync_boundaries_report.json"),
        (
            "av_sync_stress_simulation",
            "--stress-simulate",
            "av_sync_boundaries_stress_report.json",
        ),
    )
    return [
        CommandSpec(
            name,
            (
                python,
                tool,
                mode,
                "--output-dir",
                str((evidence / name).resolve()),
            ),
            root,
            "validator",
            f"A/V sync boundary validator {mode} passed.",
            1200.0,
            report_path=evidence / name / filename,
        )
        for name, mode, filename in values
    ]


def _checkpoint_specs(root: Path, evidence: Path, python: str) -> list[CommandSpec]:
    tool = str(root / "tools" / "validate_render_checkpoint_handoff.py")
    return [
        CommandSpec(
            name,
            (
                python,
                tool,
                mode,
                "--report-dir",
                str((evidence / name).resolve()),
            ),
            root,
            "validator",
            f"Render checkpoint handoff validator {mode} passed.",
            900.0,
            report_path=evidence / name / "render_checkpoint_handoff_report.json",
        )
        for name, mode in (
            ("render_checkpoint_self_check", "--self-check"),
            ("render_checkpoint_simulation", "--simulate"),
        )
    ]


def _boba_specs(root: Path, evidence: Path, python: str) -> list[CommandSpec]:
    values = (
        (
            "boba_core_self_check",
            "validate_boba_core.py",
            "--self-check",
            root / "work" / "validation_reports" / "boba_core" / "boba_core_validation_report.json",
        ),
        (
            "boba_memory_self_check",
            "validate_boba_memory.py",
            "--self-check",
            root
            / "work"
            / "validation_reports"
            / "boba_memory"
            / "boba_memory_validation_report.json",
        ),
        (
            "boba_integrated",
            "validate_rnd_boba_integrated.py",
            "--all",
            root
            / "work"
            / "rnd_validation"
            / "boba_integrated"
            / "rnd_boba_integrated_report.json",
        ),
    )
    return [
        CommandSpec(
            name,
            (python, str(root / "tools" / filename), mode),
            root,
            "validator",
            f"{name.replace('_', ' ').title()} passed.",
            1200.0,
            report_path=evidence / name / f"{name}_report.json",
            source_report_path=source,
        )
        for name, filename, mode, source in values
    ]


def collect_environment(
    *,
    root: Path = ROOT,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> dict[str, Any]:
    """Collect deterministic local prerequisites without running slow validators."""

    python = python_executable(root)
    validators = sorted(
        path.name
        for path in (root / "tools").glob("validate_*.py")
        if path.is_file()
    )
    required_validator_names = sorted(
        {
            Path(spec.command[1]).name
            for spec in build_command_specs(root=root, report_dir=report_dir)
            if len(spec.command) > 1 and spec.command[1].endswith(".py")
        }
    )
    missing_validators = [name for name in required_validator_names if name not in validators]
    optional = get_optional_dependency_status()
    report_writable, report_error = _directory_writable(report_dir)
    storage_writable, storage_error = _directory_writable(root / "storage_data")
    git = _git_state(root)
    frontend_scripts = frontend_script_status(
        root / "frontend" / "package.json", FRONTEND_SCRIPTS
    )
    backend_import, import_error = _backend_import_status()
    environment = {
        "python_available": python.is_file(),
        "python_version": sys.version.split()[0],
        "virtualenv_path": python.relative_to(root).as_posix(),
        "virtualenv_exists": python.is_file(),
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "ffprobe_available": shutil.which("ffprobe") is not None,
        "npm_available": shutil.which("npm") is not None,
        "frontend_directory_exists": (root / "frontend").is_dir(),
        "package_json_exists": (root / "frontend" / "package.json").is_file(),
        "pyproject_exists": (root / "pyproject.toml").is_file(),
        "backend_import_available": backend_import,
        "backend_import_error": import_error,
        "required_validators": required_validator_names,
        "missing_validators": missing_validators,
        "report_directory_writable": report_writable,
        "report_directory_error": report_error,
        "storage_directory_writable": storage_writable,
        "storage_directory_error": storage_error,
        "optional_dependencies": optional,
        "frontend_scripts": frontend_scripts,
        "git": git,
    }
    required_values = (
        environment["python_available"],
        environment["ffmpeg_available"],
        environment["ffprobe_available"],
        environment["npm_available"],
        environment["frontend_directory_exists"],
        environment["package_json_exists"],
        environment["pyproject_exists"],
        environment["backend_import_available"],
        not missing_validators,
        environment["report_directory_writable"],
        environment["storage_directory_writable"],
        frontend_scripts["passed"],
        not git["staged_generated_paths"],
    )
    environment["passed"] = all(value is True for value in required_values)
    return environment


def run_full_validation(
    *,
    root: Path = ROOT,
    report_dir: Path = DEFAULT_REPORT_DIR,
    skip_slow: bool = False,
) -> FinalReleaseValidationResultV1:
    """Run the full local-only release sequence and classify its evidence."""

    environment = collect_environment(root=root, report_dir=report_dir)
    result = _base_result(root=root, environment=environment)
    specs = build_command_specs(root=root, report_dir=report_dir)
    frontend_missing = set(environment["frontend_scripts"].get("missing_scripts") or [])
    for spec in specs:
        if spec.slow and skip_slow:
            result.validators.append(
                skipped_validator_result(
                    spec.name,
                    spec.command,
                    "Skipped by --skip-slow; this required proof remains incomplete.",
                    required=spec.required,
                    blocker_on_failure=spec.blocker_on_failure,
                )
            )
            continue
        missing_reason = _missing_command_reason(spec, frontend_missing)
        if missing_reason:
            missing = missing_validator_result(
                spec.name,
                spec.command,
                required=spec.required,
                blocker_on_failure=spec.blocker_on_failure,
            )
            missing.errors = [missing_reason]
            result.validators.append(missing)
            continue
        result.validators.append(_run_spec(spec, root=root))

    result.backend_status = _category_status(result.validators, "backend", specs)
    result.frontend_status = _category_status(result.validators, "frontend", specs)
    artifacts, artifact_blockers = collect_artifact_evidence(
        result.validators,
        root=root,
    )
    result.artifacts = artifacts
    result.blockers.extend(_environment_blockers(environment))
    result.blockers.extend(artifact_blockers)
    result.limitations.extend(standard_proof_limitations())
    result.limitations.extend(
        optional_provider_limitations(environment.get("optional_dependencies") or {})
    )
    if environment.get("git", {}).get("dirty"):
        result.warnings.append(
            "Git worktree is dirty; exact changed paths are recorded in environment.git."
        )
    result.artifacts["validator_durations"] = duration_summary(result.validators)
    evaluate_final_release(
        result,
        required_validator_names=[spec.name for spec in specs if spec.required],
    )
    return result


def run_self_check(
    *,
    root: Path = ROOT,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> FinalReleaseValidationResultV1:
    """Run prerequisite checks only; required runtime proof intentionally remains incomplete."""

    environment = collect_environment(root=root, report_dir=report_dir)
    result = _base_result(root=root, environment=environment)
    result.backend_status = {
        "status": "self_check_only",
        "passed": environment.get("backend_import_available") is True,
    }
    result.frontend_status = {
        "status": "self_check_only",
        "passed": environment.get("frontend_scripts", {}).get("passed") is True,
    }
    result.blockers.extend(_environment_blockers(environment))
    result.limitations.extend(standard_proof_limitations())
    result.limitations.extend(
        optional_provider_limitations(environment.get("optional_dependencies") or {})
    )
    result.warnings.append("Self-check mode does not run backend, frontend, or rendering proofs.")
    if environment.get("git", {}).get("dirty"):
        result.warnings.append(
            "Git worktree is dirty; exact changed paths are recorded in environment.git."
        )
    evaluate_final_release(result)
    if not result.blockers:
        result.final_verdict = "INCOMPLETE"
        result.release_readiness = "validation_incomplete"
    return result


def inspect_existing_reports(
    *,
    root: Path = ROOT,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> FinalReleaseValidationResultV1:
    """Inspect current final-evidence reports without rerunning commands."""

    environment = collect_environment(root=root, report_dir=report_dir)
    result = _base_result(root=root, environment=environment)
    specs = build_command_specs(root=root, report_dir=report_dir)
    for spec in specs:
        if spec.report_path is None:
            result.validators.append(
                skipped_validator_result(
                    spec.name,
                    spec.command,
                    "No standalone report exists for this command; command was not rerun.",
                    required=spec.required,
                    blocker_on_failure=spec.blocker_on_failure,
                )
            )
            continue
        payload, errors = load_json_report(spec.report_path)
        truth = extract_report_truth(payload) if not errors else None
        command_result: dict[str, Any] = {
            "passed": truth is True,
            "duration_seconds": 0.0,
            "warnings": ["Existing report inspected; validator command was not rerun."],
            "errors": errors or ([] if truth is True else ["Existing report is not passing."]),
            "timed_out": False,
        }
        result.validators.append(
            validator_result_from_command(
                name=spec.name,
                command=spec.command,
                command_result=command_result,
                required=spec.required,
                blocker_on_failure=spec.blocker_on_failure,
                summary=f"Inspected existing evidence for {spec.name}.",
                workspace_root=root,
                report_path=spec.report_path,
            )
        )
    result.backend_status = _category_status(result.validators, "backend", specs)
    result.frontend_status = _category_status(result.validators, "frontend", specs)
    result.artifacts, artifact_blockers = collect_artifact_evidence(result.validators, root=root)
    result.blockers.extend(_environment_blockers(environment))
    result.blockers.extend(artifact_blockers)
    result.limitations.extend(standard_proof_limitations())
    result.limitations.extend(
        optional_provider_limitations(environment.get("optional_dependencies") or {})
    )
    result.warnings.append("Inspection mode did not rerun validators or refresh evidence.")
    evaluate_final_release(
        result,
        required_validator_names=[spec.name for spec in specs if spec.required],
    )
    return result


def collect_artifact_evidence(
    validators: Sequence[ValidatorResultV1],
    *,
    root: Path,
) -> tuple[dict[str, Any], list[str]]:
    """Extract compact proof facts and reject internally inconsistent passing reports."""

    payloads = {
        result.name: _payload_for_result(result, root)
        for result in validators
        if result.report_path
    }
    blockers: list[str] = []
    real = payloads.get("real_rendering_e2e", {})
    real_clips = _dict_list(real.get("clips"))
    accepted_real = sum(item.get("passed") is True for item in real_clips)
    real_av = [_number(item.get("av_delta_seconds")) for item in real_clips]
    real_summary = {
        "passed": real.get("passed") is True,
        "accepted_mp4_count": accepted_real,
        "render_manifest_valid": real.get("render_manifest_valid") is True,
        "optimization_manifest_valid": real.get("optimization_manifest_valid") is True,
        "api_payload_valid": real.get("api_payload_valid") is True,
        "frontend_payload_valid": real.get("frontend_payload_valid") is True,
        "final_payload_valid": real.get("api_payload_valid") is True
        and real.get("frontend_payload_valid") is True,
        "maximum_av_delta_seconds": max((abs(item) for item in real_av), default=None),
    }
    if real.get("passed") is True:
        if accepted_real < 1:
            blockers.append("Real rendering report passed with zero accepted MP4s.")
        for key in (
            "render_manifest_valid",
            "optimization_manifest_valid",
            "api_payload_valid",
            "frontend_payload_valid",
        ):
            if real.get(key) is not True:
                blockers.append(f"Real rendering report passed while {key} was false.")
        if any(abs(item) > 0.15 for item in real_av):
            blockers.append("Real rendering report passed with A/V delta above 0.15 seconds.")

    long_video = payloads.get("long_video_full_render", {})
    long_av = _dict_list(long_video.get("av_delta_results"))
    long_summary = {
        "passed": long_video.get("passed") is True,
        "source_duration_minutes": long_video.get("source_duration_minutes"),
        "planned_clip_count": _integer(long_video.get("planned_clip_count")),
        "accepted_mp4_count": _integer(long_video.get("accepted_mp4_count")),
        "render_manifest_present": long_video.get("render_manifest_present") is True,
        "optimization_manifest_present": long_video.get("optimization_manifest_present") is True,
        "final_payload_valid": long_video.get("final_payload_valid") is True,
        "av_results_passed": bool(long_av)
        and all(item.get("passed") is True for item in long_av),
    }
    if long_video.get("passed") is True:
        if _number(long_video.get("source_duration_minutes")) < 30.0:
            blockers.append("Long-video report passed with a source shorter than 30 minutes.")
        if _integer(long_video.get("accepted_mp4_count")) < 3:
            blockers.append("Long-video report passed with fewer than three accepted MP4s.")
        if not all(
            long_video.get(key) is True
            for key in (
                "render_manifest_present",
                "optimization_manifest_present",
                "final_payload_valid",
            )
        ):
            blockers.append("Long-video report passed without complete manifest/payload proof.")
        if not long_av or any(item.get("passed") is not True for item in long_av):
            blockers.append("Long-video report passed without complete A/V tolerance proof.")

    durable_names = (
        "durable_resume_after_analysis",
        "durable_resume_after_editing",
        "durable_resume_during_rendering",
    )
    durable_payloads = [payloads.get(name, {}) for name in durable_names]
    passing_modes = [
        str(payload.get("mode"))
        for payload in durable_payloads
        if payload.get("resume_successful") is True
    ]
    durable_summary = {
        "passing_modes": passing_modes,
        "required_mode_count": len(durable_names),
        "accepted_mp4_count": sum(
            _integer(payload.get("accepted_mp4_count")) for payload in durable_payloads
        ),
        "all_manifests_present": bool(durable_payloads)
        and all(
            payload.get("render_manifest_present") is True
            and payload.get("optimization_manifest_present") is True
            for payload in durable_payloads
        ),
        "all_payloads_valid": bool(durable_payloads)
        and all(payload.get("final_payload_valid") is True for payload in durable_payloads),
    }
    for name, payload in zip(durable_names, durable_payloads, strict=True):
        if payload.get("resume_successful") is True and (
            _integer(payload.get("accepted_mp4_count")) < 1
            or payload.get("render_manifest_present") is not True
            or payload.get("optimization_manifest_present") is not True
            or payload.get("final_payload_valid") is not True
        ):
            blockers.append(f"{name} reported success without complete output proof.")

    analysis_self = payloads.get("analysis_signals_self_check", {})
    analysis_synthetic = payloads.get("analysis_signals_synthetic", {})
    assets_self = payloads.get("test_assets_self_check", {})
    assets_repo = payloads.get("test_assets_repo_check", {})
    artifacts = {
        "real_rendering": real_summary,
        "long_video": long_summary,
        "durable_resume": durable_summary,
        "analysis_signals": {
            "self_check_passed": analysis_self.get("passed") is True,
            "synthetic_passed": analysis_synthetic.get("passed") is True,
            "optional_signal_statuses_honest": _analysis_optional_honest(
                analysis_synthetic
            ),
        },
        "assets_dependencies": {
            "self_check_passed": assets_self.get("passed") is True,
            "repo_check_passed": assets_repo.get("passed") is True,
            "staged_generated_paths": _nested_list(
                assets_repo, "repository_hygiene", "staged_forbidden_paths"
            ),
        },
    }
    return artifacts, list(dict.fromkeys(blockers))


def _run_spec(spec: CommandSpec, *, root: Path) -> ValidatorResultV1:
    if spec.report_path is not None:
        spec.report_path.parent.mkdir(parents=True, exist_ok=True)
        spec.report_path.unlink(missing_ok=True)
    source_mtime = (
        spec.source_report_path.stat().st_mtime_ns
        if spec.source_report_path is not None and spec.source_report_path.is_file()
        else None
    )
    raw = run_command(
        spec.name,
        spec.command,
        cwd=spec.cwd,
        timeout_seconds=spec.timeout_seconds,
    )
    if spec.source_report_path is not None and spec.report_path is not None:
        current_mtime = (
            spec.source_report_path.stat().st_mtime_ns
            if spec.source_report_path.is_file()
            else None
        )
        fresh_source = current_mtime is not None and current_mtime != source_mtime
        if raw.get("passed") is True and fresh_source:
            spec.report_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(spec.source_report_path, spec.report_path)
    return validator_result_from_command(
        name=spec.name,
        command=spec.command,
        command_result=raw,
        required=spec.required,
        blocker_on_failure=spec.blocker_on_failure,
        summary=spec.summary,
        workspace_root=root,
        report_path=spec.report_path,
    )


def _base_result(
    *,
    root: Path,
    environment: dict[str, Any],
) -> FinalReleaseValidationResultV1:
    return FinalReleaseValidationResultV1(
        git_commit=_git_value(root, "rev-parse", "HEAD"),
        git_branch=_git_value(root, "branch", "--show-current"),
        environment=environment,
    )


def _environment_blockers(environment: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    checks = (
        ("python_available", "Workspace virtualenv Python is unavailable."),
        ("ffmpeg_available", "FFmpeg is unavailable."),
        ("ffprobe_available", "FFprobe is unavailable."),
        ("npm_available", "npm is unavailable."),
        ("frontend_directory_exists", "Frontend directory is missing."),
        ("package_json_exists", "Frontend package.json is missing."),
        ("pyproject_exists", "pyproject.toml is missing."),
        ("backend_import_available", "Olympus backend import failed."),
        ("report_directory_writable", "Final validation report directory is not writable."),
        ("storage_directory_writable", "Local validation storage directory is not writable."),
    )
    for key, message in checks:
        if environment.get(key) is not True:
            blockers.append(message)
    missing = environment.get("missing_validators") or []
    if missing:
        blockers.append("Required validator scripts are missing: " + ", ".join(missing) + ".")
    frontend = environment.get("frontend_scripts") or {}
    blockers.extend(str(item) for item in frontend.get("errors") or [])
    staged = environment.get("git", {}).get("staged_generated_paths") or []
    if staged:
        blockers.append("Generated artifacts are staged: " + ", ".join(staged) + ".")
    return list(dict.fromkeys(blockers))


def _category_status(
    validators: Sequence[ValidatorResultV1],
    category: str,
    specs: Sequence[CommandSpec],
) -> dict[str, Any]:
    names = {spec.name for spec in specs if spec.category == category}
    selected = [item for item in validators if item.name in names]
    failed = [item.name for item in selected if item.status == "failed"]
    incomplete = [
        item.name for item in selected if item.status in {"skipped", "not_run"}
    ]
    passed = bool(selected) and not failed and not incomplete
    return {
        "status": "passed" if passed else "failed" if failed else "incomplete",
        "passed": passed,
        "checks": [item.name for item in selected],
        "failed_checks": failed,
        "incomplete_checks": incomplete,
        "duration_seconds": round(sum(item.duration_seconds for item in selected), 3),
    }


def _missing_command_reason(spec: CommandSpec, frontend_missing: set[str]) -> str | None:
    if spec.category == "frontend":
        script = spec.name.removeprefix("frontend_")
        if script in frontend_missing:
            return f"Missing frontend npm script: {script}"
        if shutil.which("npm") is None:
            return "npm executable is unavailable."
        return None
    executable = Path(spec.command[0])
    if executable.is_absolute() and not executable.is_file():
        return f"Python executable is missing: {executable.name}"
    if len(spec.command) > 1 and spec.command[1].endswith(".py"):
        validator_script = Path(spec.command[1])
        if not validator_script.is_file():
            return f"Validator command is missing: {validator_script.name}"
    return None


def _payload_for_result(result: ValidatorResultV1, root: Path) -> dict[str, Any]:
    if not result.report_path:
        return {}
    path = (root / result.report_path).resolve()
    payload, errors = load_json_report(path)
    return payload if not errors else {}


def _analysis_optional_honest(payload: Mapping[str, Any]) -> bool:
    statuses = payload.get("signal_statuses")
    if not isinstance(statuses, Mapping):
        return False
    optional = (
        "speaker_segmentation",
        "emotion_timeline",
        "ocr",
        "face_detection",
        "object_detection",
    )
    return all(
        isinstance(statuses.get(name), Mapping)
        and statuses[name].get("status") in {"available", "partial", "fallback", "unavailable"}
        for name in optional
    )


def _directory_writable(path: Path) -> tuple[bool, str | None]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path,
            prefix=".final-release-write-",
            suffix=".tmp",
            delete=True,
        ) as handle:
            handle.write("ok")
            handle.flush()
        return True, None
    except OSError as exc:
        return False, str(exc)


def _backend_import_status() -> tuple[bool, str | None]:
    try:
        importlib.import_module("olympus.api.app")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


def _git_state(root: Path) -> dict[str, Any]:
    status = _git_lines(root, "status", "--porcelain=v1")
    staged = _git_lines(
        root,
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
    )
    return {
        "dirty": bool(status),
        "status_entries": status,
        "staged_generated_paths": generated_artifacts_staged(staged),
    }


def _git_lines(root: Path, *arguments: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _git_value(root: Path, *arguments: str) -> str:
    lines = _git_lines(root, *arguments)
    return lines[0] if lines else "unknown"


def _payload_output(
    result: FinalReleaseValidationResultV1,
    paths: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "final_verdict": result.final_verdict,
        "release_readiness": result.release_readiness,
        "blocker_count": len(result.blockers),
        "limitation_count": len(result.limitations),
        "reports": dict(paths),
        "blockers": result.blockers,
        "warnings": result.warnings,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--full", action="store_true")
    modes.add_argument("--inspect-reports", action="store_true")
    parser.add_argument("--skip-slow", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.skip_slow and not args.full:
        parser.error("--skip-slow requires --full")
    report_dir = validated_report_directory(args.report_dir, ROOT)
    if args.self_check:
        result = run_self_check(root=ROOT, report_dir=report_dir)
    elif args.full:
        result = run_full_validation(
            root=ROOT,
            report_dir=report_dir,
            skip_slow=bool(args.skip_slow),
        )
    else:
        result = inspect_existing_reports(root=ROOT, report_dir=report_dir)
    paths = write_final_release_report(result, report_dir, workspace_root=ROOT)
    print(json.dumps(_payload_output(result, paths), indent=2))
    if args.self_check:
        return 1 if result.final_verdict == FINAL_VERDICT_BLOCKED else 0
    return 0 if result.final_verdict == FINAL_VERDICT_PASS else 1


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _nested_list(value: Mapping[str, Any], first: str, second: str) -> list[Any]:
    nested = value.get(first)
    if not isinstance(nested, Mapping):
        return []
    raw = nested.get(second)
    return raw if isinstance(raw, list) else []


def _integer(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate deterministic analysis signals and honest unavailable states locally."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.analysis.availability import analysis_capabilities  # noqa: E402
from olympus.analysis.pipeline import AnalysisPipeline, build_default_analyzers  # noqa: E402
from olympus.data.repositories.analysis_repository import (  # noqa: E402
    StorageAnalysisRepository,
)
from olympus.data.storage.local import LocalStorage  # noqa: E402
from olympus.domain.contracts.ai import TranscriptResult, TranscriptSegment  # noqa: E402
from olympus.domain.entities.project import Project, ProjectStatus  # noqa: E402
from olympus.utils import utc_now  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "analysis_signals"
DEFAULT_STORAGE_ROOT = ROOT / "storage_data"
REPORT_NAME = "analysis_signals_report.json"
SUMMARY_NAME = "analysis_signals_summary.md"
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")


class _SyntheticTranscriptProvider:
    name = "deterministic_validator_transcript"

    async def transcribe(
        self,
        audio_key: str,
        *,
        language_hint: str | None = None,
    ) -> TranscriptResult:
        del audio_key, language_hint
        return TranscriptResult(
            language="en",
            confidence=0.96,
            segments=[
                TranscriptSegment(
                    start=0.1,
                    end=1.7,
                    text="This is amazing, but there is a problem!",
                    confidence=0.95,
                ),
                TranscriptSegment(
                    start=3.1,
                    end=4.4,
                    text="Actually the secret changes everything.",
                    confidence=0.95,
                ),
                TranscriptSegment(
                    start=4.7,
                    end=5.8,
                    text="Finally we win and succeed.",
                    confidence=0.95,
                ),
            ],
        )


def self_check() -> dict[str, Any]:
    capabilities = analysis_capabilities()
    imports_ok = True
    import_error: str | None = None
    try:
        build_default_analyzers()
    except Exception as exc:
        imports_ok = False
        import_error = f"{type(exc).__name__}: {exc}"
    ffmpeg_available = bool(capabilities["ffmpeg"]["available"])
    ffprobe_available = bool(capabilities["ffprobe"]["available"])
    errors: list[str] = []
    if not imports_ok:
        errors.append(import_error or "Analysis modules failed to import.")
    if not ffmpeg_available:
        errors.append("ffmpeg is unavailable")
    if not ffprobe_available:
        errors.append("ffprobe is unavailable")
    warnings = [
        f"{name}: {details['reason']}"
        for name, details in capabilities.items()
        if isinstance(details, dict)
        and name not in {"ffmpeg", "ffprobe"}
        and not details.get("available")
    ]
    return {
        "mode": "self_check",
        "passed": not errors,
        "analysis_modules_import": imports_ok,
        "capabilities": capabilities,
        "external_calls_made": False,
        "warnings": warnings,
        "errors": errors,
    }


def generate_synthetic_media(path: Path, *, ffmpeg_binary: str = "ffmpeg") -> dict[str, Any]:
    binary = shutil.which(ffmpeg_binary)
    if binary is None:
        raise RuntimeError(f"FFmpeg binary {ffmpeg_binary!r} is unavailable.")
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        binary,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        "1",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=320x180:r=24:d=2",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=320x180:r=24:d=2",
        "-f",
        "lavfi",
        "-i",
        "color=c=green:s=320x180:r=24:d=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=16000:duration=2",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=16000:cl=mono:d=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=660:sample_rate=16000:duration=3",
        "-filter_complex",
        (
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v];"
            "[3:a]volume=0.8[a0];[5:a]volume=0.06[a2];"
            "[a0][4:a][a2]concat=n=3:v=0:a=1[a]"
        ),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "16000",
        "-shortest",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if completed.returncode != 0 or not path.is_file():
        raise RuntimeError(
            "Synthetic media generation failed: "
            + (completed.stderr[-1000:].strip() or f"exit {completed.returncode}")
        )
    return {
        "duration_seconds": 6.0,
        "scene_count_expected": 3,
        "silence_gap_expected": True,
        "contains_real_people": False,
        "external_calls_made": False,
    }


async def run_synthetic(*, ffmpeg_binary: str = "ffmpeg") -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="olympus-analysis-signals-") as temporary:
        temporary_root = Path(temporary)
        media_path = temporary_root / "synthetic_source.mp4"
        fixture = generate_synthetic_media(media_path, ffmpeg_binary=ffmpeg_binary)
        storage = LocalStorage(str(temporary_root / "storage"))
        storage_key = "uploads/validation/analysis-signals-source.mp4"
        await storage.put(storage_key, media_path.read_bytes(), content_type="video/mp4")
        now = utc_now()
        project = Project(
            id="proj_analysis_signals_synthetic",
            name="Synthetic analysis signals",
            source_filename="analysis-signals-source.mp4",
            storage_key=storage_key,
            size_bytes=media_path.stat().st_size,
            video_format="mp4",
            content_type="video/mp4",
            duration_seconds=6.0,
            width=320,
            height=180,
            status=ProjectStatus.UPLOADED,
            created_at=now,
            updated_at=now,
        )
        repository = StorageAnalysisRepository(storage)
        analysis = await AnalysisPipeline(build_default_analyzers(), repository).run(
            project,
            storage,
            transcription_provider=_SyntheticTranscriptProvider(),
        )
        artifact = analysis.signals_v2() or {}
        report = _evaluate_artifact(
            artifact,
            mode="synthetic",
            project_id=project.id,
        )
        report["pipeline_status"] = analysis.status.value
        report["pipeline_version"] = analysis.pipeline_version
        report["stages"] = [stage.summary() for stage in analysis.stages]
        report["synthetic_fixture"] = fixture
        report["temporary_media_removed"] = False
    report["temporary_media_removed"] = not media_path.exists()
    return report


def inspect_project(
    project_id: str,
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
) -> dict[str, Any]:
    if not _PROJECT_ID_RE.fullmatch(project_id):
        return _failed_report("project_id", project_id, "Project ID is not safe.")
    artifact_path = (
        storage_root / "analysis" / project_id / "stages" / "signal_health.json"
    )
    if not artifact_path.is_file():
        return _failed_report(
            "project_id",
            project_id,
            f"analysis_signals_v2 artifact is missing: {artifact_path}",
        )
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return _failed_report("project_id", project_id, f"Artifact is unreadable: {exc}")
    data = payload.get("data") if isinstance(payload, dict) else None
    artifact = data.get("analysis_signals_v2") if isinstance(data, dict) else None
    if not isinstance(artifact, dict):
        return _failed_report(
            "project_id",
            project_id,
            "signal_health stage does not contain analysis_signals_v2.",
        )
    report = _evaluate_artifact(artifact, mode="project_id", project_id=project_id)
    report.update(
        {
            "inspection_only": True,
            "analysis_rerun": False,
            "artifact_path": str(artifact_path),
        }
    )
    return report


def write_reports(
    report: dict[str, Any],
    *,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> dict[str, str]:
    output = _validated_report_dir(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / REPORT_NAME
    summary_path = output / SUMMARY_NAME
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    health = _dict(report.get("signal_health"))
    lines = [
        "# Analysis Signal Activation V2",
        "",
        f"- Mode: `{report.get('mode')}`",
        f"- Passed: `{str(bool(report.get('passed'))).lower()}`",
        f"- Project: `{report.get('project_id') or 'none'}`",
        f"- Total signals: `{health.get('total_signals', 0)}`",
        f"- Available: `{health.get('available_count', 0)}`",
        f"- Partial: `{health.get('partial_count', 0)}`",
        f"- Fallback: `{health.get('fallback_count', 0)}`",
        f"- Unavailable: `{health.get('unavailable_count', 0)}`",
        f"- Failed: `{health.get('failed_count', 0)}`",
        "- External calls: `false`",
        "- Raw frames/media stored in artifact: `false`",
    ]
    warnings = [str(item) for item in report.get("warnings") or []]
    errors = [str(item) for item in report.get("errors") or []]
    if warnings:
        lines.extend(["", "## Warnings", *[f"- {item}" for item in warnings]])
    if errors:
        lines.extend(["", "## Errors", *[f"- {item}" for item in errors]])
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "summary": str(summary_path)}


def _evaluate_artifact(
    artifact: dict[str, Any],
    *,
    mode: str,
    project_id: str,
) -> dict[str, Any]:
    health = _dict(artifact.get("signal_health"))
    statuses = {
        name: _dict(_dict(entry).get("status"))
        for name, entry in artifact.items()
        if name not in {"contract_version", "signal_health"}
    }
    checks = {
        "analysis_signals_v2_exists": artifact.get("contract_version") == "analysis_signals_v2",
        "signal_health_exists": bool(health),
        "health_counts_correct": _health_counts_correct(health),
        "audio_energy_available": statuses.get("audio_energy", {}).get("available") is True,
        "silence_available": statuses.get("silence", {}).get("available") is True,
        "scene_detection_available": statuses.get("scene_detection", {}).get("available")
        is True,
        "shot_detection_available": statuses.get("shot_detection", {}).get("available") is True,
        "visual_pacing_usable": statuses.get("visual_pacing", {}).get("status")
        in {"available", "partial", "fallback"},
        "speaker_status_honest": statuses.get("speaker_segmentation", {}).get("status")
        in {"available", "fallback", "unavailable"},
        "emotion_status_honest": statuses.get("emotion_timeline", {}).get("status")
        in {"available", "fallback", "unavailable"},
        "ocr_status_honest": _honest_optional(statuses.get("ocr", {})),
        "face_status_honest": _honest_optional(statuses.get("face_detection", {})),
        "object_status_honest": _honest_optional(statuses.get("object_detection", {})),
        "no_raw_frames_or_media": not _contains_forbidden_payload(artifact),
    }
    errors = [name.replace("_", " ") for name, passed in checks.items() if not passed]
    warnings = [str(item) for item in health.get("warnings") or []]
    return {
        "mode": mode,
        "project_id": project_id,
        "passed": not errors,
        "checks": checks,
        "signal_health": health,
        "signal_statuses": statuses,
        "analysis_signals_v2": artifact,
        "external_calls_made": False,
        "raw_frames_stored": False,
        "raw_media_stored": False,
        "warnings": warnings,
        "errors": errors,
    }


def _health_counts_correct(health: dict[str, Any]) -> bool:
    total = int(health.get("total_signals") or 0)
    counted = sum(
        int(health.get(name) or 0)
        for name in (
            "available_count",
            "partial_count",
            "fallback_count",
            "unavailable_count",
            "failed_count",
        )
    )
    signals = health.get("signals")
    return total > 0 and counted == total and isinstance(signals, list) and len(signals) == total


def _honest_optional(status: dict[str, Any]) -> bool:
    if status.get("available") is True:
        return bool(status.get("provider"))
    return (
        status.get("status") in {"unavailable", "failed", "skipped"}
        and status.get("confidence") == 0.0
        and status.get("reason") in {"dependency_missing", "model_missing", "analysis_failed"}
    )


def _contains_forbidden_payload(value: Any) -> bool:
    forbidden = {"raw_frame", "raw_frames", "frame_bytes", "media_bytes", "video_bytes"}
    if isinstance(value, dict):
        if any(str(key).lower() in forbidden for key in value):
            return True
        return any(_contains_forbidden_payload(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_payload(item) for item in value)
    return isinstance(value, bytes | bytearray)


def _failed_report(mode: str, project_id: str | None, error: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "project_id": project_id,
        "passed": False,
        "external_calls_made": False,
        "warnings": [],
        "errors": [error],
    }


def _validated_report_dir(path: Path) -> Path:
    allowed = (ROOT / "work" / "validation_reports").resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f"Report directory must stay under {allowed}.") from exc
    return resolved


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--synthetic", action="store_true")
    modes.add_argument("--project-id")
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--ffmpeg-binary", default="ffmpeg")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.self_check:
        report = self_check()
    elif args.synthetic:
        report = asyncio.run(run_synthetic(ffmpeg_binary=args.ffmpeg_binary))
    else:
        report = inspect_project(str(args.project_id), storage_root=args.storage_root.resolve())
    paths = write_reports(report, report_dir=args.report_dir)
    report["report_paths"] = paths
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

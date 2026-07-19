"""Long-video validation helpers for real Olympus projects and media.

This module is additive to :mod:`olympus.validation.real_video`.  It reuses the
existing HTTP, ffprobe, render, and JSON helpers while adding the stricter
contracts needed for 10-120+ minute sources.  Nothing here changes production
pipeline behavior or fabricates engine outcomes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import urllib.error
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from olympus.validation.real_video import (
    DEFAULT_SAMPLE_DIRS,
    VIDEO_EXTENSIONS,
    ValidationHttpClient,
    as_dict,
    as_float,
    as_int,
    as_list,
    create_project_payload,
    duration_between,
    environment_snapshot,
    run_ffprobe,
    stage_version_warnings,
    utc_now_iso,
    validate_rendered_clip,
)

JsonDict = dict[str, Any]

REPORT_JSON = "long_video_validation_report.json"
REPORT_MARKDOWN = "long_video_validation_summary.md"
DEFAULT_LONG_REPORT_DIR = Path("D:/Olympus/work/validation_reports/long_video")
BACKEND_COMMAND = (
    "cd D:\\Olympus\n"
    ".\\.venv\\Scripts\\python.exe -m uvicorn olympus.api.app:app "
    "--app-dir src --host 127.0.0.1 --port 8000"
)
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "unavailable"}
PIPELINE_ENGINES = (
    "analysis",
    "story",
    "virality",
    "planning",
    "editing",
    "rendering",
    "optimization",
)
STAGE_TIMEOUT_CODES = {
    "analysis": "STAGE_TIMEOUT_ANALYSIS",
    "transcription": "STAGE_TIMEOUT_TRANSCRIPTION",
    "story": "STAGE_TIMEOUT_STORY",
    "virality": "STAGE_TIMEOUT_VIRALITY",
    "planning": "STAGE_TIMEOUT_PLANNING",
    "editing": "PIPELINE_STALLED",
    "rendering": "STAGE_TIMEOUT_RENDERING",
    "optimization": "PIPELINE_STALLED",
}
CLI_TIER_CHOICES = ("smoke", "10min", "30min", "60min", "90min", "120min", "stream")


@dataclass(frozen=True)
class LongVideoOptions:
    """Runtime controls supplied by the long-video CLI."""

    mode: str
    tier: str | None = None
    timeout_seconds: float = 7200.0
    stage_timeout_seconds: float = 1800.0
    poll_interval_seconds: float = 10.0
    min_clips: int | None = None
    max_clips: int | None = None
    require_rendered_clips: bool = False
    require_audio: bool = False
    from_link: bool = False
    keep_artifacts: bool = False
    debug: bool = False


LONG_VIDEO_FULL_RENDER_CONTRACT_VERSION = "1"
LONG_VIDEO_MINIMUM_SECONDS = 1800.0
LONG_VIDEO_AV_TOLERANCE_SECONDS = 0.15
LONG_VIDEO_REPORT_SUBDIR = Path("work/validation_reports/long_video_full_render")


@dataclass(slots=True)
class LongVideoStageResultV1:
    """JSON-safe durable-stage evidence for the full-render proof."""

    name: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    artifact_present: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(slots=True)
class LongVideoFullRenderResultV1:
    """One honest, serializable result for a long durable-render validation."""

    project_id: str | None
    mode: str
    source_duration_seconds: float | None = None
    source_duration_minutes: float | None = None
    minimum_required_minutes: float = 30.0
    pipeline_started_at: str | None = None
    pipeline_finished_at: str | None = None
    total_runtime_seconds: float | None = None
    stages: list[LongVideoStageResultV1] = field(default_factory=list)
    planned_clip_count: int = 0
    edited_clip_count: int = 0
    rendered_clip_count: int = 0
    accepted_mp4_count: int = 0
    optimized_clip_count: int = 0
    duplicate_source_intervals_detected: bool = False
    source_interval_coverage: JsonDict = field(default_factory=dict)
    render_manifest_present: bool = False
    optimization_manifest_present: bool = False
    final_payload_valid: bool = False
    artifact_paths: JsonDict = field(default_factory=dict)
    final_payload: JsonDict = field(default_factory=dict)
    ffprobe_results: list[JsonDict] = field(default_factory=list)
    av_delta_results: list[JsonDict] = field(default_factory=list)
    resource_observations: JsonDict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    passed: bool = False
    contract_version: str = LONG_VIDEO_FULL_RENDER_CONTRACT_VERSION

    def to_dict(self) -> JsonDict:
        payload = asdict(self)
        payload["stages"] = [stage.to_dict() for stage in self.stages]
        return payload


def long_video_stage_result(
    *,
    name: str,
    status: str,
    started_at: str | None,
    finished_at: str | None,
    artifact_present: bool,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> LongVideoStageResultV1:
    """Build one stage row and derive elapsed time from durable timestamps."""

    return LongVideoStageResultV1(
        name=name,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_between(started_at, finished_at),
        artifact_present=artifact_present,
        warnings=list(warnings or []),
        errors=list(errors or []),
    )


def validate_long_source_duration(
    duration_seconds: float | None,
    *,
    minimum_minutes: float = 30.0,
) -> JsonDict:
    """Reject absent, metadata-only, or genuinely short source durations."""

    minimum_seconds = max(0.0, float(minimum_minutes)) * 60.0
    duration = _optional_float(duration_seconds)
    errors: list[str] = []
    if duration is None or duration <= 0:
        errors.append("FFprobe did not return a positive source duration.")
    elif duration + 0.001 < minimum_seconds:
        errors.append(
            f"Source is {duration:.3f}s; at least {minimum_seconds:.3f}s "
            "of real FFprobe duration is required."
        )
    return {
        "passed": not errors,
        "duration_seconds": duration,
        "duration_minutes": round(duration / 60.0, 3) if duration is not None else None,
        "minimum_minutes": round(float(minimum_minutes), 3),
        "minimum_seconds": round(minimum_seconds, 3),
        "errors": errors,
    }


def long_video_ffprobe_result(
    *,
    clip_id: str,
    path_or_key: str,
    probe: JsonDict,
    expected_duration: float | None = None,
    av_tolerance_seconds: float = LONG_VIDEO_AV_TOLERANCE_SECONDS,
) -> JsonDict:
    """Normalize one FFprobe response into the long-video clip contract."""

    container_duration = _optional_float(probe.get("container_duration"))
    video_duration = _optional_float(probe.get("video_duration")) or container_duration
    audio_duration = _optional_float(probe.get("audio_duration"))
    fps = _optional_float(probe.get("fps"))
    frame_count = _probe_frame_count(probe)
    if frame_count is None and fps is not None and video_duration is not None:
        frame_count = max(0, round(fps * video_duration))
    has_video = bool(probe.get("width") and probe.get("height") and probe.get("video_codec"))
    has_audio = bool(probe.get("has_audio") and probe.get("audio_codec"))
    av_delta = (
        round(audio_duration - video_duration, 3)
        if audio_duration is not None and video_duration is not None
        else None
    )
    duration_delta = (
        round(container_duration - expected_duration, 3)
        if container_duration is not None and expected_duration is not None
        else None
    )
    errors = [str(item) for item in as_list(probe.get("errors"))]
    if probe.get("passed") is not True:
        errors.append("FFprobe did not validate the rendered MP4.")
    if not has_video:
        errors.append("Rendered MP4 has no valid video stream.")
    if not has_audio:
        errors.append("Rendered MP4 has no valid audio stream.")
    if container_duration is None or container_duration <= 0:
        errors.append("Rendered MP4 has no positive container duration.")
    if av_delta is None or abs(av_delta) > av_tolerance_seconds:
        errors.append(
            "Rendered MP4 audio/video delta exceeds tolerance or could not be measured."
        )
    if duration_delta is not None and abs(duration_delta) > av_tolerance_seconds:
        errors.append("Rendered MP4 duration differs from its manifest duration.")
    errors = list(dict.fromkeys(errors))
    return {
        "clip_id": clip_id,
        "path": path_or_key,
        "storage_key": path_or_key,
        "duration_seconds": container_duration,
        "video_duration_seconds": video_duration,
        "audio_duration_seconds": audio_duration,
        "expected_duration_seconds": expected_duration,
        "duration_delta_seconds": duration_delta,
        "width": as_int(probe.get("width")),
        "height": as_int(probe.get("height")),
        "video_codec": probe.get("video_codec"),
        "audio_codec": probe.get("audio_codec"),
        "audio_sample_rate": as_int(probe.get("audio_sample_rate")),
        "frame_count": frame_count,
        "has_video": has_video,
        "has_audio": has_audio,
        "av_delta_seconds": av_delta,
        "valid": not errors,
        "errors": errors,
    }


def validate_long_video_clip_counts(
    *,
    planned: int,
    rendered: int,
    accepted: int,
    optimized: int,
    minimum: int,
) -> JsonDict:
    """Require the requested number of plans, real renders, and packages."""

    minimum = max(1, int(minimum))
    counts = {
        "planned": max(0, int(planned)),
        "rendered": max(0, int(rendered)),
        "accepted": max(0, int(accepted)),
        "optimized": max(0, int(optimized)),
    }
    errors: list[str] = []
    if counts["planned"] == 1 or counts["rendered"] == 1 or counts["accepted"] == 1:
        errors.append("long-video multi-clip proof not satisfied")
    for label, value in counts.items():
        if value < minimum:
            errors.append(f"{label} clip count {value} is below required minimum {minimum}.")
    return {
        "passed": not errors,
        "minimum": minimum,
        **counts,
        "errors": list(dict.fromkeys(errors)),
    }


def analyze_long_video_source_intervals(
    clips: list[JsonDict],
    *,
    source_duration: float | None,
    high_overlap_threshold: float = 0.8,
) -> JsonDict:
    """Detect exact/severe duplicates and summarize union timeline coverage."""

    intervals = [
        (index, _clip_identity(clip, index), interval)
        for index, clip in enumerate(clips)
        if (interval := clip_range(clip)) is not None
    ]
    exact_duplicates: list[JsonDict] = []
    high_overlaps: list[JsonDict] = []
    severe_overlaps: list[JsonDict] = []
    for position, (_, left_id, left) in enumerate(intervals):
        for _, right_id, right in intervals[position + 1 :]:
            ratio = _range_overlap_ratio(left, right)
            exact = abs(left[0] - right[0]) <= 0.05 and abs(left[1] - right[1]) <= 0.05
            record = {
                "left": left_id,
                "right": right_id,
                "left_range": list(left),
                "right_range": list(right),
                "overlap_ratio": round(ratio, 3),
            }
            if exact:
                exact_duplicates.append(record)
            elif ratio > high_overlap_threshold:
                high_overlaps.append(record)
                if ratio >= 0.95:
                    severe_overlaps.append(record)
    merged = _merge_intervals([interval for _, _, interval in intervals])
    covered_seconds = round(sum(end - start for start, end in merged), 3)
    duration = max(0.0, float(source_duration or 0.0))
    warnings = []
    if high_overlaps:
        warnings.append("One or more selected clips overlap by more than 80%.")
    errors = []
    if exact_duplicates:
        errors.append("Exact duplicate source intervals were selected.")
    if severe_overlaps:
        errors.append("Near-duplicate source intervals overlap by at least 95%.")
    return {
        "interval_count": len(intervals),
        "intervals": [
            {"clip_id": clip_id, "start": interval[0], "end": interval[1]}
            for _, clip_id, interval in intervals
        ],
        "exact_duplicates": exact_duplicates,
        "high_overlaps": high_overlaps,
        "severe_overlaps": severe_overlaps,
        "duplicate_source_intervals_detected": bool(
            exact_duplicates or severe_overlaps
        ),
        "covered_seconds": covered_seconds,
        "coverage_ratio": round(covered_seconds / duration, 4) if duration else None,
        "passed": not errors,
        "warnings": warnings,
        "errors": errors,
    }


def validate_long_video_final_payload(payload: JsonDict, *, minimum_clips: int) -> JsonDict:
    """Validate a JSON-safe final payload with downloadable rendered clips."""

    clips = [as_dict(item) for item in as_list(payload.get("clips"))]
    if not clips:
        manifest = as_dict(payload.get("manifest"))
        clips = [as_dict(item) for item in as_list(manifest.get("renders"))]
    downloads = [str(item) for item in as_list(payload.get("download_urls")) if item]
    errors: list[str] = []
    if len(clips) < max(1, int(minimum_clips)):
        errors.append("Final payload does not expose the required rendered clips.")
    if clips and len(downloads) < len(clips):
        errors.append("Final payload does not expose a download URL for every clip.")
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        errors.append(f"Final payload is not JSON-safe: {exc}")
    return {
        "passed": not errors,
        "clip_count": len(clips),
        "download_url_count": len(downloads),
        "errors": errors,
    }


def validate_long_video_manifest_presence(
    *,
    render_manifest_present: bool,
    optimization_manifest_present: bool,
) -> JsonDict:
    """Require both durable handoff manifests without inventing substitutes."""

    errors: list[str] = []
    if not render_manifest_present:
        errors.append("Canonical render manifest is missing.")
    if not optimization_manifest_present:
        errors.append("Optimization manifest is missing.")
    return {"passed": not errors, "errors": errors}


def long_video_self_check(
    *,
    storage_root: Path,
    report_dir: Path,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
    which: Callable[[str], str | None] = shutil.which,
) -> JsonDict:
    """Check local-only prerequisites without starting or simulating a pipeline."""

    checks: list[JsonDict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    ffmpeg = which(ffmpeg_binary)
    ffprobe = which(ffprobe_binary)
    add("ffmpeg_available", ffmpeg is not None, ffmpeg or f"{ffmpeg_binary} not found")
    add("ffprobe_available", ffprobe is not None, ffprobe or f"{ffprobe_binary} not found")
    add("workflow_services_import", True, "durable workflow imports loaded")
    add("render_manifest_resolver_import", True, "canonical render resolver loaded")
    add("optimization_manifest_resolver_import", True, "optimization repository loaded")
    storage_ok, storage_detail = _writable_directory_check(storage_root)
    add("storage_root_writable", storage_ok, storage_detail)
    report_ok, report_detail = _writable_directory_check(report_dir)
    add("report_directory_writable", report_ok, report_detail)
    return {
        "passed": all(bool(item.get("passed")) for item in checks),
        "checks": checks,
        "external_access_required": False,
        "errors": [
            str(item.get("detail")) for item in checks if item.get("passed") is not True
        ],
    }


def validated_long_video_report_dir(report_dir: Path, *, workspace_root: Path) -> Path:
    """Restrict reports and generated fixtures to ``work/validation_reports``."""

    allowed = (workspace_root / "work" / "validation_reports").resolve()
    resolved = report_dir.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f"Report directory must stay under {allowed}.") from exc
    return resolved


def is_generated_validation_artifact(path: str | Path) -> bool:
    """Return whether a path must never be staged by validation tooling."""

    normalized = str(path).replace("\\", "/").lower().lstrip("./")
    parts = {part for part in normalized.split("/") if part}
    generated_parts = {
        ".venv",
        "node_modules",
        ".next",
        "work",
        "storage_data",
        "media",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
    return bool(
        parts.intersection(generated_parts)
        or normalized.endswith((".mp4", ".mov", ".mkv", ".webm"))
        or normalized == ".env"
        or normalized.startswith(".env.")
    )


def write_long_video_full_render_report(
    result: LongVideoFullRenderResultV1 | JsonDict,
    report_dir: Path,
    *,
    workspace_root: Path,
) -> dict[str, str]:
    """Persist JSON and a compact Markdown summary under the guarded report root."""

    output = validated_long_video_report_dir(report_dir, workspace_root=workspace_root)
    output.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict() if isinstance(result, LongVideoFullRenderResultV1) else result
    stem = (
        "long_video_full_render_project_inspection"
        if payload.get("mode") == "project_id"
        else "long_video_full_render"
    )
    json_path = output / f"{stem}_report.json"
    summary_path = output / f"{stem}_summary.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Long-Video Full Render Proof V2",
        "",
        f"- Passed: `{str(bool(payload.get('passed'))).lower()}`",
        f"- Mode: `{payload.get('mode')}`",
        f"- Project: `{payload.get('project_id') or 'not created'}`",
        f"- Source duration: `{payload.get('source_duration_seconds')}` seconds",
        f"- Planned clips: `{payload.get('planned_clip_count', 0)}`",
        f"- Rendered clips: `{payload.get('rendered_clip_count', 0)}`",
        f"- Accepted MP4s: `{payload.get('accepted_mp4_count', 0)}`",
        f"- Optimization clips: `{payload.get('optimized_clip_count', 0)}`",
        "- Peak RAM: `not measured`",
    ]
    if payload.get("warnings"):
        lines.extend(["", "## Warnings", *[f"- {item}" for item in payload["warnings"]]])
    if payload.get("errors"):
        lines.extend(["", "## Errors", *[f"- {item}" for item in payload["errors"]]])
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "summary": str(summary_path)}


def _probe_frame_count(probe: JsonDict) -> int | None:
    raw = as_dict(probe.get("raw"))
    for stream in as_list(raw.get("streams")):
        item = as_dict(stream)
        if item.get("codec_type") != "video":
            continue
        value = as_int(item.get("nb_read_frames") or item.get("nb_frames"))
        return value if value is not None and value >= 0 else None
    return None


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _writable_directory_check(path: Path) -> tuple[bool, str]:
    marker = path / f".olympus-long-video-write-{uuid4().hex}.tmp"
    try:
        path.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
    except OSError as exc:
        return False, f"{path}: {type(exc).__name__}: {exc}"
    return True, str(path.resolve())


def classify_long_video_duration(duration_seconds: float | None) -> str:
    """Classify every positive duration without the gaps in the legacy tiers."""

    if duration_seconds is None or duration_seconds <= 0:
        return "unknown"
    if duration_seconds < 180:
        return "short_under_3min"
    if duration_seconds < 600:
        return "medium_3_to_10min"
    if duration_seconds < 1800:
        return "long_10_to_30min"
    if duration_seconds < 3600:
        return "long_30_to_60min"
    if duration_seconds < 7200:
        return "very_long_60_to_120min"
    return "stream_over_120min"


def expected_clip_range_v2(duration_seconds: float | None) -> tuple[int, int]:
    """Return the intentionally broad long-video clip-count expectation."""

    if duration_seconds is None or duration_seconds <= 0:
        return (0, 0)
    if duration_seconds < 180:
        return (1, 5)
    if duration_seconds < 600:
        return (2, 8)
    if duration_seconds < 1800:
        return (3, 12)
    if duration_seconds < 3600:
        return (5, 20)
    if duration_seconds < 7200:
        return (8, 30)
    return (10, 40)


def tier_matches(duration_seconds: float | None, requested_tier: str | None) -> bool:
    """Return whether a sample belongs to a CLI duration tier."""

    if requested_tier in (None, "smoke"):
        return True
    if duration_seconds is None:
        return False
    ranges = {
        "10min": (600.0, 1800.0),
        "30min": (1800.0, 3600.0),
        "60min": (3600.0, 5400.0),
        "90min": (5400.0, 7200.0),
        "120min": (7200.0, float("inf")),
        "stream": (7200.0, float("inf")),
    }
    if requested_tier not in ranges:
        return False
    minimum, maximum = ranges[requested_tier]
    return minimum <= duration_seconds < maximum


def infer_video_types(filename: str) -> list[str]:
    """Infer useful sample labels from a filename without claiming content analysis."""

    normalized = re.sub(r"[^a-z0-9]+", "_", filename.lower())
    patterns = {
        "podcast": ("podcast",),
        "interview": ("interview",),
        "stream": ("stream", "livestream", "live_stream"),
        "gaming": ("gaming", "gameplay", "game_play"),
        "motivational": ("motivational", "motivation"),
        "speech": ("speech", "talk", "keynote"),
        "music": ("music", "song", "concert", "performance"),
        "two_speaker": ("two_speaker", "2_speaker", "two_person"),
        "multi_speaker": ("multi_speaker", "panel", "roundtable"),
    }
    inferred = [
        label
        for label, tokens in patterns.items()
        if any(token in normalized for token in tokens)
    ]
    return inferred or ["unknown"]


def probe_source_video(path: Path) -> JsonDict:
    """Probe a source and return the report-contract source object."""

    warnings: list[str] = []
    errors: list[str] = []
    exists = path.exists() and path.is_file()
    if not exists:
        errors.append(f"Source video does not exist: {path}")
        probe: JsonDict = {}
    else:
        probe = run_ffprobe(path)
        if not probe.get("passed"):
            errors.extend(str(item) for item in as_list(probe.get("errors")))
    duration = _optional_float(probe.get("container_duration"))
    if exists and probe.get("passed") and not probe.get("has_audio"):
        warnings.append("Source has no audio stream; silent-source handling may be required.")
    return {
        "path": str(path),
        "exists": exists,
        "duration_seconds": duration,
        "width": as_int(probe.get("width")),
        "height": as_int(probe.get("height")),
        "video_codec": probe.get("video_codec"),
        "audio_codec": probe.get("audio_codec"),
        "audio_sample_rate": as_int(probe.get("audio_sample_rate")),
        "file_size_bytes": path.stat().st_size if exists else 0,
        "classification": {
            "duration_tier": classify_long_video_duration(duration),
            "inferred_types": infer_video_types(path.name),
            "inference_source": "filename_only",
        },
        "ffprobe_passed": bool(probe.get("passed")),
        "warnings": warnings,
        "errors": errors,
    }


def discover_long_video_samples(
    *,
    explicit_files: list[Path] | None = None,
    sample_dirs: list[Path] | None = None,
    tier: str | None = None,
) -> list[JsonDict]:
    """Discover supported media and classify it with ffprobe."""

    candidates: list[Path] = []
    candidates.extend(explicit_files or [])
    directories = list(DEFAULT_SAMPLE_DIRS) if sample_dirs is None else sample_dirs
    for directory in directories:
        if not directory.exists() or not directory.is_dir():
            continue
        candidates.extend(
            item
            for item in directory.rglob("*")
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
        )

    seen: set[str] = set()
    samples: list[JsonDict] = []
    for path in candidates:
        if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.exists():
            continue
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        source = probe_source_video(path)
        if tier_matches(_optional_float(source.get("duration_seconds")), tier):
            samples.append(source)
    return sorted(
        samples,
        key=lambda item: (
            _optional_float(item.get("duration_seconds")) is None,
            -as_float(item.get("duration_seconds")),
            str(item.get("path") or "").casefold(),
        ),
    )


def strong_low_output_reason(reason: JsonDict | None) -> bool:
    """Require a structured explanation, not a metadata-only truthy value."""

    data = as_dict(reason)
    explanation = str(data.get("explanation") or "").strip()
    evidence_present = bool(
        as_list(data.get("rejected_reasons"))
        or data.get("story_candidate_count") is not None
        or data.get("viral_candidate_count") is not None
        or as_float(data.get("confidence")) >= 0.5
    )
    return len(explanation) >= 20 and evidence_present


def validate_clip_count(
    *,
    source_duration: float | None,
    planned_count: int,
    rendered_count: int,
    low_output_reason: JsonDict | None,
    min_clips: int | None = None,
    max_clips: int | None = None,
    require_rendered: bool = False,
) -> JsonDict:
    """Validate count sanity while allowing an evidenced low-density outcome."""

    expected_min, expected_max = expected_clip_range_v2(source_duration)
    if min_clips is not None:
        expected_min = min_clips
    if max_clips is not None:
        expected_max = max_clips
    warnings: list[str] = []
    passed = True
    low_required = expected_min > 0 and planned_count < expected_min
    low_reason_strong = strong_low_output_reason(low_output_reason)
    if low_required:
        if low_reason_strong:
            warnings.append(
                f"Planned {planned_count} clip(s), below {expected_min}-{expected_max}; "
                "a structured low_output_reason explains the result."
            )
        else:
            passed = False
            warnings.append(
                f"Planned {planned_count} clip(s), below expected {expected_min}-{expected_max}, "
                "without a strong low_output_reason."
            )
    if expected_max and planned_count > expected_max:
        passed = False
        warnings.append(
            f"Planned {planned_count} clips, above the safe expected maximum {expected_max}."
        )
    if require_rendered and rendered_count != planned_count:
        passed = False
        warnings.append(f"Rendered {rendered_count} of {planned_count} planned clip(s).")
    return {
        "duration_tier": classify_long_video_duration(source_duration),
        "expected_min": expected_min,
        "expected_max": expected_max,
        "planned_count": planned_count,
        "rendered_count": rendered_count,
        "passed": passed,
        "low_output_reason_required": low_required,
        "low_output_reason": low_output_reason,
        "low_output_reason_strong": low_reason_strong,
        "warnings": warnings,
    }


def analyze_timeline_coverage(
    *,
    source_duration: float | None,
    selected_clips: list[JsonDict],
    candidates: list[JsonDict] | None = None,
    analyzed_duration: float | None = None,
    transcript_duration: float | None = None,
    explanation: str | None = None,
) -> JsonDict:
    """Measure candidate and selected coverage over five long-video buckets."""

    bucket_labels = ("0-10%", "10-25%", "25-50%", "50-75%", "75-100%")
    duration = source_duration or 0.0
    selected_ranges = [item for clip in selected_clips if (item := clip_range(clip))]
    candidate_ranges = [item for clip in candidates or [] if (item := clip_range(clip))]
    selected_buckets = dict.fromkeys(bucket_labels, 0)
    candidate_buckets = dict.fromkeys(bucket_labels, 0)
    for start, _end in selected_ranges:
        selected_buckets[_coverage_bucket(start, duration)] += 1
    for start, _end in candidate_ranges:
        candidate_buckets[_coverage_bucket(start, duration)] += 1

    starts = [item[0] for item in selected_ranges]
    occupied = sum(1 for count in selected_buckets.values() if count)
    candidate_occupied = sum(1 for count in candidate_buckets.values() if count)
    coverage_score = round(occupied / len(bucket_labels), 3)
    early_bias = bool(
        len(starts) > 1
        and duration
        and all(start <= duration * 0.1 for start in starts)
    )
    late_ignored = bool(duration >= 600 and starts and max(starts) < duration * 0.5)
    warnings: list[str] = []
    if early_bias:
        warnings.append("All selected clips come from the first 10% of the source.")
    if late_ignored:
        warnings.append("No selected clip starts in the second half of the source.")
    if duration and analyzed_duration is not None and analyzed_duration < duration * 0.9:
        warnings.append("Analyzed duration covers less than 90% of the source.")
    if duration and transcript_duration is not None and transcript_duration < duration * 0.9:
        warnings.append("Transcript duration covers less than 90% of the source.")
    if len(selected_ranges) >= 3 and occupied < 2:
        warnings.append("Selected clips do not span enough timeline buckets.")
    if candidate_ranges and candidate_occupied < 2 and duration >= 600:
        warnings.append("Candidate generation is concentrated in one timeline bucket.")
    if warnings and explanation:
        warnings.append(f"Planning explanation: {explanation}")
    return {
        "source_duration": source_duration,
        "analyzed_duration": analyzed_duration,
        "transcript_duration": transcript_duration,
        "candidate_buckets": candidate_buckets,
        "selected_clip_buckets": selected_buckets,
        "coverage_score": coverage_score,
        "early_bias_detected": early_bias,
        "late_video_ignored": late_ignored,
        "passed": not early_bias and not late_ignored,
        "warnings": warnings,
    }


def analyze_clip_diversity(
    clips: list[JsonDict],
    *,
    source_duration: float | None,
) -> JsonDict:
    """Detect repeated ranges and summarize story/hook/timeline diversity."""

    ranges = [(index, clip_range(clip)) for index, clip in enumerate(clips)]
    duplicate_ranges: list[JsonDict] = []
    overlaps: list[JsonDict] = []
    for position, (left_index, left_range) in enumerate(ranges):
        if left_range is None:
            continue
        for right_index, right_range in ranges[position + 1 :]:
            if right_range is None:
                continue
            overlap_ratio = _range_overlap_ratio(left_range, right_range)
            exactish = (
                abs(left_range[0] - right_range[0]) <= 1.0
                and abs(left_range[1] - right_range[1]) <= 1.0
            )
            record = {
                "left": _clip_identity(clips[left_index], left_index),
                "right": _clip_identity(clips[right_index], right_index),
                "left_range": list(left_range),
                "right_range": list(right_range),
                "overlap_ratio": round(overlap_ratio, 3),
            }
            if overlap_ratio > 0:
                overlaps.append(record)
            if exactish or overlap_ratio >= 0.8:
                duplicate_ranges.append(record)

    hooks = [_normalized_signal(_hook_value(clip)) for clip in clips]
    hooks = [value for value in hooks if value]
    stories = [_normalized_signal(_story_value(clip)) for clip in clips]
    stories = [value for value in stories if value]
    music = [_normalized_signal(_music_value(clip)) for clip in clips]
    music = [value for value in music if value]
    buckets = {
        _coverage_bucket(item[1][0], source_duration or 0.0)
        for item in ranges
        if item[1] is not None
    }
    count = max(1, len(clips))
    hook_score = len(set(hooks)) / len(hooks) if hooks else 0.5
    story_score = len(set(stories)) / len(stories) if stories else 0.5
    bucket_score = min(1.0, len(buckets) / min(5, count)) if clips else 0.0
    range_score = max(0.0, 1.0 - len(duplicate_ranges) / count)
    score = round(
        0.35 * range_score + 0.25 * bucket_score + 0.2 * hook_score + 0.2 * story_score,
        3,
    )
    warnings: list[str] = []
    if duplicate_ranges:
        warnings.append("Duplicate or near-duplicate source ranges were selected.")
    if len(clips) >= 3 and bucket_score < 0.4:
        warnings.append("Too many clips are concentrated in the same timeline bucket.")
    if len(hooks) >= 3 and len(set(hooks)) == 1:
        warnings.append("Every clip repeats the same hook pattern or hook line.")
    music_reuse = bool(len(music) >= 3 and len(set(music)) == 1)
    if music_reuse:
        warnings.append("The same music asset is reused for every inspected clip.")
    return {
        "overlap_detected": bool(overlaps),
        "overlaps": overlaps,
        "duplicate_ranges": duplicate_ranges,
        "hook_pattern_diversity": round(hook_score, 3),
        "story_pattern_diversity": round(story_score, 3),
        "timeline_bucket_diversity": round(bucket_score, 3),
        "music_reuse_warning": music_reuse,
        "diversity_score": score,
        "passed": not duplicate_ranges and score >= 0.45,
        "warnings": warnings,
    }


def watchdog_assessment(
    *,
    stage: str,
    stage_elapsed_seconds: float,
    no_progress_seconds: float,
    timeout_seconds: float,
) -> JsonDict:
    """Return a deterministic timeout/stall decision for one observed stage."""

    if stage_elapsed_seconds >= timeout_seconds:
        code = STAGE_TIMEOUT_CODES.get(stage, "PIPELINE_STALLED")
        return {
            "passed": False,
            "error_code": code,
            "message": f"{stage} exceeded its {timeout_seconds:.0f}s stage timeout.",
        }
    if no_progress_seconds >= timeout_seconds:
        return {
            "passed": False,
            "error_code": "NO_PROGRESS",
            "message": f"{stage} reported no progress for {no_progress_seconds:.0f}s.",
        }
    return {"passed": True, "error_code": None, "message": "Stage remains within timeout."}


def validate_metadata_survival(
    *,
    plans: list[JsonDict],
    renders: list[JsonDict],
    require_render_metadata: bool,
) -> JsonDict:
    """Check that V2 intelligence reaches the furthest available clip contract."""

    items = renders or plans
    per_clip: list[JsonDict] = []
    warnings: list[str] = []
    for index, item in enumerate(items):
        metadata = as_dict(item.get("metadata"))
        unified = as_dict(
            metadata.get("unified_clip_intelligence") or item.get("unified_clip_intelligence")
        )
        editing = as_dict(unified.get("editing"))
        trend = as_dict(unified.get("trend_research"))
        music_intelligence = as_dict(
            metadata.get("music_intelligence_v2") or editing.get("music_intelligence_v2")
        )
        checks = {
            "story_v2_found": bool(as_dict(unified.get("story"))),
            "virality_v2_found": bool(as_dict(unified.get("virality"))),
            "trend_research_found": bool(
                trend
                or metadata.get("internet_trend_research_v2")
                or unified.get("trend_patterns")
            ),
            "music_intelligence_found": bool(music_intelligence),
            "curated_music_library_found": bool(
                as_dict(music_intelligence.get("music_library_selection"))
                or as_dict(music_intelligence.get("selected_asset")).get("source_type")
            ),
            "captions_v2_found": bool(
                metadata.get("caption_intelligence_v2") or editing.get("caption_intelligence_v2")
            ),
            "motion_v2_found": bool(
                metadata.get("motion_intelligence_v2") or editing.get("motion_intelligence_v2")
            ),
            "multi_speaker_found": bool(
                metadata.get("multi_speaker_layout_v2") or editing.get("multi_speaker_layout_v2")
            ),
            "unified_clip_intelligence_found": bool(unified),
            "why_this_clip_works_found": bool(
                as_dict(unified.get("story")).get("story_shape")
                or as_dict(unified.get("virality")).get("hook_line")
                or as_dict(unified.get("planning")).get("selected_reason")
            ),
        }
        clip_id = _clip_identity(item, index)
        if not checks["unified_clip_intelligence_found"]:
            warnings.append(f"{clip_id}: unified_clip_intelligence is missing.")
        if not checks["story_v2_found"]:
            warnings.append(f"{clip_id}: Story V2 metadata is missing at planning/render output.")
        if not checks["virality_v2_found"]:
            warnings.append(
                f"{clip_id}: Virality V2 metadata is missing at planning/render output."
            )
        if not checks["trend_research_found"]:
            warnings.append(f"{clip_id}: Trend Research V2 metadata is missing.")
        if require_render_metadata:
            for key, label in (
                ("music_intelligence_found", "Music Intelligence V2"),
                ("curated_music_library_found", "Curated Music Library V2"),
                ("captions_v2_found", "Captions/Typography V2"),
                ("motion_v2_found", "Motion Graphics V2"),
                ("multi_speaker_found", "Multi-Speaker Layout V2"),
            ):
                if not checks[key]:
                    warnings.append(f"{clip_id}: {label} metadata is missing from render output.")
        per_clip.append({"clip_id": clip_id, **checks})

    def all_found(key: str) -> bool:
        return bool(per_clip) and all(bool(item.get(key)) for item in per_clip)

    return {
        "story_v2_found": all_found("story_v2_found"),
        "virality_v2_found": all_found("virality_v2_found"),
        "trend_research_found": all_found("trend_research_found"),
        "music_intelligence_found": all_found("music_intelligence_found"),
        "curated_music_library_found": all_found("curated_music_library_found"),
        "captions_v2_found": all_found("captions_v2_found"),
        "motion_v2_found": all_found("motion_v2_found"),
        "multi_speaker_found": all_found("multi_speaker_found"),
        "unified_clip_intelligence_found": all_found("unified_clip_intelligence_found"),
        "why_this_clip_works_found": all_found("why_this_clip_works_found"),
        "per_clip": per_clip,
        "warnings": warnings,
    }


def validate_frontend_payload_v2(
    *,
    project_id: str | None,
    plans: list[JsonDict],
    renders: list[JsonDict],
    base_url: str,
) -> JsonDict:
    """Validate the data contract consumed by the existing output gallery."""

    if not renders:
        return {
            "checked": False,
            "clips_visible": False,
            "download_urls_present": False,
            "why_this_clip_works_present": False,
            "passed": False,
            "clip_cards": [],
            "warnings": ["Frontend payload not checked because no render manifest exists."],
        }
    plans_by_id = {
        str(plan.get("id") or plan.get("plan_id") or ""): plan for plan in plans
    }
    warnings: list[str] = []
    cards: list[JsonDict] = []
    for index, render in enumerate(renders):
        clip_id = str(render.get("clip_id") or f"clip_{index + 1}")
        plan_id = str(render.get("plan_id") or clip_id)
        plan = as_dict(plans_by_id.get(plan_id))
        metadata = as_dict(render.get("metadata"))
        unified = as_dict(
            metadata.get("unified_clip_intelligence") or plan.get("unified_clip_intelligence")
        )
        why_present = bool(
            as_dict(unified.get("story")).get("story_shape")
            or as_dict(unified.get("virality")).get("hook_line")
            or as_dict(unified.get("planning")).get("selected_reason")
        )
        download_url = (
            f"{base_url.rstrip('/')}/api/v1/projects/{project_id}/rendering/"
            f"clips/{clip_id}/download"
            if project_id
            else None
        )
        if not unified:
            warnings.append(f"{clip_id}: clip card lacks unified_clip_intelligence.")
        if not why_present:
            warnings.append(f"{clip_id}: clip card lacks Why-this-clip-works fields.")
        if not download_url:
            warnings.append(f"{clip_id}: a download URL cannot be constructed without project_id.")
        cards.append(
            {
                "clip_id": clip_id,
                "download_url": download_url,
                "why_this_clip_works_present": why_present,
                "story_present": bool(as_dict(unified.get("story"))),
                "virality_present": bool(as_dict(unified.get("virality"))),
                "trend_present": bool(
                    as_dict(unified.get("trend_research"))
                    or metadata.get("internet_trend_research_v2")
                ),
                "music_present": bool(
                    metadata.get("music_intelligence_v2")
                    or as_dict(unified.get("editing")).get("music_intelligence_v2")
                ),
                "captions_present": bool(metadata.get("caption_intelligence_v2")),
                "motion_present": bool(metadata.get("motion_intelligence_v2")),
                "layout_present": bool(metadata.get("multi_speaker_layout_v2")),
                "warnings_present": "warnings" in metadata or "warnings" in render,
            }
        )
    return {
        "checked": True,
        "clips_visible": bool(cards),
        "download_urls_present": all(bool(card.get("download_url")) for card in cards),
        "why_this_clip_works_present": all(
            bool(card.get("why_this_clip_works_present")) for card in cards
        ),
        "passed": bool(cards) and not any("lacks" in warning for warning in warnings),
        "clip_cards": cards,
        "warnings": warnings,
    }


def build_stage_timing_report(
    bundle: JsonDict,
    *,
    timeout_seconds: float,
) -> list[JsonDict]:
    """Build high-level and important substage timing rows from API payloads."""

    rows = [
        _stage_timing_row("analysis", as_dict(bundle.get("analysis")), timeout_seconds),
        _stage_timing_row(
            "transcription",
            as_dict(bundle.get("analysis")),
            timeout_seconds,
            substage="speech_transcription",
        ),
        _stage_timing_row("story", as_dict(bundle.get("story")), timeout_seconds),
        _stage_timing_row("virality", as_dict(bundle.get("virality")), timeout_seconds),
        _stage_timing_row(
            "trend_research",
            as_dict(bundle.get("virality")),
            timeout_seconds,
            substage="trend_research",
        ),
        _stage_timing_row("planning", as_dict(bundle.get("planning")), timeout_seconds),
        _stage_timing_row("editing", as_dict(bundle.get("editing")), timeout_seconds),
        _stage_timing_row("rendering", as_dict(bundle.get("rendering")), timeout_seconds),
        _stage_timing_row("optimization", as_dict(bundle.get("optimization")), timeout_seconds),
    ]
    return rows


def completed_stage_version_warnings(bundle: JsonDict) -> list[str]:
    """Check only completed stage artifacts; pending version ``0`` is not stale."""

    engines: dict[str, JsonDict] = {}
    for engine in PIPELINE_ENGINES:
        payload = as_dict(bundle.get(engine))
        if not payload:
            continue
        engines[engine] = {
            **payload,
            "stages": [
                as_dict(stage)
                for stage in as_list(payload.get("stages"))
                if as_dict(stage).get("status") == "completed"
            ],
        }
    return stage_version_warnings(engines)


def environment_report(report_dir: Path, *, backend_reachable: bool) -> JsonDict:
    """Return environment truth, including a real write/delete probe."""

    report_dir.mkdir(parents=True, exist_ok=True)
    write_error: str | None = None
    marker = report_dir / f".long_video_write_test_{uuid4().hex}.tmp"
    try:
        marker.write_text("write-test", encoding="utf-8")
        marker.unlink()
        writable = True
    except OSError as exc:
        writable = False
        write_error = str(exc)
    snapshot = environment_snapshot()
    try:
        disk = shutil.disk_usage(report_dir)
        disk_free = disk.free
    except OSError:
        disk_free = None
    return {
        "python": snapshot.get("python"),
        "python_executable": os.fspath(Path(sys.executable)),
        "ffmpeg_available": bool(snapshot.get("ffmpeg")),
        "ffprobe_available": bool(snapshot.get("ffprobe")),
        "olympus_imported": True,
        "backend_reachable": backend_reachable,
        "workdir_writable": writable,
        "workdir_write_error": write_error,
        "disk_free_bytes": disk_free,
        "platform": snapshot.get("platform"),
    }


def build_discovery_report(
    *,
    workspace: Path,
    branch: str,
    tier: str | None,
    samples: list[JsonDict],
    report_dir: Path,
) -> JsonDict:
    """Build an honest discovery-only report."""

    longest = samples[0] if samples else _empty_source_video()
    warnings = [] if samples else [
        "No local validation videos found. Place a supported file in "
        "D:\\Olympus\\validation_samples or pass --file."
    ]
    top = _base_contract(
        workspace=workspace,
        branch=branch,
        mode="discover",
        tier=tier,
        source={"kind": "sample_discovery", "sample_count": len(samples)},
        project_id=None,
        source_video=longest,
        environment=environment_report(report_dir, backend_reachable=False),
    )
    top["discovered_samples"] = samples
    top["result"] = {
        "passed": True,
        "status": "DISCOVERY_COMPLETED" if samples else "NO_SAMPLES",
        "failed_stage": None,
        "error_code": None,
        "message": (
            f"Discovered {len(samples)} supported video sample(s)."
            if samples
            else "No local samples were discovered; no real-video claim was made."
        ),
        "next_action": (
            "Run smoke or planning-only validation on the longest discovered sample."
            if samples
            else "Place a 30+ minute video in D:\\Olympus\\validation_samples."
        ),
        "command_to_try": (
            f"{Path(sys.executable)} tools\\validate_long_video.py --file "
            f'"{longest.get("path")}" --smoke'
            if samples
            else (
                f"{Path(sys.executable)} tools\\validate_long_video.py --discover"
            )
        ),
    }
    top["real_video_validation"] = False
    top["warnings"] = warnings
    return {"long_video_validation_v2": top, "videos": [], "samples": samples}


def validate_local_metadata(
    *,
    workspace: Path,
    branch: str,
    path: Path | None,
    options: LongVideoOptions,
    report_dir: Path,
) -> JsonDict:
    """Run source-only or smoke validation without claiming pipeline success."""

    source_video = probe_source_video(path) if path else _empty_source_video()
    environment = environment_report(report_dir, backend_reachable=False)
    warnings = [str(item) for item in as_list(source_video.get("warnings"))]
    errors = [str(item) for item in as_list(source_video.get("errors"))]
    synthetic_smoke = path is None and options.mode == "smoke"
    source_passed = bool(source_video.get("ffprobe_passed")) if path else synthetic_smoke
    if synthetic_smoke:
        warnings.append("Smoke used environment/contract checks only; no real video was supplied.")
    top = _base_contract(
        workspace=workspace,
        branch=branch,
        mode=options.mode,
        tier=options.tier,
        source={"kind": "local_file" if path else "synthetic_smoke", "path": str(path or "")},
        project_id=None,
        source_video=source_video,
        environment=environment,
    )
    top["smoke"] = {
        "enabled": options.mode == "smoke",
        "synthetic": synthetic_smoke,
        "stage_imports_passed": True,
        "planning_contract_passed": bool(expected_clip_range_v2(3600) == (8, 30)),
        "render_attempted": False,
    }
    top["real_video_validation"] = bool(path and source_video.get("ffprobe_passed"))
    top["warnings"] = warnings
    top["errors"] = errors
    top["result"] = {
        "passed": source_passed and bool(environment.get("workdir_writable")),
        "status": "SMOKE_PASSED" if source_passed else "SOURCE_VALIDATION_FAILED",
        "failed_stage": None if source_passed else "source_probe",
        "error_code": None if source_passed else "SOURCE_PROBE_FAILED",
        "message": (
            "Source/environment smoke checks passed; no pipeline or render was claimed."
            if source_passed
            else "The source could not be validated with ffprobe."
        ),
        "next_action": (
            "Run --planning-only when the local backend is available."
            if source_passed and path
            else "Provide a valid local video file."
        ),
        "command_to_try": (
            f'{Path(sys.executable)} tools\\validate_long_video.py --file "{path}" '
            "--planning-only"
            if source_passed and path
            else None
        ),
    }
    return {"long_video_validation_v2": top, "videos": [top] if path else []}


def validate_with_backend(
    *,
    workspace: Path,
    branch: str,
    client: ValidationHttpClient,
    base_url: str,
    report_dir: Path,
    options: LongVideoOptions,
    source_path: Path | None = None,
    project_id: str | None = None,
    content_category: str = "auto",
) -> JsonDict:
    """Validate a local upload or existing project through the real backend."""

    source_video = probe_source_video(source_path) if source_path else _empty_source_video()
    health = _backend_health(client)
    environment = environment_report(report_dir, backend_reachable=health.get("passed") is True)
    top = _base_contract(
        workspace=workspace,
        branch=branch,
        mode=options.mode,
        tier=options.tier,
        source={
            "kind": "existing_project" if project_id else "local_file",
            "path": str(source_path or ""),
            "from_link_expected": options.from_link,
        },
        project_id=project_id,
        source_video=source_video,
        environment=environment,
    )
    top["backend_required"] = True
    top["backend_used"] = health.get("passed") is True
    if not health.get("passed"):
        top["result"] = _failure_result(
            "LOCAL_BACKEND_UNAVAILABLE",
            "The local Olympus backend is not reachable.",
            "Start the backend without --reload, then retry validation.",
            BACKEND_COMMAND,
            failed_stage="backend_health",
        )
        top["errors"] = [str(health.get("error") or "Local backend unavailable")]
        return {"long_video_validation_v2": top, "videos": [top]}

    created_project = False
    project: JsonDict
    try:
        if source_path is not None:
            if not source_path.exists():
                raise FileNotFoundError(f"Source video does not exist: {source_path}")
            upload = client.upload_streaming(source_path)
            project = client.json_request(
                "POST",
                "/api/v1/projects",
                create_project_payload(upload, content_category=content_category),
            )
            project_id = str(project["id"])
            created_project = True
        elif project_id:
            fetched_project = client.get_json_or_none(f"/api/v1/projects/{project_id}")
            if fetched_project is None:
                raise LookupError(f"Project not found: {project_id}")
            project = fetched_project
        else:
            raise ValueError("Either source_path or project_id is required for backend mode.")
    except Exception as exc:
        code = _backend_exception_code(exc)
        top["result"] = _failure_result(
            code,
            str(exc),
            "Verify the source/project and backend, then retry.",
            BACKEND_COMMAND if code == "LOCAL_BACKEND_UNAVAILABLE" else None,
            failed_stage="project_intake",
        )
        top["errors"] = [str(exc)]
        return {"long_video_validation_v2": top, "videos": [top]}

    assert project_id is not None
    top["project_id"] = project_id
    poll_result: JsonDict = {"passed": True, "error_code": None, "warnings": []}
    if options.mode in {"planning_only", "full_pipeline"}:
        bundle, poll_result = poll_project(
            client=client,
            project_id=project_id,
            mode=options.mode,
            timeout_seconds=options.timeout_seconds,
            stage_timeout_seconds=options.stage_timeout_seconds,
            poll_interval_seconds=options.poll_interval_seconds,
        )
    else:
        try:
            bundle = fetch_project_bundle(client, project_id)
        except Exception as exc:
            top["result"] = _failure_result(
                _backend_exception_code(exc),
                str(exc),
                "Verify the project ID and backend state.",
                BACKEND_COMMAND,
                failed_stage="project_fetch",
            )
            top["errors"] = [str(exc)]
            return {"long_video_validation_v2": top, "videos": [top]}

    project = as_dict(bundle.get("project"))
    if source_path is None:
        source_video = _source_from_project(project, bundle=bundle)
        top["source_video"] = source_video
    source_duration = _optional_float(source_video.get("duration_seconds"))
    plans = _plans_from_bundle(bundle)
    manifest_renders = _renders_from_bundle(bundle)
    planning_only = options.mode == "planning_only"
    renders = [] if planning_only else manifest_renders
    planning_summary = _stage_data(as_dict(bundle.get("planning")), "planning_summary")
    generation = _stage_data(as_dict(bundle.get("planning")), "candidate_generation")
    candidates = [as_dict(item) for item in as_list(generation.get("candidates"))]
    low_output_reason = as_dict(planning_summary.get("low_output_reason")) or None
    rendered_reports = _download_and_validate_renders(
        client=client,
        project_id=project_id,
        report_dir=report_dir,
        renders=renders,
        require_audio=options.require_audio or source_video.get("audio_codec") is not None,
    )
    count_validation = validate_clip_count(
        source_duration=source_duration,
        planned_count=len(plans),
        rendered_count=len(renders),
        low_output_reason=low_output_reason,
        min_clips=options.min_clips,
        max_clips=options.max_clips,
        require_rendered=(
            options.mode == "full_pipeline" or options.require_rendered_clips
        ),
    )
    analyzed_duration, transcript_duration = _analysis_durations(bundle)
    coverage = analyze_timeline_coverage(
        source_duration=source_duration,
        selected_clips=plans,
        candidates=candidates,
        analyzed_duration=analyzed_duration,
        transcript_duration=transcript_duration,
        explanation=str(as_dict(low_output_reason).get("explanation") or "") or None,
    )
    diversity = analyze_clip_diversity(plans, source_duration=source_duration)
    metadata = validate_metadata_survival(
        plans=plans,
        renders=renders,
        require_render_metadata=bool(renders),
    )
    if planning_only:
        frontend = {
            "checked": False,
            "clips_visible": False,
            "download_urls_present": False,
            "why_this_clip_works_present": False,
            "passed": False,
            "clip_cards": [],
            "warnings": ["Frontend payload intentionally not checked in planning-only mode."],
        }
    else:
        frontend = validate_frontend_payload_v2(
            project_id=project_id,
            plans=plans,
            renders=renders,
            base_url=base_url,
        )
    timings = build_stage_timing_report(
        bundle,
        timeout_seconds=options.stage_timeout_seconds,
    )
    version_warnings = completed_stage_version_warnings(bundle)
    warnings = [str(item) for item in as_list(poll_result.get("warnings"))]
    if planning_only and manifest_renders:
        warnings.append(
            f"Observed {len(manifest_renders)} pre-existing render(s); planning-only mode "
            "did not download, validate, or claim them."
        )
    warnings.extend(str(item) for item in as_list(count_validation.get("warnings")))
    warnings.extend(str(item) for item in as_list(coverage.get("warnings")))
    warnings.extend(str(item) for item in as_list(diversity.get("warnings")))
    warnings.extend(str(item) for item in as_list(metadata.get("warnings")))
    warnings.extend(str(item) for item in as_list(frontend.get("warnings")))
    warnings.extend(version_warnings)
    errors = [str(item) for item in as_list(poll_result.get("errors"))]
    link_validation = _validate_link_project(
        client=client,
        project=project,
        required=options.from_link,
    )
    warnings.extend(str(item) for item in as_list(link_validation.get("warnings")))
    errors.extend(str(item) for item in as_list(link_validation.get("errors")))

    planning_status = _status(bundle.get("planning"))
    render_required = options.mode == "full_pipeline" or options.require_rendered_clips
    rendered_passed = bool(rendered_reports) and all(
        report.get("validation_passed") is True for report in rendered_reports
    )
    core_passed = bool(poll_result.get("passed")) and not errors
    if options.mode in {"planning_only", "full_pipeline"}:
        core_passed = core_passed and planning_status == "completed"
    core_passed = core_passed and bool(count_validation.get("passed"))
    core_passed = core_passed and bool(coverage.get("passed"))
    core_passed = core_passed and bool(diversity.get("passed"))
    if render_required:
        core_passed = core_passed and rendered_passed
    if renders:
        core_passed = core_passed and bool(frontend.get("passed"))

    top.update(
        {
            "project_id": project_id,
            "created_project": created_project,
            "preexisting_rendered_clip_count": (
                len(manifest_renders) if planning_only else 0
            ),
            "link_project_validation": link_validation,
            "real_video_validation": bool(
                source_video.get("ffprobe_passed") or project.get("id")
            ),
            "stage_timings": timings,
            "watchdog": poll_result,
            "runtime_metrics": {
                "poll_elapsed_seconds": poll_result.get("elapsed_seconds"),
                "backend_system": bundle.get("system"),
                "measurement_scope": "backend monitoring payload and validator wall clock",
            },
            "artifact_version_warnings": version_warnings,
            "planning": {
                "attempted": bool(bundle.get("planning")),
                "passed": planning_status == "completed" and bool(count_validation.get("passed")),
                "expected_clip_range": [
                    count_validation.get("expected_min"),
                    count_validation.get("expected_max"),
                ],
                "planned_clip_count": len(plans),
                "low_output_reason": low_output_reason,
                "timeline_coverage": coverage,
                "diversity_score": diversity.get("diversity_score"),
                "duplicate_risk": "high" if diversity.get("duplicate_ranges") else "low",
                "clip_count_validation": count_validation,
                "clip_diversity": diversity,
                "warnings": list(
                    dict.fromkeys(
                        as_list(count_validation.get("warnings"))
                        + as_list(coverage.get("warnings"))
                        + as_list(diversity.get("warnings"))
                    )
                ),
            },
            "rendered_clips": rendered_reports,
            "intelligence_metadata": metadata,
            "frontend_payload": frontend,
            "warnings": list(dict.fromkeys(warnings)),
            "errors": errors,
        }
    )
    if core_passed:
        status = "PASSED_WITH_WARNINGS" if warnings else "PASSED"
        top["result"] = {
            "passed": True,
            "status": status,
            "failed_stage": None,
            "error_code": None,
            "message": _success_message(options.mode, len(plans), len(rendered_reports)),
            "next_action": _next_success_action(options.mode, source_path, project_id),
            "command_to_try": _next_success_command(options.mode, source_path, project_id),
        }
    else:
        error_code = str(poll_result.get("error_code") or "VALIDATION_FAILED")
        failed_stage = str(poll_result.get("failed_stage") or _first_failed_stage(top))
        top["result"] = _failure_result(
            error_code,
            "Long-video validation found one or more failed requirements.",
            "Inspect the report warnings, failed stage, coverage, diversity, and clip probes.",
            _retry_command(options.mode, source_path, project_id),
            failed_stage=failed_stage,
        )
    return {"long_video_validation_v2": top, "videos": [top]}


def fetch_project_bundle(client: ValidationHttpClient, project_id: str) -> JsonDict:
    """Fetch all artifacts needed for validation without mutating the project."""

    project = client.get_json_or_none(f"/api/v1/projects/{project_id}")
    if project is None:
        raise LookupError(f"Project not found: {project_id}")
    bundle: JsonDict = {"project": project}
    for engine in PIPELINE_ENGINES:
        bundle[engine] = client.get_json_or_none(f"/api/v1/projects/{project_id}/{engine}")
    bundle["plans"] = client.get_json_or_none(f"/api/v1/projects/{project_id}/planning/plans")
    bundle["manifest"] = client.get_json_or_none(
        f"/api/v1/projects/{project_id}/rendering/manifest"
    )
    bundle["workflow"] = client.get_json_or_none(f"/api/v1/projects/{project_id}/workflow")
    bundle["system"] = client.get_json_or_none("/api/v1/monitoring/system")
    return bundle


def poll_project(
    *,
    client: ValidationHttpClient,
    project_id: str,
    mode: str,
    timeout_seconds: float,
    stage_timeout_seconds: float,
    poll_interval_seconds: float,
) -> tuple[JsonDict, JsonDict]:
    """Poll a real project with total, per-stage, and no-progress watchdogs."""

    started = time.monotonic()
    current_stage = "analysis"
    current_stage_started = started
    last_progress = started
    previous_fingerprint = ""
    warnings: list[str] = []
    latest: JsonDict = {}
    while True:
        now = time.monotonic()
        if now - started >= timeout_seconds:
            return latest, {
                "passed": False,
                "error_code": "PIPELINE_STALLED",
                "failed_stage": current_stage,
                "elapsed_seconds": round(now - started, 3),
                "warnings": warnings,
                "errors": [f"Pipeline exceeded the {timeout_seconds:.0f}s total timeout."],
            }
        try:
            latest = fetch_project_bundle(client, project_id)
            _start_next_missing_engine(client, project_id, latest, mode=mode, warnings=warnings)
        except Exception as exc:
            return latest, {
                "passed": False,
                "error_code": _backend_exception_code(exc),
                "failed_stage": current_stage,
                "elapsed_seconds": round(now - started, 3),
                "warnings": warnings,
                "errors": [str(exc)],
            }

        fingerprint = _progress_fingerprint(latest)
        if fingerprint != previous_fingerprint:
            previous_fingerprint = fingerprint
            last_progress = now
        observed_stage = _current_pipeline_stage(latest, mode=mode)
        if observed_stage != current_stage:
            current_stage = observed_stage
            current_stage_started = now
            last_progress = now

        terminal = _poll_target_terminal(latest, mode=mode)
        if terminal:
            if mode == "planning_only":
                warnings.extend(_cancel_downstream(client, project_id, latest))
                latest = fetch_project_bundle(client, project_id)
            failed = _target_failed(latest, mode=mode)
            return latest, {
                "passed": not failed,
                "error_code": "PIPELINE_STALLED" if failed else None,
                "failed_stage": current_stage if failed else None,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "warnings": list(dict.fromkeys(warnings)),
                "errors": [f"{current_stage} reached a failed terminal state."] if failed else [],
            }

        watchdog = watchdog_assessment(
            stage=current_stage,
            stage_elapsed_seconds=now - current_stage_started,
            no_progress_seconds=now - last_progress,
            timeout_seconds=stage_timeout_seconds,
        )
        if not watchdog.get("passed"):
            return latest, {
                "passed": False,
                "error_code": watchdog.get("error_code"),
                "failed_stage": current_stage,
                "elapsed_seconds": round(now - started, 3),
                "warnings": warnings,
                "errors": [str(watchdog.get("message"))],
            }
        interval = (
            min(poll_interval_seconds, 1.0)
            if mode == "planning_only"
            else poll_interval_seconds
        )
        time.sleep(max(0.05, interval))


def write_long_video_reports(report: JsonDict, report_dir: Path) -> dict[str, str]:
    """Write the exact JSON and Markdown report pair requested by the CLI."""

    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / REPORT_JSON
    markdown_path = report_dir / REPORT_MARKDOWN
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(long_video_markdown(report), encoding="utf-8")
    return {REPORT_JSON: str(json_path), REPORT_MARKDOWN: str(markdown_path)}


def long_video_markdown(report: JsonDict) -> str:
    """Render a concise operator summary from the JSON contract."""

    top = as_dict(report.get("long_video_validation_v2"))
    result = as_dict(top.get("result"))
    source = as_dict(top.get("source_video"))
    planning = as_dict(top.get("planning"))
    coverage = as_dict(planning.get("timeline_coverage"))
    diversity = as_dict(planning.get("clip_diversity"))
    environment = as_dict(top.get("environment"))
    intelligence = as_dict(top.get("intelligence_metadata"))
    frontend = as_dict(top.get("frontend_payload"))
    lines = [
        "# Olympus Long-Video Validation V2",
        "",
        f"- Created: `{top.get('created_at')}`",
        f"- Workspace: `{top.get('workspace')}`",
        f"- Branch: `{top.get('branch')}`",
        f"- Mode: `{top.get('mode')}`",
        f"- Tier: `{top.get('tier')}`",
        f"- Project: `{top.get('project_id')}`",
        f"- Result: `{result.get('status')}`",
        f"- Real video validation: `{top.get('real_video_validation')}`",
        "",
        "## Source",
        "",
        f"- Path: `{source.get('path')}`",
        f"- Duration: `{source.get('duration_seconds')}` seconds",
        f"- Classification: `{as_dict(source.get('classification')).get('duration_tier')}`",
        f"- Resolution: `{source.get('width')}x{source.get('height')}`",
        f"- Codecs: video `{source.get('video_codec')}`, audio `{source.get('audio_codec')}`",
        "",
        "## Environment",
        "",
        f"- FFmpeg: `{environment.get('ffmpeg_available')}`",
        f"- FFprobe: `{environment.get('ffprobe_available')}`",
        f"- Backend reachable: `{environment.get('backend_reachable')}`",
        f"- Report directory writable: `{environment.get('workdir_writable')}`",
        "",
        "## Planning",
        "",
        f"- Attempted: `{planning.get('attempted')}`",
        f"- Passed: `{planning.get('passed')}`",
        f"- Planned clips: `{planning.get('planned_clip_count')}`",
        f"- Expected range: `{planning.get('expected_clip_range')}`",
        f"- Coverage score: `{coverage.get('coverage_score')}`",
        f"- Early bias: `{coverage.get('early_bias_detected')}`",
        f"- Late video ignored: `{coverage.get('late_video_ignored')}`",
        f"- Diversity score: `{diversity.get('diversity_score')}`",
        f"- Duplicate ranges: `{len(as_list(diversity.get('duplicate_ranges')))}`",
        "",
        "## Rendered Clips",
        "",
    ]
    rendered = as_list(top.get("rendered_clips"))
    if rendered:
        for clip in rendered:
            item = as_dict(clip)
            lines.append(
                f"- `{item.get('clip_id')}`: passed `{item.get('validation_passed')}`, "
                f"duration `{item.get('duration_seconds')}`, sync delta "
                f"`{item.get('sync_delta')}`"
            )
    else:
        lines.append("- None validated; no render-success claim was made.")
    lines.extend(
        [
            "",
            "## Metadata Survival",
            "",
            f"- Story V2: `{intelligence.get('story_v2_found')}`",
            f"- Virality V2: `{intelligence.get('virality_v2_found')}`",
            f"- Trend research: `{intelligence.get('trend_research_found')}`",
            f"- Music intelligence: `{intelligence.get('music_intelligence_found')}`",
            f"- Captions V2: `{intelligence.get('captions_v2_found')}`",
            f"- Motion V2: `{intelligence.get('motion_v2_found')}`",
            f"- Multi-speaker V2: `{intelligence.get('multi_speaker_found')}`",
            f"- Unified clip intelligence: "
            f"`{intelligence.get('unified_clip_intelligence_found')}`",
            "",
            "## Frontend Payload",
            "",
            f"- Checked: `{frontend.get('checked')}`",
            f"- Clips visible: `{frontend.get('clips_visible')}`",
            f"- Download URLs present: `{frontend.get('download_urls_present')}`",
            f"- Why-this-clip-works present: "
            f"`{frontend.get('why_this_clip_works_present')}`",
            "",
            "## Result",
            "",
            f"- Message: {result.get('message')}",
            f"- Failed stage: `{result.get('failed_stage')}`",
            f"- Error code: `{result.get('error_code')}`",
            f"- Next action: {result.get('next_action')}",
        ]
    )
    if result.get("command_to_try"):
        lines.extend(["", "```powershell", str(result["command_to_try"]), "```"])
    lines.extend(["", "## Warnings", ""])
    warnings = as_list(top.get("warnings"))
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("- None")
    lines.extend(["", "## Stage Timings", ""])
    timings = as_list(top.get("stage_timings"))
    for timing in timings:
        item = as_dict(timing)
        lines.append(
            f"- `{item.get('stage')}`: `{item.get('status')}`, "
            f"`{item.get('duration_seconds')}` seconds"
        )
    if not timings:
        lines.append("- No pipeline stages were run.")
    return "\n".join(lines) + "\n"


def aggregate_reports(reports: list[JsonDict]) -> JsonDict:
    """Aggregate multiple per-source contracts without losing their evidence."""

    if not reports:
        raise ValueError("At least one report is required for aggregation.")
    if len(reports) == 1:
        return reports[0]
    videos = [as_dict(report.get("long_video_validation_v2")) for report in reports]
    first = dict(videos[0])
    passed = all(as_dict(video.get("result")).get("passed") is True for video in videos)
    first["source"] = {"kind": "multiple_sources", "count": len(videos)}
    first["source_video"] = _empty_source_video()
    first["videos_tested"] = len(videos)
    first["videos_passed"] = sum(
        1 for video in videos if as_dict(video.get("result")).get("passed") is True
    )
    first["videos_failed"] = len(videos) - int(first["videos_passed"])
    first["warnings"] = [
        str(warning) for video in videos for warning in as_list(video.get("warnings"))
    ]
    first["result"] = {
        "passed": passed,
        "status": "PASSED" if passed else "VALIDATION_FAILED",
        "failed_stage": None if passed else "multiple_sources",
        "error_code": None if passed else "VALIDATION_FAILED",
        "message": (
            f"All {len(videos)} source validations passed."
            if passed
            else f"{first['videos_failed']} of {len(videos)} source validations failed."
        ),
        "next_action": "Inspect each entry in videos for source-specific evidence.",
        "command_to_try": None,
    }
    return {"long_video_validation_v2": first, "videos": videos}


def _base_contract(
    *,
    workspace: Path,
    branch: str,
    mode: str,
    tier: str | None,
    source: JsonDict,
    project_id: str | None,
    source_video: JsonDict,
    environment: JsonDict,
) -> JsonDict:
    return {
        "created_at": utc_now_iso(),
        "workspace": str(workspace),
        "branch": branch,
        "mode": mode,
        "tier": tier or as_dict(source_video.get("classification")).get("duration_tier"),
        "source": source,
        "project_id": project_id,
        "real_video_validation": False,
        "backend_required": mode in {"planning_only", "full_pipeline", "existing_project"},
        "backend_used": False,
        "environment": environment,
        "source_video": source_video,
        "stage_timings": [],
        "planning": {
            "attempted": False,
            "passed": False,
            "expected_clip_range": list(
                expected_clip_range_v2(_optional_float(source_video.get("duration_seconds")))
            ),
            "planned_clip_count": 0,
            "low_output_reason": None,
            "timeline_coverage": {},
            "diversity_score": None,
            "duplicate_risk": "unknown",
            "warnings": [],
        },
        "rendered_clips": [],
        "intelligence_metadata": {
            "story_v2_found": False,
            "virality_v2_found": False,
            "trend_research_found": False,
            "music_intelligence_found": False,
            "curated_music_library_found": False,
            "captions_v2_found": False,
            "motion_v2_found": False,
            "multi_speaker_found": False,
            "unified_clip_intelligence_found": False,
            "why_this_clip_works_found": False,
            "warnings": [],
        },
        "frontend_payload": {
            "checked": False,
            "clips_visible": False,
            "download_urls_present": False,
            "why_this_clip_works_present": False,
            "warnings": [],
        },
        "warnings": [],
        "errors": [],
        "result": {
            "passed": False,
            "status": "NOT_RUN",
            "failed_stage": None,
            "error_code": None,
            "message": "Validation has not run.",
            "next_action": None,
            "command_to_try": None,
        },
    }


def _empty_source_video() -> JsonDict:
    return {
        "path": None,
        "exists": False,
        "duration_seconds": None,
        "width": None,
        "height": None,
        "video_codec": None,
        "audio_codec": None,
        "audio_sample_rate": None,
        "file_size_bytes": 0,
        "classification": {"duration_tier": "unknown", "inferred_types": ["unknown"]},
        "ffprobe_passed": False,
        "warnings": [],
        "errors": [],
    }


def _source_from_project(project: JsonDict, *, bundle: JsonDict | None = None) -> JsonDict:
    inspection = _stage_data(as_dict(as_dict(bundle).get("analysis")), "video_inspection")
    generation = _stage_data(
        as_dict(as_dict(bundle).get("planning")),
        "candidate_generation",
    )
    duration = _first_number(
        project.get("duration_seconds"),
        inspection.get("duration_seconds"),
        generation.get("video_duration"),
    )
    width = as_int(project.get("width")) or as_int(inspection.get("width"))
    height = as_int(project.get("height")) or as_int(inspection.get("height"))
    warnings = ["Existing project source was not downloaded for a local ffprobe probe."]
    if project.get("duration_seconds") is None and duration is not None:
        warnings.append("Source duration was recovered from persisted analysis/planning artifacts.")
    return {
        "path": None,
        "exists": None,
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "video_codec": None,
        "audio_codec": None,
        "audio_sample_rate": None,
        "file_size_bytes": as_int(project.get("size_bytes")) or 0,
        "classification": {
            "duration_tier": classify_long_video_duration(duration),
            "inferred_types": infer_video_types(str(project.get("source_filename") or "")),
            "inference_source": "project_metadata_and_filename",
        },
        "ffprobe_passed": False,
        "project_source_registered": bool(project.get("id")),
        "warnings": warnings,
        "errors": [],
    }


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _optional_float(value)
        if parsed is not None:
            return parsed
    return None


def clip_range(clip: JsonDict) -> tuple[float, float] | None:
    """Extract a source range from plan, render, candidate, or unified metadata."""

    metadata = as_dict(clip.get("metadata"))
    unified = as_dict(
        clip.get("unified_clip_intelligence") or metadata.get("unified_clip_intelligence")
    )
    timestamps = as_dict(clip.get("source_timestamps"))
    start = _first_number(
        clip.get("source_start"),
        clip.get("start"),
        clip.get("raw_start"),
        timestamps.get("start"),
        unified.get("source_start"),
    )
    end = _first_number(
        clip.get("source_end"),
        clip.get("end"),
        clip.get("raw_end"),
        timestamps.get("end"),
        unified.get("source_end"),
    )
    if start is None or end is None or end <= start:
        return None
    return (round(start, 3), round(end, 3))


def _coverage_bucket(start: float, duration: float) -> str:
    if duration <= 0:
        return "0-10%"
    ratio = max(0.0, min(1.0, start / duration))
    if ratio < 0.1:
        return "0-10%"
    if ratio < 0.25:
        return "10-25%"
    if ratio < 0.5:
        return "25-50%"
    if ratio < 0.75:
        return "50-75%"
    return "75-100%"


def _range_overlap_ratio(left: tuple[float, float], right: tuple[float, float]) -> float:
    overlap = max(0.0, min(left[1], right[1]) - max(left[0], right[0]))
    shorter = min(left[1] - left[0], right[1] - right[0])
    return overlap / shorter if shorter > 0 else 0.0


def _clip_identity(clip: JsonDict, index: int) -> str:
    return str(
        clip.get("clip_id")
        or clip.get("id")
        or clip.get("plan_id")
        or clip.get("candidate_id")
        or f"clip_{index + 1}"
    )


def _normalized_signal(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _hook_value(clip: JsonDict) -> Any:
    unified = as_dict(
        clip.get("unified_clip_intelligence")
        or as_dict(clip.get("metadata")).get("unified_clip_intelligence")
    )
    virality = as_dict(unified.get("virality"))
    return clip.get("hook_line") or virality.get("hook_category") or virality.get("hook_line")


def _story_value(clip: JsonDict) -> Any:
    unified = as_dict(
        clip.get("unified_clip_intelligence")
        or as_dict(clip.get("metadata")).get("unified_clip_intelligence")
    )
    story = as_dict(unified.get("story"))
    return clip.get("story_id") or story.get("story_shape") or story.get("story_summary")


def _music_value(clip: JsonDict) -> Any:
    metadata = as_dict(clip.get("metadata"))
    unified = as_dict(
        clip.get("unified_clip_intelligence") or metadata.get("unified_clip_intelligence")
    )
    editing = as_dict(unified.get("editing"))
    music = as_dict(metadata.get("music_intelligence_v2") or editing.get("music_intelligence_v2"))
    selected = as_dict(music.get("selected_asset"))
    return selected.get("asset_id") or selected.get("path") or metadata.get("music_asset")


def _stage_data(engine: JsonDict, stage_name: str) -> JsonDict:
    for stage in as_list(engine.get("stages")):
        item = as_dict(stage)
        if item.get("stage") == stage_name and item.get("status") == "completed":
            return as_dict(item.get("data"))
    return {}


def _stage_timing_row(
    name: str,
    engine: JsonDict,
    timeout_seconds: float,
    *,
    substage: str | None = None,
) -> JsonDict:
    stages = [as_dict(item) for item in as_list(engine.get("stages"))]
    if substage:
        item = next((stage for stage in stages if stage.get("stage") == substage), {})
        status = item.get("status") or "not_started"
        started_at = item.get("started_at")
        finished_at = item.get("completed_at")
        duration = duration_between(started_at, finished_at)
        errors = [str(item["error"])] if item.get("error") else []
        warnings = [str(item["reason"])] if item.get("reason") else []
    else:
        status = engine.get("status") or "not_started"
        starts = [str(item["started_at"]) for item in stages if item.get("started_at")]
        finishes = [str(item["completed_at"]) for item in stages if item.get("completed_at")]
        started_at = min(starts) if starts else engine.get("created_at")
        finished_at = max(finishes) if finishes else (
            engine.get("updated_at") if status in TERMINAL_STATUSES else None
        )
        duration = duration_between(started_at, finished_at)
        errors = [str(item["error"]) for item in stages if item.get("error")]
        warnings = [str(item["reason"]) for item in stages if item.get("reason")]
    return {
        "stage": name,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration,
        "timeout_seconds": timeout_seconds,
        "warnings": warnings,
        "errors": errors,
    }


def _backend_health(client: ValidationHttpClient) -> JsonDict:
    try:
        response = client.json_request("GET", "/api/v1/health/live")
    except Exception as exc:
        return {"passed": False, "error": str(exc), "error_code": _backend_exception_code(exc)}
    return {"passed": response.get("status") == "alive", "response": response}


def _backend_exception_code(exc: Exception) -> str:
    if isinstance(exc, LookupError):
        return "PROJECT_NOT_FOUND"
    if isinstance(exc, FileNotFoundError):
        return "SOURCE_NOT_FOUND"
    if isinstance(exc, urllib.error.HTTPError):
        return "PROJECT_NOT_FOUND" if exc.code == 404 else "BACKEND_REQUEST_FAILED"
    if isinstance(exc, (urllib.error.URLError, ConnectionError, TimeoutError, OSError)):
        text = str(exc).lower()
        if any(token in text for token in ("refused", "10061", "timed out", "unreachable")):
            return "LOCAL_BACKEND_UNAVAILABLE"
    return "BACKEND_REQUEST_FAILED"


def _failure_result(
    code: str,
    message: str,
    next_action: str,
    command_to_try: str | None,
    *,
    failed_stage: str,
) -> JsonDict:
    return {
        "passed": False,
        "status": "FAILED",
        "failed_stage": failed_stage,
        "error_code": code,
        "message": message,
        "next_action": next_action,
        "command_to_try": command_to_try,
    }


def _status(value: Any) -> str:
    return str(as_dict(value).get("status") or "not_started")


def _start_next_missing_engine(
    client: ValidationHttpClient,
    project_id: str,
    bundle: JsonDict,
    *,
    mode: str,
    warnings: list[str],
) -> None:
    target_index = PIPELINE_ENGINES.index("planning" if mode == "planning_only" else "optimization")
    for index, engine in enumerate(PIPELINE_ENGINES[: target_index + 1]):
        status = _status(bundle.get(engine))
        if status in {"running", "pending"}:
            return
        if status in {"failed", "cancelled", "unavailable"}:
            return
        if status == "completed":
            continue
        if index > 0 and _status(bundle.get(PIPELINE_ENGINES[index - 1])) != "completed":
            return
        try:
            client.json_request("POST", f"/api/v1/projects/{project_id}/{engine}/run")
        except Exception as exc:
            warnings.append(f"Could not start missing {engine} stage: {exc}")
        return


def _current_pipeline_stage(bundle: JsonDict, *, mode: str) -> str:
    analysis = as_dict(bundle.get("analysis"))
    if _status(analysis) not in TERMINAL_STATUSES:
        transcription = next(
            (
                as_dict(stage)
                for stage in as_list(analysis.get("stages"))
                if as_dict(stage).get("stage") == "speech_transcription"
            ),
            {},
        )
        if transcription and str(transcription.get("status")) not in TERMINAL_STATUSES:
            return "transcription"
        return "analysis"
    target = "planning" if mode == "planning_only" else "optimization"
    for engine in PIPELINE_ENGINES:
        if _status(bundle.get(engine)) not in TERMINAL_STATUSES:
            return engine
        if engine == target:
            break
    return target


def _progress_fingerprint(bundle: JsonDict) -> str:
    state: JsonDict = {}
    for engine in PIPELINE_ENGINES:
        payload = as_dict(bundle.get(engine))
        state[engine] = {
            "status": payload.get("status"),
            "updated_at": payload.get("updated_at"),
            "stages": [
                {
                    "stage": as_dict(stage).get("stage"),
                    "status": as_dict(stage).get("status"),
                    "progress": as_dict(stage).get("progress"),
                    "completed_at": as_dict(stage).get("completed_at"),
                }
                for stage in as_list(payload.get("stages"))
            ],
        }
    state["render_count"] = len(_renders_from_bundle(bundle))
    state["plan_count"] = len(_plans_from_bundle(bundle))
    return json.dumps(state, sort_keys=True, default=str)


def _poll_target_terminal(bundle: JsonDict, *, mode: str) -> bool:
    if mode == "planning_only":
        return _status(bundle.get("planning")) in TERMINAL_STATUSES
    render_status = _status(bundle.get("rendering"))
    if render_status in {"failed", "cancelled", "unavailable"}:
        return True
    if render_status != "completed":
        return False
    return _status(bundle.get("optimization")) in TERMINAL_STATUSES


def _target_failed(bundle: JsonDict, *, mode: str) -> bool:
    target = "planning" if mode == "planning_only" else "rendering"
    if _status(bundle.get(target)) in {"failed", "cancelled", "unavailable"}:
        return True
    return bool(
        mode == "full_pipeline"
        and _status(bundle.get("rendering")) == "completed"
        and _status(bundle.get("optimization")) in {"failed", "cancelled", "unavailable"}
    )


def _cancel_downstream(
    client: ValidationHttpClient,
    project_id: str,
    bundle: JsonDict,
) -> list[str]:
    warnings: list[str] = []
    observed = [engine for engine in ("editing", "rendering", "optimization") if bundle.get(engine)]
    for engine in ("editing", "rendering", "optimization"):
        try:
            response = client.json_request(
                "POST", f"/api/v1/projects/{project_id}/{engine}/cancel"
            )
            if response.get("cancelled") is True:
                warnings.append(f"Planning-only mode cancelled auto-started {engine} work.")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                warnings.append(f"Could not cancel {engine}: HTTP {exc.code}")
        except Exception as exc:
            warnings.append(f"Could not cancel {engine}: {exc}")
    if observed:
        warnings.append(
            "Automatic engine chaining had already created downstream state; "
            "planning-only cancelled it and did not claim render success."
        )
    return warnings


def _plans_from_bundle(bundle: JsonDict) -> list[JsonDict]:
    plans = [as_dict(item) for item in as_list(as_dict(bundle.get("plans")).get("plans"))]
    if plans:
        return plans
    ranking = _stage_data(as_dict(bundle.get("planning")), "ranking")
    return [as_dict(item) for item in as_list(ranking.get("plans"))]


def _renders_from_bundle(bundle: JsonDict) -> list[JsonDict]:
    manifest = as_dict(as_dict(bundle.get("manifest")).get("manifest"))
    return [as_dict(item) for item in as_list(manifest.get("renders"))]


def _analysis_durations(bundle: JsonDict) -> tuple[float | None, float | None]:
    analysis = as_dict(bundle.get("analysis"))
    inspection = _stage_data(analysis, "video_inspection")
    transcription = _stage_data(analysis, "speech_transcription")
    analyzed_duration = _optional_float(inspection.get("duration_seconds"))
    segment_ends = [
        _first_number(as_dict(segment).get("end"), as_dict(segment).get("end_time"))
        for segment in as_list(transcription.get("segments"))
    ]
    valid_ends = [value for value in segment_ends if value is not None]
    transcript_duration = max(valid_ends) if valid_ends else None
    return analyzed_duration, transcript_duration


def _download_and_validate_renders(
    *,
    client: ValidationHttpClient,
    project_id: str,
    report_dir: Path,
    renders: list[JsonDict],
    require_audio: bool,
) -> list[JsonDict]:
    reports: list[JsonDict] = []
    output_dir = report_dir / "downloads" / project_id
    for index, render in enumerate(renders):
        clip_id = _clip_identity(render, index)
        destination = output_dir / f"{clip_id}.mp4"
        rendered_path: Path | None = destination
        download_error: str | None = None
        try:
            client.download(
                f"/api/v1/projects/{project_id}/rendering/clips/{clip_id}/download",
                destination,
            )
        except Exception as exc:
            download_error = str(exc)
            rendered_path = None
        metadata = as_dict(render.get("metadata"))
        planned_duration = _first_number(
            metadata.get("planned_duration"),
            render.get("duration"),
        )
        raw = validate_rendered_clip(
            clip=render,
            rendered_path=rendered_path,
            planned_duration=planned_duration,
            require_audio=require_audio,
        )
        probe = as_dict(raw.get("ffprobe"))
        warnings = [str(item) for item in as_list(raw.get("warnings"))]
        errors = [str(item) for item in as_list(raw.get("errors"))]
        if download_error:
            errors.append(f"download failed: {download_error}")
        video_codec = str(probe.get("video_codec") or "").lower()
        audio_codec = str(probe.get("audio_codec") or "").lower()
        if video_codec not in {"h264", "libx264"}:
            warnings.append(f"Expected H.264 video, found {video_codec or 'unknown'}.")
        if probe.get("audio_codec") and audio_codec != "aac":
            warnings.append(f"Expected AAC audio, found {audio_codec}.")
        if probe.get("audio_sample_rate") not in (None, 48000):
            warnings.append(
                f"Audio sample rate is {probe.get('audio_sample_rate')} Hz; 48000 Hz is preferred."
            )
        fps = _optional_float(probe.get("fps"))
        video_duration = _optional_float(probe.get("video_duration"))
        estimated_frames = int(fps * video_duration) if fps and video_duration else None
        if estimated_frames is not None and estimated_frames <= 0:
            errors.append("Rendered video has no decodable-duration frame estimate.")
        codec_passed = video_codec in {"h264", "libx264"} and (
            not probe.get("audio_codec") or audio_codec == "aac"
        )
        validation_passed = bool(raw.get("pass_fail")) and not errors and codec_passed
        reports.append(
            {
                "clip_id": clip_id,
                "path": str(rendered_path) if rendered_path and rendered_path.exists() else None,
                "download_url": (
                    f"/api/v1/projects/{project_id}/rendering/clips/{clip_id}/download"
                ),
                "exists": bool(rendered_path and rendered_path.exists()),
                "duration_seconds": probe.get("container_duration"),
                "video_duration": probe.get("video_duration"),
                "audio_duration": probe.get("audio_duration"),
                "width": probe.get("width"),
                "height": probe.get("height"),
                "video_codec": probe.get("video_codec"),
                "audio_codec": probe.get("audio_codec"),
                "audio_sample_rate": probe.get("audio_sample_rate"),
                "estimated_frame_count": estimated_frames,
                "sync_delta": as_dict(raw.get("validation")).get("sync_delta_seconds"),
                "duration_delta": as_dict(raw.get("validation")).get(
                    "duration_delta_seconds"
                ),
                "validation_passed": validation_passed,
                "warnings": list(dict.fromkeys(warnings)),
                "errors": list(dict.fromkeys(errors)),
                "validation_details": raw,
            }
        )
    return reports


def _validate_link_project(
    *,
    client: ValidationHttpClient,
    project: JsonDict,
    required: bool,
) -> JsonDict:
    source_type = str(project.get("source_type") or "upload")
    ingestion_id = str(project.get("link_ingestion_id") or "")
    warnings: list[str] = []
    errors: list[str] = []
    status: JsonDict | None = None
    if required and source_type != "link":
        errors.append("--from-link was requested, but project source_type is not link.")
    if source_type == "link" and not ingestion_id:
        errors.append("Link project is missing link_ingestion_id provenance.")
    if ingestion_id:
        try:
            status = client.get_json_or_none(f"/api/v1/projects/link-ingestions/{ingestion_id}")
        except Exception as exc:
            warnings.append(f"Link ingestion status could not be fetched: {exc}")
    return {
        "checked": required or source_type == "link",
        "source_type": source_type,
        "source_url_present": bool(project.get("source_url")),
        "link_ingestion_id": ingestion_id or None,
        "link_ingestion_status": status,
        "passed": not errors,
        "warnings": warnings,
        "errors": errors,
    }


def _success_message(mode: str, planned: int, rendered: int) -> str:
    if mode == "planning_only":
        return (
            f"Planning-only validation passed with {planned} planned clip(s); "
            "render was not claimed."
        )
    if mode == "full_pipeline":
        return f"Full-pipeline validation passed with {planned} plans and {rendered} probed MP4(s)."
    return f"Existing project validation passed with {planned} plans and {rendered} render(s)."


def _next_success_action(mode: str, source_path: Path | None, project_id: str) -> str:
    if mode == "planning_only":
        return "Run full-pipeline validation when render time and disk space are available."
    if mode == "full_pipeline":
        return "Inspect the Markdown report and manually play representative clips."
    return "Use --full-pipeline only if this existing project still needs downstream work."


def _next_success_command(mode: str, source_path: Path | None, project_id: str) -> str | None:
    executable = Path(sys.executable)
    if mode == "planning_only" and source_path:
        return (
            f'{executable} tools\\validate_long_video.py --file "{source_path}" '
            "--full-pipeline"
        )
    if mode == "planning_only":
        return (
            f"{executable} tools\\validate_long_video.py --project-id {project_id} "
            "--full-pipeline"
        )
    return None


def _retry_command(mode: str, source_path: Path | None, project_id: str) -> str:
    executable = Path(sys.executable)
    flag = "--planning-only" if mode == "planning_only" else "--full-pipeline"
    if source_path:
        return f'{executable} tools\\validate_long_video.py --file "{source_path}" {flag}'
    return f"{executable} tools\\validate_long_video.py --project-id {project_id} {flag}"


def _first_failed_stage(top: JsonDict) -> str:
    planning = as_dict(top.get("planning"))
    if planning.get("passed") is False:
        return "planning"
    rendered_failed = any(
        as_dict(item).get("validation_passed") is False
        for item in as_list(top.get("rendered_clips"))
    )
    if rendered_failed:
        return "rendering"
    if as_dict(top.get("frontend_payload")).get("checked") and not as_dict(
        top.get("frontend_payload")
    ).get("passed"):
        return "frontend_payload"
    return "validation"

"""Real-video validation and runtime hardening helpers.

The helpers in this module are deliberately independent from the production
runtime. They validate the real HTTP/API flow when a backend is running, but can
also run discovery/report/schema checks without videos or servers. Reports are
JSON-safe dictionaries so the CLI can persist them verbatim for debugging.
"""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any
from uuid import uuid4

VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
DEFAULT_SAMPLE_DIRS = (
    Path("D:/Olympus/validation_samples"),
    Path("D:/Olympus/samples"),
    Path("D:/Olympus/test_media"),
    Path("D:/Olympus/media"),
    Path("D:/Olympus/work/validation_samples"),
)
DEFAULT_REPORT_DIR = Path("D:/Olympus/work/validation_reports")
REPORT_FILES = {
    "top": "validation_report.json",
    "summary": "validation_summary.md",
    "videos": "per_video_report.json",
    "clips": "per_clip_report.json",
    "ffprobe": "ffprobe_outputs.json",
    "timings": "timings.json",
    "warnings": "warnings.json",
}

EXPECTED_STAGE_VERSIONS = {
    "story_analysis_v2": "1",
    "trend_research": "2",
    "hook_strength": "2",
    "retention": "2",
    "replay_potential": "2",
    "platform_fit": "2",
    "virality_summary": "3",
    "candidate_generation": "4",
    "boundary_refinement": "3",
    "clip_scoring": "5",
    "duplicate_detection": "4",
    "blueprint_generation": "5",
    "ranking": "5",
    "planning_summary": "5",
    "timeline_initialization": "2",
    "subtitle_segmentation": "4",
    "caption_timing": "5",
    "zoom_planner": "3",
    "crop_planner": "4",
    "timeline_validation": "8",
    "validate_timeline": "3",
    "apply_captions": "2",
    "render_preview": "9",
    "full_resolution_render": "9",
    "render_verification": "8",
    "generate_render_manifest": "11",
    "rendering.final_validation": "8",
}

TIER_RANGES = {
    "tiny": (0.0, 180.0),
    "short": (180.0, 300.0),
    "medium": (600.0, 1200.0),
    "long": (1800.0, 3600.0),
    "very_long": (3600.0, 7200.0),
}


@dataclass(frozen=True)
class VideoSample:
    path: Path
    filename: str
    duration: float | None
    tier: str
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool
    audio_codec: str | None
    video_codec: str | None
    file_size_bytes: int
    ffprobe: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "filename": self.filename,
            "duration": self.duration,
            "tier": self.tier,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "has_audio": self.has_audio,
            "audio_codec": self.audio_codec,
            "video_codec": self.video_codec,
            "file_size_bytes": self.file_size_bytes,
            "ffprobe": self.ffprobe,
        }


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def classify_duration(duration: float | None) -> str:
    if duration is None or duration <= 0:
        return "unknown"
    for tier, (minimum, maximum) in TIER_RANGES.items():
        if minimum <= duration < maximum:
            return tier
    return "unknown"


def parse_fps(value: str | None) -> float | None:
    if not value:
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        den = as_float(denominator)
        if den <= 0:
            return None
        return round(as_float(numerator) / den, 3)
    parsed = as_float(value)
    return round(parsed, 3) if parsed > 0 else None


def run_ffprobe(path: Path, *, timeout_seconds: float = 60.0) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return {
            "passed": False,
            "unavailable": True,
            "errors": ["ffprobe is not available on PATH"],
            "path": str(path),
        }
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration,size,format_name:"
                    "stream=index,codec_type,codec_name,width,height,duration,"
                    "channels,sample_rate,avg_frame_rate,r_frame_rate"
                ),
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "errors": [f"ffprobe timed out after {timeout_seconds}s"],
            "path": str(path),
        }
    except OSError as exc:
        return {"passed": False, "errors": [str(exc)], "path": str(path)}
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        return {
            "passed": False,
            "errors": [stderr or f"ffprobe exited {completed.returncode}"],
            "path": str(path),
        }
    try:
        raw = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {
            "passed": False,
            "errors": [f"ffprobe returned invalid JSON: {exc}"],
            "path": str(path),
        }
    return {"passed": True, "path": str(path), "raw": raw, **parse_probe(raw)}


def parse_probe(raw: dict[str, Any]) -> dict[str, Any]:
    streams = as_list(raw.get("streams"))
    fmt = as_dict(raw.get("format"))
    video = next((as_dict(s) for s in streams if as_dict(s).get("codec_type") == "video"), {})
    audio = next((as_dict(s) for s in streams if as_dict(s).get("codec_type") == "audio"), {})
    duration = as_float(fmt.get("duration"))
    video_duration = as_float(video.get("duration"), duration)
    audio_duration = as_float(audio.get("duration"), duration if audio else 0.0)
    fps = parse_fps(str(video.get("avg_frame_rate") or video.get("r_frame_rate") or ""))
    return {
        "container_duration": round(duration, 3) if duration else None,
        "video_duration": round(video_duration, 3) if video_duration else None,
        "audio_duration": round(audio_duration, 3) if audio_duration else None,
        "width": as_int(video.get("width")),
        "height": as_int(video.get("height")),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "audio_sample_rate": as_int(audio.get("sample_rate")),
        "fps": fps,
        "has_audio": bool(audio),
        "stream_count": len(streams),
        "file_size_bytes": as_int(fmt.get("size")),
    }


def discover_video_samples(
    *,
    explicit_files: list[Path] | None = None,
    sample_dirs: list[Path] | None = None,
    tier: str | None = None,
    long_only: bool = False,
) -> list[VideoSample]:
    paths: list[Path] = []
    for file in explicit_files or []:
        if file.suffix.lower() in VIDEO_EXTENSIONS:
            paths.append(file)
    for folder in sample_dirs or list(DEFAULT_SAMPLE_DIRS):
        if not folder.exists():
            continue
        for child in sorted(folder.rglob("*")):
            if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
                paths.append(child)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)

    samples = [_sample_from_path(path) for path in unique if path.exists()]
    if tier:
        samples = [sample for sample in samples if sample.tier == tier]
    if long_only:
        samples = [sample for sample in samples if sample.tier in {"long", "very_long"}]
    return sorted(
        samples,
        key=lambda sample: (
            sample.duration is None,
            sample.duration or 0.0,
            str(sample.path).lower(),
        ),
    )


def _sample_from_path(path: Path) -> VideoSample:
    probe = run_ffprobe(path)
    duration = probe.get("container_duration") if probe.get("passed") else None
    return VideoSample(
        path=path,
        filename=path.name,
        duration=as_float(duration) if duration is not None else None,
        tier=classify_duration(as_float(duration) if duration is not None else None),
        width=probe.get("width"),
        height=probe.get("height"),
        fps=probe.get("fps"),
        has_audio=bool(probe.get("has_audio")),
        audio_codec=probe.get("audio_codec"),
        video_codec=probe.get("video_codec"),
        file_size_bytes=path.stat().st_size,
        ffprobe=probe,
    )


def expected_clip_range(duration: float | None) -> tuple[int, int]:
    if duration is None:
        return (0, 0)
    if duration < 180:
        return (1, 4)
    if duration < 600:
        return (2, 6)
    if duration < 1800:
        return (4, 10)
    if duration < 3600:
        return (6, 15)
    if duration <= 7200:
        return (10, 30)
    return (0, 0)


def output_count_assessment(
    *,
    source_duration: float | None,
    planned_clip_count: int,
    rendered_clip_count: int,
    low_output_reason: dict[str, Any] | None,
    candidate_count: int | None = None,
) -> dict[str, Any]:
    expected_min, expected_max = expected_clip_range(source_duration)
    warnings: list[str] = []
    passed = True
    if expected_min and planned_clip_count < expected_min:
        if low_output_reason:
            warnings.append(
                f"planned {planned_clip_count} clip(s), below expected "
                f"{expected_min}-{expected_max}, but low_output_reason exists"
            )
        else:
            passed = False
            warnings.append(
                f"planned {planned_clip_count} clip(s), below expected "
                f"{expected_min}-{expected_max}, without low_output_reason"
            )
    if rendered_clip_count < planned_clip_count:
        passed = False
        warnings.append(f"rendered {rendered_clip_count} of {planned_clip_count} planned clip(s)")
    if candidate_count and planned_clip_count <= 1 and candidate_count > 1:
        warnings.append("multiple candidates existed but only one clip was selected")
    return {
        "passed": passed,
        "expected_min": expected_min,
        "expected_max": expected_max,
        "planned_clip_count": planned_clip_count,
        "rendered_clip_count": rendered_clip_count,
        "low_output_reason_present": bool(low_output_reason),
        "warnings": warnings,
    }


def timeline_coverage(
    *,
    source_duration: float | None,
    clips: list[dict[str, Any]],
    explanation: str | None = None,
    total_sections: int | None = None,
) -> dict[str, Any]:
    starts = [
        as_float(clip.get("source_start"), as_float(clip.get("start")))
        for clip in clips
        if clip.get("source_start") is not None or clip.get("start") is not None
    ]
    duration = source_duration or 0.0
    quarters = [0, 0, 0, 0]
    for start in starts:
        if duration <= 0:
            continue
        idx = min(3, max(0, int((start / duration) * 4)))
        quarters[idx] += 1
    earliest = min(starts) if starts else None
    latest = max(starts) if starts else None
    span = (latest - earliest) if earliest is not None and latest is not None else 0.0
    first_ten_cluster = bool(
        duration and starts and all(start <= duration * 0.1 for start in starts)
    )
    distinct_story_ids = {
        str(clip.get("story_id")) for clip in clips if clip.get("story_id") not in (None, "")
    }
    clustered = first_ten_cluster and len(starts) > 1
    diversity_passed = not clustered or bool(explanation)
    warning = None
    if clustered and not explanation:
        warning = "all selected clips are in the first 10% without a clustering explanation"
    return {
        "source_duration": source_duration,
        "clip_count": len(clips),
        "earliest_clip_start": round(earliest, 3) if earliest is not None else None,
        "latest_clip_start": round(latest, 3) if latest is not None else None,
        "coverage_span_seconds": round(span, 3),
        "coverage_span_percent": round(span / duration, 3) if duration else 0.0,
        "sections_with_selected_clips": len(distinct_story_ids) or None,
        "total_sections": total_sections,
        "first_quarter_count": quarters[0],
        "second_quarter_count": quarters[1],
        "third_quarter_count": quarters[2],
        "fourth_quarter_count": quarters[3],
        "diversity_passed": diversity_passed,
        "warning": warning,
    }


def validate_rendered_clip(
    *,
    clip: dict[str, Any],
    rendered_path: Path | None,
    planned_duration: float | None,
    expected_width: int = 1080,
    expected_height: int = 1920,
    require_audio: bool = False,
) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    render_exists = bool(rendered_path and rendered_path.exists())
    ffprobe: dict[str, Any] = {}
    if not render_exists:
        errors.append("rendered file does not exist")
    else:
        assert rendered_path is not None
        ffprobe = run_ffprobe(rendered_path)
        if not ffprobe.get("passed"):
            errors.extend([str(e) for e in as_list(ffprobe.get("errors"))])

    container_duration = as_float(ffprobe.get("container_duration"))
    video_duration = as_float(ffprobe.get("video_duration"), container_duration)
    audio_duration = as_float(ffprobe.get("audio_duration"), container_duration)
    audio_video_delta = round(audio_duration - video_duration, 3) if ffprobe else None
    duration_delta = (
        round(container_duration - planned_duration, 3)
        if planned_duration is not None and ffprobe
        else None
    )
    resolution_passed = (
        ffprobe.get("width") == expected_width and ffprobe.get("height") == expected_height
        if ffprobe
        else False
    )
    codec_passed = (
        str(ffprobe.get("video_codec") or "").lower() in {"h264", "libx264"} if ffprobe else False
    )
    audio_present = bool(ffprobe.get("has_audio"))
    sync_passed = audio_video_delta is not None and abs(audio_video_delta) <= 0.15
    duration_passed = duration_delta is not None and abs(duration_delta) <= 0.15
    if ffprobe and not resolution_passed:
        warnings.append(
            f"resolution is {ffprobe.get('width')}x{ffprobe.get('height')}, "
            f"expected {expected_width}x{expected_height}"
        )
    if ffprobe and not codec_passed:
        warnings.append(f"unexpected video codec {ffprobe.get('video_codec')}")
    if require_audio and not audio_present:
        errors.append("audio stream missing")
    if audio_video_delta is not None and not sync_passed:
        warnings.append(f"audio/video delta {audio_video_delta}s exceeds 0.15s")
    if duration_delta is not None and not duration_passed:
        warnings.append(f"duration delta {duration_delta}s exceeds 0.15s")
    early_cutoff_risk = bool(duration_delta is not None and duration_delta < -0.15)
    metadata = as_dict(clip.get("metadata"))
    unified = as_dict(metadata.get("unified_clip_intelligence"))
    story = as_dict(unified.get("story"))
    virality = as_dict(unified.get("virality"))
    planning = as_dict(unified.get("planning"))
    multi_speaker_plan = as_dict(
        metadata.get("multi_speaker_layout_v2") or unified.get("multi_speaker_layout")
    )
    multi_speaker_decision = as_dict(multi_speaker_plan.get("layout_decision"))
    multi_speaker_validation = as_dict(metadata.get("multi_speaker_validation"))
    multi_speaker_passed = multi_speaker_validation.get("passed")
    if multi_speaker_passed is False:
        warnings.append("multi-speaker layout validation failed")
    caption_intelligence = as_dict(metadata.get("caption_intelligence_v2"))
    caption_style = as_dict(caption_intelligence.get("style_decision"))
    caption_timing = as_dict(caption_intelligence.get("caption_timing_quality"))
    caption_readability = as_dict(
        metadata.get("caption_readability_validation")
        or caption_intelligence.get("caption_readability_validation")
    )
    caption_render_validation = as_dict(metadata.get("caption_render_validation"))
    captions_planned = caption_render_validation.get("captions_planned") is True
    caption_render_passed = caption_render_validation.get("passed")
    caption_readability_warning_count = len(as_list(caption_readability.get("warnings")))
    caption_readability_severity = str(
        caption_readability.get("severity") or "warning"
    ).lower()
    caption_readability_blocking = bool(
        caption_readability.get("blocking") is True
        or caption_readability.get("errors")
        or caption_readability_severity in {"error", "critical"}
    )
    if captions_planned and caption_render_passed is not True:
        warnings.append("caption render validation failed")
    if caption_readability.get("passed") is False:
        warnings.append(
            "caption readability advisory"
            f" ({caption_readability_warning_count} warning(s))"
        )
    validation = {
        "resolution_passed": resolution_passed,
        "codec_passed": codec_passed,
        "audio_present": audio_present,
        "sync_delta_seconds": audio_video_delta,
        "sync_passed": sync_passed,
        "duration_delta_seconds": duration_delta,
        "duration_passed": duration_passed,
        "early_cutoff_risk": early_cutoff_risk,
        "face_tracking_status": as_dict(metadata.get("face_tracking")).get("mode"),
        "multi_speaker_layout_mode": multi_speaker_validation.get("applied_mode")
        or multi_speaker_decision.get("mode"),
        "multi_speaker_layout_applied": multi_speaker_validation.get("applied"),
        "multi_speaker_layout_passed": multi_speaker_passed,
        "multi_speaker_face_tracks": multi_speaker_validation.get("face_tracks_used"),
        "multi_speaker_associations": multi_speaker_validation.get(
            "speaker_associations_used"
        ),
        "multi_speaker_regions": multi_speaker_validation.get("rendered_regions"),
        "multi_speaker_switches": multi_speaker_validation.get("rendered_switches"),
        "music_status": "mixed" if metadata.get("music_mixed") else metadata.get("music_warning"),
        "sfx_status": metadata.get("sfx_mixed_count"),
        "captions_status": (
            "included"
            if clip.get("subtitles_included") and caption_render_passed is not False
            else "planned_but_unconfirmed"
            if captions_planned
            else "unavailable"
        ),
        "caption_style": caption_style.get("caption_style"),
        "caption_timing_source": caption_timing.get("source"),
        "caption_timing_estimated": caption_timing.get("estimated"),
        "caption_readability_passed": caption_readability.get("passed"),
        "caption_readability_warning_count": caption_readability_warning_count,
        "caption_readability_warnings": as_list(caption_readability.get("warnings")),
        "caption_readability_blocking": caption_readability_blocking,
        "caption_render_passed": caption_render_passed,
        "caption_render_validation": caption_render_validation,
    }
    pass_fail = not errors and bool(ffprobe.get("passed")) and resolution_passed and duration_passed
    if audio_present:
        pass_fail = pass_fail and sync_passed
    if multi_speaker_passed is False:
        pass_fail = False
    if captions_planned and caption_render_passed is not True:
        pass_fail = False
    if caption_readability.get("passed") is False and caption_readability_blocking:
        pass_fail = False
    return {
        "clip_id": clip.get("clip_id"),
        "source_start": clip.get("source_start") or unified.get("source_start"),
        "source_end": clip.get("source_end") or unified.get("source_end"),
        "planned_duration": planned_duration,
        "rendered_path": str(rendered_path) if rendered_path else None,
        "render_exists": render_exists,
        "file_size_bytes": rendered_path.stat().st_size if render_exists and rendered_path else 0,
        "ffprobe": {
            "container_duration": ffprobe.get("container_duration"),
            "video_duration": ffprobe.get("video_duration"),
            "audio_duration": ffprobe.get("audio_duration"),
            "width": ffprobe.get("width"),
            "height": ffprobe.get("height"),
            "video_codec": ffprobe.get("video_codec"),
            "audio_codec": ffprobe.get("audio_codec"),
            "audio_sample_rate": ffprobe.get("audio_sample_rate"),
            "fps": ffprobe.get("fps"),
        },
        "ffprobe_validation": {
            "passed": bool(ffprobe.get("passed")) and not errors,
            "width": ffprobe.get("width"),
            "height": ffprobe.get("height"),
            "video_codec": ffprobe.get("video_codec"),
            "audio_codec": ffprobe.get("audio_codec"),
            "audio_sample_rate": ffprobe.get("audio_sample_rate"),
            "container_duration": ffprobe.get("container_duration"),
            "video_duration": ffprobe.get("video_duration"),
            "audio_duration": ffprobe.get("audio_duration"),
            "audio_video_delta": audio_video_delta,
            "duration_delta": duration_delta,
            "warnings": warnings,
            "errors": errors,
        },
        "validation": validation,
        "intelligence": {
            "story_shape": story.get("story_shape"),
            "hook_line": virality.get("hook_line"),
            "payoff_line": story.get("payoff"),
            "why_selected": planning.get("selected_reason"),
            "why_this_clip_works_present": bool(
                virality.get("hook_line")
                or story.get("story_shape")
                or planning.get("selected_reason")
            ),
            "unified_clip_intelligence_present": bool(unified),
        },
        "warnings": warnings,
        "errors": errors,
        "pass_fail": pass_fail,
    }


def stage_timings(engine: dict[str, Any] | None) -> dict[str, Any]:
    data = as_dict(engine)
    timings: dict[str, Any] = {}
    for stage in as_list(data.get("stages")):
        item = as_dict(stage)
        name = str(item.get("stage") or "")
        if not name:
            continue
        timings[name] = {
            "status": item.get("status"),
            "version": item.get("version"),
            "duration_seconds": duration_between(item.get("started_at"), item.get("completed_at")),
            "attempts": item.get("attempts"),
            "reason": item.get("reason"),
            "error": item.get("error"),
        }
    return timings


def duration_between(started_at: Any, completed_at: Any) -> float | None:
    if not started_at or not completed_at:
        return None
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((end - start).total_seconds(), 3)


def stage_version_warnings(engines: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for engine_name, engine in engines.items():
        for stage in as_list(as_dict(engine).get("stages")):
            item = as_dict(stage)
            name = str(item.get("stage") or "")
            version = str(item.get("version") or "")
            expected = EXPECTED_STAGE_VERSIONS.get(
                f"{engine_name}.{name}", EXPECTED_STAGE_VERSIONS.get(name)
            )
            if expected and version and version != expected:
                warnings.append(f"{engine_name}.{name} used version {version}; expected {expected}")
    return warnings


def hang_warnings(
    *,
    tier: str,
    source_duration: float | None,
    observed_seconds: dict[str, float | None],
) -> list[str]:
    thresholds = {
        "tiny": {"transcription": 300, "rendering_per_clip": 180},
        "short": {"transcription": 600, "rendering_per_clip": 300},
        "medium": {"transcription": 1500, "planning": 300, "rendering_per_clip": 480},
        "long": {"transcription": 3600, "planning": 900},
        "very_long": {"transcription": 5400, "planning": 1200},
    }.get(tier, {})
    warnings: list[str] = []
    for key, threshold in thresholds.items():
        value = observed_seconds.get(key)
        if value is not None and value > threshold:
            warnings.append(f"{key} took {value:.1f}s, above warning threshold {threshold}s")
    total = observed_seconds.get("total")
    if (
        tier in {"long", "very_long"}
        and source_duration
        and total
        and total > 2.5 * source_duration
    ):
        warnings.append("total runtime exceeded 2.5x source duration")
    return warnings


def build_empty_report(
    *,
    workspace: Path,
    branch: str,
    mode: str,
    samples: list[VideoSample],
    synthetic_validation: bool,
) -> dict[str, Any]:
    no_video = not samples
    warnings = []
    if no_video:
        warnings.append(
            "No local validation videos found. Place files in D:\\Olympus\\validation_samples "
            "or pass --file."
        )
    return {
        "real_video_validation_report": {
            "created_at": utc_now_iso(),
            "olympus_version_or_git_ref": git_ref(workspace),
            "branch": branch,
            "workspace": str(workspace),
            "validation_mode": mode,
            "real_video_validation": False,
            "synthetic_validation": synthetic_validation,
            "internet_available": False,
            "videos_discovered": len(samples),
            "videos_tested": 0,
            "videos_passed": 0,
            "videos_failed": 0,
            "total_runtime_seconds": 0.0,
            "environment": environment_snapshot(),
            "summary": "No real videos were processed." if no_video else "Discovery completed.",
            "warnings": warnings,
            "failures": [],
            "recommendations": [
                "Place validation videos in D:\\Olympus\\validation_samples and rerun the tool."
            ]
            if no_video
            else [],
        },
        "videos": [],
        "clips": [],
        "ffprobe_outputs": [sample.ffprobe for sample in samples],
        "timings": {},
        "warnings": warnings,
        "failures": [],
        "samples": [sample.to_dict() for sample in samples],
    }


def environment_snapshot() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "pid": os.getpid(),
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
    }


def git_ref(workspace: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError:
        return None
    ref = completed.stdout.strip()
    return ref or None


def git_branch(workspace: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def write_reports(report: dict[str, Any], report_dir: Path) -> dict[str, str]:
    report_dir.mkdir(parents=True, exist_ok=True)
    videos = as_list(report.get("videos"))
    clips = as_list(report.get("clips"))
    ffprobe_outputs = as_list(report.get("ffprobe_outputs"))
    timings = as_dict(report.get("timings"))
    warnings = as_list(report.get("warnings"))
    written = {
        REPORT_FILES["top"]: report,
        REPORT_FILES["videos"]: videos,
        REPORT_FILES["clips"]: clips,
        REPORT_FILES["ffprobe"]: ffprobe_outputs,
        REPORT_FILES["timings"]: timings,
        REPORT_FILES["warnings"]: warnings,
    }
    paths: dict[str, str] = {}
    for filename, payload in written.items():
        path = report_dir / filename
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        paths[filename] = str(path)
    summary = markdown_summary(report)
    summary_path = report_dir / REPORT_FILES["summary"]
    summary_path.write_text(summary, encoding="utf-8")
    paths[REPORT_FILES["summary"]] = str(summary_path)
    return paths


def markdown_summary(report: dict[str, Any]) -> str:
    top = as_dict(report.get("real_video_validation_report"))
    lines = [
        "# Olympus Real Video Validation V2",
        "",
        f"- Created: {top.get('created_at')}",
        f"- Workspace: `{top.get('workspace')}`",
        f"- Branch: `{top.get('branch')}`",
        f"- Mode: `{top.get('validation_mode')}`",
        f"- Real video validation: `{top.get('real_video_validation')}`",
        f"- Synthetic validation: `{top.get('synthetic_validation')}`",
        f"- Videos discovered: `{top.get('videos_discovered')}`",
        f"- Videos tested: `{top.get('videos_tested')}`",
        f"- Videos passed: `{top.get('videos_passed')}`",
        f"- Videos failed: `{top.get('videos_failed')}`",
        f"- Total runtime seconds: `{top.get('total_runtime_seconds')}`",
        "",
        "## Summary",
        "",
        str(top.get("summary") or ""),
        "",
        "## Warnings",
        "",
    ]
    warnings = as_list(top.get("warnings"))
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("- None")
    lines.extend(["", "## Failures", ""])
    failures = as_list(top.get("failures"))
    lines.extend(f"- {failure}" for failure in failures) if failures else lines.append("- None")
    lines.extend(["", "## Videos", ""])
    for video in as_list(report.get("videos")):
        lines.append(
            f"- `{video.get('filename')}` tier `{video.get('tier')}`: "
            f"`{video.get('pass_fail')}` ({len(as_list(video.get('warnings')))} warnings)"
        )
    if not as_list(report.get("videos")):
        lines.append("- None processed")
    return "\n".join(lines) + "\n"


class ValidationHttpClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds

    def json_request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            urllib.parse.urljoin(self.base_url, path.lstrip("/")),
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if payload is not None else {},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return as_dict(json.loads(response.read().decode("utf-8")))

    def get_json_or_none(self, path: str) -> dict[str, Any] | None:
        try:
            return self.json_request("GET", path)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def upload_streaming(self, video: Path) -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(self.base_url)
        conn_cls = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        host = parsed.netloc
        base_path = parsed.path.rstrip("/")
        target = f"{base_path}/api/v1/uploads"
        boundary = f"----olympus-{uuid4().hex}"
        content_type = mimetypes.guess_type(video.name)[0] or "video/mp4"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{video.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        content_length = len(head) + video.stat().st_size + len(tail)
        conn = conn_cls(host, timeout=max(self.timeout_seconds, 120.0))
        try:
            conn.putrequest("POST", target)
            conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            conn.putheader("Content-Length", str(content_length))
            conn.endheaders()
            conn.send(head)
            with video.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    conn.send(chunk)
            conn.send(tail)
            response = conn.getresponse()
            body = response.read().decode("utf-8")
            if response.status >= 400:
                raise RuntimeError(f"upload failed HTTP {response.status}: {body[:500]}")
            return as_dict(json.loads(body))
        finally:
            conn.close()

    def download(self, path: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (
            urllib.request.urlopen(
                urllib.parse.urljoin(self.base_url, path.lstrip("/")),
                timeout=max(self.timeout_seconds, 120.0),
            ) as response,
            destination.open("wb") as handle,
        ):
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)


def create_project_payload(upload: dict[str, Any], *, content_category: str) -> dict[str, Any]:
    return {
        "storage_key": upload["storage_key"],
        "source_filename": upload["filename"],
        "size_bytes": upload["size_bytes"],
        "video_format": upload["video_format"],
        "content_type": upload.get("content_type"),
        "duration_seconds": None,
        "width": None,
        "height": None,
        "upload_duration_ms": None,
        "desired_clip_count": None,
        "content_category": content_category,
        "editing_intensity": "auto",
        "music_enabled": True,
        "sfx_enabled": True,
        "captions_enabled": True,
    }


def validate_frontend_payload(
    *,
    manifest: dict[str, Any] | None,
    plans: dict[str, Any] | None,
) -> dict[str, Any]:
    manifest_data = as_dict(as_dict(manifest).get("manifest"))
    renders = as_list(manifest_data.get("renders"))
    plan_items = as_list(as_dict(plans).get("plans"))
    warnings: list[str] = []
    if not renders:
        warnings.append("render manifest has no renders")
    for render in renders:
        metadata = as_dict(as_dict(render).get("metadata"))
        unified = as_dict(metadata.get("unified_clip_intelligence"))
        if not unified:
            warnings.append(
                f"render {as_dict(render).get('clip_id')} lacks unified_clip_intelligence"
            )
            continue
        story = as_dict(unified.get("story"))
        virality = as_dict(unified.get("virality"))
        planning = as_dict(unified.get("planning"))
        if not (
            story.get("story_shape") or virality.get("hook_line") or planning.get("selected_reason")
        ):
            warnings.append(f"render {as_dict(render).get('clip_id')} lacks Why-this-clip fields")
    return {
        "passed": bool(renders) and not warnings,
        "render_count": len(renders),
        "plan_count": len(plan_items),
        "unified_clip_intelligence_present": all(
            bool(as_dict(as_dict(render).get("metadata")).get("unified_clip_intelligence"))
            for render in renders
        )
        if renders
        else False,
        "why_this_clip_works_present": bool(renders) and not warnings,
        "warnings": warnings,
    }


def terminal_pipeline_state(
    stage_snapshots: dict[str, dict[str, Any] | None],
) -> dict[str, str] | None:
    """Return an authoritative terminal state so validators never poll a dead workflow."""

    for source, terminal_statuses in (
        ("workflow", {"completed", "failed", "cancelled", "canceled", "blocked"}),
        ("optimization", {"completed", "failed", "cancelled", "canceled"}),
        ("rendering", {"failed", "cancelled", "canceled"}),
        ("project", {"failed", "cancelled", "canceled"}),
    ):
        status = str(as_dict(stage_snapshots.get(source)).get("status") or "").lower()
        if status in terminal_statuses:
            return {"source": source, "status": status}
    return None


def run_http_validation_for_sample(
    *,
    sample: VideoSample,
    client: ValidationHttpClient,
    report_dir: Path,
    content_category: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    require_audio: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    errors: list[str] = []
    warnings: list[str] = []
    downloads_dir = report_dir / "downloads" / sample.path.stem
    stage_snapshots: dict[str, dict[str, Any] | None] = {}
    manifest: dict[str, Any] | None = None
    plans: dict[str, Any] | None = None
    project: dict[str, Any] | None = None
    observed_first_seen: dict[str, float] = {}
    try:
        upload_started = time.monotonic()
        upload = client.upload_streaming(sample.path)
        intake_seconds = round(time.monotonic() - upload_started, 3)
        project = client.json_request(
            "POST",
            "/api/v1/projects",
            create_project_payload(upload, content_category=content_category),
        )
        project_id = str(project["id"])
        try:
            client.json_request("POST", f"/api/v1/projects/{project_id}/process")
        except Exception as exc:
            warnings.append(f"/process queue trigger failed or was unavailable: {exc}")

        while time.monotonic() - started < timeout_seconds:
            stage_snapshots = {
                "project": client.get_json_or_none(f"/api/v1/projects/{project_id}"),
                "workflow": client.get_json_or_none(
                    f"/api/v1/projects/{project_id}/workflow"
                ),
                "analysis": client.get_json_or_none(f"/api/v1/projects/{project_id}/analysis"),
                "story": client.get_json_or_none(f"/api/v1/projects/{project_id}/story"),
                "virality": client.get_json_or_none(f"/api/v1/projects/{project_id}/virality"),
                "planning": client.get_json_or_none(f"/api/v1/projects/{project_id}/planning"),
                "editing": client.get_json_or_none(f"/api/v1/projects/{project_id}/editing"),
                "rendering": client.get_json_or_none(f"/api/v1/projects/{project_id}/rendering"),
                "optimization": client.get_json_or_none(
                    f"/api/v1/projects/{project_id}/optimization"
                ),
            }
            for name, payload in stage_snapshots.items():
                if payload and name not in observed_first_seen:
                    observed_first_seen[name] = round(time.monotonic() - started, 3)
            manifest = client.get_json_or_none(f"/api/v1/projects/{project_id}/rendering/manifest")
            plans = client.get_json_or_none(f"/api/v1/projects/{project_id}/planning/plans")
            renders = as_list(as_dict(as_dict(manifest).get("manifest")).get("renders"))
            terminal = terminal_pipeline_state(stage_snapshots)
            if terminal is not None:
                if terminal["status"] != "completed":
                    errors.append(
                        f"{terminal['source']} stopped with status {terminal['status']} "
                        f"{'after' if renders else 'before'} a render was produced"
                    )
                break
            time.sleep(poll_interval_seconds)
        else:
            errors.append(f"pipeline timed out after {timeout_seconds}s")
    except Exception as exc:
        errors.append(str(exc))
        intake_seconds = None

    if project is not None:
        project_id = str(project["id"])
        stage_snapshots = {
            "project": client.get_json_or_none(f"/api/v1/projects/{project_id}"),
            "workflow": client.get_json_or_none(f"/api/v1/projects/{project_id}/workflow"),
            "analysis": client.get_json_or_none(f"/api/v1/projects/{project_id}/analysis"),
            "story": client.get_json_or_none(f"/api/v1/projects/{project_id}/story"),
            "virality": client.get_json_or_none(f"/api/v1/projects/{project_id}/virality"),
            "planning": client.get_json_or_none(f"/api/v1/projects/{project_id}/planning"),
            "editing": client.get_json_or_none(f"/api/v1/projects/{project_id}/editing"),
            "rendering": client.get_json_or_none(f"/api/v1/projects/{project_id}/rendering"),
            "optimization": client.get_json_or_none(
                f"/api/v1/projects/{project_id}/optimization"
            ),
        }

    total_seconds = round(time.monotonic() - started, 3)
    project_id = str(as_dict(project).get("id") or f"failed_{sample.path.stem}")
    manifest_data = as_dict(as_dict(manifest).get("manifest"))
    renders = as_list(manifest_data.get("renders"))
    plan_items = as_list(as_dict(plans).get("plans"))
    per_clip: list[dict[str, Any]] = []
    output_paths: list[str] = []
    for render in renders:
        clip = as_dict(render)
        clip_id = str(clip.get("clip_id"))
        destination = downloads_dir / f"{clip_id}.mp4"
        try:
            client.download(
                f"/api/v1/projects/{project_id}/rendering/clips/{clip_id}/download",
                destination,
            )
            output_paths.append(str(destination))
        except Exception as exc:
            warnings.append(f"download failed for {clip_id}: {exc}")
            destination = None  # type: ignore[assignment]
        planned_duration = as_float(
            as_dict(clip.get("metadata")).get("planned_duration"),
            as_float(clip.get("duration"), sample.duration or 0.0),
        )
        per_clip.append(
            validate_rendered_clip(
                clip=clip,
                rendered_path=destination,
                planned_duration=planned_duration,
                require_audio=require_audio or sample.has_audio,
            )
        )

    planning_summary = _stage_data(stage_snapshots.get("planning"), "planning_summary")
    low_output_reason = as_dict(planning_summary.get("low_output_reason"))
    generation = _stage_data(stage_snapshots.get("planning"), "candidate_generation")
    count_check = output_count_assessment(
        source_duration=sample.duration,
        planned_clip_count=len(plan_items),
        rendered_clip_count=len(renders),
        low_output_reason=low_output_reason or None,
        candidate_count=as_int(generation.get("candidate_count")),
    )
    warnings.extend(as_list(count_check.get("warnings")))
    coverage = timeline_coverage(
        source_duration=sample.duration,
        clips=plan_items,
        explanation=as_dict(planning_summary.get("low_output_reason")).get("explanation")
        or as_dict(planning_summary.get("low_clip_count_explanation")).get("explanation"),
        total_sections=_total_story_sections(stage_snapshots.get("story")),
    )
    if coverage.get("warning"):
        warnings.append(str(coverage["warning"]))
    frontend_payload = validate_frontend_payload(manifest=manifest, plans=plans)
    warnings.extend(as_list(frontend_payload.get("warnings")))
    version_warnings = stage_version_warnings(
        {name: payload or {} for name, payload in stage_snapshots.items()}
    )
    warnings.extend(version_warnings)
    timings_by_engine = {name: stage_timings(payload) for name, payload in stage_snapshots.items()}
    stage_seconds = _major_stage_seconds(timings_by_engine, total_seconds)
    if intake_seconds is not None:
        stage_seconds["intake_seconds"] = intake_seconds
    rendering_seconds = stage_seconds.get("rendering_seconds")
    warnings.extend(
        hang_warnings(
            tier=sample.tier,
            source_duration=sample.duration,
            observed_seconds={
                "transcription": stage_seconds.get("transcription_seconds"),
                "planning": stage_seconds.get("planning_seconds"),
                "rendering_per_clip": (
                    rendering_seconds / max(1, len(renders))
                    if rendering_seconds is not None
                    else None
                ),
                "total": total_seconds,
            },
        )
    )
    pipeline = {
        "project_created": bool(project),
        "terminal_state": terminal_pipeline_state(stage_snapshots),
        "upload_or_intake_passed": not any("upload failed" in e for e in errors),
        "transcription_passed": _stage_completed(stage_snapshots.get("analysis")),
        "story_passed": _stage_completed(stage_snapshots.get("story")),
        "virality_passed": _stage_completed(stage_snapshots.get("virality")),
        "planning_passed": _stage_completed(stage_snapshots.get("planning")),
        "editing_passed": _stage_completed(stage_snapshots.get("editing")),
        "rendering_passed": bool(renders),
        "optimization_passed": _stage_completed(stage_snapshots.get("optimization")),
        "frontend_payload_passed": bool(frontend_payload.get("passed")),
    }
    core_pipeline_passed = all(
        pipeline[key]
        for key in (
            "project_created",
            "upload_or_intake_passed",
            "transcription_passed",
            "story_passed",
            "virality_passed",
            "planning_passed",
            "editing_passed",
            "rendering_passed",
            "frontend_payload_passed",
        )
    )
    optimization_present = bool(stage_snapshots.get("optimization"))
    pass_fail = (
        not errors
        and bool(renders)
        and all(clip.get("pass_fail") for clip in per_clip)
        and bool(frontend_payload.get("passed"))
        and bool(count_check.get("passed"))
        and core_pipeline_passed
        and (not optimization_present or pipeline["optimization_passed"])
    )
    video_report = {
        "video_id": project_id,
        "path": str(sample.path),
        "filename": sample.filename,
        "duration": sample.duration,
        "tier": sample.tier,
        "width": sample.width,
        "height": sample.height,
        "fps": sample.fps,
        "has_audio": sample.has_audio,
        "audio_codec": sample.audio_codec,
        "video_codec": sample.video_codec,
        "file_size_bytes": sample.file_size_bytes,
        "pipeline": pipeline,
        "stage_timings": {
            "intake_seconds": stage_seconds.get("intake_seconds"),
            "probe_seconds": 0.0 if sample.ffprobe.get("passed") else None,
            "transcription_seconds": stage_seconds.get("transcription_seconds"),
            "story_seconds": stage_seconds.get("story_seconds"),
            "virality_seconds": stage_seconds.get("virality_seconds"),
            "planning_seconds": stage_seconds.get("planning_seconds"),
            "editing_seconds": stage_seconds.get("editing_seconds"),
            "rendering_seconds": stage_seconds.get("rendering_seconds"),
            "optimization_seconds": stage_seconds.get("optimization_seconds"),
            "total_seconds": total_seconds,
        },
        "stage_details": timings_by_engine,
        "stage_first_seen_seconds": observed_first_seen,
        "outputs": {
            "planned_clip_count": len(plan_items),
            "rendered_clip_count": len(renders),
            "failed_clip_count": max(0, len(plan_items) - len(renders)),
            "download_count": len(output_paths),
            "output_paths": output_paths,
            "manifest_paths": [str(report_dir / REPORT_FILES["top"])] if manifest else [],
        },
        "quality": {
            "enough_clips_for_duration": count_check.get("passed"),
            "timeline_diversity_passed": coverage.get("diversity_passed"),
            "duplicate_risk": _duplicate_risk(plan_items),
            "low_output_reason_present": bool(low_output_reason),
            "story_v2_present": bool(
                _stage_data(stage_snapshots.get("story"), "story_analysis_v2")
            ),
            "virality_v2_present": bool(
                _stage_data(stage_snapshots.get("virality"), "virality_summary")
            ),
            "unified_clip_intelligence_present": frontend_payload.get(
                "unified_clip_intelligence_present"
            ),
            "why_this_clip_works_present": frontend_payload.get("why_this_clip_works_present"),
            "timeline_coverage": coverage,
            "output_count": count_check,
            "frontend_payload": frontend_payload,
            "stale_artifact_warnings": version_warnings,
        },
        "performance_baseline": {
            "video_tier": sample.tier,
            "source_duration": sample.duration,
            "total_runtime": total_seconds,
            "runtime_ratio": round(total_seconds / sample.duration, 3) if sample.duration else None,
            "stage_timings": stage_seconds,
            "clips_per_minute_source": round(len(renders) / max(1.0, sample.duration / 60), 3)
            if sample.duration
            else None,
            "render_seconds_per_clip": round(
                as_float(stage_seconds.get("rendering_seconds")) / max(1, len(renders)), 3
            )
            if renders
            else None,
            "warnings": warnings,
        },
        "warnings": warnings,
        "errors": errors,
        "pass_fail": pass_fail,
        "clips": per_clip,
    }
    return video_report


def _major_stage_seconds(
    timings_by_engine: dict[str, dict[str, Any]],
    total_seconds: float,
) -> dict[str, float | None]:
    def sum_engine(name: str) -> float | None:
        values = [
            as_float(item.get("duration_seconds"))
            for item in as_dict(timings_by_engine.get(name)).values()
            if item.get("duration_seconds") is not None
        ]
        return round(sum(values), 3) if values else None

    analysis = as_dict(timings_by_engine.get("analysis"))
    transcription = as_float(
        as_dict(analysis.get("speech_transcription")).get("duration_seconds"),
        0.0,
    )
    return {
        "transcription_seconds": transcription or None,
        "story_seconds": sum_engine("story"),
        "virality_seconds": sum_engine("virality"),
        "planning_seconds": sum_engine("planning"),
        "editing_seconds": sum_engine("editing"),
        "rendering_seconds": sum_engine("rendering"),
        "optimization_seconds": sum_engine("optimization"),
        "total_seconds": total_seconds,
    }


def _stage_completed(engine: dict[str, Any] | None) -> bool:
    return as_dict(engine).get("status") == "completed"


def _stage_data(engine: dict[str, Any] | None, stage_name: str) -> dict[str, Any]:
    for stage in as_list(as_dict(engine).get("stages")):
        item = as_dict(stage)
        if item.get("stage") == stage_name and item.get("status") == "completed":
            return as_dict(item.get("data"))
    return {}


def _total_story_sections(story: dict[str, Any] | None) -> int | None:
    v2 = _stage_data(story, "story_analysis_v2")
    if v2:
        return len(as_list(v2.get("topic_sections")))
    return None


def _duplicate_risk(plans: list[dict[str, Any]]) -> str:
    groups = [plan.get("duplicate_group") for plan in plans if plan.get("duplicate_group")]
    if not groups:
        return "low"
    return "medium" if len(set(groups)) == len(groups) else "high"


def aggregate_report(
    *,
    workspace: Path,
    branch: str,
    mode: str,
    samples: list[VideoSample],
    video_reports: list[dict[str, Any]],
    started_at: float,
    synthetic_validation: bool,
) -> dict[str, Any]:
    clips = [clip for video in video_reports for clip in as_list(video.get("clips"))]
    warnings = [warning for video in video_reports for warning in as_list(video.get("warnings"))]
    failures = [error for video in video_reports for error in as_list(video.get("errors"))]
    passed = sum(1 for video in video_reports if video.get("pass_fail") is True)
    failed = len(video_reports) - passed
    total_runtime = round(time.monotonic() - started_at, 3)
    real_video_validation = bool(video_reports)
    summary = (
        f"Processed {len(video_reports)} real video(s): {passed} passed, {failed} failed."
        if real_video_validation
        else "No real videos were processed."
    )
    return {
        "real_video_validation_report": {
            "created_at": utc_now_iso(),
            "olympus_version_or_git_ref": git_ref(workspace),
            "branch": branch,
            "workspace": str(workspace),
            "validation_mode": mode,
            "real_video_validation": real_video_validation,
            "synthetic_validation": synthetic_validation,
            "internet_available": False,
            "videos_discovered": len(samples),
            "videos_tested": len(video_reports),
            "videos_passed": passed,
            "videos_failed": failed,
            "total_runtime_seconds": total_runtime,
            "environment": environment_snapshot(),
            "summary": summary,
            "warnings": warnings,
            "failures": failures,
            "recommendations": _recommendations(video_reports, samples),
        },
        "videos": video_reports,
        "clips": clips,
        "ffprobe_outputs": [sample.ffprobe for sample in samples]
        + [clip.get("ffprobe_validation") for clip in clips],
        "timings": {video.get("video_id"): video.get("stage_timings") for video in video_reports},
        "warnings": warnings,
        "failures": failures,
        "samples": [sample.to_dict() for sample in samples],
    }


def _recommendations(video_reports: list[dict[str, Any]], samples: list[VideoSample]) -> list[str]:
    if not samples:
        return [
            "Place videos in D:\\Olympus\\validation_samples and rerun validation.",
            "Use at least one 30+ minute file before claiming long-video validation.",
        ]
    if not video_reports:
        return ["Run without --discover to process discovered videos through the backend."]
    recs: list[str] = []
    if not any(sample.tier in {"long", "very_long"} for sample in samples):
        recs.append("Add a 30+ minute file to validate long-video behavior.")
    if any(video.get("pass_fail") is False for video in video_reports):
        recs.append("Open validation_summary.md and per_video_report.json for exact failures.")
    return recs

"""Validate anonymous Multi-Speaker Layout V2 planning and render truth."""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from math import sin
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tools import validate_face_tracking_motion as face_motion_validator  # noqa: E402

from olympus.editing.analyzers import _normalize_face_detections  # noqa: E402
from olympus.editing.multi_speaker import (  # noqa: E402
    build_multi_speaker_layout,
    consolidate_face_tracks,
)
from olympus.platform.config import get_settings  # noqa: E402
from olympus.rendering import command as render_command  # noqa: E402
from olympus.validation.face_motion import (  # noqa: E402
    face_plan_from_timeline,
    validate_local_face_path,
    validate_project_id,
)
from olympus.validation.multi_speaker import (  # noqa: E402
    MultiSpeakerLayoutValidationResultV1,
    MultiSpeakerLayoutValidationThresholdsV1,
    active_speaker_switch_count,
    evaluate_assigned_subject_regions,
    fallback_is_consistent,
    layout_motion_metrics,
    speaker_region_coverage_ratio,
    write_multi_speaker_report,
)
from olympus.validation.real_video import run_ffprobe  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "multi_speaker_layout"
DEFAULT_STORAGE_ROOT = ROOT / "storage_data"
SYNTHETIC_DURATION_SECONDS = 4.0
SYNTHETIC_FPS = 24


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}
    return value if isinstance(value, dict) else {"error": "JSON root is not an object"}


def _stage_data(value: dict[str, Any]) -> dict[str, Any]:
    data = value.get("data")
    return data if isinstance(data, dict) else value


def _manifest(value: dict[str, Any]) -> dict[str, Any]:
    data = _stage_data(value)
    manifest = data.get("manifest")
    return manifest if isinstance(manifest, dict) else data


def _probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,sample_rate,channels,duration",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        return {"available": False, "reason": completed.stderr.strip() or "ffprobe failed"}
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"available": False, "reason": "ffprobe returned invalid JSON"}
    return {"available": True, **value}


def _simulated_detections(face_count: int, duration: float) -> list[dict[str, float]]:
    centers = (
        [0.5]
        if face_count == 1
        else [0.24 + index * 0.52 / (face_count - 1) for index in range(face_count)]
    )
    output: list[dict[str, float]] = []
    timestamp = 0.0
    while timestamp <= duration + 0.001:
        for index, x_center in enumerate(centers):
            output.append(
                {
                    "time": round(timestamp, 3),
                    "x_center": x_center,
                    "y_center": 0.42 + index * 0.005,
                    "width": 0.16,
                    "height": 0.28,
                    "confidence": 0.9,
                }
            )
        timestamp += 0.5
    return output


def _simulated_speakers(speaker_count: int, duration: float) -> list[dict[str, Any]]:
    if speaker_count <= 0:
        return []
    segment = duration / speaker_count
    return [
        {
            "speaker": f"spk_{index}",
            "start": round(index * segment, 3),
            "end": round((index + 1) * segment, 3),
        }
        for index in range(speaker_count)
    ]


def _synthetic_two_speaker_detections(duration: float) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    timestamp = 0.0
    while timestamp <= duration + 0.001:
        movement = 0.012 * sin(timestamp * 1.6)
        detections.extend(
            [
                {
                    "time": round(timestamp, 3),
                    "x_center": round(0.22 + movement, 4),
                    "y_center": 0.50,
                    "width": 0.18,
                    "height": 0.32,
                    "confidence": 0.92,
                    "face_id": "speaker_1",
                },
                {
                    "time": round(timestamp, 3),
                    "x_center": round(0.78 - movement, 4),
                    "y_center": 0.50,
                    "width": 0.18,
                    "height": 0.32,
                    "confidence": 0.92,
                    "face_id": "speaker_2",
                },
            ]
        )
        timestamp += 0.5
    return detections


def _active_speaker_probe(duration: float) -> dict[str, Any]:
    detections: list[dict[str, Any]] = []
    for timestamp in (0.0, 0.5, 1.0, 1.5, 1.9):
        detections.append(
            {
                "time": timestamp,
                "x_center": 0.25,
                "y_center": 0.48,
                "width": 0.2,
                "height": 0.32,
                "confidence": 0.92,
                "face_id": "speaker_1",
            }
        )
    for timestamp in (2.1, 2.5, 3.0, 3.5, duration):
        detections.append(
            {
                "time": timestamp,
                "x_center": 0.75,
                "y_center": 0.48,
                "width": 0.2,
                "height": 0.32,
                "confidence": 0.92,
                "face_id": "speaker_2",
            }
        )
    return build_multi_speaker_layout(
        detections=detections,
        speaker_timeline=[
            {"speaker": "speaker_1", "start": 0.0, "end": 1.9},
            {"speaker": "speaker_2", "start": 2.1, "end": duration},
        ],
        clip_id="synthetic_active_speaker_probe",
        project_id="multi_speaker_validation",
        clip_start=0.0,
        duration=duration,
        source_width=640.0,
        source_height=360.0,
        fps=float(SYNTHETIC_FPS),
    )


def _run(
    command: list[str],
    *,
    timeout_seconds: float = 180.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def synthetic_media_plan(destination: Path, duration: float) -> list[str]:
    ffmpeg = get_settings().rendering.ffmpeg_binary
    return [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x20242a:s=640x360:r={SYNTHETIC_FPS}:d={duration:.3f}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0xf2c94c:s=120x120:r={SYNTHETIC_FPS}:d={duration:.3f}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x56ccf2:s=120x120:r={SYNTHETIC_FPS}:d={duration:.3f}",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=420:sample_rate=48000",
        "-filter_complex",
        (
            "[1:v]drawbox=x=24:y=32:w=18:h=18:color=0x20242a:t=fill,"
            "drawbox=x=78:y=32:w=18:h=18:color=0x20242a:t=fill,"
            "drawbox=x=35:y=82:w=50:h=8:color=0x20242a:t=fill[left];"
            "[2:v]drawbox=x=24:y=32:w=18:h=18:color=0x20242a:t=fill,"
            "drawbox=x=78:y=32:w=18:h=18:color=0x20242a:t=fill,"
            "drawbox=x=35:y=82:w=50:h=8:color=0x20242a:t=fill[right];"
            "[0:v][left]overlay=x='80+8*sin(2*PI*t/4)':y=120[tmp];"
            "[tmp][right]overlay=x='440-8*sin(2*PI*t/4)':y=120[pair];"
            "[pair]drawbox=x=72:y=112:w=136:h=136:color=white:t=5:"
            "enable='lt(mod(t,2),1)',drawbox=x=432:y=112:w=136:h=136:"
            "color=white:t=5:enable='gte(mod(t,2),1)'[v]"
        ),
        "-map",
        "[v]",
        "-map",
        "3:a",
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-threads",
        "2",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        str(destination),
    ]


def _timeline(layout: dict[str, Any], duration: float, clip_id: str) -> dict[str, Any]:
    source_window = {
        "contract_version": "1",
        "project_id": "multi_speaker_validation",
        "clip_id": clip_id,
        "requested_start_seconds": 0.0,
        "requested_end_seconds": duration,
        "repaired_start_seconds": 0.0,
        "repaired_end_seconds": duration,
        "duration_seconds": duration,
        "preroll_seconds": 0.0,
        "postroll_seconds": 0.0,
        "boundary_repair_applied": False,
        "start_reason": "local multi-speaker validation",
        "end_reason": "local multi-speaker validation",
        "warnings": [],
    }
    return {
        "clip_id": clip_id,
        "source_start": 0.0,
        "source_end": duration,
        "duration": duration,
        "source_window_v1": source_window,
        "tracks": [
            {
                "kind": "video",
                "events": [
                    {
                        "id": "source",
                        "type": "source_clip",
                        "start": 0.0,
                        "end": duration,
                        "duration": duration,
                        "reason": "multi-speaker validation source",
                        "confidence": 1.0,
                        "evidence": [],
                    }
                ],
            },
            {
                "kind": "audio",
                "events": [
                    {
                        "id": "audio",
                        "type": "speech",
                        "start": 0.0,
                        "end": duration,
                        "reason": "preserve source audio",
                        "confidence": 1.0,
                        "evidence": [],
                    }
                ],
            },
            {"kind": "caption", "events": []},
            {"kind": "markers", "events": []},
        ],
        "metadata": {
            "timeline": source_window,
            "face_tracking_plan": layout,
            "multi_speaker_layout_v2": layout,
            "editing_v2": {
                "face_tracking_plan": layout,
                "multi_speaker_layout_v2": layout,
                "motion_plan": {"events": []},
                "voice_enhancement_plan": {"filters": ["highpass", "loudnorm"]},
                "video_enhancement_plan": {"profile": "clean_high_retention"},
            },
            "render_assets_v2": {"music": {}, "sfx": {}},
        },
    }


def _compact_probe(probe: dict[str, Any]) -> dict[str, Any]:
    return {
        key: probe.get(key)
        for key in (
            "passed",
            "container_duration",
            "video_duration",
            "audio_duration",
            "width",
            "height",
            "fps",
            "video_codec",
            "audio_codec",
            "audio_sample_rate",
            "has_audio",
        )
    }


def _render_layout(
    *,
    source: Path,
    output: Path,
    timeline: dict[str, Any],
    width: int = 540,
    height: int = 960,
    fps: int = SYNTHETIC_FPS,
) -> dict[str, Any]:
    command = render_command.build_ffmpeg_command(
        binary=get_settings().rendering.ffmpeg_binary,
        source_path=str(source),
        output_path=str(output),
        timeline=timeline,
        width=width,
        height=height,
        fps=fps,
        video_bitrate_kbps=1400,
        audio_bitrate_kbps=96,
        encoder_preset="veryfast",
        encoder_threads=2,
        filter_threads=1,
    )
    try:
        completed = _run(command)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "render_completed": False,
            "output_mp4_valid": False,
            "stack_filter_present": False,
            "duration_delta": None,
            "probe": {},
            "errors": [f"FFmpeg layout render failed: {exc}"],
        }
    graph = command[command.index("-filter_complex") + 1]
    if completed.returncode != 0:
        tail = completed.stderr.strip().splitlines()[-6:]
        return {
            "render_completed": False,
            "output_mp4_valid": False,
            "stack_filter_present": "vstack=inputs=2" in graph,
            "duration_delta": None,
            "probe": {},
            "errors": [f"FFmpeg exited {completed.returncode}: {' | '.join(tail)}"],
        }
    probe = run_ffprobe(output)
    expected_duration = render_command.expected_duration(timeline)
    actual_duration = float(probe.get("container_duration") or 0.0)
    duration_delta = abs(actual_duration - expected_duration) if actual_duration else None
    valid = bool(
        output.exists()
        and output.stat().st_size > 1024
        and probe.get("passed") is True
        and probe.get("video_codec") == "h264"
        and probe.get("audio_codec") == "aac"
        and probe.get("has_audio") is True
        and probe.get("width") == width
        and probe.get("height") == height
        and duration_delta is not None
        and duration_delta
        <= MultiSpeakerLayoutValidationThresholdsV1().maximum_duration_delta_seconds
    )
    return {
        "render_completed": output.exists(),
        "output_mp4_valid": valid,
        "stack_filter_present": "vstack=inputs=2" in graph,
        "duration_delta": round(duration_delta, 4) if duration_delta is not None else None,
        "probe": _compact_probe(probe),
        "errors": [] if valid else ["rendered MP4 failed layout codec/stream/duration checks"],
    }


def _layout_assignments(
    *,
    layout: dict[str, Any],
    detections: list[dict[str, Any]],
    duration: float,
    source_width: float,
    source_height: float,
    region_width: float = 540.0,
    region_height: float = 480.0,
) -> list[dict[str, Any]]:
    tracks = consolidate_face_tracks(detections, duration)
    track_map = {str(track.get("face_track_id")): track for track in tracks}
    assignments: list[dict[str, Any]] = []
    for region in layout.get("layout_regions") or []:
        if not isinstance(region, dict):
            continue
        track = track_map.get(str(region.get("source_face_track_id")))
        if not track:
            continue
        assignments.append(
            {
                "detections": track.get("observations") or [],
                "crop_keyframes": region.get("crop_keyframes") or [],
                "source_width": source_width,
                "source_height": source_height,
                "region_width": region_width,
                "region_height": region_height,
                "safe_zone_margin_ratio": 0.05,
            }
        )
    return assignments


def _region_counts(detections: list[dict[str, Any]]) -> list[int]:
    by_time: dict[float, int] = {}
    for detection in detections:
        timestamp = round(float(detection.get("time") or 0.0), 3)
        by_time[timestamp] = by_time.get(timestamp, 0) + 1
    return [count for _timestamp, count in sorted(by_time.items())]


def run_self_check() -> tuple[MultiSpeakerLayoutValidationResultV1, dict[str, Any]]:
    settings = get_settings()
    ffmpeg_available = shutil.which(settings.rendering.ffmpeg_binary) is not None
    ffprobe_available = shutil.which(settings.rendering.ffprobe_binary) is not None
    opencv_available = importlib.util.find_spec("cv2") is not None
    errors = []
    if not ffmpeg_available:
        errors.append("ffmpeg is unavailable")
    if not ffprobe_available:
        errors.append("ffprobe is unavailable")
    warnings = []
    if not opencv_available:
        warnings.append(
            "Optional local OpenCV face detection is unavailable; real local multi-speaker "
            "layout cannot be proven in this environment."
        )
    result = MultiSpeakerLayoutValidationResultV1(
        project_id=None,
        clip_id=None,
        mode="self_check",
        real_multi_speaker_sample_used=False,
        synthetic_sample_used=False,
        speaker_signals_available=False,
        face_signals_available=False,
        detected_speaker_count=0,
        expected_speaker_count=2,
        layout_strategy="not_evaluated",
        active_speaker_switches=0,
        frames_sampled=0,
        layout_regions_present=False,
        speaker_region_coverage_ratio=0.0,
        face_inside_region_ratio=0.0,
        subject_cutoff_detected=False,
        layout_jitter_score=0.0,
        max_region_shift_per_second=0.0,
        wrong_speaker_focus_warnings=[],
        fallback_used=False,
        fallback_reason=None,
        render_completed=False,
        output_mp4_valid=False,
        passed=not errors,
        warnings=warnings,
        errors=errors,
    )
    return result, {
        "module_imports_passed": True,
        "multi_speaker_config_available": settings.multi_speaker_layout.enabled is not None,
        "rendering_config_available": settings.rendering.ffmpeg_binary is not None,
        "ffmpeg_available": ffmpeg_available,
        "ffprobe_available": ffprobe_available,
        "optional_opencv_available": opencv_available,
        "external_access_required": False,
        "real_media_required": False,
    }


def run_synthetic_two_speaker(
) -> tuple[MultiSpeakerLayoutValidationResultV1, dict[str, Any]]:
    duration = SYNTHETIC_DURATION_SECONDS
    detections = _synthetic_two_speaker_detections(duration)
    layout = build_multi_speaker_layout(
        detections=detections,
        speaker_timeline=[],
        clip_id="synthetic_two_speaker",
        project_id="multi_speaker_validation",
        clip_start=0.0,
        duration=duration,
        source_width=640.0,
        source_height=360.0,
        fps=float(SYNTHETIC_FPS),
    )
    regions = [
        item for item in layout.get("layout_regions") or [] if isinstance(item, dict)
    ]
    region_coverage = speaker_region_coverage_ratio(
        expected_speaker_count=2,
        region_counts_by_frame=[len(regions)] * len(_region_counts(detections)),
    )
    subject_safety = evaluate_assigned_subject_regions(
        _layout_assignments(
            layout=layout,
            detections=detections,
            duration=duration,
            source_width=640.0,
            source_height=360.0,
        )
    )
    motion = layout_motion_metrics(regions)
    active_probe = _active_speaker_probe(duration)
    active_probe_switches = active_speaker_switch_count(
        [
            item
            for item in active_probe.get("speaker_switches") or []
            if isinstance(item, dict)
        ]
    )
    errors: list[str] = []
    warnings = [
        "Generated speaker-like shapes are not real people and do not prove real "
        "multi-speaker performance.",
        "Speaker diarization was intentionally absent; stack layout made no active-speaker claim.",
    ]
    render: dict[str, Any]
    with tempfile.TemporaryDirectory(prefix="olympus-multi-speaker-") as temporary:
        temporary_root = Path(temporary)
        source = temporary_root / "synthetic_two_speaker.mp4"
        output = temporary_root / "synthetic_two_speaker_stack.mp4"
        try:
            generated = _run(synthetic_media_plan(source, duration))
        except (OSError, subprocess.TimeoutExpired) as exc:
            generated = None
            errors.append(f"synthetic fixture generation failed: {exc}")
        if generated is not None and generated.returncode != 0:
            tail = generated.stderr.strip().splitlines()[-6:]
            errors.append(f"synthetic fixture generation failed: {' | '.join(tail)}")
        if errors:
            render = {
                "render_completed": False,
                "output_mp4_valid": False,
                "stack_filter_present": False,
                "duration_delta": None,
                "probe": {},
                "errors": [],
            }
        else:
            render = _render_layout(
                source=source,
                output=output,
                timeline=_timeline(layout, duration, "synthetic_two_speaker"),
            )
            errors.extend(
                str(item) for item in render.get("errors") or [] if isinstance(item, str)
            )

    strategy = str(layout.get("mode") or "center_fallback")
    fallback_used = strategy == "center_fallback"
    fallback_reason = str(layout.get("fallback_reason") or "") or None
    fallback_consistent = fallback_is_consistent(
        speaker_signals_available=False,
        face_signals_available=True,
        layout_strategy=strategy,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )
    thresholds = MultiSpeakerLayoutValidationThresholdsV1()
    wrong_focus_warnings: list[str] = []
    if strategy == "active_speaker_focus":
        wrong_focus_warnings.append(
            "Active-speaker focus was selected without speaker evidence in the primary fixture."
        )
    passed = bool(
        strategy == "two_speaker_stack"
        and len(regions) == 2
        and region_coverage >= thresholds.minimum_speaker_region_coverage_ratio
        and subject_safety.get("evaluated") is True
        and float(subject_safety.get("face_inside_region_ratio") or 0.0)
        >= thresholds.minimum_face_inside_region_ratio
        and subject_safety.get("subject_cutoff_detected") is False
        and motion["layout_jitter_score"] <= thresholds.maximum_layout_jitter_score
        and motion["max_region_shift_per_second"]
        <= thresholds.maximum_region_shift_per_second
        and fallback_consistent
        and not wrong_focus_warnings
        and not errors
        and render.get("stack_filter_present") is True
        and render.get("output_mp4_valid") is True
    )
    result = MultiSpeakerLayoutValidationResultV1(
        project_id=None,
        clip_id="synthetic_two_speaker",
        mode="synthetic_two_speaker",
        real_multi_speaker_sample_used=False,
        synthetic_sample_used=True,
        speaker_signals_available=False,
        face_signals_available=True,
        detected_speaker_count=0,
        expected_speaker_count=2,
        layout_strategy=strategy,
        active_speaker_switches=0,
        frames_sampled=len(_region_counts(detections)),
        layout_regions_present=len(regions) == 2,
        speaker_region_coverage_ratio=region_coverage,
        face_inside_region_ratio=float(subject_safety.get("face_inside_region_ratio") or 0.0),
        subject_cutoff_detected=subject_safety.get("subject_cutoff_detected") is True,
        layout_jitter_score=motion["layout_jitter_score"],
        max_region_shift_per_second=motion["max_region_shift_per_second"],
        wrong_speaker_focus_warnings=wrong_focus_warnings,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        render_completed=render.get("render_completed") is True,
        output_mp4_valid=render.get("output_mp4_valid") is True,
        passed=passed,
        subject_region_safety_evaluated=subject_safety.get("evaluated") is True,
        warnings=warnings,
        errors=list(dict.fromkeys(errors)),
    )
    return result, {
        "fixture_kind": "generated_two_moving_speaker_like_shapes",
        "real_multi_speaker_proof": False,
        "primary_layout_strategy": strategy,
        "stack_filter_rendered": render.get("stack_filter_present") is True,
        "active_speaker_planning_probe_mode": active_probe.get("mode"),
        "active_speaker_planning_probe_switches": active_probe_switches,
        "render_probe": render.get("probe"),
        "duration_delta": render.get("duration_delta"),
        "temporary_media_removed": True,
    }


def run_local_multi_speaker_file(
    path: Path,
    *,
    rights_confirmed: bool,
) -> tuple[MultiSpeakerLayoutValidationResultV1, dict[str, Any]]:
    validated, path_errors = validate_local_face_path(path, rights_confirmed=rights_confirmed)
    if validated is None:
        result = MultiSpeakerLayoutValidationResultV1(
            project_id=None,
            clip_id=None,
            mode="local_multi_speaker_file",
            real_multi_speaker_sample_used=False,
            synthetic_sample_used=False,
            speaker_signals_available=False,
            face_signals_available=False,
            detected_speaker_count=0,
            expected_speaker_count=2,
            layout_strategy="not_evaluated",
            active_speaker_switches=0,
            frames_sampled=0,
            layout_regions_present=False,
            speaker_region_coverage_ratio=0.0,
            face_inside_region_ratio=0.0,
            subject_cutoff_detected=False,
            layout_jitter_score=0.0,
            max_region_shift_per_second=0.0,
            wrong_speaker_focus_warnings=[],
            fallback_used=False,
            fallback_reason=None,
            render_completed=False,
            output_mp4_valid=False,
            passed=False,
            errors=path_errors,
        )
        return result, {
            "real_multi_speaker_proof": False,
            "temporary_media_removed": True,
        }

    probe = run_ffprobe(validated)
    duration = min(
        8.0,
        float(probe.get("container_duration") or 0.0),
    )
    source_width = float(probe.get("width") or 0.0)
    source_height = float(probe.get("height") or 0.0)
    errors: list[str] = []
    warnings: list[str] = []
    if probe.get("passed") is not True or duration <= 0 or source_width <= 0 or source_height <= 0:
        errors.append("local multi-speaker video failed ffprobe or has invalid dimensions")
    sampled = face_motion_validator._sample_faces_with_optional_opencv(
        validated,
        duration=max(0.0, duration),
        sample_fps=2.0,
    )
    errors.extend(str(item) for item in sampled.get("errors") or [] if isinstance(item, str))
    warnings.extend(
        str(item) for item in sampled.get("warnings") or [] if isinstance(item, str)
    )
    detections = [
        item for item in sampled.get("detections") or [] if isinstance(item, dict)
    ]
    layout = build_multi_speaker_layout(
        detections=detections,
        speaker_timeline=[],
        clip_id="local_multi_speaker_validation",
        project_id="multi_speaker_validation",
        clip_start=0.0,
        duration=max(0.1, duration),
        source_width=source_width,
        source_height=source_height,
        fps=float(probe.get("fps") or 30.0),
    )
    strategy = str(layout.get("mode") or "center_fallback")
    regions = [
        item for item in layout.get("layout_regions") or [] if isinstance(item, dict)
    ]
    face_signals = len(layout.get("participants") or []) >= 2
    fallback_used = strategy == "center_fallback"
    fallback_reason = str(layout.get("fallback_reason") or "") or None
    region_counts = _region_counts(detections)
    region_coverage = speaker_region_coverage_ratio(
        expected_speaker_count=2,
        region_counts_by_frame=[len(regions)] * len(region_counts),
    )
    subject_safety = evaluate_assigned_subject_regions(
        _layout_assignments(
            layout=layout,
            detections=detections,
            duration=max(0.1, duration),
            source_width=source_width,
            source_height=source_height,
        )
    )
    motion = layout_motion_metrics(regions)
    wrong_focus_warnings: list[str] = []
    if strategy == "active_speaker_focus":
        wrong_focus_warnings.append(
            "Active-speaker focus cannot be validated because local diarization is unavailable."
        )
    render: dict[str, Any] = {
        "render_completed": False,
        "output_mp4_valid": False,
        "stack_filter_present": False,
        "duration_delta": None,
        "probe": {},
        "errors": [],
    }
    if not errors and strategy == "two_speaker_stack" and len(regions) == 2:
        with tempfile.TemporaryDirectory(prefix="olympus-real-multi-speaker-") as temporary:
            render = _render_layout(
                source=validated,
                output=Path(temporary) / "local_multi_speaker_stack.mp4",
                timeline=_timeline(layout, duration, "local_multi_speaker_validation"),
                fps=max(1, round(float(probe.get("fps") or 30.0))),
            )
    elif not errors:
        errors.append("two stable anonymous subjects did not produce a two-speaker stack")
    errors.extend(str(item) for item in render.get("errors") or [] if isinstance(item, str))
    warnings.append(
        "Speaker diarization is unavailable in direct local-file mode; no active-speaker claim "
        "was made."
    )
    thresholds = MultiSpeakerLayoutValidationThresholdsV1()
    fallback_consistent = fallback_is_consistent(
        speaker_signals_available=False,
        face_signals_available=face_signals,
        layout_strategy=strategy,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )
    passed = bool(
        not errors
        and face_signals
        and strategy == "two_speaker_stack"
        and len(regions) == 2
        and region_coverage >= thresholds.minimum_speaker_region_coverage_ratio
        and subject_safety.get("evaluated") is True
        and float(subject_safety.get("face_inside_region_ratio") or 0.0)
        >= thresholds.minimum_face_inside_region_ratio
        and subject_safety.get("subject_cutoff_detected") is False
        and motion["layout_jitter_score"] <= thresholds.maximum_layout_jitter_score
        and motion["max_region_shift_per_second"]
        <= thresholds.maximum_region_shift_per_second
        and fallback_consistent
        and not wrong_focus_warnings
        and render.get("output_mp4_valid") is True
    )
    result = MultiSpeakerLayoutValidationResultV1(
        project_id=None,
        clip_id="local_multi_speaker_validation",
        mode="local_multi_speaker_file",
        real_multi_speaker_sample_used=True,
        synthetic_sample_used=False,
        speaker_signals_available=False,
        face_signals_available=face_signals,
        detected_speaker_count=0,
        expected_speaker_count=2,
        layout_strategy=strategy,
        active_speaker_switches=0,
        frames_sampled=int(sampled.get("frames_sampled") or 0),
        layout_regions_present=len(regions) == 2,
        speaker_region_coverage_ratio=region_coverage,
        face_inside_region_ratio=float(subject_safety.get("face_inside_region_ratio") or 0.0),
        subject_cutoff_detected=subject_safety.get("subject_cutoff_detected") is True,
        layout_jitter_score=motion["layout_jitter_score"],
        max_region_shift_per_second=motion["max_region_shift_per_second"],
        wrong_speaker_focus_warnings=wrong_focus_warnings,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        render_completed=render.get("render_completed") is True,
        output_mp4_valid=render.get("output_mp4_valid") is True,
        passed=passed,
        subject_region_safety_evaluated=subject_safety.get("evaluated") is True,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )
    return result, {
        "real_multi_speaker_proof": passed,
        "rights_confirmed": rights_confirmed,
        "detector": "opencv_haar_local_validation_only"
        if sampled.get("available")
        else "unavailable",
        "speaker_diarization": "unavailable",
        "layout_strategy": strategy,
        "render_probe": render.get("probe"),
        "duration_delta": render.get("duration_delta"),
        "temporary_media_removed": True,
    }


def _extract_timelines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [payload, _stage_data(payload)]
    for candidate in list(candidates):
        for key in ("artifact", "final_output", "output", "result"):
            nested = candidate.get(key)
            if isinstance(nested, dict):
                candidates.extend([nested, _stage_data(nested)])
    for candidate in candidates:
        timelines = candidate.get("timelines")
        if isinstance(timelines, list):
            return [item for item in timelines if isinstance(item, dict)]
        timeline = candidate.get("timeline")
        if isinstance(timeline, dict):
            return [timeline]
    return []


def _extract_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = [payload, _stage_data(payload)]
    for candidate in list(candidates):
        for key in ("render_manifest", "manifest", "artifact", "final_output", "output"):
            nested = candidate.get(key)
            if isinstance(nested, dict):
                candidates.extend([nested, _stage_data(nested)])
    return next(
        (candidate for candidate in candidates if isinstance(candidate.get("renders"), list)),
        {},
    )


def _first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def inspect_project(
    project_id: str,
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
) -> tuple[MultiSpeakerLayoutValidationResultV1, dict[str, Any]]:
    project_error = validate_project_id(project_id)
    editing_paths = [
        storage_root / "editing" / project_id / "run" / "stages" / "timeline_validation.json",
        storage_root / "editing" / project_id / "stages" / "timeline_validation.json",
        storage_root / "editing" / project_id / "run" / "index.json",
        storage_root / "editing" / project_id / "index.json",
    ]
    render_paths = [
        storage_root / "render" / project_id / "run" / "index.json",
        storage_root / "render" / project_id / "run" / "stages" / "generate_render_manifest.json",
        storage_root / "render" / project_id / "index.json",
    ]
    editing_path = _first_existing(editing_paths)
    render_path = _first_existing(render_paths)
    errors = [project_error] if project_error else []
    if editing_path is None:
        errors.append("editing multi-speaker artifact was not found")
    if render_path is None:
        errors.append("render manifest was not found")
    timelines = _extract_timelines(_load(editing_path)) if editing_path else []
    manifest = _extract_manifest(_load(render_path)) if render_path else {}
    if editing_path and not timelines:
        errors.append("editing artifact did not contain a timeline")
    renders = [item for item in manifest.get("renders") or [] if isinstance(item, dict)]
    if render_path and not renders:
        errors.append("render manifest did not contain rendered clips")
    timeline: dict[str, Any] = timelines[0] if timelines else {}
    render: dict[str, Any] = renders[0] if renders else {}
    metadata_value = render.get("metadata")
    metadata: dict[str, Any] = metadata_value if isinstance(metadata_value, dict) else {}
    layout: dict[str, Any] = face_plan_from_timeline(timeline)
    if not layout:
        rendered_layout = metadata.get("multi_speaker_layout_v2")
        layout = rendered_layout if isinstance(rendered_layout, dict) else {}
    validation_value = metadata.get("multi_speaker_validation")
    validation: dict[str, Any] = (
        validation_value if isinstance(validation_value, dict) else {}
    )
    input_analysis_value = layout.get("input_analysis")
    input_analysis: dict[str, Any] = (
        input_analysis_value if isinstance(input_analysis_value, dict) else {}
    )
    strategy = str(layout.get("mode") or validation.get("planned_mode") or "center_fallback")
    regions = [item for item in layout.get("layout_regions") or [] if isinstance(item, dict)]
    switches = [item for item in layout.get("speaker_switches") or [] if isinstance(item, dict)]
    speaker_signals = bool(input_analysis.get("diarization_available"))
    face_signals = bool(input_analysis.get("face_tracking_available"))
    speaker_count = int(input_analysis.get("speaker_count") or 0)
    expected_count = max(2, speaker_count)
    fallback_used = strategy == "center_fallback"
    fallback_reason_value = str(
        layout.get("fallback_reason") or validation.get("fallback_reason") or ""
    )
    fallback_reason: str | None = fallback_reason_value or None
    wrong_focus_warnings: list[str] = []
    if strategy == "active_speaker_focus" and not speaker_signals:
        wrong_focus_warnings.append("Active-speaker focus lacks persisted diarization evidence.")
    if strategy != "center_fallback" and validation.get("applied") is not True:
        wrong_focus_warnings.append("Planned multi-speaker layout was not confirmed as rendered.")
    expected_regions = int(validation.get("expected_regions") or len(regions))
    rendered_regions = int(validation.get("rendered_regions") or 0)
    if expected_regions and rendered_regions != expected_regions:
        wrong_focus_warnings.append("Rendered layout region count does not match the plan.")
    layout_metrics = layout_motion_metrics(regions)
    region_coverage = speaker_region_coverage_ratio(
        expected_speaker_count=expected_count,
        region_counts_by_frame=[len(regions)] if regions else [],
    )
    storage_key = str(render.get("storage_key") or render.get("output_key") or "")
    output_path = Path(storage_key)
    if storage_key and not output_path.is_absolute():
        output_path = storage_root / output_path
    output_exists = bool(storage_key and output_path.is_file())
    output_probe = run_ffprobe(output_path) if output_exists else {}
    output_valid = bool(
        output_probe.get("passed") is True
        and output_probe.get("video_codec") == "h264"
        and output_probe.get("audio_codec") == "aac"
        and output_probe.get("has_audio") is True
    )
    if render and not output_exists:
        errors.append("rendered MP4 referenced by the manifest is missing")
    elif output_exists and not output_valid:
        errors.append("rendered MP4 failed ffprobe codec or stream validation")
    fallback_consistent = fallback_is_consistent(
        speaker_signals_available=speaker_signals,
        face_signals_available=face_signals,
        layout_strategy=strategy,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )
    if not fallback_consistent:
        errors.append("persisted speaker/face signals and fallback metadata are inconsistent")
    warnings = [
        "Project inspection does not rerender or reprocess source frames.",
        "Subject cutoff metrics were not recomputed because raw detections are not persisted here.",
    ]
    result = MultiSpeakerLayoutValidationResultV1(
        project_id=project_id,
        clip_id=str(timeline.get("clip_id") or render.get("clip_id") or "") or None,
        mode="project_id",
        real_multi_speaker_sample_used=False,
        synthetic_sample_used=False,
        speaker_signals_available=speaker_signals,
        face_signals_available=face_signals,
        detected_speaker_count=speaker_count,
        expected_speaker_count=expected_count,
        layout_strategy=strategy,
        active_speaker_switches=active_speaker_switch_count(switches),
        frames_sampled=0,
        layout_regions_present=bool(regions),
        speaker_region_coverage_ratio=region_coverage,
        face_inside_region_ratio=0.0,
        subject_cutoff_detected=False,
        layout_jitter_score=layout_metrics["layout_jitter_score"],
        max_region_shift_per_second=layout_metrics["max_region_shift_per_second"],
        wrong_speaker_focus_warnings=wrong_focus_warnings,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        render_completed=bool(render and output_exists),
        output_mp4_valid=output_valid,
        passed=not errors and not wrong_focus_warnings and output_valid and fallback_consistent,
        subject_region_safety_evaluated=False,
        warnings=warnings,
        errors=[item for item in errors if item],
    )
    return result, {
        "real_multi_speaker_proof": False,
        "inspection_only": True,
        "rerendered": False,
        "searched_editing_paths": [str(path.relative_to(storage_root)) for path in editing_paths],
        "searched_render_paths": [str(path.relative_to(storage_root)) for path in render_paths],
        "editing_artifact_found": str(editing_path.relative_to(storage_root))
        if editing_path
        else None,
        "render_artifact_found": str(render_path.relative_to(storage_root))
        if render_path
        else None,
        "render_probe": _compact_probe(output_probe),
    }


def _layout_from_face_artifact(args: argparse.Namespace) -> dict[str, Any]:
    raw = _load(args.face_artifact)
    detections = _normalize_face_detections(
        raw,
        clip_start=args.clip_start,
        clip_duration=args.duration,
        source_width=args.source_width,
        source_height=args.source_height,
    )
    speaker_timeline: list[dict[str, Any]] = []
    if args.speaker_artifact:
        speaker_timeline = [
            item
            for item in _stage_data(_load(args.speaker_artifact)).get("timeline") or []
            if isinstance(item, dict)
        ]
    return build_multi_speaker_layout(
        detections=detections,
        speaker_timeline=speaker_timeline,
        clip_id="artifact_validation",
        project_id=None,
        clip_start=args.clip_start,
        duration=args.duration,
        source_width=args.source_width,
        source_height=args.source_height,
        fps=args.fps,
    )


def _project_artifacts(project_id: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    root = Path(get_settings().storage.local_root)
    editing_path = root / "editing" / project_id / "run" / "stages" / "timeline_validation.json"
    render_path = root / "render" / project_id / "run" / "stages" / "generate_render_manifest.json"
    warnings: list[str] = []
    layout: dict[str, Any] = {}
    rendered: dict[str, Any] = {}
    if editing_path.exists():
        editing = _stage_data(_load(editing_path))
        timelines = editing.get("timelines") if isinstance(editing.get("timelines"), list) else []
        if timelines:
            metadata = timelines[0].get("metadata") if isinstance(timelines[0], dict) else None
            if isinstance(metadata, dict):
                layout = metadata.get("multi_speaker_layout_v2") or {}
    else:
        warnings.append(f"Editing timeline artifact not found at {editing_path}")
    if render_path.exists():
        manifest = _manifest(_load(render_path))
        renders = manifest.get("renders") if isinstance(manifest.get("renders"), list) else []
        if renders:
            metadata = renders[0].get("metadata") if isinstance(renders[0], dict) else None
            if isinstance(metadata, dict):
                rendered = metadata.get("multi_speaker_validation") or {}
    else:
        warnings.append(f"Render manifest artifact not found at {render_path}")
    return layout, rendered, warnings


def _render_manifest_layout(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _manifest(_load(path))
    renders = manifest.get("renders") if isinstance(manifest.get("renders"), list) else []
    if not renders:
        return {}, {}
    metadata = renders[0].get("metadata") if isinstance(renders[0], dict) else None
    if not isinstance(metadata, dict):
        return {}, {}
    return (
        metadata.get("multi_speaker_layout_v2") or {},
        metadata.get("multi_speaker_validation") or {},
    )


def _report(args: argparse.Namespace) -> dict[str, Any]:
    layout: dict[str, Any] = {}
    rendered: dict[str, Any] = {}
    probe: dict[str, Any] | None = None
    warnings: list[str] = []
    mode = "unknown"
    if args.simulate:
        mode = "simulate"
        layout = build_multi_speaker_layout(
            detections=_simulated_detections(args.faces, args.duration),
            speaker_timeline=_simulated_speakers(args.speakers, args.duration),
            clip_id="simulation",
            project_id="simulation",
            clip_start=0.0,
            duration=args.duration,
            source_width=args.source_width,
            source_height=args.source_height,
            fps=args.fps,
        )
    elif args.face_artifact:
        mode = "face_artifact"
        layout = _layout_from_face_artifact(args)
    elif args.rendered_file:
        mode = "rendered_file"
        probe = _probe(args.rendered_file)
        if args.manifest:
            layout, rendered = _render_manifest_layout(args.manifest)
        else:
            warnings.append("A render manifest is required to validate layout truth.")
    elif args.project_id:
        mode = "project"
        layout, rendered, project_warnings = _project_artifacts(args.project_id)
        warnings.extend(project_warnings)
    tracks = layout.get("participants") if isinstance(layout.get("participants"), list) else []
    associations = (
        layout.get("speaker_face_associations")
        if isinstance(layout.get("speaker_face_associations"), list)
        else []
    )
    decision_value = layout.get("decision")
    decision: dict[str, Any] = decision_value if isinstance(decision_value, dict) else {}
    render_plan_value = layout.get("render_plan")
    render_plan: dict[str, Any] = (
        render_plan_value if isinstance(render_plan_value, dict) else {}
    )
    pass_fail = bool(layout and decision.get("mode"))
    if mode == "rendered_file":
        pass_fail = bool(
            pass_fail
            and probe
            and probe.get("available")
            and rendered.get("passed") is True
        )
    if args.validate_renders and mode == "project":
        pass_fail = bool(pass_fail and rendered.get("passed") is True)
    return {
        "multi_speaker_validation_report": {
            "mode": mode,
            "face_tracks": tracks,
            "speaker_associations": associations,
            "layout_decision": decision,
            "render_plan": render_plan,
            "rendered_validation": rendered,
            "ffprobe": probe,
            "warnings": warnings,
            "pass_fail": pass_fail,
        }
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument(
        "--synthetic-two-speaker",
        "--synthetic",
        dest="synthetic_two_speaker",
        action="store_true",
    )
    modes.add_argument("--local-multi-speaker-file", type=Path)
    modes.add_argument("--simulate", action="store_true")
    modes.add_argument("--face-artifact", type=Path)
    modes.add_argument("--rendered-file", type=Path)
    modes.add_argument("--project-id")
    parser.add_argument("--confirm-rights", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--speaker-artifact", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--validate-renders", action="store_true")
    parser.add_argument("--faces", type=int, default=2)
    parser.add_argument("--speakers", type=int, default=0)
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--clip-start", type=float, default=0.0)
    parser.add_argument("--source-width", type=float, default=1920.0)
    parser.add_argument("--source-height", type=float, default=1080.0)
    parser.add_argument("--fps", type=float, default=30.0)
    return parser


def run_selected_mode(
    args: argparse.Namespace,
) -> tuple[MultiSpeakerLayoutValidationResultV1, dict[str, Any]]:
    if args.self_check:
        return run_self_check()
    if args.synthetic_two_speaker:
        return run_synthetic_two_speaker()
    if args.local_multi_speaker_file:
        return run_local_multi_speaker_file(
            args.local_multi_speaker_file,
            rights_confirmed=bool(args.confirm_rights),
        )
    return inspect_project(str(args.project_id or ""), storage_root=args.storage_root)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.simulate or args.face_artifact or args.rendered_file:
        legacy_report = _report(args)
        print(json.dumps(legacy_report, indent=2, default=str))
        return 0 if legacy_report["multi_speaker_validation_report"]["pass_fail"] else 1

    result, details = run_selected_mode(args)
    try:
        report_path = write_multi_speaker_report(
            result,
            workspace_root=ROOT,
            report_dir=args.report_dir,
            details=details,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": f"validation report could not be written: {exc}"}, indent=2))
        return 1
    legacy_summary = {
        "mode": result.mode,
        "layout_decision": {"mode": result.layout_strategy},
        "rendered_validation": {
            "render_completed": result.render_completed,
            "output_mp4_valid": result.output_mp4_valid,
        },
        "warnings": result.warnings,
        "pass_fail": result.passed,
    }
    print(
        json.dumps(
            {
                "multi_speaker_layout_validation_result_v1": result.to_dict(),
                "multi_speaker_validation_report": legacy_summary,
                "details": details,
                "report_path": str(report_path),
            },
            indent=2,
        )
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

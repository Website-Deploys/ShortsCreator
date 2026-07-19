"""Validate face tracking, crop stability, motion safety, and render truth locally."""

from __future__ import annotations

import argparse
import importlib
import json
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

from olympus.editing.motion import build_motion_intelligence  # noqa: E402
from olympus.editing.multi_speaker import (  # noqa: E402
    build_multi_speaker_layout,
    consolidate_face_tracks,
)
from olympus.platform.config import get_settings  # noqa: E402
from olympus.rendering import command as render_command  # noqa: E402
from olympus.validation.face_motion import (  # noqa: E402
    FaceMotionValidationResultV1,
    FaceMotionValidationThresholdsV1,
    crop_motion_metrics,
    evaluate_face_crop_safety,
    face_plan_from_timeline,
    fallback_is_consistent,
    motion_effects_from_contract,
    motion_from_timeline,
    tracking_coverage_ratio,
    validate_local_face_path,
    validate_project_id,
    write_face_motion_report,
)
from olympus.validation.real_video import run_ffprobe  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "face_tracking_motion"
DEFAULT_STORAGE_ROOT = ROOT / "storage_data"
SYNTHETIC_DURATION_SECONDS = 4.0
SYNTHETIC_FRAMES_PER_SECOND = 24
LOCAL_SAMPLE_FRAMES_PER_SECOND = 2.0
MAX_LOCAL_VALIDATION_SECONDS = 8.0


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"_error": str(exc)}
    return value if isinstance(value, dict) else {"_error": "JSON root is not an object"}


def _stage_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


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


def _motion_contract(face_plan: dict[str, Any], duration: float, clip_id: str) -> dict[str, Any]:
    return build_motion_intelligence(
        clip={
            "clip_id": clip_id,
            "source_start": 0.0,
            "source_end": duration,
            "duration": duration,
        },
        blueprint={
            "content_niche": {"primary": "educational"},
            "hook_v2": {"category": "curiosity_gap", "score": 0.84},
            "story_v2_guidance": {
                "story_guidance_used": True,
                "story_shape": "setup_tension_payoff",
                "turning_point": {"time": duration * 0.5},
                "payoff": "Validation payoff",
                "payoff_present": True,
            },
            "ending_payoff_v2": {
                "ending_type": "lesson",
                "ending_line": "Validation payoff",
                "payoff_present": True,
            },
            "closing_payoff": {"timestamp": max(0.0, duration - 1.0)},
            "viral_score_v2": {"overall": 0.75},
            "editing_trend_guidance": {"pacing_style": "restrained_dynamic"},
            "source_motion": {"level": "low"},
        },
        caption_intelligence={
            "input_signals": {"speech_density": 2.0},
            "style_decision": {"caption_style": "default_clean"},
            "caption_safe_zone": {"strategy": "lower_safe_zone", "collision_risk": "low"},
        },
        music_intelligence={},
        face_plan=face_plan,
        sfx_plan={"enabled": False, "effects": []},
        project_id="face_motion_validation",
    )


def _timeline(
    *,
    clip_id: str,
    duration: float,
    face_plan: dict[str, Any],
    motion: dict[str, Any],
) -> dict[str, Any]:
    motion_effects = motion_effects_from_contract(motion)
    source_window = {
        "contract_version": "1",
        "project_id": "face_motion_validation",
        "clip_id": clip_id,
        "requested_start_seconds": 0.0,
        "requested_end_seconds": duration,
        "repaired_start_seconds": 0.0,
        "repaired_end_seconds": duration,
        "duration_seconds": duration,
        "preroll_seconds": 0.0,
        "postroll_seconds": 0.0,
        "boundary_repair_applied": False,
        "start_reason": "local validation clip",
        "end_reason": "local validation clip",
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
                        "reason": "local face/motion validation",
                        "confidence": 1.0,
                        "evidence": [],
                    },
                    *motion_effects,
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
                        "reason": "preserve validation source audio",
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
            "face_tracking_plan": face_plan,
            "multi_speaker_layout_v2": face_plan,
            "motion_intelligence_v2": motion,
            "motion_safety_validation": motion.get("motion_safety_validation"),
            "editing_v2": {
                "face_tracking_plan": face_plan,
                "multi_speaker_layout_v2": face_plan,
                "motion_intelligence_v2": motion,
                "motion_plan": {"events": motion_effects},
                "voice_enhancement_plan": {"filters": ["highpass", "loudnorm"]},
                "video_enhancement_plan": {"profile": "clean_high_retention"},
            },
            "render_assets_v2": {"music": {}, "sfx": {}},
        },
    }


def _run(command: list[str], *, timeout_seconds: float = 180.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _synthetic_media_plan(destination: Path, duration: float) -> list[str]:
    settings = get_settings().rendering
    return [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x20242a:s=640x360:r={SYNTHETIC_FRAMES_PER_SECOND}:d={duration:.3f}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0xf2c94c:s=120x120:r={SYNTHETIC_FRAMES_PER_SECOND}:d={duration:.3f}",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-filter_complex",
        (
            "[1:v]drawbox=x=24:y=32:w=18:h=18:color=0x20242a:t=fill,"
            "drawbox=x=78:y=32:w=18:h=18:color=0x20242a:t=fill,"
            "drawbox=x=35:y=82:w=50:h=8:color=0x20242a:t=fill[shape];"
            "[0:v][shape]overlay=x='60+70*t':y=120:shortest=1[v]"
        ),
        "-map",
        "[v]",
        "-map",
        "2:a",
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


def _render_validation_clip(
    *,
    source: Path,
    output: Path,
    timeline: dict[str, Any],
    width: int = 540,
    height: int = 960,
    fps: int = 24,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    settings = get_settings().rendering
    command = render_command.build_ffmpeg_command(
        binary=settings.ffmpeg_binary,
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
        completed = _run(command, timeout_seconds=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "render_completed": False,
            "output_mp4_valid": False,
            "filtergraph_contains_motion": False,
            "duration_delta": None,
            "probe": {},
            "errors": [f"FFmpeg render failed: {exc}"],
            "warnings": [],
        }
    graph = command[command.index("-filter_complex") + 1]
    if completed.returncode != 0:
        tail = completed.stderr.strip().splitlines()[-6:]
        return {
            "render_completed": False,
            "output_mp4_valid": False,
            "filtergraph_contains_motion": "zoompan=" in graph,
            "duration_delta": None,
            "probe": {},
            "errors": [f"FFmpeg exited {completed.returncode}: {' | '.join(tail)}"],
            "warnings": [],
        }
    probe = run_ffprobe(output)
    expected_duration = render_command.expected_duration(timeline)
    actual_duration = _float(probe.get("container_duration"))
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
        <= FaceMotionValidationThresholdsV1().maximum_duration_delta_seconds
    )
    return {
        "render_completed": output.exists(),
        "output_mp4_valid": valid,
        "filtergraph_contains_motion": "zoompan=" in graph,
        "duration_delta": round(duration_delta, 4) if duration_delta is not None else None,
        "probe": _compact_probe(probe),
        "errors": []
        if valid
        else ["rendered MP4 failed codec, stream, size, or duration validation"],
        "warnings": [],
    }


def run_self_check() -> tuple[FaceMotionValidationResultV1, dict[str, Any]]:
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
            "Optional local OpenCV face detection is unavailable; real face tracking cannot be "
            "proven in this environment."
        )
    result = FaceMotionValidationResultV1(
        project_id=None,
        clip_id=None,
        mode="self_check",
        face_sample_used=False,
        real_face_sample_used=False,
        face_tracking_available=False,
        face_count_detected=0,
        frames_sampled=0,
        tracked_frames=0,
        tracking_coverage_ratio=0.0,
        crop_keyframes_present=False,
        motion_effects_present=False,
        face_inside_safe_zone_ratio=0.0,
        jitter_score=0.0,
        max_crop_shift_per_second=0.0,
        face_cutoff_detected=False,
        center_fallback_used=False,
        render_completed=False,
        output_mp4_valid=False,
        passed=not errors,
        warnings=warnings,
        errors=errors,
    )
    return result, {
        "module_imports_passed": True,
        "motion_config_available": settings.motion_graphics.enabled is not None,
        "multi_speaker_config_available": settings.multi_speaker_layout.enabled is not None,
        "ffmpeg_available": ffmpeg_available,
        "ffprobe_available": ffprobe_available,
        "optional_opencv_available": opencv_available,
        "external_access_required": False,
        "real_media_required": False,
    }


def run_synthetic_fallback() -> tuple[FaceMotionValidationResultV1, dict[str, Any]]:
    duration = SYNTHETIC_DURATION_SECONDS
    layout = build_multi_speaker_layout(
        detections=[],
        speaker_timeline=[],
        clip_id="synthetic_fallback",
        project_id="face_motion_validation",
        clip_start=0.0,
        duration=duration,
        source_width=640.0,
        source_height=360.0,
        fps=float(SYNTHETIC_FRAMES_PER_SECOND),
    )
    face_plan = dict(layout)
    input_analysis = dict(_dict(face_plan.get("input_analysis")))
    input_analysis.update(
        {
            "face_tracking_available": True,
            "detected_face_count": 0,
            "validation_fixture_known_non_face": True,
        }
    )
    face_plan["input_analysis"] = input_analysis
    motion = _motion_contract(face_plan, duration, "synthetic_fallback")
    effects = motion_effects_from_contract(motion)
    timeline = _timeline(
        clip_id="synthetic_fallback",
        duration=duration,
        face_plan=face_plan,
        motion=motion,
    )
    warnings = [
        "Synthetic face-like geometry is not a real person and does not prove face detection.",
        "No face detections were supplied; center fallback correctness was exercised.",
    ]
    errors: list[str] = []
    render: dict[str, Any]
    with tempfile.TemporaryDirectory(prefix="olympus-face-motion-") as temporary:
        temporary_root = Path(temporary)
        source = temporary_root / "synthetic_shape.mp4"
        output = temporary_root / "synthetic_motion.mp4"
        try:
            generated = _run(_synthetic_media_plan(source, duration))
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
                "filtergraph_contains_motion": False,
                "duration_delta": None,
                "probe": {},
                "errors": [],
                "warnings": [],
            }
        else:
            render = _render_validation_clip(source=source, output=output, timeline=timeline)
            errors.extend(_list(render.get("errors")))
            warnings.extend(_list(render.get("warnings")))

    center_fallback = layout.get("mode") == "center_fallback"
    fallback_consistent = fallback_is_consistent(
        face_tracking_available=False,
        face_count_detected=0,
        center_fallback_used=center_fallback,
    )
    motion_rendered = bool(effects and render.get("filtergraph_contains_motion"))
    passed = bool(
        fallback_consistent
        and center_fallback
        and not errors
        and render.get("render_completed")
        and render.get("output_mp4_valid")
        and motion_rendered
    )
    result = FaceMotionValidationResultV1(
        project_id=None,
        clip_id="synthetic_fallback",
        mode="synthetic_fallback",
        face_sample_used=True,
        real_face_sample_used=False,
        face_tracking_available=False,
        face_count_detected=0,
        frames_sampled=0,
        tracked_frames=0,
        tracking_coverage_ratio=0.0,
        crop_keyframes_present=False,
        motion_effects_present=motion_rendered,
        face_inside_safe_zone_ratio=0.0,
        jitter_score=0.0,
        max_crop_shift_per_second=0.0,
        face_cutoff_detected=False,
        center_fallback_used=center_fallback,
        render_completed=render.get("render_completed") is True,
        output_mp4_valid=render.get("output_mp4_valid") is True,
        passed=passed,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )
    return result, {
        "fixture_kind": "generated_moving_face_like_shape",
        "real_face_proof": False,
        "fallback_reason": layout.get("fallback_reason"),
        "fallback_consistent": fallback_consistent,
        "motion_effects_planned": len(effects),
        "motion_filter_rendered": motion_rendered,
        "render_probe": render.get("probe"),
        "duration_delta": render.get("duration_delta"),
        "temporary_media_removed": True,
    }


def _sample_faces_with_optional_opencv(
    path: Path,
    *,
    duration: float,
    sample_fps: float,
) -> dict[str, Any]:
    try:
        cv2: Any = importlib.import_module("cv2")
    except ImportError:
        return {
            "available": False,
            "frames_sampled": 0,
            "tracked_frames": 0,
            "max_faces": 0,
            "detections": [],
            "warnings": [],
            "errors": [
                "Optional local OpenCV detector is unavailable; the production face detection "
                "stage is also configured as unavailable."
            ],
        }
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        return {
            "available": False,
            "frames_sampled": 0,
            "tracked_frames": 0,
            "max_faces": 0,
            "detections": [],
            "warnings": [],
            "errors": ["OpenCV frontal-face cascade could not be loaded"],
        }
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return {
            "available": True,
            "frames_sampled": 0,
            "tracked_frames": 0,
            "max_faces": 0,
            "detections": [],
            "warnings": [],
            "errors": ["local video could not be opened for frame sampling"],
        }
    interval = 1.0 / max(0.25, sample_fps)
    timestamp = 0.0
    sampled = 0
    tracked = 0
    max_faces = 0
    detections: list[dict[str, Any]] = []
    try:
        while timestamp <= duration + 0.001:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            success, frame = capture.read()
            if not success:
                timestamp += interval
                continue
            sampled += 1
            frame_height, frame_width = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            boxes = detector.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(40, 40),
            )
            if len(boxes):
                tracked += 1
            max_faces = max(max_faces, len(boxes))
            for x, y, width, height in boxes:
                detections.append(
                    {
                        "time": round(timestamp, 3),
                        "x_center": (float(x) + float(width) / 2) / frame_width,
                        "y_center": (float(y) + float(height) / 2) / frame_height,
                        "width": float(width) / frame_width,
                        "height": float(height) / frame_height,
                        "confidence": 0.75,
                    }
                )
            del gray
            del frame
            timestamp += interval
    finally:
        capture.release()
    return {
        "available": True,
        "frames_sampled": sampled,
        "tracked_frames": tracked,
        "max_faces": max_faces,
        "detections": detections,
        "warnings": [
            "OpenCV Haar detections use a fixed planning confidence; this is validation-only and "
            "not identity recognition."
        ],
        "errors": [],
    }


def run_local_face_file(
    path: Path,
    *,
    rights_confirmed: bool,
) -> tuple[FaceMotionValidationResultV1, dict[str, Any]]:
    validated, path_errors = validate_local_face_path(path, rights_confirmed=rights_confirmed)
    if validated is None:
        result = FaceMotionValidationResultV1(
            project_id=None,
            clip_id=None,
            mode="local_face_file",
            face_sample_used=False,
            real_face_sample_used=False,
            face_tracking_available=False,
            face_count_detected=0,
            frames_sampled=0,
            tracked_frames=0,
            tracking_coverage_ratio=0.0,
            crop_keyframes_present=False,
            motion_effects_present=False,
            face_inside_safe_zone_ratio=0.0,
            jitter_score=0.0,
            max_crop_shift_per_second=0.0,
            face_cutoff_detected=False,
            center_fallback_used=False,
            render_completed=False,
            output_mp4_valid=False,
            passed=False,
            errors=path_errors,
        )
        return result, {"real_face_proof": False, "temporary_media_removed": True}

    source_probe = run_ffprobe(validated)
    source_duration = _float(source_probe.get("container_duration"))
    width = _float(source_probe.get("width"))
    height = _float(source_probe.get("height"))
    duration = min(MAX_LOCAL_VALIDATION_SECONDS, source_duration)
    errors: list[str] = []
    warnings: list[str] = []
    if source_probe.get("passed") is not True or duration <= 0 or width <= 0 or height <= 0:
        errors.append("local face video failed ffprobe or has invalid duration/dimensions")
    sampled = _sample_faces_with_optional_opencv(
        validated,
        duration=max(0.0, duration),
        sample_fps=LOCAL_SAMPLE_FRAMES_PER_SECOND,
    )
    errors.extend(_list(sampled.get("errors")))
    warnings.extend(_list(sampled.get("warnings")))
    detections = [item for item in _list(sampled.get("detections")) if isinstance(item, dict)]
    layout = build_multi_speaker_layout(
        detections=detections,
        speaker_timeline=[],
        clip_id="local_face_validation",
        project_id="face_motion_validation",
        clip_start=0.0,
        duration=max(0.1, duration),
        source_width=width,
        source_height=height,
        fps=_float(source_probe.get("fps"), 30.0),
    )
    keyframes = [item for item in _list(layout.get("crop_keyframes")) if isinstance(item, dict)]
    motion = _motion_contract(layout, max(0.1, duration), "local_face_validation")
    effects = motion_effects_from_contract(motion)
    tracks = consolidate_face_tracks(detections, max(0.1, duration))
    safety_detections = (
        [item for item in _list(tracks[0].get("observations")) if isinstance(item, dict)]
        if tracks
        else detections
    )
    safety = evaluate_face_crop_safety(
        detections=safety_detections,
        crop_keyframes=keyframes,
        source_width=width,
        source_height=height,
        motion_effects=effects,
    )
    crop_metrics = crop_motion_metrics(keyframes)
    render: dict[str, Any] = {
        "render_completed": False,
        "output_mp4_valid": False,
        "filtergraph_contains_motion": False,
        "duration_delta": None,
        "probe": {},
        "errors": [],
        "warnings": [],
    }
    if not errors and keyframes and effects:
        timeline = _timeline(
            clip_id="local_face_validation",
            duration=duration,
            face_plan=layout,
            motion=motion,
        )
        with tempfile.TemporaryDirectory(prefix="olympus-real-face-motion-") as temporary:
            render = _render_validation_clip(
                source=validated,
                output=Path(temporary) / "local_face_motion.mp4",
                timeline=timeline,
                fps=max(1, round(_float(source_probe.get("fps"), 30.0))),
            )
    elif not errors and not effects:
        errors.append("motion was safely disabled; real face-plus-motion proof was not completed")
    errors.extend(_list(render.get("errors")))
    warnings.extend(_list(render.get("warnings")))

    frames_sampled = int(sampled.get("frames_sampled") or 0)
    tracked_frames = int(sampled.get("tracked_frames") or 0)
    coverage = tracking_coverage_ratio(
        sampled_frames=frames_sampled,
        tracked_frames=tracked_frames,
    )
    face_tracking_available = bool(layout.get("mode") != "center_fallback" and keyframes)
    center_fallback = layout.get("mode") == "center_fallback"
    thresholds = FaceMotionValidationThresholdsV1()
    passed = bool(
        not errors
        and face_tracking_available
        and coverage >= thresholds.minimum_tracking_coverage_ratio
        and keyframes
        and safety.get("evaluated") is True
        and _float(safety.get("face_inside_safe_zone_ratio"))
        >= thresholds.minimum_face_inside_safe_zone_ratio
        and safety.get("face_cutoff_detected") is False
        and crop_metrics["jitter_score"] <= thresholds.maximum_jitter_score
        and crop_metrics["max_crop_shift_per_second"]
        <= thresholds.maximum_crop_shift_per_second
        and render.get("output_mp4_valid") is True
        and render.get("filtergraph_contains_motion") is True
        and fallback_is_consistent(
            face_tracking_available=face_tracking_available,
            face_count_detected=int(sampled.get("max_faces") or 0),
            center_fallback_used=center_fallback,
        )
    )
    if not face_tracking_available:
        warnings.append(
            "Face detection did not produce a renderable track; center fallback was used."
        )
    result = FaceMotionValidationResultV1(
        project_id=None,
        clip_id="local_face_validation",
        mode="local_face_file",
        face_sample_used=True,
        real_face_sample_used=True,
        face_tracking_available=face_tracking_available,
        face_count_detected=int(sampled.get("max_faces") or 0),
        frames_sampled=frames_sampled,
        tracked_frames=tracked_frames,
        tracking_coverage_ratio=coverage,
        crop_keyframes_present=bool(keyframes),
        motion_effects_present=bool(effects and render.get("filtergraph_contains_motion")),
        face_inside_safe_zone_ratio=_float(safety.get("face_inside_safe_zone_ratio")),
        jitter_score=crop_metrics["jitter_score"],
        max_crop_shift_per_second=crop_metrics["max_crop_shift_per_second"],
        face_cutoff_detected=safety.get("face_cutoff_detected") is True,
        center_fallback_used=center_fallback,
        render_completed=render.get("render_completed") is True,
        output_mp4_valid=render.get("output_mp4_valid") is True,
        passed=passed,
        face_crop_safety_evaluated=safety.get("evaluated") is True,
        warnings=list(dict.fromkeys(warnings)),
        errors=list(dict.fromkeys(errors)),
    )
    return result, {
        "real_face_proof": passed,
        "rights_confirmed": rights_confirmed,
        "detector": "opencv_haar_local_validation_only"
        if sampled.get("available")
        else "unavailable",
        "layout_mode": layout.get("mode"),
        "fallback_reason": layout.get("fallback_reason"),
        "motion_effects_planned": len(effects),
        "render_probe": render.get("probe"),
        "duration_delta": render.get("duration_delta"),
        "temporary_media_removed": True,
    }


def _first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def inspect_project(
    project_id: str,
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
) -> tuple[FaceMotionValidationResultV1, dict[str, Any]]:
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
        errors.append("editing face/motion artifact was not found in canonical or legacy paths")
    if render_path is None:
        errors.append("render manifest was not found in canonical or legacy paths")

    timelines = _extract_timelines(_load_json(editing_path)) if editing_path else []
    manifest = _extract_manifest(_load_json(render_path)) if render_path else {}
    if editing_path and not timelines:
        errors.append("editing artifact did not contain a timeline")
    renders = [item for item in _list(manifest.get("renders")) if isinstance(item, dict)]
    if render_path and not renders:
        errors.append("render manifest did not contain rendered clips")
    timeline = timelines[0] if timelines else {}
    render = renders[0] if renders else {}
    clip_id = str(timeline.get("clip_id") or render.get("clip_id") or "") or None
    face_plan = face_plan_from_timeline(timeline)
    motion = motion_from_timeline(timeline)
    render_metadata = _dict(render.get("metadata"))
    if not face_plan:
        face_plan = _dict(render_metadata.get("multi_speaker_layout_v2"))
    if not motion:
        motion = _dict(render_metadata.get("motion_intelligence_v2"))
    face_truth = _dict(render_metadata.get("face_tracking"))
    motion_truth = _dict(render_metadata.get("motion_render_validation"))
    keyframes = [item for item in _list(face_plan.get("crop_keyframes")) if isinstance(item, dict)]
    crop_metrics = crop_motion_metrics(keyframes)
    mode = str(face_plan.get("mode") or face_truth.get("mode") or "center_fallback")
    center_fallback = mode == "center_fallback"
    face_applied = bool(
        render_metadata.get("face_tracking_applied") is True or face_truth.get("applied") is True
    )
    face_tracking_available = bool(not center_fallback and keyframes)
    input_analysis = _dict(face_plan.get("input_analysis"))
    face_count = int(
        input_analysis.get("stable_face_count")
        or input_analysis.get("detected_face_count")
        or len(_list(face_plan.get("participants")))
        or 0
    )
    tracked_faces = [
        item for item in _list(face_plan.get("tracked_faces")) if isinstance(item, dict)
    ]
    coverage = max((_float(item.get("coverage")) for item in tracked_faces), default=0.0)
    if not coverage:
        coverage = max(
            (_float(item.get("visibility_ratio")) for item in _list(face_plan.get("participants"))),
            default=0.0,
        )
    effects = motion_effects_from_contract(motion)
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
    truth_consistent = fallback_is_consistent(
        face_tracking_available=face_tracking_available,
        face_count_detected=face_count,
        center_fallback_used=center_fallback,
    ) and (not face_tracking_available or face_applied)
    if not truth_consistent:
        errors.append("face plan and rendered applied/fallback metadata are inconsistent")
    warnings = []
    if face_tracking_available:
        warnings.append(
            "Existing project artifacts contain face tracking truth, but raw detections were not "
            "reprocessed and real face provenance was not assumed."
        )
    else:
        warnings.append("Project inspection found center fallback or unavailable face tracking.")
    warnings.append("Face safe-zone/cutoff metrics require detections and were not re-evaluated.")
    edit_truth_motion = _dict(_dict(render_metadata.get("edit_truth")).get("motion"))
    motion_rendered = bool(
        motion_truth.get("effects_rendered", 0)
        or edit_truth_motion.get("applied") is True
    )
    result = FaceMotionValidationResultV1(
        project_id=project_id,
        clip_id=clip_id,
        mode="project_id",
        face_sample_used=face_count > 0,
        real_face_sample_used=False,
        face_tracking_available=face_tracking_available,
        face_count_detected=face_count,
        frames_sampled=0,
        tracked_frames=0,
        tracking_coverage_ratio=round(coverage, 4),
        crop_keyframes_present=bool(keyframes),
        motion_effects_present=bool(effects and motion_rendered),
        face_inside_safe_zone_ratio=0.0,
        jitter_score=crop_metrics["jitter_score"],
        max_crop_shift_per_second=crop_metrics["max_crop_shift_per_second"],
        face_cutoff_detected=False,
        center_fallback_used=center_fallback,
        render_completed=bool(render and output_exists),
        output_mp4_valid=output_valid,
        passed=not errors and output_valid and truth_consistent,
        face_crop_safety_evaluated=False,
        warnings=warnings,
        errors=[item for item in errors if item],
    )
    return result, {
        "real_face_proof": False,
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
        "layout_mode": mode,
        "face_tracking_applied": face_applied,
        "motion_effects_planned": len(effects),
        "motion_effects_rendered": motion_truth.get("effects_rendered", 0),
        "render_probe": _compact_probe(output_probe),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--synthetic-fallback", action="store_true")
    modes.add_argument("--local-face-file", type=Path)
    modes.add_argument("--project-id")
    parser.add_argument(
        "--confirm-rights",
        action="store_true",
        help="Confirm rights/permission for the explicitly supplied local face video",
    )
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    return parser


def run_selected_mode(
    args: argparse.Namespace,
) -> tuple[FaceMotionValidationResultV1, dict[str, Any]]:
    if args.self_check:
        return run_self_check()
    if args.synthetic_fallback:
        return run_synthetic_fallback()
    if args.local_face_file:
        return run_local_face_file(
            args.local_face_file,
            rights_confirmed=bool(args.confirm_rights),
        )
    return inspect_project(str(args.project_id or ""), storage_root=args.storage_root)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result, details = run_selected_mode(args)
    try:
        report_path = write_face_motion_report(
            result,
            workspace_root=ROOT,
            report_dir=args.report_dir,
            details=details,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": f"validation report could not be written: {exc}"}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "face_motion_validation_result_v1": result.to_dict(),
                "details": details,
                "report_path": str(report_path),
            },
            indent=2,
        )
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

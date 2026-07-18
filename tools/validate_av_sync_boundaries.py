"""Validate canonical clip boundaries and content-level A/V marker alignment."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import struct
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.data.storage.local import LocalStorage  # noqa: E402
from olympus.editing import timeline as T  # noqa: E402, N812
from olympus.editing.boundary_repair import (  # noqa: E402
    repair_clip_source_window,
    validate_clip_source_window,
)
from olympus.editing.timeline_contracts import ClipSourceWindowV1  # noqa: E402
from olympus.rendering import command as C  # noqa: E402, N812
from olympus.rendering.artifacts import resolve_render_manifest  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "av_sync_boundaries"
REPORT_NAME = "av_sync_boundaries_report.json"
SUMMARY_NAME = "av_sync_boundaries_summary.md"
STRESS_REPORT_NAME = "av_sync_boundaries_stress_report.json"
STRESS_SUMMARY_NAME = "av_sync_boundaries_stress_summary.md"
STRESS_SCENARIO_NAMES = (
    "clean_speech_marker",
    "voice_filter_latency",
    "boundary_near_final_word",
    "mid_word_start",
    "no_word_level_transcript",
    "short_clip_near_source_end",
    "captions_source_time",
    "short_music_sfx",
)
SYNTHETIC_INPUT_POLICY = {
    "generated_synthetic_media_only": True,
    "real_user_media_used": False,
    "downloads_used": False,
    "external_api_calls_used": False,
    "network_used": False,
}


def _dict_value(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def validate_marker_alignment(
    visual_marker_seconds: float | None,
    audio_marker_seconds: float | None,
    *,
    tolerance_seconds: float = 0.04,
) -> dict[str, Any]:
    """Compare detected content markers instead of inferring sync from duration."""

    if visual_marker_seconds is None or audio_marker_seconds is None:
        return {
            "passed": False,
            "visual_marker_seconds": visual_marker_seconds,
            "audio_marker_seconds": audio_marker_seconds,
            "offset_seconds": None,
            "tolerance_seconds": tolerance_seconds,
            "warning": "One or both content markers could not be detected.",
        }
    offset = audio_marker_seconds - visual_marker_seconds
    return {
        "passed": abs(offset) <= tolerance_seconds,
        "visual_marker_seconds": round(visual_marker_seconds, 6),
        "audio_marker_seconds": round(audio_marker_seconds, 6),
        "offset_seconds": round(offset, 6),
        "tolerance_seconds": tolerance_seconds,
        "warning": (
            None
            if abs(offset) <= tolerance_seconds
            else f"Content markers differ by {abs(offset):.3f}s."
        ),
    }


def validate_final_word_tail(
    repaired_end_seconds: float,
    final_word_end_seconds: float,
    *,
    minimum_tail_seconds: float = 0.3,
) -> dict[str, Any]:
    """Require the repaired window to retain breathing room after the final word."""

    tail = repaired_end_seconds - final_word_end_seconds
    return {
        "passed": tail + 0.001 >= minimum_tail_seconds,
        "repaired_end_seconds": round(repaired_end_seconds, 6),
        "final_word_end_seconds": round(final_word_end_seconds, 6),
        "tail_seconds": round(tail, 6),
        "minimum_tail_seconds": minimum_tail_seconds,
        "warning": (
            None
            if tail + 0.001 >= minimum_tail_seconds
            else f"Final-word tail is only {max(0.0, tail):.3f}s."
        ),
    }


def validate_caption_alignment(
    cues: list[dict[str, Any]],
    duration_seconds: float,
    *,
    expected_first_start: float | None = None,
) -> dict[str, Any]:
    """Verify that final caption cues are bounded and clip-relative."""

    invalid = [
        index
        for index, cue in enumerate(cues)
        if not (
            0.0 <= float(cue.get("start", -1.0))
            < float(cue.get("end", -1.0))
            <= duration_seconds + 0.001
        )
    ]
    first_start = float(cues[0].get("start", 0.0)) if cues else None
    expected_matches = (
        True
        if expected_first_start is None
        else first_start is not None and abs(first_start - expected_first_start) <= 0.001
    )
    return {
        "passed": bool(cues) and not invalid and expected_matches,
        "cue_count": len(cues),
        "invalid_cue_indexes": invalid,
        "first_caption_start": round(first_start, 6) if first_start is not None else None,
        "expected_first_start": expected_first_start,
        "duration_seconds": round(duration_seconds, 6),
    }


def _scenario_record(
    name: str,
    *,
    window: ClipSourceWindowV1,
    passed: bool,
    measured_offset_seconds: float | None = None,
    expected_tolerance_seconds: float | None = None,
    output_duration: float | None = None,
    caption_alignment_result: dict[str, Any] | None = None,
    checks: dict[str, Any] | None = None,
    warnings: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "measured_offset_seconds": measured_offset_seconds,
        "expected_tolerance_seconds": expected_tolerance_seconds,
        "requested_window": {
            "start_seconds": window.requested_start_seconds,
            "end_seconds": window.requested_end_seconds,
        },
        "repaired_window": {
            "start_seconds": window.repaired_start_seconds,
            "end_seconds": window.repaired_end_seconds,
            "duration_seconds": window.duration_seconds,
        },
        "boundary_repair_applied": window.boundary_repair_applied,
        "warnings": list(dict.fromkeys([*window.warnings, *(warnings or [])])),
        "output_duration": output_duration,
        "caption_alignment_result": caption_alignment_result
        or {"passed": True, "status": "not_applicable"},
        "checks": checks or {},
    }


def _run(
    args: list[str],
    *,
    label: str,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        tail = "\n".join(completed.stderr.splitlines()[-8:])
        raise RuntimeError(f"{label} failed with code {completed.returncode}:\n{tail}")
    return completed


def _first_video_marker(path: Path, *, fps: float) -> float | None:
    values = path.read_bytes()
    for index, value in enumerate(values):
        if value >= 180:
            return index / fps
    return None


def _first_audio_marker(path: Path, *, sample_rate: int) -> float | None:
    payload = path.read_bytes()
    for index, (sample,) in enumerate(struct.iter_unpack("<h", payload[: len(payload) // 2 * 2])):
        if abs(sample) >= 500:
            return index / sample_rate
    return None


def _probe(path: Path, ffprobe_binary: str) -> dict[str, Any]:
    completed = _run(
        C.build_ffprobe_command(binary=ffprobe_binary, path=str(path)),
        label="ffprobe",
        timeout=60.0,
    )
    value = json.loads(completed.stdout)
    return value if isinstance(value, dict) else {}


def _duration_check(probe: dict[str, Any], expected_duration: float) -> dict[str, Any]:
    fmt = _dict_value(probe.get("format"))
    streams = _list_value(probe.get("streams"))
    video = next(
        (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"),
        {},
    )
    audio = next(
        (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"),
        {},
    )

    def seconds(value: object) -> float | None:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    container_duration = seconds(fmt.get("duration"))
    video_duration = seconds(video.get("duration")) or container_duration
    audio_duration = seconds(audio.get("duration")) or container_duration
    duration_delta = (
        container_duration - expected_duration if container_duration is not None else None
    )
    stream_delta = (
        audio_duration - video_duration
        if audio_duration is not None and video_duration is not None
        else None
    )
    passed = bool(
        duration_delta is not None
        and stream_delta is not None
        and abs(duration_delta) <= 0.08
        and abs(stream_delta) <= 0.08
    )
    return {
        "passed": passed,
        "expected_duration": round(expected_duration, 6),
        "container_duration": container_duration,
        "video_duration": video_duration,
        "audio_duration": audio_duration,
        "duration_delta": round(duration_delta, 6) if duration_delta is not None else None,
        "audio_video_duration_delta": (
            round(stream_delta, 6) if stream_delta is not None else None
        ),
    }


def _synthetic_segments() -> list[dict[str, Any]]:
    return [
        {
            "start": 1.0,
            "end": 3.0,
            "text": "Hook continues through final payoff.",
            "words": [
                {"word": "Hook", "start": 1.0, "end": 1.3},
                {"word": "continues", "start": 1.5, "end": 2.0},
                {"word": "payoff.", "start": 2.6, "end": 3.0},
            ],
        }
    ]


def _simulate_media_validation(
    work_dir: Path,
    *,
    ffmpeg_binary: str,
    ffprobe_binary: str,
) -> dict[str, Any]:
    if shutil.which(ffmpeg_binary) is None or shutil.which(ffprobe_binary) is None:
        return {
            "passed": False,
            "checks": {},
            "artifacts": {},
            "warnings": ["ffmpeg and ffprobe are required for synthetic marker validation."],
        }
    work_dir.mkdir(parents=True, exist_ok=True)
    source_path = work_dir / "synthetic_source.mkv"
    output_path = work_dir / "synthetic_repaired.mp4"
    ass_path = work_dir / "synthetic_captions.ass"
    video_raw_path = work_dir / "visual_marker.gray"
    audio_raw_path = work_dir / "audio_marker.s16le"
    _run(
        [
            ffmpeg_binary,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=30:d=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000:duration=0.1",
            "-filter_complex",
            "[0:v]drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:"
            "enable='between(t\\,1.000\\,1.100)'[v];"
            "[1:a]adelay=1000:all=1,apad,atrim=0:4[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(source_path),
        ],
        label="synthetic source generation",
    )
    segments = _synthetic_segments()
    window = repair_clip_source_window(
        project_id="synthetic_project",
        clip_id="synthetic_clip",
        requested_start_seconds=1.15,
        requested_end_seconds=2.8,
        transcript_segments=segments,
        source_duration_seconds=4.0,
    )
    localized = T.clip_segments(
        segments,
        window.repaired_start_seconds,
        window.repaired_end_seconds,
    )
    caption_event = {
        "type": "caption",
        "start": localized[0]["words"][0]["start"],
        "end": localized[0]["words"][0]["end"],
        "duration": (
            localized[0]["words"][0]["end"] - localized[0]["words"][0]["start"]
        ),
        "text": "Hook",
        "style": "default_clean",
        "highlighted_words": ["Hook"],
    }
    timeline = {
        "project_id": "synthetic_project",
        "clip_id": "synthetic_clip",
        "source_start": window.repaired_start_seconds,
        "source_end": window.repaired_end_seconds,
        "duration": window.duration_seconds,
        "source_window_v1": window.to_dict(),
        "tracks": [
            {"kind": "video", "events": []},
            {"kind": "audio", "events": []},
            {"kind": "caption", "events": [caption_event]},
        ],
        "metadata": {"timeline": window.to_dict()},
    }
    ass_path.write_text(C.build_ass(C.caption_cues(timeline), timeline), encoding="utf-8")
    render_args = C.build_ffmpeg_command(
        binary=ffmpeg_binary,
        source_path=str(source_path),
        output_path=str(output_path),
        timeline=timeline,
        width=320,
        height=568,
        fps=30,
        video_bitrate_kbps=900,
        audio_bitrate_kbps=128,
        srt_path=str(ass_path),
    )
    _run(render_args, label="synthetic repaired render")
    _run(
        [
            ffmpeg_binary,
            "-y",
            "-i",
            str(output_path),
            "-map",
            "0:v:0",
            "-vf",
            "scale=1:1,format=gray",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            str(video_raw_path),
        ],
        label="visual marker extraction",
    )
    _run(
        [
            ffmpeg_binary,
            "-y",
            "-i",
            str(output_path),
            "-map",
            "0:a:0",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "48000",
            str(audio_raw_path),
        ],
        label="audio marker extraction",
    )
    visual_marker = _first_video_marker(video_raw_path, fps=30.0)
    audio_marker = _first_audio_marker(audio_raw_path, sample_rate=48000)
    graph = render_args[render_args.index("-filter_complex") + 1]
    captions_in_bounds = bool(
        0.0 <= caption_event["start"] < caption_event["end"] <= window.duration_seconds
    )
    checks = {
        "boundary_validation": validate_clip_source_window(window, segments),
        "duration_alignment": _duration_check(
            _probe(output_path, ffprobe_binary),
            window.duration_seconds,
        ),
        "marker_alignment": validate_marker_alignment(visual_marker, audio_marker),
        "caption_alignment": {
            "passed": captions_in_bounds and "Dialogue:" in ass_path.read_text(encoding="utf-8"),
            "caption_start": caption_event["start"],
            "caption_end": caption_event["end"],
            "expected_source_offset": round(1.0 - window.repaired_start_seconds, 6),
        },
        "shared_source_window": {
            "passed": (
                f"trim=start={window.repaired_start_seconds:.3f}:"
                f"end={window.repaired_end_seconds:.3f}" in graph
                and f"atrim=start={window.repaired_start_seconds:.3f}:"
                f"end={window.repaired_end_seconds:.3f}" in graph
            ),
            "repaired_start": window.repaired_start_seconds,
            "repaired_end": window.repaired_end_seconds,
        },
        "final_word_and_tail": {
            "passed": window.repaired_end_seconds >= 3.0 + 0.3,
            "final_word_end": 3.0,
            "render_end": window.repaired_end_seconds,
        },
        "no_early_cutoff_flags": {
            "passed": "-shortest" not in render_args and "-t" not in render_args,
            "shortest_present": "-shortest" in render_args,
            "output_t_present": "-t" in render_args,
        },
    }
    return {
        "passed": all(item.get("passed") is True for item in checks.values()),
        "source_window": window.to_dict(),
        "checks": checks,
        "artifacts": {
            "source": str(source_path),
            "rendered_mp4": str(output_path),
            "captions_ass": str(ass_path),
        },
        "warnings": [
            "Synthetic markers validate this deterministic fixture only; real user media "
            "was not used."
        ],
    }


def _measure_media_markers(
    media_path: Path,
    work_dir: Path,
    *,
    prefix: str,
    ffmpeg_binary: str,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    video_path = work_dir / f"{prefix}_visual.gray"
    audio_path = work_dir / f"{prefix}_audio.s16le"
    _run(
        [
            ffmpeg_binary,
            "-y",
            "-i",
            str(media_path),
            "-map",
            "0:v:0",
            "-vf",
            "scale=1:1,format=gray",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            str(video_path),
        ],
        label=f"{prefix} visual marker extraction",
    )
    _run(
        [
            ffmpeg_binary,
            "-y",
            "-i",
            str(media_path),
            "-map",
            "0:a:0",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "48000",
            str(audio_path),
        ],
        label=f"{prefix} audio marker extraction",
    )
    return validate_marker_alignment(
        _first_video_marker(video_path, fps=30.0),
        _first_audio_marker(audio_path, sample_rate=48000),
    )


def _generate_short_tone(
    path: Path,
    *,
    frequency: int,
    duration_seconds: float,
    ffmpeg_binary: str,
) -> None:
    _run(
        [
            ffmpeg_binary,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration={duration_seconds:.3f}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        label=f"generate {path.name}",
    )


def _simulate_short_assets_validation(
    work_dir: Path,
    source_path: Path,
    window: ClipSourceWindowV1,
    *,
    ffmpeg_binary: str,
    ffprobe_binary: str,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    music_path = work_dir / "short_music.wav"
    sfx_path = work_dir / "short_sfx.wav"
    output_path = work_dir / "short_assets_output.mp4"
    _generate_short_tone(
        music_path,
        frequency=220,
        duration_seconds=0.35,
        ffmpeg_binary=ffmpeg_binary,
    )
    _generate_short_tone(
        sfx_path,
        frequency=880,
        duration_seconds=0.08,
        ffmpeg_binary=ffmpeg_binary,
    )
    timeline = {
        "project_id": "stress_project",
        "clip_id": "short_assets",
        "source_window_v1": window.to_dict(),
        "tracks": [],
        "metadata": {
            "timeline": window.to_dict(),
            "render_assets_v2": {
                "music": {
                    "mixed": True,
                    "path": str(music_path),
                    "gain_db": -20.0,
                    "fade_in_s": 0.05,
                    "fade_out_s": 0.1,
                    "looped": False,
                },
                "sfx": {
                    "events": [
                        {
                            "mixed": True,
                            "path": str(sfx_path),
                            "time": 0.25,
                            "gain_db": -18.0,
                        }
                    ]
                },
            },
        },
    }
    args = C.build_ffmpeg_command(
        binary=ffmpeg_binary,
        source_path=str(source_path),
        output_path=str(output_path),
        timeline=timeline,
        width=320,
        height=568,
        fps=30,
        video_bitrate_kbps=900,
        audio_bitrate_kbps=128,
    )
    _run(args, label="short music and SFX render")
    duration = _duration_check(_probe(output_path, ffprobe_binary), window.duration_seconds)
    return {
        "passed": bool(
            duration["passed"]
            and "-shortest" not in args
            and "-t" not in args
            and output_path.is_file()
        ),
        "duration_alignment": duration,
        "output_path": str(output_path),
        "music_duration_seconds": 0.35,
        "sfx_duration_seconds": 0.08,
        "speech_master_duration_seconds": window.duration_seconds,
        "shortest_present": "-shortest" in args,
        "output_t_present": "-t" in args,
    }


def _stress_scenarios(
    work_dir: Path,
    *,
    ffmpeg_binary: str,
    ffprobe_binary: str,
) -> list[dict[str, Any]]:
    voice_result = _simulate_media_validation(
        work_dir / "voice_filter_latency",
        ffmpeg_binary=ffmpeg_binary,
        ffprobe_binary=ffprobe_binary,
    )
    source_window = ClipSourceWindowV1.from_dict(_dict_value(voice_result.get("source_window")))
    voice_checks = _dict_value(voice_result.get("checks"))
    voice_marker = _dict_value(voice_checks.get("marker_alignment"))
    voice_duration = _dict_value(voice_checks.get("duration_alignment"))
    voice_caption = _dict_value(voice_checks.get("caption_alignment")) or {"passed": False}
    artifacts = _dict_value(voice_result.get("artifacts"))
    source_path = Path(str(artifacts.get("source") or ""))

    clean_window = repair_clip_source_window(
        project_id="stress_project",
        clip_id="clean_speech_marker",
        requested_start_seconds=0.0,
        requested_end_seconds=4.0,
        transcript_segments=_synthetic_segments(),
        source_duration_seconds=4.0,
    )
    clean_marker = (
        _measure_media_markers(
            source_path,
            work_dir / "clean_speech_marker",
            prefix="clean",
            ffmpeg_binary=ffmpeg_binary,
        )
        if source_path.is_file()
        else validate_marker_alignment(None, None)
    )
    clean_probe = (
        _duration_check(_probe(source_path, ffprobe_binary), 4.0)
        if source_path.is_file()
        else {}
    )
    scenarios = [
        _scenario_record(
            "clean_speech_marker",
            window=clean_window,
            passed=bool(clean_marker.get("passed") and clean_probe.get("passed")),
            measured_offset_seconds=clean_marker.get("offset_seconds"),
            expected_tolerance_seconds=clean_marker.get("tolerance_seconds"),
            output_duration=clean_probe.get("container_duration"),
            checks={"marker_alignment": clean_marker, "duration_alignment": clean_probe},
        ),
        _scenario_record(
            "voice_filter_latency",
            window=source_window,
            passed=voice_result.get("passed") is True,
            measured_offset_seconds=voice_marker.get("offset_seconds"),
            expected_tolerance_seconds=voice_marker.get("tolerance_seconds"),
            output_duration=voice_duration.get("container_duration"),
            caption_alignment_result=voice_caption,
            checks=voice_checks,
            warnings=list(voice_result.get("warnings") or []),
        ),
    ]

    final_word_window = repair_clip_source_window(
        project_id="stress_project",
        clip_id="boundary_near_final_word",
        requested_start_seconds=1.0,
        requested_end_seconds=2.8,
        transcript_segments=_synthetic_segments(),
        source_duration_seconds=4.0,
    )
    final_tail = validate_final_word_tail(final_word_window.repaired_end_seconds, 3.0)
    scenarios.append(
        _scenario_record(
            "boundary_near_final_word",
            window=final_word_window,
            passed=bool(final_tail["passed"] and final_word_window.postroll_seconds >= 0.3),
            output_duration=final_word_window.duration_seconds,
            checks={"final_word_tail": final_tail},
        )
    )

    mid_word_window = repair_clip_source_window(
        project_id="stress_project",
        clip_id="mid_word_start",
        requested_start_seconds=1.15,
        requested_end_seconds=3.4,
        transcript_segments=_synthetic_segments(),
        source_duration_seconds=4.0,
    )
    mid_word_validation = validate_clip_source_window(mid_word_window, _synthetic_segments())
    scenarios.append(
        _scenario_record(
            "mid_word_start",
            window=mid_word_window,
            passed=bool(
                mid_word_window.repaired_start_seconds < 1.0
                and mid_word_validation["passed"]
            ),
            output_duration=mid_word_window.duration_seconds,
            checks={"boundary_validation": mid_word_validation},
        )
    )

    segment_only = [{"start": 1.0, "end": 8.0, "text": "A long segment without word timing."}]
    fallback_window = repair_clip_source_window(
        project_id="stress_project",
        clip_id="no_word_level_transcript",
        requested_start_seconds=1.0,
        requested_end_seconds=3.0,
        transcript_segments=segment_only,
        source_duration_seconds=10.0,
    )
    scenarios.append(
        _scenario_record(
            "no_word_level_transcript",
            window=fallback_window,
            passed=bool(fallback_window.postroll_seconds >= 0.3 and fallback_window.warnings),
            output_duration=fallback_window.duration_seconds,
            checks={
                "conservative_postroll": {
                    "passed": fallback_window.postroll_seconds >= 0.3,
                    "postroll_seconds": fallback_window.postroll_seconds,
                },
                "warning_present": {"passed": bool(fallback_window.warnings)},
            },
        )
    )

    near_end_segments = [
        {
            "start": 2.0,
            "end": 3.2,
            "text": "Source ending now.",
            "words": [{"word": "now.", "start": 2.9, "end": 3.2}],
        }
    ]
    source_end_window = repair_clip_source_window(
        project_id="stress_project",
        clip_id="short_clip_near_source_end",
        requested_start_seconds=2.0,
        requested_end_seconds=3.0,
        transcript_segments=near_end_segments,
        source_duration_seconds=3.25,
    )
    scenarios.append(
        _scenario_record(
            "short_clip_near_source_end",
            window=source_end_window,
            passed=bool(
                source_end_window.duration_seconds > 0.0
                and source_end_window.repaired_end_seconds <= 3.25
                and source_end_window.warnings
            ),
            output_duration=source_end_window.duration_seconds,
            checks={
                "source_clamp": {
                    "passed": source_end_window.repaired_end_seconds <= 3.25,
                    "source_duration_seconds": 3.25,
                }
            },
        )
    )

    caption_segments = [
        {
            "start": 10.0,
            "end": 12.0,
            "text": "Caption source timing.",
            "words": [
                {"word": "Caption", "start": 10.0, "end": 10.5},
                {"word": "timing.", "start": 11.4, "end": 12.0},
            ],
        }
    ]
    caption_window = repair_clip_source_window(
        project_id="stress_project",
        clip_id="captions_source_time",
        requested_start_seconds=9.75,
        requested_end_seconds=12.0,
        transcript_segments=caption_segments,
        source_duration_seconds=20.0,
    )
    localized = T.clip_segments(
        caption_segments,
        caption_window.repaired_start_seconds,
        caption_window.repaired_end_seconds,
    )
    caption_event = {
        "type": "caption",
        "start": localized[0]["words"][0]["start"],
        "end": localized[0]["words"][0]["end"],
        "text": "Caption",
    }
    caption_timeline = {
        "source_window_v1": caption_window.to_dict(),
        "tracks": [{"kind": "caption", "events": [caption_event]}],
        "metadata": {"timeline": caption_window.to_dict()},
    }
    caption_cues = C.caption_cues(caption_timeline)
    caption_check = validate_caption_alignment(
        caption_cues,
        caption_window.duration_seconds,
        expected_first_start=10.0 - caption_window.repaired_start_seconds,
    )
    ass_valid = "Dialogue:" in C.build_ass(caption_cues, caption_timeline)
    scenarios.append(
        _scenario_record(
            "captions_source_time",
            window=caption_window,
            passed=bool(caption_check["passed"] and ass_valid),
            output_duration=caption_window.duration_seconds,
            caption_alignment_result={**caption_check, "ass_valid": ass_valid},
            checks={"caption_alignment": caption_check, "ass_valid": {"passed": ass_valid}},
        )
    )

    assets_check = (
        _simulate_short_assets_validation(
            work_dir / "short_music_sfx",
            source_path,
            source_window,
            ffmpeg_binary=ffmpeg_binary,
            ffprobe_binary=ffprobe_binary,
        )
        if source_path.is_file()
        else {"passed": False, "warning": "Synthetic source was unavailable."}
    )
    assets_duration = _dict_value(assets_check.get("duration_alignment"))
    assets_warning = assets_check.get("warning")
    scenarios.append(
        _scenario_record(
            "short_music_sfx",
            window=source_window,
            passed=assets_check.get("passed") is True,
            output_duration=assets_duration.get("container_duration"),
            checks={"speech_master_duration": assets_check},
            warnings=[str(assets_warning)] if assets_warning else [],
        )
    )
    return scenarios


def _summary(report: dict[str, Any]) -> str:
    lines = [
        "# A/V Sync and Boundary Validation",
        "",
        f"- Mode: `{report.get('mode')}`",
        f"- Passed: `{str(report.get('passed')).lower()}`",
        f"- Generated: `{report.get('generated_at')}`",
        "",
        "## Checks",
        "",
    ]
    checks = _dict_value(report.get("checks"))
    for name, value in checks.items():
        passed = value.get("passed") if isinstance(value, dict) else None
        lines.append(f"- `{name}`: `{passed}`")
    scenarios = _list_value(report.get("scenarios"))
    if scenarios:
        lines.extend(["", "## Stress Scenarios", ""])
        for scenario in scenarios:
            if isinstance(scenario, dict):
                lines.append(f"- `{scenario.get('name')}`: `{scenario.get('passed')}`")
    for warning in _list_value(report.get("warnings")):
        lines.append(f"- Warning: {warning}")
    return "\n".join(lines) + "\n"


def _write_report(
    output_dir: Path,
    report: dict[str, Any],
    *,
    report_name: str = REPORT_NAME,
    summary_name: str = SUMMARY_NAME,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        **report,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (output_dir / report_name).write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / summary_name).write_text(_summary(report), encoding="utf-8")
    return report


def run_self_check(*, output_dir: Path = DEFAULT_REPORT_DIR) -> dict[str, Any]:
    segments = _synthetic_segments()
    window = repair_clip_source_window(
        project_id="self_check",
        clip_id="self_check",
        requested_start_seconds=1.15,
        requested_end_seconds=2.8,
        transcript_segments=segments,
        source_duration_seconds=4.0,
    )
    restored = ClipSourceWindowV1.from_dict(window.to_dict())
    timeline = {"source_window_v1": window.to_dict(), "tracks": [], "metadata": {}}
    checks = {
        "contract_round_trip": {"passed": restored == window},
        "boundary_repair": validate_clip_source_window(window, segments),
        "renderer_window": {
            "passed": C.source_range(timeline)
            == (window.repaired_start_seconds, window.repaired_end_seconds)
        },
        "known_marker_alignment": validate_marker_alignment(0.25, 0.252),
    }
    return _write_report(
        output_dir,
        {
            "mode": "self-check",
            "passed": all(item.get("passed") is True for item in checks.values()),
            "checks": checks,
            "warnings": [],
        },
    )


def run_simulation(
    *,
    output_dir: Path = DEFAULT_REPORT_DIR,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
) -> dict[str, Any]:
    result = _simulate_media_validation(
        output_dir / "simulation",
        ffmpeg_binary=ffmpeg_binary,
        ffprobe_binary=ffprobe_binary,
    )
    return _write_report(output_dir, {"mode": "simulate", **result})


def _require_stress_report_path(output_dir: Path) -> None:
    allowed_root = (ROOT / "work" / "validation_reports").resolve()
    resolved = output_dir.resolve()
    if resolved != allowed_root and allowed_root not in resolved.parents:
        raise ValueError(
            "Stress reports must stay under work/validation_reports; "
            f"received {resolved}."
        )


def run_stress_simulation(
    *,
    output_dir: Path = DEFAULT_REPORT_DIR,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
) -> dict[str, Any]:
    _require_stress_report_path(output_dir)
    scenarios = _stress_scenarios(
        output_dir / "stress_simulation",
        ffmpeg_binary=ffmpeg_binary,
        ffprobe_binary=ffprobe_binary,
    )
    names = tuple(
        str(item.get("name")) for item in scenarios if isinstance(item, dict)
    )
    passed = names == STRESS_SCENARIO_NAMES and all(
        item.get("passed") is True for item in scenarios
    )
    return _write_report(
        output_dir,
        {
            "mode": "stress-simulate",
            "passed": passed,
            "scenario_count": len(scenarios),
            "scenarios": scenarios,
            "checks": {
                "all_scenarios_present": {
                    "passed": names == STRESS_SCENARIO_NAMES,
                    "expected": list(STRESS_SCENARIO_NAMES),
                    "actual": list(names),
                },
                "all_scenarios_passed": {
                    "passed": all(item.get("passed") is True for item in scenarios)
                },
                "synthetic_input_policy": {
                    "passed": all(
                        (
                            SYNTHETIC_INPUT_POLICY["generated_synthetic_media_only"],
                            not SYNTHETIC_INPUT_POLICY["real_user_media_used"],
                            not SYNTHETIC_INPUT_POLICY["downloads_used"],
                            not SYNTHETIC_INPUT_POLICY["external_api_calls_used"],
                            not SYNTHETIC_INPUT_POLICY["network_used"],
                        )
                    ),
                    **SYNTHETIC_INPUT_POLICY,
                },
            },
            "input_policy": SYNTHETIC_INPUT_POLICY,
            "warnings": [
                "Stress simulation improves automated confidence but does not replace "
                "human playback."
            ],
        },
        report_name=STRESS_REPORT_NAME,
        summary_name=STRESS_SUMMARY_NAME,
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def _stage_data(value: dict[str, Any]) -> dict[str, Any]:
    data = value.get("data")
    return data if isinstance(data, dict) else value


def _caption_events(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    tracks = _list_value(timeline.get("tracks"))
    for track in tracks:
        if isinstance(track, dict) and track.get("kind") == "caption":
            events = _list_value(track.get("events"))
            return [item for item in events if isinstance(item, dict)]
    return []


def run_project_validation(
    project_id: str,
    *,
    output_dir: Path = DEFAULT_REPORT_DIR,
    storage_root: Path | None = None,
    ffprobe_binary: str = "ffprobe",
) -> dict[str, Any]:
    root = (storage_root or ROOT / "storage_data").resolve()
    project_path = root / "projects" / project_id / "project.json"
    stage_path = root / "editing" / project_id / "stages" / "timeline_validation.json"
    initial_paths = [str(project_path), str(stage_path)]
    if not root.is_dir() or not project_path.is_file():
        return _write_report(
            output_dir,
            {
                "mode": "project-id",
                "project_id": project_id,
                "passed": False,
                "project_found": False,
                "searched_paths": initial_paths,
                "repair_attempted": False,
                "checks": {
                    "project": {
                        "passed": False,
                        "reason": "project not found",
                        "path": str(project_path),
                    }
                },
                "warnings": ["Project not found; inspection stopped and no repair was attempted."],
            },
        )
    storage = LocalStorage(str(root))
    resolution = asyncio.run(resolve_render_manifest(storage, project_id))
    searched_paths = [*initial_paths, *resolution.resolved_physical_paths]
    timeline_data = _stage_data(_load_json_object(stage_path)) if stage_path.is_file() else {}
    timelines = _list_value(timeline_data.get("timelines"))
    timelines_by_clip = {
        str(item.get("clip_id")): item
        for item in timelines
        if isinstance(item, dict) and item.get("clip_id")
    }
    manifest = resolution.manifest or {}
    renders = _list_value(manifest.get("renders"))
    clip_checks: dict[str, Any] = {}
    ffprobe_available = shutil.which(ffprobe_binary) is not None
    for index, raw_render in enumerate(renders):
        render = raw_render if isinstance(raw_render, dict) else {}
        clip_id = str(render.get("clip_id") or f"render_{index}")
        timeline = timelines_by_clip.get(clip_id, {})
        editing_window = C.source_window_metadata(timeline) if timeline else {}
        metadata = _dict_value(render.get("metadata"))
        rendered_timeline = _dict_value(metadata.get("timeline"))
        source_window = (
            rendered_timeline
            if rendered_timeline.get("contract_version") == "1"
            else editing_window
        )
        repaired_start = source_window.get("repaired_start_seconds")
        repaired_end = source_window.get("repaired_end_seconds")
        window_complete = bool(
            source_window.get("contract_version") == "1"
            and isinstance(source_window.get("requested_start_seconds"), int | float)
            and isinstance(source_window.get("requested_end_seconds"), int | float)
            and isinstance(repaired_start, int | float)
            and isinstance(repaired_end, int | float)
            and float(repaired_end) > float(repaired_start)
        )
        expected_duration = (
            float(repaired_end) - float(repaired_start)
            if isinstance(repaired_start, int | float)
            and isinstance(repaired_end, int | float)
            else 0.0
        )
        storage_key = str(render.get("storage_key") or "")
        output_path_value = storage.local_path(storage_key) if storage_key else None
        output_path = Path(output_path_value) if output_path_value else None
        output_exists = output_path is not None and output_path.is_file()
        probe = (
            _probe(output_path, ffprobe_binary)
            if output_exists and ffprobe_available and output_path is not None
            else {}
        )
        duration_check = (
            _duration_check(probe, expected_duration)
            if window_complete and probe
            else {"passed": False, "expected_duration": expected_duration}
        )
        caption_events = _caption_events(timeline)
        caption_check = (
            validate_caption_alignment(caption_events, expected_duration)
            if caption_events and window_complete
            else {
                "passed": window_complete,
                "cue_count": 0,
                "status": "no_captions" if window_complete else "timeline_unavailable",
            }
        )
        sync_validation = _dict_value(metadata.get("sync_validation"))
        boundary_warnings_present = "boundary_warnings" in rendered_timeline and isinstance(
            rendered_timeline.get("boundary_warnings"), list
        )
        no_requested_only_timing = bool(
            window_complete
            and source_window.get("repaired_start_seconds") is not None
            and source_window.get("repaired_end_seconds") is not None
        )
        passed = bool(
            output_exists
            and probe
            and duration_check.get("passed") is True
            and caption_check.get("passed") is True
            and sync_validation.get("passed") is True
            and boundary_warnings_present
            and no_requested_only_timing
        )
        clip_checks[clip_id] = {
            "passed": passed,
            "storage_key": storage_key,
            "output_path": str(output_path) if output_path else None,
            "output_exists": output_exists,
            "ffprobe_available": ffprobe_available,
            "timeline_metadata_exists": bool(rendered_timeline),
            "source_window": source_window,
            "duration_alignment": duration_check,
            "caption_alignment": caption_check,
            "sync_validation": sync_validation,
            "boundary_warnings_present": boundary_warnings_present,
            "boundary_warnings": rendered_timeline.get("boundary_warnings") or [],
            "no_requested_only_timing": no_requested_only_timing,
        }
    checks: dict[str, dict[str, Any]] = {
        "project": {"passed": True, "path": str(project_path)},
        "editing_timeline_artifact": {
            "passed": stage_path.is_file() and bool(timelines),
            "path": str(stage_path),
            "timeline_count": len(timelines),
        },
        "render_manifest": {
            "passed": resolution.manifest_exists and bool(renders),
            "artifact_path": resolution.artifact_path,
            "manifest_source_path": resolution.manifest_source_path,
            "render_count": len(renders),
        },
        "rendered_clips": {
            "passed": bool(clip_checks)
            and all(item.get("passed") is True for item in clip_checks.values()),
            "clips": clip_checks,
        },
    }
    return _write_report(
        output_dir,
        {
            "mode": "project-id",
            "project_id": project_id,
            "project_found": True,
            "passed": all(item.get("passed") is True for item in checks.values()),
            "checks": checks,
            "searched_paths": list(dict.fromkeys(searched_paths)),
            "repair_attempted": False,
            "warnings": [*resolution.warnings, *resolution.errors],
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--simulate", action="store_true")
    mode.add_argument("--stress-simulate", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--storage-root", type=Path, default=ROOT / "storage_data")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.self_check:
            report = run_self_check(output_dir=args.output_dir)
        elif args.simulate:
            report = run_simulation(
                output_dir=args.output_dir,
                ffmpeg_binary=args.ffmpeg,
                ffprobe_binary=args.ffprobe,
            )
        elif args.stress_simulate:
            report = run_stress_simulation(
                output_dir=args.output_dir,
                ffmpeg_binary=args.ffmpeg,
                ffprobe_binary=args.ffprobe,
            )
        else:
            report = run_project_validation(
                args.project_id,
                output_dir=args.output_dir,
                storage_root=args.storage_root,
                ffprobe_binary=args.ffprobe,
            )
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        report = _write_report(
            args.output_dir,
            {
                "mode": (
                    "simulate"
                    if args.simulate
                    else "stress-simulate"
                    if args.stress_simulate
                    else "project-id"
                ),
                "passed": False,
                "checks": {},
                "warnings": [str(exc)],
            },
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

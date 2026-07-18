"""Validate canonical clip boundaries and content-level A/V marker alignment."""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.editing import timeline as T  # noqa: E402, N812
from olympus.editing.boundary_repair import (  # noqa: E402
    repair_clip_source_window,
    validate_clip_source_window,
)
from olympus.editing.timeline_contracts import ClipSourceWindowV1  # noqa: E402
from olympus.rendering import command as C  # noqa: E402, N812

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "av_sync_boundaries"
REPORT_NAME = "av_sync_boundaries_report.json"
SUMMARY_NAME = "av_sync_boundaries_summary.md"


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
    fmt = probe.get("format") if isinstance(probe.get("format"), dict) else {}
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
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
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    for name, value in checks.items():
        passed = value.get("passed") if isinstance(value, dict) else None
        lines.append(f"- `{name}`: `{passed}`")
    for warning in report.get("warnings") or []:
        lines.append(f"- Warning: {warning}")
    return "\n".join(lines) + "\n"


def _write_report(output_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        **report,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (output_dir / REPORT_NAME).write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / SUMMARY_NAME).write_text(_summary(report), encoding="utf-8")
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


def run_project_validation(
    project_id: str,
    *,
    output_dir: Path = DEFAULT_REPORT_DIR,
) -> dict[str, Any]:
    stage_path = (
        ROOT
        / "storage_data"
        / "editing"
        / project_id
        / "stages"
        / "timeline_validation.json"
    )
    if not stage_path.is_file():
        return _write_report(
            output_dir,
            {
                "mode": "project-id",
                "project_id": project_id,
                "passed": False,
                "checks": {"timeline_artifact": {"passed": False, "path": str(stage_path)}},
                "warnings": ["The persisted editing timeline artifact was not found."],
            },
        )
    value = json.loads(stage_path.read_text(encoding="utf-8-sig"))
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    timelines = data.get("timelines") if isinstance(data.get("timelines"), list) else []
    checks: dict[str, Any] = {}
    for index, raw in enumerate(timelines):
        timeline = raw if isinstance(raw, dict) else {}
        source_window = C.source_window_metadata(timeline)
        checks[f"timeline_{index}"] = {
            "passed": source_window.get("contract_version") == "1",
            "clip_id": timeline.get("clip_id"),
            "source_window": source_window,
        }
    return _write_report(
        output_dir,
        {
            "mode": "project-id",
            "project_id": project_id,
            "passed": bool(checks) and all(item.get("passed") is True for item in checks.values()),
            "checks": checks,
            "warnings": [
                "Project mode validates persisted timeline contracts; it does not use user media."
            ],
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--simulate", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
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
        else:
            report = run_project_validation(args.project_id, output_dir=args.output_dir)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        report = _write_report(
            args.output_dir,
            {
                "mode": "simulate" if args.simulate else "project-id",
                "passed": False,
                "checks": {},
                "warnings": [str(exc)],
            },
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

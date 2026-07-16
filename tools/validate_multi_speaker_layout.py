"""Validate anonymous Multi-Speaker Layout V2 planning and render truth."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from olympus.editing.analyzers import _normalize_face_detections
from olympus.editing.multi_speaker import build_multi_speaker_layout
from olympus.platform.config import get_settings


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


def _layout_from_face_artifact(args: argparse.Namespace) -> dict[str, Any]:
    raw = _load(args.face_artifact)
    detections = _normalize_face_detections(
        raw,
        clip_start=args.clip_start,
        clip_duration=args.duration,
        source_width=args.source_width,
        source_height=args.source_height,
    )
    speaker_timeline = []
    if args.speaker_artifact:
        speaker_timeline = _stage_data(_load(args.speaker_artifact)).get("timeline") or []
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
    decision = layout.get("decision") if isinstance(layout.get("decision"), dict) else {}
    render_plan = layout.get("render_plan") if isinstance(layout.get("render_plan"), dict) else {}
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--simulate", action="store_true")
    modes.add_argument("--face-artifact", type=Path)
    modes.add_argument("--rendered-file", type=Path)
    modes.add_argument("--project-id")
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
    return parser.parse_args()


def main() -> int:
    report = _report(_parse_args())
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["multi_speaker_validation_report"]["pass_fail"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

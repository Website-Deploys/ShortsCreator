"""Validate Motion Graphics / Effects V2 plans and rendered truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from olympus.editing.motion import build_motion_intelligence
from olympus.platform.config import get_settings
from olympus.rendering import command as C  # noqa: N812 (module alias is intentional)
from olympus.rendering.ffmpeg_renderer import _render_metadata


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


def _motion_metadata(
    value: dict[str, Any], clip_id: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _manifest(value)
    renders = manifest.get("renders") if isinstance(manifest.get("renders"), list) else []
    if not renders:
        return {}, {}
    render_value = next(
        (
            item
            for item in renders
            if isinstance(item, dict)
            and (
                item.get("clip_id") == clip_id
                or Path(str(item.get("storage_key") or item.get("output_key") or "")).stem
                == clip_id
            )
        ),
        renders[0] if clip_id is None else {},
    )
    render: dict[str, Any] = render_value if isinstance(render_value, dict) else {}
    metadata_value = render.get("metadata")
    metadata: dict[str, Any] = metadata_value if isinstance(metadata_value, dict) else {}
    motion = metadata.get("motion_intelligence_v2")
    validation = metadata.get("motion_render_validation")
    return (
        motion if isinstance(motion, dict) else {},
        validation if isinstance(validation, dict) else {},
    )


def _probe(path: Path) -> dict[str, Any]:
    settings = get_settings().rendering
    if shutil.which(settings.ffprobe_binary) is None:
        return {"available": False, "reason": "ffprobe is unavailable"}
    completed = subprocess.run(
        C.build_ffprobe_command(binary=settings.ffprobe_binary, path=str(path)),
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


def _face_plan(duration: float) -> dict[str, Any]:
    return {
        "mode": "single_face_tracking",
        "input_analysis": {"detected_face_count": 1},
        "crop_keyframes": [
            {"time": 0.0, "x_center": 0.5, "y_center": 0.43, "confidence": 0.9},
            {"time": duration, "x_center": 0.52, "y_center": 0.43, "confidence": 0.9},
        ],
        "warnings": [],
    }


def _simulated_contract(niche: str, hook_category: str, duration: float = 8.0) -> dict[str, Any]:
    clip = {
        "clip_id": "motion_simulation",
        "source_start": 0.0,
        "source_end": duration,
        "duration": duration,
    }
    blueprint = {
        "content_niche": {"primary": niche},
        "hook_v2": {"category": hook_category, "score": 0.86},
        "story_v2_guidance": {
            "story_guidance_used": True,
            "story_shape": "setup_tension_payoff",
            "turning_point": {"time": duration * 0.48},
            "payoff": "The final lesson lands here.",
            "payoff_present": True,
        },
        "ending_payoff_v2": {
            "ending_type": "lesson",
            "ending_line": "The final lesson lands here.",
            "payoff_present": True,
        },
        "closing_payoff": {"timestamp": duration - 1.7},
        "viral_score_v2": {"overall": 0.82},
        "editing_trend_guidance": {"pacing_style": "restrained_dynamic"},
    }
    caption_intelligence = {
        "input_signals": {"speech_density": 2.8},
        "style_decision": {"caption_style": "bold_hook_word_highlight"},
        "caption_safe_zone": {"strategy": "tracked_face_opposite_zone", "collision_risk": "low"},
    }
    return build_motion_intelligence(
        clip=clip,
        blueprint=blueprint,
        caption_intelligence=caption_intelligence,
        music_intelligence={"decision": {"music_role": "motivational_drive"}},
        face_plan=_face_plan(duration),
        sfx_plan={"enabled": True, "effects": []},
        project_id="motion_validation",
    )


def _timeline(contract: dict[str, Any], duration: float) -> dict[str, Any]:
    effects = contract.get("effect_plan", {}).get("effects", [])
    face_plan = _face_plan(duration)
    return {
        "clip_id": "motion_synthetic",
        "source_start": 0.0,
        "source_end": duration,
        "duration": duration,
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
                        "reason": "synthetic validation source",
                        "confidence": 1.0,
                        "evidence": [],
                    },
                    *effects,
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
                        "reason": "synthetic validation audio",
                        "confidence": 1.0,
                        "evidence": [],
                    }
                ],
            },
            {
                "kind": "caption",
                "events": [
                    {
                        "id": "caption",
                        "type": "caption",
                        "start": 0.15,
                        "end": 2.2,
                        "text": "MOTION VALIDATION",
                        "reason": "prove captions remain after motion",
                        "confidence": 1.0,
                        "evidence": [],
                    }
                ],
            },
            {"kind": "markers", "events": []},
        ],
        "metadata": {
            "face_tracking_plan": face_plan,
            "multi_speaker_layout_v2": face_plan,
            "motion_intelligence_v2": contract,
            "motion_safety_validation": contract.get("motion_safety_validation"),
            "editing_v2": {
                "motion_intelligence_v2": contract,
                "motion_plan": {"events": effects},
                "face_tracking_plan": face_plan,
                "multi_speaker_layout_v2": face_plan,
                "voice_enhancement_plan": {"filters": ["highpass", "loudnorm"]},
                "video_enhancement_plan": {"profile": "clean_high_retention"},
                "caption_style": {"style": "default_clean"},
            },
            "render_assets_v2": {"music": {}, "sfx": {}},
        },
    }


def _run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _extract_frames(
    rendered_file: Path,
    contract: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    ffmpeg = get_settings().rendering.ffmpeg_binary
    if shutil.which(ffmpeg) is None:
        return {"performed": False, "frames_extracted": 0, "reason": "ffmpeg unavailable"}
    effects = contract.get("effect_plan", {}).get("effects", [])
    hashes: list[dict[str, Any]] = []
    for index, effect in enumerate(effects[:3]):
        if not isinstance(effect, dict):
            continue
        timestamp = float(effect.get("start_time") or 0.0) + 0.15
        destination = output_dir / f"motion_probe_{index}.png"
        completed = _run(
            [
                ffmpeg,
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(rendered_file),
                "-frames:v",
                "1",
                str(destination),
            ],
            timeout=60,
        )
        if completed.returncode == 0 and destination.exists():
            hashes.append(
                {
                    "effect_type": effect.get("type"),
                    "timestamp": round(timestamp, 3),
                    "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                }
            )
    return {
        "performed": True,
        "frames_extracted": len(hashes),
        "frame_hashes": hashes,
        "note": "Frame existence/hash was measured; visual quality was not judged.",
    }


def _synthetic_render() -> dict[str, Any]:
    settings = get_settings().rendering
    if shutil.which(settings.ffmpeg_binary) is None:
        return {"passed": False, "warnings": ["ffmpeg is unavailable"]}
    duration = 8.0
    contract = _simulated_contract("motivational", "curiosity_gap", duration)
    timeline = _timeline(contract, duration)
    with tempfile.TemporaryDirectory(prefix="olympus-motion-") as temporary:
        root = Path(temporary)
        source = root / "source.mp4"
        output = root / "motion.mp4"
        captions = root / "captions.ass"
        source_result = _run(
            [
                settings.ffmpeg_binary,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=1280x720:rate=30",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000",
                "-t",
                f"{duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(source),
            ]
        )
        if source_result.returncode != 0:
            return {
                "passed": False,
                "warnings": [source_result.stderr.splitlines()[-1] or "source generation failed"],
            }
        caption_content = C.build_ass(C.caption_cues(timeline), timeline)
        captions.write_text(caption_content, encoding="utf-8")
        command = C.build_ffmpeg_command(
            binary=settings.ffmpeg_binary,
            source_path=str(source),
            output_path=str(output),
            timeline=timeline,
            width=1080,
            height=1920,
            fps=30,
            video_bitrate_kbps=3500,
            audio_bitrate_kbps=160,
            srt_path=str(captions),
        )
        render_result = _run(command)
        if render_result.returncode != 0:
            return {
                "passed": False,
                "warnings": [render_result.stderr.splitlines()[-1] or "render failed"],
            }
        probe = _probe(output)
        graph = command[command.index("-filter_complex") + 1]
        metadata = _render_metadata(
            timeline,
            render_result.stderr.splitlines()[-8:],
            probe,
            {
                "captions_planned": True,
                "ass_file_created": True,
                "ass_file_exists": captions.exists(),
                "ass_non_empty": bool(caption_content.strip()),
                "ass_valid": True,
                "ass_event_count": 1,
                "ass_styles_count": 1,
                "ffmpeg_filter_present": "subtitles=" in graph,
                "output_exists": output.exists(),
                "warnings": [],
            },
            {
                "ffmpeg_filtergraph": graph,
                "expected_motion_filters": C.motion_expected_filters(timeline),
                "output_exists": output.exists(),
            },
        )
        frame_probe = _extract_frames(output, contract, root)
        validation = metadata.get("motion_render_validation", {})
        validation = validation if isinstance(validation, dict) else {}
        validation["visual_probe_performed"] = frame_probe.get("performed") is True
        validation["frames_extracted"] = frame_probe.get("frames_extracted", 0)
        return {
            "passed": bool(validation.get("passed") and frame_probe.get("frames_extracted")),
            "motion_intelligence": metadata.get("motion_intelligence_v2"),
            "render_validation": validation,
            "ffprobe": probe,
            "frame_probe": frame_probe,
            "filtergraph_contains_zoompan": "zoompan=" in graph,
            "filtergraph_contains_subtitles": "subtitles=" in graph,
            "warnings": validation.get("warnings") or [],
        }


def _project_motion(project_id: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    root = Path(get_settings().storage.local_root)
    editing_path = root / "editing" / project_id / "stages" / "timeline_validation.json"
    render_path = root / "render" / project_id / "run" / "stages" / "generate_render_manifest.json"
    warnings: list[str] = []
    motion: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    if editing_path.exists():
        editing = _stage_data(_load(editing_path))
        timelines = editing.get("timelines") if isinstance(editing.get("timelines"), list) else []
        if timelines and isinstance(timelines[0], dict):
            metadata = timelines[0].get("metadata")
            if isinstance(metadata, dict):
                motion = metadata.get("motion_intelligence_v2") or {}
    else:
        warnings.append(f"Editing timeline artifact not found at {editing_path}")
    if render_path.exists():
        rendered_motion, validation = _motion_metadata(_load(render_path))
        motion = rendered_motion or motion
    else:
        warnings.append(f"Render manifest artifact not found at {render_path}")
    return motion, validation, warnings


def _report(args: argparse.Namespace) -> dict[str, Any]:
    mode = "unknown"
    motion: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    probe: dict[str, Any] | None = None
    frame_probe: dict[str, Any] | None = None
    warnings: list[str] = []
    synthetic: dict[str, Any] | None = None
    if args.simulate:
        mode = "simulate"
        motion = _simulated_contract(args.niche, args.hook_category, args.duration)
        validation = motion.get("validation", {})
    elif args.synthetic_render:
        mode = "synthetic_render"
        synthetic = _synthetic_render()
        motion = synthetic.get("motion_intelligence", {})
        validation = synthetic.get("render_validation", {})
        probe = synthetic.get("ffprobe")
        frame_probe = synthetic.get("frame_probe")
        warnings.extend(synthetic.get("warnings") or [])
    elif args.project_id:
        mode = "project"
        motion, validation, project_warnings = _project_motion(args.project_id)
        warnings.extend(project_warnings)
    elif args.rendered_file:
        mode = "rendered_file"
        probe = _probe(args.rendered_file)
        if args.manifest:
            motion, validation = _motion_metadata(
                _load(args.manifest), args.rendered_file.stem
            )
            with tempfile.TemporaryDirectory(prefix="olympus-motion-probe-") as temporary:
                frame_probe = _extract_frames(args.rendered_file, motion, Path(temporary))
        else:
            warnings.append("A render manifest is required to validate effect truth.")
    elif args.manifest:
        mode = "manifest"
        motion, validation = _motion_metadata(_load(args.manifest))

    decision_value = motion.get("decision")
    decision: dict[str, Any] = decision_value if isinstance(decision_value, dict) else {}
    effect_plan_value = motion.get("effect_plan")
    effect_plan: dict[str, Any] = (
        effect_plan_value if isinstance(effect_plan_value, dict) else {}
    )
    effects_value = effect_plan.get("effects")
    effects: list[Any] = effects_value if isinstance(effects_value, list) else []
    safety_value = motion.get("motion_safety_validation")
    safety: dict[str, Any] = safety_value if isinstance(safety_value, dict) else {}
    if mode == "simulate":
        passed = bool(motion and safety.get("passed") and decision.get("motion_style"))
    elif mode == "synthetic_render":
        passed = bool(synthetic and synthetic.get("passed"))
    elif mode == "rendered_file":
        expected_frame_count = min(len(effects), 3)
        passed = bool(
            motion
            and validation.get("passed") is True
            and probe
            and probe.get("available") is True
            and frame_probe
            and expected_frame_count > 0
            and frame_probe.get("frames_extracted", 0) == expected_frame_count
        )
    else:
        passed = bool(motion and validation.get("passed") is True)
    return {
        "motion_effects_validation_report": {
            "mode": mode,
            "motion_style": decision.get("motion_style"),
            "effects_planned": len(effects),
            "effects_rendered": validation.get("effects_rendered", 0),
            "hook_effect": effect_plan.get("hook_effect"),
            "pattern_interrupts": effect_plan.get("pattern_interrupts") or [],
            "payoff_effect": effect_plan.get("payoff_effect"),
            "safety_validation": safety,
            "render_validation": validation,
            "ffprobe": probe,
            "frame_probe": frame_probe,
            "warnings": list(dict.fromkeys(warnings)),
            "pass_fail": passed,
        }
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--synthetic-render", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--rendered-file", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--niche", default="motivational")
    parser.add_argument("--hook-category", default="curiosity_gap")
    parser.add_argument("--duration", type=float, default=8.0)
    args = parser.parse_args(argv)
    standalone_manifest = bool(args.manifest and not args.rendered_file)
    modes = sum(
        bool(value)
        for value in (
            args.simulate,
            args.synthetic_render,
            standalone_manifest,
            args.rendered_file,
            args.project_id,
        )
    )
    if modes != 1:
        parser.error(
            "choose exactly one mode: --simulate, --synthetic-render, --manifest, "
            "--rendered-file, or --project-id"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    report = _report(_parse_args(argv))
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["motion_effects_validation_report"]["pass_fail"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate Caption Intelligence V2 plans, ASS files, and rendered truth."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from olympus.editing import captions as CAP  # noqa: N812
from olympus.editing import timeline as T  # noqa: N812
from olympus.platform.config import get_settings
from olympus.rendering import command as C  # noqa: N812


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


def _first_render_metadata(value: dict[str, Any]) -> dict[str, Any]:
    records = _render_metadata_records(value)
    return records[0] if records else {}


def _render_metadata_records(value: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = _manifest(value)
    renders = manifest.get("renders")
    records: list[dict[str, Any]] = []
    if isinstance(renders, list):
        for raw_render in renders:
            render = raw_render if isinstance(raw_render, dict) else {}
            metadata = render.get("metadata")
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            clip_id = render.get("clip_id") or metadata.get("clip_id")
            if clip_id:
                metadata["clip_id"] = clip_id
            records.append(metadata)
    if records:
        return records
    metadata = manifest.get("metadata")
    return [dict(metadata)] if isinstance(metadata, dict) else []


def _probe(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return {"available": False, "reason": "ffprobe is not available on PATH"}
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration:stream=codec_type,codec_name,width,height,"
                    "sample_rate,duration"
                ),
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc)}
    if completed.returncode != 0:
        return {"available": False, "reason": completed.stderr.strip() or "ffprobe failed"}
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"available": False, "reason": "ffprobe returned invalid JSON"}
    return {"available": True, **value}


def _simulation(niche: str, hook_category: str) -> tuple[dict[str, Any], dict[str, Any]]:
    events = [
        T.event(
            "caption",
            0.05,
            1.65,
            reason="simulation word timestamps",
            confidence=0.95,
            text="This mistake changes everything",
            speaker="spk_0",
            word_timings=[
                {"word": "This", "start": 0.05, "end": 0.22},
                {"word": "mistake", "start": 0.25, "end": 0.55},
                {"word": "changes", "start": 0.58, "end": 0.9},
                {"word": "everything", "start": 0.93, "end": 1.65},
            ],
            timing_source="word_level",
            timing_quality="word_level",
            estimated=False,
            highlighted_words=[],
            style="default_clean",
            animation="phrase_reveal",
            readability=T.caption_readability("This mistake changes everything", 0.05, 1.65),
        ),
        T.event(
            "caption",
            2.4,
            4.2,
            reason="simulation word timestamps",
            confidence=0.95,
            text="The payoff is clarity",
            speaker="spk_0",
            word_timings=[],
            timing_source="word_level",
            timing_quality="word_level",
            estimated=False,
            highlighted_words=[],
            style="default_clean",
            animation="phrase_reveal",
            readability=T.caption_readability("The payoff is clarity", 2.4, 4.2),
        ),
    ]
    decorated, intelligence = CAP.build_caption_intelligence(
        clip={"clip_id": "caption_simulation", "duration": 5.0},
        events=events,
        timing_quality={
            "source": "word_level",
            "estimated": False,
            "quality_level": "word_level",
            "warnings": [],
        },
        blueprint={
            "content_niche": {"primary": niche},
            "hook_v2": {
                "category": hook_category,
                "hook_line": "This mistake changes everything",
            },
            "ending_payoff_v2": {"ending_line": "The payoff is clarity"},
        },
        face_plan={"mode": "center_fallback"},
        project_id="caption_simulation",
        captions_enabled=True,
    )
    timeline = {
        "metadata": {"caption_intelligence_v2": intelligence},
        "tracks": [{"kind": "caption", "events": decorated}],
    }
    ass = C.build_ass(C.caption_cues(timeline), timeline)
    return intelligence, C.validate_ass(ass)


def _project_caption_data(project_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    root = Path(get_settings().storage.local_root)
    editing_candidates = [
        root / "editing" / project_id / "stages" / "timeline_validation.json",
        root / "editing" / project_id / "run" / "stages" / "timeline_validation.json",
    ]
    manifest_candidates = [
        root / "render" / project_id / "manifest.json",
        root / "render" / project_id / "index.json",
        root / "render" / project_id / "run" / "stages" / "generate_render_manifest.json",
    ]
    warnings: list[str] = []
    timeline_metadata: dict[str, dict[str, Any]] = {}
    render_metadata: dict[str, dict[str, Any]] = {}
    clip_order: list[str] = []
    editing_path = next((path for path in editing_candidates if path.exists()), None)
    if editing_path:
        editing = _stage_data(_load(editing_path))
        timelines = editing.get("timelines")
        if isinstance(timelines, list):
            for raw_timeline in timelines:
                timeline = raw_timeline if isinstance(raw_timeline, dict) else {}
                clip_id = str(timeline.get("clip_id") or "").strip()
                metadata = timeline.get("metadata")
                if not clip_id or not isinstance(metadata, dict):
                    continue
                timeline_metadata[clip_id] = dict(metadata)
                clip_order.append(clip_id)
    else:
        warnings.append(
            "Editing caption artifact was not found in direct or run-stage local storage."
        )
    manifest_path = next((path for path in manifest_candidates if path.exists()), None)
    if manifest_path:
        for metadata in _render_metadata_records(_load(manifest_path)):
            clip_id = str(metadata.get("clip_id") or "").strip()
            if not clip_id:
                continue
            render_metadata[clip_id] = metadata
            if clip_id not in clip_order:
                clip_order.append(clip_id)
    else:
        warnings.append("Project render manifest was not found in local storage.")
    records: list[dict[str, Any]] = []
    for clip_id in clip_order:
        metadata = {"clip_id": clip_id}
        metadata.update(timeline_metadata.get(clip_id, {}))
        metadata.update(render_metadata.get(clip_id, {}))
        if manifest_path:
            metadata["manifest_path"] = str(manifest_path)
        if clip_id not in timeline_metadata:
            warnings.append(f"Editing caption metadata is missing for {clip_id}.")
        if clip_id not in render_metadata:
            warnings.append(f"Render caption metadata is missing for {clip_id}.")
        records.append(metadata)
    if not records:
        warnings.append("No clip-level caption metadata was found for this project.")
    return records, warnings


def _metadata_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    intelligence = metadata.get("caption_intelligence_v2")
    intelligence = intelligence if isinstance(intelligence, dict) else {}
    return {
        "clip_id": metadata.get("clip_id"),
        "caption_intelligence": intelligence,
        "style_decision": intelligence.get("style_decision"),
        "timing_quality": intelligence.get("caption_timing_quality"),
        "safe_zone": intelligence.get("caption_safe_zone"),
        "hook_treatment": intelligence.get("hook_caption_treatment"),
        "emphasis": intelligence.get("caption_emphasis"),
        "speaker_captioning": intelligence.get("speaker_captioning"),
        "readability_validation": metadata.get("caption_readability_validation")
        or intelligence.get("caption_readability_validation"),
        "render_validation": metadata.get("caption_render_validation")
        or intelligence.get("validation"),
    }


def _project_clip_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    summary = _metadata_summary(metadata)
    render_validation = summary.get("render_validation")
    render_validation = render_validation if isinstance(render_validation, dict) else {}
    readability = summary.get("readability_validation")
    readability = readability if isinstance(readability, dict) else {}
    failure_reasons: list[str] = []
    if not summary.get("caption_intelligence"):
        failure_reasons.append("caption intelligence is missing")
    if render_validation.get("passed") is not True:
        failure_reasons.append("caption render validation did not pass")
    if render_validation.get("render_manifest_confirmed") is not True:
        failure_reasons.append("render manifest did not confirm captions")
    if readability.get("passed") is not True:
        failure_reasons.append("caption readability validation did not pass")
    summary["failure_reasons"] = failure_reasons
    summary["pass_fail"] = not failure_reasons
    return summary


def _report(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {
        "mode": "unknown",
        "caption_intelligence": None,
        "style_decision": None,
        "timing_quality": None,
        "safe_zone": None,
        "hook_treatment": None,
        "emphasis": None,
        "speaker_captioning": None,
        "ass_validation": None,
        "readability_validation": None,
        "render_validation": None,
        "clips": [],
        "failed_clip_count": 0,
        "failed_clips": [],
        "ffprobe": None,
        "warnings": [],
        "pass_fail": False,
    }
    if args.ass_file:
        report["mode"] = "ass_file"
        try:
            content = args.ass_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            report["warnings"].append(str(exc))
        else:
            report["ass_validation"] = C.validate_ass(content)
            report["pass_fail"] = report["ass_validation"].get("ass_valid") is True
    elif args.simulate:
        report["mode"] = "simulate"
        intelligence, ass_validation = _simulation(args.niche, args.hook_category)
        report.update(_metadata_summary({"caption_intelligence_v2": intelligence}))
        report["ass_validation"] = ass_validation
        report["pass_fail"] = bool(
            ass_validation.get("ass_valid")
            and report["readability_validation"]
            and report["readability_validation"].get("passed") is True
        )
    elif args.rendered_file:
        report["mode"] = "rendered_file"
        report["ffprobe"] = _probe(args.rendered_file)
        if args.manifest:
            report.update(_metadata_summary(_first_render_metadata(_load(args.manifest))))
        else:
            report["warnings"].append(
                "A render manifest is required to prove captions were applied."
            )
        render_validation = report.get("render_validation")
        readability = report.get("readability_validation")
        report["pass_fail"] = bool(
            report["ffprobe"].get("available")
            and isinstance(render_validation, dict)
            and render_validation.get("passed") is True
            and render_validation.get("render_manifest_confirmed") is True
            and isinstance(readability, dict)
            and readability.get("passed") is True
        )
    elif args.project_id:
        report["mode"] = "project"
        metadata_records, warnings = _project_caption_data(args.project_id)
        clips = [_project_clip_summary(metadata) for metadata in metadata_records]
        if clips:
            report.update(
                {
                    key: value
                    for key, value in clips[0].items()
                    if key not in {"pass_fail", "failure_reasons"}
                }
            )
        failed_clips = [
            str(clip.get("clip_id") or "unknown")
            for clip in clips
            if clip.get("pass_fail") is not True
        ]
        report["clips"] = clips
        report["failed_clip_count"] = len(failed_clips)
        report["failed_clips"] = failed_clips
        report["warnings"].extend(warnings)
        report["pass_fail"] = bool(clips) and not failed_clips
    intelligence = report.get("caption_intelligence")
    intelligence = intelligence if isinstance(intelligence, dict) else {}
    intelligence_validation = intelligence.get("validation")
    intelligence_validation = (
        intelligence_validation if isinstance(intelligence_validation, dict) else {}
    )
    ass_validation = report.get("ass_validation")
    ass_validation = ass_validation if isinstance(ass_validation, dict) else {}
    render_validation = report.get("render_validation")
    render_validation = render_validation if isinstance(render_validation, dict) else {}
    style_decision = report.get("style_decision")
    style_decision = style_decision if isinstance(style_decision, dict) else {}
    timing_quality = report.get("timing_quality")
    timing_quality = timing_quality if isinstance(timing_quality, dict) else {}
    readability = report.get("readability_validation")
    readability = readability if isinstance(readability, dict) else {}
    flattened_warnings = list(report.get("warnings") or [])
    flattened_warnings.extend(ass_validation.get("warnings") or [])
    flattened_warnings.extend(render_validation.get("warnings") or [])
    flattened_warnings.extend(readability.get("warnings") or [])
    flattened_warnings.extend(intelligence.get("warnings") or [])
    for clip in report.get("clips") or []:
        if not isinstance(clip, dict):
            continue
        clip_readability = clip.get("readability_validation")
        clip_render = clip.get("render_validation")
        clip_intelligence = clip.get("caption_intelligence")
        if isinstance(clip_readability, dict):
            flattened_warnings.extend(clip_readability.get("warnings") or [])
        if isinstance(clip_render, dict):
            flattened_warnings.extend(clip_render.get("warnings") or [])
        if isinstance(clip_intelligence, dict):
            flattened_warnings.extend(clip_intelligence.get("warnings") or [])
    report.update(
        {
            "captions_planned": render_validation.get("captions_planned")
            if render_validation
            else intelligence_validation.get("captions_planned")
            if intelligence_validation
            else bool(ass_validation.get("events_count")),
            "ass_valid": ass_validation.get("ass_valid")
            if ass_validation
            else render_validation.get("ass_valid")
            if render_validation.get("ass_valid") is not None
            else intelligence_validation.get("ass_valid"),
            "events_count": ass_validation.get("events_count")
            or render_validation.get("ass_event_count")
            or intelligence_validation.get("event_count"),
            "style": style_decision.get("caption_style")
            or ("ass_embedded" if ass_validation else None),
            "timing_source": timing_quality.get("source")
            or ("unavailable" if ass_validation else None),
            "warnings": list(dict.fromkeys(str(item) for item in flattened_warnings if item)),
        }
    )
    return {"caption_validation_report": report}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--ass-file", type=Path)
    modes.add_argument("--simulate", action="store_true")
    modes.add_argument("--rendered-file", type=Path)
    modes.add_argument("--project-id")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--niche", default="education_tutorial")
    parser.add_argument("--hook-category", default="curiosity_gap")
    return parser.parse_args()


def main() -> int:
    report = _report(_parse_args())
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["caption_validation_report"]["pass_fail"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

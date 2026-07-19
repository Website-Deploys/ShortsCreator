"""Deterministic FFmpeg-derived scene, shot, and visual pacing helpers."""

from __future__ import annotations

import re
from typing import Any

from olympus.analysis.signals import (
    AnalysisSignalState,
    AnalysisSignalStatusV1,
    AnalysisTimelineEventV1,
    AnalysisTimelineSignalV1,
)

_FRAME_RE = re.compile(r"pts_time:(?P<time>-?\d+(?:\.\d+)?)")
_SCENE_RE = re.compile(r"lavfi\.scene_score=(?P<score>\d+(?:\.\d+)?)")
_BRIGHTNESS_RE = re.compile(r"lavfi\.signalstats\.YAVG=(?P<value>\d+(?:\.\d+)?)")


def parse_scene_metadata(output: str) -> list[dict[str, float]]:
    events: list[dict[str, float]] = []
    pending_time: float | None = None
    for line in output.splitlines():
        frame = _FRAME_RE.search(line)
        if frame:
            pending_time = max(0.0, float(frame.group("time")))
        scene = _SCENE_RE.search(line)
        if scene and pending_time is not None:
            events.append(
                {"time": round(pending_time, 3), "score": round(float(scene.group("score")), 3)}
            )
            pending_time = None
    return _deduplicate_boundaries(events)


def parse_brightness_metadata(output: str) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    pending_time: float | None = None
    for line in output.splitlines():
        frame = _FRAME_RE.search(line)
        if frame:
            pending_time = max(0.0, float(frame.group("time")))
        brightness = _BRIGHTNESS_RE.search(line)
        if brightness and pending_time is not None:
            samples.append(
                {
                    "time": round(pending_time, 3),
                    "brightness": round(float(brightness.group("value")) / 255.0, 3),
                }
            )
            pending_time = None
    return samples


def build_scene_signal(
    boundaries: list[dict[str, float]],
    *,
    duration_seconds: float,
    brightness_samples: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    duration = max(0.0, float(duration_seconds))
    cuts = [item for item in boundaries if 0.05 < item["time"] < duration - 0.05]
    starts = [0.0, *[item["time"] for item in cuts]]
    ends = [*[item["time"] for item in cuts], duration]
    scores = [0.7, *[item["score"] for item in cuts]]
    scenes: list[dict[str, Any]] = [
        {
            "id": f"scene_{index + 1}",
            "start": round(start, 3),
            "end": round(end, 3),
            "confidence": round(max(0.5, min(0.98, scores[index])), 3),
            "boundary_score": round(scores[index], 3),
        }
        for index, (start, end) in enumerate(zip(starts, ends, strict=True))
        if end > start
    ]
    scene_events = [
        AnalysisTimelineEventV1(
            start_seconds=_float(scene["start"]),
            end_seconds=_float(scene["end"]),
            label=str(scene["id"]),
            score=_float(scene["confidence"]),
            metadata={"boundary_score": scene["boundary_score"]},
        )
        for scene in scenes
    ]
    scene_status = AnalysisSignalStatusV1(
        signal_name="scene_detection",
        available=bool(scenes),
        status=AnalysisSignalState.AVAILABLE if scenes else AnalysisSignalState.PARTIAL,
        confidence=0.82 if scenes else 0.0,
        provider="ffmpeg_scene_filter",
        fallback_used=False,
        reason=None if scenes else "insufficient_input",
        warnings=[],
        metadata={"scene_count": len(scenes), "semantic_model_used": False},
    )
    visual_regions = build_visual_region_signal(
        scenes,
        brightness_samples=brightness_samples or [],
    )
    return {
        "scenes": scenes,
        "boundaries": cuts,
        "scene_detection": {
            "status": scene_status.to_dict(),
            "timeline": AnalysisTimelineSignalV1(
                signal_name="scene_detection",
                events=scene_events,
                confidence=scene_status.confidence,
            ).to_dict(),
        },
        "visual_regions": visual_regions,
    }


def build_shot_signal(scene_data: dict[str, Any], *, duration_seconds: float) -> dict[str, Any]:
    scenes = [item for item in scene_data.get("scenes") or [] if isinstance(item, dict)]
    shots: list[dict[str, Any]] = [
        {
            "id": f"shot_{index + 1}",
            "start": float(scene.get("start") or 0.0),
            "end": float(scene.get("end") or duration_seconds),
            "confidence": float(scene.get("confidence") or 0.7),
            "source_scene_id": scene.get("id"),
        }
        for index, scene in enumerate(scenes)
    ]
    events = [
        AnalysisTimelineEventV1(
            start_seconds=_float(shot["start"]),
            end_seconds=_float(shot["end"]),
            label=str(shot["id"]),
            score=_float(shot["confidence"]),
            metadata={"source_scene_id": shot["source_scene_id"]},
        )
        for shot in shots
    ]
    status = AnalysisSignalStatusV1(
        signal_name="shot_detection",
        available=bool(shots),
        status=AnalysisSignalState.AVAILABLE if shots else AnalysisSignalState.PARTIAL,
        confidence=0.78 if shots else 0.0,
        provider="derived_from_ffmpeg_scene_boundaries",
        fallback_used=False,
        reason=None if shots else "insufficient_input",
        warnings=[],
        metadata={"shot_count": len(shots), "semantic_model_used": False},
    )
    pacing = build_visual_pacing_signal(shots, duration_seconds=duration_seconds)
    return {
        "shots": shots,
        "shot_detection": {
            "status": status.to_dict(),
            "timeline": AnalysisTimelineSignalV1(
                signal_name="shot_detection",
                events=events,
                confidence=status.confidence,
            ).to_dict(),
        },
        "visual_pacing": pacing,
    }


def build_visual_pacing_signal(
    shots: list[dict[str, Any]], *, duration_seconds: float
) -> dict[str, Any]:
    duration = max(0.001, float(duration_seconds))
    cuts_per_minute = max(0.0, (len(shots) - 1) * 60.0 / duration)
    score = max(0.0, min(1.0, cuts_per_minute / 30.0))
    label = "fast" if score >= 0.67 else "moderate" if score >= 0.33 else "slow"
    events = [
        AnalysisTimelineEventV1(
            start_seconds=float(shot.get("start") or 0.0),
            end_seconds=float(shot.get("end") or duration),
            label=label,
            score=score,
            metadata={"shot_id": shot.get("id")},
        )
        for shot in shots
    ]
    status = AnalysisSignalStatusV1(
        signal_name="visual_pacing",
        available=bool(shots),
        status=AnalysisSignalState.PARTIAL if shots else AnalysisSignalState.UNAVAILABLE,
        confidence=0.68 if shots else 0.0,
        provider="shot_frequency_heuristic",
        fallback_used=False,
        reason=None if shots else "insufficient_input",
        warnings=["Visual pacing is derived from cut frequency, not audience retention."],
        metadata={"cuts_per_minute": round(cuts_per_minute, 3), "overall_label": label},
    )
    return {
        "status": status.to_dict(),
        "timeline": AnalysisTimelineSignalV1(
            signal_name="visual_pacing",
            events=events,
            confidence=status.confidence,
            warnings=list(status.warnings),
        ).to_dict(),
        "overall_score": round(score, 3),
        "overall_label": label,
        "cuts_per_minute": round(cuts_per_minute, 3),
    }


def build_visual_region_signal(
    scenes: list[dict[str, Any]],
    *,
    brightness_samples: list[dict[str, float]],
) -> dict[str, Any]:
    events: list[AnalysisTimelineEventV1] = []
    for scene in scenes:
        start = float(scene.get("start") or 0.0)
        end = float(scene.get("end") or start)
        samples = [item for item in brightness_samples if start <= item["time"] < end]
        mean_brightness = (
            sum(item["brightness"] for item in samples) / len(samples) if samples else None
        )
        events.append(
            AnalysisTimelineEventV1(
                start_seconds=start,
                end_seconds=end,
                label="full_frame_visual_activity",
                score=float(scene.get("confidence") or 0.5),
                metadata={
                    "region": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                    "mean_brightness": round(mean_brightness, 3)
                    if mean_brightness is not None
                    else None,
                    "object_classes": [],
                },
            )
        )
    warnings = [
        "Visual regions contain full-frame activity/brightness only; no object classes "
        "are inferred."
    ]
    if not brightness_samples:
        warnings.append("Brightness sampling was unavailable; scene activity remains usable.")
    status = AnalysisSignalStatusV1(
        signal_name="visual_regions",
        available=bool(events),
        status=AnalysisSignalState.PARTIAL if events else AnalysisSignalState.UNAVAILABLE,
        confidence=0.62 if events and brightness_samples else 0.5 if events else 0.0,
        provider="ffmpeg_scene_and_signalstats",
        fallback_used=False,
        reason=None if events else "insufficient_input",
        warnings=warnings,
        metadata={"semantic_object_detection": False, "sample_count": len(brightness_samples)},
    )
    return {
        "status": status.to_dict(),
        "timeline": AnalysisTimelineSignalV1(
            signal_name="visual_regions",
            events=events,
            confidence=status.confidence,
            warnings=warnings,
        ).to_dict(),
    }


def _deduplicate_boundaries(events: list[dict[str, float]]) -> list[dict[str, float]]:
    output: list[dict[str, float]] = []
    for event in sorted(events, key=lambda item: item["time"]):
        if output and event["time"] - output[-1]["time"] < 0.12:
            if event["score"] > output[-1]["score"]:
                output[-1] = event
            continue
        output.append(event)
    return output


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

"""The sixteen Editing Engine stages.

Each stage is an isolated, replaceable module behind the :class:`EditingAnalyzer`
contract. None imports another; they communicate only through the structured
:class:`EditingStageContext`. Together they transform the Clip Planner's approved
blueprints into real, professional, non-destructive edit timelines (one per
clip), then validate them.

Honesty rules (enforced by construction):
- When the inputs needed to build a timeline are missing (no approved clips / no
  transcript), a stage returns ``UNAVAILABLE`` with a detailed reason.
- A single decision that cannot be determined (e.g. pans without subject
  tracking, audio beats without an audio model) is recorded as ``UNKNOWN`` -
  never guessed.
- Every event is clip-relative, timestamped, and carries a reason, a confidence
  (``None`` = UNKNOWN), and supporting evidence. Nothing is rendered or applied.
"""

from __future__ import annotations

from typing import Any

from olympus.domain.contracts.editing import (
    EditingAnalyzer,
    EditingOutcome,
    EditingProgressReporter,
    EditingStageContext,
)
from olympus.editing import boundary_repair as BR  # noqa: N812 (module alias is intentional)
from olympus.editing import captions as CAP  # noqa: N812 (module alias is intentional)
from olympus.editing import motion as MOT  # noqa: N812 (module alias is intentional)
from olympus.editing import timeline as T  # noqa: N812 (module alias is intentional)
from olympus.editing.multi_speaker import build_multi_speaker_layout
from olympus.integration import clip_intelligence as CI  # noqa: N812 (module alias is intentional)
from olympus.music import plan_music_intelligence
from olympus.personalization import apply as P  # noqa: N812 (module alias is intentional)
from olympus.platform.config import get_settings
from olympus.trends import build_editing_trend_guidance

_NO_CLIPS = (
    "There are no approved clip plans to build a timeline for. The Clip Planner "
    "produced zero clips (or has not completed), so there is nothing to edit. No "
    "timeline is fabricated without an approved clip."
)
_NO_TRANSCRIPT = (
    "Requires a transcript from the Cognitive Engine, which is not available for "
    "this video. Speech-derived edits cannot be determined without it."
)
_LONG_PAUSE = 0.6
_DEAD_AIR = 1.5
_SILENCE_GAP = 0.35


# --------------------------------------------------------------------------- #
# Shared, pure helpers
# --------------------------------------------------------------------------- #
def _clips(ctx: EditingStageContext) -> list[dict[str, Any]] | None:
    """The base clips from timeline initialization, or ``None`` if unavailable."""

    init = ctx.editing_data("timeline_initialization")
    if init is None:
        return None
    return T.as_list(init.get("clips"))


def _plans_by_id(ctx: EditingStageContext) -> dict[str, dict[str, Any]]:
    return {T.as_str(p.get("id")): p for p in ctx.approved_plans()}


def _window(clip: dict[str, Any]) -> tuple[float, float, float]:
    start = T.as_float(clip.get("source_start"))
    end = T.as_float(clip.get("source_end"))
    return start, end, T.as_float(clip.get("duration"), end - start)


def _blueprint(plans: dict[str, dict[str, Any]], clip_id: str) -> dict[str, Any]:
    return T.as_dict(T.as_dict(plans.get(clip_id)).get("blueprint"))


def _per_clip(
    ctx: EditingStageContext,
) -> tuple[list[dict[str, Any]] | None, dict[str, dict[str, Any]]]:
    return _clips(ctx), _plans_by_id(ctx)


def _face_tracking_plan(
    *,
    face_data: dict[str, Any] | None,
    speaker_data: dict[str, Any] | None,
    clip: dict[str, Any],
    source_width: float,
    source_height: float,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Build the canonical anonymous Multi-Speaker Layout V2 contract."""

    clip_start, _, duration = _window(clip)
    detections = _normalize_face_detections(
        face_data or {},
        clip_start=clip_start,
        clip_duration=duration,
        source_width=source_width,
        source_height=source_height,
    )
    return build_multi_speaker_layout(
        detections=detections,
        speaker_timeline=T.as_list((speaker_data or {}).get("timeline")),
        clip_id=T.as_str(clip.get("clip_id")),
        project_id=project_id,
        clip_start=clip_start,
        duration=duration,
        source_width=source_width,
        source_height=source_height,
        fps=T.as_float(clip.get("fps"), 30.0),
    )


def _legacy_face_tracking_plan(
    *,
    face_data: dict[str, Any] | None,
    speaker_data: dict[str, Any] | None,
    clip: dict[str, Any],
    source_width: float,
    source_height: float,
) -> dict[str, Any]:
    """Convert cognitive face detections into a renderable crop-keyframe plan."""

    fallback = {
        "mode": "center_fallback",
        "applied_to_render": False,
        "confidence": 0.0,
        "fallback_reason": "face_detection_unavailable",
        "tracked_faces": [],
        "crop_keyframes": [],
        "layout_regions": [],
        "smoothing": {
            "method": "exponential_moving_average",
            "alpha": 0.35,
            "max_crop_movement_per_second": 0.22,
            "interpolate_gaps_seconds": 0.75,
        },
        "warnings": ["No completed face_detection stage data was available."],
    }
    if not face_data:
        return fallback

    clip_start, _, duration = _window(clip)
    detections = _normalize_face_detections(
        face_data,
        clip_start=clip_start,
        clip_duration=duration,
        source_width=source_width,
        source_height=source_height,
    )
    usable = [d for d in detections if T.as_float(d.get("confidence")) >= 0.45]
    if len(usable) < 2:
        plan = dict(fallback)
        plan["fallback_reason"] = "sparse_or_low_confidence_faces"
        plan["warnings"] = [f"Only {len(usable)} usable face detection(s) in this clip window."]
        return plan

    tracks = _face_tracks(usable, duration)
    stable = [track for track in tracks if track["score"] >= 0.2]
    if not stable:
        plan = dict(fallback)
        plan["fallback_reason"] = "unstable_face_tracks"
        plan["warnings"] = ["Face tracks were too unstable for safe reframing."]
        return plan

    stable.sort(key=lambda item: item["score"], reverse=True)
    speaker_timeline = T.as_list((speaker_data or {}).get("timeline")) if speaker_data else []
    speaker_available = bool(speaker_timeline)
    warnings: list[str] = []
    if len(stable) == 1:
        mode = "single_face_tracking"
        selected = stable[0]["detections"]
        tracked = stable[:1]
    elif len(stable) == 2:
        mode = "active_speaker_focus"
        selected = stable[0]["detections"]
        tracked = stable[:2]
        warnings.append(
            "Two stable faces found; renderer will use active/stable speaker focus "
            "instead of split-screen unless a compositor supports stacked layouts."
        )
    else:
        mode = "multi_face_safe_frame"
        selected = _multi_face_safe_detections(stable[:4])
        tracked = stable[:4]
        warnings.append("Three or more faces found; using multi-face safe-frame centers.")

    keyframes = _crop_keyframes(selected, duration)
    if len(keyframes) < 2:
        plan = dict(fallback)
        plan["fallback_reason"] = "insufficient_crop_keyframes"
        plan["warnings"] = ["Face detections could not produce at least two crop keyframes."]
        return plan

    confidence = T.round3(
        min(
            0.95,
            sum(T.as_float(track.get("score")) for track in tracked) / max(1, len(tracked)),
        )
    )
    return {
        "mode": mode,
        "applied_to_render": False,
        "confidence": confidence,
        "fallback_reason": None,
        "tracked_faces": [
            {
                "face_id": track["face_id"],
                "detections": track["count"],
                "coverage": track["coverage"],
                "avg_confidence": track["avg_confidence"],
                "score": track["score"],
            }
            for track in tracked
        ],
        "crop_keyframes": keyframes,
        "layout_regions": _layout_regions_for_faces(tracked, mode),
        "smoothing": {
            "method": "exponential_moving_average",
            "alpha": 0.35,
            "max_crop_movement_per_second": 0.22,
            "interpolate_gaps_seconds": 0.75,
            "ignore_below_confidence": 0.45,
        },
        "warnings": warnings
        + ([] if speaker_available else ["No active-speaker mapping to face ids is available."]),
    }


def _normalize_face_detections(
    face_data: dict[str, Any],
    *,
    clip_start: float,
    clip_duration: float,
    source_width: float,
    source_height: float,
) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []

    def visit(node: Any, inherited_time: float | None = None, index: int = 0) -> None:
        if isinstance(node, list):
            for item_index, item in enumerate(node):
                visit(item, inherited_time, item_index)
            return
        if not isinstance(node, dict):
            return

        time_value = _face_time(node, inherited_time)
        nested = node.get("faces") or node.get("detections") or node.get("boxes")
        if isinstance(nested, list):
            for item_index, item in enumerate(nested):
                visit(item, time_value, item_index)
            return
        track_detections = node.get("track") or node.get("track_detections")
        if isinstance(track_detections, list):
            for item in track_detections:
                if isinstance(item, dict) and "face_id" not in item and node.get("face_id"):
                    item = {**item, "face_id": node.get("face_id")}
                visit(item, time_value, index)
            return

        box = _face_box(node)
        if box is None or time_value is None:
            return
        rel = _face_clip_time(time_value, clip_start, clip_duration)
        if rel is None:
            return
        normalized = _normalize_box(
            box,
            source_width=source_width,
            source_height=source_height,
        )
        if normalized is None:
            return
        detections.append(
            {
                "time": T.round3(rel),
                "x_center": normalized["x_center"],
                "y_center": normalized["y_center"],
                "width": normalized["width"],
                "height": normalized["height"],
                "confidence": T.round3(T.as_float(node.get("confidence"), 0.5)),
                "face_id": T.as_str(
                    node.get("face_id") or node.get("track_id") or node.get("id")
                )
                or None,
            }
        )

    for key in ("frames", "tracks", "faces", "detections", "results"):
        value = face_data.get(key)
        if isinstance(value, list):
            visit(value)
    if not detections:
        visit(face_data)
    detections.sort(key=lambda item: (T.as_float(item.get("time")), T.as_str(item.get("face_id"))))
    return detections


def _face_time(node: dict[str, Any], inherited_time: float | None) -> float | None:
    for key in ("time", "timestamp", "time_s", "seconds", "at", "start", "frame_time"):
        value = node.get(key)
        if isinstance(value, int | float):
            return float(value)
    return inherited_time


def _face_clip_time(timestamp: float, clip_start: float, clip_duration: float) -> float | None:
    rel = T.to_clip_relative(timestamp, clip_start, clip_duration)
    if rel is not None:
        return rel
    if -0.05 <= timestamp <= clip_duration + 0.05:
        return T.round3(T.clamp(timestamp, 0.0, clip_duration))
    return None


def _face_box(node: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("bbox", "box", "bounding_box", "rect", "bounds"):
        value = node.get(key)
        if isinstance(value, dict):
            return value
    if any(key in node for key in ("x", "y", "width", "height", "w", "h", "x1", "x2")):
        return node
    return None


def _normalize_box(
    box: dict[str, Any], *, source_width: float, source_height: float
) -> dict[str, float] | None:
    if all(key in box for key in ("x_center", "y_center", "width", "height")):
        x_center = T.as_float(box.get("x_center"))
        y_center = T.as_float(box.get("y_center"))
        width = T.as_float(box.get("width"))
        height = T.as_float(box.get("height"))
    elif all(key in box for key in ("cx", "cy", "w", "h")):
        x_center = T.as_float(box.get("cx"))
        y_center = T.as_float(box.get("cy"))
        width = T.as_float(box.get("w"))
        height = T.as_float(box.get("h"))
    elif all(key in box for key in ("x1", "y1", "x2", "y2")):
        x1 = T.as_float(box.get("x1"))
        y1 = T.as_float(box.get("y1"))
        x2 = T.as_float(box.get("x2"))
        y2 = T.as_float(box.get("y2"))
        width = x2 - x1
        height = y2 - y1
        x_center = x1 + width / 2
        y_center = y1 + height / 2
    else:
        x = T.as_float(box.get("x") if "x" in box else box.get("left"))
        y = T.as_float(box.get("y") if "y" in box else box.get("top"))
        width = T.as_float(box.get("width") if "width" in box else box.get("w"))
        height = T.as_float(box.get("height") if "height" in box else box.get("h"))
        x_center = x + width / 2
        y_center = y + height / 2

    if width <= 0 or height <= 0:
        return None
    if max(x_center, width) > 1.5 and source_width > 0:
        x_center /= source_width
        width /= source_width
    if max(y_center, height) > 1.5 and source_height > 0:
        y_center /= source_height
        height /= source_height
    if not (0.0 <= x_center <= 1.0 and 0.0 <= y_center <= 1.0):
        return None
    return {
        "x_center": T.round3(T.clamp(x_center, 0.0, 1.0)),
        "y_center": T.round3(T.clamp(y_center, 0.0, 1.0)),
        "width": T.round3(T.clamp(width, 0.01, 1.0)),
        "height": T.round3(T.clamp(height, 0.01, 1.0)),
    }


def _face_tracks(detections: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for detection in detections:
        grouped.setdefault(T.as_str(detection.get("face_id")) or "face_0", []).append(detection)

    tracks: list[dict[str, Any]] = []
    for face_id, items in grouped.items():
        items.sort(key=lambda item: T.as_float(item.get("time")))
        confidences = [T.as_float(item.get("confidence")) for item in items]
        heights = [T.as_float(item.get("height")) for item in items]
        span = max(0.0, T.as_float(items[-1].get("time")) - T.as_float(items[0].get("time")))
        coverage = T.round3(min(1.0, span / max(0.1, duration)))
        avg_confidence = T.round3(sum(confidences) / max(1, len(confidences)))
        avg_height = sum(heights) / max(1, len(heights))
        score = T.round3(min(0.95, avg_confidence * 0.55 + coverage * 0.3 + avg_height * 0.8))
        tracks.append(
            {
                "face_id": face_id,
                "detections": items,
                "count": len(items),
                "coverage": coverage,
                "avg_confidence": avg_confidence,
                "score": score,
            }
        )
    return tracks


def _multi_face_safe_detections(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_time: dict[float, list[dict[str, Any]]] = {}
    for track in tracks:
        for detection in T.as_list(track.get("detections")):
            by_time.setdefault(T.as_float(detection.get("time")), []).append(detection)
    safe: list[dict[str, Any]] = []
    for time, detections in sorted(by_time.items()):
        xs = [T.as_float(d.get("x_center")) for d in detections]
        ys = [T.as_float(d.get("y_center")) for d in detections]
        widths = [T.as_float(d.get("width")) for d in detections]
        heights = [T.as_float(d.get("height")) for d in detections]
        left = min(x - w / 2 for x, w in zip(xs, widths, strict=False))
        right = max(x + w / 2 for x, w in zip(xs, widths, strict=False))
        top = min(y - h / 2 for y, h in zip(ys, heights, strict=False))
        bottom = max(y + h / 2 for y, h in zip(ys, heights, strict=False))
        safe.append(
            {
                "time": T.round3(time),
                "x_center": T.round3(T.clamp((left + right) / 2, 0.0, 1.0)),
                "y_center": T.round3(T.clamp((top + bottom) / 2, 0.0, 1.0)),
                "width": T.round3(T.clamp(right - left, 0.01, 1.0)),
                "height": T.round3(T.clamp(bottom - top, 0.01, 1.0)),
                "confidence": T.round3(
                    sum(T.as_float(d.get("confidence")) for d in detections)
                    / max(1, len(detections))
                ),
                "face_id": "multi_face_safe_frame",
            }
        )
    return safe


def _crop_keyframes(detections: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    if not detections:
        return []
    detections = sorted(detections, key=lambda item: T.as_float(item.get("time")))
    smoothed: list[dict[str, Any]] = []
    alpha = 0.35
    sx = T.as_float(detections[0].get("x_center"), 0.5)
    sy = T.as_float(detections[0].get("y_center"), 0.46)
    last_time = T.as_float(detections[0].get("time"))
    for item in detections:
        current_time = T.as_float(item.get("time"))
        gap = max(0.001, current_time - last_time)
        max_step = 0.22 * gap
        target_x = T.as_float(item.get("x_center"), sx)
        target_y = T.as_float(item.get("y_center"), sy)
        sx += T.clamp((target_x - sx) * alpha, -max_step, max_step)
        sy += T.clamp((target_y - sy) * alpha, -max_step, max_step)
        last_time = current_time
        face_height = T.as_float(item.get("height"), 0.22)
        zoom = T.clamp(0.95 + max(0.0, 0.25 - face_height) * 0.7, 1.0, 1.14)
        smoothed.append(
            {
                "time": T.round3(current_time),
                "x_center": T.round3(T.clamp(sx, 0.08, 0.92)),
                "y_center": T.round3(T.clamp(sy - 0.04, 0.12, 0.82)),
                "width": T.round3(T.as_float(item.get("width"), 0.2)),
                "height": T.round3(face_height),
                "zoom": T.round3(zoom),
                "confidence": T.round3(T.as_float(item.get("confidence"), 0.5)),
                "source_face_id": item.get("face_id"),
            }
        )
    if smoothed[0]["time"] > 0.0:
        first = dict(smoothed[0])
        first["time"] = 0.0
        smoothed.insert(0, first)
    if smoothed[-1]["time"] < duration:
        last = dict(smoothed[-1])
        last["time"] = T.round3(duration)
        smoothed.append(last)
    return smoothed[:24]


def _layout_regions_for_faces(tracks: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "active_speaker_focus":
        return [
            {"name": "primary_focus", "face_id": tracks[0]["face_id"], "region": "full_frame"},
            {"name": "secondary_safe", "face_id": tracks[1]["face_id"], "region": "safe_margin"},
        ][: len(tracks)]
    if mode == "multi_face_safe_frame":
        return [{"name": "safe_frame", "face_ids": [track["face_id"] for track in tracks]}]
    return [{"name": "tracked_face", "face_id": tracks[0]["face_id"], "region": "full_frame"}]


# --------------------------------------------------------------------------- #
# 1. Timeline Initialization - one base timeline per approved clip.
# --------------------------------------------------------------------------- #
class TimelineInitializationAnalyzer(EditingAnalyzer):
    name = "timeline_initialization"
    version = "4"

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        plans = ctx.approved_plans()
        if not plans:
            return EditingOutcome.unavailable(_NO_CLIPS)
        fps = ctx.fps()
        transcript_segments = ctx.transcript_segments() or []
        source_duration = ctx.video_duration()
        clips: list[dict[str, Any]] = []
        for plan in plans:
            boundary_quality = T.as_dict(plan.get("boundary_quality"))
            requested_start = T.as_float(
                boundary_quality.get("recommended_start_seconds"),
                T.as_float(plan.get("start")),
            )
            requested_end = T.as_float(
                boundary_quality.get("recommended_end_seconds"),
                T.as_float(plan.get("end")),
            )
            clip_id = T.as_str(plan.get("id"))
            blueprint = T.as_dict(plan.get("blueprint"))
            source_window = BR.repair_clip_source_window(
                project_id=ctx.project.id,
                clip_id=clip_id,
                requested_start_seconds=requested_start,
                requested_end_seconds=requested_end,
                transcript_segments=transcript_segments,
                source_duration_seconds=source_duration,
                planning_metadata=plan,
                story_metadata=blueprint,
            )
            boundary_validation = BR.validate_clip_source_window(
                source_window,
                transcript_segments,
            )
            source_window_data = source_window.to_dict()
            start = source_window.repaired_start_seconds
            end = source_window.repaired_end_seconds
            duration = source_window.duration_seconds
            confidence = T.as_float(plan.get("confidence"))
            clips.append(
                {
                    "clip_id": clip_id,
                    "plan_id": clip_id,
                    "rank": plan.get("rank"),
                    "source_video": T.as_dict(plan.get("source_video")),
                    "source_start": T.round3(start),
                    "source_end": T.round3(end),
                    "duration": T.round3(duration),
                    "source_window_v1": source_window_data,
                    "boundary_quality": boundary_quality,
                    "boundary_quality_decision": T.as_dict(
                        plan.get("boundary_quality_decision")
                        or boundary_quality.get("decision")
                    ),
                    "boundary_validation": boundary_validation,
                    "boundary_warnings": boundary_validation["warnings"],
                    "fps": fps,
                    "start_frame": round(start * fps),
                    "end_frame": round(end * fps),
                    "quality_score": T.as_float(plan.get("quality_score")),
                    "confidence": confidence,
                    "base_video_event": T.event(
                        "source_clip",
                        0.0,
                        duration,
                        reason="base clip spanning the approved plan window",
                        confidence=confidence,
                        evidence=[{"type": "plan", "detail": T.as_str(plan.get("explanation"))}],
                        source_start=T.round3(start),
                        source_end=T.round3(end),
                    ),
                    "base_audio_event": T.event(
                        "source_audio",
                        0.0,
                        duration,
                        reason="clip audio, co-extensive with the base video clip",
                        confidence=confidence,
                        source_start=T.round3(start),
                        source_end=T.round3(end),
                    ),
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {
                "clip_count": len(clips),
                "clips": clips,
                "fps": fps,
                "note": "One canonical repaired source window per approved clip. All later "
                "events are clip-relative and share its source-time origin.",
            }
        )


# --------------------------------------------------------------------------- #
# 2. Speech Cleanup - IDENTIFY fillers / pauses / dead air (never remove).
# --------------------------------------------------------------------------- #
class SpeechCleanupAnalyzer(EditingAnalyzer):
    name = "speech_cleanup"
    version = "2"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        segments = ctx.transcript_segments()
        if not segments:
            return EditingOutcome.unavailable(_NO_TRANSCRIPT)

        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, ce, duration = _window(clip)
            segs = T.clip_segments(segments, cs, ce)
            items: list[dict[str, Any]] = []
            for seg in segs:
                for word in T.find_fillers(seg["text"]):
                    items.append(
                        T.marker(
                            "filler_word",
                            seg["start"],
                            reason=f"filler/hedge '{word}' identified for optional tightening",
                            confidence=0.5,
                            evidence=[{"type": "transcript", "detail": seg["text"][:80]}],
                            word=word,
                        )
                    )
                for word in T.find_repeated_words(seg["text"]):
                    items.append(
                        T.marker(
                            "repeated_word",
                            seg["start"],
                            reason=f"immediate repetition of '{word}'",
                            confidence=0.5,
                            evidence=[{"type": "transcript", "detail": seg["text"][:80]}],
                            word=word,
                        )
                    )
            for gap in T.gaps_between(segs, duration, min_gap=_LONG_PAUSE):
                kind = "dead_air" if gap["end"] - gap["start"] >= _DEAD_AIR else "long_pause"
                items.append(
                    T.event(
                        kind,
                        gap["start"],
                        gap["end"],
                        reason="silence between speech, inferred from transcript timing",
                        confidence=0.5,
                        evidence=[{"type": "transcript_gap", "detail": "no speech in interval"}],
                    )
                )
            out.append(
                {
                    "clip_id": clip["clip_id"],
                    "items": items,
                    "breathing": {
                        "status": "unknown",
                        "reason": "breath detection requires audio-waveform analysis, "
                        "which is unavailable; not guessed.",
                    },
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Identification only - nothing is removed. Fillers, repeats, "
                "long pauses and dead air are flagged for an editor/future engine.",
            }
        )


# --------------------------------------------------------------------------- #
# 3. Jump Cut Detection - natural cut points at sentence boundaries.
# --------------------------------------------------------------------------- #
class JumpCutDetectionAnalyzer(EditingAnalyzer):
    name = "jump_cut_detection"
    version = "2"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        segments = ctx.transcript_segments()
        if not segments:
            return EditingOutcome.unavailable(_NO_TRANSCRIPT)

        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, ce, _ = _window(clip)
            segs = T.clip_segments(segments, cs, ce)
            cuts: list[dict[str, Any]] = []
            for i, seg in enumerate(segs[:-1]):
                gap = segs[i + 1]["start"] - seg["end"]
                cuts.append(
                    T.marker(
                        "jump_cut_point",
                        seg["end"],
                        reason="natural sentence boundary"
                        + (" followed by a pause" if gap >= _LONG_PAUSE else ""),
                        confidence=T.round3(min(0.9, 0.55 + gap)),
                        evidence=[{"type": "transcript", "detail": seg["text"][:80]}],
                    )
                )
            out.append({"clip_id": clip["clip_id"], "cut_points": cuts})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Candidate jump-cut points at real sentence boundaries; "
                "pauses raise confidence. Cuts are proposed, never applied.",
            }
        )


# --------------------------------------------------------------------------- #
# 4. Silence Detection - real silence intervals (inferred from transcript).
# --------------------------------------------------------------------------- #
class SilenceDetectionAnalyzer(EditingAnalyzer):
    name = "silence_detection"
    version = "2"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        segments = ctx.transcript_segments()
        if not segments:
            return EditingOutcome.unavailable(_NO_TRANSCRIPT)

        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, ce, duration = _window(clip)
            segs = T.clip_segments(segments, cs, ce)
            intervals = [
                T.event(
                    "silence",
                    gap["start"],
                    gap["end"],
                    reason="no speech in interval (inferred from transcript timing, "
                    "not measured from the audio waveform)",
                    confidence=0.5,
                    evidence=[{"type": "transcript_gap", "detail": "gap between segments"}],
                )
                for gap in T.gaps_between(segs, duration, min_gap=_SILENCE_GAP)
            ]
            out.append({"clip_id": clip["clip_id"], "silences": intervals})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Silence is inferred from transcript gaps; true waveform "
                "silence requires an audio model (unavailable) - confidence kept modest.",
            }
        )


# --------------------------------------------------------------------------- #
# 5. Subtitle Segmentation - split captions at linguistic boundaries.
# --------------------------------------------------------------------------- #
class SubtitleSegmentationAnalyzer(EditingAnalyzer):
    name = "subtitle_segmentation"
    version = "6"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        segments = ctx.transcript_segments()
        if not segments:
            return EditingOutcome.unavailable(_NO_TRANSCRIPT)

        plans = _plans_by_id(ctx)
        settings = get_settings()
        default_max_words = settings.caption_intelligence.max_words_per_line
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, ce, _ = _window(clip)
            segs = T.clip_segments(segments, cs, ce)
            blueprint = _blueprint(plans, T.as_str(clip.get("plan_id")))
            caption_preferences = P.caption_personalization(
                T.as_dict(blueprint.get("personalization_directives_v2")) or None
                if settings.creator_personalization.apply_to_captions
                else None,
                default_style="default_clean",
                default_max_words=default_max_words,
            )
            chunks: list[dict[str, Any]] = []
            for i, seg in enumerate(segs):
                for piece in CAP.caption_chunks_for_segment(
                    seg,
                    max_words_per_line=int(caption_preferences["max_words_per_line"]),
                ):
                    chunks.append({**piece, "segment_index": i})
            out.append(
                {
                    "clip_id": clip["clip_id"],
                    "duration": T.as_float(clip.get("duration")),
                    "caption_chunks": chunks,
                    "caption_personalization": caption_preferences,
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Captions split at clause/punctuation boundaries and packed "
                "to a readable length - not at fixed time intervals.",
            }
        )


# --------------------------------------------------------------------------- #
# 6. Caption Timing - assign timing to each caption chunk.
# --------------------------------------------------------------------------- #
class CaptionTimingAnalyzer(EditingAnalyzer):
    name = "caption_timing"
    version = "7"
    depends_on = ("subtitle_segmentation",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        seg_stage = ctx.editing_data("subtitle_segmentation")
        if seg_stage is None:
            return EditingOutcome.unavailable(
                "Requires subtitle segmentation, which is unavailable."
            )
        out: list[dict[str, Any]] = []
        for clip in T.as_list(seg_stage.get("clips")):
            captions, quality = CAP.timed_caption_events(
                [T.as_dict(item) for item in T.as_list(clip.get("caption_chunks"))],
                T.as_float(clip.get("duration")),
            )
            out.append(
                {
                    "clip_id": T.as_str(clip.get("clip_id")),
                    "captions": captions,
                    "caption_timing_quality": quality,
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {"clips": out, "note": "Each caption gets a real start/end within its segment."}
        )


# --------------------------------------------------------------------------- #
# 7. Caption Layout - placement (face/OCR-aware where possible, else UNKNOWN).
# --------------------------------------------------------------------------- #
class CaptionLayoutAnalyzer(EditingAnalyzer):
    name = "caption_layout"
    version = "5"
    depends_on = ("caption_timing",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        timing = ctx.editing_data("caption_timing")
        if timing is None:
            return EditingOutcome.unavailable("Requires caption timing, which is unavailable.")
        faces = ctx.cognitive_data("face_detection")
        ocr = ctx.cognitive_data("ocr")
        unknowns: list[str] = []
        if faces is None:
            unknowns.append(
                "face regions (no face-detection model) - cannot verify captions avoid faces"
            )
        if ocr is None:
            unknowns.append(
                "on-screen text regions (no OCR) - cannot verify captions avoid burned-in text"
            )
        out = [
            {
                "clip_id": T.as_str(clip.get("clip_id")),
                "caption_count": len(T.as_list(clip.get("captions"))),
                "layout": {
                    "position": "lower_third",
                    "safe_margins": {"x_pct": 8, "bottom_pct": 14, "top_pct": 8},
                    "face_aware": faces is not None,
                    "ocr_aware": ocr is not None,
                    "reason": "default lower-third safe area"
                    + (
                        ""
                        if not unknowns
                        else "; UNKNOWN whether it overlaps " + "; ".join(unknowns)
                    ),
                },
            }
            for clip in T.as_list(timing.get("clips"))
        ]
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "unknowns": unknowns,
                "note": "Placement defaults to a lower-third safe area. Avoidance of "
                "faces/OCR/objects is UNKNOWN without the corresponding models.",
            }
        )


# --------------------------------------------------------------------------- #
# 8. Zoom Planner - punch-ins on emphasis moments.
# --------------------------------------------------------------------------- #
class ZoomPlannerAnalyzer(EditingAnalyzer):
    name = "zoom_planner"
    version = "3"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            bp = _blueprint(plans, clip["clip_id"])
            zooms: list[dict[str, Any]] = []
            hook_v2 = T.as_dict(bp.get("hook_v2"))
            hook_score = T.as_float(hook_v2.get("score"))
            zooms.append(
                T.event(
                    "hook_punch_zoom",
                    0.0,
                    min(duration, 0.85),
                    reason="first-second hook punch-in for retention",
                    confidence=max(0.6, min(0.95, hook_score or 0.7)),
                    evidence=[
                        {
                            "type": "hook_v2",
                            "detail": T.as_str(hook_v2.get("hook_line"))[:90],
                            "score": hook_v2.get("score"),
                        }
                    ],
                    scale=1.16,
                    easing="fast_out",
                )
            )
            for sug in T.as_list(bp.get("zoom_suggestions")):
                rel = T.to_clip_relative(T.as_float(sug.get("timestamp")), cs, duration)
                if rel is None:
                    continue
                zooms.append(
                    T.event(
                        "zoom_in",
                        rel,
                        min(duration, rel + 1.5),
                        reason=T.as_str(sug.get("reason")) or "emphasize this moment",
                        confidence=0.55,
                        evidence=[
                            {"type": "planner_emphasis", "detail": T.as_str(sug.get("reason"))}
                        ],
                        scale=1.15,
                    )
                )
            cursor = 4.0
            while cursor < duration - 1.5 and len(zooms) < 10:
                zooms.append(
                    T.event(
                        "micro_zoom",
                        cursor,
                        min(duration, cursor + 1.2),
                        reason=(
                            "recurring micro movement keeps a talking-head clip from feeling static"
                        ),
                        confidence=0.55,
                        evidence=[{"type": "pacing_rule", "detail": "3-7 second motion cadence"}],
                        scale=1.055,
                        easing="subtle",
                    )
                )
                cursor += 5.25
            if duration >= 8.0:
                zooms.append(
                    T.event(
                        "payoff_zoom",
                        max(0.0, duration - 2.2),
                        min(duration, duration - 0.25),
                        reason="final payoff emphasis before the clip exits",
                        confidence=0.58,
                        evidence=[{"type": "clip_boundary", "detail": "ending/payoff zone"}],
                        scale=1.1,
                        easing="smooth_in",
                    )
                )
            out.append({"clip_id": clip["clip_id"], "zooms": zooms})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Subtle punch-ins (~1.15x) on emphasis moments identified "
                "upstream. Magnitudes are recommendations, not applied effects.",
            }
        )


# --------------------------------------------------------------------------- #
# 9. Pan Planner - requires subject tracking; UNKNOWN without it.
# --------------------------------------------------------------------------- #
class PanPlannerAnalyzer(EditingAnalyzer):
    name = "pan_planner"
    version = "2"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            bp = _blueprint(plans, clip["clip_id"])
            switches = T.as_list(T.as_dict(bp.get("speaker_switches")).get("switches"))
            pans: list[dict[str, Any]] = []
            for sw in switches:
                rel = T.to_clip_relative(T.as_float(sw.get("timestamp")), cs, duration)
                if rel is None:
                    continue
                pans.append(
                    T.marker(
                        "pan_to_speaker",
                        rel,
                        reason=f"reframe toward speaker {T.as_str(sw.get('speaker'))}",
                        confidence=0.5,
                        evidence=[
                            {"type": "speaker_switch", "detail": T.as_str(sw.get("speaker"))}
                        ],
                    )
                )
            unknown = not pans
            out.append(
                {
                    "clip_id": clip["clip_id"],
                    "pans": pans,
                    "status": "unknown" if unknown else "planned",
                    "reason": None
                    if pans
                    else "pan planning needs subject/face tracking, which is "
                    "unavailable; returning UNKNOWN rather than guessing pan targets.",
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Pans are only planned where speaker-switch evidence exists; "
                "otherwise UNKNOWN (no subject-tracking model).",
            }
        )


# --------------------------------------------------------------------------- #
# 10. Crop Planner - 9:16 safe area from the source dimensions.
# --------------------------------------------------------------------------- #
class CropPlannerAnalyzer(EditingAnalyzer):
    name = "crop_planner"
    version = "4"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        inspection = ctx.cognitive_data("video_inspection") or {}
        width = T.as_float(inspection.get("width"))
        height = T.as_float(inspection.get("height"))
        vertical = bool(height and width and height >= width)
        faces = ctx.cognitive_data("face_detection")
        speakers = ctx.cognitive_data("speaker_segmentation")

        if not (width and height):
            crop: dict[str, Any] = {
                "target_aspect": "9:16",
                "status": "unknown",
                "reason": "source dimensions are unavailable (no video inspection); "
                "the exact crop region is UNKNOWN and must be computed at render time.",
            }
        elif vertical:
            crop = {
                "target_aspect": "9:16",
                "x_offset": 0,
                "width": int(width),
                "height": int(height),
                "subject_aware": False,
                "reason": "source is already vertical; no horizontal crop needed. "
                "Subject-aware reframing is UNKNOWN (no face/object model).",
            }
        else:
            target_w = round(height * 9 / 16)
            crop = {
                "target_aspect": "9:16",
                "x_offset": max(0, round((width - target_w) / 2)),
                "width": int(target_w),
                "height": int(height),
                "subject_aware": False,
                "reason": "center 9:16 crop of a horizontal source; subject-aware "
                "reframing is UNKNOWN without a face/object model.",
            }
        out: list[dict[str, Any]] = []
        for clip in clips:
            clip_crop = dict(crop)
            face_plan = _face_tracking_plan(
                face_data=faces,
                speaker_data=speakers,
                clip=clip,
                source_width=width,
                source_height=height,
                project_id=ctx.project.id,
            )
            if face_plan.get("mode") != "center_fallback":
                clip_crop["subject_aware"] = True
                clip_crop["reason"] = (
                    "face-aware 9:16 reframe from completed face detections; "
                    "renderer consumes crop keyframes when valid."
                )
            clip_crop["face_tracking_plan"] = face_plan
            out.append(
                {
                    "clip_id": clip["clip_id"],
                    "crop": clip_crop,
                    "face_tracking_plan": face_plan,
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {"clips": out, "note": "9:16 safe-area crop derived from real source dimensions."}
        )


# --------------------------------------------------------------------------- #
# 11. Hook Enhancement - cold open / preview / fast start / no changes.
# --------------------------------------------------------------------------- #
class HookEnhancementAnalyzer(EditingAnalyzer):
    name = "hook_enhancement"
    version = "2"
    depends_on = ("timeline_initialization", "silence_detection")

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        silences = {
            T.as_str(c.get("clip_id")): T.as_list(c.get("silences"))
            for c in T.as_list((ctx.editing_data("silence_detection") or {}).get("clips"))
        }
        out: list[dict[str, Any]] = []
        for clip in clips:
            bp = _blueprint(plans, clip["clip_id"])
            opening = T.as_dict(bp.get("opening_hook"))
            hook_v2 = T.as_dict(bp.get("hook_v2"))
            pacing = T.as_str(T.as_dict(bp.get("pacing")).get("value"))
            payoffs = T.as_list(bp.get("replay_moments"))
            lead_silence = next(
                (s for s in silences.get(clip["clip_id"], []) if T.as_float(s.get("start")) < 0.5),
                None,
            )

            if lead_silence and T.as_float(lead_silence.get("end")) >= 1.0:
                decision = {
                    "type": "fast_start",
                    "reason": "trim the silent lead-in so the clip opens on speech",
                    "suggested_trim_seconds": T.round3(T.as_float(lead_silence.get("end"))),
                    "confidence": 0.6,
                }
            elif T.as_float(hook_v2.get("score")) >= 0.72:
                decision = {
                    "type": "punch_in_caption_pop",
                    "reason": T.as_str(hook_v2.get("explanation"))
                    or "strong V2 hook should get a punch-in and caption emphasis",
                    "confidence": T.as_float(hook_v2.get("score")),
                    "hook_category": T.as_str(hook_v2.get("category")),
                }
            elif opening.get("text") and pacing == "fast":
                decision = {
                    "type": "no_changes",
                    "reason": "the clip already opens on a strong, fast hook",
                    "confidence": 0.6,
                }
            elif payoffs and not opening.get("text"):
                decision = {
                    "type": "preview",
                    "reason": "cold-open with a teaser of the later payoff to set a curiosity gap",
                    "confidence": 0.45,
                }
            elif opening.get("text"):
                decision = {
                    "type": "no_changes",
                    "reason": "opening line is a serviceable hook",
                    "confidence": 0.5,
                }
            else:
                decision = {
                    "type": "unknown",
                    "reason": "insufficient hook/pacing evidence to recommend an enhancement",
                    "confidence": None,
                }
            decision["evidence"] = [
                {"type": "opening_hook", "detail": T.as_str(opening.get("text"))[:80]},
                {
                    "type": "hook_v2",
                    "detail": T.as_str(hook_v2.get("category")),
                    "score": hook_v2.get("score"),
                },
                {"type": "pacing", "detail": pacing},
            ]
            out.append({"clip_id": clip["clip_id"], "decision": decision})
        report(1.0)
        return EditingOutcome.completed(
            {"clips": out, "note": "Hook enhancement decided per clip, with reasoning."}
        )


# --------------------------------------------------------------------------- #
# 12. Retention Planner - pattern-interrupt MARKERS (not effects).
# --------------------------------------------------------------------------- #
class RetentionPlannerAnalyzer(EditingAnalyzer):
    name = "retention_planner"
    version = "2"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            bp = _blueprint(plans, clip["clip_id"])
            markers: list[dict[str, Any]] = []
            for risk in T.as_list(bp.get("retention_risks")):
                rel = T.to_clip_relative(T.as_float(risk.get("timestamp")), cs, duration)
                if rel is None:
                    continue
                markers.append(
                    T.marker(
                        "pattern_interrupt",
                        rel,
                        reason="retention risk here - insert a pattern interrupt (cut/zoom/broll)",
                        confidence=0.5,
                        evidence=[
                            {"type": "retention_risk", "detail": T.as_str(risk.get("reason"))}
                        ],
                    )
                )
            out.append({"clip_id": clip["clip_id"], "checkpoints": markers})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Timeline markers only - where attention may dip. No effects "
                "are inserted; an editor/future engine decides the interrupt.",
            }
        )


# --------------------------------------------------------------------------- #
# 13. Music Planner - intro / drop / ending timestamps (NO selection).
# --------------------------------------------------------------------------- #
class MusicPlannerAnalyzer(EditingAnalyzer):
    name = "music_planner"
    version = "3"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            bp = _blueprint(plans, clip["clip_id"])
            markers = [
                T.marker(
                    "music_intro",
                    0.0,
                    reason="music in at clip start",
                    confidence=0.6,
                    evidence=[{"type": "clip_boundary", "detail": "start"}],
                ),
                T.marker(
                    "music_ending",
                    duration,
                    reason="music out at clip end",
                    confidence=0.6,
                    evidence=[{"type": "clip_boundary", "detail": "end"}],
                ),
            ]
            emphasis = T.as_list(bp.get("emphasis_moments")) or T.as_list(bp.get("replay_moments"))
            if emphasis:
                rel = T.to_clip_relative(T.as_float(emphasis[0].get("timestamp")), cs, duration)
                if rel is not None:
                    markers.append(
                        T.marker(
                            "music_drop",
                            rel,
                            reason="align a musical drop with the strongest moment",
                            confidence=0.45,
                            evidence=[{"type": "emphasis", "detail": "peak emphasis/payoff"}],
                        )
                    )
            out.append(
                {
                    "clip_id": clip["clip_id"],
                    "markers": markers,
                    "decision": T.as_dict(bp.get("music_decision_v2")),
                    "beats": {
                        "status": "unknown",
                        "reason": "beat detection requires audio analysis (unavailable); "
                        "structural music timestamps are provided but no beat map is asserted.",
                    },
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Music mood decisions are carried from V2 planning; rendering only "
                "mixes music when a local royalty-free/user-provided asset exists.",
            }
        )


# --------------------------------------------------------------------------- #
# 14. Transition Planner - recommend transition TYPES at cut points.
# --------------------------------------------------------------------------- #
class TransitionPlannerAnalyzer(EditingAnalyzer):
    name = "transition_planner"
    version = "2"
    depends_on = ("jump_cut_detection",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        jump = ctx.editing_data("jump_cut_detection")
        if jump is None:
            return EditingOutcome.unavailable("Requires jump-cut detection, which is unavailable.")
        clips, _ = _per_clip(ctx)
        topic_shifts = T.as_list((ctx.story_data("topic_segmentation") or {}).get("shifts"))
        cuts_by_clip = {
            T.as_str(c.get("clip_id")): T.as_list(c.get("cut_points"))
            for c in T.as_list(jump.get("clips"))
        }
        out: list[dict[str, Any]] = []
        for clip in clips or []:
            cs, _, duration = _window(clip)
            shift_times = {
                T.to_clip_relative(T.as_float(s.get("timestamp")), cs, duration)
                for s in topic_shifts
            }
            shift_times.discard(None)
            transitions: list[dict[str, Any]] = []
            for cut in cuts_by_clip.get(clip["clip_id"], []):
                at = T.as_float(cut.get("start"))
                near_shift = any(abs(at - st) < 1.0 for st in shift_times if st is not None)
                ttype = "cross_dissolve" if near_shift else "hard_cut"
                transitions.append(
                    T.marker(
                        "transition",
                        at,
                        reason="topic shift - a soft transition reads better"
                        if near_shift
                        else "same-topic sentence boundary - a hard cut keeps pace",
                        confidence=0.5,
                        evidence=[{"type": "cut_point", "detail": T.as_str(cut.get("reason"))}],
                        transition_type=ttype,
                    )
                )
            out.append({"clip_id": clip["clip_id"], "transitions": transitions})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Transition TYPES are recommended at cut points (hard cut / "
                "cross dissolve). Nothing is rendered or applied.",
            }
        )


# --------------------------------------------------------------------------- #
# 15. B-roll Planner - describe needed footage (never invent it).
# --------------------------------------------------------------------------- #
class BrollPlannerAnalyzer(EditingAnalyzer):
    name = "broll_planner"
    version = "2"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        density = T.as_list((ctx.story_data("information_density") or {}).get("windows"))
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            suggestions: list[dict[str, Any]] = []
            for window in density:
                if T.as_str(window.get("classification")) != "dense":
                    continue
                rel = T.to_clip_relative(T.as_float(window.get("start")), cs, duration)
                if rel is None:
                    continue
                suggestions.append(
                    T.event(
                        "broll_suggestion",
                        rel,
                        min(duration, rel + 3.0),
                        reason="information-dense passage - B-roll would aid understanding",
                        confidence=0.4,
                        evidence=[
                            {
                                "type": "information_density",
                                "detail": T.as_str(window.get("reason")),
                            }
                        ],
                        description="B-roll needed here; footage is described, never invented",
                    )
                )
            out.append({"clip_id": clip["clip_id"], "suggestions": suggestions})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Identifies WHERE B-roll would help and describes the need; "
                "no B-roll footage is invented or selected.",
            }
        )


# --------------------------------------------------------------------------- #
# 16. Timeline Validation - assemble tracks + validate continuity.
# --------------------------------------------------------------------------- #
class TimelineValidationAnalyzer(EditingAnalyzer):
    name = "timeline_validation"
    version = "12"
    depends_on = (
        "timeline_initialization",
        "speech_cleanup",
        "jump_cut_detection",
        "silence_detection",
        "caption_timing",
        "caption_layout",
        "zoom_planner",
        "pan_planner",
        "crop_planner",
        "hook_enhancement",
        "retention_planner",
        "music_planner",
        "transition_planner",
        "broll_planner",
    )

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.completed(
                {
                    "timeline_count": 0,
                    "timelines": [],
                    "report": {"valid": True, "clips": [], "issues": []},
                    "note": "No approved clips, so there are no timelines to assemble - "
                    "an honest, valid empty result.",
                }
            )

        by_clip = _index_stages(ctx)
        timelines: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []
        for clip in clips:
            cid = clip["clip_id"]
            duration = T.as_float(clip.get("duration"))
            bundle = by_clip.get(cid, {})
            timeline = _assemble_timeline(
                clip,
                bundle,
                _blueprint(plans, cid),
                project_id=ctx.project.id,
                captions_enabled=ctx.project.captions_enabled,
            )
            report_entry = _validate_timeline(timeline, duration)
            timelines.append(timeline)
            reports.append(report_entry)

        overall_valid = all(r["valid"] for r in reports)
        report(1.0)
        return EditingOutcome.completed(
            {
                "timeline_count": len(timelines),
                "timelines": timelines,
                "report": {
                    "valid": overall_valid,
                    "clips": reports,
                    "issue_count": sum(len(r["issues"]) for r in reports),
                },
                "note": "Each clip is assembled into video/audio/caption/marker tracks "
                "and checked for broken timestamps, out-of-bounds events, caption "
                "overlaps, and video continuity.",
            }
        )


# --------------------------------------------------------------------------- #
# Assembly + validation helpers (pure).
# --------------------------------------------------------------------------- #
def _index_stages(ctx: EditingStageContext) -> dict[str, dict[str, Any]]:
    """Index every per-clip stage output by clip id for assembly."""

    stages = (
        "speech_cleanup",
        "jump_cut_detection",
        "silence_detection",
        "caption_timing",
        "caption_layout",
        "zoom_planner",
        "pan_planner",
        "crop_planner",
        "hook_enhancement",
        "retention_planner",
        "music_planner",
        "transition_planner",
        "broll_planner",
    )
    out: dict[str, dict[str, Any]] = {}
    for stage in stages:
        data = ctx.editing_data(stage)
        if data is None:
            continue
        for clip in T.as_list(data.get("clips")):
            cid = T.as_str(clip.get("clip_id"))
            out.setdefault(cid, {})[stage] = clip
    return out


def _assemble_timeline(
    clip: dict[str, Any],
    bundle: dict[str, Any],
    blueprint: dict[str, Any],
    *,
    project_id: str | None = None,
    captions_enabled: bool = True,
) -> dict[str, Any]:
    duration = T.as_float(clip.get("duration"))
    crop = T.as_dict(T.as_dict(bundle.get("crop_planner")).get("crop"))
    face_tracking_plan = T.as_dict(
        T.as_dict(bundle.get("crop_planner")).get("face_tracking_plan")
        or crop.get("face_tracking_plan")
    )
    timing_bundle = T.as_dict(bundle.get("caption_timing"))
    caption_events, caption_intelligence = CAP.build_caption_intelligence(
        clip=clip,
        events=[T.as_dict(item) for item in T.as_list(timing_bundle.get("captions"))],
        timing_quality=T.as_dict(timing_bundle.get("caption_timing_quality")),
        blueprint=blueprint,
        face_plan=face_tracking_plan,
        project_id=project_id,
        captions_enabled=captions_enabled,
    )
    editing_v2 = _editing_v2_contract(
        clip,
        bundle,
        blueprint,
        face_tracking_plan,
        captions=caption_events,
        caption_intelligence=caption_intelligence,
        project_id=project_id,
    )
    unified = CI.unified_clip_intelligence(
        clip=clip,
        blueprint=blueprint,
        editing_v2=editing_v2,
    )

    motion_effects = T.as_list(
        T.as_dict(T.as_dict(editing_v2.get("motion_intelligence_v2")).get("effect_plan")).get(
            "effects"
        )
    )
    video_events = [clip["base_video_event"]]
    video_events += motion_effects or T.as_list(
        T.as_dict(bundle.get("zoom_planner")).get("zooms")
    )
    video_events += T.as_list(T.as_dict(bundle.get("pan_planner")).get("pans"))

    audio_events = [clip["base_audio_event"]]
    audio_events += T.as_list(T.as_dict(bundle.get("silence_detection")).get("silences"))
    audio_events += T.as_list(T.as_dict(bundle.get("speech_cleanup")).get("items"))

    markers: list[dict[str, Any]] = []
    markers += T.as_list(T.as_dict(bundle.get("jump_cut_detection")).get("cut_points"))
    markers += T.as_list(T.as_dict(bundle.get("retention_planner")).get("checkpoints"))
    markers += T.as_list(T.as_dict(bundle.get("music_planner")).get("markers"))
    markers += T.as_list(T.as_dict(bundle.get("transition_planner")).get("transitions"))
    markers += T.as_list(T.as_dict(bundle.get("broll_planner")).get("suggestions"))
    for effect in T.as_list(T.as_dict(blueprint.get("sound_effect_plan_v2")).get("effects")):
        markers.append(
            T.marker(
                f"sfx_{T.as_str(effect.get('type')) or 'effect'}",
                T.as_float(effect.get("at")),
                reason=T.as_str(effect.get("reason")),
                confidence=0.5,
                evidence=[{"type": "sfx_plan_v2", "detail": T.as_str(effect.get("type"))}],
                volume_db=effect.get("volume_db"),
            )
        )
    decision = T.as_dict(T.as_dict(bundle.get("hook_enhancement")).get("decision"))
    if decision:
        markers.append(
            T.marker(
                "hook_enhancement",
                0.0,
                reason=T.as_str(decision.get("reason")),
                confidence=decision.get("confidence"),
                evidence=T.as_list(decision.get("evidence")),
                decision=T.as_str(decision.get("type")),
            )
        )
    markers.sort(key=lambda m: T.as_float(m.get("start")))

    layout = T.as_dict(caption_intelligence.get("caption_safe_zone"))
    return {
        "clip_id": clip["clip_id"],
        "project_id": project_id,
        "plan_id": clip.get("plan_id"),
        "rank": clip.get("rank"),
        "source_video": clip.get("source_video"),
        "source_start": clip.get("source_start"),
        "source_end": clip.get("source_end"),
        "duration": duration,
        "source_window_v1": T.as_dict(clip.get("source_window_v1")),
        "boundary_quality": T.as_dict(clip.get("boundary_quality")),
        "boundary_quality_decision": T.as_dict(clip.get("boundary_quality_decision")),
        "fps": clip.get("fps"),
        "tracks": [
            {"kind": "video", "events": video_events},
            {"kind": "audio", "events": audio_events},
            {"kind": "caption", "events": caption_events},
            {"kind": "markers", "events": markers},
        ],
        "metadata": {
            "timeline": {
                **T.as_dict(clip.get("source_window_v1")),
                "boundary_quality": T.as_dict(clip.get("boundary_quality")),
                "boundary_quality_decision": T.as_dict(
                    clip.get("boundary_quality_decision")
                ),
                "boundary_validation": T.as_dict(clip.get("boundary_validation")),
                "boundary_warnings": T.as_list(clip.get("boundary_warnings")),
            },
            "aspect_ratio": T.as_str(T.as_dict(blueprint.get("aspect_ratio")).get("value"))
            or "9:16",
            "pacing": T.as_str(T.as_dict(blueprint.get("pacing")).get("value")),
            "title": T.as_str(T.as_dict(blueprint.get("title_suggestion")).get("text")),
            "subtitle_style": T.as_str(T.as_dict(blueprint.get("subtitle_style")).get("style")),
            "caption_layout": layout,
            "crop": crop,
            "face_tracking_plan": face_tracking_plan,
            "multi_speaker_layout_v2": face_tracking_plan,
            "hook_decision": T.as_str(decision.get("type")),
            "hook_v2": T.as_dict(blueprint.get("hook_v2")),
            "caption_decision_v2": T.as_dict(blueprint.get("caption_decision_v2")),
            "caption_intelligence_v2": caption_intelligence,
            "caption_timing_quality": T.as_dict(
                caption_intelligence.get("caption_timing_quality")
            ),
            "caption_readability_validation": T.as_dict(
                caption_intelligence.get("caption_readability_validation")
            ),
            "music_decision_v2": T.as_dict(blueprint.get("music_decision_v2")),
            "music_intelligence_v2": T.as_dict(editing_v2.get("music_intelligence_v2")),
            "sound_effect_plan_v2": T.as_dict(blueprint.get("sound_effect_plan_v2")),
            "story_v2_guidance": T.as_dict(blueprint.get("story_v2_guidance")),
            "story_trend_guidance": T.as_dict(blueprint.get("story_trend_guidance")),
            "planning_story_integration": T.as_dict(blueprint.get("planning_story_integration")),
            "boundary_quality": T.as_dict(
                clip.get("boundary_quality") or blueprint.get("boundary_quality")
            ),
            "planning_trend_integration": T.as_dict(
                blueprint.get("planning_trend_integration")
            ),
            "editing_guidance_v2": T.as_dict(blueprint.get("editing_guidance_v2")),
            "editing_trend_guidance": T.as_dict(blueprint.get("editing_trend_guidance")),
            "motion_intelligence_v2": T.as_dict(
                editing_v2.get("motion_intelligence_v2")
            ),
            "motion_safety_validation": T.as_dict(
                T.as_dict(editing_v2.get("motion_intelligence_v2")).get(
                    "motion_safety_validation"
                )
            ),
            "internet_trend_research_v2": T.as_dict(
                blueprint.get("internet_trend_research_v2")
                or blueprint.get("viral_research_snapshot")
            ),
            "v2_metadata": T.as_dict(blueprint.get("v2_metadata")),
            "personalization_directives_v2": T.as_dict(
                editing_v2.get("personalization_directives_v2")
            ),
            "planning_personalization": T.as_dict(
                editing_v2.get("planning_personalization")
            ),
            "editing_personalization": T.as_dict(
                editing_v2.get("editing_personalization")
            ),
            "caption_personalization": T.as_dict(
                editing_v2.get("caption_personalization")
            ),
            "music_personalization": T.as_dict(
                editing_v2.get("music_personalization")
            ),
            "motion_personalization": T.as_dict(
                editing_v2.get("motion_personalization")
            ),
            "personalization_applied_v2": T.as_dict(
                editing_v2.get("personalization_applied_v2")
            ),
            "editing_v2": editing_v2,
            "unified_clip_intelligence": unified,
            "quality_score": clip.get("quality_score"),
            "confidence": clip.get("confidence"),
        },
    }


def _editing_v2_contract(
    clip: dict[str, Any],
    bundle: dict[str, Any],
    blueprint: dict[str, Any],
    face_tracking_plan: dict[str, Any],
    *,
    captions: list[dict[str, Any]] | None = None,
    caption_intelligence: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Build the executable Editing V2 contract persisted on the timeline."""

    duration = T.as_float(clip.get("duration"))
    metadata = T.as_dict(blueprint.get("v2_metadata"))
    hook_v2 = T.as_dict(blueprint.get("hook_v2"))
    caption = T.as_dict(blueprint.get("caption_decision_v2"))
    music = T.as_dict(blueprint.get("music_decision_v2"))
    sfx = T.as_dict(blueprint.get("sound_effect_plan_v2"))
    story_guidance = T.as_dict(blueprint.get("story_v2_guidance"))
    planning_story = T.as_dict(blueprint.get("planning_story_integration"))
    boundary_quality = T.as_dict(
        clip.get("boundary_quality") or blueprint.get("boundary_quality")
    )
    editing_guidance_v2 = T.as_dict(blueprint.get("editing_guidance_v2"))
    trend_snapshot = T.as_dict(
        blueprint.get("internet_trend_research_v2")
        or blueprint.get("viral_research_snapshot")
    )
    trend_match = T.as_dict(blueprint.get("trend_match_v2"))
    trend_guidance = T.as_dict(blueprint.get("editing_trend_guidance")) or (
        build_editing_trend_guidance(
            trend_snapshot,
            T.as_dict(blueprint.get("content_niche")),
            trend_match,
        )
    )
    story_editing = T.as_dict(story_guidance.get("editing_guidance")) or editing_guidance_v2
    caption_words = {
        T.as_str(word).lower()
        for word in T.as_list(story_editing.get("caption_emphasis_words"))
        if T.as_str(word)
    }
    intensity = T.as_str(metadata.get("editing_intensity")) or "balanced"
    content = T.as_str(metadata.get("content_category")) or "auto"
    preset = _preset_for(content, intensity, T.as_str(hook_v2.get("category")))
    personalization_settings = get_settings().creator_personalization
    personalization_directives = T.as_dict(
        blueprint.get("personalization_directives_v2")
    )
    if personalization_settings.apply_to_editing:
        preset, editing_personalization = P.apply_editing_personalization(
            preset,
            personalization_directives or None,
        )
    else:
        editing_personalization = P.empty_application(
            "Editing personalization is disabled by configuration."
        )
    transitions = T.as_list(T.as_dict(bundle.get("transition_planner")).get("transitions"))
    captions = captions or []
    caption_intelligence = caption_intelligence or {}
    silence = T.as_list(T.as_dict(bundle.get("silence_detection")).get("silences"))
    music_intelligence = plan_music_intelligence(
        clip=clip,
        blueprint=blueprint,
        bundle=bundle,
        project_id=project_id,
    )
    motion_intelligence = MOT.build_motion_intelligence(
        clip=clip,
        blueprint=blueprint,
        caption_intelligence=caption_intelligence,
        music_intelligence=music_intelligence,
        face_plan=face_tracking_plan,
        sfx_plan=sfx,
        project_id=project_id,
    )
    render_effects = _render_effect_events(duration, preset)
    hook_editing = _hook_editing_contract(
        clip, captions, hook_v2, T.as_dict(bundle.get("hook_enhancement"))
    )
    edit_events = [
        _event_summary(e)
        for e in [
            *T.as_list(T.as_dict(motion_intelligence.get("effect_plan")).get("effects")),
            *transitions,
            *render_effects,
        ]
        if T.as_str(T.as_dict(e).get("type"))
    ]
    sfx_events = []
    trend_sfx_density = T.as_str(trend_guidance.get("sfx_density"))
    effective_sfx_density = (
        preset["sfx_density"]
        if editing_personalization.get("applied")
        else trend_sfx_density or preset["sfx_density"]
    )
    sfx_intensity = T.as_float(editing_personalization.get("sfx_intensity"), 0.35)
    if (
        sfx.get("enabled") is not False
        and effective_sfx_density != "minimal"
        and sfx_intensity > 0.05
    ):
        sfx_events.append(
            {
                "type": "impact",
                "time": 0.12,
                "gain_db": -13,
                "reason": "first-word hook hit",
                "status": "planned",
            }
        )
        if duration > 6 and effective_sfx_density not in {"low", "minimal"}:
            sfx_events.append(
                {
                    "type": "whoosh",
                    "time": min(duration - 0.5, 3.8),
                    "gain_db": -18,
                    "reason": "micro zoom movement accent",
                    "status": "planned",
                }
            )
        if duration > 14 and effective_sfx_density not in {"low", "minimal"}:
            sfx_events.append(
                {
                    "type": "subtle_hit",
                    "time": max(0.0, duration - 2.0),
                    "gain_db": -16,
                    "reason": "ending/payoff emphasis",
                    "status": "planned",
                }
            )
    caption_metrics = _caption_metrics(captions)
    ending_hold_s = T.as_float(story_editing.get("ending_hold_recommendation"))
    if ending_hold_s <= 0:
        ending_hold_s = T.as_float(editing_guidance_v2.get("ending_hold"))
    trend_ending_used = False
    if ending_hold_s <= 0 and T.as_str(trend_guidance.get("ending_style")):
        ending_hold_s = 0.2
        trend_ending_used = True
    ending_hold_s = min(0.6, max(0.0, ending_hold_s))
    consumed = {
        "story_used": story_guidance.get("story_guidance_used") is True,
        "virality_used": bool(
            hook_v2 or blueprint.get("viral_score_v2") or blueprint.get("hook_analysis_v2")
        ),
        "planning_used": bool(blueprint),
        "trend_used": bool(trend_snapshot),
        "hook_treatment_source": "virality_v2_hook" if hook_v2 else "fallback",
        "caption_words_source": (
            "story_analysis_v2" if caption_words else "default_highlight_words"
        ),
        "music_mood_source": (
            "story_analysis_v2"
            if T.as_str(story_editing.get("music_mood"))
            else "internet_trend_research_v2"
            if T.as_str(trend_guidance.get("music_mood"))
            else "planning_v2_music_decision"
        ),
        "sfx_moments_source": (
            "trend_guided_planning_v2"
            if sfx.get("enabled") is not False and trend_snapshot
            else "planning_v2_sound_effect_plan"
            if sfx.get("enabled") is not False
            else "disabled"
        ),
        "ending_hold_source": (
            "story_analysis_v2"
            if ending_hold_s > 0 and not trend_ending_used
            else "internet_trend_research_v2"
            if trend_ending_used
            else "default"
        ),
        "trend_guidance_source": trend_guidance.get("source"),
        "warnings": (
            []
            if story_guidance.get("story_guidance_used") is True
            else ["story_analysis_v2 guidance unavailable; editing used planning defaults"]
        )
        + [
            T.as_str(warning)
            for warning in T.as_list(trend_guidance.get("warnings"))
            if T.as_str(warning)
        ],
    }
    caption_personalization = T.as_dict(
        caption_intelligence.get("caption_personalization")
    )
    music_personalization = T.as_dict(
        music_intelligence.get("music_personalization")
    )
    motion_personalization = T.as_dict(
        motion_intelligence.get("motion_personalization")
    )
    planning_personalization = T.as_dict(
        blueprint.get("planning_personalization")
    )
    personalization_applied = P.combine_applications(
        planning_personalization,
        editing_personalization,
        caption_personalization,
        music_personalization,
        motion_personalization,
    )
    return {
        "version": "2",
        "clip_id": clip.get("clip_id"),
        "source_start": clip.get("source_start"),
        "source_end": clip.get("source_end"),
        "output_duration": duration,
        "boundary_quality": boundary_quality,
        "boundary_quality_decision": T.as_dict(
            clip.get("boundary_quality_decision")
            or boundary_quality.get("decision")
        ),
        "editing_style": preset["style"],
        "edit_intensity": intensity,
        "hook_strategy": {
            "hook_start": 0.0,
            "hook_text": T.as_str(hook_v2.get("hook_line") or hook_v2.get("overlay_text")),
            "hook_category": T.as_str(hook_v2.get("category")),
            "first_3_seconds_score": T.as_float(hook_v2.get("score")),
            "trend_motion_style": T.as_str(trend_guidance.get("hook_motion_style")),
            "events": [e for e in edit_events if e["start"] <= 3.0],
        },
        "hook_editing": hook_editing,
        "face_tracking_plan": face_tracking_plan,
        "multi_speaker_layout_v2": face_tracking_plan,
        "pacing_profile": {
            "profile": preset["pacing"]
            if editing_personalization.get("applied")
            else T.as_str(trend_guidance.get("pacing_style")) or preset["pacing"],
            "removed_silences": [
                {
                    "start": T.as_float(s.get("start")),
                    "end": T.as_float(s.get("end")),
                    "status": "planned_only",
                    "reason": (
                        "timeline identifies silence; destructive gap removal is conservative"
                    ),
                }
                for s in silence
                if T.as_float(s.get("end")) - T.as_float(s.get("start")) >= 0.6
            ],
            "original_duration": duration,
            "final_duration": duration,
        },
        "caption_style": {
            "style": T.as_str(
                T.as_dict(caption_intelligence.get("style_decision")).get("caption_style")
            )
            or T.as_str(trend_guidance.get("caption_style"))
            or T.as_str(caption.get("style"))
            or preset["caption_style"],
            "renderer": "ass",
            "animation": T.as_str(
                T.as_dict(caption_intelligence.get("style_decision")).get("animation_style")
            )
            or "pop_in",
            "highlight_words": T.as_list(
                T.as_dict(caption_intelligence.get("caption_emphasis")).get(
                    "highlighted_words"
                )
            )
            or sorted(set(T.HIGHLIGHT_WORDS) | caption_words),
            "metrics": caption_metrics,
            "reason": T.as_str(
                T.as_dict(caption_intelligence.get("style_decision")).get("reason")
            )
            or T.as_str(caption.get("reason"))
            or "style follows content type, hook strength, and mobile readability",
        },
        "caption_intelligence_v2": caption_intelligence,
        "caption_timing_quality": T.as_dict(
            caption_intelligence.get("caption_timing_quality")
        ),
        "hook_caption_treatment": T.as_dict(
            caption_intelligence.get("hook_caption_treatment")
        ),
        "caption_safe_zone": T.as_dict(caption_intelligence.get("caption_safe_zone")),
        "speaker_captioning": T.as_dict(caption_intelligence.get("speaker_captioning")),
        "caption_readability_validation": T.as_dict(
            caption_intelligence.get("caption_readability_validation")
        ),
        "music_plan": {
            **music,
            "mood": T.as_str(story_editing.get("music_mood"))
            or T.as_str(trend_guidance.get("music_mood"))
            or T.as_str(
                T.as_dict(music_intelligence.get("decision")).get("target_mood")
            ),
            "target_mood": T.as_str(
                T.as_dict(music_intelligence.get("decision")).get("target_mood")
            ),
            "role": T.as_str(
                T.as_dict(music_intelligence.get("decision")).get("music_role")
            ),
            "status": (
                "pending_asset_resolution"
                if T.as_dict(music_intelligence.get("decision")).get("should_use_music")
                else "disabled"
            ),
            "ducking": T.as_dict(music_intelligence.get("mix_plan")).get(
                "ducking_enabled"
            ),
            "target_gain_db": T.as_dict(music_intelligence.get("mix_plan")).get(
                "music_gain_db"
            ),
            "fade_in_s": T.as_dict(music_intelligence.get("mix_plan")).get(
                "fade_in_seconds"
            ),
            "fade_out_s": T.as_dict(music_intelligence.get("mix_plan")).get(
                "fade_out_seconds"
            ),
        },
        "music_intelligence_v2": music_intelligence,
        "motion_intelligence_v2": motion_intelligence,
        "motion_safety_validation": T.as_dict(
            motion_intelligence.get("motion_safety_validation")
        ),
        "sfx_plan": {
            **sfx,
            "status": "pending_asset_resolution" if sfx.get("enabled") is not False else "disabled",
            "events": sfx_events,
            "density": effective_sfx_density,
        },
        "voice_enhancement_plan": {
            "applied_at_render": True,
            "filters": [
                "highpass",
                "lowpass",
                "afftdn",
                "dynaudnorm",
                "compand",
                "alimiter",
                "loudnorm",
            ],
            "loudness_target": "-16 LUFS",
            "peak_target": "-1.5 dBTP",
            "reason": "speech clarity and platform loudness normalization",
        },
        "video_enhancement_plan": {
            "applied_at_render": True,
            "profile": preset["video_profile"],
            "filters": ["eq", "unsharp", "format"],
            "reason": "subtle contrast, saturation, and sharpness polish without heavy CV models",
        },
        "motion_plan": {
            "events": T.as_list(
                T.as_dict(motion_intelligence.get("effect_plan")).get("effects")
            ),
            "zoom_frequency": preset["zoom_frequency"],
            "reason": T.as_dict(motion_intelligence.get("decision")).get("reason"),
            "source": "motion_intelligence_v2",
        },
        "ending_hold": {
            "duration_s": T.round3(ending_hold_s),
            "source": consumed["ending_hold_source"],
            "reason": "preserve final payoff beat"
            if ending_hold_s > 0
            else "no ending hold requested",
        },
        "editing_trend_guidance": trend_guidance,
        "editing_guidance_consumed": consumed,
        "personalization_directives_v2": personalization_directives,
        "planning_personalization": planning_personalization,
        "editing_personalization": editing_personalization,
        "caption_personalization": caption_personalization,
        "music_personalization": music_personalization,
        "motion_personalization": motion_personalization,
        "personalization_applied_v2": personalization_applied,
        "upstream_guidance": {
            "story_id": story_guidance.get("story_id"),
            "boundary_quality": boundary_quality,
            "planning_story_integration": planning_story,
            "planning_trend_integration": T.as_dict(
                blueprint.get("planning_trend_integration")
            ),
            "trend_snapshot_id": trend_snapshot.get("snapshot_id"),
            "context_caption": T.as_dict(story_guidance.get("planning_guidance")).get(
                "context_caption"
            ),
        },
        "transition_plan": {
            "events": [_event_summary(e) for e in transitions],
            "style": preset["transition_style"],
        },
        "render_effects": render_effects,
        "quality_targets": {
            "resolution": "1080x1920",
            "max_caption_cps": 23,
            "audio_peak_target": "-1.5 dBTP",
            "music_below_speech_db": -18,
            "platform": ["YouTube Shorts", "Instagram Reels", "TikTok"],
        },
    }


def _preset_for(content: str, intensity: str, hook_category: str) -> dict[str, str]:
    key = content.lower().replace(" / ", "_").replace(" ", "_")
    if "motivation" in key or "motivational" in hook_category:
        return {
            "style": "motivation_high_aura",
            "pacing": "cinematic_fast",
            "caption_style": "motivational_cinematic",
            "video_profile": "high_aura_contrast",
            "transition_style": "impact_cut",
            "zoom_frequency": "medium_high",
            "sfx_density": "medium",
        }
    if "stream" in key or "entertainment" in key or "funny" in key:
        return {
            "style": "stream_entertainment",
            "pacing": "fast_pattern_interrupts",
            "caption_style": "stream_reaction",
            "video_profile": "high_energy",
            "transition_style": "whip_or_pop",
            "zoom_frequency": "high",
            "sfx_density": "medium_high",
        }
    if "educational" in key:
        return {
            "style": "clean_educational",
            "pacing": "tight_clarity",
            "caption_style": "clean_educational",
            "video_profile": "clean_sharp",
            "transition_style": "quick_cut",
            "zoom_frequency": "medium",
            "sfx_density": "low",
        }
    if "emotional" in key:
        return {
            "style": "emotional_story",
            "pacing": "restrained_cinematic",
            "caption_style": "dramatic_hook",
            "video_profile": "warm_cinematic",
            "transition_style": "soft_cut",
            "zoom_frequency": "low_medium",
            "sfx_density": "low",
        }
    return {
        "style": "podcast_talking_head" if intensity != "high-energy" else "high_energy_short",
        "pacing": "tight_balanced",
        "caption_style": "high_energy_bold",
        "video_profile": "clean_high_retention",
        "transition_style": "quick_cut",
        "zoom_frequency": "medium_high",
        "sfx_density": "medium",
    }


def _render_effect_events(duration: float, preset: dict[str, str]) -> list[dict[str, Any]]:
    return [
        T.event(
            "subtle_sharpen_color",
            0.0,
            duration,
            reason=f"apply {preset['video_profile']} visual enhancement profile",
            confidence=0.8,
            evidence=[{"type": "preset", "detail": preset["style"]}],
            profile=preset["video_profile"],
        )
    ]


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": T.as_str(event.get("type")),
        "start": T.as_float(event.get("start")),
        "end": T.as_float(event.get("end")),
        "strength": event.get("scale") or event.get("intensity"),
        "reason": T.as_str(event.get("reason")),
    }


def _caption_metrics(captions: list[dict[str, Any]]) -> dict[str, Any]:
    if not captions:
        return {
            "total_captions": 0,
            "comfortable": 0,
            "brisk": 0,
            "too_fast": 0,
            "average_cps": 0,
            "max_cps": 0,
        }
    cps_values: list[float] = []
    counts = {"comfortable": 0, "brisk": 0, "too_fast": 0}
    for caption in captions:
        metrics = T.as_dict(caption.get("readability"))
        comfort = T.as_str(metrics.get("comfort")) or "comfortable"
        if comfort in counts:
            counts[comfort] += 1
        cps_values.append(T.as_float(metrics.get("characters_per_second")))
    return {
        "total_captions": len(captions),
        **counts,
        "average_cps": T.round3(sum(cps_values) / max(1, len(cps_values))),
        "max_cps": T.round3(max(cps_values or [0.0])),
    }


def _hook_editing_contract(
    clip: dict[str, Any],
    captions: list[dict[str, Any]],
    hook_v2: dict[str, Any],
    hook_stage: dict[str, Any],
) -> dict[str, Any]:
    duration = T.as_float(clip.get("duration"))
    decision = T.as_dict(hook_stage.get("decision"))
    first_caption = min(captions, key=lambda item: T.as_float(item.get("start")), default={})
    first_word_time = T.as_float(first_caption.get("start"), 0.0)
    hook_text = T.as_str(
        hook_v2.get("hook_line") or hook_v2.get("overlay_text") or first_caption.get("text")
    )
    trim_suggestion = min(0.35, max(0.0, T.as_float(decision.get("suggested_trim_seconds"))))
    score = T.as_float(hook_v2.get("score"), 0.55)
    return {
        "first_meaningful_word_time": T.round3(first_word_time),
        "hook_trim_adjustment": T.round3(trim_suggestion),
        "hook_caption_style": "bold_hook_word_highlight",
        "hook_motion_event": {
            "type": "hook_punch_zoom",
            "start": 0.0,
            "end": T.round3(min(duration, 0.85)),
            "scale": 1.16,
        },
        "hook_sfx_event": {
            "type": "impact",
            "time": 0.12,
            "gain_db": -13,
            "safe_default": True,
        },
        "strongest_hook_words": T.highlight_words(hook_text)[:3],
        "first_3_seconds_score": T.round3(min(0.98, max(0.55, score + 0.08))),
        "warnings": []
        if trim_suggestion
        else ["No destructive hook trim was applied; timing stays source-aligned."],
    }


def _validate_timeline(timeline: dict[str, Any], duration: float) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []
    video_events: list[dict[str, Any]] = []
    for track in T.as_list(timeline.get("tracks")):
        events = T.as_list(track.get("events"))
        issues.extend(T.validate_event_bounds(events, duration))
        if track.get("kind") == "caption":
            captions = events
        elif track.get("kind") == "video":
            video_events = events
    issues.extend(T.find_overlaps(captions))
    # Continuity: the base video clip must cover the full clip duration.
    base = next((e for e in video_events if e.get("type") == "source_clip"), None)
    if base is None:
        issues.append({"detail": "missing base video clip (no continuity)"})
    elif abs(T.as_float(base.get("end")) - duration) > 0.05:
        issues.append({"detail": "base video clip does not span the full clip duration"})
    return {"clip_id": timeline.get("clip_id"), "valid": not issues, "issues": issues}

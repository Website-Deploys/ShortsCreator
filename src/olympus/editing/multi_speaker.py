"""Anonymous face-track consolidation and Multi-Speaker Layout V2 decisions."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from itertools import pairwise
from math import hypot
from typing import Any

from olympus.platform.config import get_settings

_MAX_CROP_KEYFRAMES = 32


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str(value: Any) -> str:
    return str(value or "").strip()


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _bounded_keyframes(
    keyframes: list[dict[str, Any]], limit: int = _MAX_CROP_KEYFRAMES
) -> list[dict[str, Any]]:
    by_time: dict[float, dict[str, Any]] = {}
    for item in sorted(keyframes, key=lambda value: _float(value.get("time"))):
        by_time[round(_float(item.get("time")), 3)] = item
    points = list(by_time.values())
    if len(points) <= limit:
        return points
    indexes = {
        round(position * (len(points) - 1) / (limit - 1)) for position in range(limit)
    }
    return [points[index] for index in sorted(indexes)]


def _center_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    dx = _float(a.get("x_center")) - _float(b.get("x_center"))
    dy = _float(a.get("y_center")) - _float(b.get("y_center"))
    return hypot(dx, dy)


def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax1 = _float(a.get("x_center")) - _float(a.get("width")) / 2
    ay1 = _float(a.get("y_center")) - _float(a.get("height")) / 2
    ax2 = _float(a.get("x_center")) + _float(a.get("width")) / 2
    ay2 = _float(a.get("y_center")) + _float(a.get("height")) / 2
    bx1 = _float(b.get("x_center")) - _float(b.get("width")) / 2
    by1 = _float(b.get("y_center")) - _float(b.get("height")) / 2
    bx2 = _float(b.get("x_center")) + _float(b.get("width")) / 2
    by2 = _float(b.get("y_center")) + _float(b.get("height")) / 2
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(
        0.0, min(ay2, by2) - max(ay1, by1)
    )
    union = max(0.0, (ax2 - ax1) * (ay2 - ay1)) + max(
        0.0, (bx2 - bx1) * (by2 - by1)
    ) - intersection
    return intersection / union if union > 0 else 0.0


def _predicted_box(track: dict[str, Any], timestamp: float) -> dict[str, Any]:
    observations: list[dict[str, Any]] = track["observations"]
    last = observations[-1]
    if len(observations) < 2:
        return last
    previous = observations[-2]
    elapsed = max(0.001, _float(last.get("time")) - _float(previous.get("time")))
    future = max(0.0, timestamp - _float(last.get("time")))
    return {
        **last,
        "x_center": _clamp(
            _float(last.get("x_center"))
            + (_float(last.get("x_center")) - _float(previous.get("x_center")))
            / elapsed
            * future,
            0.0,
            1.0,
        ),
        "y_center": _clamp(
            _float(last.get("y_center"))
            + (_float(last.get("y_center")) - _float(previous.get("y_center")))
            / elapsed
            * future,
            0.0,
            1.0,
        ),
    }


def consolidate_face_tracks(
    detections: list[dict[str, Any]], duration: float
) -> list[dict[str, Any]]:
    """Build anonymous temporal tracks without recognizing or identifying people."""

    settings = get_settings().multi_speaker_layout
    usable = [
        dict(item)
        for item in detections
        if _float(item.get("confidence")) >= settings.minimum_face_confidence
    ]
    usable.sort(key=lambda item: (_float(item.get("time")), _str(item.get("face_id"))))
    tracks: list[dict[str, Any]] = []
    frame_groups: dict[float, list[dict[str, Any]]] = {}
    for detection in usable:
        frame_groups.setdefault(round(_float(detection.get("time")), 3), []).append(detection)

    for timestamp, frame in sorted(frame_groups.items()):
        used: set[int] = set()
        for detection in frame:
            best_index: int | None = None
            best_score = -1.0
            for index, track in enumerate(tracks):
                if index in used:
                    continue
                last = track["observations"][-1]
                gap = timestamp - _float(last.get("time"))
                source_hint = _str(detection.get("face_id"))
                same_hint = bool(source_hint and source_hint == track.get("source_hint"))
                max_gap = settings.interpolation_max_gap_seconds * (3.0 if same_hint else 1.0)
                if gap < -0.001 or gap > max_gap:
                    continue
                predicted = _predicted_box(track, timestamp)
                distance = _center_distance(predicted, detection)
                overlap = _iou(predicted, detection)
                size_delta = abs(
                    _float(predicted.get("width")) - _float(detection.get("width"))
                ) + abs(_float(predicted.get("height")) - _float(detection.get("height")))
                max_distance = settings.max_crop_movement_per_second * max(gap, 0.1) + 0.12
                if distance > max_distance and overlap < 0.05 and not same_hint:
                    continue
                score = overlap * 0.48 + max(0.0, 1.0 - distance / 0.5) * 0.32
                score += max(0.0, 1.0 - size_delta / 0.6) * 0.12
                score += 0.2 if same_hint else 0.0
                if score > best_score:
                    best_score = score
                    best_index = index
            if best_index is None or best_score < 0.34:
                tracks.append(
                    {
                        "face_track_id": f"face_track_{len(tracks) + 1}",
                        "source_hint": _str(detection.get("face_id")) or None,
                        "observations": [detection],
                        "warnings": [],
                    }
                )
                used.add(len(tracks) - 1)
                continue
            track = tracks[best_index]
            last = track["observations"][-1]
            gap = max(0.001, timestamp - _float(last.get("time")))
            distance = _center_distance(last, detection)
            allowed = settings.max_crop_movement_per_second * gap + 0.16
            if distance > allowed and _float(detection.get("confidence")) < 0.75:
                track["warnings"].append(
                    f"Rejected low-confidence position jump at {timestamp:.3f}s."
                )
                used.add(best_index)
                continue
            track["observations"].append(detection)
            used.add(best_index)

    output: list[dict[str, Any]] = []
    for track in tracks:
        observations = track["observations"]
        first = _float(observations[0].get("time"))
        last = _float(observations[-1].get("time"))
        observation_gaps = [
            max(0.0, _float(current.get("time")) - _float(previous.get("time")))
            for previous, current in pairwise(observations)
        ]
        uses_sparse_temporal_hint = bool(track.get("source_hint")) and len(observations) >= 3
        coverage_gap_limit = settings.interpolation_max_gap_seconds * (
            3.0 if uses_sparse_temporal_hint else 1.0
        )
        observed_seconds = sum(
            min(gap, coverage_gap_limit) for gap in observation_gaps
        )
        if len(observations) == 1:
            observed_seconds = min(duration, settings.missing_detection_hold_seconds)
        if uses_sparse_temporal_hint and any(
            gap > settings.interpolation_max_gap_seconds for gap in observation_gaps
        ):
            track["warnings"].append(
                "Preserved sparse samples using an upstream anonymous temporal track hint."
            )
        coverage = _clamp(observed_seconds / max(duration, 0.1), 0.0, 1.0)
        confidence = sum(_float(item.get("confidence")) for item in observations) / max(
            1, len(observations)
        )
        movement = [
            _center_distance(previous, current)
            for previous, current in pairwise(observations)
        ]
        mean_movement = sum(movement) / max(1, len(movement))
        stability = _clamp(
            confidence * 0.55 + coverage * 0.35 + max(0.0, 1.0 - mean_movement * 4) * 0.1,
            0.0,
            1.0,
        )
        output.append(
            {
                "face_track_id": track["face_track_id"],
                "first_seen": round(first, 3),
                "last_seen": round(last, 3),
                "observation_count": len(observations),
                "coverage_ratio": round(coverage, 3),
                "mean_confidence": round(confidence, 3),
                "stability_score": round(stability, 3),
                "average_box": {
                    key: round(
                        sum(_float(item.get(key)) for item in observations)
                        / max(1, len(observations)),
                        3,
                    )
                    for key in ("x_center", "y_center", "width", "height")
                },
                "observations": observations,
                "warnings": track["warnings"],
            }
        )
    output.sort(
        key=lambda item: (
            _float(item.get("stability_score")),
            _float(item.get("coverage_ratio")),
            _float(item.get("mean_confidence")),
        ),
        reverse=True,
    )
    return output


def associate_speakers(
    tracks: list[dict[str, Any]],
    speaker_timeline: list[dict[str, Any]],
    *,
    clip_start: float,
    clip_duration: float,
) -> list[dict[str, Any]]:
    """Associate diarized labels only when visibility evidence is unambiguous."""

    settings = get_settings().multi_speaker_layout
    evidence: dict[str, dict[str, float]] = {}
    supporting: dict[tuple[str, str], list[dict[str, float]]] = {}
    speaker_totals: dict[str, float] = {}
    for raw in speaker_timeline:
        speaker = _str(raw.get("speaker"))
        start = max(0.0, _float(raw.get("start")) - clip_start)
        end = min(clip_duration, _float(raw.get("end")) - clip_start)
        if not speaker or end <= start:
            continue
        speaker_totals[speaker] = speaker_totals.get(speaker, 0.0) + end - start
        visible = []
        for track in tracks:
            observations = track.get("observations") or []
            if any(start <= _float(item.get("time")) <= end for item in observations):
                visible.append(track)
        if len(visible) != 1:
            continue
        track_id = _str(visible[0].get("face_track_id"))
        evidence.setdefault(speaker, {})[track_id] = (
            evidence.setdefault(speaker, {}).get(track_id, 0.0) + end - start
        )
        supporting.setdefault((speaker, track_id), []).append(
            {"start": round(start, 3), "end": round(end, 3)}
        )

    associations: list[dict[str, Any]] = []
    claimed: set[str] = set()
    for speaker, candidates in sorted(evidence.items()):
        ordered = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
        track_id, seconds = ordered[0]
        conflict = len(ordered) > 1 and ordered[1][1] >= seconds * 0.75
        ratio = seconds / max(0.001, speaker_totals.get(speaker, seconds))
        confidence = _clamp(0.5 + ratio * 0.45, 0.0, 0.95)
        if conflict or track_id in claimed or confidence < settings.minimum_association_confidence:
            associations.append(
                {
                    "speaker_id": speaker,
                    "face_track_id": None,
                    "confidence": round(confidence, 3),
                    "method": "unresolved_visibility_overlap",
                    "supporting_segments": [],
                    "conflicts": [item[0] for item in ordered],
                    "warnings": ["Speaker-to-face evidence was conflicting or non-unique."],
                }
            )
            continue
        claimed.add(track_id)
        associations.append(
            {
                "speaker_id": speaker,
                "face_track_id": track_id,
                "confidence": round(confidence, 3),
                "method": "single_visible_track_during_diarized_segment",
                "supporting_segments": supporting.get((speaker, track_id), []),
                "conflicts": [],
                "warnings": [
                    "Association is temporal visibility evidence, not biometric identity "
                    "or lip-sync."
                ],
            }
        )
    return associations


def _track_keyframes(track: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    settings = get_settings().multi_speaker_layout
    observations = sorted(
        [dict(item) for item in track.get("observations") or []],
        key=lambda item: _float(item.get("time")),
    )
    if not observations:
        return []
    sx = _float(observations[0].get("x_center"), 0.5)
    sy = _float(observations[0].get("y_center"), 0.46)
    sw = _float(observations[0].get("width"), 0.2)
    sh = _float(observations[0].get("height"), 0.22)
    zoom = _clamp(1.0 + max(0.0, 0.22 - sh) * 0.5, 1.0, 1.12)
    last_time = _float(observations[0].get("time"))
    last_confidence = _float(observations[0].get("confidence"), 0.5)

    def keyframe(timestamp: float, confidence: float) -> dict[str, Any]:
        return {
            "time": round(timestamp, 3),
            "x_center": round(_clamp(sx, 0.06, 0.94), 3),
            "y_center": round(_clamp(sy - 0.04, 0.1, 0.84), 3),
            "width": round(sw, 3),
            "height": round(sh, 3),
            "zoom": round(zoom, 3),
            "confidence": round(confidence, 3),
            "source_face_id": track.get("face_track_id"),
            "source_face_track_id": track.get("face_track_id"),
            "speaker_id": None,
            "active": True,
        }

    keyframes: list[dict[str, Any]] = [keyframe(last_time, last_confidence)]
    for observation in observations[1:]:
        timestamp = _float(observation.get("time"))
        gap = max(0.001, timestamp - last_time)
        if gap > settings.interpolation_max_gap_seconds:
            hold_until = min(timestamp, last_time + settings.missing_detection_hold_seconds)
            transition_from = max(hold_until, timestamp - settings.interpolation_max_gap_seconds)
            for boundary in (hold_until, transition_from):
                if boundary > _float(keyframes[-1].get("time")) + 0.001:
                    keyframes.append(keyframe(boundary, last_confidence))
        effective_gap = min(gap, settings.interpolation_max_gap_seconds)
        confidence = _clamp(_float(observation.get("confidence"), 0.5), 0.0, 1.0)
        alpha = 0.2 + confidence * 0.25
        movement_limit = settings.max_crop_movement_per_second * effective_gap
        size_limit = settings.max_zoom_change_per_second * effective_gap
        x_delta = _float(observation.get("x_center"), sx) - sx
        y_delta = _float(observation.get("y_center"), sy) - sy
        if abs(x_delta) < 0.006:
            x_delta = 0.0
        if abs(y_delta) < 0.006:
            y_delta = 0.0
        sx += _clamp(x_delta * alpha, -movement_limit, movement_limit)
        sy += _clamp(y_delta * alpha, -movement_limit, movement_limit)
        sw += _clamp(
            (_float(observation.get("width"), sw) - sw) * alpha,
            -size_limit,
            size_limit,
        )
        sh += _clamp(
            (_float(observation.get("height"), sh) - sh) * alpha,
            -size_limit,
            size_limit,
        )
        target_zoom = _clamp(1.0 + max(0.0, 0.22 - sh) * 0.5, 1.0, 1.12)
        zoom += _clamp((target_zoom - zoom) * alpha, -size_limit, size_limit)
        keyframes.append(keyframe(timestamp, confidence))
        last_time = timestamp
        last_confidence = confidence
    if keyframes[0]["time"] > 0:
        keyframes.insert(0, {**keyframes[0], "time": 0.0})
    if keyframes[-1]["time"] < duration:
        keyframes.append({**keyframes[-1], "time": round(duration, 3)})
    return _bounded_keyframes(keyframes)


def _nearest_keyframe(track: dict[str, Any], timestamp: float) -> dict[str, Any]:
    observations = track.get("observations") or []
    return min(observations, key=lambda item: abs(_float(item.get("time")) - timestamp))


def _active_speaker_keyframes(
    tracks: list[dict[str, Any]],
    associations: list[dict[str, Any]],
    speaker_timeline: list[dict[str, Any]],
    *,
    clip_start: float,
    duration: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    settings = get_settings().multi_speaker_layout
    speaker_map = {
        _str(item.get("speaker_id")): _str(item.get("face_track_id"))
        for item in associations
        if item.get("face_track_id")
        and _float(item.get("confidence")) >= settings.minimum_association_confidence
    }
    track_map = {_str(track.get("face_track_id")): track for track in tracks}
    keyframes: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    current_speaker: str | None = None
    last_switch = -999.0
    max_switches = max(1, round(settings.maximum_render_switches_per_minute * duration / 60))
    for segment in sorted(speaker_timeline, key=lambda item: _float(item.get("start"))):
        speaker = _str(segment.get("speaker"))
        track = track_map.get(speaker_map.get(speaker, ""))
        start = max(0.0, _float(segment.get("start")) - clip_start)
        end = min(duration, _float(segment.get("end")) - clip_start)
        if track is None or end - start < settings.minimum_speaker_hold_seconds:
            continue
        if current_speaker and speaker != current_speaker:
            minimum_hold = max(
                settings.minimum_speaker_hold_seconds,
                settings.switch_hysteresis_seconds,
            )
            if start - last_switch < minimum_hold or len(switches) >= max_switches:
                continue
            switches.append(
                {
                    "time": round(start, 3),
                    "from_speaker": current_speaker,
                    "to_speaker": speaker,
                    "confidence": round(
                        min(
                            _float(item.get("confidence"))
                            for item in associations
                            if _str(item.get("speaker_id")) == speaker
                        ),
                        3,
                    ),
                    "reason": "diarized speaker segment with unique temporal face association",
                    "transition_duration": settings.switch_hysteresis_seconds,
                }
            )
            last_switch = start
        elif current_speaker is None:
            last_switch = start
        current_speaker = speaker
        for timestamp in (start, end):
            observation = _nearest_keyframe(track, timestamp)
            keyframes.append(
                {
                    "time": round(timestamp, 3),
                    "x_center": round(_float(observation.get("x_center"), 0.5), 3),
                    "y_center": round(_float(observation.get("y_center"), 0.46) - 0.04, 3),
                    "width": round(_float(observation.get("width"), 0.2), 3),
                    "height": round(_float(observation.get("height"), 0.22), 3),
                    "zoom": 1.04,
                    "confidence": round(_float(observation.get("confidence"), 0.5), 3),
                    "source_face_id": track.get("face_track_id"),
                    "source_face_track_id": track.get("face_track_id"),
                    "speaker_id": speaker,
                    "active": True,
                }
            )
    keyframes.sort(key=lambda item: _float(item.get("time")))
    if keyframes and keyframes[0]["time"] > 0:
        keyframes.insert(0, {**keyframes[0], "time": 0.0})
    if keyframes and keyframes[-1]["time"] < duration:
        keyframes.append({**keyframes[-1], "time": round(duration, 3)})
    return _bounded_keyframes(keyframes), switches


def _multi_face_keyframes(tracks: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    by_time: dict[float, list[dict[str, Any]]] = {}
    for track in tracks:
        for observation in track.get("observations") or []:
            by_time.setdefault(round(_float(observation.get("time")), 3), []).append(observation)
    combined: list[dict[str, Any]] = []
    for timestamp, observations in sorted(by_time.items()):
        left = min(
            _float(item.get("x_center")) - _float(item.get("width")) / 2
            for item in observations
        )
        right = max(
            _float(item.get("x_center")) + _float(item.get("width")) / 2
            for item in observations
        )
        top = min(
            _float(item.get("y_center")) - _float(item.get("height")) / 2
            for item in observations
        )
        bottom = max(
            _float(item.get("y_center")) + _float(item.get("height")) / 2
            for item in observations
        )
        combined.append(
            {
                "time": timestamp,
                "x_center": _clamp((left + right) / 2, 0.0, 1.0),
                "y_center": _clamp((top + bottom) / 2, 0.0, 1.0),
                "width": _clamp(right - left, 0.01, 1.0),
                "height": _clamp(bottom - top, 0.01, 1.0),
                "confidence": sum(_float(item.get("confidence")) for item in observations)
                / max(1, len(observations)),
                "face_id": "multi_face_safe_frame",
            }
        )
    synthetic = {
        "face_track_id": "multi_face_safe_frame",
        "observations": combined,
    }
    return _track_keyframes(synthetic, duration)


def _naturally_framed(
    tracks: list[dict[str, Any]], source_width: float, source_height: float
) -> bool:
    if source_width <= 0 or source_height <= 0:
        return False
    boxes = [track.get("average_box") or {} for track in tracks[:2]]
    left = min(_float(box.get("x_center")) - _float(box.get("width")) / 2 for box in boxes)
    right = max(_float(box.get("x_center")) + _float(box.get("width")) / 2 for box in boxes)
    if source_height >= source_width:
        return left >= 0.04 and right <= 0.96
    crop_width = min(1.0, (source_height * 9 / 16) / source_width)
    safe_left = 0.5 - crop_width * 0.45
    safe_right = 0.5 + crop_width * 0.45
    return left >= safe_left and right <= safe_right


def build_multi_speaker_layout(
    *,
    detections: list[dict[str, Any]],
    speaker_timeline: list[dict[str, Any]],
    clip_id: str,
    project_id: str | None,
    clip_start: float,
    duration: float,
    source_width: float,
    source_height: float,
    fps: float,
) -> dict[str, Any]:
    settings = get_settings().multi_speaker_layout
    tracks = consolidate_face_tracks(detections, duration)
    stable = [
        track
        for track in tracks
        if _float(track.get("coverage_ratio")) >= settings.minimum_track_coverage
        and _float(track.get("mean_confidence")) >= settings.minimum_face_confidence
    ]
    associations = associate_speakers(
        stable,
        speaker_timeline,
        clip_start=clip_start,
        clip_duration=duration,
    )
    resolved_associations = [item for item in associations if item.get("face_track_id")]
    speakers = sorted(
        {
            _str(item.get("speaker"))
            for item in speaker_timeline
            if _str(item.get("speaker"))
        }
    )
    max_faces = 0
    counts: dict[float, int] = {}
    for detection in detections:
        timestamp = round(_float(detection.get("time")), 3)
        counts[timestamp] = counts.get(timestamp, 0) + 1
        max_faces = max(max_faces, counts[timestamp])
    mode = "center_fallback"
    reason = "No stable anonymous face tracks were available."
    fallback_reason: str | None = (
        "sparse_or_low_confidence_faces" if detections else "face_detection_unavailable"
    )
    keyframes: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    regions: list[dict[str, Any]] = []
    active_method = "none"
    if not settings.enabled:
        fallback_reason = "multi_speaker_layout_disabled"
        reason = "Multi-speaker layout is disabled by configuration."
    elif len(stable) == 1:
        mode = "single_face_tracking"
        reason = "One stable anonymous face track supports subject-aware reframing."
        fallback_reason = None
        keyframes = _track_keyframes(stable[0], duration)
    elif len(stable) == 2:
        active_keyframes, active_switches = _active_speaker_keyframes(
            stable,
            associations,
            speaker_timeline,
            clip_start=clip_start,
            duration=duration,
        )
        if (
            settings.enable_active_speaker_focus
            and len(resolved_associations) >= 2
            and active_switches
            and len(active_keyframes) >= 2
        ):
            mode = "active_speaker_focus"
            reason = "Reliable diarized speaker turns map uniquely to anonymous face tracks."
            fallback_reason = None
            keyframes, switches = active_keyframes, active_switches
            active_method = "diarized_segments_with_unique_visibility_association"
        elif settings.preserve_natural_two_face_frame and _naturally_framed(
            stable, source_width, source_height
        ):
            mode = "natural_frame_preserved"
            reason = "Both stable faces already fit safely in the vertical composition."
            fallback_reason = None
            keyframes = [
                {
                    "time": 0.0,
                    "x_center": 0.5,
                    "y_center": 0.46,
                    "width": 1.0,
                    "height": 1.0,
                    "zoom": 1.0,
                    "confidence": 0.8,
                    "source_face_id": "natural_frame",
                    "source_face_track_id": "natural_frame",
                    "speaker_id": None,
                    "active": True,
                },
                {
                    "time": round(duration, 3),
                    "x_center": 0.5,
                    "y_center": 0.46,
                    "width": 1.0,
                    "height": 1.0,
                    "zoom": 1.0,
                    "confidence": 0.8,
                    "source_face_id": "natural_frame",
                    "source_face_track_id": "natural_frame",
                    "speaker_id": None,
                    "active": True,
                },
            ]
        elif settings.prefer_two_speaker_stack:
            mode = "two_speaker_stack"
            reason = "Two stable faces require independent top/bottom crops to remain visible."
            fallback_reason = None
            for index, track in enumerate(stable[:2]):
                regions.append(
                    {
                        "region_id": "top_speaker" if index == 0 else "bottom_speaker",
                        "role": "top" if index == 0 else "bottom",
                        "x": 0,
                        "y": 0 if index == 0 else 960,
                        "width": 1080,
                        "height": 960,
                        "source_face_track_id": track.get("face_track_id"),
                        "source_crop": track.get("average_box"),
                        "crop_keyframes": _track_keyframes(track, duration),
                        "safe_margins": {"headroom": 0.12, "chin": 0.1, "horizontal": 0.08},
                    }
                )
            keyframes = _track_keyframes(stable[0], duration)
    elif len(stable) >= 3 and settings.enable_multi_face_safe_frame:
        mode = "multi_face_safe_frame"
        reason = "Multiple stable participants require a group-safe crop without a tiny grid."
        fallback_reason = None
        keyframes = _multi_face_keyframes(stable[:4], duration)
        regions = [
            {
                "region_id": "multi_face_safe_frame",
                "role": "group",
                "x": 0,
                "y": 0,
                "width": 1080,
                "height": 1920,
                "source_face_track_id": None,
                "source_crop": None,
                "safe_margins": {"headroom": 0.1, "horizontal": 0.06},
            }
        ]

    renderable = mode != "center_fallback" and (
        len(regions) >= 2 if mode == "two_speaker_stack" else len(keyframes) >= 2
    )
    if not renderable and mode != "center_fallback":
        fallback_reason = "invalid_layout_geometry"
        reason = "The selected layout lacked safe render geometry; center fallback is required."
        mode = "center_fallback"
        regions, keyframes, switches = [], [], []
    confidence = round(
        sum(_float(track.get("stability_score")) for track in stable[:4])
        / max(1, min(4, len(stable))),
        3,
    )
    seed = f"{project_id}|{clip_id}|{mode}|{len(stable)}|{len(speakers)}"
    decision_id = "layout_" + hashlib.sha256(seed.encode()).hexdigest()[:16]
    participants = []
    association_by_track = {
        _str(item.get("face_track_id")): item for item in resolved_associations
    }
    for track in stable[:4]:
        association = association_by_track.get(_str(track.get("face_track_id")), {})
        participants.append(
            {
                "face_track_id": track.get("face_track_id"),
                "speaker_id": association.get("speaker_id"),
                "association_confidence": association.get("confidence"),
                "importance_score": track.get("stability_score"),
                "stability_score": track.get("stability_score"),
                "visibility_ratio": track.get("coverage_ratio"),
                "speaking_segments": association.get("supporting_segments") or [],
                "warnings": track.get("warnings") or [],
            }
        )
    warnings = []
    if not speaker_timeline:
        warnings.append("Diarization was unavailable; no active-speaker claim was made.")
    elif not resolved_associations:
        warnings.append("Speaker labels existed, but face association was not uniquely supported.")
    if mode == "two_speaker_stack":
        warnings.append("Both faces are shown continuously; no active-speaker identity is claimed.")
    contract: dict[str, Any] = {
        "version": "2",
        "layout_decision_id": decision_id,
        "clip_id": clip_id,
        "project_id": project_id,
        "created_at": datetime.now(UTC).isoformat(),
        "input_analysis": {
            "detected_face_count": max_faces,
            "stable_face_count": len(stable),
            "tracked_face_ids": [track.get("face_track_id") for track in stable],
            "speaker_count": len(speakers),
            "speaker_ids": speakers,
            "diarization_available": bool(speaker_timeline),
            "face_tracking_available": bool(stable),
            "active_speaker_evidence_available": bool(resolved_associations),
            "source_width": source_width,
            "source_height": source_height,
            "source_aspect_ratio": round(source_width / source_height, 4)
            if source_height
            else None,
            "confidence": confidence,
            "warnings": list(warnings),
        },
        "decision": {
            "mode": mode,
            "reason": reason,
            "confidence": confidence,
            "fallback_reason": fallback_reason,
            "anonymous_tracking_only": True,
            "active_speaker_method": active_method,
            "switching_policy": "minimum_hold_with_hysteresis",
        },
        "mode": mode,
        "participants": participants,
        "speaker_face_associations": associations,
        "layout_regions": regions,
        "crop_keyframes": keyframes,
        "speaker_switches": switches,
        "smoothing": {
            "method": "confidence_weighted_exponential_moving_average",
            "ema_alpha": 0.35,
            "ema_alpha_range": [0.2, 0.45],
            "max_movement_per_second": settings.max_crop_movement_per_second,
            "max_zoom_change_per_second": settings.max_zoom_change_per_second,
            "minimum_hold_seconds": settings.minimum_speaker_hold_seconds,
            "switch_hysteresis_seconds": settings.switch_hysteresis_seconds,
            "missing_detection_hold_seconds": settings.missing_detection_hold_seconds,
            "interpolation_max_gap_seconds": settings.interpolation_max_gap_seconds,
            "position_dead_zone": 0.006,
        },
        "render_plan": {
            "renderable": renderable,
            "output_width": 1080,
            "output_height": 1920,
            "fps": fps,
            "layout_filter_type": "split_crop_vstack"
            if mode == "two_speaker_stack"
            else "dynamic_crop"
            if renderable
            else "center_crop",
            "segment_count": max(1, len(switches) + 1),
            "expected_duration": duration,
            "validation_required": settings.validation_required,
            "warnings": [],
        },
        "validation": {
            "applied": False,
            "applied_mode": None,
            "rendered_regions": 0,
            "rendered_switches": 0,
            "sync_passed": None,
            "duration_passed": None,
            "warnings": [],
        },
        "applied_to_render": False,
        "confidence": confidence,
        "fallback_reason": fallback_reason,
        "tracked_faces": [
            {
                "face_id": item.get("face_track_id"),
                "detections": item.get("observation_count"),
                "coverage": item.get("coverage_ratio"),
                "avg_confidence": item.get("mean_confidence"),
                "score": item.get("stability_score"),
            }
            for item in stable[:4]
        ],
        "warnings": warnings,
    }
    return contract

"""Privacy-safe metrics and result contracts for face/motion validation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from math import hypot
from pathlib import Path
from typing import Any

VIDEO_EXTENSIONS = frozenset({".m4v", ".mkv", ".mov", ".mp4", ".webm"})
REPORT_SUBDIRECTORY = Path("work") / "validation_reports" / "face_tracking_motion"
_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_PRIVATE_REPORT_KEYS = frozenset(
    {
        "biometric_data",
        "embeddings",
        "face_images",
        "frame_bytes",
        "frame_data",
        "identity",
        "image_bytes",
        "pixels",
        "raw_frames",
    }
)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


@dataclass(frozen=True)
class FaceMotionValidationThresholdsV1:
    """Deterministic limits used by local validation, not production editing policy."""

    minimum_tracking_coverage_ratio: float = 0.60
    minimum_face_inside_safe_zone_ratio: float = 0.90
    safe_zone_margin_ratio: float = 0.05
    maximum_jitter_score: float = 0.08
    maximum_crop_shift_per_second: float = 0.22
    maximum_duration_delta_seconds: float = 0.15

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FaceMotionValidationResultV1:
    """JSON-safe face tracking and motion validation truth for one inspected clip."""

    project_id: str | None
    clip_id: str | None
    mode: str
    face_sample_used: bool
    real_face_sample_used: bool
    face_tracking_available: bool
    face_count_detected: int
    frames_sampled: int
    tracked_frames: int
    tracking_coverage_ratio: float
    crop_keyframes_present: bool
    motion_effects_present: bool
    face_inside_safe_zone_ratio: float
    jitter_score: float
    max_crop_shift_per_second: float
    face_cutoff_detected: bool
    center_fallback_used: bool
    render_completed: bool
    output_mp4_valid: bool
    passed: bool
    face_crop_safety_evaluated: bool = False
    external_calls_made: bool = False
    raw_frames_stored: bool = False
    contract_version: str = "1"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        json.dumps(result)
        return result


def tracking_coverage_ratio(*, sampled_frames: int, tracked_frames: int) -> float:
    """Return the bounded ratio of sampled frames containing a tracked face."""

    if sampled_frames <= 0:
        return 0.0
    return round(_clamp(tracked_frames / sampled_frames), 4)


def crop_motion_metrics(keyframes: list[dict[str, Any]]) -> dict[str, float]:
    """Measure average crop-center displacement and the largest time-normalized shift."""

    points = sorted(
        (
            (
                _as_float(item.get("time")),
                _as_float(item.get("x_center"), 0.5),
                _as_float(item.get("y_center"), 0.5),
            )
            for item in keyframes
            if isinstance(item, dict)
        ),
        key=lambda item: item[0],
    )
    displacements: list[float] = []
    speeds: list[float] = []
    for previous, current in pairwise(points):
        elapsed = current[0] - previous[0]
        if elapsed <= 0:
            continue
        shift = hypot(current[1] - previous[1], current[2] - previous[2])
        displacements.append(shift)
        speeds.append(shift / elapsed)
    return {
        "jitter_score": round(sum(displacements) / len(displacements), 4)
        if displacements
        else 0.0,
        "max_crop_shift_per_second": round(max(speeds), 4) if speeds else 0.0,
    }


def _interpolated_keyframe(
    keyframes: list[dict[str, Any]], timestamp: float
) -> dict[str, float]:
    points = sorted(
        [item for item in keyframes if isinstance(item, dict)],
        key=lambda item: _as_float(item.get("time")),
    )
    if not points:
        return {"x_center": 0.5, "y_center": 0.5}
    if timestamp <= _as_float(points[0].get("time")):
        return {
            "x_center": _as_float(points[0].get("x_center"), 0.5),
            "y_center": _as_float(points[0].get("y_center"), 0.5),
        }
    for previous, current in pairwise(points):
        start = _as_float(previous.get("time"))
        end = _as_float(current.get("time"))
        if start <= timestamp <= end and end > start:
            progress = (timestamp - start) / (end - start)
            return {
                field_name: _as_float(previous.get(field_name), 0.5)
                + (
                    _as_float(current.get(field_name), 0.5)
                    - _as_float(previous.get(field_name), 0.5)
                )
                * progress
                for field_name in ("x_center", "y_center")
            }
    return {
        "x_center": _as_float(points[-1].get("x_center"), 0.5),
        "y_center": _as_float(points[-1].get("y_center"), 0.5),
    }


def _motion_scale_at(motion_effects: list[dict[str, Any]], timestamp: float) -> float:
    scale = 1.0
    for effect in motion_effects:
        start = _as_float(effect.get("start_time"), _as_float(effect.get("start")))
        end = _as_float(effect.get("end_time"), _as_float(effect.get("end"), start))
        if start <= timestamp <= end:
            scale = max(scale, _clamp(_as_float(effect.get("scale"), 1.0), 1.0, 1.3))
    return scale


def evaluate_face_crop_safety(
    *,
    detections: list[dict[str, Any]],
    crop_keyframes: list[dict[str, Any]],
    source_width: float,
    source_height: float,
    output_width: float = 1080.0,
    output_height: float = 1920.0,
    safe_zone_margin_ratio: float = 0.05,
    cutoff_tolerance_ratio: float = 0.01,
    motion_effects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate normalized face boxes against the renderer's effective crop window."""

    if (
        not detections
        or not crop_keyframes
        or source_width <= 0
        or source_height <= 0
        or output_width <= 0
        or output_height <= 0
    ):
        return {
            "evaluated": False,
            "evaluated_detections": 0,
            "face_inside_safe_zone_ratio": 0.0,
            "face_cutoff_detected": False,
        }

    source_aspect = source_width / source_height
    output_aspect = output_width / output_height
    if source_aspect >= output_aspect:
        base_width = output_aspect / source_aspect
        base_height = 1.0
    else:
        base_width = 1.0
        base_height = source_aspect / output_aspect

    safe_count = 0
    cutoff_detected = False
    evaluated = 0
    for detection in detections:
        timestamp = _as_float(detection.get("time"))
        crop = _interpolated_keyframe(crop_keyframes, timestamp)
        left = _clamp(crop["x_center"] - base_width / 2, 0.0, 1.0 - base_width)
        top = _clamp(crop["y_center"] - base_height * 0.43, 0.0, 1.0 - base_height)
        scale = _motion_scale_at(motion_effects or [], timestamp)
        view_width = base_width / scale
        view_height = base_height / scale
        view_left = left + (base_width - view_width) / 2
        view_top = top + (base_height - view_height) / 2
        view_right = view_left + view_width
        view_bottom = view_top + view_height

        face_width = max(0.0, _as_float(detection.get("width")))
        face_height = max(0.0, _as_float(detection.get("height")))
        face_left = _as_float(detection.get("x_center"), 0.5) - face_width / 2
        face_right = _as_float(detection.get("x_center"), 0.5) + face_width / 2
        face_top = _as_float(detection.get("y_center"), 0.5) - face_height / 2
        face_bottom = _as_float(detection.get("y_center"), 0.5) + face_height / 2
        margin_x = view_width * _clamp(safe_zone_margin_ratio, 0.0, 0.4)
        margin_y = view_height * _clamp(safe_zone_margin_ratio, 0.0, 0.4)
        tolerance_x = view_width * max(0.0, cutoff_tolerance_ratio)
        tolerance_y = view_height * max(0.0, cutoff_tolerance_ratio)

        inside_safe_zone = bool(
            face_left >= view_left + margin_x
            and face_right <= view_right - margin_x
            and face_top >= view_top + margin_y
            and face_bottom <= view_bottom - margin_y
        )
        if inside_safe_zone:
            safe_count += 1
        if (
            face_left < view_left - tolerance_x
            or face_right > view_right + tolerance_x
            or face_top < view_top - tolerance_y
            or face_bottom > view_bottom + tolerance_y
        ):
            cutoff_detected = True
        evaluated += 1

    return {
        "evaluated": evaluated > 0,
        "evaluated_detections": evaluated,
        "face_inside_safe_zone_ratio": round(safe_count / evaluated, 4) if evaluated else 0.0,
        "face_cutoff_detected": cutoff_detected,
    }


def fallback_is_consistent(
    *, face_tracking_available: bool, face_count_detected: int, center_fallback_used: bool
) -> bool:
    """Require an honest center fallback when usable face tracking is absent."""

    if not face_tracking_available or face_count_detected <= 0:
        return center_fallback_used
    return not center_fallback_used


def validate_project_id(project_id: str) -> str | None:
    if not project_id:
        return "project id is required"
    if not _PROJECT_ID_PATTERN.fullmatch(project_id):
        return "project id may contain only letters, numbers, underscores, and hyphens"
    return None


def validate_local_face_path(
    path: str | Path,
    *,
    rights_confirmed: bool,
) -> tuple[Path | None, list[str]]:
    """Validate an explicitly supplied local video without discovering other user media."""

    raw = str(path).strip()
    errors: list[str] = []
    if "://" in raw or raw.lower().startswith("file:") or raw.startswith(("\\\\", "//")):
        errors.append("local face file must not be a URL, file URI, or network path")
        return None, errors
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        errors.append("local face file must be an absolute local path")
    if candidate.suffix.lower() not in VIDEO_EXTENSIONS:
        errors.append("local face file must use a supported video extension")
    if any(part.lower() in {".git", ".venv", ".next", "node_modules"} for part in candidate.parts):
        errors.append("local face file cannot come from a generated or repository-internal folder")
    if not candidate.exists():
        errors.append("local face file does not exist")
    elif not candidate.is_file():
        errors.append("local face path is not a file")
    if not rights_confirmed:
        errors.append("local face validation requires explicit --confirm-rights confirmation")
    if errors:
        return None, errors
    try:
        return candidate.resolve(strict=True), []
    except OSError as exc:
        return None, [f"local face file could not be resolved: {exc}"]


def report_contains_private_frame_data(value: Any) -> bool:
    """Return true if a report contains raw imagery, identity, or biometric payloads."""

    if isinstance(value, bytes | bytearray | memoryview):
        return True
    if isinstance(value, dict):
        return any(
            str(key).lower() in _PRIVATE_REPORT_KEYS or report_contains_private_frame_data(item)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple):
        return any(report_contains_private_frame_data(item) for item in value)
    return False


def write_face_motion_report(
    result: FaceMotionValidationResultV1,
    *,
    workspace_root: Path,
    report_dir: Path | None = None,
    details: dict[str, Any] | None = None,
) -> Path:
    """Atomically write metrics beneath ``work/validation_reports`` only."""

    workspace = workspace_root.resolve()
    allowed_root = (workspace / "work" / "validation_reports").resolve()
    selected_destination = report_dir or workspace / REPORT_SUBDIRECTORY
    if not selected_destination.is_absolute():
        selected_destination = workspace / selected_destination
    destination = selected_destination.resolve()
    if not destination.is_relative_to(allowed_root):
        raise ValueError(f"report directory must be under {allowed_root}")
    payload: dict[str, Any] = {"face_motion_validation_result_v1": result.to_dict()}
    if details:
        payload["details"] = details
    if report_contains_private_frame_data(payload):
        raise ValueError("face/motion reports cannot contain raw frames or biometric identity data")
    json.dumps(payload)
    destination.mkdir(parents=True, exist_ok=True)
    safe_mode = re.sub(r"[^a-z0-9_-]+", "_", result.mode.lower()).strip("_") or "unknown"
    path = destination / f"face_motion_validation_{safe_mode}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def face_plan_from_timeline(timeline: dict[str, Any]) -> dict[str, Any]:
    metadata = _as_dict(timeline.get("metadata"))
    editing = _as_dict(metadata.get("editing_v2"))
    for value in (
        metadata.get("multi_speaker_layout_v2"),
        metadata.get("face_tracking_plan"),
        editing.get("multi_speaker_layout_v2"),
        editing.get("face_tracking_plan"),
    ):
        if isinstance(value, dict):
            return value
    return {}


def motion_from_timeline(timeline: dict[str, Any]) -> dict[str, Any]:
    metadata = _as_dict(timeline.get("metadata"))
    editing = _as_dict(metadata.get("editing_v2"))
    for value in (
        metadata.get("motion_intelligence_v2"),
        editing.get("motion_intelligence_v2"),
    ):
        if isinstance(value, dict):
            return value
    return {}


def motion_effects_from_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    plan = _as_dict(contract.get("effect_plan"))
    return [item for item in _as_list(plan.get("effects")) if isinstance(item, dict)]

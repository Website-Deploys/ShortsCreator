"""Privacy-safe contracts and metrics for multi-speaker layout validation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from olympus.validation.face_motion import (
    crop_motion_metrics,
    evaluate_face_crop_safety,
    report_contains_private_frame_data,
)

REPORT_SUBDIRECTORY = Path("work") / "validation_reports" / "multi_speaker_layout"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


@dataclass(frozen=True)
class MultiSpeakerLayoutValidationThresholdsV1:
    """Deterministic validator limits, separate from production editing policy."""

    minimum_speaker_region_coverage_ratio: float = 0.95
    minimum_face_inside_region_ratio: float = 0.90
    maximum_layout_jitter_score: float = 0.08
    maximum_region_shift_per_second: float = 0.22
    maximum_duration_delta_seconds: float = 0.15

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MultiSpeakerLayoutValidationResultV1:
    """JSON-safe truth for one synthetic, local, or persisted layout inspection."""

    project_id: str | None
    clip_id: str | None
    mode: str
    real_multi_speaker_sample_used: bool
    synthetic_sample_used: bool
    speaker_signals_available: bool
    face_signals_available: bool
    detected_speaker_count: int
    expected_speaker_count: int
    layout_strategy: str
    active_speaker_switches: int
    frames_sampled: int
    layout_regions_present: bool
    speaker_region_coverage_ratio: float
    face_inside_region_ratio: float
    subject_cutoff_detected: bool
    layout_jitter_score: float
    max_region_shift_per_second: float
    wrong_speaker_focus_warnings: list[str]
    fallback_used: bool
    fallback_reason: str | None
    render_completed: bool
    output_mp4_valid: bool
    passed: bool
    subject_region_safety_evaluated: bool = False
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


def speaker_region_coverage_ratio(
    *,
    expected_speaker_count: int,
    region_counts_by_frame: list[int],
) -> float:
    """Return the average fraction of expected layout regions present per sampled frame."""

    if expected_speaker_count <= 0 or not region_counts_by_frame:
        return 0.0
    coverage = sum(
        min(expected_speaker_count, max(0, count)) / expected_speaker_count
        for count in region_counts_by_frame
    ) / len(region_counts_by_frame)
    return round(min(1.0, max(0.0, coverage)), 4)


def layout_motion_metrics(layout_regions: list[dict[str, Any]]) -> dict[str, float]:
    """Measure average crop displacement and maximum shift across all layout regions."""

    metrics = [
        crop_motion_metrics(
            [
                item
                for item in _as_list(region.get("crop_keyframes"))
                if isinstance(item, dict)
            ]
        )
        for region in layout_regions
        if isinstance(region, dict)
    ]
    return {
        "layout_jitter_score": round(
            sum(item["jitter_score"] for item in metrics) / len(metrics), 4
        )
        if metrics
        else 0.0,
        "max_region_shift_per_second": round(
            max((item["max_crop_shift_per_second"] for item in metrics), default=0.0),
            4,
        ),
    }


def active_speaker_switch_count(switches: list[dict[str, Any]]) -> int:
    """Count genuine focus changes without persisting speaker labels."""

    return sum(
        1
        for switch in switches
        if isinstance(switch, dict)
        and switch.get("from_speaker")
        and switch.get("to_speaker")
        and switch.get("from_speaker") != switch.get("to_speaker")
    )


def evaluate_assigned_subject_regions(
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate anonymous subject boxes against their assigned top/bottom crop regions."""

    evaluated = 0
    safe = 0.0
    cutoff = False
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        result = evaluate_face_crop_safety(
            detections=[
                item
                for item in _as_list(assignment.get("detections"))
                if isinstance(item, dict)
            ],
            crop_keyframes=[
                item
                for item in _as_list(assignment.get("crop_keyframes"))
                if isinstance(item, dict)
            ],
            source_width=_as_float(assignment.get("source_width")),
            source_height=_as_float(assignment.get("source_height")),
            output_width=_as_float(assignment.get("region_width"), 1080.0),
            output_height=_as_float(assignment.get("region_height"), 960.0),
            safe_zone_margin_ratio=_as_float(
                assignment.get("safe_zone_margin_ratio"), 0.05
            ),
        )
        count = int(result.get("evaluated_detections") or 0)
        evaluated += count
        safe += _as_float(result.get("face_inside_safe_zone_ratio")) * count
        cutoff = cutoff or result.get("face_cutoff_detected") is True
    return {
        "evaluated": evaluated > 0,
        "evaluated_detections": evaluated,
        "face_inside_region_ratio": round(safe / evaluated, 4) if evaluated else 0.0,
        "subject_cutoff_detected": cutoff,
    }


def fallback_is_consistent(
    *,
    speaker_signals_available: bool,
    face_signals_available: bool,
    layout_strategy: str,
    fallback_used: bool,
    fallback_reason: str | None,
) -> bool:
    """Reject silent fallback and active-speaker claims without speaker evidence."""

    if not face_signals_available:
        return fallback_used and bool(fallback_reason)
    if fallback_used:
        return bool(fallback_reason)
    return speaker_signals_available or layout_strategy != "active_speaker_focus"


def write_multi_speaker_report(
    result: MultiSpeakerLayoutValidationResultV1,
    *,
    workspace_root: Path,
    report_dir: Path | None = None,
    details: dict[str, Any] | None = None,
) -> Path:
    """Atomically write numeric validation truth beneath ``work/validation_reports``."""

    workspace = workspace_root.resolve()
    allowed_root = (workspace / "work" / "validation_reports").resolve()
    selected_destination = report_dir or workspace / REPORT_SUBDIRECTORY
    if not selected_destination.is_absolute():
        selected_destination = workspace / selected_destination
    destination = selected_destination.resolve()
    if not destination.is_relative_to(allowed_root):
        raise ValueError(f"report directory must be under {allowed_root}")
    payload: dict[str, Any] = {"multi_speaker_layout_validation_result_v1": result.to_dict()}
    if details:
        payload["details"] = details
    if report_contains_private_frame_data(payload):
        raise ValueError("multi-speaker reports cannot contain raw frames or biometric data")
    json.dumps(payload)
    destination.mkdir(parents=True, exist_ok=True)
    safe_mode = re.sub(r"[^a-z0-9_-]+", "_", result.mode.lower()).strip("_") or "unknown"
    path = destination / f"multi_speaker_layout_validation_{safe_mode}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path

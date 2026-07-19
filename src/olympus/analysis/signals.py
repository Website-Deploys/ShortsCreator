"""Versioned, JSON-safe contracts for Olympus analysis signal truth."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from olympus.domain.entities.analysis import StageResult, StageStatus


class AnalysisSignalState(StrEnum):
    """Allowed availability states for a normalized analysis signal."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    FALLBACK = "fallback"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class AnalysisSignalStatusV1:
    signal_name: str
    available: bool
    status: AnalysisSignalState
    confidence: float
    provider: str
    fallback_used: bool
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = round(max(0.0, min(1.0, float(self.confidence))), 3)
        if self.status in {
            AnalysisSignalState.UNAVAILABLE,
            AnalysisSignalState.FAILED,
            AnalysisSignalState.SKIPPED,
        }:
            self.available = False
        if self.status is AnalysisSignalState.FALLBACK:
            self.fallback_used = True

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _json_safe(asdict(self)))


@dataclass(slots=True)
class AnalysisTimelineEventV1:
    start_seconds: float
    end_seconds: float
    label: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.start_seconds = round(max(0.0, float(self.start_seconds)), 3)
        self.end_seconds = round(max(self.start_seconds, float(self.end_seconds)), 3)
        self.score = round(max(0.0, min(1.0, float(self.score))), 3)

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _json_safe(asdict(self)))


@dataclass(slots=True)
class AnalysisTimelineSignalV1:
    signal_name: str
    events: list[AnalysisTimelineEventV1]
    confidence: float
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.confidence = round(max(0.0, min(1.0, float(self.confidence))), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_name": self.signal_name,
            "events": [event.to_dict() for event in self.events],
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class AnalysisSignalHealthV1:
    project_id: str
    source_id: str
    created_at: str
    total_signals: int
    available_count: int
    partial_count: int
    fallback_count: int
    unavailable_count: int
    failed_count: int
    signals: list[AnalysisSignalStatusV1]
    warnings: list[str] = field(default_factory=list)
    blockers: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        source_id: str,
        signals: list[AnalysisSignalStatusV1],
    ) -> AnalysisSignalHealthV1:
        counts: dict[AnalysisSignalState, int] = dict.fromkeys(AnalysisSignalState, 0)
        for signal in signals:
            counts[signal.status] += 1
        warnings = [
            f"{signal.signal_name}: {warning}"
            for signal in signals
            for warning in signal.warnings
        ]
        blockers = [
            {
                "signal_name": signal.signal_name,
                "reason": signal.reason or signal.status.value,
            }
            for signal in signals
            if signal.status in {AnalysisSignalState.UNAVAILABLE, AnalysisSignalState.FAILED}
        ]
        return cls(
            project_id=project_id,
            source_id=source_id,
            created_at=datetime.now(UTC).isoformat(),
            total_signals=len(signals),
            available_count=counts[AnalysisSignalState.AVAILABLE],
            partial_count=counts[AnalysisSignalState.PARTIAL],
            fallback_count=counts[AnalysisSignalState.FALLBACK],
            unavailable_count=(
                counts[AnalysisSignalState.UNAVAILABLE] + counts[AnalysisSignalState.SKIPPED]
            ),
            failed_count=counts[AnalysisSignalState.FAILED],
            signals=signals,
            warnings=list(dict.fromkeys(warnings)),
            blockers=blockers,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "source_id": self.source_id,
            "created_at": self.created_at,
            "total_signals": self.total_signals,
            "available_count": self.available_count,
            "partial_count": self.partial_count,
            "fallback_count": self.fallback_count,
            "unavailable_count": self.unavailable_count,
            "failed_count": self.failed_count,
            "signals": [signal.to_dict() for signal in self.signals],
            "warnings": list(self.warnings),
            "blockers": [dict(item) for item in self.blockers],
        }


def build_analysis_signals_v2(
    *,
    project_id: str,
    source_id: str,
    stages: Mapping[str, StageResult],
) -> dict[str, Any]:
    """Build the compact, persisted cross-stage signal view.

    Transcript segments and raw frame data are intentionally not copied. Timeline
    signals remain compact and all larger source data stays in its canonical stage.
    """

    entries: dict[str, dict[str, Any]] = {}
    statuses: list[AnalysisSignalStatusV1] = []

    def add(signal_name: str, entry: dict[str, Any]) -> None:
        normalized = dict(entry)
        raw_status = normalized.get("status")
        if not isinstance(raw_status, dict):
            raise ValueError(f"Signal {signal_name!r} is missing a status contract.")
        status = _status_from_dict(signal_name, raw_status)
        normalized["status"] = status.to_dict()
        entries[signal_name] = normalized
        statuses.append(status)

    transcript = stages.get("speech_transcription")
    add(
        "transcript",
        _stage_entry(
            "transcript",
            transcript,
            provider=str(
                (transcript.data if transcript else {}).get("provider") or "transcription"
            ),
            confidence=_float((transcript.data if transcript else {}).get("confidence"), 0.0),
            metadata={
                "stage_ref": "speech_transcription",
                "word_count": (transcript.data if transcript else {}).get("word_count"),
                "segment_count": len((transcript.data if transcript else {}).get("segments") or []),
            },
        ),
    )

    audio = stages.get("audio_extraction")
    audio_data = audio.data if audio and audio.status is StageStatus.COMPLETED else {}
    add("audio_energy", _embedded_or_stage("audio_energy", audio_data, audio))
    add("silence", _embedded_or_stage("silence", audio_data, audio))

    scene = stages.get("scene_detection")
    scene_data = scene.data if scene and scene.status is StageStatus.COMPLETED else {}
    add("scene_detection", _embedded_or_stage("scene_detection", scene_data, scene))
    add("visual_regions", _embedded_or_stage("visual_regions", scene_data, scene))

    shot = stages.get("shot_detection")
    shot_data = shot.data if shot and shot.status is StageStatus.COMPLETED else {}
    add("shot_detection", _embedded_or_stage("shot_detection", shot_data, shot))
    add("visual_pacing", _embedded_or_stage("visual_pacing", shot_data, shot))

    speaker = stages.get("speaker_segmentation")
    speaker_data = speaker.data if speaker and speaker.status is StageStatus.COMPLETED else {}
    add("speaker_segmentation", _embedded_or_stage("speaker_segmentation", speaker_data, speaker))

    face = stages.get("face_detection")
    face_data = face.data if face and face.status is StageStatus.COMPLETED else {}
    add("face_detection", _embedded_or_stage("face_detection", face_data, face))
    add("face_tracking", _face_tracking_entry(face, face_data))

    ocr = stages.get("ocr")
    ocr_data = ocr.data if ocr and ocr.status is StageStatus.COMPLETED else {}
    add("ocr", _embedded_or_stage("ocr", ocr_data, ocr))

    objects = stages.get("object_detection")
    object_data = objects.data if objects and objects.status is StageStatus.COMPLETED else {}
    add("object_detection", _embedded_or_stage("object_detection", object_data, objects))

    emotion = stages.get("emotion_timeline")
    emotion_data = emotion.data if emotion and emotion.status is StageStatus.COMPLETED else {}
    add("emotion_timeline", _embedded_or_stage("emotion_timeline", emotion_data, emotion))

    health = AnalysisSignalHealthV1.build(
        project_id=project_id,
        source_id=source_id,
        signals=statuses,
    )
    return {
        "contract_version": "analysis_signals_v2",
        "signal_health": health.to_dict(),
        **entries,
    }


def unavailable_signal_entry(
    signal_name: str,
    *,
    provider: str,
    reason: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "status": AnalysisSignalStatusV1(
            signal_name=signal_name,
            available=False,
            status=AnalysisSignalState.UNAVAILABLE,
            confidence=0.0,
            provider=provider,
            fallback_used=False,
            reason=reason,
            warnings=[detail],
            metadata={"detail": detail},
        ).to_dict()
    }


def _embedded_or_stage(
    signal_name: str,
    data: dict[str, Any],
    stage: StageResult | None,
) -> dict[str, Any]:
    embedded = data.get(signal_name)
    if isinstance(embedded, dict) and isinstance(embedded.get("status"), dict):
        return dict(embedded)
    return _stage_entry(signal_name, stage, provider=signal_name)


def _stage_entry(
    signal_name: str,
    stage: StageResult | None,
    *,
    provider: str,
    confidence: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if stage and stage.status is StageStatus.COMPLETED:
        status = AnalysisSignalState.AVAILABLE
        available = True
        reason = None
        warnings: list[str] = []
    elif stage and stage.status is StageStatus.FAILED:
        status = AnalysisSignalState.FAILED
        available = False
        reason = "analysis_failed"
        warnings = [stage.error or stage.reason or "The analysis stage failed."]
    else:
        status = AnalysisSignalState.UNAVAILABLE
        available = False
        reason = _reason_code(stage.reason if stage else None)
        warnings = [stage.reason] if stage and stage.reason else ["Signal stage is unavailable."]
    return {
        "status": AnalysisSignalStatusV1(
            signal_name=signal_name,
            available=available,
            status=status,
            confidence=confidence if available else 0.0,
            provider=provider,
            fallback_used=False,
            reason=reason,
            warnings=warnings,
            metadata={"stage_ref": stage.stage if stage else signal_name, **(metadata or {})},
        ).to_dict()
    }


def _face_tracking_entry(stage: StageResult | None, data: dict[str, Any]) -> dict[str, Any]:
    detections = data.get("detections") or data.get("frames") or data.get("tracks")
    if (
        stage
        and stage.status is StageStatus.COMPLETED
        and isinstance(detections, list)
        and detections
    ):
        timestamped = any(
            isinstance(item, dict)
            and any(key in item for key in ("time", "timestamp", "start", "frame_time"))
            for item in detections
        )
        state = AnalysisSignalState.PARTIAL if timestamped else AnalysisSignalState.UNAVAILABLE
        return {
            "status": AnalysisSignalStatusV1(
                signal_name="face_tracking",
                available=timestamped,
                status=state,
                confidence=_float(data.get("confidence"), 0.5) if timestamped else 0.0,
                provider="face_detection_tracks",
                fallback_used=False,
                reason=None if timestamped else "insufficient_input",
                warnings=(
                    ["Timestamped anonymous face tracks are available for downstream framing."]
                    if timestamped
                    else ["Face detections do not contain timestamped tracks."]
                ),
                metadata={"stage_ref": "face_detection", "identity_data_stored": False},
            ).to_dict()
        }
    return _stage_entry("face_tracking", stage, provider="face_detection_tracks")


def _status_from_dict(signal_name: str, raw: dict[str, Any]) -> AnalysisSignalStatusV1:
    try:
        state = AnalysisSignalState(str(raw.get("status") or "unavailable"))
    except ValueError:
        state = AnalysisSignalState.FAILED
    return AnalysisSignalStatusV1(
        signal_name=signal_name,
        available=bool(raw.get("available")),
        status=state,
        confidence=_float(raw.get("confidence"), 0.0),
        provider=str(raw.get("provider") or "unknown"),
        fallback_used=bool(raw.get("fallback_used")),
        reason=str(raw.get("reason")) if raw.get("reason") else None,
        warnings=[str(item) for item in raw.get("warnings") or []],
        metadata=dict(raw.get("metadata") or {}),
    )


def _reason_code(detail: str | None) -> str:
    text = (detail or "").lower()
    if any(token in text for token in ("transcript", "audio", "source", "input")):
        return "insufficient_input"
    if any(token in text for token in ("binary", "dependency", "opencv", "ffmpeg", "engine")):
        return "dependency_missing"
    return "model_missing"


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)

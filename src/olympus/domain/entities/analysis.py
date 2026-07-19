"""Video understanding entities - the structured output of the Cognitive Engine.

These are technology-free data types. An :class:`Analysis` is the evolving,
persisted understanding of a project's video, composed of one
:class:`StageResult` per pipeline stage.

Honesty is built into the type system: a stage is ``UNAVAILABLE`` (with a
reason) when its analyzer cannot run in the current environment - it never
pretends to have produced output it didn't. ``FAILED`` is reserved for genuine
errors, and is never silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class StageStatus(StrEnum):
    """Status of a single analysis stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"  # honest: analyzer not configured in this environment
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisStatus(StrEnum):
    """Overall status of a project's analysis."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# The ordered pipeline. Order matters: later stages may depend on earlier ones
# (e.g. transcription depends on extracted audio).
STAGE_ORDER: tuple[str, ...] = (
    "video_inspection",
    "audio_extraction",
    "speech_transcription",
    "speaker_segmentation",
    "scene_detection",
    "shot_detection",
    "ocr",
    "face_detection",
    "object_detection",
    "emotion_timeline",
    "signal_health",
    "knowledge_graph",
)

# Human-friendly labels for the UI.
STAGE_LABELS: dict[str, str] = {
    "video_inspection": "Video Inspection",
    "audio_extraction": "Audio Extraction",
    "speech_transcription": "Speech Transcription",
    "speaker_segmentation": "Speaker Segmentation",
    "scene_detection": "Scene Detection",
    "shot_detection": "Shot Detection",
    "ocr": "On-screen Text (OCR)",
    "face_detection": "Face Detection",
    "object_detection": "Object Detection",
    "emotion_timeline": "Emotion Timeline",
    "signal_health": "Signal Health",
    "knowledge_graph": "Knowledge Graph",
}


@dataclass(slots=True)
class StageResult:
    """The result of running one analysis stage."""

    stage: str
    status: StageStatus = StageStatus.PENDING
    version: str = "0"
    progress: float = 0.0
    attempts: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    reason: str | None = None  # explanation for UNAVAILABLE
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            StageStatus.COMPLETED,
            StageStatus.UNAVAILABLE,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
        )

    def summary(self) -> dict[str, Any]:
        """Index-friendly summary (excludes the potentially large ``data``)."""

        return {
            "stage": self.stage,
            "status": self.status.value,
            "version": self.version,
            "progress": self.progress,
            "attempts": self.attempts,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "reason": self.reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.summary(), "data": self.data}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> StageResult:
        return cls(
            stage=raw["stage"],
            status=StageStatus(raw.get("status", "pending")),
            version=str(raw.get("version", "0")),
            progress=float(raw.get("progress", 0.0)),
            attempts=int(raw.get("attempts", 0)),
            started_at=_parse_dt(raw.get("started_at")),
            completed_at=_parse_dt(raw.get("completed_at")),
            error=raw.get("error"),
            reason=raw.get("reason"),
            data=raw.get("data", {}) or {},
        )


@dataclass(slots=True)
class Analysis:
    """A project's complete (and evolving) video understanding."""

    project_id: str
    pipeline_version: str
    status: AnalysisStatus
    created_at: datetime
    updated_at: datetime
    stages: list[StageResult] = field(default_factory=list)

    def stage(self, name: str) -> StageResult | None:
        return next((s for s in self.stages if s.stage == name), None)

    def signals_v2(self) -> dict[str, Any] | None:
        """Return the normalized signal artifact when produced by pipeline V2."""

        result = self.stage("signal_health")
        if result is None or result.status is not StageStatus.COMPLETED:
            return None
        artifact = result.data.get("analysis_signals_v2")
        return artifact if isinstance(artifact, dict) else None

    def signal(self, name: str) -> dict[str, Any] | None:
        """Return one normalized signal entry without requiring it to be available."""

        artifact = self.signals_v2()
        if artifact is None:
            return None
        signal = artifact.get(name)
        return signal if isinstance(signal, dict) else None

    def index(self) -> dict[str, Any]:
        """The lightweight index document (summaries only, no stage data)."""

        return {
            "project_id": self.project_id,
            "pipeline_version": self.pipeline_version,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "stages": [s.summary() for s in self.stages],
        }

    def recompute_status(self) -> AnalysisStatus:
        """Derive overall status from the stages (all terminal -> done)."""

        if any(s.status is StageStatus.RUNNING for s in self.stages):
            return AnalysisStatus.RUNNING
        if self.stages and all(s.is_terminal for s in self.stages):
            if any(s.status is StageStatus.CANCELLED for s in self.stages):
                return AnalysisStatus.CANCELLED
            return AnalysisStatus.COMPLETED
        return self.status


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None

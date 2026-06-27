"""Editing entities - the structured output of the Editing Engine.

Where the Clip Planner decides *what* should be edited (ranked blueprints), the
Editing Engine decides *how* it should be edited: it transforms each approved
blueprint into a real, professional, non-destructive **edit timeline** - the
kind a non-linear editor (Premiere, Resolve, Final Cut) builds internally.

It is **not** a renderer, encoder, exporter, or Short generator. It only produces
the edit decision list. No video is ever touched.

These are technology-free data types, deliberately independent from the other
engines' entities (the Editing Engine consumes their *output*, never their
types). An :class:`EditingAnalysis` is the evolving, persisted set of timelines
for a project, composed of one :class:`EditingStageResult` per pipeline stage.

Honesty is built into the type system exactly as in the other engines: a stage
is ``UNAVAILABLE`` (with a detailed reason) when it lacks the evidence it needs,
and any single decision that cannot be determined is recorded as ``UNKNOWN``
(never guessed). ``FAILED`` is reserved for genuine errors. Every timeline event
carries a start, end, duration, reason, confidence, and the supporting evidence
it was derived from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EditingStageStatus(StrEnum):
    """Status of a single editing stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"  # honest: required evidence not available
    FAILED = "failed"
    CANCELLED = "cancelled"


class EditingStatus(StrEnum):
    """Overall status of a project's editing analysis."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# The ordered editing pipeline. Order matters: each stage builds on the ones
# before it, and the final stage assembles + validates the complete timelines.
EDITING_STAGE_ORDER: tuple[str, ...] = (
    "timeline_initialization",
    "speech_cleanup",
    "jump_cut_detection",
    "silence_detection",
    "subtitle_segmentation",
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
    "timeline_validation",
)

# Human-friendly labels for the UI.
EDITING_STAGE_LABELS: dict[str, str] = {
    "timeline_initialization": "Timeline Initialization",
    "speech_cleanup": "Speech Cleanup",
    "jump_cut_detection": "Jump Cut Detection",
    "silence_detection": "Silence Detection",
    "subtitle_segmentation": "Subtitle Segmentation",
    "caption_timing": "Caption Timing",
    "caption_layout": "Caption Layout",
    "zoom_planner": "Zoom Planner",
    "pan_planner": "Pan Planner",
    "crop_planner": "Crop Planner",
    "hook_enhancement": "Hook Enhancement",
    "retention_planner": "Retention Planner",
    "music_planner": "Music Planner",
    "transition_planner": "Transition Planner",
    "broll_planner": "B-roll Planner",
    "timeline_validation": "Timeline Validation",
}


@dataclass(slots=True)
class EditingStageResult:
    """The result of running one editing stage.

    ``data`` holds the stage's structured output, organized per clip. By
    convention every timeline event inside ``data`` carries ``start``/``end``/
    ``duration`` (clip-relative seconds), a ``reason``, a ``confidence``, and the
    ``evidence`` it was derived from - no cut, zoom, caption, or marker is ever
    produced without the real upstream signal behind it.
    """

    stage: str
    status: EditingStageStatus = EditingStageStatus.PENDING
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
            EditingStageStatus.COMPLETED,
            EditingStageStatus.UNAVAILABLE,
            EditingStageStatus.FAILED,
            EditingStageStatus.CANCELLED,
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
    def from_dict(cls, raw: dict[str, Any]) -> EditingStageResult:
        return cls(
            stage=raw["stage"],
            status=EditingStageStatus(raw.get("status", "pending")),
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
class EditingAnalysis:
    """A project's complete (and evolving) set of edit timelines."""

    project_id: str
    pipeline_version: str
    status: EditingStatus
    created_at: datetime
    updated_at: datetime
    stages: list[EditingStageResult] = field(default_factory=list)

    def stage(self, name: str) -> EditingStageResult | None:
        return next((s for s in self.stages if s.stage == name), None)

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


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None

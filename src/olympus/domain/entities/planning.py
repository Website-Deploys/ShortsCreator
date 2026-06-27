"""Clip planning entities - the structured output of the Clip Planner.

Where the Cognitive Engine understands *what exists*, the Story Engine *what the
video is saying*, and the Virality Engine *how likely each moment is to perform*,
the Clip Planner decides **what should be edited**: it produces professional
editing blueprints - one per proposed Short - consuming the three upstream
engines' outputs.

It is **not** an editing, rendering, or clip-generation engine. It only decides
*what* a future Editing Engine should produce. No video is touched.

These are technology-free data types, deliberately independent from the other
engines' entities (the Clip Planner consumes their *output*, never their types).
A :class:`ClipPlanningAnalysis` is the evolving, persisted plan set for a
project, composed of one :class:`PlanningStageResult` per pipeline stage.

Honesty is built into the type system exactly as in the other engines: a stage
is ``UNAVAILABLE`` (with a detailed reason) when it lacks the evidence it needs,
and the planner returns **zero clips with an explanation** rather than forcing
low-quality plans. ``FAILED`` is reserved for genuine errors. Every plan and
decision carries confidence and the supporting evidence it was derived from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class PlanningStageStatus(StrEnum):
    """Status of a single clip-planning stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"  # honest: required evidence not available
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanningStatus(StrEnum):
    """Overall status of a project's clip planning."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# The ordered clip-planning pipeline. Order matters: each stage builds on the
# one before it (candidates -> refined boundaries -> scores -> de-duplicated ->
# blueprints -> ranked -> summarized).
PLANNING_STAGE_ORDER: tuple[str, ...] = (
    "candidate_generation",
    "boundary_refinement",
    "clip_scoring",
    "duplicate_detection",
    "blueprint_generation",
    "ranking",
    "planning_summary",
)

# Human-friendly labels for the UI.
PLANNING_STAGE_LABELS: dict[str, str] = {
    "candidate_generation": "Candidate Generation",
    "boundary_refinement": "Boundary Refinement",
    "clip_scoring": "Clip Scoring",
    "duplicate_detection": "Duplicate Detection",
    "blueprint_generation": "Blueprint Generation",
    "ranking": "Ranking",
    "planning_summary": "Planning Summary",
}


@dataclass(slots=True)
class PlanningStageResult:
    """The result of running one clip-planning stage.

    ``data`` holds the stage's structured output. By convention every plan and
    decision inside ``data`` carries a ``confidence`` and the ``evidence`` it was
    derived from - no clip boundary, score, or recommendation is ever produced
    without the real upstream signals behind it.
    """

    stage: str
    status: PlanningStageStatus = PlanningStageStatus.PENDING
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
            PlanningStageStatus.COMPLETED,
            PlanningStageStatus.UNAVAILABLE,
            PlanningStageStatus.FAILED,
            PlanningStageStatus.CANCELLED,
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
    def from_dict(cls, raw: dict[str, Any]) -> PlanningStageResult:
        return cls(
            stage=raw["stage"],
            status=PlanningStageStatus(raw.get("status", "pending")),
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
class ClipPlanningAnalysis:
    """A project's complete (and evolving) set of editing plans."""

    project_id: str
    pipeline_version: str
    status: PlanningStatus
    created_at: datetime
    updated_at: datetime
    stages: list[PlanningStageResult] = field(default_factory=list)

    def stage(self, name: str) -> PlanningStageResult | None:
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

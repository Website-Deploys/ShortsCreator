"""Story understanding entities - the structured output of the Story Engine.

Where the Cognitive Engine understands *what exists* in a video, the Story
Engine understands *what the video is trying to say*: where it starts, how it
develops, where it changes, where emotion shifts, where information becomes
valuable, where context matters, and where earlier setups pay off.

These are technology-free data types and are deliberately independent from the
Cognitive Engine's entities (the Story Engine consumes the Cognitive Engine's
*output*, but does not share its types). A :class:`StoryAnalysis` is the
evolving, persisted narrative understanding of a project, composed of one
:class:`StoryStageResult` per story stage.

Honesty is built into the type system, exactly as in the Cognitive Engine: a
stage is ``UNAVAILABLE`` (with a reason) when it lacks the inputs it needs
(most stages need a transcript) - it never fabricates a narrative it could not
derive. ``FAILED`` is reserved for genuine errors and is never silently skipped.
Every conclusion a stage records carries a confidence score and supporting
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class StoryStageStatus(StrEnum):
    """Status of a single story-analysis stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"  # honest: required inputs/model not available
    FAILED = "failed"
    CANCELLED = "cancelled"


class StoryStatus(StrEnum):
    """Overall status of a project's story analysis."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# The ordered story pipeline. Order matters: later stages build on earlier ones
# (e.g. the narrative arc reads narrative segmentation; the graph/summary
# aggregate everything before them).
STORY_STAGE_ORDER: tuple[str, ...] = (
    "narrative_segmentation",
    "hook_detection",
    "topic_segmentation",
    "narrative_arc",
    "payoff_detection",
    "emotional_turning_points",
    "information_density",
    "context_dependencies",
    "story_analysis_v2",
    "story_graph",
    "story_summary",
)

# Human-friendly labels for the UI.
STORY_STAGE_LABELS: dict[str, str] = {
    "narrative_segmentation": "Narrative Segmentation",
    "hook_detection": "Hook Detection",
    "topic_segmentation": "Topic Segmentation",
    "narrative_arc": "Narrative Arc",
    "payoff_detection": "Payoff Detection",
    "emotional_turning_points": "Emotional Turning Points",
    "information_density": "Information Density",
    "context_dependencies": "Context Dependencies",
    "story_analysis_v2": "Story Analysis V2",
    "story_graph": "Story Graph",
    "story_summary": "Story Summary",
}


@dataclass(slots=True)
class StoryStageResult:
    """The result of running one story-analysis stage.

    ``data`` holds the stage's structured conclusions. By convention every
    conclusion inside ``data`` carries its own ``confidence`` (0-1) and the
    evidence (supporting transcript excerpts / timestamps) it was derived from.
    """

    stage: str
    status: StoryStageStatus = StoryStageStatus.PENDING
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
            StoryStageStatus.COMPLETED,
            StoryStageStatus.UNAVAILABLE,
            StoryStageStatus.FAILED,
            StoryStageStatus.CANCELLED,
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
    def from_dict(cls, raw: dict[str, Any]) -> StoryStageResult:
        return cls(
            stage=raw["stage"],
            status=StoryStageStatus(raw.get("status", "pending")),
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
class StoryAnalysis:
    """A project's complete (and evolving) narrative understanding."""

    project_id: str
    pipeline_version: str
    status: StoryStatus
    created_at: datetime
    updated_at: datetime
    stages: list[StoryStageResult] = field(default_factory=list)

    def stage(self, name: str) -> StoryStageResult | None:
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

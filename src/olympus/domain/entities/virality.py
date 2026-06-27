"""Virality understanding entities - the structured output of the Virality Engine.

Where the Cognitive Engine understands *what exists* and the Story Engine
understands *what the video is saying*, the Virality Engine answers a single
question for every part of the video:

    "How likely is this moment to perform well as a short-form video, and why?"

It is **not** an editing, clip-generation, or recommendation engine. It only
produces an explainable assessment of viral potential, consuming the Cognitive
and Story engines' outputs.

These are technology-free data types, deliberately independent from the other
engines' entities (the Virality Engine consumes their *output*, never their
types). A :class:`ViralityAnalysis` is the evolving, persisted assessment of a
project, composed of one :class:`ViralityStageResult` per analyzer.

Honesty is built into the type system exactly as in the other engines: a stage
is ``UNAVAILABLE`` (with a detailed reason) when it lacks the evidence it needs -
it never fabricates a score, confidence, or conclusion. ``FAILED`` is reserved
for genuine errors. Every conclusion carries a confidence score, the supporting
evidence it was derived from, and its limitations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ViralityStageStatus(StrEnum):
    """Status of a single virality-analysis stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"  # honest: required evidence not available
    FAILED = "failed"
    CANCELLED = "cancelled"


class ViralityStatus(StrEnum):
    """Overall status of a project's virality analysis."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# The ordered virality pipeline. Order matters: aggregate analyzers (shareability,
# comment potential) and the final summary build on the per-signal analyzers
# before them.
VIRALITY_STAGE_ORDER: tuple[str, ...] = (
    "hook_strength",
    "curiosity_gap",
    "emotional_impact",
    "conflict",
    "novelty",
    "information_value",
    "audience_relatability",
    "momentum",
    "retention",
    "replay_potential",
    "shareability",
    "comment_potential",
    "platform_fit",
    "audience_fit",
    "virality_summary",
)

# Human-friendly labels for the UI.
VIRALITY_STAGE_LABELS: dict[str, str] = {
    "hook_strength": "Hook Strength",
    "curiosity_gap": "Curiosity Gap",
    "emotional_impact": "Emotional Impact",
    "conflict": "Conflict",
    "novelty": "Novelty",
    "information_value": "Information Value",
    "audience_relatability": "Audience Relatability",
    "momentum": "Momentum",
    "retention": "Retention",
    "replay_potential": "Replay Potential",
    "shareability": "Shareability",
    "comment_potential": "Comment Potential",
    "platform_fit": "Platform Fit",
    "audience_fit": "Audience Fit",
    "virality_summary": "Virality Summary",
}


@dataclass(slots=True)
class ViralityStageResult:
    """The result of running one virality-analysis stage.

    ``data`` holds the stage's structured conclusions. By convention a scoring
    stage records a ``score`` (0-1), a ``confidence`` (0-1), an ``evidence`` list,
    and a ``limitations`` string - so no number is ever presented without the
    real signals behind it and an honest statement of what it cannot know.
    """

    stage: str
    status: ViralityStageStatus = ViralityStageStatus.PENDING
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
            ViralityStageStatus.COMPLETED,
            ViralityStageStatus.UNAVAILABLE,
            ViralityStageStatus.FAILED,
            ViralityStageStatus.CANCELLED,
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
    def from_dict(cls, raw: dict[str, Any]) -> ViralityStageResult:
        return cls(
            stage=raw["stage"],
            status=ViralityStageStatus(raw.get("status", "pending")),
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
class ViralityAnalysis:
    """A project's complete (and evolving) virality assessment."""

    project_id: str
    pipeline_version: str
    status: ViralityStatus
    created_at: datetime
    updated_at: datetime
    stages: list[ViralityStageResult] = field(default_factory=list)

    def stage(self, name: str) -> ViralityStageResult | None:
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

"""Clip-planning contracts (ports): the repository and the planner-stage interface.

These let the Clip Planner pipeline persist its plans and run isolated,
replaceable stages without binding to any concrete technique or storage
technology. Each planning stage is completely independent: it never imports
another stage's implementation and only communicates through this structured
context.

The Clip Planner *consumes only* the Cognitive, Story, and Virality engines'
outputs. Those dependencies are expressed here as three read-only inputs - the
cognitive :class:`Analysis`, the :class:`StoryAnalysis`, and the
:class:`ViralityAnalysis` - surfaced through small accessors so stages never need
to know how the upstream engines store their results. The Clip Planner never
modifies them.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis, StageStatus
from olympus.domain.entities.planning import (
    ClipPlanningAnalysis,
    PlanningStageResult,
    PlanningStageStatus,
)
from olympus.domain.entities.project import Project
from olympus.domain.entities.story import StoryAnalysis, StoryStageStatus
from olympus.domain.entities.virality import ViralityAnalysis, ViralityStageStatus


class PlanningRepository(abc.ABC):
    """Durable persistence for a project's clip planning.

    Mirrors the other engines' repository contracts: an index plus one artifact
    per stage, so stages are individually rerunnable and work is never lost. A
    database-backed implementation can later replace the storage-backed one
    behind this same contract.
    """

    @abc.abstractmethod
    async def load(self, project_id: str) -> ClipPlanningAnalysis | None:
        """Load the clip planning (index + all stage artifacts), or None."""

    @abc.abstractmethod
    async def save_index(self, analysis: ClipPlanningAnalysis) -> None:
        """Persist the index (overall status + per-stage summaries)."""

    @abc.abstractmethod
    async def save_stage(self, project_id: str, result: PlanningStageResult) -> None:
        """Persist a single stage's full result (called after every stage)."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete all planning artifacts for a project (idempotent)."""


@dataclass(slots=True)
class PlanningStageContext:
    """Everything a planning stage needs to do its work.

    Args:
        project: The project under analysis.
        storage: Storage backend (for any large artifacts a stage may persist).
        analysis: The Cognitive Engine's output for this project, if present.
        story: The Story Engine's output for this project, if present.
        virality: The Virality Engine's output for this project, if present.
        results: Prior *planning* stages' results, so a stage can build on them.
    """

    project: Project
    storage: StoragePort
    analysis: Analysis | None = None
    story: StoryAnalysis | None = None
    virality: ViralityAnalysis | None = None
    results: dict[str, PlanningStageResult] = field(default_factory=dict)

    # -- Cognitive Engine accessors -------------------------------------------
    def cognitive_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed cognitive stage's data, or ``None``."""

        if self.analysis is None:
            return None
        result = self.analysis.stage(stage)
        if result and result.status is StageStatus.COMPLETED:
            return result.data
        return None

    def cognitive_signal(self, signal: str) -> dict[str, Any] | None:
        """Return normalized signal truth, including unavailable/fallback status."""

        return self.analysis.signal(signal) if self.analysis is not None else None

    def transcript_segments(self) -> list[dict[str, Any]] | None:
        """Return the transcript's segments if available, else None."""

        transcript = self.cognitive_data("speech_transcription")
        if not transcript:
            return None
        segments = transcript.get("segments")
        return segments if isinstance(segments, list) and segments else None

    def video_duration(self) -> float | None:
        """Best available video duration (cognitive inspection, else project)."""

        inspection = self.cognitive_data("video_inspection")
        if inspection and isinstance(inspection.get("duration_seconds"), int | float):
            return float(inspection["duration_seconds"])
        if self.project.duration_seconds:
            return float(self.project.duration_seconds)
        return None

    def fps(self) -> float:
        """Best available frame rate (cognitive inspection, else 30.0 default)."""

        inspection = self.cognitive_data("video_inspection")
        if inspection and isinstance(inspection.get("fps"), int | float) and inspection["fps"]:
            return float(inspection["fps"])
        return 30.0

    # -- Story Engine accessors -----------------------------------------------
    def story_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed story stage's data, or ``None``."""

        if self.story is None:
            return None
        result = self.story.stage(stage)
        if result and result.status is StoryStageStatus.COMPLETED:
            return result.data
        return None

    # -- Virality Engine accessors --------------------------------------------
    def virality_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed virality stage's data, or ``None``."""

        if self.virality is None:
            return None
        result = self.virality.stage(stage)
        if result and result.status is ViralityStageStatus.COMPLETED:
            return result.data
        return None

    # -- Planning-stage accessors ---------------------------------------------
    def planning_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed prior *planning* stage's data, or ``None``."""

        result = self.results.get(stage)
        if result and result.status is PlanningStageStatus.COMPLETED:
            return result.data
        return None


@dataclass(slots=True)
class PlanningOutcome:
    """What a planning stage returns: an honest status, plus data or a reason."""

    status: PlanningStageStatus
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @classmethod
    def completed(cls, data: dict[str, Any]) -> PlanningOutcome:
        return cls(status=PlanningStageStatus.COMPLETED, data=data)

    @classmethod
    def unavailable(cls, reason: str) -> PlanningOutcome:
        return cls(status=PlanningStageStatus.UNAVAILABLE, reason=reason)

    @classmethod
    def failed(cls, reason: str) -> PlanningOutcome:
        return cls(status=PlanningStageStatus.FAILED, reason=reason)


# A progress reporter a stage may call with a value in [0, 1].
PlanningProgressReporter = Callable[[float], None]


class PlanningAnalyzer(abc.ABC):
    """One isolated, replaceable clip-planning stage."""

    #: Stable stage identifier (must be one of PLANNING_STAGE_ORDER).
    name: str = ""
    #: Bump when the stage's behaviour changes, to trigger a rerun on resume.
    version: str = "1"
    #: Planning stage names this stage depends on (must run after them).
    depends_on: tuple[str, ...] = ()

    @abc.abstractmethod
    async def analyze(
        self, ctx: PlanningStageContext, report: PlanningProgressReporter
    ) -> PlanningOutcome:
        """Run the stage. Return an outcome; raise only on genuine errors.

        Implementations MUST NOT fabricate output: when the required evidence is
        missing, return ``PlanningOutcome.unavailable(reason)`` with a detailed
        reason, and never force a clip into existence. Every plan/decision placed
        in ``data`` must carry confidence and the supporting evidence behind it.
        """

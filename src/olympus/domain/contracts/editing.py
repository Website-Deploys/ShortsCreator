"""Editing contracts (ports): the repository and the editing-stage interface.

These let the Editing pipeline persist its timelines and run isolated,
replaceable stages without binding to any concrete technique or storage
technology. Each editing stage is completely independent: it never imports
another stage's implementation and only communicates through this structured
context.

The Editing Engine *consumes only* the Cognitive, Story, Virality, and Clip
Planner outputs. Those dependencies are expressed here as four read-only inputs,
surfaced through small accessors so stages never need to know how the upstream
engines store their results. The Editing Engine never modifies them, and it
never renders, encodes, or exports anything.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis, StageStatus
from olympus.domain.entities.editing import (
    EditingAnalysis,
    EditingStageResult,
    EditingStageStatus,
)
from olympus.domain.entities.planning import ClipPlanningAnalysis, PlanningStageStatus
from olympus.domain.entities.project import Project
from olympus.domain.entities.story import StoryAnalysis, StoryStageStatus
from olympus.domain.entities.virality import ViralityAnalysis, ViralityStageStatus


class EditingRepository(abc.ABC):
    """Durable persistence for a project's editing timelines.

    Mirrors the other engines' repository contracts: an index plus one artifact
    per stage, so stages are individually rerunnable and work is never lost. A
    database-backed implementation can later replace the storage-backed one
    behind this same contract.
    """

    @abc.abstractmethod
    async def load(self, project_id: str) -> EditingAnalysis | None:
        """Load the editing analysis (index + all stage artifacts), or None."""

    @abc.abstractmethod
    async def save_index(self, analysis: EditingAnalysis) -> None:
        """Persist the index (overall status + per-stage summaries)."""

    @abc.abstractmethod
    async def save_stage(self, project_id: str, result: EditingStageResult) -> None:
        """Persist a single stage's full result (called after every stage)."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete all editing artifacts for a project (idempotent)."""


@dataclass(slots=True)
class EditingStageContext:
    """Everything an editing stage needs to do its work.

    Args:
        project: The project under analysis.
        storage: Storage backend (for any large artifacts a stage may persist).
        analysis: The Cognitive Engine's output for this project, if present.
        story: The Story Engine's output for this project, if present.
        virality: The Virality Engine's output for this project, if present.
        planning: The Clip Planner's output for this project, if present.
        results: Prior *editing* stages' results, so a stage can build on them.
    """

    project: Project
    storage: StoragePort
    analysis: Analysis | None = None
    story: StoryAnalysis | None = None
    virality: ViralityAnalysis | None = None
    planning: ClipPlanningAnalysis | None = None
    results: dict[str, EditingStageResult] = field(default_factory=dict)

    # -- Cognitive Engine accessors -------------------------------------------
    def cognitive_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed cognitive stage's data, or ``None``."""

        if self.analysis is None:
            return None
        result = self.analysis.stage(stage)
        if result and result.status is StageStatus.COMPLETED:
            return result.data
        return None

    def transcript_segments(self) -> list[dict[str, Any]] | None:
        """Return the transcript's segments if available, else None."""

        transcript = self.cognitive_data("speech_transcription")
        if not transcript:
            return None
        segments = transcript.get("segments")
        return segments if isinstance(segments, list) and segments else None

    def fps(self) -> float:
        """Best available frame rate (cognitive inspection, else 30.0 default)."""

        inspection = self.cognitive_data("video_inspection")
        if inspection and isinstance(inspection.get("fps"), int | float) and inspection["fps"]:
            return float(inspection["fps"])
        return 30.0

    def video_duration(self) -> float | None:
        """Best available source duration for safe boundary clamping."""

        inspection = self.cognitive_data("video_inspection")
        if inspection and isinstance(inspection.get("duration_seconds"), int | float):
            return float(inspection["duration_seconds"])
        if self.project.duration_seconds:
            return float(self.project.duration_seconds)
        return None

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

    # -- Clip Planner accessors -----------------------------------------------
    def planning_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed planning stage's data, or ``None``."""

        if self.planning is None:
            return None
        result = self.planning.stage(stage)
        if result and result.status is PlanningStageStatus.COMPLETED:
            return result.data
        return None

    def approved_plans(self) -> list[dict[str, Any]]:
        """Return the Clip Planner's ranked plans (the approved clips), or []."""

        ranking = self.planning_data("ranking")
        plans = (ranking or {}).get("plans")
        return plans if isinstance(plans, list) else []

    # -- Editing-stage accessors ----------------------------------------------
    def editing_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed prior *editing* stage's data, or ``None``."""

        result = self.results.get(stage)
        if result and result.status is EditingStageStatus.COMPLETED:
            return result.data
        return None


@dataclass(slots=True)
class EditingOutcome:
    """What an editing stage returns: an honest status, plus data or a reason."""

    status: EditingStageStatus
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @classmethod
    def completed(cls, data: dict[str, Any]) -> EditingOutcome:
        return cls(status=EditingStageStatus.COMPLETED, data=data)

    @classmethod
    def unavailable(cls, reason: str) -> EditingOutcome:
        return cls(status=EditingStageStatus.UNAVAILABLE, reason=reason)

    @classmethod
    def failed(cls, reason: str) -> EditingOutcome:
        return cls(status=EditingStageStatus.FAILED, reason=reason)


# A progress reporter a stage may call with a value in [0, 1].
EditingProgressReporter = Callable[[float], None]


class EditingAnalyzer(abc.ABC):
    """One isolated, replaceable editing stage."""

    #: Stable stage identifier (must be one of EDITING_STAGE_ORDER).
    name: str = ""
    #: Bump when the stage's behaviour changes, to trigger a rerun on resume.
    version: str = "1"
    #: Editing stage names this stage depends on (must run after them).
    depends_on: tuple[str, ...] = ()

    @abc.abstractmethod
    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        """Run the stage. Return an outcome; raise only on genuine errors.

        Implementations MUST NOT fabricate edits: when the required evidence is
        missing, return ``EditingOutcome.unavailable(reason)`` with a detailed
        reason; when a single decision cannot be determined, record it as
        ``UNKNOWN`` rather than guessing. Every event placed in ``data`` must be
        timestamped and carry a reason, a confidence, and supporting evidence.
        """

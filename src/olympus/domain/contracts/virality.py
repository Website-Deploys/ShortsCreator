"""Virality contracts (ports): the repository and the virality-analyzer interface.

These let the Virality pipeline persist its assessment and run isolated,
replaceable analyzers without binding to any concrete technique or storage
technology. Each virality analyzer is completely independent: it never imports
another analyzer and only communicates through this structured context.

The Virality Engine *consumes only* the Cognitive Engine's and Story Engine's
outputs. Those dependencies are expressed here as two read-only inputs - the
completed cognitive :class:`Analysis` and the story :class:`StoryAnalysis` -
surfaced through small accessors so analyzers never need to know how the upstream
engines store their results. The Virality Engine never modifies them.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis, StageStatus
from olympus.domain.entities.project import Project
from olympus.domain.entities.story import StoryAnalysis, StoryStageStatus
from olympus.domain.entities.virality import (
    ViralityAnalysis,
    ViralityStageResult,
    ViralityStageStatus,
)


class ViralityRepository(abc.ABC):
    """Durable persistence for a project's virality analysis.

    Mirrors the other engines' repository contracts: an index plus one artifact
    per stage, so stages are individually rerunnable and work is never lost. A
    database-backed implementation can later replace the storage-backed one
    behind this same contract.
    """

    @abc.abstractmethod
    async def load(self, project_id: str) -> ViralityAnalysis | None:
        """Load the virality analysis (index + all stage artifacts), or None."""

    @abc.abstractmethod
    async def save_index(self, analysis: ViralityAnalysis) -> None:
        """Persist the index (overall status + per-stage summaries)."""

    @abc.abstractmethod
    async def save_stage(self, project_id: str, result: ViralityStageResult) -> None:
        """Persist a single stage's full result (called after every stage)."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete all virality artifacts for a project (idempotent)."""


@dataclass(slots=True)
class ViralityStageContext:
    """Everything a virality analyzer needs to do its work.

    Args:
        project: The project under analysis.
        storage: Storage backend (for any large artifacts a stage may persist).
        analysis: The Cognitive Engine's output for this project, if present.
        story: The Story Engine's output for this project, if present.
        results: Prior *virality* stages' results, so aggregate analyzers (e.g.
            shareability, the summary) can build on them.
    """

    project: Project
    storage: StoragePort
    analysis: Analysis | None = None
    story: StoryAnalysis | None = None
    results: dict[str, ViralityStageResult] = field(default_factory=dict)

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
        """Return the transcript's segments if a transcript is available, else None."""

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

    # -- Story Engine accessors -----------------------------------------------
    def story_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed story stage's data, or ``None``."""

        if self.story is None:
            return None
        result = self.story.stage(stage)
        if result and result.status is StoryStageStatus.COMPLETED:
            return result.data
        return None

    # -- Virality-stage accessors ---------------------------------------------
    def virality_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed prior *virality* stage's data, or ``None``."""

        result = self.results.get(stage)
        if result and result.status is ViralityStageStatus.COMPLETED:
            return result.data
        return None


@dataclass(slots=True)
class ViralityOutcome:
    """What a virality analyzer returns: an honest status, plus data or a reason."""

    status: ViralityStageStatus
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @classmethod
    def completed(cls, data: dict[str, Any]) -> ViralityOutcome:
        return cls(status=ViralityStageStatus.COMPLETED, data=data)

    @classmethod
    def unavailable(cls, reason: str) -> ViralityOutcome:
        return cls(status=ViralityStageStatus.UNAVAILABLE, reason=reason)

    @classmethod
    def failed(cls, reason: str) -> ViralityOutcome:
        return cls(status=ViralityStageStatus.FAILED, reason=reason)


# A progress reporter an analyzer may call with a value in [0, 1].
ViralityProgressReporter = Callable[[float], None]


class ViralityAnalyzer(abc.ABC):
    """One isolated, replaceable virality-analysis stage."""

    #: Stable stage identifier (must be one of VIRALITY_STAGE_ORDER).
    name: str = ""
    #: Bump when the analyzer's behaviour changes, to trigger a rerun on resume.
    version: str = "1"
    #: Virality stage names this analyzer depends on (must run after them).
    depends_on: tuple[str, ...] = ()

    @abc.abstractmethod
    async def analyze(
        self, ctx: ViralityStageContext, report: ViralityProgressReporter
    ) -> ViralityOutcome:
        """Run the analysis. Return an outcome; raise only on genuine errors.

        Implementations MUST NOT fabricate output: when the required evidence is
        missing, return ``ViralityOutcome.unavailable(reason)`` with a detailed
        reason. Every score placed in ``data`` must carry a confidence, the
        supporting evidence it was derived from, and its limitations.
        """

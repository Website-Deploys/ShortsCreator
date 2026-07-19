"""Story contracts (ports): the repository and the story-analyzer interface.

These let the Story pipeline persist its understanding and run isolated,
replaceable analyzers without binding to any concrete technique or storage
technology. Each story analyzer is completely independent: it never imports
another analyzer and only communicates through this structured context.

The Story Engine *consumes* the Cognitive Engine's output. That dependency is
expressed here as a single, read-only input - the completed cognitive
:class:`Analysis` - surfaced through small helper accessors so analyzers don't
need to know how the Cognitive Engine stores its results.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis, StageStatus
from olympus.domain.entities.project import Project
from olympus.domain.entities.story import StoryAnalysis, StoryStageResult, StoryStageStatus


class StoryRepository(abc.ABC):
    """Durable persistence for a project's story analysis.

    Mirrors the Cognitive Engine's repository contract: an index plus one
    artifact per stage, so stages are individually rerunnable and work is never
    lost. A database-backed implementation can later replace the storage-backed
    one behind this same contract.
    """

    @abc.abstractmethod
    async def load(self, project_id: str) -> StoryAnalysis | None:
        """Load the story analysis (index + all stage artifacts), or None."""

    @abc.abstractmethod
    async def save_index(self, analysis: StoryAnalysis) -> None:
        """Persist the index (overall status + per-stage summaries)."""

    @abc.abstractmethod
    async def save_stage(self, project_id: str, result: StoryStageResult) -> None:
        """Persist a single stage's full result (called after every stage)."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete all story artifacts for a project (idempotent)."""


@dataclass(slots=True)
class StoryStageContext:
    """Everything a story analyzer needs to do its work.

    Args:
        project: The project under analysis.
        storage: Storage backend (for any large artifacts a stage may persist).
        analysis: The Cognitive Engine's output for this project, if present.
            May be ``None`` when no cognitive analysis exists yet.
        results: Prior *story* stages' results, so a stage can build on them.
    """

    project: Project
    storage: StoragePort
    analysis: Analysis | None = None
    results: dict[str, StoryStageResult] = field(default_factory=dict)

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
        """Return the transcript's segments if a transcript is available.

        Each segment is a dict with ``start``/``end``/``text``/``speaker``/
        ``confidence`` (as produced by the Cognitive Engine's transcription
        stage). Returns ``None`` when no transcript exists - the honest signal
        that most story stages cannot run.
        """

        transcript = self.cognitive_data("speech_transcription")
        if not transcript:
            return None
        segments = transcript.get("segments")
        return segments if isinstance(segments, list) and segments else None

    # -- Story-stage accessors -------------------------------------------------
    def story_data(self, stage: str) -> dict[str, Any] | None:
        """Return a completed prior *story* stage's data, or ``None``."""

        result = self.results.get(stage)
        if result and result.status is StoryStageStatus.COMPLETED:
            return result.data
        return None


@dataclass(slots=True)
class StoryOutcome:
    """What a story analyzer returns: an honest status, plus data or a reason."""

    status: StoryStageStatus
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @classmethod
    def completed(cls, data: dict[str, Any]) -> StoryOutcome:
        return cls(status=StoryStageStatus.COMPLETED, data=data)

    @classmethod
    def unavailable(cls, reason: str) -> StoryOutcome:
        return cls(status=StoryStageStatus.UNAVAILABLE, reason=reason)

    @classmethod
    def failed(cls, reason: str) -> StoryOutcome:
        return cls(status=StoryStageStatus.FAILED, reason=reason)


# A progress reporter an analyzer may call with a value in [0, 1].
StoryProgressReporter = Callable[[float], None]


class StoryAnalyzer(abc.ABC):
    """One isolated, replaceable story-analysis stage."""

    #: Stable stage identifier (must be one of STORY_STAGE_ORDER).
    name: str = ""
    #: Bump when the analyzer's behaviour changes, to trigger a rerun on resume.
    version: str = "1"
    #: Story stage names this analyzer depends on (must run after them).
    depends_on: tuple[str, ...] = ()

    @abc.abstractmethod
    async def analyze(
        self, ctx: StoryStageContext, report: StoryProgressReporter
    ) -> StoryOutcome:
        """Run the analysis. Return an outcome; raise only on genuine errors.

        Implementations MUST NOT fabricate output: when the required inputs are
        missing (e.g. no transcript), return ``StoryOutcome.unavailable(reason)``.
        Every conclusion placed in ``data`` must carry a confidence score and the
        supporting evidence it was derived from.
        """

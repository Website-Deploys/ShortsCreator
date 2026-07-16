"""Analysis contracts (ports): the repository and the stage-analyzer interface.

These let the pipeline persist understanding and run isolated, replaceable
analyzers without binding to any concrete model, tool, or storage technology.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis, StageResult, StageStatus
from olympus.domain.entities.project import Project


class AnalysisRepository(abc.ABC):
    """Durable persistence for a project's analysis (index + per-stage artifacts).

    Each stage's full result is stored independently so stages are individually
    rerunnable and work is never lost. The index holds lightweight summaries.
    """

    @abc.abstractmethod
    async def load(self, project_id: str) -> Analysis | None:
        """Load the analysis (index + all stage artifacts), or None if absent."""

    @abc.abstractmethod
    async def save_index(self, analysis: Analysis) -> None:
        """Persist the analysis index (overall status + per-stage summaries)."""

    @abc.abstractmethod
    async def save_stage(self, project_id: str, result: StageResult) -> None:
        """Persist a single stage's full result (called after every stage)."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete all analysis artifacts for a project (idempotent)."""


@dataclass(slots=True)
class StageContext:
    """Everything an analyzer needs to do its work.

    ``results`` exposes prior stages' outputs so an analyzer can depend on them
    (e.g. transcription reads the extracted-audio key). ``transcription_provider``
    is injected so the transcription analyzer stays decoupled from provider
    construction.
    """

    project: Project
    storage: StoragePort
    results: dict[str, StageResult] = field(default_factory=dict)
    transcription_provider: Any | None = None

    def data_of(self, stage: str) -> dict[str, Any] | None:
        """Return the data of a completed prior stage, or None."""

        result = self.results.get(stage)
        if result and result.status is StageStatus.COMPLETED:
            return result.data
        return None


@dataclass(slots=True)
class StageOutcome:
    """What an analyzer returns: an honest status, plus data or a reason."""

    status: StageStatus
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    retryable: bool = True

    @classmethod
    def completed(cls, data: dict[str, Any]) -> StageOutcome:
        return cls(status=StageStatus.COMPLETED, data=data)

    @classmethod
    def unavailable(cls, reason: str) -> StageOutcome:
        return cls(status=StageStatus.UNAVAILABLE, reason=reason)

    @classmethod
    def failed(cls, reason: str, *, retryable: bool = True) -> StageOutcome:
        return cls(status=StageStatus.FAILED, reason=reason, retryable=retryable)


# A progress reporter an analyzer may call with a value in [0, 1].
ProgressReporter = Callable[[float], None]


class Analyzer(abc.ABC):
    """One isolated, replaceable analysis stage."""

    #: Stable stage identifier (must be one of STAGE_ORDER).
    name: str = ""
    #: Bump when the analyzer's behaviour changes, to trigger a rerun on resume.
    version: str = "1"
    #: Stage names this analyzer depends on (must run after them).
    depends_on: tuple[str, ...] = ()

    @abc.abstractmethod
    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        """Run the analysis. Return an outcome; raise only on genuine errors.

        Implementations MUST NOT fabricate output: when the required tooling or
        model is unavailable, return ``StageOutcome.unavailable(reason)``.
        """

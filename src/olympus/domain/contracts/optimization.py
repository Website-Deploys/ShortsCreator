"""Optimization contracts (ports): the repository and the optimization-stage API.

These let the Optimization pipeline persist its results and run isolated,
replaceable stages without binding to any concrete technique or storage
technology. Each stage is completely independent: it never imports another
stage's implementation and communicates only through the structured
:class:`OptimizationStageContext`.

The Optimization Engine *consumes only* the outputs of the engines before it -
Cognitive, Story, Virality, Clip Planner, Editing - plus the Rendering Engine's
render manifest, and it talks to music/enhancement providers through their ports.
It never modifies any upstream output, and it never re-renders or re-decides the
story; it polishes what was already produced. Those dependencies are surfaced
here as read-only inputs with small accessors so stages never need to know how
the upstream engines store their results.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.enhancement import EnhancementCapabilities
from olympus.domain.contracts.music import MusicProviderRegistry
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis, StageStatus
from olympus.domain.entities.editing import EditingAnalysis, EditingStageStatus
from olympus.domain.entities.optimization import (
    OptimizationAnalysis,
    OptimizationStageResult,
    OptimizationStageStatus,
)
from olympus.domain.entities.planning import ClipPlanningAnalysis, PlanningStageStatus
from olympus.domain.entities.project import Project
from olympus.domain.entities.rendering import RenderedVideo, RenderManifest
from olympus.domain.entities.story import StoryAnalysis, StoryStageStatus
from olympus.domain.entities.virality import ViralityAnalysis, ViralityStageStatus


class OptimizationRepository(abc.ABC):
    """Durable persistence for a project's optimization analysis.

    Mirrors the other engines' repository contracts: an index plus one artifact
    per stage, so stages are individually rerunnable and work is never lost. A
    database-backed implementation can later replace the storage-backed one
    behind this same contract.
    """

    @abc.abstractmethod
    async def load(self, project_id: str) -> OptimizationAnalysis | None:
        """Load the optimization analysis (index + all stage artifacts), or None."""

    @abc.abstractmethod
    async def save_index(self, analysis: OptimizationAnalysis) -> None:
        """Persist the index (overall status + per-stage summaries)."""

    @abc.abstractmethod
    async def save_stage(self, project_id: str, result: OptimizationStageResult) -> None:
        """Persist a single stage's full result (called after every stage)."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete all optimization artifacts for a project (idempotent)."""


@dataclass(slots=True)
class OptimizationStageContext:
    """Everything an optimization stage needs to do its work.

    Args:
        project: The project under optimization.
        storage: Storage backend (for reading rendered media and writing assets).
        renders: The Rendering Engine's manifest for this project, if present.
        analysis: The Cognitive Engine's output, if present.
        story: The Story Engine's output, if present.
        virality: The Virality Engine's output, if present.
        planning: The Clip Planner's output, if present.
        editing: The Editing Engine's output (timelines), if present.
        music: The registry of copyright-free music providers.
        enhancement: The available audio/visual/thumbnail enhancement capabilities.
        results: Prior *optimization* stages' results, so a stage can build on them.
    """

    project: Project
    storage: StoragePort
    music: MusicProviderRegistry
    enhancement: EnhancementCapabilities
    renders: RenderManifest | None = None
    analysis: Analysis | None = None
    story: StoryAnalysis | None = None
    virality: ViralityAnalysis | None = None
    planning: ClipPlanningAnalysis | None = None
    editing: EditingAnalysis | None = None
    results: dict[str, OptimizationStageResult] = field(default_factory=dict)

    # -- Render (Rendering Engine) accessors ----------------------------------
    def rendered_videos(self) -> list[RenderedVideo]:
        """Return the finished rendered clips, or ``[]`` if none were produced."""

        if self.renders is None:
            return []
        return list(self.renders.renders)

    # -- Cognitive Engine accessors -------------------------------------------
    def cognitive_data(self, stage: str) -> dict[str, Any] | None:
        if self.analysis is None:
            return None
        result = self.analysis.stage(stage)
        if result and result.status is StageStatus.COMPLETED:
            return result.data
        return None

    def transcript_segments(self) -> list[dict[str, Any]] | None:
        transcript = self.cognitive_data("speech_transcription")
        if not transcript:
            return None
        segments = transcript.get("segments")
        return segments if isinstance(segments, list) and segments else None

    # -- Story Engine accessors -----------------------------------------------
    def story_data(self, stage: str) -> dict[str, Any] | None:
        if self.story is None:
            return None
        result = self.story.stage(stage)
        if result and result.status is StoryStageStatus.COMPLETED:
            return result.data
        return None

    # -- Virality Engine accessors --------------------------------------------
    def virality_data(self, stage: str) -> dict[str, Any] | None:
        if self.virality is None:
            return None
        result = self.virality.stage(stage)
        if result and result.status is ViralityStageStatus.COMPLETED:
            return result.data
        return None

    # -- Clip Planner accessors -----------------------------------------------
    def planning_data(self, stage: str) -> dict[str, Any] | None:
        if self.planning is None:
            return None
        result = self.planning.stage(stage)
        if result and result.status is PlanningStageStatus.COMPLETED:
            return result.data
        return None

    # -- Editing Engine accessors ---------------------------------------------
    def editing_data(self, stage: str) -> dict[str, Any] | None:
        if self.editing is None:
            return None
        result = self.editing.stage(stage)
        if result and result.status is EditingStageStatus.COMPLETED:
            return result.data
        return None

    def timelines(self) -> list[dict[str, Any]]:
        """Return the Editing Engine's assembled timelines, or ``[]``."""

        validation = self.editing_data("timeline_validation")
        timelines = (validation or {}).get("timelines")
        return timelines if isinstance(timelines, list) else []

    # -- Optimization-stage accessors -----------------------------------------
    def optimization_data(self, stage: str) -> dict[str, Any] | None:
        result = self.results.get(stage)
        if result and result.status is OptimizationStageStatus.COMPLETED:
            return result.data
        return None


@dataclass(slots=True)
class OptimizationOutcome:
    """What a stage returns: an honest status, plus data or a reason."""

    status: OptimizationStageStatus
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @classmethod
    def completed(cls, data: dict[str, Any]) -> OptimizationOutcome:
        return cls(status=OptimizationStageStatus.COMPLETED, data=data)

    @classmethod
    def unavailable(cls, reason: str) -> OptimizationOutcome:
        return cls(status=OptimizationStageStatus.UNAVAILABLE, reason=reason)

    @classmethod
    def failed(cls, reason: str) -> OptimizationOutcome:
        return cls(status=OptimizationStageStatus.FAILED, reason=reason)


# A progress reporter a stage may call with a value in [0, 1].
OptimizationProgressReporter = Callable[[float], None]


class OptimizationAnalyzer(abc.ABC):
    """One isolated, replaceable optimization stage."""

    #: Stable stage identifier (must be one of OPTIMIZATION_STAGE_ORDER).
    name: str = ""
    #: Bump when the stage's behaviour changes, to trigger a rerun on resume.
    version: str = "1"
    #: Optimization stage names this stage depends on (must run after them).
    depends_on: tuple[str, ...] = ()

    @abc.abstractmethod
    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        """Run the stage. Return an outcome; raise only on genuine errors.

        Implementations MUST NOT fabricate enhancements: when the rendered media
        or the required model is missing, return
        ``OptimizationOutcome.unavailable(reason)`` with a detailed reason; when a
        single value cannot be determined, record it as ``UNKNOWN`` rather than
        guessing. Every recommendation or score placed in ``data`` must carry a
        reason, a confidence, and supporting evidence.
        """

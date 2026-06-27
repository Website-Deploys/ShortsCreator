"""Render-pipeline contracts (ports): the repository and the render-stage API.

These let the Rendering Engine's pipeline persist its run state and execute
isolated, replaceable stages without binding to any concrete technique or
storage technology. Each stage is independent: it never imports another stage's
implementation and communicates only through the structured
:class:`RenderStageContext`.

The Rendering Engine performs *execution* only. It consumes the upstream
engines' outputs - chiefly the Editing Engine's timelines (plus the Cognitive,
Story, Virality, and Clip Planner outputs for context) - and the source media,
and it produces real encoded files via a replaceable :class:`ClipRenderer`. It
never makes creative decisions and never modifies any upstream output. When the
renderer or a dependency is unavailable, stages report ``UNAVAILABLE`` honestly.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.rendering import ClipRenderer, RenderManifestStore
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis, StageStatus
from olympus.domain.entities.editing import EditingAnalysis, EditingStageStatus
from olympus.domain.entities.planning import ClipPlanningAnalysis, PlanningStageStatus
from olympus.domain.entities.project import Project
from olympus.domain.entities.render_pipeline import (
    RenderRun,
    RenderStageResult,
    RenderStageStatus,
)
from olympus.domain.entities.story import StoryAnalysis, StoryStageStatus
from olympus.domain.entities.virality import ViralityAnalysis, ViralityStageStatus


class RenderRunRepository(abc.ABC):
    """Durable persistence for a project's render run (index + per-stage artifacts)."""

    @abc.abstractmethod
    async def load(self, project_id: str) -> RenderRun | None:
        """Load the render run (index + all stage artifacts), or ``None``."""

    @abc.abstractmethod
    async def save_index(self, run: RenderRun) -> None:
        """Persist the index (overall status + per-stage summaries)."""

    @abc.abstractmethod
    async def save_stage(self, project_id: str, result: RenderStageResult) -> None:
        """Persist a single stage's full result (called after every stage)."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete all render-run artifacts for a project (idempotent)."""


@dataclass(slots=True)
class RenderSettings:
    """Execution parameters for a render (not creative choices).

    Defaults target a full-resolution vertical Short; ``preview_*`` are used by
    the preview stage. These are knobs the operator controls, independent of the
    creative decisions baked into the timeline.
    """

    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_bitrate_kbps: int = 12000
    audio_bitrate_kbps: int = 192
    preview_width: int = 540
    preview_height: int = 960
    preview_bitrate_kbps: int = 2500


@dataclass(slots=True)
class RenderStageContext:
    """Everything a render stage needs to do its work.

    Args:
        project: The project being rendered.
        storage: Storage backend (read source media, write rendered files).
        renderer: The replaceable clip renderer (FFmpeg/GPU/cloud/...).
        manifest_store: The write side of the render-manifest contract.
        settings: Execution parameters (dimensions, fps, bitrate).
        editing: The Editing Engine's output (the timelines to render).
        analysis/story/virality/planning: Upstream context, if present.
        results: Prior *render* stages' results, so a stage can build on them.
    """

    project: Project
    storage: StoragePort
    renderer: ClipRenderer
    manifest_store: RenderManifestStore
    settings: RenderSettings
    editing: EditingAnalysis | None = None
    analysis: Analysis | None = None
    story: StoryAnalysis | None = None
    virality: ViralityAnalysis | None = None
    planning: ClipPlanningAnalysis | None = None
    results: dict[str, RenderStageResult] = field(default_factory=dict)

    # -- Editing Engine accessors (the render inputs) --------------------------
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

    def editing_version(self) -> str | None:
        return self.editing.pipeline_version if self.editing is not None else None

    # -- Upstream context accessors -------------------------------------------
    def cognitive_data(self, stage: str) -> dict[str, Any] | None:
        if self.analysis is None:
            return None
        result = self.analysis.stage(stage)
        if result and result.status is StageStatus.COMPLETED:
            return result.data
        return None

    def story_data(self, stage: str) -> dict[str, Any] | None:
        if self.story is None:
            return None
        result = self.story.stage(stage)
        if result and result.status is StoryStageStatus.COMPLETED:
            return result.data
        return None

    def virality_data(self, stage: str) -> dict[str, Any] | None:
        if self.virality is None:
            return None
        result = self.virality.stage(stage)
        if result and result.status is ViralityStageStatus.COMPLETED:
            return result.data
        return None

    def planning_data(self, stage: str) -> dict[str, Any] | None:
        if self.planning is None:
            return None
        result = self.planning.stage(stage)
        if result and result.status is PlanningStageStatus.COMPLETED:
            return result.data
        return None

    # -- Render-stage accessors -----------------------------------------------
    def render_data(self, stage: str) -> dict[str, Any] | None:
        result = self.results.get(stage)
        if result and result.status is RenderStageStatus.COMPLETED:
            return result.data
        return None


@dataclass(slots=True)
class RenderOutcome:
    """What a stage returns: an honest status, plus data or a reason."""

    status: RenderStageStatus
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @classmethod
    def completed(cls, data: dict[str, Any]) -> RenderOutcome:
        return cls(status=RenderStageStatus.COMPLETED, data=data)

    @classmethod
    def unavailable(cls, reason: str, data: dict[str, Any] | None = None) -> RenderOutcome:
        return cls(status=RenderStageStatus.UNAVAILABLE, reason=reason, data=data or {})

    @classmethod
    def failed(cls, reason: str) -> RenderOutcome:
        return cls(status=RenderStageStatus.FAILED, reason=reason)


# A progress reporter a stage may call with a value in [0, 1].
RenderProgressReporter = Callable[[float], None]


class RenderStageAnalyzer(abc.ABC):
    """One isolated, replaceable render stage."""

    #: Stable stage identifier (must be one of RENDER_STAGE_ORDER).
    name: str = ""
    #: Bump when the stage's behaviour changes, to trigger a rerun on resume.
    version: str = "1"
    #: Render stage names this stage depends on (must run after them).
    depends_on: tuple[str, ...] = ()

    @abc.abstractmethod
    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        """Run the stage. Return an outcome; raise only on genuine errors.

        Implementations MUST NOT fabricate a rendered file: when the renderer or
        a dependency is missing, return ``RenderOutcome.unavailable(reason)`` with
        the precise reason. Stages that only build a plan or validate inputs run
        deterministically and need no renderer.
        """

"""The Optimization service - the application boundary for post-render polish.

This service owns the *lifecycle* of a project's optimization analysis: starting
it in the background (typically right after the Rendering Engine finishes),
reporting its state, returning the quality report, export variants, music
recommendations and publish packages, resolving a package asset for download,
re-running a single stage, and cancelling an in-flight run. It coordinates the
optimization pipeline, the optimization repository, the render-manifest
repository, and the Cognitive + Story + Virality + Clip Planner + Editing
repositories (whose outputs are the pipeline's only inputs).

Background runs are tracked in a small process-wide registry keyed by project id,
exactly like the other engines' services. It never re-renders, re-encodes, or
changes the story decided upstream.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.analysis import AnalysisRepository
from olympus.domain.contracts.editing import EditingRepository
from olympus.domain.contracts.optimization import OptimizationRepository
from olympus.domain.contracts.planning import PlanningRepository
from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.rendering import RenderManifestRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.story import StoryRepository
from olympus.domain.contracts.virality import ViralityRepository
from olympus.domain.entities.optimization import (
    OPTIMIZATION_STAGE_ORDER,
    OptimizationAnalysis,
)
from olympus.domain.entities.project import Project
from olympus.optimization import OptimizationPipeline, build_default_optimization_analyzers
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger

log = get_logger(__name__)

# An optional hook invoked after a run completes successfully (kept for symmetry
# with the other engines, so a future Publishing/Distribution engine could chain
# after the Optimization Engine).
CompletionHook = Callable[[Project, OptimizationAnalysis], Awaitable[None]]


@dataclass(slots=True)
class _Run:
    """A tracked background optimization run for one project."""

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


# Process-wide registry of in-flight optimization runs (shared across instances).
_RUNS: dict[str, _Run] = {}


class OptimizationService:
    """Coordinates starting, inspecting, re-running, and cancelling optimization."""

    def __init__(
        self,
        *,
        optimization_repo: OptimizationRepository,
        render_repo: RenderManifestRepository,
        editing_repo: EditingRepository,
        planning_repo: PlanningRepository,
        virality_repo: ViralityRepository,
        story_repo: StoryRepository,
        analysis_repo: AnalysisRepository,
        project_repo: ProjectRepository,
        storage: StoragePort,
        pipeline: OptimizationPipeline | None = None,
        on_complete: CompletionHook | None = None,
    ) -> None:
        self._optimization_repo = optimization_repo
        self._render_repo = render_repo
        self._editing_repo = editing_repo
        self._planning_repo = planning_repo
        self._virality_repo = virality_repo
        self._story_repo = story_repo
        self._analysis_repo = analysis_repo
        self._project_repo = project_repo
        self._storage = storage
        self._on_complete = on_complete
        self._pipeline = pipeline or OptimizationPipeline(
            build_default_optimization_analyzers(), optimization_repo
        )

    # ----------------------------------------------------------------- start

    async def start(self, project: Project, *, restart: bool = False) -> OptimizationAnalysis:
        """Begin (or resume) optimization for ``project`` as a background task."""

        if project.id in _RUNS and not restart and _RUNS[project.id].task is not None:
            existing = await self._optimization_repo.load(project.id)
            if existing is not None:
                return existing

        run = _Run()
        _RUNS[project.id] = run
        run.task = asyncio.create_task(self._run(project, run))
        await asyncio.sleep(0)  # let the task persist its initial index
        optimization = await self._optimization_repo.load(project.id)
        if optimization is not None:
            return optimization
        return await self._wait_for_index(project.id)

    async def _run(self, project: Project, run: _Run) -> None:
        try:
            renders = await self._render_repo.load(project.id)
            analysis = await self._analysis_repo.load(project.id)
            story = await self._story_repo.load(project.id)
            virality = await self._virality_repo.load(project.id)
            planning = await self._planning_repo.load(project.id)
            editing = await self._editing_repo.load(project.id)
            optimization = await self._pipeline.run(
                project,
                self._storage,
                renders=renders,
                analysis=analysis,
                story=story,
                virality=virality,
                planning=planning,
                editing=editing,
                cancel_event=run.cancel_event,
            )
            if self._on_complete is not None and optimization.status.value == "completed":
                try:
                    await self._on_complete(project, optimization)
                except Exception as exc:  # never let the hook break the run
                    log.error(
                        "optimization_on_complete_error",
                        project_id=project.id,
                        error=str(exc),
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            log.info("optimization_task_cancelled", project_id=project.id)
            raise
        except Exception as exc:  # background task must not crash silently
            log.error(
                "optimization_task_error",
                project_id=project.id,
                error=str(exc),
                exc_info=True,
            )
        finally:
            _RUNS.pop(project.id, None)

    async def _wait_for_index(self, project_id: str) -> OptimizationAnalysis:
        for _ in range(50):
            optimization = await self._optimization_repo.load(project_id)
            if optimization is not None:
                return optimization
            await asyncio.sleep(0.02)
        raise NotFoundError(
            "Optimization analysis could not be initialized.", details={"id": project_id}
        )

    # ------------------------------------------------------------------ read

    async def get_optimization(self, project_id: str) -> OptimizationAnalysis | None:
        """Return the current optimization analysis for a project, or ``None``."""

        return await self._optimization_repo.load(project_id)

    async def _stage_data(self, project_id: str, stage: str) -> dict[str, Any] | None:
        optimization = await self._optimization_repo.load(project_id)
        if optimization is None:
            return None
        result = optimization.stage(stage)
        if result is None or result.status.value != "completed":
            return None
        return result.data

    async def quality_report(self, project_id: str) -> dict[str, Any] | None:
        """Return the per-clip quality evaluation, or ``None`` if not produced."""

        return await self._stage_data(project_id, "quality_evaluation")

    async def variants(self, project_id: str) -> dict[str, Any] | None:
        """Return the generated export variants, or ``None`` if not produced."""

        return await self._stage_data(project_id, "variant_generation")

    async def music_recommendations(self, project_id: str) -> dict[str, Any] | None:
        """Return the music recommendations, or ``None`` if not produced."""

        return await self._stage_data(project_id, "music_recommendation")

    async def list_packages(self, project_id: str) -> list[dict[str, Any]] | None:
        """Return the publish packages (zero is valid), or ``None`` if not produced."""

        data = await self._stage_data(project_id, "publish_package_creation")
        if data is None:
            # Terminal-but-unpackaged still yields an honest empty result.
            optimization = await self._optimization_repo.load(project_id)
            if optimization is not None and optimization.status.value in (
                "completed",
                "failed",
                "cancelled",
            ):
                return []
            return None
        packages = data.get("packages")
        return packages if isinstance(packages, list) else []

    async def get_package(self, project_id: str, clip_id: str) -> dict[str, Any] | None:
        """Return a single clip's publish package, or ``None`` if not found."""

        packages = await self.list_packages(project_id)
        if not packages:
            return None
        return next((p for p in packages if p.get("clip_id") == clip_id), None)

    async def resolve_asset(
        self, project_id: str, clip_id: str, kind: str
    ) -> dict[str, Any] | None:
        """Resolve a package asset to its storage key (or its unavailable reason).

        Returns the asset descriptor (``kind``, ``status``, and ``storage_key``
        when available). ``None`` when the package or asset does not exist. An
        asset that is honestly ``unavailable`` is returned with its reason rather
        than a key, so callers surface the truth instead of a broken download.
        """

        package = await self.get_package(project_id, clip_id)
        if package is None:
            return None
        for asset in package.get("assets", []):
            if asset.get("kind") == kind:
                return asset
        return None

    def is_running(self, project_id: str) -> bool:
        """Whether a background optimization run is currently tracked."""

        run = _RUNS.get(project_id)
        return run is not None and run.task is not None and not run.task.done()

    # ---------------------------------------------------------------- rerun

    async def rerun_stage(self, project: Project, stage: str) -> OptimizationAnalysis:
        """Re-run a single optimization stage, leaving the others untouched."""

        if stage not in OPTIMIZATION_STAGE_ORDER:
            raise ValidationError("Unknown optimization stage.", details={"stage": stage})
        renders = await self._render_repo.load(project.id)
        analysis = await self._analysis_repo.load(project.id)
        story = await self._story_repo.load(project.id)
        virality = await self._virality_repo.load(project.id)
        planning = await self._planning_repo.load(project.id)
        editing = await self._editing_repo.load(project.id)
        return await self._pipeline.run(
            project,
            self._storage,
            renders=renders,
            analysis=analysis,
            story=story,
            virality=virality,
            planning=planning,
            editing=editing,
            only={stage},
        )

    # --------------------------------------------------------------- cancel

    async def cancel(self, project_id: str) -> bool:
        """Request cancellation of an in-flight run. Returns whether one existed."""

        run = _RUNS.get(project_id)
        if run is None:
            return False
        run.cancel_event.set()
        log.info("optimization_cancel_requested", project_id=project_id)
        return True

    # --------------------------------------------------------------- delete

    async def delete(self, project_id: str) -> None:
        """Cancel any run and delete all optimization artifacts (idempotent)."""

        # Capture the in-flight run BEFORE cancelling so we can wait for it to
        # actually stop. Deleting a project's artifacts while its background
        # task is still writing would orphan the directory or raise a
        # StorageError (os.replace into a just-deleted dir).
        run = _RUNS.get(project_id)
        await self.cancel(project_id)
        if run is not None and run.task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(run.task), timeout=10.0)
            except Exception as exc:  # best-effort drain; deletion proceeds
                log.warning(
                    "optimization_delete_drain_incomplete",
                    project_id=project_id,
                    error=str(exc),
                )
        await self._optimization_repo.delete(project_id)

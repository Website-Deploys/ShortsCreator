"""The Clip Planner service - the application boundary for editing plans.

This service owns the *lifecycle* of a project's clip planning: starting it in
the background (typically right after the Virality Engine finishes), reporting
its state, listing/fetching individual plans, re-running a single stage,
cancelling an in-flight run, and exposing the aggregated summary. It coordinates
the planning pipeline, the planning repository, and the Cognitive + Story +
Virality repositories (whose outputs are the pipeline's only inputs).

Background runs are tracked in a small process-wide registry keyed by project id,
exactly like the other engines' services. When a distributed worker tier is
introduced, this service is the single place that changes; the pipeline,
repository, and stages are untouched.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.analysis import AnalysisRepository
from olympus.domain.contracts.planning import PlanningRepository
from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.story import StoryRepository
from olympus.domain.contracts.virality import ViralityRepository
from olympus.domain.entities.planning import PLANNING_STAGE_ORDER, ClipPlanningAnalysis
from olympus.domain.entities.project import Project
from olympus.planning import ClipPlanningPipeline, build_default_planning_analyzers
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.services.runs import begin_or_reuse_run

log = get_logger(__name__)

# An optional hook invoked after a run completes successfully (kept for symmetry
# with the other engines, so a future engine - e.g. an Editing Engine - could
# chain after the Clip Planner).
CompletionHook = Callable[[Project, ClipPlanningAnalysis], Awaitable[None]]


@dataclass(slots=True)
class _Run:
    """A tracked background planning run for one project."""

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


# Process-wide registry of in-flight planning runs (shared across instances).
_RUNS: dict[str, _Run] = {}


class ClipPlannerService:
    """Coordinates starting, inspecting, listing, re-running, and cancelling plans."""

    def __init__(
        self,
        *,
        planning_repo: PlanningRepository,
        virality_repo: ViralityRepository,
        story_repo: StoryRepository,
        analysis_repo: AnalysisRepository,
        project_repo: ProjectRepository,
        storage: StoragePort,
        pipeline: ClipPlanningPipeline | None = None,
        on_complete: CompletionHook | None = None,
    ) -> None:
        self._planning_repo = planning_repo
        self._virality_repo = virality_repo
        self._story_repo = story_repo
        self._analysis_repo = analysis_repo
        self._project_repo = project_repo
        self._storage = storage
        self._on_complete = on_complete
        self._pipeline = pipeline or ClipPlanningPipeline(
            build_default_planning_analyzers(), planning_repo
        )

    # ----------------------------------------------------------------- start

    async def start(self, project: Project, *, restart: bool = False) -> ClipPlanningAnalysis:
        """Begin (or resume) clip planning for ``project`` as a background task."""

        existing, _run = await begin_or_reuse_run(
            scope="planning",
            project_id=project.id,
            runs=_RUNS,
            make_run=_Run,
            loader=lambda: self._planning_repo.load(project.id),
            spawn=lambda r: asyncio.create_task(self._run(project, r)),
            restart=restart,
        )
        if existing is not None:
            return existing
        await asyncio.sleep(0)  # let the task persist its initial index
        planning = await self._planning_repo.load(project.id)
        if planning is not None:
            return planning
        return await self._wait_for_index(project.id)

    async def _run(self, project: Project, run: _Run) -> None:
        try:
            analysis = await self._analysis_repo.load(project.id)
            story = await self._story_repo.load(project.id)
            virality = await self._virality_repo.load(project.id)
            planning = await self._pipeline.run(
                project,
                self._storage,
                analysis=analysis,
                story=story,
                virality=virality,
                cancel_event=run.cancel_event,
            )
            if self._on_complete is not None and planning.status.value == "completed":
                try:
                    await self._on_complete(project, planning)
                except Exception as exc:  # never let the hook break the run
                    log.error(
                        "planning_on_complete_error",
                        project_id=project.id,
                        error=str(exc),
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            log.info("planning_task_cancelled", project_id=project.id)
            raise
        except Exception as exc:  # background task must not crash silently
            log.error(
                "planning_task_error",
                project_id=project.id,
                error=str(exc),
                exc_info=True,
            )
        finally:
            _RUNS.pop(project.id, None)

    async def _wait_for_index(self, project_id: str) -> ClipPlanningAnalysis:
        for _ in range(50):
            planning = await self._planning_repo.load(project_id)
            if planning is not None:
                return planning
            await asyncio.sleep(0.02)
        raise NotFoundError("Clip planning could not be initialized.", details={"id": project_id})

    # ------------------------------------------------------------------ read

    async def get_planning(self, project_id: str) -> ClipPlanningAnalysis | None:
        """Return the current clip-planning analysis for a project, or ``None``."""

        return await self._planning_repo.load(project_id)

    async def get_summary(self, project_id: str) -> dict[str, Any] | None:
        """Return the aggregated planning summary, or ``None`` if not produced."""

        planning = await self._planning_repo.load(project_id)
        if planning is None:
            return None
        stage = planning.stage("planning_summary")
        if stage is None or stage.status.value != "completed":
            return None
        return stage.data

    async def list_plans(self, project_id: str) -> list[dict[str, Any]] | None:
        """Return the full ranked plans (with blueprints), or ``None`` if absent.

        Returns an empty list when the pipeline reached a terminal state without
        producing ranked plans (an honest "zero clips" outcome). Returns ``None``
        only when no planning exists yet or it is still in progress.
        """

        planning = await self._planning_repo.load(project_id)
        if planning is None:
            return None
        ranking = planning.stage("ranking")
        if ranking is not None and ranking.status.value == "completed":
            plans = ranking.data.get("plans")
            return plans if isinstance(plans, list) else []
        if planning.status.value in ("completed", "failed", "cancelled"):
            return []  # terminal but zero ranked plans - honest, not an error
        return None  # still running / not ready

    async def get_plan(self, project_id: str, plan_id: str) -> dict[str, Any] | None:
        """Return a single full plan by id, or ``None`` if not found."""

        plans = await self.list_plans(project_id)
        if not plans:
            return None
        return next((p for p in plans if p.get("id") == plan_id), None)

    def is_running(self, project_id: str) -> bool:
        """Whether a background planning run is currently tracked for the project."""

        run = _RUNS.get(project_id)
        return run is not None and run.task is not None and not run.task.done()

    # ---------------------------------------------------------------- rerun

    async def rerun_stage(self, project: Project, stage: str) -> ClipPlanningAnalysis:
        """Re-run a single planning stage, leaving the others' results untouched."""

        if stage not in PLANNING_STAGE_ORDER:
            raise ValidationError("Unknown planning stage.", details={"stage": stage})
        analysis = await self._analysis_repo.load(project.id)
        story = await self._story_repo.load(project.id)
        virality = await self._virality_repo.load(project.id)
        return await self._pipeline.run(
            project, self._storage, analysis=analysis, story=story, virality=virality, only={stage}
        )

    # --------------------------------------------------------------- cancel

    async def cancel(self, project_id: str) -> bool:
        """Request cancellation of an in-flight run. Returns whether one existed."""

        run = _RUNS.get(project_id)
        if run is None:
            return False
        run.cancel_event.set()
        log.info("planning_cancel_requested", project_id=project_id)
        return True

    # --------------------------------------------------------------- delete

    async def delete(self, project_id: str) -> None:
        """Cancel any run and delete all planning artifacts (idempotent)."""

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
                    "planning_delete_drain_incomplete",
                    project_id=project_id,
                    error=str(exc),
                )
        await self._planning_repo.delete(project_id)

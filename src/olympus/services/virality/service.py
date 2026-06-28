"""The virality service - the application boundary for viral-potential analysis.

This service owns the *lifecycle* of a project's virality analysis: starting it
in the background (typically right after the Story Engine finishes), reporting
its state, re-running a single stage, cancelling an in-flight run, and exposing
the aggregated summary. It coordinates the virality pipeline, the virality
repository, and the Cognitive + Story analysis repositories (whose outputs are
the pipeline's only inputs).

Background runs are tracked in a small process-wide registry keyed by project id,
exactly like the other engines' services - keeping the MVP free of an external
task queue while remaining honest about what is genuinely running. When a
distributed worker tier is introduced, this service is the single place that
changes; the pipeline, repository, and analyzers are untouched.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.analysis import AnalysisRepository
from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.story import StoryRepository
from olympus.domain.contracts.virality import ViralityRepository
from olympus.domain.entities.project import Project
from olympus.domain.entities.virality import VIRALITY_STAGE_ORDER, ViralityAnalysis
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.virality import ViralityPipeline, build_default_virality_analyzers

log = get_logger(__name__)

# An optional hook invoked after a run completes successfully (kept for symmetry
# with the other engines, so a future engine could chain after Virality).
CompletionHook = Callable[[Project, ViralityAnalysis], Awaitable[None]]


@dataclass(slots=True)
class _Run:
    """A tracked background virality run for one project."""

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


# Process-wide registry of in-flight virality runs (shared across instances).
_RUNS: dict[str, _Run] = {}


class ViralityService:
    """Coordinates starting, inspecting, re-running, and cancelling virality analysis."""

    def __init__(
        self,
        *,
        virality_repo: ViralityRepository,
        story_repo: StoryRepository,
        analysis_repo: AnalysisRepository,
        project_repo: ProjectRepository,
        storage: StoragePort,
        pipeline: ViralityPipeline | None = None,
        on_complete: CompletionHook | None = None,
    ) -> None:
        self._virality_repo = virality_repo
        self._story_repo = story_repo
        self._analysis_repo = analysis_repo
        self._project_repo = project_repo
        self._storage = storage
        self._on_complete = on_complete
        self._pipeline = pipeline or ViralityPipeline(
            build_default_virality_analyzers(), virality_repo
        )

    # ----------------------------------------------------------------- start

    async def start(self, project: Project, *, restart: bool = False) -> ViralityAnalysis:
        """Begin (or resume) virality analysis for ``project`` as a background task.

        If a run is already in flight, the existing assessment is returned rather
        than starting a duplicate.
        """

        if project.id in _RUNS and not restart and _RUNS[project.id].task is not None:
            existing = await self._virality_repo.load(project.id)
            if existing is not None:
                return existing

        run = _Run()
        _RUNS[project.id] = run
        run.task = asyncio.create_task(self._run(project, run))
        await asyncio.sleep(0)  # let the task persist its initial index
        virality = await self._virality_repo.load(project.id)
        if virality is not None:
            return virality
        return await self._wait_for_index(project.id)

    async def _run(self, project: Project, run: _Run) -> None:
        try:
            analysis = await self._analysis_repo.load(project.id)
            story = await self._story_repo.load(project.id)
            virality = await self._pipeline.run(
                project,
                self._storage,
                analysis=analysis,
                story=story,
                cancel_event=run.cancel_event,
            )
            if self._on_complete is not None and virality.status.value == "completed":
                try:
                    await self._on_complete(project, virality)
                except Exception as exc:  # never let the hook break the analysis
                    log.error(
                        "virality_on_complete_error",
                        project_id=project.id,
                        error=str(exc),
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            log.info("virality_task_cancelled", project_id=project.id)
            raise
        except Exception as exc:  # background task must not crash silently
            log.error(
                "virality_task_error",
                project_id=project.id,
                error=str(exc),
                exc_info=True,
            )
        finally:
            _RUNS.pop(project.id, None)

    async def _wait_for_index(self, project_id: str) -> ViralityAnalysis:
        for _ in range(50):
            virality = await self._virality_repo.load(project_id)
            if virality is not None:
                return virality
            await asyncio.sleep(0.02)
        raise NotFoundError(
            "Virality analysis could not be initialized.", details={"id": project_id}
        )

    # ------------------------------------------------------------------ read

    async def get_virality(self, project_id: str) -> ViralityAnalysis | None:
        """Return the current virality analysis for a project, or ``None``."""

        return await self._virality_repo.load(project_id)

    async def get_summary(self, project_id: str) -> dict[str, Any] | None:
        """Return the aggregated virality summary, or ``None`` if not produced."""

        virality = await self._virality_repo.load(project_id)
        if virality is None:
            return None
        summary_stage = virality.stage("virality_summary")
        if summary_stage is None or summary_stage.status.value != "completed":
            return None
        return summary_stage.data

    def is_running(self, project_id: str) -> bool:
        """Whether a background virality run is currently tracked for the project."""

        run = _RUNS.get(project_id)
        return run is not None and run.task is not None and not run.task.done()

    # ---------------------------------------------------------------- rerun

    async def rerun_stage(self, project: Project, stage: str) -> ViralityAnalysis:
        """Re-run a single virality stage, leaving the others' results untouched."""

        if stage not in VIRALITY_STAGE_ORDER:
            raise ValidationError("Unknown virality stage.", details={"stage": stage})
        analysis = await self._analysis_repo.load(project.id)
        story = await self._story_repo.load(project.id)
        return await self._pipeline.run(
            project, self._storage, analysis=analysis, story=story, only={stage}
        )

    # --------------------------------------------------------------- cancel

    async def cancel(self, project_id: str) -> bool:
        """Request cancellation of an in-flight run. Returns whether one existed."""

        run = _RUNS.get(project_id)
        if run is None:
            return False
        run.cancel_event.set()
        log.info("virality_cancel_requested", project_id=project_id)
        return True

    # --------------------------------------------------------------- delete

    async def delete(self, project_id: str) -> None:
        """Cancel any run and delete all virality artifacts (idempotent)."""

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
                    "virality_delete_drain_incomplete",
                    project_id=project_id,
                    error=str(exc),
                )
        await self._virality_repo.delete(project_id)

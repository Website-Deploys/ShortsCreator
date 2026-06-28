"""The story service - the application boundary for narrative understanding.

This service owns the *lifecycle* of a project's story analysis: starting it in
the background (typically right after the Cognitive Engine finishes), reporting
its state, re-running a single stage, cancelling an in-flight run, and exposing
the engineering summary. It coordinates the story pipeline, the story repository,
and the cognitive analysis repository (whose output is the story pipeline's
input).

Background runs are tracked in a small process-wide registry keyed by project
id, exactly like the Cognitive Engine's service - keeping the MVP free of an
external task queue while remaining honest about what is genuinely running. When
a distributed worker tier is introduced, this service is the single place that
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
from olympus.domain.entities.project import Project
from olympus.domain.entities.story import STORY_STAGE_ORDER, StoryAnalysis
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.services.runs import begin_or_reuse_run
from olympus.story import StoryPipeline, build_default_story_analyzers

log = get_logger(__name__)

# An optional hook invoked after a run completes successfully. Used to chain the
# Virality Engine after the Story Engine without coupling this service to it.
CompletionHook = Callable[[Project, StoryAnalysis], Awaitable[None]]


@dataclass(slots=True)
class _Run:
    """A tracked background story run for one project."""

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


# Process-wide registry of in-flight story runs (shared across service instances).
_RUNS: dict[str, _Run] = {}


class StoryService:
    """Coordinates starting, inspecting, re-running, and cancelling story analysis."""

    def __init__(
        self,
        *,
        story_repo: StoryRepository,
        analysis_repo: AnalysisRepository,
        project_repo: ProjectRepository,
        storage: StoragePort,
        pipeline: StoryPipeline | None = None,
        on_complete: CompletionHook | None = None,
    ) -> None:
        self._story_repo = story_repo
        self._analysis_repo = analysis_repo
        self._project_repo = project_repo
        self._storage = storage
        self._on_complete = on_complete
        self._pipeline = pipeline or StoryPipeline(
            build_default_story_analyzers(), story_repo
        )

    # ----------------------------------------------------------------- start

    async def start(self, project: Project, *, restart: bool = False) -> StoryAnalysis:
        """Begin (or resume) story analysis for ``project`` as a background task.

        If a run is already in flight, the existing story analysis is returned
        rather than starting a duplicate.
        """

        existing, _run = await begin_or_reuse_run(
            scope="story",
            project_id=project.id,
            runs=_RUNS,
            make_run=_Run,
            loader=lambda: self._story_repo.load(project.id),
            spawn=lambda r: asyncio.create_task(self._run(project, r)),
            restart=restart,
        )
        if existing is not None:
            return existing
        await asyncio.sleep(0)  # let the task persist its initial index
        story = await self._story_repo.load(project.id)
        if story is not None:
            return story
        return await self._wait_for_index(project.id)

    async def _run(self, project: Project, run: _Run) -> None:
        try:
            analysis = await self._analysis_repo.load(project.id)
            story = await self._pipeline.run(
                project,
                self._storage,
                analysis=analysis,
                cancel_event=run.cancel_event,
            )
            # Chain the next intelligence layer (the Virality Engine) once the
            # Story Engine has genuinely finished. Failures here never affect the
            # completed story analysis.
            if self._on_complete is not None and story.status.value == "completed":
                try:
                    await self._on_complete(project, story)
                except Exception as exc:  # never let the hook break the analysis
                    log.error(
                        "story_on_complete_error",
                        project_id=project.id,
                        error=str(exc),
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            log.info("story_task_cancelled", project_id=project.id)
            raise
        except Exception as exc:  # background task must not crash silently
            log.error(
                "story_task_error",
                project_id=project.id,
                error=str(exc),
                exc_info=True,
            )
        finally:
            _RUNS.pop(project.id, None)

    async def _wait_for_index(self, project_id: str) -> StoryAnalysis:
        for _ in range(50):
            story = await self._story_repo.load(project_id)
            if story is not None:
                return story
            await asyncio.sleep(0.02)
        raise NotFoundError(
            "Story analysis could not be initialized.", details={"id": project_id}
        )

    # ------------------------------------------------------------------ read

    async def get_story(self, project_id: str) -> StoryAnalysis | None:
        """Return the current story analysis for a project, or ``None``."""

        return await self._story_repo.load(project_id)

    async def get_summary(self, project_id: str) -> dict[str, Any] | None:
        """Return the engineering story summary, or ``None`` if not produced."""

        story = await self._story_repo.load(project_id)
        if story is None:
            return None
        summary_stage = story.stage("story_summary")
        if summary_stage is None or summary_stage.status.value != "completed":
            return None
        return summary_stage.data

    def is_running(self, project_id: str) -> bool:
        """Whether a background story run is currently tracked for the project."""

        run = _RUNS.get(project_id)
        return run is not None and run.task is not None and not run.task.done()

    # ---------------------------------------------------------------- rerun

    async def rerun_stage(self, project: Project, stage: str) -> StoryAnalysis:
        """Re-run a single story stage, leaving the others' results untouched."""

        if stage not in STORY_STAGE_ORDER:
            raise ValidationError("Unknown story stage.", details={"stage": stage})
        analysis = await self._analysis_repo.load(project.id)
        return await self._pipeline.run(
            project, self._storage, analysis=analysis, only={stage}
        )

    # --------------------------------------------------------------- cancel

    async def cancel(self, project_id: str) -> bool:
        """Request cancellation of an in-flight run. Returns whether one existed."""

        run = _RUNS.get(project_id)
        if run is None:
            return False
        run.cancel_event.set()
        log.info("story_cancel_requested", project_id=project_id)
        return True

    # --------------------------------------------------------------- delete

    async def delete(self, project_id: str) -> None:
        """Cancel any run and delete all story artifacts (idempotent)."""

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
                    "story_delete_drain_incomplete",
                    project_id=project_id,
                    error=str(exc),
                )
        await self._story_repo.delete(project_id)

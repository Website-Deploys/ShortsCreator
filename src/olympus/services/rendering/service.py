"""The Rendering service - the application boundary for render execution.

This service owns the *lifecycle* of a project's render run: starting it in the
background, reporting its status and logs, returning the validation report and
the published render manifest, resolving a rendered clip for download, re-running
a single stage, and cancelling an in-flight run. It coordinates the render
pipeline, the render-run repository, the render-manifest store (the output
contract), the replaceable clip renderer, and the upstream engines' repositories
(chiefly Editing, whose timelines are the render inputs).

On a successful render (a manifest published with real rendered clips) it invokes
an optional completion hook - wired in the API layer to start the Optimization
Engine - realising the Rendering -> Optimization chain. It never makes creative
decisions and never modifies any upstream output.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.contracts.analysis import AnalysisRepository
from olympus.domain.contracts.editing import EditingRepository
from olympus.domain.contracts.planning import PlanningRepository
from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.render_pipeline import RenderRunRepository, RenderSettings
from olympus.domain.contracts.rendering import ClipRenderer, RenderManifestStore
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.story import StoryRepository
from olympus.domain.contracts.virality import ViralityRepository
from olympus.domain.entities.project import Project
from olympus.domain.entities.render_pipeline import RENDER_STAGE_ORDER, RenderRun
from olympus.domain.entities.rendering import RenderManifest
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.rendering import RenderPipeline, build_default_render_stages

log = get_logger(__name__)

# Invoked after a run that produced a real manifest (chains the Optimization
# Engine). Kept optional so the engine is usable standalone and in tests.
CompletionHook = Callable[[Project, RenderRun], Awaitable[None]]


@dataclass(slots=True)
class _Run:
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


_RUNS: dict[str, _Run] = {}


class RenderingService:
    """Coordinates starting, inspecting, re-running, and cancelling renders."""

    def __init__(
        self,
        *,
        render_run_repo: RenderRunRepository,
        manifest_store: RenderManifestStore,
        renderer: ClipRenderer,
        editing_repo: EditingRepository,
        planning_repo: PlanningRepository,
        virality_repo: ViralityRepository,
        story_repo: StoryRepository,
        analysis_repo: AnalysisRepository,
        project_repo: ProjectRepository,
        storage: StoragePort,
        settings: RenderSettings | None = None,
        pipeline: RenderPipeline | None = None,
        on_complete: CompletionHook | None = None,
    ) -> None:
        self._run_repo = render_run_repo
        self._manifest_store = manifest_store
        self._renderer = renderer
        self._editing_repo = editing_repo
        self._planning_repo = planning_repo
        self._virality_repo = virality_repo
        self._story_repo = story_repo
        self._analysis_repo = analysis_repo
        self._project_repo = project_repo
        self._storage = storage
        self._settings = settings or RenderSettings()
        self._on_complete = on_complete
        self._pipeline = pipeline or RenderPipeline(build_default_render_stages(), render_run_repo)

    # ----------------------------------------------------------------- start

    async def start(self, project: Project, *, restart: bool = False) -> RenderRun:
        """Begin (or resume) rendering for ``project`` as a background task."""

        if project.id in _RUNS and not restart and _RUNS[project.id].task is not None:
            existing = await self._run_repo.load(project.id)
            if existing is not None:
                return existing

        run = _Run()
        _RUNS[project.id] = run
        run.task = asyncio.create_task(self._run(project, run))
        await asyncio.sleep(0)
        existing = await self._run_repo.load(project.id)
        return existing if existing is not None else await self._wait_for_index(project.id)

    async def _run(self, project: Project, run: _Run) -> None:
        try:
            editing = await self._editing_repo.load(project.id)
            analysis = await self._analysis_repo.load(project.id)
            story = await self._story_repo.load(project.id)
            virality = await self._virality_repo.load(project.id)
            planning = await self._planning_repo.load(project.id)
            result = await self._pipeline.run(
                project,
                self._storage,
                self._renderer,
                self._manifest_store,
                settings=self._settings,
                editing=editing,
                analysis=analysis,
                story=story,
                virality=virality,
                planning=planning,
                cancel_event=run.cancel_event,
            )
            if self._on_complete is not None and self._manifest_produced(result):
                try:
                    await self._on_complete(project, result)
                except Exception as exc:  # never let the hook break the run
                    log.error(
                        "render_on_complete_error",
                        project_id=project.id,
                        error=str(exc),
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            log.info("render_task_cancelled", project_id=project.id)
            raise
        except Exception as exc:  # background task must not crash silently
            log.error(
                "render_task_error",
                project_id=project.id,
                error=str(exc),
                exc_info=True,
            )
        finally:
            _RUNS.pop(project.id, None)

    @staticmethod
    def _manifest_produced(run: RenderRun) -> bool:
        """Whether a real manifest with rendered clips was published."""

        stage = run.stage("generate_render_manifest")
        if stage is None or stage.status.value != "completed":
            return False
        return bool(stage.data.get("written")) and int(stage.data.get("clip_count", 0)) > 0

    async def _wait_for_index(self, project_id: str) -> RenderRun:
        for _ in range(50):
            run = await self._run_repo.load(project_id)
            if run is not None:
                return run
            await asyncio.sleep(0.02)
        raise NotFoundError("Render run could not be initialized.", details={"id": project_id})

    # ------------------------------------------------------------------ read

    async def get_run(self, project_id: str) -> RenderRun | None:
        """Return the current render run for a project, or ``None``."""

        return await self._run_repo.load(project_id)

    async def manifest(self, project_id: str) -> RenderManifest | None:
        """Return the published render manifest, or ``None`` if none exists."""

        return await self._manifest_store.load(project_id)

    async def validation_report(self, project_id: str) -> dict[str, Any] | None:
        """Return the final validation report, or ``None`` if not produced."""

        run = await self._run_repo.load(project_id)
        if run is None:
            return None
        stage = run.stage("final_validation")
        if stage is None or stage.status.value != "completed":
            return None
        return stage.data

    async def logs(self, project_id: str) -> list[dict[str, Any]] | None:
        """Return per-stage render logs (in pipeline order), or ``None``."""

        run = await self._run_repo.load(project_id)
        if run is None:
            return None
        out: list[dict[str, Any]] = []
        for stage in run.stages:
            lines = stage.logs
            if lines or stage.reason or stage.error:
                out.append(
                    {
                        "stage": stage.stage,
                        "status": stage.status.value,
                        "lines": lines,
                        "reason": stage.reason,
                        "error": stage.error,
                    }
                )
        return out

    async def resolve_clip(self, project_id: str, clip_id: str) -> str | None:
        """Return the storage key of a rendered clip, or ``None`` if not rendered."""

        manifest = await self._manifest_store.load(project_id)
        if manifest is None:
            return None
        render = manifest.render(clip_id)
        if render is None or not await self._storage.exists(render.storage_key):
            return None
        return render.storage_key

    def is_running(self, project_id: str) -> bool:
        run = _RUNS.get(project_id)
        return run is not None and run.task is not None and not run.task.done()

    # ---------------------------------------------------------------- rerun

    async def rerun_stage(self, project: Project, stage: str) -> RenderRun:
        """Re-run a single render stage, leaving the others untouched."""

        if stage not in RENDER_STAGE_ORDER:
            raise ValidationError("Unknown render stage.", details={"stage": stage})
        editing = await self._editing_repo.load(project.id)
        analysis = await self._analysis_repo.load(project.id)
        story = await self._story_repo.load(project.id)
        virality = await self._virality_repo.load(project.id)
        planning = await self._planning_repo.load(project.id)
        return await self._pipeline.run(
            project,
            self._storage,
            self._renderer,
            self._manifest_store,
            settings=self._settings,
            editing=editing,
            analysis=analysis,
            story=story,
            virality=virality,
            planning=planning,
            only={stage},
        )

    # --------------------------------------------------------------- cancel

    async def cancel(self, project_id: str) -> bool:
        run = _RUNS.get(project_id)
        if run is None:
            return False
        run.cancel_event.set()
        log.info("render_cancel_requested", project_id=project_id)
        return True

    # --------------------------------------------------------------- delete

    async def delete(self, project_id: str) -> None:
        """Cancel any run and delete all render artifacts (idempotent)."""

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
                    "rendering_delete_drain_incomplete",
                    project_id=project_id,
                    error=str(exc),
                )
        await self._run_repo.delete(project_id)
        await self._manifest_store.delete(project_id)

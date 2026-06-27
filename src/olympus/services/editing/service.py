"""The Editing service - the application boundary for edit timelines.

This service owns the *lifecycle* of a project's editing analysis: starting it in
the background (typically right after the Clip Planner finishes), reporting its
state, listing/fetching individual timelines, returning a clip's timeline events
and the validation report, re-running a single stage, and cancelling an
in-flight run. It coordinates the editing pipeline, the editing repository, and
the Cognitive + Story + Virality + Clip Planner repositories (whose outputs are
the pipeline's only inputs).

Background runs are tracked in a small process-wide registry keyed by project id,
exactly like the other engines' services. It renders nothing and exports nothing.
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
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.story import StoryRepository
from olympus.domain.contracts.virality import ViralityRepository
from olympus.domain.entities.editing import EDITING_STAGE_ORDER, EditingAnalysis
from olympus.domain.entities.project import Project
from olympus.editing import EditingPipeline, build_default_editing_analyzers
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger

log = get_logger(__name__)

# An optional hook invoked after a run completes successfully (kept for symmetry
# with the other engines, so a future Render/Export engine could chain after the
# Editing Engine).
CompletionHook = Callable[[Project, EditingAnalysis], Awaitable[None]]


@dataclass(slots=True)
class _Run:
    """A tracked background editing run for one project."""

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


# Process-wide registry of in-flight editing runs (shared across instances).
_RUNS: dict[str, _Run] = {}


class EditingService:
    """Coordinates starting, inspecting, listing, re-running, and cancelling timelines."""

    def __init__(
        self,
        *,
        editing_repo: EditingRepository,
        planning_repo: PlanningRepository,
        virality_repo: ViralityRepository,
        story_repo: StoryRepository,
        analysis_repo: AnalysisRepository,
        project_repo: ProjectRepository,
        storage: StoragePort,
        pipeline: EditingPipeline | None = None,
        on_complete: CompletionHook | None = None,
    ) -> None:
        self._editing_repo = editing_repo
        self._planning_repo = planning_repo
        self._virality_repo = virality_repo
        self._story_repo = story_repo
        self._analysis_repo = analysis_repo
        self._project_repo = project_repo
        self._storage = storage
        self._on_complete = on_complete
        self._pipeline = pipeline or EditingPipeline(
            build_default_editing_analyzers(), editing_repo
        )

    # ----------------------------------------------------------------- start

    async def start(self, project: Project, *, restart: bool = False) -> EditingAnalysis:
        """Begin (or resume) editing for ``project`` as a background task."""

        if project.id in _RUNS and not restart and _RUNS[project.id].task is not None:
            existing = await self._editing_repo.load(project.id)
            if existing is not None:
                return existing

        run = _Run()
        _RUNS[project.id] = run
        run.task = asyncio.create_task(self._run(project, run))
        await asyncio.sleep(0)  # let the task persist its initial index
        editing = await self._editing_repo.load(project.id)
        if editing is not None:
            return editing
        return await self._wait_for_index(project.id)

    async def _run(self, project: Project, run: _Run) -> None:
        try:
            analysis = await self._analysis_repo.load(project.id)
            story = await self._story_repo.load(project.id)
            virality = await self._virality_repo.load(project.id)
            planning = await self._planning_repo.load(project.id)
            editing = await self._pipeline.run(
                project,
                self._storage,
                analysis=analysis,
                story=story,
                virality=virality,
                planning=planning,
                cancel_event=run.cancel_event,
            )
            if self._on_complete is not None and editing.status.value == "completed":
                try:
                    await self._on_complete(project, editing)
                except Exception as exc:  # never let the hook break the run
                    log.error("editing_on_complete_error", project_id=project.id, error=str(exc))
        except asyncio.CancelledError:
            log.info("editing_task_cancelled", project_id=project.id)
            raise
        except Exception as exc:  # background task must not crash silently
            log.error("editing_task_error", project_id=project.id, error=str(exc))
        finally:
            _RUNS.pop(project.id, None)

    async def _wait_for_index(self, project_id: str) -> EditingAnalysis:
        for _ in range(50):
            editing = await self._editing_repo.load(project_id)
            if editing is not None:
                return editing
            await asyncio.sleep(0.02)
        raise NotFoundError(
            "Editing analysis could not be initialized.", details={"id": project_id}
        )

    # ------------------------------------------------------------------ read

    async def get_editing(self, project_id: str) -> EditingAnalysis | None:
        """Return the current editing analysis for a project, or ``None``."""

        return await self._editing_repo.load(project_id)

    async def _validation_stage(self, project_id: str) -> dict[str, Any] | None:
        editing = await self._editing_repo.load(project_id)
        if editing is None:
            return None
        stage = editing.stage("timeline_validation")
        if stage is None or stage.status.value != "completed":
            # Terminal-but-unvalidated still yields an honest empty result.
            if editing.status.value in ("completed", "failed", "cancelled"):
                return {"timelines": [], "report": {"valid": True, "clips": [], "issue_count": 0}}
            return None
        return stage.data

    async def list_timelines(self, project_id: str) -> list[dict[str, Any]] | None:
        """Return the assembled timelines (zero is a valid outcome), or ``None``."""

        data = await self._validation_stage(project_id)
        if data is None:
            return None
        timelines = data.get("timelines")
        return timelines if isinstance(timelines, list) else []

    async def get_timeline(self, project_id: str, clip_id: str) -> dict[str, Any] | None:
        """Return a single clip's complete timeline, or ``None`` if not found."""

        timelines = await self.list_timelines(project_id)
        if not timelines:
            return None
        return next((t for t in timelines if t.get("clip_id") == clip_id), None)

    async def timeline_events(self, project_id: str, clip_id: str) -> list[dict[str, Any]] | None:
        """Return a clip's events flattened across all tracks (track on each), or None."""

        timeline = await self.get_timeline(project_id, clip_id)
        if timeline is None:
            return None
        events: list[dict[str, Any]] = []
        for track in timeline.get("tracks", []):
            kind = track.get("kind")
            for ev in track.get("events", []):
                events.append({**ev, "track": kind})
        events.sort(key=lambda e: e.get("start") or 0.0)
        return events

    async def validation_report(self, project_id: str) -> dict[str, Any] | None:
        """Return the timeline validation report, or ``None`` if not produced."""

        data = await self._validation_stage(project_id)
        if data is None:
            return None
        report = data.get("report")
        return report if isinstance(report, dict) else None

    def is_running(self, project_id: str) -> bool:
        """Whether a background editing run is currently tracked for the project."""

        run = _RUNS.get(project_id)
        return run is not None and run.task is not None and not run.task.done()

    # ---------------------------------------------------------------- rerun

    async def rerun_stage(self, project: Project, stage: str) -> EditingAnalysis:
        """Re-run a single editing stage, leaving the others' results untouched."""

        if stage not in EDITING_STAGE_ORDER:
            raise ValidationError("Unknown editing stage.", details={"stage": stage})
        analysis = await self._analysis_repo.load(project.id)
        story = await self._story_repo.load(project.id)
        virality = await self._virality_repo.load(project.id)
        planning = await self._planning_repo.load(project.id)
        return await self._pipeline.run(
            project,
            self._storage,
            analysis=analysis,
            story=story,
            virality=virality,
            planning=planning,
            only={stage},
        )

    # --------------------------------------------------------------- cancel

    async def cancel(self, project_id: str) -> bool:
        """Request cancellation of an in-flight run. Returns whether one existed."""

        run = _RUNS.get(project_id)
        if run is None:
            return False
        run.cancel_event.set()
        log.info("editing_cancel_requested", project_id=project_id)
        return True

    # --------------------------------------------------------------- delete

    async def delete(self, project_id: str) -> None:
        """Cancel any run and delete all editing artifacts (idempotent)."""

        await self.cancel(project_id)
        await self._editing_repo.delete(project_id)

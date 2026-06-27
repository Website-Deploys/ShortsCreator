"""The analysis service - the application boundary for video understanding.

This service owns the *lifecycle* of a project's analysis: kicking it off in the
background after upload, reporting its current state, re-running a single stage,
and cancelling an in-flight run. It coordinates the pipeline, the analysis
repository, the project repository (to reflect ``ANALYZING`` / ``ANALYZED``
status honestly), and the configured transcription provider.

Background runs are tracked in a small in-process registry keyed by project id,
holding the running task and a cooperative cancellation event. This keeps the
MVP free of an external task queue while remaining honest: the registry only
reflects work that is genuinely running in this process. When the system grows a
distributed worker tier, this service is the single place that changes - the
pipeline, repository, and analyzers are untouched.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from olympus.analysis import AnalysisPipeline, build_default_analyzers
from olympus.domain.contracts.analysis import AnalysisRepository
from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import STAGE_ORDER, Analysis, AnalysisStatus
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.utils import utc_now

log = get_logger(__name__)


@dataclass(slots=True)
class _Run:
    """A tracked background analysis run for one project."""

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


# Process-wide registry of in-flight runs. Shared across service instances so a
# request handled by a fresh, per-request service can still cancel a run started
# by an earlier request.
_RUNS: dict[str, _Run] = {}


class AnalysisService:
    """Coordinates starting, inspecting, re-running, and cancelling analyses."""

    def __init__(
        self,
        *,
        analysis_repo: AnalysisRepository,
        project_repo: ProjectRepository,
        storage: StoragePort,
        transcription_provider: object | None = None,
        pipeline: AnalysisPipeline | None = None,
    ) -> None:
        self._analysis_repo = analysis_repo
        self._project_repo = project_repo
        self._storage = storage
        self._transcription_provider = transcription_provider
        self._pipeline = pipeline or AnalysisPipeline(
            build_default_analyzers(), analysis_repo
        )

    # ----------------------------------------------------------------- start

    async def start(self, project: Project, *, restart: bool = False) -> Analysis:
        """Begin (or resume) analysis for ``project`` as a background task.

        If a run is already in flight for the project, the existing analysis is
        returned rather than starting a duplicate. Returns the analysis as it
        currently stands (freshly initialized to ``RUNNING`` on a new start).
        """

        if project.id in _RUNS and not (_RUNS[project.id].task or restart):
            existing = await self._analysis_repo.load(project.id)
            if existing is not None:
                return existing

        run = _Run()
        _RUNS[project.id] = run

        await self._set_project_status(project.id, ProjectStatus.ANALYZING)

        run.task = asyncio.create_task(self._run(project, run))
        # Yield once so the task starts and the index exists before we return.
        await asyncio.sleep(0)
        analysis = await self._analysis_repo.load(project.id)
        if analysis is not None:
            return analysis
        return await self._run_until_index(project.id)

    async def _run(self, project: Project, run: _Run) -> None:
        try:
            analysis = await self._pipeline.run(
                project,
                self._storage,
                transcription_provider=self._transcription_provider,
                cancel_event=run.cancel_event,
            )
            await self._reflect_status(project.id, analysis)
        except asyncio.CancelledError:
            log.info("analysis_task_cancelled", project_id=project.id)
            raise
        except Exception as exc:
            log.error("analysis_task_error", project_id=project.id, error=str(exc))
        finally:
            _RUNS.pop(project.id, None)

    async def _run_until_index(self, project_id: str) -> Analysis:
        """Wait briefly for the background task to persist the initial index."""

        for _ in range(50):
            analysis = await self._analysis_repo.load(project_id)
            if analysis is not None:
                return analysis
            await asyncio.sleep(0.02)
        raise NotFoundError("Analysis could not be initialized.", details={"id": project_id})

    # ------------------------------------------------------------------ read

    async def get_analysis(self, project_id: str) -> Analysis | None:
        """Return the current analysis for a project, or ``None`` if absent."""

        return await self._analysis_repo.load(project_id)

    def is_running(self, project_id: str) -> bool:
        """Whether a background run is currently tracked for the project."""

        run = _RUNS.get(project_id)
        return run is not None and run.task is not None and not run.task.done()

    # ---------------------------------------------------------------- rerun

    async def rerun_stage(self, project: Project, stage: str) -> Analysis:
        """Re-run a single stage, leaving the others' results untouched.

        Dependencies are read from the already-persisted analysis, so a stage can
        be refreshed in isolation without re-running the whole pipeline.
        """

        if stage not in STAGE_ORDER:
            raise ValidationError("Unknown analysis stage.", details={"stage": stage})
        await self._set_project_status(project.id, ProjectStatus.ANALYZING)
        analysis = await self._pipeline.run(
            project,
            self._storage,
            transcription_provider=self._transcription_provider,
            only={stage},
        )
        await self._reflect_status(project.id, analysis)
        return analysis

    # --------------------------------------------------------------- cancel

    async def cancel(self, project_id: str) -> bool:
        """Request cancellation of an in-flight run. Returns whether one was found."""

        run = _RUNS.get(project_id)
        if run is None:
            return False
        run.cancel_event.set()
        log.info("analysis_cancel_requested", project_id=project_id)
        return True

    # --------------------------------------------------------------- delete

    async def delete(self, project_id: str) -> None:
        """Cancel any run and delete all analysis artifacts (idempotent)."""

        await self.cancel(project_id)
        await self._analysis_repo.delete(project_id)

    # --------------------------------------------------------------- helpers

    async def _set_project_status(self, project_id: str, status: ProjectStatus) -> None:
        project = await self._project_repo.get(project_id)
        if project is None or project.status == status:
            return
        project.status = status
        project.updated_at = utc_now()
        await self._project_repo.save(project)

    async def _reflect_status(self, project_id: str, analysis: Analysis) -> None:
        """Map the overall analysis status onto the project's honest status."""

        mapping = {
            AnalysisStatus.COMPLETED: ProjectStatus.ANALYZED,
            AnalysisStatus.FAILED: ProjectStatus.FAILED,
            AnalysisStatus.RUNNING: ProjectStatus.ANALYZING,
        }
        target = mapping.get(analysis.status)
        if target is not None:
            await self._set_project_status(project_id, target)

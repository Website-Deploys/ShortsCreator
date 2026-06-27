"""The Render pipeline - the Rendering Engine's orchestrator.

Runs the ordered :class:`RenderStageAnalyzer` stages over a project's editing
timelines and source media, executing them (via a replaceable
:class:`ClipRenderer`) into real encoded files and a published render manifest.
It is an independent sibling of the other engines' pipelines and owns the same
orchestration guarantees:

- **Persist after every stage** (work is never lost).
- **Resume** (skip stages already completed at the current stage version).
- **Retries** for genuine errors; an honest ``UNAVAILABLE`` is never retried.
- **Cancellation** between stages (remaining stages marked ``CANCELLED``).
- **Targeted single-stage reruns** via ``only=``.

It performs execution only and never fabricates output: when the renderer or a
dependency is unavailable, the relevant stages record honest ``UNAVAILABLE``
reasons and no manifest is published.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from olympus.domain.contracts.render_pipeline import (
    RenderOutcome,
    RenderRunRepository,
    RenderSettings,
    RenderStageAnalyzer,
    RenderStageContext,
)
from olympus.domain.contracts.rendering import ClipRenderer, RenderManifestStore
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis
from olympus.domain.entities.editing import EditingAnalysis
from olympus.domain.entities.planning import ClipPlanningAnalysis
from olympus.domain.entities.project import Project
from olympus.domain.entities.render_pipeline import (
    RENDER_STAGE_ORDER,
    RenderRun,
    RenderRunStatus,
    RenderStageResult,
    RenderStageStatus,
)
from olympus.domain.entities.story import StoryAnalysis
from olympus.domain.entities.virality import ViralityAnalysis
from olympus.platform.logging import get_logger
from olympus.rendering.stages import (
    ApplyBrollStage,
    ApplyCaptionsStage,
    ApplyCropsStage,
    ApplyJumpCutsStage,
    ApplyMusicStage,
    ApplyTransitionsStage,
    ApplyZoomsStage,
    AudioMixingStage,
    BuildAudioTimelineStage,
    BuildVideoTimelineStage,
    CleanupTemporaryFilesStage,
    FinalValidationStage,
    FullResolutionRenderStage,
    GenerateRenderManifestStage,
    LoadTimelineStage,
    PrepareWorkingDirectoryStage,
    RenderPreviewStage,
    RenderVerificationStage,
    ValidateSourceAssetsStage,
    ValidateTimelineStage,
)
from olympus.utils import utc_now

log = get_logger(__name__)

#: Bumped when the *set* or *ordering* of render stages changes.
RENDER_PIPELINE_VERSION = "1"

#: Retry budget for stages that raise or return FAILED. UNAVAILABLE is never
#: retried (it is the truth about the renderer/dependency, not a failure).
DEFAULT_MAX_RETRIES = 2

RenderProgressCallback = Callable[[RenderRun], None]


def build_default_render_stages() -> list[RenderStageAnalyzer]:
    """Return the twenty render stages in pipeline order.

    The order mirrors :data:`RENDER_STAGE_ORDER`; the pipeline validates this on
    construction so the two can never silently drift apart.
    """

    return [
        LoadTimelineStage(),
        ValidateTimelineStage(),
        ValidateSourceAssetsStage(),
        PrepareWorkingDirectoryStage(),
        BuildVideoTimelineStage(),
        BuildAudioTimelineStage(),
        ApplyJumpCutsStage(),
        ApplyZoomsStage(),
        ApplyCropsStage(),
        ApplyTransitionsStage(),
        ApplyCaptionsStage(),
        ApplyBrollStage(),
        ApplyMusicStage(),
        AudioMixingStage(),
        RenderPreviewStage(),
        FullResolutionRenderStage(),
        RenderVerificationStage(),
        GenerateRenderManifestStage(),
        CleanupTemporaryFilesStage(),
        FinalValidationStage(),
    ]


class RenderPipeline:
    """Orchestrates the ordered render stages into a persisted render run."""

    def __init__(
        self,
        stages: Iterable[RenderStageAnalyzer],
        repository: RenderRunRepository,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._stages = list(stages)
        self._repo = repository
        self._max_retries = max(0, max_retries)
        self._backoff = retry_backoff_seconds
        self._validate_order()

    def _validate_order(self) -> None:
        names = tuple(s.name for s in self._stages)
        if names != RENDER_STAGE_ORDER:
            raise ValueError(
                "Render stage ordering does not match RENDER_STAGE_ORDER: "
                f"{names} != {RENDER_STAGE_ORDER}"
            )

    async def run(
        self,
        project: Project,
        storage: StoragePort,
        renderer: ClipRenderer,
        manifest_store: RenderManifestStore,
        *,
        settings: RenderSettings | None = None,
        editing: EditingAnalysis | None = None,
        analysis: Analysis | None = None,
        story: StoryAnalysis | None = None,
        virality: ViralityAnalysis | None = None,
        planning: ClipPlanningAnalysis | None = None,
        cancel_event: asyncio.Event | None = None,
        on_progress: RenderProgressCallback | None = None,
        only: Iterable[str] | None = None,
    ) -> RenderRun:
        """Run (or resume) the render pipeline and return the run state."""

        only_set = set(only) if only is not None else None
        settings = settings or RenderSettings()
        run = await self._load_or_init(project.id)
        run.status = RenderRunStatus.RUNNING
        run.updated_at = utc_now()
        await self._repo.save_index(run)

        results: dict[str, RenderStageResult] = {s.stage: s for s in run.stages}
        cancelled = False

        for stage in self._stages:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if not self._should_run(stage, results.get(stage.name), only_set):
                continue

            result = await self._run_stage(
                stage,
                RenderStageContext(
                    project=project,
                    storage=storage,
                    renderer=renderer,
                    manifest_store=manifest_store,
                    settings=settings,
                    editing=editing,
                    analysis=analysis,
                    story=story,
                    virality=virality,
                    planning=planning,
                    results=results,
                ),
            )
            results[stage.name] = result
            self._replace_stage(run, result)
            run.updated_at = utc_now()
            await self._repo.save_stage(project.id, result)
            await self._repo.save_index(run)
            if on_progress is not None:
                on_progress(run)

        if cancelled:
            self._mark_remaining_cancelled(run)
            run.status = RenderRunStatus.CANCELLED
        else:
            run.status = self._overall_status(run)
        run.updated_at = utc_now()
        await self._repo.save_index(run)
        log.info("render_run_finished", project_id=project.id, status=run.status.value)
        return run

    async def _load_or_init(self, project_id: str) -> RenderRun:
        existing = await self._repo.load(project_id)
        if existing is not None:
            present = {s.stage for s in existing.stages}
            for name in RENDER_STAGE_ORDER:
                if name not in present:
                    existing.stages.append(RenderStageResult(stage=name))
            existing.stages.sort(key=lambda s: RENDER_STAGE_ORDER.index(s.stage))
            return existing
        now = utc_now()
        return RenderRun(
            project_id=project_id,
            pipeline_version=RENDER_PIPELINE_VERSION,
            status=RenderRunStatus.PENDING,
            created_at=now,
            updated_at=now,
            stages=[RenderStageResult(stage=name) for name in RENDER_STAGE_ORDER],
        )

    def _should_run(
        self,
        stage: RenderStageAnalyzer,
        existing: RenderStageResult | None,
        only_set: set[str] | None,
    ) -> bool:
        if only_set is not None:
            return stage.name in only_set
        return not (
            existing is not None
            and existing.status is RenderStageStatus.COMPLETED
            and existing.version == stage.version
        )

    async def _run_stage(
        self, stage: RenderStageAnalyzer, ctx: RenderStageContext
    ) -> RenderStageResult:
        result = RenderStageResult(
            stage=stage.name,
            status=RenderStageStatus.RUNNING,
            version=stage.version,
            started_at=utc_now(),
        )

        def report(value: float) -> None:
            result.progress = max(0.0, min(1.0, value))

        max_attempts = 1 + self._max_retries
        last_error: str | None = None
        for attempt in range(1, max_attempts + 1):
            result.attempts = attempt
            try:
                outcome = await stage.run(ctx, report)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "render_stage_error", stage=stage.name, attempt=attempt, error=last_error
                )
                if attempt < max_attempts:
                    await asyncio.sleep(self._backoff * attempt)
                    continue
                return self._finalize_failed(result, last_error)

            if outcome.status is RenderStageStatus.FAILED and attempt < max_attempts:
                last_error = outcome.reason or "Stage reported failure."
                log.warning(
                    "render_stage_failed_outcome",
                    stage=stage.name,
                    attempt=attempt,
                    reason=last_error,
                )
                await asyncio.sleep(self._backoff * attempt)
                continue

            return self._finalize(result, outcome)

        return self._finalize_failed(result, last_error or "Unknown error.")

    @staticmethod
    def _finalize(result: RenderStageResult, outcome: RenderOutcome) -> RenderStageResult:
        result.status = outcome.status
        result.data = outcome.data
        result.reason = outcome.reason
        result.completed_at = utc_now()
        if outcome.status is RenderStageStatus.COMPLETED:
            result.progress = 1.0
            result.error = None
        elif outcome.status is RenderStageStatus.FAILED:
            result.error = outcome.reason
        return result

    @staticmethod
    def _finalize_failed(result: RenderStageResult, error: str) -> RenderStageResult:
        result.status = RenderStageStatus.FAILED
        result.error = error
        result.completed_at = utc_now()
        return result

    @staticmethod
    def _replace_stage(run: RenderRun, result: RenderStageResult) -> None:
        for index, stage in enumerate(run.stages):
            if stage.stage == result.stage:
                run.stages[index] = result
                return
        run.stages.append(result)
        run.stages.sort(key=lambda s: RENDER_STAGE_ORDER.index(s.stage))

    @staticmethod
    def _mark_remaining_cancelled(run: RenderRun) -> None:
        for stage in run.stages:
            if stage.status in (RenderStageStatus.PENDING, RenderStageStatus.RUNNING):
                stage.status = RenderStageStatus.CANCELLED
                stage.completed_at = utc_now()

    @staticmethod
    def _overall_status(run: RenderRun) -> RenderRunStatus:
        """Derive honest overall status; a genuine FAILED stage is never hidden."""

        if any(s.status is RenderStageStatus.RUNNING for s in run.stages):
            return RenderRunStatus.RUNNING
        if any(s.status is RenderStageStatus.FAILED for s in run.stages):
            return RenderRunStatus.FAILED
        if run.stages and all(s.is_terminal for s in run.stages):
            if any(s.status is RenderStageStatus.CANCELLED for s in run.stages):
                return RenderRunStatus.CANCELLED
            return RenderRunStatus.COMPLETED
        return RenderRunStatus.PENDING

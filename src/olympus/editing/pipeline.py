"""The Editing pipeline - the Editing Engine's orchestrator.

Runs the ordered :class:`EditingAnalyzer` stages over a project's cognitive,
story, virality, and clip-planning output and turns the result into a durable,
evolving :class:`EditingAnalysis`. It is an independent sibling of the other
engines' pipelines and owns the same orchestration guarantees:

- **Persist after every stage** (work is never lost).
- **Resume** (skip stages already completed at the current stage version).
- **Retries** for genuine errors; an honest ``UNAVAILABLE`` is never retried.
- **Cancellation** between stages (remaining stages marked ``CANCELLED``).
- **Targeted single-stage reruns** via ``only=``.

It never fabricates output - it only records what the stages genuinely produced,
including honest "unavailable"/"unknown" reasons. It renders nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from olympus.domain.contracts.editing import (
    EditingAnalyzer,
    EditingOutcome,
    EditingRepository,
    EditingStageContext,
)
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis
from olympus.domain.entities.editing import (
    EDITING_STAGE_ORDER,
    EditingAnalysis,
    EditingStageResult,
    EditingStageStatus,
    EditingStatus,
)
from olympus.domain.entities.planning import ClipPlanningAnalysis
from olympus.domain.entities.project import Project
from olympus.domain.entities.story import StoryAnalysis
from olympus.domain.entities.virality import ViralityAnalysis
from olympus.editing.analyzers import (
    BrollPlannerAnalyzer,
    CaptionLayoutAnalyzer,
    CaptionTimingAnalyzer,
    CropPlannerAnalyzer,
    HookEnhancementAnalyzer,
    JumpCutDetectionAnalyzer,
    MusicPlannerAnalyzer,
    PanPlannerAnalyzer,
    RetentionPlannerAnalyzer,
    SilenceDetectionAnalyzer,
    SpeechCleanupAnalyzer,
    SubtitleSegmentationAnalyzer,
    TimelineInitializationAnalyzer,
    TimelineValidationAnalyzer,
    TransitionPlannerAnalyzer,
    ZoomPlannerAnalyzer,
)
from olympus.platform.logging import get_logger
from olympus.utils import utc_now

log = get_logger(__name__)

#: Bumped when the *set* or *ordering* of editing stages changes.
EDITING_PIPELINE_VERSION = "1"

#: Retry budget for stages that raise or return FAILED. UNAVAILABLE is never
#: retried (it is the truth about the evidence, not a failure).
DEFAULT_MAX_RETRIES = 2

EditingProgressCallback = Callable[[EditingAnalysis], None]


def build_default_editing_analyzers() -> list[EditingAnalyzer]:
    """Return the sixteen editing stages in pipeline order.

    The order mirrors :data:`EDITING_STAGE_ORDER`; the pipeline validates this on
    construction so the two can never silently drift apart.
    """

    return [
        TimelineInitializationAnalyzer(),
        SpeechCleanupAnalyzer(),
        JumpCutDetectionAnalyzer(),
        SilenceDetectionAnalyzer(),
        SubtitleSegmentationAnalyzer(),
        CaptionTimingAnalyzer(),
        CaptionLayoutAnalyzer(),
        ZoomPlannerAnalyzer(),
        PanPlannerAnalyzer(),
        CropPlannerAnalyzer(),
        HookEnhancementAnalyzer(),
        RetentionPlannerAnalyzer(),
        MusicPlannerAnalyzer(),
        TransitionPlannerAnalyzer(),
        BrollPlannerAnalyzer(),
        TimelineValidationAnalyzer(),
    ]


class EditingPipeline:
    """Orchestrates the ordered editing stages into a persisted set of timelines."""

    def __init__(
        self,
        analyzers: Iterable[EditingAnalyzer],
        repository: EditingRepository,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._analyzers = list(analyzers)
        self._repo = repository
        self._max_retries = max(0, max_retries)
        self._backoff = retry_backoff_seconds
        self._validate_order()

    def _validate_order(self) -> None:
        names = tuple(a.name for a in self._analyzers)
        if names != EDITING_STAGE_ORDER:
            raise ValueError(
                "Editing stage ordering does not match EDITING_STAGE_ORDER: "
                f"{names} != {EDITING_STAGE_ORDER}"
            )

    async def run(
        self,
        project: Project,
        storage: StoragePort,
        *,
        analysis: Analysis | None = None,
        story: StoryAnalysis | None = None,
        virality: ViralityAnalysis | None = None,
        planning: ClipPlanningAnalysis | None = None,
        cancel_event: asyncio.Event | None = None,
        on_progress: EditingProgressCallback | None = None,
        only: Iterable[str] | None = None,
    ) -> EditingAnalysis:
        """Run (or resume) the editing pipeline and return the timeline set."""

        only_set = set(only) if only is not None else None
        editing = await self._load_or_init(project.id)
        editing.status = EditingStatus.RUNNING
        editing.updated_at = utc_now()
        await self._repo.save_index(editing)

        results: dict[str, EditingStageResult] = {s.stage: s for s in editing.stages}
        cancelled = False

        for analyzer in self._analyzers:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            if not self._should_run(analyzer, results.get(analyzer.name), only_set):
                continue

            result = await self._run_stage(
                analyzer,
                EditingStageContext(
                    project=project,
                    storage=storage,
                    analysis=analysis,
                    story=story,
                    virality=virality,
                    planning=planning,
                    results=results,
                ),
            )
            results[analyzer.name] = result
            self._replace_stage(editing, result)
            editing.updated_at = utc_now()
            await self._repo.save_stage(project.id, result)
            await self._repo.save_index(editing)
            if on_progress is not None:
                on_progress(editing)

        if cancelled:
            self._mark_remaining_cancelled(editing)
            editing.status = EditingStatus.CANCELLED
        else:
            editing.status = self._overall_status(editing)
        editing.updated_at = utc_now()
        await self._repo.save_index(editing)
        log.info("editing_run_finished", project_id=project.id, status=editing.status.value)
        return editing

    async def _load_or_init(self, project_id: str) -> EditingAnalysis:
        existing = await self._repo.load(project_id)
        if existing is not None:
            present = {s.stage for s in existing.stages}
            for name in EDITING_STAGE_ORDER:
                if name not in present:
                    existing.stages.append(EditingStageResult(stage=name))
            existing.stages.sort(key=lambda s: EDITING_STAGE_ORDER.index(s.stage))
            return existing
        now = utc_now()
        return EditingAnalysis(
            project_id=project_id,
            pipeline_version=EDITING_PIPELINE_VERSION,
            status=EditingStatus.PENDING,
            created_at=now,
            updated_at=now,
            stages=[EditingStageResult(stage=name) for name in EDITING_STAGE_ORDER],
        )

    def _should_run(
        self,
        analyzer: EditingAnalyzer,
        existing: EditingStageResult | None,
        only_set: set[str] | None,
    ) -> bool:
        if only_set is not None:
            return analyzer.name in only_set
        return not (
            existing is not None
            and existing.status is EditingStageStatus.COMPLETED
            and existing.version == analyzer.version
        )

    async def _run_stage(
        self, analyzer: EditingAnalyzer, ctx: EditingStageContext
    ) -> EditingStageResult:
        result = EditingStageResult(
            stage=analyzer.name,
            status=EditingStageStatus.RUNNING,
            version=analyzer.version,
            started_at=utc_now(),
        )

        def report(value: float) -> None:
            result.progress = max(0.0, min(1.0, value))

        max_attempts = 1 + self._max_retries
        last_error: str | None = None
        for attempt in range(1, max_attempts + 1):
            result.attempts = attempt
            try:
                outcome = await analyzer.analyze(ctx, report)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "editing_stage_error", stage=analyzer.name, attempt=attempt, error=last_error
                )
                if attempt < max_attempts:
                    await asyncio.sleep(self._backoff * attempt)
                    continue
                return self._finalize_failed(result, last_error)

            if outcome.status is EditingStageStatus.FAILED and attempt < max_attempts:
                last_error = outcome.reason or "Stage reported failure."
                log.warning(
                    "editing_stage_failed_outcome",
                    stage=analyzer.name,
                    attempt=attempt,
                    reason=last_error,
                )
                await asyncio.sleep(self._backoff * attempt)
                continue

            return self._finalize(result, outcome)

        return self._finalize_failed(result, last_error or "Unknown error.")

    @staticmethod
    def _finalize(result: EditingStageResult, outcome: EditingOutcome) -> EditingStageResult:
        result.status = outcome.status
        result.data = outcome.data
        result.reason = outcome.reason
        result.completed_at = utc_now()
        if outcome.status is EditingStageStatus.COMPLETED:
            result.progress = 1.0
            result.error = None
        elif outcome.status is EditingStageStatus.FAILED:
            result.error = outcome.reason
        return result

    @staticmethod
    def _finalize_failed(result: EditingStageResult, error: str) -> EditingStageResult:
        result.status = EditingStageStatus.FAILED
        result.error = error
        result.completed_at = utc_now()
        return result

    @staticmethod
    def _replace_stage(editing: EditingAnalysis, result: EditingStageResult) -> None:
        for index, stage in enumerate(editing.stages):
            if stage.stage == result.stage:
                editing.stages[index] = result
                return
        editing.stages.append(result)
        editing.stages.sort(key=lambda s: EDITING_STAGE_ORDER.index(s.stage))

    @staticmethod
    def _mark_remaining_cancelled(editing: EditingAnalysis) -> None:
        for stage in editing.stages:
            if stage.status in (EditingStageStatus.PENDING, EditingStageStatus.RUNNING):
                stage.status = EditingStageStatus.CANCELLED
                stage.completed_at = utc_now()

    @staticmethod
    def _overall_status(editing: EditingAnalysis) -> EditingStatus:
        """Derive honest overall status; a genuine FAILED stage is never hidden."""

        if any(s.status is EditingStageStatus.RUNNING for s in editing.stages):
            return EditingStatus.RUNNING
        if any(s.status is EditingStageStatus.FAILED for s in editing.stages):
            return EditingStatus.FAILED
        if editing.stages and all(s.is_terminal for s in editing.stages):
            if any(s.status is EditingStageStatus.CANCELLED for s in editing.stages):
                return EditingStatus.CANCELLED
            return EditingStatus.COMPLETED
        return EditingStatus.PENDING

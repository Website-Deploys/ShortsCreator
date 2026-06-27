"""The Story pipeline - the Story Engine's orchestrator.

The Story pipeline runs the ordered :class:`StoryAnalyzer` stages over a
project's *cognitive understanding* and turns the result into a durable,
evolving :class:`StoryAnalysis`. It is an independent sibling of the Cognitive
Engine's pipeline and owns the same orchestration guarantees:

- **Persist after every stage** (work is never lost).
- **Resume** (skip stages already completed at the current analyzer version).
- **Retries** for genuine errors; an honest ``UNAVAILABLE`` is never retried.
- **Cancellation** between stages (remaining stages marked ``CANCELLED``).
- **Targeted single-stage reruns** via ``only=``.

It never fabricates output - it only records what the analyzers genuinely
derived, including their honest "unavailable" reasons and per-conclusion
confidence/evidence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.story import (
    StoryAnalyzer,
    StoryOutcome,
    StoryRepository,
    StoryStageContext,
)
from olympus.domain.entities.analysis import Analysis
from olympus.domain.entities.project import Project
from olympus.domain.entities.story import (
    STORY_STAGE_ORDER,
    StoryAnalysis,
    StoryStageResult,
    StoryStageStatus,
    StoryStatus,
)
from olympus.platform.logging import get_logger
from olympus.story.analyzers import (
    ContextDependenciesAnalyzer,
    EmotionalTurningPointsAnalyzer,
    HookDetectionAnalyzer,
    InformationDensityAnalyzer,
    NarrativeArcAnalyzer,
    NarrativeSegmentationAnalyzer,
    PayoffDetectionAnalyzer,
    StoryGraphAnalyzer,
    StorySummaryAnalyzer,
    TopicSegmentationAnalyzer,
)
from olympus.utils import utc_now

log = get_logger(__name__)

#: Bumped when the *set* or *ordering* of story stages changes.
STORY_PIPELINE_VERSION = "1"

#: Retry budget for stages that raise or return FAILED. UNAVAILABLE is never
#: retried (it is the truth about the inputs, not a failure).
DEFAULT_MAX_RETRIES = 2

StoryProgressCallback = Callable[[StoryAnalysis], None]


def build_default_story_analyzers() -> list[StoryAnalyzer]:
    """Return the ten story analyzers in pipeline order.

    The order mirrors :data:`STORY_STAGE_ORDER`; the pipeline validates this on
    construction so the two can never silently drift apart.
    """

    return [
        NarrativeSegmentationAnalyzer(),
        HookDetectionAnalyzer(),
        TopicSegmentationAnalyzer(),
        NarrativeArcAnalyzer(),
        PayoffDetectionAnalyzer(),
        EmotionalTurningPointsAnalyzer(),
        InformationDensityAnalyzer(),
        ContextDependenciesAnalyzer(),
        StoryGraphAnalyzer(),
        StorySummaryAnalyzer(),
    ]


class StoryPipeline:
    """Orchestrates the ordered story analyzers into a persisted understanding."""

    def __init__(
        self,
        analyzers: Iterable[StoryAnalyzer],
        repository: StoryRepository,
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
        if names != STORY_STAGE_ORDER:
            raise ValueError(
                "Story analyzer ordering does not match STORY_STAGE_ORDER: "
                f"{names} != {STORY_STAGE_ORDER}"
            )

    async def run(
        self,
        project: Project,
        storage: StoragePort,
        *,
        analysis: Analysis | None = None,
        cancel_event: asyncio.Event | None = None,
        on_progress: StoryProgressCallback | None = None,
        only: Iterable[str] | None = None,
    ) -> StoryAnalysis:
        """Run (or resume) the story pipeline and return the story analysis.

        Args:
            project: The project under analysis.
            storage: Storage backend for any large artifacts.
            analysis: The Cognitive Engine's output for this project (its
                transcript drives most stages). May be ``None``.
            cancel_event: Cooperative cancellation signal, checked between stages.
            on_progress: Optional callback invoked with the story analysis after
                each stage completes.
            only: Optional set of stage names to run *exclusively* (targeted
                single-stage reruns). When ``None``, normal resume rules apply.
        """

        only_set = set(only) if only is not None else None
        story = await self._load_or_init(project.id)
        story.status = StoryStatus.RUNNING
        story.updated_at = utc_now()
        await self._repo.save_index(story)

        results: dict[str, StoryStageResult] = {s.stage: s for s in story.stages}
        cancelled = False

        for analyzer in self._analyzers:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            if not self._should_run(analyzer, results.get(analyzer.name), only_set):
                continue

            result = await self._run_stage(
                analyzer,
                StoryStageContext(
                    project=project,
                    storage=storage,
                    analysis=analysis,
                    results=results,
                ),
            )
            results[analyzer.name] = result
            self._replace_stage(story, result)
            story.updated_at = utc_now()
            await self._repo.save_stage(project.id, result)
            await self._repo.save_index(story)
            if on_progress is not None:
                on_progress(story)

        if cancelled:
            self._mark_remaining_cancelled(story)
            story.status = StoryStatus.CANCELLED
        else:
            story.status = self._overall_status(story)
        story.updated_at = utc_now()
        await self._repo.save_index(story)
        log.info("story_run_finished", project_id=project.id, status=story.status.value)
        return story

    async def _load_or_init(self, project_id: str) -> StoryAnalysis:
        existing = await self._repo.load(project_id)
        if existing is not None:
            present = {s.stage for s in existing.stages}
            for name in STORY_STAGE_ORDER:
                if name not in present:
                    existing.stages.append(StoryStageResult(stage=name))
            existing.stages.sort(key=lambda s: STORY_STAGE_ORDER.index(s.stage))
            return existing
        now = utc_now()
        return StoryAnalysis(
            project_id=project_id,
            pipeline_version=STORY_PIPELINE_VERSION,
            status=StoryStatus.PENDING,
            created_at=now,
            updated_at=now,
            stages=[StoryStageResult(stage=name) for name in STORY_STAGE_ORDER],
        )

    def _should_run(
        self,
        analyzer: StoryAnalyzer,
        existing: StoryStageResult | None,
        only_set: set[str] | None,
    ) -> bool:
        if only_set is not None:
            return analyzer.name in only_set
        return not (
            existing is not None
            and existing.status is StoryStageStatus.COMPLETED
            and existing.version == analyzer.version
        )

    async def _run_stage(self, analyzer: StoryAnalyzer, ctx: StoryStageContext) -> StoryStageResult:
        result = StoryStageResult(
            stage=analyzer.name,
            status=StoryStageStatus.RUNNING,
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
                    "story_stage_error", stage=analyzer.name, attempt=attempt, error=last_error
                )
                if attempt < max_attempts:
                    await asyncio.sleep(self._backoff * attempt)
                    continue
                return self._finalize_failed(result, last_error)

            if outcome.status is StoryStageStatus.FAILED and attempt < max_attempts:
                last_error = outcome.reason or "Stage reported failure."
                log.warning(
                    "story_stage_failed_outcome",
                    stage=analyzer.name,
                    attempt=attempt,
                    reason=last_error,
                )
                await asyncio.sleep(self._backoff * attempt)
                continue

            return self._finalize(result, outcome)

        return self._finalize_failed(result, last_error or "Unknown error.")

    @staticmethod
    def _finalize(result: StoryStageResult, outcome: StoryOutcome) -> StoryStageResult:
        result.status = outcome.status
        result.data = outcome.data
        result.reason = outcome.reason
        result.completed_at = utc_now()
        if outcome.status is StoryStageStatus.COMPLETED:
            result.progress = 1.0
            result.error = None
        elif outcome.status is StoryStageStatus.FAILED:
            result.error = outcome.reason
        return result

    @staticmethod
    def _finalize_failed(result: StoryStageResult, error: str) -> StoryStageResult:
        result.status = StoryStageStatus.FAILED
        result.error = error
        result.completed_at = utc_now()
        return result

    @staticmethod
    def _replace_stage(story: StoryAnalysis, result: StoryStageResult) -> None:
        for index, stage in enumerate(story.stages):
            if stage.stage == result.stage:
                story.stages[index] = result
                return
        story.stages.append(result)
        story.stages.sort(key=lambda s: STORY_STAGE_ORDER.index(s.stage))

    @staticmethod
    def _mark_remaining_cancelled(story: StoryAnalysis) -> None:
        for stage in story.stages:
            if stage.status in (StoryStageStatus.PENDING, StoryStageStatus.RUNNING):
                stage.status = StoryStageStatus.CANCELLED
                stage.completed_at = utc_now()

    @staticmethod
    def _overall_status(story: StoryAnalysis) -> StoryStatus:
        """Derive honest overall status; a genuine FAILED stage is never hidden."""

        if any(s.status is StoryStageStatus.RUNNING for s in story.stages):
            return StoryStatus.RUNNING
        if any(s.status is StoryStageStatus.FAILED for s in story.stages):
            return StoryStatus.FAILED
        if story.stages and all(s.is_terminal for s in story.stages):
            if any(s.status is StoryStageStatus.CANCELLED for s in story.stages):
                return StoryStatus.CANCELLED
            return StoryStatus.COMPLETED
        return StoryStatus.PENDING

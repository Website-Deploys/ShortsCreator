"""The Clip Planning pipeline - the Clip Planner's orchestrator.

Runs the ordered :class:`PlanningAnalyzer` stages over a project's cognitive,
story, and virality understanding and turns the result into a durable, evolving
:class:`ClipPlanningAnalysis`. It is an independent sibling of the other engines'
pipelines and owns the same orchestration guarantees:

- **Persist after every stage** (work is never lost).
- **Resume** (skip stages already completed at the current stage version).
- **Retries** for genuine errors; an honest ``UNAVAILABLE`` is never retried.
- **Cancellation** between stages (remaining stages marked ``CANCELLED``).
- **Targeted single-stage reruns** via ``only=``.

It never fabricates output - it only records what the stages genuinely produced,
including honest "unavailable" reasons and zero-clip explanations.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from olympus.domain.contracts.planning import (
    PlanningAnalyzer,
    PlanningOutcome,
    PlanningRepository,
    PlanningStageContext,
)
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis
from olympus.domain.entities.planning import (
    PLANNING_STAGE_ORDER,
    ClipPlanningAnalysis,
    PlanningStageResult,
    PlanningStageStatus,
    PlanningStatus,
)
from olympus.domain.entities.project import Project
from olympus.domain.entities.story import StoryAnalysis
from olympus.domain.entities.virality import ViralityAnalysis
from olympus.planning.analyzers import (
    BlueprintGenerationAnalyzer,
    BoundaryRefinementAnalyzer,
    CandidateGenerationAnalyzer,
    ClipScoringAnalyzer,
    DuplicateDetectionAnalyzer,
    PlanningSummaryAnalyzer,
    RankingAnalyzer,
)
from olympus.platform.logging import get_logger
from olympus.utils import utc_now

log = get_logger(__name__)

#: Bumped when the *set* or *ordering* of planning stages changes.
PLANNING_PIPELINE_VERSION = "1"

#: Retry budget for stages that raise or return FAILED. UNAVAILABLE is never
#: retried (it is the truth about the evidence, not a failure).
DEFAULT_MAX_RETRIES = 2

PlanningProgressCallback = Callable[[ClipPlanningAnalysis], None]


def build_default_planning_analyzers() -> list[PlanningAnalyzer]:
    """Return the seven planning stages in pipeline order.

    The order mirrors :data:`PLANNING_STAGE_ORDER`; the pipeline validates this on
    construction so the two can never silently drift apart.
    """

    return [
        CandidateGenerationAnalyzer(),
        BoundaryRefinementAnalyzer(),
        ClipScoringAnalyzer(),
        DuplicateDetectionAnalyzer(),
        BlueprintGenerationAnalyzer(),
        RankingAnalyzer(),
        PlanningSummaryAnalyzer(),
    ]


class ClipPlanningPipeline:
    """Orchestrates the ordered planning stages into a persisted plan set."""

    def __init__(
        self,
        analyzers: Iterable[PlanningAnalyzer],
        repository: PlanningRepository,
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
        if names != PLANNING_STAGE_ORDER:
            raise ValueError(
                "Planning stage ordering does not match PLANNING_STAGE_ORDER: "
                f"{names} != {PLANNING_STAGE_ORDER}"
            )

    async def run(
        self,
        project: Project,
        storage: StoragePort,
        *,
        analysis: Analysis | None = None,
        story: StoryAnalysis | None = None,
        virality: ViralityAnalysis | None = None,
        cancel_event: asyncio.Event | None = None,
        on_progress: PlanningProgressCallback | None = None,
        only: Iterable[str] | None = None,
    ) -> ClipPlanningAnalysis:
        """Run (or resume) the planning pipeline and return the plan set.

        Args:
            project: The project under analysis.
            storage: Storage backend for any large artifacts.
            analysis: The Cognitive Engine's output (may be None).
            story: The Story Engine's output (may be None).
            virality: The Virality Engine's output (may be None).
            cancel_event: Cooperative cancellation signal, checked between stages.
            on_progress: Optional callback invoked with the plan set after each
                stage completes.
            only: Optional set of stage names to run *exclusively* (targeted
                single-stage reruns). When ``None``, normal resume rules apply.
        """

        only_set = set(only) if only is not None else None
        planning = await self._load_or_init(project.id)
        planning.status = PlanningStatus.RUNNING
        planning.updated_at = utc_now()
        await self._repo.save_index(planning)

        results: dict[str, PlanningStageResult] = {s.stage: s for s in planning.stages}
        cancelled = False

        for analyzer in self._analyzers:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            if not self._should_run(analyzer, results.get(analyzer.name), only_set):
                continue

            result = await self._run_stage(
                analyzer,
                PlanningStageContext(
                    project=project,
                    storage=storage,
                    analysis=analysis,
                    story=story,
                    virality=virality,
                    results=results,
                ),
            )
            results[analyzer.name] = result
            self._replace_stage(planning, result)
            planning.updated_at = utc_now()
            await self._repo.save_stage(project.id, result)
            await self._repo.save_index(planning)
            if on_progress is not None:
                on_progress(planning)

        if cancelled:
            self._mark_remaining_cancelled(planning)
            planning.status = PlanningStatus.CANCELLED
        else:
            planning.status = self._overall_status(planning)
        planning.updated_at = utc_now()
        await self._repo.save_index(planning)
        log.info("planning_run_finished", project_id=project.id, status=planning.status.value)
        return planning

    async def _load_or_init(self, project_id: str) -> ClipPlanningAnalysis:
        existing = await self._repo.load(project_id)
        if existing is not None:
            present = {s.stage for s in existing.stages}
            for name in PLANNING_STAGE_ORDER:
                if name not in present:
                    existing.stages.append(PlanningStageResult(stage=name))
            existing.stages.sort(key=lambda s: PLANNING_STAGE_ORDER.index(s.stage))
            return existing
        now = utc_now()
        return ClipPlanningAnalysis(
            project_id=project_id,
            pipeline_version=PLANNING_PIPELINE_VERSION,
            status=PlanningStatus.PENDING,
            created_at=now,
            updated_at=now,
            stages=[PlanningStageResult(stage=name) for name in PLANNING_STAGE_ORDER],
        )

    def _should_run(
        self,
        analyzer: PlanningAnalyzer,
        existing: PlanningStageResult | None,
        only_set: set[str] | None,
    ) -> bool:
        if only_set is not None:
            return analyzer.name in only_set
        return not (
            existing is not None
            and existing.status is PlanningStageStatus.COMPLETED
            and existing.version == analyzer.version
        )

    async def _run_stage(
        self, analyzer: PlanningAnalyzer, ctx: PlanningStageContext
    ) -> PlanningStageResult:
        result = PlanningStageResult(
            stage=analyzer.name,
            status=PlanningStageStatus.RUNNING,
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
                    "planning_stage_error", stage=analyzer.name, attempt=attempt, error=last_error
                )
                if attempt < max_attempts:
                    await asyncio.sleep(self._backoff * attempt)
                    continue
                return self._finalize_failed(result, last_error)

            if outcome.status is PlanningStageStatus.FAILED and attempt < max_attempts:
                last_error = outcome.reason or "Stage reported failure."
                log.warning(
                    "planning_stage_failed_outcome",
                    stage=analyzer.name,
                    attempt=attempt,
                    reason=last_error,
                )
                await asyncio.sleep(self._backoff * attempt)
                continue

            return self._finalize(result, outcome)

        return self._finalize_failed(result, last_error or "Unknown error.")

    @staticmethod
    def _finalize(result: PlanningStageResult, outcome: PlanningOutcome) -> PlanningStageResult:
        result.status = outcome.status
        result.data = outcome.data
        result.reason = outcome.reason
        result.completed_at = utc_now()
        if outcome.status is PlanningStageStatus.COMPLETED:
            result.progress = 1.0
            result.error = None
        elif outcome.status is PlanningStageStatus.FAILED:
            result.error = outcome.reason
        return result

    @staticmethod
    def _finalize_failed(result: PlanningStageResult, error: str) -> PlanningStageResult:
        result.status = PlanningStageStatus.FAILED
        result.error = error
        result.completed_at = utc_now()
        return result

    @staticmethod
    def _replace_stage(planning: ClipPlanningAnalysis, result: PlanningStageResult) -> None:
        for index, stage in enumerate(planning.stages):
            if stage.stage == result.stage:
                planning.stages[index] = result
                return
        planning.stages.append(result)
        planning.stages.sort(key=lambda s: PLANNING_STAGE_ORDER.index(s.stage))

    @staticmethod
    def _mark_remaining_cancelled(planning: ClipPlanningAnalysis) -> None:
        for stage in planning.stages:
            if stage.status in (PlanningStageStatus.PENDING, PlanningStageStatus.RUNNING):
                stage.status = PlanningStageStatus.CANCELLED
                stage.completed_at = utc_now()

    @staticmethod
    def _overall_status(planning: ClipPlanningAnalysis) -> PlanningStatus:
        """Derive honest overall status; a genuine FAILED stage is never hidden."""

        if any(s.status is PlanningStageStatus.RUNNING for s in planning.stages):
            return PlanningStatus.RUNNING
        if any(s.status is PlanningStageStatus.FAILED for s in planning.stages):
            return PlanningStatus.FAILED
        if planning.stages and all(s.is_terminal for s in planning.stages):
            if any(s.status is PlanningStageStatus.CANCELLED for s in planning.stages):
                return PlanningStatus.CANCELLED
            return PlanningStatus.COMPLETED
        return PlanningStatus.PENDING

"""The Virality pipeline - the Virality Engine's orchestrator.

Runs the ordered :class:`ViralityAnalyzer` stages over a project's *cognitive*
and *story* understanding and turns the result into a durable, evolving
:class:`ViralityAnalysis`. It is an independent sibling of the other engines'
pipelines and owns the same orchestration guarantees:

- **Persist after every stage** (work is never lost).
- **Resume** (skip stages already completed at the current analyzer version).
- **Retries** for genuine errors; an honest ``UNAVAILABLE`` is never retried.
- **Cancellation** between stages (remaining stages marked ``CANCELLED``).
- **Targeted single-stage reruns** via ``only=``.

It never fabricates output - it only records what the analyzers genuinely
derived, including their honest "unavailable" reasons and per-conclusion
confidence/evidence/limitations.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.virality import (
    ViralityAnalyzer,
    ViralityOutcome,
    ViralityRepository,
    ViralityStageContext,
)
from olympus.domain.entities.analysis import Analysis
from olympus.domain.entities.project import Project
from olympus.domain.entities.story import StoryAnalysis
from olympus.domain.entities.virality import (
    VIRALITY_STAGE_ORDER,
    ViralityAnalysis,
    ViralityStageResult,
    ViralityStageStatus,
    ViralityStatus,
)
from olympus.platform.logging import get_logger
from olympus.utils import utc_now
from olympus.virality.analyzers import (
    AudienceFitAnalyzer,
    AudienceRelatabilityAnalyzer,
    CommentPotentialAnalyzer,
    ConflictAnalyzer,
    CuriosityGapAnalyzer,
    EmotionalImpactAnalyzer,
    HookStrengthAnalyzer,
    InformationValueAnalyzer,
    MomentumAnalyzer,
    NoveltyAnalyzer,
    PlatformFitAnalyzer,
    ReplayPotentialAnalyzer,
    RetentionAnalyzer,
    ShareabilityAnalyzer,
    ViralitySummaryAnalyzer,
)

log = get_logger(__name__)

#: Bumped when the *set* or *ordering* of virality stages changes.
VIRALITY_PIPELINE_VERSION = "1"

#: Retry budget for stages that raise or return FAILED. UNAVAILABLE is never
#: retried (it is the truth about the evidence, not a failure).
DEFAULT_MAX_RETRIES = 2

ViralityProgressCallback = Callable[[ViralityAnalysis], None]


def build_default_virality_analyzers() -> list[ViralityAnalyzer]:
    """Return the fifteen virality analyzers in pipeline order.

    The order mirrors :data:`VIRALITY_STAGE_ORDER`; the pipeline validates this on
    construction so the two can never silently drift apart.
    """

    return [
        HookStrengthAnalyzer(),
        CuriosityGapAnalyzer(),
        EmotionalImpactAnalyzer(),
        ConflictAnalyzer(),
        NoveltyAnalyzer(),
        InformationValueAnalyzer(),
        AudienceRelatabilityAnalyzer(),
        MomentumAnalyzer(),
        RetentionAnalyzer(),
        ReplayPotentialAnalyzer(),
        ShareabilityAnalyzer(),
        CommentPotentialAnalyzer(),
        PlatformFitAnalyzer(),
        AudienceFitAnalyzer(),
        ViralitySummaryAnalyzer(),
    ]


class ViralityPipeline:
    """Orchestrates the ordered virality analyzers into a persisted assessment."""

    def __init__(
        self,
        analyzers: Iterable[ViralityAnalyzer],
        repository: ViralityRepository,
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
        if names != VIRALITY_STAGE_ORDER:
            raise ValueError(
                "Virality analyzer ordering does not match VIRALITY_STAGE_ORDER: "
                f"{names} != {VIRALITY_STAGE_ORDER}"
            )

    async def run(
        self,
        project: Project,
        storage: StoragePort,
        *,
        analysis: Analysis | None = None,
        story: StoryAnalysis | None = None,
        cancel_event: asyncio.Event | None = None,
        on_progress: ViralityProgressCallback | None = None,
        only: Iterable[str] | None = None,
    ) -> ViralityAnalysis:
        """Run (or resume) the virality pipeline and return the assessment.

        Args:
            project: The project under analysis.
            storage: Storage backend for any large artifacts.
            analysis: The Cognitive Engine's output for this project (may be None).
            story: The Story Engine's output for this project (may be None).
            cancel_event: Cooperative cancellation signal, checked between stages.
            on_progress: Optional callback invoked with the assessment after each
                stage completes.
            only: Optional set of stage names to run *exclusively* (targeted
                single-stage reruns). When ``None``, normal resume rules apply.
        """

        only_set = set(only) if only is not None else None
        virality = await self._load_or_init(project.id)
        virality.status = ViralityStatus.RUNNING
        virality.updated_at = utc_now()
        await self._repo.save_index(virality)

        results: dict[str, ViralityStageResult] = {s.stage: s for s in virality.stages}
        cancelled = False

        for analyzer in self._analyzers:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            if not self._should_run(analyzer, results.get(analyzer.name), only_set):
                continue

            result = await self._run_stage(
                analyzer,
                ViralityStageContext(
                    project=project,
                    storage=storage,
                    analysis=analysis,
                    story=story,
                    results=results,
                ),
            )
            results[analyzer.name] = result
            self._replace_stage(virality, result)
            virality.updated_at = utc_now()
            await self._repo.save_stage(project.id, result)
            await self._repo.save_index(virality)
            if on_progress is not None:
                on_progress(virality)

        if cancelled:
            self._mark_remaining_cancelled(virality)
            virality.status = ViralityStatus.CANCELLED
        else:
            virality.status = self._overall_status(virality)
        virality.updated_at = utc_now()
        await self._repo.save_index(virality)
        log.info("virality_run_finished", project_id=project.id, status=virality.status.value)
        return virality

    async def _load_or_init(self, project_id: str) -> ViralityAnalysis:
        existing = await self._repo.load(project_id)
        if existing is not None:
            present = {s.stage for s in existing.stages}
            for name in VIRALITY_STAGE_ORDER:
                if name not in present:
                    existing.stages.append(ViralityStageResult(stage=name))
            existing.stages.sort(key=lambda s: VIRALITY_STAGE_ORDER.index(s.stage))
            return existing
        now = utc_now()
        return ViralityAnalysis(
            project_id=project_id,
            pipeline_version=VIRALITY_PIPELINE_VERSION,
            status=ViralityStatus.PENDING,
            created_at=now,
            updated_at=now,
            stages=[ViralityStageResult(stage=name) for name in VIRALITY_STAGE_ORDER],
        )

    def _should_run(
        self,
        analyzer: ViralityAnalyzer,
        existing: ViralityStageResult | None,
        only_set: set[str] | None,
    ) -> bool:
        if only_set is not None:
            return analyzer.name in only_set
        return not (
            existing is not None
            and existing.status is ViralityStageStatus.COMPLETED
            and existing.version == analyzer.version
        )

    async def _run_stage(
        self, analyzer: ViralityAnalyzer, ctx: ViralityStageContext
    ) -> ViralityStageResult:
        result = ViralityStageResult(
            stage=analyzer.name,
            status=ViralityStageStatus.RUNNING,
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
                    "virality_stage_error", stage=analyzer.name, attempt=attempt, error=last_error
                )
                if attempt < max_attempts:
                    await asyncio.sleep(self._backoff * attempt)
                    continue
                return self._finalize_failed(result, last_error)

            if outcome.status is ViralityStageStatus.FAILED and attempt < max_attempts:
                last_error = outcome.reason or "Stage reported failure."
                log.warning(
                    "virality_stage_failed_outcome",
                    stage=analyzer.name,
                    attempt=attempt,
                    reason=last_error,
                )
                await asyncio.sleep(self._backoff * attempt)
                continue

            return self._finalize(result, outcome)

        return self._finalize_failed(result, last_error or "Unknown error.")

    @staticmethod
    def _finalize(result: ViralityStageResult, outcome: ViralityOutcome) -> ViralityStageResult:
        result.status = outcome.status
        result.data = outcome.data
        result.reason = outcome.reason
        result.completed_at = utc_now()
        if outcome.status is ViralityStageStatus.COMPLETED:
            result.progress = 1.0
            result.error = None
        elif outcome.status is ViralityStageStatus.FAILED:
            result.error = outcome.reason
        return result

    @staticmethod
    def _finalize_failed(result: ViralityStageResult, error: str) -> ViralityStageResult:
        result.status = ViralityStageStatus.FAILED
        result.error = error
        result.completed_at = utc_now()
        return result

    @staticmethod
    def _replace_stage(virality: ViralityAnalysis, result: ViralityStageResult) -> None:
        for index, stage in enumerate(virality.stages):
            if stage.stage == result.stage:
                virality.stages[index] = result
                return
        virality.stages.append(result)
        virality.stages.sort(key=lambda s: VIRALITY_STAGE_ORDER.index(s.stage))

    @staticmethod
    def _mark_remaining_cancelled(virality: ViralityAnalysis) -> None:
        for stage in virality.stages:
            if stage.status in (ViralityStageStatus.PENDING, ViralityStageStatus.RUNNING):
                stage.status = ViralityStageStatus.CANCELLED
                stage.completed_at = utc_now()

    @staticmethod
    def _overall_status(virality: ViralityAnalysis) -> ViralityStatus:
        """Derive honest overall status; a genuine FAILED stage is never hidden."""

        if any(s.status is ViralityStageStatus.RUNNING for s in virality.stages):
            return ViralityStatus.RUNNING
        if any(s.status is ViralityStageStatus.FAILED for s in virality.stages):
            return ViralityStatus.FAILED
        if virality.stages and all(s.is_terminal for s in virality.stages):
            if any(s.status is ViralityStageStatus.CANCELLED for s in virality.stages):
                return ViralityStatus.CANCELLED
            return ViralityStatus.COMPLETED
        return ViralityStatus.PENDING

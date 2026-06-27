"""The Optimization pipeline - the Optimization Engine's orchestrator.

Runs the ordered :class:`OptimizationAnalyzer` stages over a project's render
manifest and its upstream engine outputs, turning the result into a durable,
evolving :class:`OptimizationAnalysis`. It is an independent sibling of the other
engines' pipelines and owns the same orchestration guarantees:

- **Persist after every stage** (work is never lost).
- **Resume** (skip stages already completed at the current stage version).
- **Retries** for genuine errors; an honest ``UNAVAILABLE`` is never retried.
- **Cancellation** between stages (remaining stages marked ``CANCELLED``).
- **Targeted single-stage reruns** via ``only=``.

It never fabricates output - it records only what the stages genuinely produced,
including honest "unavailable"/"unknown" reasons. It never re-renders, re-encodes,
or changes the story decided upstream.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from olympus.domain.contracts.enhancement import EnhancementCapabilities
from olympus.domain.contracts.music import MusicProviderRegistry
from olympus.domain.contracts.optimization import (
    OptimizationAnalyzer,
    OptimizationOutcome,
    OptimizationRepository,
    OptimizationStageContext,
)
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis
from olympus.domain.entities.editing import EditingAnalysis
from olympus.domain.entities.optimization import (
    OPTIMIZATION_STAGE_ORDER,
    OptimizationAnalysis,
    OptimizationStageResult,
    OptimizationStageStatus,
    OptimizationStatus,
)
from olympus.domain.entities.planning import ClipPlanningAnalysis
from olympus.domain.entities.project import Project
from olympus.domain.entities.rendering import RenderManifest
from olympus.domain.entities.story import StoryAnalysis
from olympus.domain.entities.virality import ViralityAnalysis
from olympus.optimization.analyzers import (
    AudioAnalysisAnalyzer,
    CaptionOptimizationAnalyzer,
    ColorRefinementAnalyzer,
    CompressionOptimizationAnalyzer,
    DescriptionSuggestionAnalyzer,
    FinalValidationAnalyzer,
    FrameCleanupAnalyzer,
    HashtagRecommendationAnalyzer,
    LoadRenderAnalyzer,
    LoudnessNormalizationAnalyzer,
    MusicMixingAnalyzer,
    MusicRecommendationAnalyzer,
    NoiseReductionAnalyzer,
    PlatformOptimizationAnalyzer,
    PublishPackageCreationAnalyzer,
    QualityEvaluationAnalyzer,
    SharpeningAnalyzer,
    SilenceRefinementAnalyzer,
    ThumbnailOptimizationAnalyzer,
    TitleSuggestionAnalyzer,
    TypographyImprovementAnalyzer,
    VariantGenerationAnalyzer,
    VisualEnhancementAnalyzer,
    VoiceEnhancementAnalyzer,
)
from olympus.optimization.enhancement import build_default_enhancement_capabilities
from olympus.optimization.music_library import build_default_music_registry
from olympus.platform.logging import get_logger
from olympus.utils import utc_now

log = get_logger(__name__)

#: Bumped when the *set* or *ordering* of optimization stages changes.
OPTIMIZATION_PIPELINE_VERSION = "1"

#: Retry budget for stages that raise or return FAILED. UNAVAILABLE is never
#: retried (it is the truth about the render/model, not a failure).
DEFAULT_MAX_RETRIES = 2

OptimizationProgressCallback = Callable[[OptimizationAnalysis], None]


def build_default_optimization_analyzers() -> list[OptimizationAnalyzer]:
    """Return the twenty-four optimization stages in pipeline order.

    The order mirrors :data:`OPTIMIZATION_STAGE_ORDER`; the pipeline validates
    this on construction so the two can never silently drift apart.
    """

    return [
        LoadRenderAnalyzer(),
        AudioAnalysisAnalyzer(),
        VoiceEnhancementAnalyzer(),
        NoiseReductionAnalyzer(),
        LoudnessNormalizationAnalyzer(),
        SilenceRefinementAnalyzer(),
        MusicRecommendationAnalyzer(),
        MusicMixingAnalyzer(),
        CaptionOptimizationAnalyzer(),
        TypographyImprovementAnalyzer(),
        VisualEnhancementAnalyzer(),
        SharpeningAnalyzer(),
        ColorRefinementAnalyzer(),
        FrameCleanupAnalyzer(),
        ThumbnailOptimizationAnalyzer(),
        TitleSuggestionAnalyzer(),
        DescriptionSuggestionAnalyzer(),
        HashtagRecommendationAnalyzer(),
        PlatformOptimizationAnalyzer(),
        CompressionOptimizationAnalyzer(),
        QualityEvaluationAnalyzer(),
        VariantGenerationAnalyzer(),
        FinalValidationAnalyzer(),
        PublishPackageCreationAnalyzer(),
    ]


class OptimizationPipeline:
    """Orchestrates the ordered optimization stages into a persisted analysis."""

    def __init__(
        self,
        analyzers: Iterable[OptimizationAnalyzer],
        repository: OptimizationRepository,
        *,
        music: MusicProviderRegistry | None = None,
        enhancement: EnhancementCapabilities | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._analyzers = list(analyzers)
        self._repo = repository
        self._music = music or build_default_music_registry()
        self._enhancement = enhancement or build_default_enhancement_capabilities()
        self._max_retries = max(0, max_retries)
        self._backoff = retry_backoff_seconds
        self._validate_order()

    def _validate_order(self) -> None:
        names = tuple(a.name for a in self._analyzers)
        if names != OPTIMIZATION_STAGE_ORDER:
            raise ValueError(
                "Optimization stage ordering does not match OPTIMIZATION_STAGE_ORDER: "
                f"{names} != {OPTIMIZATION_STAGE_ORDER}"
            )

    async def run(
        self,
        project: Project,
        storage: StoragePort,
        *,
        renders: RenderManifest | None = None,
        analysis: Analysis | None = None,
        story: StoryAnalysis | None = None,
        virality: ViralityAnalysis | None = None,
        planning: ClipPlanningAnalysis | None = None,
        editing: EditingAnalysis | None = None,
        cancel_event: asyncio.Event | None = None,
        on_progress: OptimizationProgressCallback | None = None,
        only: Iterable[str] | None = None,
    ) -> OptimizationAnalysis:
        """Run (or resume) the optimization pipeline and return the analysis."""

        only_set = set(only) if only is not None else None
        optimization = await self._load_or_init(project.id)
        optimization.status = OptimizationStatus.RUNNING
        optimization.updated_at = utc_now()
        await self._repo.save_index(optimization)

        results: dict[str, OptimizationStageResult] = {s.stage: s for s in optimization.stages}
        cancelled = False

        for analyzer in self._analyzers:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            if not self._should_run(analyzer, results.get(analyzer.name), only_set):
                continue

            result = await self._run_stage(
                analyzer,
                OptimizationStageContext(
                    project=project,
                    storage=storage,
                    music=self._music,
                    enhancement=self._enhancement,
                    renders=renders,
                    analysis=analysis,
                    story=story,
                    virality=virality,
                    planning=planning,
                    editing=editing,
                    results=results,
                ),
            )
            results[analyzer.name] = result
            self._replace_stage(optimization, result)
            optimization.updated_at = utc_now()
            await self._repo.save_stage(project.id, result)
            await self._repo.save_index(optimization)
            if on_progress is not None:
                on_progress(optimization)

        if cancelled:
            self._mark_remaining_cancelled(optimization)
            optimization.status = OptimizationStatus.CANCELLED
        else:
            optimization.status = self._overall_status(optimization)
        optimization.updated_at = utc_now()
        await self._repo.save_index(optimization)
        log.info(
            "optimization_run_finished", project_id=project.id, status=optimization.status.value
        )
        return optimization

    async def _load_or_init(self, project_id: str) -> OptimizationAnalysis:
        existing = await self._repo.load(project_id)
        if existing is not None:
            present = {s.stage for s in existing.stages}
            for name in OPTIMIZATION_STAGE_ORDER:
                if name not in present:
                    existing.stages.append(OptimizationStageResult(stage=name))
            existing.stages.sort(key=lambda s: OPTIMIZATION_STAGE_ORDER.index(s.stage))
            return existing
        now = utc_now()
        return OptimizationAnalysis(
            project_id=project_id,
            pipeline_version=OPTIMIZATION_PIPELINE_VERSION,
            status=OptimizationStatus.PENDING,
            created_at=now,
            updated_at=now,
            stages=[OptimizationStageResult(stage=name) for name in OPTIMIZATION_STAGE_ORDER],
        )

    def _should_run(
        self,
        analyzer: OptimizationAnalyzer,
        existing: OptimizationStageResult | None,
        only_set: set[str] | None,
    ) -> bool:
        if only_set is not None:
            return analyzer.name in only_set
        return not (
            existing is not None
            and existing.status is OptimizationStageStatus.COMPLETED
            and existing.version == analyzer.version
        )

    async def _run_stage(
        self, analyzer: OptimizationAnalyzer, ctx: OptimizationStageContext
    ) -> OptimizationStageResult:
        result = OptimizationStageResult(
            stage=analyzer.name,
            status=OptimizationStageStatus.RUNNING,
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
                    "optimization_stage_error",
                    stage=analyzer.name,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(self._backoff * attempt)
                    continue
                return self._finalize_failed(result, last_error)

            if outcome.status is OptimizationStageStatus.FAILED and attempt < max_attempts:
                last_error = outcome.reason or "Stage reported failure."
                log.warning(
                    "optimization_stage_failed_outcome",
                    stage=analyzer.name,
                    attempt=attempt,
                    reason=last_error,
                )
                await asyncio.sleep(self._backoff * attempt)
                continue

            return self._finalize(result, outcome)

        return self._finalize_failed(result, last_error or "Unknown error.")

    @staticmethod
    def _finalize(
        result: OptimizationStageResult, outcome: OptimizationOutcome
    ) -> OptimizationStageResult:
        result.status = outcome.status
        result.data = outcome.data
        result.reason = outcome.reason
        result.completed_at = utc_now()
        if outcome.status is OptimizationStageStatus.COMPLETED:
            result.progress = 1.0
            result.error = None
        elif outcome.status is OptimizationStageStatus.FAILED:
            result.error = outcome.reason
        return result

    @staticmethod
    def _finalize_failed(result: OptimizationStageResult, error: str) -> OptimizationStageResult:
        result.status = OptimizationStageStatus.FAILED
        result.error = error
        result.completed_at = utc_now()
        return result

    @staticmethod
    def _replace_stage(optimization: OptimizationAnalysis, result: OptimizationStageResult) -> None:
        for index, stage in enumerate(optimization.stages):
            if stage.stage == result.stage:
                optimization.stages[index] = result
                return
        optimization.stages.append(result)
        optimization.stages.sort(key=lambda s: OPTIMIZATION_STAGE_ORDER.index(s.stage))

    @staticmethod
    def _mark_remaining_cancelled(optimization: OptimizationAnalysis) -> None:
        for stage in optimization.stages:
            if stage.status in (
                OptimizationStageStatus.PENDING,
                OptimizationStageStatus.RUNNING,
            ):
                stage.status = OptimizationStageStatus.CANCELLED
                stage.completed_at = utc_now()

    @staticmethod
    def _overall_status(optimization: OptimizationAnalysis) -> OptimizationStatus:
        """Derive honest overall status; a genuine FAILED stage is never hidden."""

        if any(s.status is OptimizationStageStatus.RUNNING for s in optimization.stages):
            return OptimizationStatus.RUNNING
        if any(s.status is OptimizationStageStatus.FAILED for s in optimization.stages):
            return OptimizationStatus.FAILED
        if optimization.stages and all(s.is_terminal for s in optimization.stages):
            if any(s.status is OptimizationStageStatus.CANCELLED for s in optimization.stages):
                return OptimizationStatus.CANCELLED
            return OptimizationStatus.COMPLETED
        return OptimizationStatus.PENDING

"""The analysis pipeline - the Cognitive Engine's orchestrator.

The pipeline runs the ordered :class:`Analyzer` stages over a project's video
and turns the result into a durable, evolving :class:`Analysis`. It owns the
*orchestration* concerns that every analyzer would otherwise have to repeat:

- **Persist after every stage.** A stage's full result is saved the moment it
  finishes, and the lightweight index is updated too. Work is never lost, even
  if the process dies mid-pipeline.
- **Resume.** Re-running the pipeline skips stages that already completed at the
  current analyzer version, and only re-does the rest. Bumping an analyzer's
  ``version`` invalidates its cached result so it re-runs.
- **Retries.** Genuine errors are retried a bounded number of times with a small
  backoff. An honest ``UNAVAILABLE`` outcome is *not* retried - it is not a
  failure, it is the truth about this environment.
- **Cancellation.** A cooperative ``asyncio.Event`` is checked between stages;
  when set, the remaining stages are marked ``CANCELLED`` (never silently
  dropped) and the run ends.
- **Dependencies.** Each analyzer receives the prior stages' results, so a stage
  can build on what came before (e.g. transcription reads the extracted audio).

The pipeline never fabricates output: it only records what the analyzers
genuinely produced, including their honest "unavailable" reasons.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from olympus.analysis.analyzers import (
    AudioExtractionAnalyzer,
    EmotionTimelineAnalyzer,
    FaceDetectionAnalyzer,
    KnowledgeGraphAnalyzer,
    ObjectDetectionAnalyzer,
    OcrAnalyzer,
    SceneDetectionAnalyzer,
    ShotDetectionAnalyzer,
    SpeakerSegmentationAnalyzer,
    SpeechTranscriptionAnalyzer,
    VideoInspectionAnalyzer,
)
from olympus.domain.contracts.analysis import (
    AnalysisRepository,
    Analyzer,
    StageContext,
    StageOutcome,
)
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import (
    STAGE_ORDER,
    Analysis,
    AnalysisStatus,
    StageResult,
    StageStatus,
)
from olympus.domain.entities.project import Project
from olympus.platform.logging import get_logger
from olympus.utils import utc_now

log = get_logger(__name__)

#: Bumped when the *set* or *ordering* of stages changes (not per-stage logic;
#: that is tracked by each analyzer's own ``version``).
PIPELINE_VERSION = "1"

#: How many times to retry a stage that raised or returned FAILED. UNAVAILABLE
#: outcomes are never retried.
DEFAULT_MAX_RETRIES = 2

# Called with the whole analysis after each stage so callers can report progress.
ProgressCallback = Callable[[Analysis], None]


def build_default_analyzers() -> list[Analyzer]:
    """Return the eleven analyzers in pipeline order.

    The order mirrors :data:`STAGE_ORDER`; the pipeline validates this on
    construction so the two can never silently drift apart.
    """

    return [
        VideoInspectionAnalyzer(),
        AudioExtractionAnalyzer(),
        SpeechTranscriptionAnalyzer(),
        SpeakerSegmentationAnalyzer(),
        SceneDetectionAnalyzer(),
        ShotDetectionAnalyzer(),
        OcrAnalyzer(),
        FaceDetectionAnalyzer(),
        ObjectDetectionAnalyzer(),
        EmotionTimelineAnalyzer(),
        KnowledgeGraphAnalyzer(),
    ]


class AnalysisPipeline:
    """Orchestrates the ordered analyzers into a persisted understanding."""

    def __init__(
        self,
        analyzers: Iterable[Analyzer],
        repository: AnalysisRepository,
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
        if names != STAGE_ORDER:
            raise ValueError(
                "Analyzer ordering does not match STAGE_ORDER: "
                f"{names} != {STAGE_ORDER}"
            )

    async def run(
        self,
        project: Project,
        storage: StoragePort,
        *,
        transcription_provider: object | None = None,
        cancel_event: asyncio.Event | None = None,
        on_progress: ProgressCallback | None = None,
        only: Iterable[str] | None = None,
    ) -> Analysis:
        """Run (or resume) the pipeline for ``project`` and return the analysis.

        Args:
            project: The project whose video is analyzed.
            storage: Storage backend the analyzers read/write artifacts through.
            transcription_provider: Optional speech-to-text provider, injected
                into the transcription stage's context.
            cancel_event: Optional cooperative cancellation signal, checked
                between stages.
            on_progress: Optional callback invoked with the full analysis after
                each stage completes (for live progress reporting).
            only: Optional set of stage names to run *exclusively*. Stages not in
                the set keep their existing results untouched (used for targeted
                single-stage reruns). When ``None``, normal resume rules apply.
        """

        only_set = set(only) if only is not None else None
        analysis = await self._load_or_init(project.id)
        analysis.status = AnalysisStatus.RUNNING
        analysis.updated_at = utc_now()
        await self._repo.save_index(analysis)

        results: dict[str, StageResult] = {s.stage: s for s in analysis.stages}
        cancelled = False

        for analyzer in self._analyzers:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            if not self._should_run(analyzer, results.get(analyzer.name), only_set):
                continue

            result = await self._run_stage(
                analyzer,
                StageContext(
                    project=project,
                    storage=storage,
                    results=results,
                    transcription_provider=transcription_provider,
                ),
            )
            results[analyzer.name] = result
            self._replace_stage(analysis, result)
            analysis.updated_at = utc_now()
            await self._repo.save_stage(project.id, result)
            await self._repo.save_index(analysis)
            if on_progress is not None:
                on_progress(analysis)

        if cancelled:
            self._mark_remaining_cancelled(analysis)
            analysis.status = AnalysisStatus.CANCELLED
        else:
            analysis.status = self._overall_status(analysis)
        analysis.updated_at = utc_now()
        await self._repo.save_index(analysis)
        log.info(
            "analysis_run_finished",
            project_id=project.id,
            status=analysis.status.value,
        )
        return analysis

    async def _load_or_init(self, project_id: str) -> Analysis:
        existing = await self._repo.load(project_id)
        if existing is not None:
            # Ensure every known stage has a slot (e.g. after adding stages).
            present = {s.stage for s in existing.stages}
            for name in STAGE_ORDER:
                if name not in present:
                    existing.stages.append(StageResult(stage=name))
            existing.stages.sort(key=lambda s: STAGE_ORDER.index(s.stage))
            return existing
        now = utc_now()
        return Analysis(
            project_id=project_id,
            pipeline_version=PIPELINE_VERSION,
            status=AnalysisStatus.PENDING,
            created_at=now,
            updated_at=now,
            stages=[StageResult(stage=name) for name in STAGE_ORDER],
        )

    def _should_run(
        self,
        analyzer: Analyzer,
        existing: StageResult | None,
        only_set: set[str] | None,
    ) -> bool:
        # Targeted rerun: only run the explicitly-requested stages.
        if only_set is not None:
            return analyzer.name in only_set
        # Resume: skip stages already completed at the current analyzer version.
        return not (
            existing is not None
            and existing.status is StageStatus.COMPLETED
            and existing.version == analyzer.version
        )

    async def _run_stage(self, analyzer: Analyzer, ctx: StageContext) -> StageResult:
        result = StageResult(
            stage=analyzer.name,
            status=StageStatus.RUNNING,
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
                    "analysis_stage_error",
                    stage=analyzer.name,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(self._backoff * attempt)
                    continue
                return self._finalize_failed(result, last_error)

            # A returned FAILED outcome is a genuine failure -> retry too.
            if outcome.status is StageStatus.FAILED and attempt < max_attempts:
                last_error = outcome.reason or "Stage reported failure."
                log.warning(
                    "analysis_stage_failed_outcome",
                    stage=analyzer.name,
                    attempt=attempt,
                    reason=last_error,
                )
                await asyncio.sleep(self._backoff * attempt)
                continue

            return self._finalize(result, outcome)

        # Unreachable, but keeps the type-checker satisfied.
        return self._finalize_failed(result, last_error or "Unknown error.")

    @staticmethod
    def _finalize(result: StageResult, outcome: StageOutcome) -> StageResult:
        result.status = outcome.status
        result.data = outcome.data
        result.reason = outcome.reason
        result.completed_at = utc_now()
        if outcome.status is StageStatus.COMPLETED:
            result.progress = 1.0
            result.error = None
        elif outcome.status is StageStatus.FAILED:
            result.error = outcome.reason
        return result

    @staticmethod
    def _finalize_failed(result: StageResult, error: str) -> StageResult:
        result.status = StageStatus.FAILED
        result.error = error
        result.completed_at = utc_now()
        return result

    @staticmethod
    def _replace_stage(analysis: Analysis, result: StageResult) -> None:
        for index, stage in enumerate(analysis.stages):
            if stage.stage == result.stage:
                analysis.stages[index] = result
                return
        analysis.stages.append(result)
        analysis.stages.sort(key=lambda s: STAGE_ORDER.index(s.stage))

    @staticmethod
    def _mark_remaining_cancelled(analysis: Analysis) -> None:
        for stage in analysis.stages:
            if stage.status in (StageStatus.PENDING, StageStatus.RUNNING):
                stage.status = StageStatus.CANCELLED
                stage.completed_at = utc_now()

    @staticmethod
    def _overall_status(analysis: Analysis) -> AnalysisStatus:
        """Derive the honest overall status from the stages.

        A genuine ``FAILED`` stage surfaces as an overall failure (never hidden).
        Honest ``UNAVAILABLE`` stages are terminal but do *not* mean failure - the
        pipeline completed everything it could in this environment.
        """

        if any(s.status is StageStatus.RUNNING for s in analysis.stages):
            return AnalysisStatus.RUNNING
        if any(s.status is StageStatus.FAILED for s in analysis.stages):
            return AnalysisStatus.FAILED
        if analysis.stages and all(s.is_terminal for s in analysis.stages):
            if any(s.status is StageStatus.CANCELLED for s in analysis.stages):
                return AnalysisStatus.CANCELLED
            return AnalysisStatus.COMPLETED
        return AnalysisStatus.PENDING

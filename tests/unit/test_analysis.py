"""Tests for the Cognitive Engine: analyzers, pipeline, repository, and service.

These verify the *honest* contract of video understanding: real stages produce
real output, unconfigured stages report ``UNAVAILABLE`` (never fabricated), work
is persisted after every stage, runs resume, single stages re-run, and
cancellation is cooperative.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from olympus.analysis import build_default_analyzers
from olympus.analysis.pipeline import AnalysisPipeline
from olympus.data.repositories import StorageAnalysisRepository, StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.ai import TranscriptResult, TranscriptSegment
from olympus.domain.contracts.analysis import (
    Analyzer,
    ProgressReporter,
    StageContext,
    StageOutcome,
)
from olympus.domain.entities.analysis import (
    STAGE_ORDER,
    Analysis,
    AnalysisStatus,
    StageResult,
    StageStatus,
)
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.services.analysis import AnalysisService
from olympus.utils import new_id, utc_now


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


@pytest.fixture
def repo(storage: LocalStorage) -> StorageAnalysisRepository:
    return StorageAnalysisRepository(storage)


async def _make_project(storage: LocalStorage) -> Project:
    key = "uploads/u1/source.mp4"
    await storage.put(key, b"not-a-real-video", content_type="video/mp4")
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name="Test",
        source_filename="clip.mp4",
        storage_key=key,
        size_bytes=16,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=12.0,
        width=1920,
        height=1080,
        status=ProjectStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )


# --------------------------------------------------------------------------- #
# Pipeline behaviour
# --------------------------------------------------------------------------- #
async def test_pipeline_runs_all_stages_and_persists(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    project = await _make_project(storage)
    pipeline = AnalysisPipeline(build_default_analyzers(), repo)

    analysis = await pipeline.run(project, storage)

    # Every stage in the canonical order is present and terminal.
    assert [s.stage for s in analysis.stages] == list(STAGE_ORDER)
    assert all(s.is_terminal for s in analysis.stages)

    # Persisted and reloadable as the same understanding.
    reloaded = await repo.load(project.id)
    assert reloaded is not None
    assert [s.stage for s in reloaded.stages] == list(STAGE_ORDER)


async def test_video_inspection_completes_without_ffmpeg(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    """Video inspection is real and always completes from known metadata."""

    project = await _make_project(storage)
    analysis = await AnalysisPipeline(build_default_analyzers(), repo).run(project, storage)

    inspection = analysis.stage("video_inspection")
    assert inspection is not None
    assert inspection.status is StageStatus.COMPLETED
    assert inspection.data["width"] == 1920
    assert inspection.data["duration_seconds"] == 12.0


async def test_model_stages_are_honestly_unavailable(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    """Without FFmpeg/models, stages report UNAVAILABLE with a reason - never faked."""

    project = await _make_project(storage)
    analysis = await AnalysisPipeline(build_default_analyzers(), repo).run(project, storage)

    for name in ("audio_extraction", "scene_detection", "ocr", "object_detection"):
        stage = analysis.stage(name)
        assert stage is not None
        assert stage.status is StageStatus.UNAVAILABLE
        assert stage.reason  # a human-readable explanation is always present
        assert not stage.data  # nothing fabricated


async def test_knowledge_graph_aggregates_known_signals(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    project = await _make_project(storage)
    analysis = await AnalysisPipeline(build_default_analyzers(), repo).run(project, storage)

    graph = analysis.stage("knowledge_graph")
    assert graph is not None
    assert graph.status is StageStatus.COMPLETED
    # The technical profile from video inspection is a genuinely-available signal.
    assert "video_inspection" in graph.data["available_signals"]
    # Unconfigured signals are listed as pending (transparent, not hidden).
    pending_stages = {p["stage"] for p in graph.data["pending_signals"]}
    assert "scene_detection" in pending_stages
    assert graph.data["metadata"]["width"] == 1920


async def test_resume_skips_completed_stages(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    """A second run resumes: completed stages are not re-executed."""

    project = await _make_project(storage)
    pipeline = AnalysisPipeline(build_default_analyzers(), repo)
    first = await pipeline.run(project, storage)
    inspection_first = first.stage("video_inspection")
    assert inspection_first is not None
    first_completed_at = inspection_first.completed_at

    second = await pipeline.run(project, storage)
    inspection_second = second.stage("video_inspection")
    assert inspection_second is not None
    # Same completion timestamp => it was reused, not re-run.
    assert inspection_second.completed_at == first_completed_at


async def test_pipeline_overall_status_is_completed(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    project = await _make_project(storage)
    analysis = await AnalysisPipeline(build_default_analyzers(), repo).run(project, storage)
    # No genuine failures in this environment: completed (unavailable != failed).
    assert analysis.status is AnalysisStatus.COMPLETED


async def test_failed_stage_is_retried_and_surfaces(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    """A genuinely failing stage is retried, then surfaced as FAILED (not hidden)."""

    attempts = {"n": 0}

    class _FlakyInspection(Analyzer):
        name = "video_inspection"
        version = "1"

        async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
            attempts["n"] += 1
            raise RuntimeError("boom")

    analyzers = build_default_analyzers()
    analyzers[0] = _FlakyInspection()
    pipeline = AnalysisPipeline(analyzers, repo, retry_backoff_seconds=0.0)

    project = await _make_project(storage)
    analysis = await pipeline.run(project, storage)

    stage = analysis.stage("video_inspection")
    assert stage is not None
    assert stage.status is StageStatus.FAILED
    assert stage.attempts == 3  # 1 + 2 retries
    assert attempts["n"] == 3
    assert analysis.status is AnalysisStatus.FAILED


async def test_rerun_only_targets_one_stage(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    project = await _make_project(storage)
    pipeline = AnalysisPipeline(build_default_analyzers(), repo)
    first = await pipeline.run(project, storage)
    kg_first = first.stage("knowledge_graph")
    assert kg_first is not None

    rerun = await pipeline.run(project, storage, only={"knowledge_graph"})
    kg_rerun = rerun.stage("knowledge_graph")
    assert kg_rerun is not None
    assert kg_rerun.status is StageStatus.COMPLETED


async def test_pipeline_persists_speech_transcription_and_continues(
    storage: LocalStorage,
    repo: StorageAnalysisRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olympus.analysis import analyzers

    monkeypatch.setattr(analyzers.shutil, "which", lambda binary: f"C:/tools/{binary}.exe")

    async def fake_run(*args: str, timeout: float = 120.0) -> tuple[int, bytes, bytes]:
        if args[0] == "ffmpeg":
            Path(args[-1]).write_bytes(b"RIFFfake-wav-data")
            return 0, b"", b""
        return 1, b"", b""

    class _Provider:
        name = "fake-transcriber"

        async def transcribe(self, audio_key: str) -> TranscriptResult:
            assert audio_key.endswith("/audio.wav")
            return TranscriptResult(
                language="en",
                segments=[
                    TranscriptSegment(start=0.0, end=1.2, text="Hello Olympus"),
                ],
            )

    monkeypatch.setattr(analyzers, "_run", fake_run)
    project = await _make_project(storage)

    analysis = await AnalysisPipeline(build_default_analyzers(), repo).run(
        project,
        storage,
        transcription_provider=_Provider(),
    )

    speech = analysis.stage("speech_transcription")
    assert speech is not None
    assert speech.status is StageStatus.COMPLETED
    assert speech.data["word_count"] == 2
    assert speech.data["segments"][0]["text"] == "Hello Olympus"
    assert (
        Path(storage._root)  # type: ignore[attr-defined]
        / "analysis"
        / project.id
        / "stages"
        / "speech_transcription.json"
    ).exists()

    graph = analysis.stage("knowledge_graph")
    assert graph is not None
    assert graph.status is StageStatus.COMPLETED
    assert graph.data["transcript_available"] is True
    assert graph.data["transcript_word_count"] == 2


async def test_pipeline_recovers_stale_running_stage(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    project = await _make_project(storage)
    now = utc_now()
    stale = Analysis(
        project_id=project.id,
        pipeline_version="1",
        status=AnalysisStatus.RUNNING,
        created_at=now,
        updated_at=now,
        stages=[StageResult(stage=name) for name in STAGE_ORDER],
    )
    speech = stale.stage("speech_transcription")
    assert speech is not None
    speech.status = StageStatus.RUNNING
    speech.version = "1"
    speech.started_at = now
    speech.progress = 0.4
    await repo.save_stage(project.id, speech)
    await repo.save_index(stale)

    result = await AnalysisPipeline(build_default_analyzers(), repo).run(
        project,
        storage,
        only={"video_inspection"},
    )

    recovered = result.stage("speech_transcription")
    assert recovered is not None
    assert recovered.status is StageStatus.FAILED
    assert recovered.error is not None and "interrupted" in recovered.error
    assert result.status is AnalysisStatus.FAILED

    reloaded = await repo.load(project.id)
    assert reloaded is not None
    persisted = reloaded.stage("speech_transcription")
    assert persisted is not None
    assert persisted.status is StageStatus.FAILED


# --------------------------------------------------------------------------- #
# Repository round-trip
# --------------------------------------------------------------------------- #
async def test_repository_roundtrip_and_delete(
    storage: LocalStorage, repo: StorageAnalysisRepository
) -> None:
    project = await _make_project(storage)
    await AnalysisPipeline(build_default_analyzers(), repo).run(project, storage)

    loaded = await repo.load(project.id)
    assert loaded is not None
    assert isinstance(loaded.created_at, datetime)

    await repo.delete(project.id)
    assert await repo.load(project.id) is None


# --------------------------------------------------------------------------- #
# Service lifecycle
# --------------------------------------------------------------------------- #
async def test_service_start_completes_and_sets_project_status(
    storage: LocalStorage,
) -> None:
    project = await _make_project(storage)
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)

    service = AnalysisService(
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=project_repo,
        storage=storage,
    )
    await service.start(project)

    # Wait for the background task to finish.
    run = service  # noqa: F841 - readability
    for _ in range(200):
        if not service.is_running(project.id):
            break
        await _tick()

    analysis = await service.get_analysis(project.id)
    assert analysis is not None
    assert analysis.status is AnalysisStatus.COMPLETED

    refreshed = await project_repo.get(project.id)
    assert refreshed is not None
    assert refreshed.status is ProjectStatus.ANALYZED


async def test_service_rerun_stage(storage: LocalStorage) -> None:
    project = await _make_project(storage)
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)
    service = AnalysisService(
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=project_repo,
        storage=storage,
    )
    analysis = await service.rerun_stage(project, "video_inspection")
    stage = analysis.stage("video_inspection")
    assert stage is not None
    assert stage.status is StageStatus.COMPLETED


async def test_service_rejects_unknown_stage(storage: LocalStorage) -> None:
    from olympus.platform.errors import ValidationError

    project = await _make_project(storage)
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)
    service = AnalysisService(
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=project_repo,
        storage=storage,
    )
    with pytest.raises(ValidationError):
        await service.rerun_stage(project, "telepathy")


async def _tick() -> None:
    import asyncio

    await asyncio.sleep(0.01)



# --------------------------------------------------------------------------- #
# Audio extraction: honest preconditions + backend-agnostic source resolution.
#
# Regression coverage for the bug where audio extraction reported "FFmpeg is not
# available" even when FFmpeg WAS installed - because it conflated the FFmpeg
# check with `storage.local_path() is None` (true for cloud backends and for any
# local-root/working-directory mismatch). The fix separates the two and falls
# back to materializing the real uploaded bytes when no local path exists.
# --------------------------------------------------------------------------- #
class _NoLocalPathStorage(LocalStorage):
    """A storage backend that holds the real bytes but exposes no local path.

    Mirrors a cloud (S3) backend, or a local backend whose resolved root does not
    contain the file under the current working directory - the exact conditions
    under which the old code wrongly blamed FFmpeg.
    """

    def local_path(self, key: str) -> str | None:
        return None


async def _audio_ctx(store: LocalStorage) -> StageContext:
    from olympus.analysis.analyzers import AudioExtractionAnalyzer  # noqa: F401

    project = await _make_project(store)
    return StageContext(project=project, storage=store, results={})


async def test_audio_extraction_unavailable_when_ffmpeg_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no FFmpeg binary, the message names FFmpeg/PATH - and nothing else."""

    from olympus.analysis import analyzers

    monkeypatch.setattr(analyzers.shutil, "which", lambda _binary: None)
    store = LocalStorage(root=str(tmp_path))
    ctx = await _audio_ctx(store)

    outcome = await analyzers.AudioExtractionAnalyzer().analyze(ctx, lambda _v: None)
    assert outcome.status is StageStatus.UNAVAILABLE
    assert "FFmpeg" in (outcome.reason or "")
    assert "PATH" in (outcome.reason or "")


async def test_audio_extraction_runs_when_no_local_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FFmpeg present + no local path => materialize real bytes and succeed.

    This is the core regression: previously this returned UNAVAILABLE blaming
    FFmpeg. Now it fetches the bytes via the storage port, writes a temp file,
    and FFmpeg (stubbed here) runs against a genuine existing file.
    """

    from olympus.analysis import analyzers

    # FFmpeg "installed".
    monkeypatch.setattr(analyzers.shutil, "which", lambda binary: f"/usr/bin/{binary}")

    captured: dict[str, str] = {}

    async def fake_run(*args: str, timeout: float = 120.0) -> tuple[int, bytes, bytes]:
        # The input path is the 4th arg: ffmpeg -y -i <src> ...
        src = args[3]
        captured["src"] = src
        # Prove the analyzer handed FFmpeg a real, existing file (not a
        # hardcoded or fabricated path).
        assert Path(src).exists()
        # Emulate FFmpeg writing the output WAV.
        Path(args[-1]).write_bytes(b"RIFFfake-wav-data")
        return 0, b"", b""

    monkeypatch.setattr(analyzers, "_run", fake_run)

    store = _NoLocalPathStorage(root=str(tmp_path))
    assert store.local_path("uploads/u1/source.mp4") is None  # cloud-like
    ctx = await _audio_ctx(store)

    outcome = await analyzers.AudioExtractionAnalyzer().analyze(ctx, lambda _v: None)
    assert outcome.status is StageStatus.COMPLETED
    assert outcome.data["audio_key"] == f"analysis/{ctx.project.id}/audio.wav"
    # The materialized source carried the project's extension.
    assert captured["src"].endswith(".mp4")
    # The extracted audio was genuinely stored.
    assert await store.exists(outcome.data["audio_key"])


async def test_audio_extraction_reports_source_missing_distinctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FFmpeg present but the source object is genuinely absent: honest, distinct."""

    from olympus.analysis import analyzers

    monkeypatch.setattr(analyzers.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    store = _NoLocalPathStorage(root=str(tmp_path))
    project = await _make_project(store)
    await store.delete(project.storage_key)  # remove the bytes
    ctx = StageContext(project=project, storage=store, results={})

    outcome = await analyzers.AudioExtractionAnalyzer().analyze(ctx, lambda _v: None)
    assert outcome.status is StageStatus.UNAVAILABLE
    assert "source video" in (outcome.reason or "")
    assert "FFmpeg" not in (outcome.reason or "")  # not misattributed to FFmpeg


async def test_audio_extraction_degrades_on_ffmpeg_decode_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero FFmpeg exit (corrupt/unsupported input) degrades to UNAVAILABLE.

    It must NOT return FAILED: an input-specific decode failure should not poison
    the whole analysis or block downstream engines. The real FFmpeg stderr is
    surfaced honestly in the reason.
    """

    from olympus.analysis import analyzers

    monkeypatch.setattr(analyzers.shutil, "which", lambda binary: f"/usr/bin/{binary}")

    async def failing_run(*args: str, timeout: float = 120.0) -> tuple[int, bytes, bytes]:
        return 1, b"", b"ffmpeg: Invalid data found when processing input"

    monkeypatch.setattr(analyzers, "_run", failing_run)
    store = LocalStorage(root=str(tmp_path))
    ctx = await _audio_ctx(store)

    outcome = await analyzers.AudioExtractionAnalyzer().analyze(ctx, lambda _v: None)
    assert outcome.status is StageStatus.UNAVAILABLE
    assert "Invalid data found" in (outcome.reason or "")



# --------------------------------------------------------------------------- #
# Subprocess-incapable event loops (e.g. a Windows SelectorEventLoop) must NOT
# crash the analyzers with NotImplementedError. _run converts it into a
# catchable SubprocessUnavailableError; the analyzers then degrade honestly.
# --------------------------------------------------------------------------- #
async def _no_subprocess_run(*_args: str, timeout: float = 120.0):
    """Stand-in for `_run` on a loop that cannot spawn subprocesses."""

    from olympus.analysis.analyzers import SubprocessUnavailableError

    raise SubprocessUnavailableError(
        "The running asyncio event loop does not support spawning subprocesses."
    )


async def test_run_executes_a_real_subprocess(tmp_path: Path) -> None:
    """`_run` genuinely executes an external command via subprocess.run-in-thread.

    Uses the Python interpreter as a portable stand-in for ffprobe/ffmpeg. This is
    the path that previously raised NotImplementedError on Windows event loops;
    it must now work regardless of the running event loop.
    """

    import sys

    from olympus.analysis import analyzers

    code, out, _err = await analyzers._run(sys.executable, "-c", "print('olympus-ok')")
    assert code == 0
    assert b"olympus-ok" in out


async def test_run_works_even_when_event_loop_cannot_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the Windows failure mode is structurally eliminated.

    Previously `_run` used `asyncio.create_subprocess_exec`, which raises
    NotImplementedError on event loops without subprocess support (e.g. a Windows
    SelectorEventLoop) - crashing video_inspection/audio_extraction. `_run` now
    runs the command in a thread, so even if that asyncio API is broken, `_run`
    still works.
    """

    import sys

    from olympus.analysis import analyzers

    async def _broken(*_a, **_k):  # what a Windows SelectorEventLoop effectively does
        raise NotImplementedError

    monkeypatch.setattr(analyzers.asyncio, "create_subprocess_exec", _broken)
    code, out, _err = await analyzers._run(sys.executable, "-c", "print('still-works')")
    assert code == 0
    assert b"still-works" in out


async def test_run_translates_notimplemented_defensively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the platform itself refuses to spawn, `_run` raises a catchable error."""

    from olympus.analysis import analyzers

    def _raise_notimplemented(*_a, **_k):
        raise NotImplementedError

    monkeypatch.setattr(analyzers.subprocess, "run", _raise_notimplemented)
    with pytest.raises(analyzers.SubprocessUnavailableError):
        await analyzers._run("ffprobe", "-version")


async def test_run_missing_binary_raises_oserror() -> None:
    """A genuinely missing binary surfaces as OSError (caught by callers)."""

    from olympus.analysis import analyzers

    with pytest.raises(OSError):
        await analyzers._run("definitely-not-a-real-binary-olympus", "-x")


async def test_video_inspection_completes_when_subprocess_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ffprobe can't be spawned -> still COMPLETED from client metadata."""

    from olympus.analysis import analyzers

    monkeypatch.setattr(analyzers.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(analyzers, "_run", _no_subprocess_run)

    store = LocalStorage(root=str(tmp_path))
    project = await _make_project(store)
    ctx = StageContext(project=project, storage=store, results={})

    outcome = await analyzers.VideoInspectionAnalyzer().analyze(ctx, lambda _v: None)
    assert outcome.status is StageStatus.COMPLETED  # never crashes / never FAILED
    assert outcome.data["width"] == 1920
    assert outcome.data["source"] == "client_metadata"


async def test_audio_extraction_unavailable_when_subprocess_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FFmpeg present but unspawnable -> honest UNAVAILABLE, not a crash."""

    from olympus.analysis import analyzers

    monkeypatch.setattr(analyzers.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(analyzers, "_run", _no_subprocess_run)

    store = LocalStorage(root=str(tmp_path))
    project = await _make_project(store)
    ctx = StageContext(project=project, storage=store, results={})

    outcome = await analyzers.AudioExtractionAnalyzer().analyze(ctx, lambda _v: None)
    assert outcome.status is StageStatus.UNAVAILABLE
    assert "subprocess" in (outcome.reason or "").lower()



# --------------------------------------------------------------------------- #
# Regression: AnalysisService.start() must not spawn a duplicate run while one
# is already in flight (the guard was inverted, double-firing the engine chain).
# --------------------------------------------------------------------------- #
class _BlockingPipeline:
    """A pipeline whose run blocks on a release event, so we can observe the
    'already running' window deterministically and count invocations."""

    def __init__(self, repo: StorageAnalysisRepository, release) -> None:
        self._repo = repo
        self._release = release
        self.calls = 0

    async def run(self, project, storage, *, cancel_event=None, **_kwargs):
        self.calls += 1
        analysis = Analysis(
            project_id=project.id,
            pipeline_version="1",
            status=AnalysisStatus.RUNNING,
            created_at=utc_now(),
            updated_at=utc_now(),
            stages=[],
        )
        await self._repo.save_index(analysis)  # so start() can load the index
        # Block until released, but honor cooperative cancellation promptly so
        # delete()'s drain does not have to wait for the full timeout.
        import asyncio as _asyncio

        while not self._release.is_set():
            if cancel_event is not None and cancel_event.is_set():
                analysis.status = AnalysisStatus.CANCELLED
                analysis.updated_at = utc_now()
                await self._repo.save_index(analysis)
                return analysis
            await _asyncio.sleep(0.01)
        analysis.status = AnalysisStatus.COMPLETED
        analysis.updated_at = utc_now()
        await self._repo.save_index(analysis)
        return analysis


async def test_service_start_does_not_duplicate_inflight_run(storage: LocalStorage) -> None:
    import asyncio

    repo = StorageAnalysisRepository(storage)
    project_repo = StorageProjectRepository(storage)
    project = await _make_project(storage)
    await project_repo.save(project)

    release = asyncio.Event()
    pipeline = _BlockingPipeline(repo, release)
    service = AnalysisService(
        analysis_repo=repo,
        project_repo=project_repo,
        storage=storage,
        pipeline=pipeline,  # type: ignore[arg-type]
    )

    await service.start(project)
    assert service.is_running(project.id)

    # A second start while the first is in flight must return the existing
    # analysis WITHOUT launching a second pipeline run.
    await service.start(project)
    assert pipeline.calls == 1

    release.set()
    for _ in range(300):
        if not service.is_running(project.id):
            break
        await asyncio.sleep(0.01)

    assert pipeline.calls == 1  # still exactly one run, even after completion
    analysis = await service.get_analysis(project.id)
    assert analysis is not None and analysis.status is AnalysisStatus.COMPLETED



async def test_delete_drains_inflight_run_then_removes_artifacts(storage: LocalStorage) -> None:
    """Deleting a project while its analysis is running must wait for the task to
    stop, then remove artifacts cleanly (no orphaned directory, no StorageError
    from a write racing the deletion)."""

    import asyncio

    repo = StorageAnalysisRepository(storage)
    project_repo = StorageProjectRepository(storage)
    project = await _make_project(storage)
    await project_repo.save(project)

    release = asyncio.Event()  # never set: the run only ends via cancellation
    pipeline = _BlockingPipeline(repo, release)
    service = AnalysisService(
        analysis_repo=repo,
        project_repo=project_repo,
        storage=storage,
        pipeline=pipeline,  # type: ignore[arg-type]
    )

    await service.start(project)
    assert service.is_running(project.id)

    # Delete mid-run: should cancel, drain the task, then delete artifacts.
    await service.delete(project.id)

    assert not service.is_running(project.id)
    assert await service.get_analysis(project.id) is None
    # The on-disk analysis directory must be gone (no orphan).
    assert not (Path(storage._root) / "analysis" / project.id).exists()  # type: ignore[attr-defined]



async def test_audio_extraction_degrades_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long/slow source that exceeds the FFmpeg time limit degrades to
    UNAVAILABLE (not FAILED), so the analysis still completes and the chain is
    not blocked or retried wastefully."""

    from olympus.analysis import analyzers

    monkeypatch.setattr(analyzers.shutil, "which", lambda binary: f"/usr/bin/{binary}")

    async def timing_out_run(*args: str, timeout: float = 120.0) -> tuple[int, bytes, bytes]:
        raise TimeoutError("ffmpeg timed out")

    monkeypatch.setattr(analyzers, "_run", timing_out_run)
    store = LocalStorage(root=str(tmp_path))
    ctx = await _audio_ctx(store)

    outcome = await analyzers.AudioExtractionAnalyzer().analyze(ctx, lambda _v: None)
    assert outcome.status is StageStatus.UNAVAILABLE
    assert "time limit" in (outcome.reason or "")

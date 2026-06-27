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
from olympus.domain.contracts.analysis import (
    Analyzer,
    ProgressReporter,
    StageContext,
    StageOutcome,
)
from olympus.domain.entities.analysis import (
    STAGE_ORDER,
    AnalysisStatus,
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


async def test_audio_extraction_captures_ffmpeg_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real FFmpeg non-zero exit surfaces as FAILED carrying its stderr."""

    from olympus.analysis import analyzers

    monkeypatch.setattr(analyzers.shutil, "which", lambda binary: f"/usr/bin/{binary}")

    async def failing_run(*args: str, timeout: float = 120.0) -> tuple[int, bytes, bytes]:
        return 1, b"", b"ffmpeg: Invalid data found when processing input"

    monkeypatch.setattr(analyzers, "_run", failing_run)
    store = LocalStorage(root=str(tmp_path))
    ctx = await _audio_ctx(store)

    outcome = await analyzers.AudioExtractionAnalyzer().analyze(ctx, lambda _v: None)
    assert outcome.status is StageStatus.FAILED
    assert "Invalid data found" in (outcome.reason or "")

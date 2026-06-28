"""Automated chaos tests: inject failures into the pipeline and assert Olympus
degrades safely - no stuck state, no leaked run registry, honest status.

These complement the unit tests by simulating adversarial backend conditions
(storage errors mid-run, a pipeline that raises) rather than only the happy path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from olympus.data.repositories import StorageAnalysisRepository, StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.analysis import Analysis, AnalysisStatus
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import StorageError
from olympus.services.analysis import AnalysisService
from olympus.utils import new_id, utc_now


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


async def _project(storage: LocalStorage) -> Project:
    key = "uploads/u_chaos/source.mp4"
    await storage.put(key, b"not-a-real-video", content_type="video/mp4")
    now = utc_now()
    project = Project(
        id=new_id("proj"),
        name="chaos",
        source_filename="c.mp4",
        storage_key=key,
        size_bytes=16,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=5.0,
        width=320,
        height=240,
        status=ProjectStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )
    await StorageProjectRepository(storage).save(project)
    return project


class _ExplodingPipeline:
    """A pipeline that persists an initial RUNNING index, then raises - simulating
    a storage error or unexpected crash mid-run."""

    def __init__(self, repo: StorageAnalysisRepository) -> None:
        self._repo = repo

    async def run(self, project, storage, **_kwargs):
        analysis = Analysis(
            project_id=project.id,
            pipeline_version="1",
            status=AnalysisStatus.RUNNING,
            created_at=utc_now(),
            updated_at=utc_now(),
            stages=[],
        )
        await self._repo.save_index(analysis)
        raise StorageError("simulated backend failure mid-pipeline", details={"id": project.id})


async def test_pipeline_failure_marks_project_failed_and_clears_registry(
    storage: LocalStorage,
) -> None:
    repo = StorageAnalysisRepository(storage)
    project_repo = StorageProjectRepository(storage)
    project = await _project(storage)

    service = AnalysisService(
        analysis_repo=repo,
        project_repo=project_repo,
        storage=storage,
        pipeline=_ExplodingPipeline(repo),  # type: ignore[arg-type]
    )

    # start() must not raise even though the pipeline will explode.
    await service.start(project)

    # Wait for the background task to finish handling the failure.
    for _ in range(300):
        if not service.is_running(project.id):
            break
        await asyncio.sleep(0.01)

    assert not service.is_running(project.id), "run registry leaked after failure"
    refreshed = await project_repo.get(project.id)
    assert refreshed is not None
    # Not stuck in ANALYZING - honestly reflected as FAILED.
    assert refreshed.status is ProjectStatus.FAILED


async def test_repeated_cancel_and_delete_are_idempotent(storage: LocalStorage) -> None:
    """Repeated cancels/deletes must never raise or corrupt state."""

    repo = StorageAnalysisRepository(storage)
    project_repo = StorageProjectRepository(storage)
    project = await _project(storage)
    service = AnalysisService(analysis_repo=repo, project_repo=project_repo, storage=storage)

    # cancel with nothing running -> False, no raise; repeated -> still safe.
    assert await service.cancel(project.id) is False
    assert await service.cancel(project.id) is False

    # repeated deletes are idempotent and leave no artifacts.
    await service.delete(project.id)
    await service.delete(project.id)
    assert await service.get_analysis(project.id) is None

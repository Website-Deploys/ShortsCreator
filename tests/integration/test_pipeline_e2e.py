"""End-to-end pipeline integration test: upload -> analysis -> story -> virality
-> planning, driven exactly like the production chain (engine on_complete hooks).

This is the regression guard for the reported failure: when an early analysis
stage crashed (NotImplementedError from subprocess spawning on a Windows event
loop), the analysis status became FAILED, the analysis service's on_complete
hook (which requires COMPLETED) never fired, and Story/Virality/Planning never
ran - so their endpoints returned 404. With the subprocess fix in place, the
analysis completes honestly (real ffprobe/ffmpeg when present; honest UNAVAILABLE
when not) and the whole chain runs automatically to the Clip Planner.

No external tools are required: stages with no tool/model degrade to UNAVAILABLE
(never FAILED), so the analysis still COMPLETES and the chain proceeds - which is
exactly the behaviour the success criteria require.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from olympus.data.repositories import (
    StorageAnalysisRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageStoryRepository,
    StorageViralityRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.services.analysis import AnalysisService
from olympus.services.planning import ClipPlannerService
from olympus.services.story import StoryService
from olympus.services.virality import ViralityService
from olympus.utils import new_id, utc_now

pytestmark = pytest.mark.asyncio


async def _make_uploaded_project(storage: LocalStorage) -> Project:
    """Simulate the post-upload state: source bytes on disk + a project record."""

    key = f"uploads/{new_id('upl')}/source.mp4"
    payload = b"\x00\x00\x00\x18ftypmp42E2E-PIPELINE-FIXTURE"
    await storage.put(key, payload, content_type="video/mp4")
    now = utc_now()
    project = Project(
        id=new_id("proj"),
        name="E2E Clip",
        source_filename="clip.mp4",
        storage_key=key,
        size_bytes=29,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=42.0,
        width=1920,
        height=1080,
        status=ProjectStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )
    await StorageProjectRepository(storage).save(project)
    return project


def _build_chain(storage: LocalStorage) -> AnalysisService:
    """Wire analysis -> story -> virality -> planning via on_complete hooks.

    Mirrors the production wiring in olympus.api.dependencies, but against a
    single tmp-storage instance so the test is hermetic.
    """

    analysis_repo = StorageAnalysisRepository(storage)
    story_repo = StorageStoryRepository(storage)
    virality_repo = StorageViralityRepository(storage)
    planning_repo = StoragePlanningRepository(storage)
    project_repo = StorageProjectRepository(storage)

    planning = ClipPlannerService(
        planning_repo=planning_repo,
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )

    async def _start_planning(project: object, _v: object) -> None:
        await planning.start(project)  # type: ignore[arg-type]

    virality = ViralityService(
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
        on_complete=_start_planning,
    )

    async def _start_virality(project: object, _s: object) -> None:
        await virality.start(project)  # type: ignore[arg-type]

    story = StoryService(
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
        on_complete=_start_virality,
    )

    async def _start_story(project: object, _a: object) -> None:
        await story.start(project)  # type: ignore[arg-type]

    return AnalysisService(
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
        transcription_provider=None,
        on_complete=_start_story,
    )


async def _wait_for(predicate, *, timeout: float = 15.0, interval: float = 0.05) -> bool:
    waited = 0.0
    while waited < timeout:
        if await predicate():
            return True
        await asyncio.sleep(interval)
        waited += interval
    return False


async def test_full_pipeline_runs_upload_through_planning(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = await _make_uploaded_project(storage)

    analysis_repo = StorageAnalysisRepository(storage)
    story_repo = StorageStoryRepository(storage)
    virality_repo = StorageViralityRepository(storage)
    planning_repo = StoragePlanningRepository(storage)

    analysis_service = _build_chain(storage)

    # Kick off exactly as the API does on project creation.
    await analysis_service.start(project)

    # Planning is the last link in the in-scope chain; wait for it to persist.
    got_planning = await _wait_for(lambda: _exists(planning_repo, project.id))
    assert got_planning, "Clip Planner never produced output - the chain stalled."

    # 1) Cognitive analysis completed (no stage crashed -> never FAILED).
    analysis = await analysis_repo.load(project.id)
    assert analysis is not None
    assert analysis.status.value == "completed"
    # video_inspection always completes (from client metadata when ffprobe absent).
    vi = analysis.stage("video_inspection")
    assert vi is not None and vi.status.value == "completed"
    # audio_extraction is honest: UNAVAILABLE without ffmpeg, never FAILED.
    ae = analysis.stage("audio_extraction")
    assert ae is not None and ae.status.value in {"completed", "unavailable"}

    # 2) Story, 3) Virality, 4) Planning each persisted real output (no 404s).
    story = await story_repo.load(project.id)
    virality = await virality_repo.load(project.id)
    planning = await planning_repo.load(project.id)
    assert story is not None and story.status.value == "completed"
    assert virality is not None and virality.status.value == "completed"
    assert planning is not None and planning.status.value == "completed"


async def _exists(repo, project_id: str) -> bool:
    return (await repo.load(project_id)) is not None

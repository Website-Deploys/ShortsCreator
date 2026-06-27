"""Tests for the Workflow Orchestration Engine.

Two layers:

1. **Orchestration** (deterministic, fast) - drives the scheduler, queue, worker
   pool, recovery, cancellation, retries/backoff/dead jobs, and multi-project
   concurrency using a controllable fake runner. This exercises the machinery
   without spinning the heavy engines, and is the bulk of the coverage.

2. **Real integration** - drives a workflow with the *real* engine runners over
   real services on temp storage. Every engine degrades honestly in this
   environment (no models/FFmpeg), so the workflow genuinely runs all eight
   engines to honest terminal states - proving the bridge is real, not mocked.

Plus the HTTP API surface. The fake runner never fabricates work beyond a
deterministic success/failure the test controls; the real runners drive genuine
engine outcomes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import project_service_provider, workflow_service_provider
from olympus.data.repositories import (
    StorageAnalysisRepository,
    StorageEditingRepository,
    StorageOptimizationRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageRenderManifestRepository,
    StorageRenderRunRepository,
    StorageStoryRepository,
    StorageViralityRepository,
    StorageWorkflowRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.workflow import EngineRunner, EngineRunResult
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.workflow import (
    WORKFLOW_STAGES,
    Job,
    JobStatus,
    WorkerStatus,
    Workflow,
    WorkflowStatus,
)
from olympus.rendering.ffmpeg_renderer import FfmpegClipRenderer
from olympus.services.analysis import AnalysisService
from olympus.services.editing import EditingService
from olympus.services.optimization import OptimizationService
from olympus.services.planning import ClipPlannerService
from olympus.services.projects import ProjectService
from olympus.services.rendering import RenderingService
from olympus.services.story import StoryService
from olympus.services.virality import ViralityService
from olympus.services.workflow import WorkflowService
from olympus.utils import new_id, utc_now
from olympus.workflow import InMemoryWorkerRegistry, RepositoryJobQueue, Scheduler, UploadRunner
from olympus.workflow.workers import WorkerPool

ALL_STAGES = [s.stage for s in WORKFLOW_STAGES]
_FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomWORKFLOW-FIXTURE"


# --------------------------------------------------------------------------- #
# Fixtures + fakes
# --------------------------------------------------------------------------- #
@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


def _project(name: str = "WF Test") -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name=name,
        source_filename="clip.mp4",
        storage_key=f"uploads/{new_id('u')}/source.mp4",
        size_bytes=1024,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=60.0,
        width=1920,
        height=1080,
        status=ProjectStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )


class FakeRunner(EngineRunner):
    """A controllable, deterministic runner (no real engine, no fabrication)."""

    def __init__(
        self,
        engine: str,
        *,
        fail_times: int = 0,
        fail_forever: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.engine = engine
        self.calls = 0
        self._fail_times = fail_times
        self._fail_forever = fail_forever
        self._delay = delay

    async def run(self, project: Project, job: Job) -> EngineRunResult:
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        job.log(f"fake {self.engine} run #{self.calls}")
        if self._fail_forever or self.calls <= self._fail_times:
            return EngineRunResult(
                status="failed", error=f"{self.engine} forced fail #{self.calls}"
            )
        return EngineRunResult(
            status="completed", summary={"engine": self.engine, "calls": self.calls}
        )


def fake_runners(**overrides: EngineRunner) -> dict[str, EngineRunner]:
    runners: dict[str, EngineRunner] = {s.stage: FakeRunner(s.stage) for s in WORKFLOW_STAGES}
    runners.update(overrides)
    return runners


async def _seed_project(storage: LocalStorage, project: Project, *, source: bool = True) -> None:
    await StorageProjectRepository(storage).save(project)
    if source:
        await storage.put(project.storage_key, _FAKE_MP4, content_type="video/mp4")


def _service(
    storage: LocalStorage,
    runners: dict[str, EngineRunner],
    *,
    concurrency: int = 2,
    max_attempts: int = 3,
) -> WorkflowService:
    return WorkflowService(
        repository=StorageWorkflowRepository(storage),
        project_repo=StorageProjectRepository(storage),
        runners=runners,
        concurrency=concurrency,
        max_attempts=max_attempts,
        backoff_base_seconds=0.01,  # keep retry tests fast
    )


# --------------------------------------------------------------------------- #
# Scheduler (pure logic)
# --------------------------------------------------------------------------- #
def _wf(project: Project, *, max_attempts: int = 3) -> Workflow:
    svc = WorkflowService(
        repository=StorageWorkflowRepository(LocalStorage(root="/tmp/_wf_unused")),
        project_repo=StorageProjectRepository(LocalStorage(root="/tmp/_wf_unused")),
        runners={},
        max_attempts=max_attempts,
    )
    return svc._build_workflow(project)


def test_scheduler_promotes_and_blocks() -> None:
    sched = Scheduler()
    wf = _wf(_project())
    wf.status = WorkflowStatus.RUNNING
    now = utc_now()
    sched.reconcile(wf, now=now)
    # Only 'upload' (no deps) becomes READY; the rest wait on dependencies.
    assert wf.job("upload").status is JobStatus.READY
    assert wf.job("cognitive").status is JobStatus.PENDING
    # Complete upload -> cognitive becomes runnable.
    wf.job("upload").status = JobStatus.COMPLETED
    sched.reconcile(wf, now=now)
    assert wf.job("cognitive").status is JobStatus.READY
    # A dead dependency blocks everything downstream.
    wf.job("cognitive").status = JobStatus.DEAD
    sched.reconcile(wf, now=now)
    assert wf.job("story").status is JobStatus.BLOCKED


def test_scheduler_priority_ordering() -> None:
    sched = Scheduler()
    wf = _wf(_project())
    wf.status = WorkflowStatus.RUNNING
    # Make two stages independently runnable with different priorities.
    for job in wf.jobs:
        job.depends_on = ()
        job.status = JobStatus.READY
    wf.job("rendering").priority = 100
    wf.job("upload").priority = 10
    runnable = sched.runnable(wf, now=utc_now())
    assert runnable[0].stage == "rendering"  # highest priority first


def test_scheduler_retry_then_dead() -> None:
    sched = Scheduler(backoff_base_seconds=0.0)
    job = Job(job_id="j", workflow_id="w", project_id="p", engine="x", stage="x", max_attempts=2)
    job.attempts = 1
    assert sched.on_failure(job, now=utc_now()) is True  # 1 < 2 -> retry
    assert job.status is JobStatus.PENDING
    job.attempts = 2
    assert sched.on_failure(job, now=utc_now()) is False  # 2 == 2 -> dead
    assert job.status is JobStatus.DEAD


# --------------------------------------------------------------------------- #
# Queue (direct, atomic claim + dependency gating)
# --------------------------------------------------------------------------- #
async def test_queue_claim_respects_dependencies(storage: LocalStorage) -> None:
    from olympus.workflow.events import InMemoryEventBus

    project = _project()
    wf = _wf(project)
    wf.status = WorkflowStatus.RUNNING
    workflows = {project.id: wf}
    queue = RepositoryJobQueue(
        workflows=workflows,
        lock=asyncio.Lock(),
        scheduler=Scheduler(),
        repository=StorageWorkflowRepository(storage),
        event_bus=InMemoryEventBus(),
    )
    # First claim is 'upload' (only runnable job); deps gate the rest.
    job = await queue.claim("w1")
    assert job is not None and job.stage == "upload" and job.status is JobStatus.RUNNING
    # Nothing else is runnable until upload completes.
    assert await queue.claim("w2") is None
    await queue.complete(job, {"ok": True})
    nxt = await queue.claim("w2")
    assert nxt is not None and nxt.stage == "cognitive"


async def test_queue_delayed_job_not_claimable_until_available(storage: LocalStorage) -> None:
    from datetime import timedelta

    from olympus.workflow.events import InMemoryEventBus

    project = _project()
    wf = _wf(project)
    wf.status = WorkflowStatus.RUNNING
    upload = wf.job("upload")
    upload.status = JobStatus.READY
    upload.available_at = utc_now() + timedelta(seconds=100)  # delayed
    queue = RepositoryJobQueue(
        workflows={project.id: wf},
        lock=asyncio.Lock(),
        scheduler=Scheduler(),
        repository=StorageWorkflowRepository(storage),
        event_bus=InMemoryEventBus(),
    )
    assert await queue.claim("w1") is None  # not yet available


# --------------------------------------------------------------------------- #
# Service orchestration with the fake runner
# --------------------------------------------------------------------------- #
async def test_workflow_happy_path_runs_all_stages_in_order(storage: LocalStorage) -> None:
    project = _project()
    await _seed_project(storage, project)
    svc = _service(storage, fake_runners())
    try:
        await svc.start(project)
        wf = await svc.wait_for(project.id, timeout=10)
    finally:
        await svc.stop_pool()
    assert wf.status is WorkflowStatus.COMPLETED
    assert wf.completed_stages == ALL_STAGES  # completed in dependency order
    assert all(j.attempts == 1 for j in wf.jobs)
    assert wf.overall_progress == 1.0


async def test_workflow_retries_then_succeeds(storage: LocalStorage) -> None:
    project = _project()
    await _seed_project(storage, project)
    runners = fake_runners(editing=FakeRunner("editing", fail_times=2))
    svc = _service(storage, runners, max_attempts=3)
    try:
        await svc.start(project)
        wf = await svc.wait_for(project.id, timeout=10)
    finally:
        await svc.stop_pool()
    assert wf.status is WorkflowStatus.COMPLETED
    assert wf.job("editing").attempts == 3  # failed twice, succeeded on third
    assert any(e.type.value == "job_retrying" for e in wf.history)


async def test_workflow_dead_job_fails_workflow_and_blocks_downstream(
    storage: LocalStorage,
) -> None:
    project = _project()
    await _seed_project(storage, project)
    runners = fake_runners(rendering=FakeRunner("rendering", fail_forever=True))
    svc = _service(storage, runners, max_attempts=2)
    try:
        await svc.start(project)
        wf = await svc.wait_for(project.id, timeout=10)
    finally:
        await svc.stop_pool()
    assert wf.status is WorkflowStatus.FAILED
    assert wf.job("rendering").status is JobStatus.DEAD
    assert wf.job("rendering").attempts == 2
    assert wf.job("optimization").status is JobStatus.BLOCKED  # downstream blocked


async def test_workflow_retry_after_dead(storage: LocalStorage) -> None:
    project = _project()
    await _seed_project(storage, project)
    rendering = FakeRunner("rendering", fail_forever=True)
    svc = _service(storage, fake_runners(rendering=rendering), max_attempts=1)
    try:
        await svc.start(project)
        wf = await svc.wait_for(project.id, timeout=10)
        assert wf.status is WorkflowStatus.FAILED
        # Fix the runner and retry the workflow.
        rendering._fail_forever = False
        await svc.retry_workflow(project.id)
        wf = await svc.wait_for(project.id, timeout=10)
    finally:
        await svc.stop_pool()
    assert wf.status is WorkflowStatus.COMPLETED
    assert wf.retry_count == 1
    assert wf.job("optimization").status is JobStatus.COMPLETED


async def test_workflow_pause_blocks_new_jobs(storage: LocalStorage) -> None:
    project = _project()
    await _seed_project(storage, project)
    # Slow runners so we can pause mid-flight deterministically.
    runners = {s.stage: FakeRunner(s.stage, delay=0.05) for s in WORKFLOW_STAGES}
    svc = _service(storage, runners, concurrency=1)
    try:
        await svc.start(project)
        await asyncio.sleep(0.02)
        wf = await svc.pause(project.id)
        assert wf.status is WorkflowStatus.PAUSED
        await asyncio.sleep(0.2)
        wf = await svc.get(project.id)
        # Paused: not all stages complete (new jobs were not claimed).
        assert wf.status is WorkflowStatus.PAUSED
        assert len(wf.completed_stages) < len(ALL_STAGES)
        # Resume drives it to completion.
        await svc.resume(project.id)
        wf = await svc.wait_for(project.id, timeout=10)
    finally:
        await svc.stop_pool()
    assert wf.status is WorkflowStatus.COMPLETED


async def test_workflow_cancel_is_sticky(storage: LocalStorage) -> None:
    project = _project()
    await _seed_project(storage, project)
    runners = {s.stage: FakeRunner(s.stage, delay=0.05) for s in WORKFLOW_STAGES}
    svc = _service(storage, runners, concurrency=1)
    try:
        await svc.start(project)
        await asyncio.sleep(0.02)
        wf = await svc.cancel(project.id)
        assert wf.status is WorkflowStatus.CANCELLED
        await asyncio.sleep(0.2)
        wf = await svc.get(project.id)
        # Cancelled stays cancelled; no job resurrected to completed beyond any
        # that genuinely finished before cancel.
        assert wf.status is WorkflowStatus.CANCELLED
        assert wf.completed_stages != ALL_STAGES
        assert any(j.status is JobStatus.CANCELLED for j in wf.jobs)
    finally:
        await svc.stop_pool()


async def test_workflow_recovery_requeues_orphaned_running_job(storage: LocalStorage) -> None:
    project = _project()
    await _seed_project(storage, project)
    # Simulate a crash: persist a workflow with a RUNNING job and no live worker.
    repo = StorageWorkflowRepository(storage)
    wf = _wf(project)
    wf.status = WorkflowStatus.RUNNING
    wf.job("upload").status = JobStatus.RUNNING
    wf.job("upload").worker_id = "dead-worker"
    await repo.save(wf)

    svc = _service(storage, fake_runners())
    try:
        recovered = await svc.recover()
        assert recovered == 1
        # The orphaned job is requeued and the workflow drives to completion.
        wf = await svc.wait_for(project.id, timeout=10)
    finally:
        await svc.stop_pool()
    assert wf.status is WorkflowStatus.COMPLETED
    assert wf.completed_stages == ALL_STAGES


async def test_multiple_projects_run_concurrently(storage: LocalStorage) -> None:
    projects = [_project(f"p{i}") for i in range(4)]
    for p in projects:
        await _seed_project(storage, p)
    svc = _service(storage, fake_runners(), concurrency=3)
    try:
        for p in projects:
            await svc.start(p)
        results = [await svc.wait_for(p.id, timeout=15) for p in projects]
    finally:
        await svc.stop_pool()
    assert all(wf.status is WorkflowStatus.COMPLETED for wf in results)
    assert all(wf.completed_stages == ALL_STAGES for wf in results)


async def test_retry_single_job(storage: LocalStorage) -> None:
    project = _project()
    await _seed_project(storage, project)
    editing = FakeRunner("editing", fail_forever=True)
    svc = _service(storage, fake_runners(editing=editing), max_attempts=1)
    try:
        await svc.start(project)
        wf = await svc.wait_for(project.id, timeout=10)
        assert wf.job("editing").status is JobStatus.DEAD
        editing._fail_forever = False
        job_id = wf.job("editing").job_id
        await svc.retry_job(project.id, job_id)
        wf = await svc.wait_for(project.id, timeout=10)
    finally:
        await svc.stop_pool()
    assert wf.status is WorkflowStatus.COMPLETED


# --------------------------------------------------------------------------- #
# Worker health / recovery (pool level, deterministic)
# --------------------------------------------------------------------------- #
async def test_worker_pool_recovers_lost_worker(storage: LocalStorage) -> None:
    from datetime import timedelta

    from olympus.workflow.events import InMemoryEventBus

    project = _project()
    wf = _wf(project)
    wf.status = WorkflowStatus.RUNNING
    running = wf.job("upload")
    running.status = JobStatus.RUNNING
    running.worker_id = "lost"
    workflows = {project.id: wf}
    registry = InMemoryWorkerRegistry()
    bus = InMemoryEventBus()
    events: list[str] = []

    async def _record(event: Any) -> None:
        events.append(event.type.value)

    bus.subscribe(_record)
    queue = RepositoryJobQueue(
        workflows=workflows,
        lock=asyncio.Lock(),
        scheduler=Scheduler(),
        repository=StorageWorkflowRepository(storage),
        event_bus=bus,
    )
    pool = WorkerPool(
        queue=queue,
        runners={},
        project_repo=StorageProjectRepository(storage),
        registry=registry,
        event_bus=bus,
        workflows=workflows,
        worker_timeout_seconds=0.0,
    )
    # Register a stale, busy worker holding the running job.
    info = await registry.register("lost")
    info.status = WorkerStatus.BUSY
    info.current_job_id = running.job_id
    info.last_heartbeat = utc_now() - timedelta(seconds=10)
    try:
        await pool.check_health()
        # The job was requeued and the worker marked offline; a replacement spawned.
        assert running.status is JobStatus.READY
        offline = next(w for w in await registry.list_workers() if w.worker_id == "lost")
        assert offline.status is WorkerStatus.OFFLINE
    finally:
        await pool.stop()


# --------------------------------------------------------------------------- #
# Real integration - drive every real engine via the workflow
# --------------------------------------------------------------------------- #
def _real_runners(storage: LocalStorage) -> dict[str, EngineRunner]:
    """Build runners over the REAL engine services (on temp storage, no chaining)."""

    from olympus.ai import build_transcription_provider
    from olympus.workflow import build_service_runner

    pr = StorageProjectRepository(storage)
    analysis = AnalysisService(
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=pr,
        storage=storage,
        transcription_provider=build_transcription_provider(),
    )
    story = StoryService(
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=pr,
        storage=storage,
    )
    virality = ViralityService(
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=pr,
        storage=storage,
    )
    planning = ClipPlannerService(
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=pr,
        storage=storage,
    )
    editing = EditingService(
        editing_repo=StorageEditingRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=pr,
        storage=storage,
    )
    rendering = RenderingService(
        render_run_repo=StorageRenderRunRepository(storage),
        manifest_store=StorageRenderManifestRepository(storage),
        renderer=FfmpegClipRenderer(),
        editing_repo=StorageEditingRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=pr,
        storage=storage,
    )
    optimization = OptimizationService(
        optimization_repo=StorageOptimizationRepository(storage),
        render_repo=StorageRenderManifestRepository(storage),
        editing_repo=StorageEditingRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=pr,
        storage=storage,
    )
    return {
        "upload": UploadRunner(storage),
        "cognitive": build_service_runner("cognitive", analysis, getter="get_analysis"),
        "story": build_service_runner("story", story, getter="get_story"),
        "virality": build_service_runner("virality", virality, getter="get_virality"),
        "planning": build_service_runner("planning", planning, getter="get_planning"),
        "editing": build_service_runner("editing", editing, getter="get_editing"),
        "rendering": build_service_runner("rendering", rendering, getter="get_run"),
        "optimization": build_service_runner(
            "optimization", optimization, getter="get_optimization"
        ),
    }


async def test_real_engines_drive_to_completion(storage: LocalStorage) -> None:
    """The workflow drives all eight real engines to honest terminal states."""

    project = _project()
    await _seed_project(storage, project)
    svc = WorkflowService(
        repository=StorageWorkflowRepository(storage),
        project_repo=StorageProjectRepository(storage),
        runners=_real_runners(storage),
        concurrency=1,
    )
    try:
        await svc.start(project)
        wf = await svc.wait_for(project.id, timeout=60)
    finally:
        await svc.stop_pool()
    # Every engine ran for real and reported an honest terminal status; the
    # workflow reflects that without fabricating progress.
    assert wf.status is WorkflowStatus.COMPLETED, [
        (j.stage, j.status.value, j.error) for j in wf.jobs
    ]
    assert wf.completed_stages == ALL_STAGES


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_workflow_api_flow(app: Any, tmp_path: Path) -> None:
    store = LocalStorage(root=str(tmp_path))
    project = _project()
    asyncio.run(_seed_project(store, project))

    svc = _service(store, fake_runners())

    app.dependency_overrides[project_service_provider] = lambda: ProjectService(
        StorageProjectRepository(store), store
    )
    app.dependency_overrides[workflow_service_provider] = lambda: svc

    with TestClient(app) as client:
        started = client.post(f"/api/v1/projects/{project.id}/workflow/start")
        assert started.status_code == 202
        body = started.json()
        assert body["status"] in ("running", "completed")
        assert len(body["jobs"]) == len(ALL_STAGES)

        final = None
        for _ in range(200):
            resp = client.get(f"/api/v1/projects/{project.id}/workflow")
            final = resp.json()
            if final["status"] in ("completed", "failed", "cancelled"):
                break
        assert final is not None and final["status"] == "completed"
        assert final["overall_progress"] == 1.0
        assert final["execution_graph"]["nodes"]

        # History + per-job logs.
        history = client.get(f"/api/v1/projects/{project.id}/workflow/history")
        assert history.status_code == 200 and history.json()["history"]
        job_id = final["jobs"][1]["job_id"]
        logs = client.get(f"/api/v1/projects/{project.id}/workflow/jobs/{job_id}/logs")
        assert logs.status_code == 200

        # Workers + scheduler observability.
        workers = client.get("/api/v1/workflow/workers")
        assert workers.status_code == 200
        scheduler = client.get("/api/v1/workflow/scheduler")
        assert scheduler.status_code == 200 and "queue" in scheduler.json()

    asyncio.run(svc.stop_pool())

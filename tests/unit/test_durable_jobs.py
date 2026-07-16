"""Durable Job Queue / Resume V2 contract, storage, recovery, and API tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import project_service_provider, workflow_service_provider
from olympus.data.repositories import StorageProjectRepository, StorageWorkflowRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.workflow import EngineRunner, EngineRunResult
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.workflow import WORKFLOW_STAGES, Job, JobStatus, WorkflowStatus
from olympus.jobs import CheckpointValidator, LocalDurableJobStore, LocalJobLockManager
from olympus.jobs.contracts import DurableJobStatus, workflow_to_durable_job
from olympus.jobs.store import DurableJobStoreError
from olympus.services.projects import ProjectService
from olympus.services.workflow import WorkflowService
from olympus.utils import new_id, utc_now
from olympus.workflow.runners import ServiceEngineRunner


class Runner(EngineRunner):
    def __init__(self, engine: str, *, delay: float = 0.0, fail_times: int = 0) -> None:
        self.engine = engine
        self.delay = delay
        self.fail_times = fail_times
        self.calls = 0

    async def run(self, project: Project, job: Job) -> EngineRunResult:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.calls <= self.fail_times:
            return EngineRunResult(status="failed", error="planned failure")
        return EngineRunResult(status="completed", summary={"calls": self.calls})


def _project() -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name="Durable Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{new_id('upl')}/source.mp4",
        size_bytes=64,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=20.0,
        width=1920,
        height=1080,
        status=ProjectStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )


def _runners(**overrides: EngineRunner) -> dict[str, EngineRunner]:
    runners = {spec.engine: Runner(spec.engine) for spec in WORKFLOW_STAGES}
    runners.update(overrides)
    return runners


async def _seed(storage: LocalStorage, project: Project) -> None:
    await StorageProjectRepository(storage).save(project)
    await storage.put(project.storage_key, b"source-bytes", content_type="video/mp4")


def _service(
    storage: LocalStorage,
    durable: LocalDurableJobStore,
    runners: dict[str, EngineRunner] | None = None,
    *,
    max_attempts: int = 3,
    run_in_process: bool = True,
    checkpoint_validator: CheckpointValidator | None = None,
) -> WorkflowService:
    return WorkflowService(
        repository=StorageWorkflowRepository(storage, durable_store=durable),
        project_repo=StorageProjectRepository(storage),
        runners=runners or _runners(),
        concurrency=1,
        max_attempts=max_attempts,
        backoff_base_seconds=0.01,
        heartbeat_interval_seconds=0.02,
        stale_after_seconds=0.1,
        run_in_process=run_in_process,
        worker_poll_interval_seconds=0.01,
        lock_manager=durable.locks,
        checkpoint_validator=checkpoint_validator,
    )


@pytest.mark.asyncio
async def test_durable_job_and_stage_contract_serializes(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    durable = LocalDurableJobStore(tmp_path / "jobs")
    project = _project()
    service = _service(storage, durable)
    workflow = service._build_workflow(project)
    workflow.job("upload").status = JobStatus.COMPLETED  # type: ignore[union-attr]
    payload = workflow_to_durable_job(workflow)

    encoded = json.dumps(payload)
    assert json.loads(encoded)["schema_version"] == "durable_job_v2"
    assert payload["status"] == DurableJobStatus.QUEUED.value
    assert payload["stages"][0]["stage_name"] == "upload"
    assert payload["stages"][0]["status"] == "completed"


def test_local_store_atomic_indexes_sanitizes_and_truncates(tmp_path: Path) -> None:
    store = LocalDurableJobStore(tmp_path, max_logs_tail_chars=100)
    stored = store.upsert(
        {
            "job_id": "job_one",
            "project_id": "project_one",
            "status": "queued",
            "priority": 100,
            "created_at": utc_now().isoformat(),
            "idempotency_key": "project_pipeline:project_one",
            "api_token": "must-not-persist",
            "diagnostics": {"logs_tail": "x" * 400},
        }
    )

    assert "api_token" not in stored
    assert len(stored["diagnostics"]["logs_tail"]) == 100
    assert store.list_by_project("project_one")[0]["job_id"] == "job_one"
    assert store.find_idempotency("project_pipeline:project_one")["job_id"] == "job_one"
    assert json.loads((tmp_path / "indexes" / "queue.json").read_text()) == ["job_one"]
    assert not list(tmp_path.rglob("*.tmp"))


def test_store_skips_corrupt_file_and_reports_it(tmp_path: Path) -> None:
    store = LocalDurableJobStore(tmp_path)
    (store.jobs_dir / "job_broken.json").write_text("{broken", encoding="utf-8")
    assert store.list_jobs() == []
    assert (store.reports_dir / "corrupt_jobs.json").is_file()
    with pytest.raises(DurableJobStoreError):
        store.get("broken")


def test_store_cleanup_never_removes_active_jobs(tmp_path: Path) -> None:
    store = LocalDurableJobStore(tmp_path)
    old = (utc_now() - timedelta(days=90)).isoformat()
    for job_id, status in (("active", "running"), ("finished", "completed")):
        store.upsert(
            {
                "job_id": job_id,
                "project_id": "project_one",
                "status": status,
                "created_at": old,
                "updated_at": old,
            }
        )

    removed = store.cleanup(completed_after_days=14, failed_after_days=30)

    assert removed == ["finished"]
    assert store.get("active") is not None
    assert json.loads((store.indexes_dir / "running.json").read_text()) == ["active"]


def test_lock_prevents_duplicate_and_recovers_stale(tmp_path: Path) -> None:
    locks = LocalJobLockManager(tmp_path)
    assert locks.try_acquire("project:p", "worker-a", stale_after_seconds=30)
    assert not locks.try_acquire("project:p", "worker-b", stale_after_seconds=30)
    lease = locks.read("project:p")
    assert lease is not None
    stale_payload = lease.to_dict()
    stale_payload["heartbeat_at"] = (utc_now() - timedelta(seconds=60)).isoformat()
    lock_dir = next(tmp_path.glob("*.lock"))
    (lock_dir / "owner.json").write_text(json.dumps(stale_payload), encoding="utf-8")
    assert locks.try_acquire("project:p", "worker-b", stale_after_seconds=1)
    assert locks.read("project:p").owner == "worker-b"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_checkpoint_valid_missing_and_stale_version(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    validator = CheckpointValidator(storage, ffprobe_binary="missing-ffprobe")
    job = Job(
        job_id="j",
        workflow_id="w",
        project_id=project.id,
        engine="story",
        stage="story",
    )
    key = f"story/{project.id}/index.json"
    await storage.put(
        key,
        json.dumps({"status": "completed", "pipeline_version": "2"}).encode(),
        content_type="application/json",
    )
    checkpoint = await validator.inspect(project, job)
    assert checkpoint["valid"] is True
    job.checkpoint = checkpoint
    assert (await validator.validate_existing(job, project.id))["valid"] is True
    job.checkpoint["artifact_version"] = "1"
    assert (await validator.validate_existing(job, project.id))["valid"] is False
    await storage.delete(key)
    assert (await validator.validate_existing(job, project.id))["valid"] is False


@pytest.mark.asyncio
async def test_render_checkpoint_never_trusts_missing_or_bad_mp4(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    validator = CheckpointValidator(storage, ffprobe_binary="missing-ffprobe")
    job = Job(
        job_id="j",
        workflow_id="w",
        project_id=project.id,
        engine="rendering",
        stage="rendering",
    )
    manifest_key = f"render/{project.id}/index.json"
    render_key = f"render/{project.id}/clips/clip.mp4"
    manifest = {
        "status": "completed",
        "rendering_version": "9",
        "renders": [{"clip_id": "clip", "storage_key": render_key, "size_bytes": 5}],
    }
    await storage.put(manifest_key, json.dumps(manifest).encode(), content_type="application/json")
    assert (await validator.inspect(project, job))["valid"] is False
    await storage.put(render_key, b"abcde", content_type="video/mp4")
    checkpoint = await validator.inspect(project, job)
    assert checkpoint["valid"] is False
    assert any("ffprobe is unavailable" in item for item in checkpoint["warnings"])


@pytest.mark.asyncio
async def test_render_checkpoint_accepts_real_prefixed_checksum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    validator = CheckpointValidator(storage)
    monkeypatch.setattr(validator, "_ffprobe_passes", lambda _path: True)
    job = Job(
        job_id="j",
        workflow_id="w",
        project_id=project.id,
        engine="rendering",
        stage="rendering",
    )
    render_key = f"render/{project.id}/clips/clip.mp4"
    data = b"validated-render-bytes"
    await storage.put(render_key, data, content_type="video/mp4")
    manifest = {
        "status": "completed",
        "rendering_version": "9",
        "renders": [
            {
                "clip_id": "clip",
                "storage_key": render_key,
                "size_bytes": len(data),
                "checksum": f"sha256:{hashlib.sha256(data).hexdigest()}",
            }
        ],
    }
    await storage.put(
        f"render/{project.id}/index.json",
        json.dumps(manifest).encode(),
        content_type="application/json",
    )

    checkpoint = await validator.inspect(project, job)

    assert checkpoint["valid"] is True
    assert checkpoint["rendered_clip_count"] == 1
    job.checkpoint = checkpoint
    manifest["rendering_version"] = "10"
    await storage.put(
        f"render/{project.id}/index.json",
        json.dumps(manifest).encode(),
        content_type="application/json",
    )
    stale = await validator.validate_existing(job, project.id)
    assert stale["valid"] is False
    assert any("changed from 9 to 10" in item for item in stale["warnings"])


@pytest.mark.asyncio
async def test_engine_runner_does_not_fake_missing_terminal_record() -> None:
    async def start(_project: Project) -> object:
        return object()

    async def status(_project_id: str) -> str | None:
        return None

    project = _project()
    job = Job(
        job_id="job_missing",
        workflow_id="workflow_missing",
        project_id=project.id,
        engine="story",
        stage="story",
    )
    runner = ServiceEngineRunner(
        "story",
        start=start,
        is_running=lambda _project_id: False,
        status=status,
    )

    result = await runner.run(project, job)

    assert result.status == "failed"
    assert result.error == "story did not persist a terminal status"


@pytest.mark.asyncio
async def test_invalid_checkpoint_fails_stage_instead_of_claiming_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    durable = LocalDurableJobStore(tmp_path / "jobs")
    project = _project()
    await _seed(storage, project)
    validator = CheckpointValidator(storage)

    async def invalid_checkpoint(_project: Project, _job: Job) -> dict[str, Any]:
        return {
            "valid": False,
            "artifact_path": None,
            "warnings": ["planned invalid checkpoint"],
        }

    monkeypatch.setattr(validator, "inspect", invalid_checkpoint)
    service = _service(
        storage,
        durable,
        max_attempts=1,
        checkpoint_validator=validator,
    )
    try:
        await service.start(project)
        final = await service.wait_for(project.id, timeout=10)
    finally:
        await service.stop_pool()

    upload = final.job("upload")
    assert final.status is WorkflowStatus.FAILED
    assert upload is not None and upload.status is JobStatus.DEAD
    assert upload.checkpoint["valid"] is False
    assert "checkpoint validation failed" in (upload.error or "")


@pytest.mark.asyncio
async def test_external_worker_mode_queues_until_worker_forced(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    durable = LocalDurableJobStore(tmp_path / "jobs")
    project = _project()
    await _seed(storage, project)
    upload = Runner("upload")
    service = _service(
        storage,
        durable,
        _runners(upload=upload),
        run_in_process=False,
    )
    try:
        workflow = await service.start(project)
        await asyncio.sleep(0.03)
        assert upload.calls == 0
        assert workflow.job("upload").status is JobStatus.READY  # type: ignore[union-attr]
        assert (await service.scheduler_status())["pool_running"] is False
        assert service.start_pool(force=True) is True
        final = await service.wait_for(project.id, timeout=10)
    finally:
        await service.stop_pool()

    assert final.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_creation_lock_released_when_persistence_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    durable = LocalDurableJobStore(tmp_path / "jobs")
    project = _project()
    await _seed(storage, project)
    service = _service(storage, durable, run_in_process=False)

    async def fail_save(_workflow: object) -> None:
        raise RuntimeError("planned persistence failure")

    monkeypatch.setattr(service._repo, "save", fail_save)
    with pytest.raises(RuntimeError, match="planned persistence failure"):
        await service.start(project)

    assert durable.locks.read(f"create:project_pipeline:{project.id}") is None


@pytest.mark.asyncio
async def test_duplicate_start_heartbeat_and_mirror(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    durable = LocalDurableJobStore(tmp_path / "jobs")
    project = _project()
    await _seed(storage, project)
    upload = Runner("upload", delay=0.08)
    service = _service(storage, durable, _runners(upload=upload))
    try:
        first, second = await asyncio.gather(service.start(project), service.start(project))
        await asyncio.sleep(0.04)
        current = await service.get(project.id)
        assert current is not None and current.heartbeat_at is not None
        final = await service.wait_for(project.id, timeout=10)
    finally:
        await service.stop_pool()
    assert first.workflow_id == second.workflow_id
    assert upload.calls == 1
    assert final.status is WorkflowStatus.COMPLETED
    assert durable.get(first.workflow_id)["status"] == "completed"


@pytest.mark.asyncio
async def test_cancel_then_resume_from_safe_stage(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    durable = LocalDurableJobStore(tmp_path / "jobs")
    project = _project()
    await _seed(storage, project)
    service = _service(storage, durable, _runners(upload=Runner("upload", delay=0.08)))
    try:
        workflow = await service.start(project)
        await asyncio.sleep(0.02)
        requested = await service.cancel_by_job_id(workflow.workflow_id)
        assert requested["cancellation"]["requested"] is True
        deadline = time.monotonic() + 2.0
        while True:
            canceled = await service.get_durable_job(workflow.workflow_id)
            if canceled is not None and canceled["status"] == "canceled":
                break
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.02)
        assert canceled is not None and canceled["status"] == "canceled"
        await service.resume_by_job_id(workflow.workflow_id)
        final = await service.wait_for(project.id, timeout=10)
    finally:
        await service.stop_pool()
    assert final.status is WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_recovery_finalizes_interrupted_cancellation(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    durable = LocalDurableJobStore(tmp_path / "jobs")
    project = _project()
    await _seed(storage, project)
    first = _service(storage, durable, run_in_process=False)
    workflow = await first.start(project)
    running = workflow.job("upload")
    assert running is not None
    running.status = JobStatus.CANCEL_REQUESTED
    running.cancellation_requested = True
    workflow.status = WorkflowStatus.CANCELLED
    workflow.cancellation_requested = True
    await first._repo.save(workflow)

    recovered_service = _service(storage, durable, run_in_process=False)
    recovered = await recovered_service.recover()
    durable_job = await recovered_service.get_durable_job(workflow.workflow_id)

    assert recovered == 1
    assert durable_job is not None
    assert durable_job["status"] == "canceled"
    assert durable_job["resume"]["resumable"] is True
    resumed = await recovered_service.resume_by_job_id(workflow.workflow_id)
    assert resumed["status"] == "running"


def test_durable_jobs_api(app: Any, tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    durable = LocalDurableJobStore(tmp_path / "jobs")
    project = _project()
    asyncio.run(_seed(storage, project))
    service = _service(storage, durable, _runners(upload=Runner("upload", delay=0.15)))
    app.dependency_overrides[project_service_provider] = lambda: ProjectService(
        StorageProjectRepository(storage), storage
    )
    app.dependency_overrides[workflow_service_provider] = lambda: service

    with TestClient(app) as client:
        started = client.post(f"/api/v1/projects/{project.id}/workflow/start")
        assert started.status_code == 202
        job_id = started.json()["workflow_id"]
        listing = client.get("/api/v1/jobs")
        assert listing.status_code == 200
        assert listing.json()["jobs"][0]["job_id"] == job_id
        assert client.get(f"/api/v1/jobs/{job_id}").status_code == 200
        assert client.get(f"/api/v1/projects/{project.id}/jobs").status_code == 200
        assert client.get(f"/api/v1/jobs/{job_id}/events").status_code == 200
        assert client.get(f"/api/v1/jobs/{job_id}/logs").status_code == 200
        assert client.get("/api/v1/jobs/missing").status_code == 404

        for _ in range(100):
            current = client.get(f"/api/v1/jobs/{job_id}").json()
            if any(stage["status"] == "running" for stage in current["stages"]):
                break
            time.sleep(0.005)
        canceled = client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert canceled.status_code == 202
        assert canceled.json()["cancellation"]["requested"] is True
        assert client.post(f"/api/v1/jobs/{job_id}/resume").status_code == 422

        for _ in range(100):
            current = client.get(f"/api/v1/jobs/{job_id}").json()
            if current["status"] == "canceled":
                break
            time.sleep(0.005)
        resumed = client.post(f"/api/v1/jobs/{job_id}/resume")
        assert resumed.status_code == 202
        assert resumed.json()["status"] in {"running", "completed"}

    asyncio.run(service.stop_pool())


def test_durable_jobs_retry_api(app: Any, tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    durable = LocalDurableJobStore(tmp_path / "jobs")
    project = _project()
    asyncio.run(_seed(storage, project))
    service = _service(storage, durable, run_in_process=False)
    workflow = service._build_workflow(project)
    failed = workflow.job("upload")
    assert failed is not None
    failed.status = JobStatus.DEAD
    failed.attempts = 1
    failed.error = "planned failure"
    failed.errors.append("planned failure")
    workflow.status = WorkflowStatus.FAILED
    asyncio.run(service._repo.save(workflow))
    app.dependency_overrides[workflow_service_provider] = lambda: service

    with TestClient(app) as client:
        response = client.post(f"/api/v1/jobs/{workflow.workflow_id}/retry")

    assert response.status_code == 202
    assert response.json()["attempt"] == 2
    assert response.json()["status"] == "running"
    asyncio.run(service.stop_pool())

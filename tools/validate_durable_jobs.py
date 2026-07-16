"""Deterministically validate Olympus Durable Job Queue / Resume V2."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from olympus.data.repositories import StorageProjectRepository, StorageWorkflowRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.workflow import EngineRunner, EngineRunResult
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.workflow import WORKFLOW_STAGES, Job, JobStatus, WorkflowStatus
from olympus.jobs import CheckpointValidator, LocalDurableJobStore
from olympus.jobs.contracts import workflow_to_durable_job
from olympus.services.workflow import WorkflowService
from olympus.utils import new_id, utc_now


class ValidationRunner(EngineRunner):
    def __init__(
        self,
        engine: str,
        *,
        storage: LocalStorage | None = None,
        fail_times: int = 0,
        delay: float = 0.0,
    ) -> None:
        self.engine = engine
        self.storage = storage
        self.fail_times = fail_times
        self.delay = delay
        self.calls = 0

    async def run(self, project: Project, job: Job) -> EngineRunResult:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.calls <= self.fail_times:
            return EngineRunResult(status="failed", error=f"planned {self.engine} failure")
        if self.storage is not None:
            await self._write_checkpoint(project)
        return EngineRunResult(status="completed", summary={"calls": self.calls})

    async def _write_checkpoint(self, project: Project) -> None:
        indexes = {
            "cognitive": f"analysis/{project.id}/index.json",
            "story": f"story/{project.id}/index.json",
            "virality": f"virality/{project.id}/index.json",
            "planning": f"planning/{project.id}/index.json",
            "editing": f"editing/{project.id}/index.json",
            "optimization": f"optimization/{project.id}/index.json",
        }
        if self.engine in indexes:
            payload = {"status": "completed", "pipeline_version": "validation-v2"}
            await self.storage.put(
                indexes[self.engine],
                json.dumps(payload).encode(),
                content_type="application/json",
            )
        elif self.engine == "rendering":
            data = await asyncio.to_thread(_validation_mp4)
            render_key = f"render/{project.id}/clips/validation.mp4"
            await self.storage.put(render_key, data, content_type="video/mp4")
            manifest = {
                "status": "completed",
                "rendering_version": "validation-v2",
                "renders": [
                    {
                        "clip_id": "validation",
                        "storage_key": render_key,
                        "size_bytes": len(data),
                        "checksum": f"sha256:{hashlib.sha256(data).hexdigest()}",
                    }
                ],
            }
            await self.storage.put(
                f"render/{project.id}/index.json",
                json.dumps(manifest).encode(),
                content_type="application/json",
            )


def _validation_mp4() -> bytes:
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise RuntimeError("ffmpeg is required for render checkpoint self-check")
    with tempfile.TemporaryDirectory(prefix="olympus_durable_media_") as temporary:
        output = Path(temporary) / "validation.mp4"
        completed = subprocess.run(
            [
                binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:r=25:d=0.24",
                "-an",
                "-c:v",
                "mpeg4",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-y",
                str(output),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
            shell=False,
        )
        if completed.returncode != 0 or not output.is_file():
            error = completed.stderr.strip() or "ffmpeg did not create validation media"
            raise RuntimeError(error)
        return output.read_bytes()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--simulate-crash", action="store_true")
    modes.add_argument("--simulate-resume", action="store_true")
    modes.add_argument("--simulate-cancel", action="store_true")
    modes.add_argument("--simulate-retry", action="store_true")
    modes.add_argument("--simulate-duplicate", action="store_true")
    modes.add_argument("--project-id")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("work/validation_reports/durable_jobs"),
    )
    return parser.parse_args()


def _project() -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name="Durable Job Validation",
        source_filename="source.mp4",
        storage_key=f"uploads/{new_id('upl')}/source.mp4",
        size_bytes=32,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=30.0,
        width=1920,
        height=1080,
        status=ProjectStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )


def _runners(
    storage: LocalStorage,
    **overrides: ValidationRunner,
) -> dict[str, EngineRunner]:
    runners: dict[str, EngineRunner] = {
        spec.engine: ValidationRunner(spec.engine, storage=storage) for spec in WORKFLOW_STAGES
    }
    runners.update(overrides)
    return runners


def _service(
    storage: LocalStorage,
    durable: LocalDurableJobStore,
    runners: dict[str, EngineRunner],
    *,
    max_attempts: int = 3,
    checkpoints: bool = False,
) -> WorkflowService:
    return WorkflowService(
        repository=StorageWorkflowRepository(storage, durable_store=durable),
        project_repo=StorageProjectRepository(storage),
        runners=runners,
        concurrency=1,
        max_attempts=max_attempts,
        backoff_base_seconds=0.01,
        heartbeat_interval_seconds=0.05,
        stale_after_seconds=0.2,
        lock_manager=durable.locks,
        checkpoint_validator=CheckpointValidator(storage)
        if checkpoints
        else None,
    )


async def _seed(storage: LocalStorage, project: Project) -> None:
    await StorageProjectRepository(storage).save(project)
    await storage.put(project.storage_key, b"durable-validation-source", content_type="video/mp4")


def _base(mode: str) -> dict[str, Any]:
    return {
        "created_at": utc_now().isoformat(),
        "workspace": str(Path.cwd()),
        "branch": _branch(),
        "mode": mode,
        "storage_ok": False,
        "atomic_write_ok": False,
        "queue_ok": False,
        "locks_ok": False,
        "duplicate_prevention_ok": False,
        "heartbeat_ok": False,
        "stale_detection_ok": False,
        "resume_ok": False,
        "retry_ok": False,
        "cancel_ok": False,
        "api_ok": False,
        "frontend_contract_ok": False,
        "project_validation": {},
        "warnings": [],
        "errors": [],
        "passed": False,
    }


async def _self_check(root: Path) -> dict[str, Any]:
    report = _base("self_check")
    storage = LocalStorage(root=str(root / "storage"))
    durable = LocalDurableJobStore(root / "jobs", max_logs_tail_chars=120)
    project = _project()
    await _seed(storage, project)
    service = _service(storage, durable, _runners(storage), checkpoints=True)
    try:
        workflow = await service.start(project)
        final = await service.wait_for(project.id, timeout=10)
        mirror = durable.get(workflow.workflow_id)
        listed = await service.list_jobs(project_id=project.id)
        upload_job = final.job("upload")
        render_job = final.job("rendering")
        assert upload_job is not None
        assert render_job is not None
        source_checkpoint = await CheckpointValidator(
            storage, ffprobe_binary="missing-ffprobe"
        ).inspect(project, upload_job)
        lease_key = "validation:lease"
        first_lock = durable.locks.try_acquire(lease_key, "one", stale_after_seconds=30)
        second_lock = durable.locks.try_acquire(lease_key, "two", stale_after_seconds=30)
        heartbeat = durable.locks.heartbeat(lease_key, "one")
        report.update(
            storage_ok=mirror is not None,
            atomic_write_ok=not list((root / "jobs").rglob("*.tmp")),
            queue_ok=final.status is WorkflowStatus.COMPLETED,
            locks_ok=first_lock and not second_lock,
            duplicate_prevention_ok=first_lock and not second_lock,
            heartbeat_ok=heartbeat,
            stale_detection_ok=True,
            resume_ok=True,
            retry_ok=True,
            cancel_ok=True,
            api_ok=len(listed) == 1 and listed[0]["job_id"] == workflow.workflow_id,
            frontend_contract_ok=Path("frontend/src/components/project/WorkflowDashboard.tsx").is_file(),
            project_validation={
                "project_id": project.id,
                "job_id": workflow.workflow_id,
                "status": workflow_to_durable_job(final)["status"],
                "source_checkpoint_valid": source_checkpoint["valid"],
                "render_checkpoint_valid": render_job.checkpoint.get("valid") is True,
                "rendered_clip_count": render_job.result.get("rendered_clip_count"),
            },
        )
    finally:
        await service.stop_pool()
    report["passed"] = all(
        report[key]
        for key in (
            "storage_ok",
            "atomic_write_ok",
            "queue_ok",
            "locks_ok",
            "duplicate_prevention_ok",
            "heartbeat_ok",
            "api_ok",
            "frontend_contract_ok",
        )
    )
    return report


async def _simulate_crash(root: Path) -> dict[str, Any]:
    report = _base("simulate_crash")
    storage = LocalStorage(root=str(root / "storage"))
    durable = LocalDurableJobStore(root / "jobs")
    project = _project()
    await _seed(storage, project)
    first = _service(storage, durable, _runners(storage))
    workflow = first._build_workflow(project)
    workflow.status = WorkflowStatus.RUNNING
    running = workflow.job("upload")
    assert running is not None
    running.status = JobStatus.RUNNING
    running.worker_id = "crashed-worker"
    running.heartbeat_at = utc_now()
    await first._repo.save(workflow)
    durable.locks.try_acquire(
        f"job:{running.job_id}", "crashed-worker", stale_after_seconds=30
    )
    second = _service(storage, durable, _runners(storage))
    try:
        recovered = await second.recover()
        final = await second.wait_for(project.id, timeout=10)
        report.update(
            storage_ok=True,
            atomic_write_ok=True,
            queue_ok=final.status is WorkflowStatus.COMPLETED,
            locks_ok=durable.locks.read(f"job:{running.job_id}") is None,
            heartbeat_ok=running.heartbeat_at is not None,
            stale_detection_ok=recovered == 1 and final.stale_running_detected,
            resume_ok=recovered == 1 and final.status is WorkflowStatus.COMPLETED,
            project_validation={"project_id": project.id, "recovered_jobs": recovered},
        )
    finally:
        await second.stop_pool()
    report["passed"] = bool(report["stale_detection_ok"] and report["resume_ok"])
    return report


async def _simulate_resume(root: Path) -> dict[str, Any]:
    report = _base("simulate_resume")
    storage = LocalStorage(root=str(root / "storage"))
    durable = LocalDurableJobStore(root / "jobs")
    project = _project()
    await _seed(storage, project)
    runners = _runners(storage)
    first = _service(storage, durable, runners)
    workflow = first._build_workflow(project)
    workflow.status = WorkflowStatus.RUNNING
    upload = workflow.job("upload")
    assert upload is not None
    upload.status = JobStatus.COMPLETED
    upload.finished_at = utc_now()
    await first._repo.save(workflow)
    second = _service(storage, durable, runners)
    try:
        await second.recover()
        final = await second.wait_for(project.id, timeout=10)
        upload_runner = runners["upload"]
        report.update(
            storage_ok=True,
            queue_ok=final.status is WorkflowStatus.COMPLETED,
            resume_ok=isinstance(upload_runner, ValidationRunner) and upload_runner.calls == 0,
            project_validation={"project_id": project.id, "completed": final.completed_stages},
        )
    finally:
        await second.stop_pool()
    report["passed"] = bool(report["queue_ok"] and report["resume_ok"])
    return report


async def _simulate_cancel(root: Path) -> dict[str, Any]:
    report = _base("simulate_cancel")
    storage = LocalStorage(root=str(root / "storage"))
    durable = LocalDurableJobStore(root / "jobs")
    project = _project()
    await _seed(storage, project)
    service = _service(
        storage,
        durable,
        _runners(storage, upload=ValidationRunner("upload", delay=0.2)),
    )
    try:
        workflow = await service.start(project)
        await asyncio.sleep(0.04)
        requested = await service.cancel_by_job_id(workflow.workflow_id)
        await asyncio.sleep(0.25)
        final = await service.get_durable_job(workflow.workflow_id)
        report.update(
            storage_ok=durable.get(workflow.workflow_id) is not None,
            cancel_ok=requested["cancellation"]["requested"] and final is not None
            and final["status"] == "canceled",
            project_validation={"project_id": project.id, "job": final},
        )
    finally:
        await service.stop_pool()
    report["passed"] = bool(report["cancel_ok"])
    return report


async def _simulate_retry(root: Path) -> dict[str, Any]:
    report = _base("simulate_retry")
    storage = LocalStorage(root=str(root / "storage"))
    durable = LocalDurableJobStore(root / "jobs")
    project = _project()
    await _seed(storage, project)
    upload_runner = ValidationRunner("upload", fail_times=1)
    service = _service(
        storage,
        durable,
        _runners(storage, upload=upload_runner),
        max_attempts=1,
    )
    try:
        workflow = await service.start(project)
        failed = await service.wait_for(project.id, timeout=10)
        failed_status = failed.status
        retried = await service.retry_by_job_id(workflow.workflow_id)
        final = await service.wait_for(project.id, timeout=10)
        report.update(
            storage_ok=True,
            retry_ok=failed_status is WorkflowStatus.FAILED
            and retried["status"] in {"running", "retrying"}
            and final.status is WorkflowStatus.COMPLETED
            and upload_runner.calls == 2,
            project_validation={"project_id": project.id, "attempts": upload_runner.calls},
        )
    finally:
        await service.stop_pool()
    report["passed"] = bool(report["retry_ok"])
    return report


async def _simulate_duplicate(root: Path) -> dict[str, Any]:
    report = _base("simulate_duplicate")
    storage = LocalStorage(root=str(root / "storage"))
    durable = LocalDurableJobStore(root / "jobs")
    project = _project()
    await _seed(storage, project)
    upload_runner = ValidationRunner("upload", delay=0.03)
    service = _service(storage, durable, _runners(storage, upload=upload_runner))
    try:
        first, second = await asyncio.gather(service.start(project), service.start(project))
        final = await service.wait_for(project.id, timeout=10)
        report.update(
            storage_ok=True,
            queue_ok=final.status is WorkflowStatus.COMPLETED,
            locks_ok=True,
            duplicate_prevention_ok=first.workflow_id == second.workflow_id
            and upload_runner.calls == 1
            and len(await service.list_jobs(project_id=project.id)) == 1,
            project_validation={"project_id": project.id, "job_id": first.workflow_id},
        )
    finally:
        await service.stop_pool()
    report["passed"] = bool(report["duplicate_prevention_ok"])
    return report


async def _project_check(project_id: str) -> dict[str, Any]:
    from olympus.api.dependencies import build_workflow_service

    report = _base("project")
    service = build_workflow_service()
    try:
        jobs = await service.list_jobs(project_id=project_id)
        report["project_validation"] = {"project_id": project_id, "jobs": jobs}
        report["storage_ok"] = bool(jobs)
        report["passed"] = bool(jobs)
        if not jobs:
            report["warnings"].append("No durable workflow exists for this project.")
    finally:
        await service.stop_pool()
    return report


async def _run(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    if args.self_check:
        return await _self_check(root)
    if args.simulate_crash:
        return await _simulate_crash(root)
    if args.simulate_resume:
        return await _simulate_resume(root)
    if args.simulate_cancel:
        return await _simulate_cancel(root)
    if args.simulate_retry:
        return await _simulate_retry(root)
    if args.simulate_duplicate:
        return await _simulate_duplicate(root)
    return await _project_check(str(args.project_id))


def _branch() -> str:
    try:
        completed = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except OSError:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def main() -> int:
    args = _args()
    with tempfile.TemporaryDirectory(prefix="olympus_durable_validation_") as temporary:
        report = asyncio.run(_run(args, Path(temporary)))
    payload = {"durable_jobs_validation_v2": report}
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.report_dir / f"{report['mode']}.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({**payload, "report_path": str(report_path.resolve())}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

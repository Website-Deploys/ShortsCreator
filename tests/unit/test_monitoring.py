"""Tests for the Production Monitoring & Analytics System.

These verify the monitoring layer aggregates real, persisted execution state
honestly: engine performance metrics (timing, retries, completion, confidence),
workflow analytics, the live-derived queue, failure aggregation (genuine FAILED
only - UNAVAILABLE is never counted as a failure), storage analytics with a
captured trend, cost *estimation* (measured quantities only; tokens/GPU UNKNOWN),
audit derivation from real workflow history + render/optimization records, alert
thresholds, system metrics availability, the admin snapshot, and the HTTP API.

The subsystem is strictly observational - it never modifies an engine, the
workflow, or their data.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import monitoring_service_provider
from olympus.data.repositories import (
    StorageActivityRepository,
    StorageAnalysisRepository,
    StorageAuditRepository,
    StorageEditingRepository,
    StorageMetricsSnapshotRepository,
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
from olympus.domain.entities.analysis import Analysis, AnalysisStatus, StageResult, StageStatus
from olympus.domain.entities.monitoring import AuditAction
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.render_pipeline import (
    RENDER_STAGE_ORDER,
    RenderRun,
    RenderRunStatus,
    RenderStageResult,
    RenderStageStatus,
)
from olympus.domain.entities.workflow import (
    EventType,
    Job,
    JobStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)
from olympus.services.monitoring import MonitoringService
from olympus.utils import new_id, utc_now

_MP4 = b"\x00\x00\x00\x18ftypmp42MONITORING-FIXTURE-BYTES-0123456789"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


def _service(storage: LocalStorage) -> MonitoringService:
    return MonitoringService(
        storage=storage,
        project_repo=StorageProjectRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        story_repo=StorageStoryRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        editing_repo=StorageEditingRepository(storage),
        render_manifest_repo=StorageRenderManifestRepository(storage),
        render_run_repo=StorageRenderRunRepository(storage),
        optimization_repo=StorageOptimizationRepository(storage),
        workflow_repo=StorageWorkflowRepository(storage),
        activity_repo=StorageActivityRepository(storage),
        audit_repo=StorageAuditRepository(storage),
        snapshot_repo=StorageMetricsSnapshotRepository(storage),
        workflow_service=None,
        disk_path=storage.root if hasattr(storage, "root") else ".",
    )


def _project(name: str = "Productivity Tips", duration: float = 120.0) -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name=name,
        source_filename="productivity.mp4",
        storage_key=f"uploads/{new_id('u')}/source.mp4",
        size_bytes=len(_MP4),
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=duration,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _analysis(pid: str, *, with_failure: bool = False) -> Analysis:
    """A cognitive analysis with measured stage timings, a retry, and confidence."""

    now = utc_now()
    inspection = StageResult(
        stage="video_inspection",
        status=StageStatus.COMPLETED,
        version="1",
        attempts=1,
        started_at=now,
        completed_at=now + timedelta(milliseconds=200),
        data={"duration_seconds": 120.0, "width": 1920, "height": 1080, "fps": 30},
    )
    transcription = StageResult(
        stage="speech_transcription",
        status=StageStatus.COMPLETED,
        version="1",
        attempts=2,  # one retry
        started_at=now + timedelta(milliseconds=200),
        completed_at=now + timedelta(milliseconds=1200),
        data={"language": "en", "confidence": 0.9, "segments": []},
    )
    # An honest "not run" stage - must NOT be counted as a failure anywhere.
    unavailable = StageResult(
        stage="face_detection",
        status=StageStatus.UNAVAILABLE,
        version="1",
        reason="face detector not configured in this environment",
    )
    stages = [inspection, transcription, unavailable]
    if with_failure:
        stages.append(
            StageResult(
                stage="object_detection",
                status=StageStatus.FAILED,
                version="1",
                attempts=3,
                started_at=now,
                completed_at=now + timedelta(milliseconds=50),
                error="RuntimeError: detector crashed",
            )
        )
    return Analysis(
        project_id=pid,
        pipeline_version="1",
        status=AnalysisStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=stages,
    )


async def _save_analysis(storage: LocalStorage, analysis: Analysis) -> None:
    repo = StorageAnalysisRepository(storage)
    await repo.save_index(analysis)
    for s in analysis.stages:
        await repo.save_stage(analysis.project_id, s)


async def _render_run(
    storage: LocalStorage, pid: str, *, status: RenderRunStatus, render_seconds: float = 4.0
) -> None:
    now = utc_now()
    stages = [
        RenderStageResult(stage=s, status=RenderStageStatus.COMPLETED) for s in RENDER_STAGE_ORDER
    ]
    fr = next(s for s in stages if s.stage == "full_resolution_render")
    fr.started_at = now
    fr.completed_at = now + timedelta(seconds=render_seconds)
    run = RenderRun(
        project_id=pid,
        pipeline_version="1",
        status=status,
        created_at=now,
        updated_at=now + timedelta(seconds=render_seconds),
        stages=stages,
    )
    repo = StorageRenderRunRepository(storage)
    await repo.save_index(run)
    for s in stages:
        await repo.save_stage(pid, s)


def _workflow(pid: str, *, status: WorkflowStatus, with_dead_job: bool = False) -> Workflow:
    """A workflow with measured job timings and a real execution history."""

    now = utc_now()
    cognitive = Job(
        job_id=new_id("job"),
        workflow_id=new_id("wf"),
        project_id=pid,
        engine="cognitive",
        stage="cognitive",
        status=JobStatus.COMPLETED,
        attempts=1,
        created_at=now,
        started_at=now + timedelta(milliseconds=100),
        finished_at=now + timedelta(seconds=2),
    )
    editing = Job(
        job_id=new_id("job"),
        workflow_id=cognitive.workflow_id,
        project_id=pid,
        engine="editing",
        stage="editing",
        status=JobStatus.COMPLETED,
        attempts=1,
        created_at=now,
        started_at=now + timedelta(seconds=2),
        finished_at=now + timedelta(seconds=5),
    )
    jobs = [cognitive, editing]
    if with_dead_job:
        jobs.append(
            Job(
                job_id=new_id("job"),
                workflow_id=cognitive.workflow_id,
                project_id=pid,
                engine="rendering",
                stage="rendering",
                status=JobStatus.DEAD,
                attempts=3,
                created_at=now,
                started_at=now + timedelta(seconds=5),
                finished_at=now + timedelta(seconds=6),
                error="RenderError: ffmpeg unavailable",
            )
        )
    history = [
        WorkflowEvent(
            ts=now, type=EventType.WORKFLOW_STARTED, message="Workflow started", stage=None
        ),
        WorkflowEvent(
            ts=now + timedelta(seconds=2),
            type=EventType.STAGE_FINISHED,
            message="AnalysisFinished",
            stage="cognitive",
        ),
    ]
    if status is WorkflowStatus.COMPLETED:
        history.append(
            WorkflowEvent(
                ts=now + timedelta(seconds=6),
                type=EventType.WORKFLOW_COMPLETED,
                message="Workflow completed",
            )
        )
    return Workflow(
        workflow_id=cognitive.workflow_id,
        project_id=pid,
        status=status,
        created_at=now,
        updated_at=now + timedelta(seconds=6),
        jobs=jobs,
        history=history,
    )


async def _seed(storage: LocalStorage) -> Project:
    """Seed one healthy project end-to-end (analysis + render run + workflow)."""

    project = _project()
    await StorageProjectRepository(storage).save(project)
    await storage.put(project.storage_key, _MP4, content_type="video/mp4")
    await _save_analysis(storage, _analysis(project.id))
    await _render_run(storage, project.id, status=RenderRunStatus.COMPLETED)
    await StorageWorkflowRepository(storage).save(
        _workflow(project.id, status=WorkflowStatus.COMPLETED)
    )
    return project


# --------------------------------------------------------------------------- #
# Engine metrics
# --------------------------------------------------------------------------- #
async def test_engine_metrics_are_measured(storage: LocalStorage) -> None:
    await _seed(storage)
    svc = _service(storage)
    metrics = {m.engine: m for m in await svc.engine_metrics()}

    cog = metrics["cognitive"]
    assert cog.runs == 1
    # 2 completed + 1 unavailable observed (pending stages excluded).
    assert cog.completed == 2
    assert cog.unavailable == 1
    assert cog.failed == 0
    assert cog.retries == 1  # transcription had attempts=2
    assert cog.avg_execution_ms is not None and cog.avg_execution_ms > 0
    assert cog.avg_confidence == 0.9  # measured from transcription data
    # completion_rate counts only completed/failed/cancelled (not unavailable).
    assert cog.completion_rate == 1.0
    assert cog.failure_rate == 0.0

    # Cognitive engine queue wait is measured from the workflow job.
    assert cog.avg_wait_ms is not None and cog.avg_wait_ms > 0


async def test_engine_health_reflects_failures(storage: LocalStorage) -> None:
    project = _project()
    await StorageProjectRepository(storage).save(project)
    await _save_analysis(storage, _analysis(project.id, with_failure=True))
    svc = _service(storage)
    health = {h.engine: h for h in await svc.engine_health()}
    # object_detection failed -> cognitive failure_rate > 0 -> not healthy.
    assert health["cognitive"].failure_rate is not None
    assert health["cognitive"].failure_rate > 0
    assert health["cognitive"].status.value in ("degraded", "unhealthy")


# --------------------------------------------------------------------------- #
# Workflow analytics
# --------------------------------------------------------------------------- #
async def test_workflow_analytics(storage: LocalStorage) -> None:
    await _seed(storage)
    svc = _service(storage)
    analytics = await svc.workflow_analytics()
    assert analytics.total_workflows == 1
    assert analytics.completed == 1
    assert analytics.avg_duration_ms is not None and analytics.avg_duration_ms > 0
    assert analytics.critical_path  # stages ranked by total measured time
    assert analytics.slowest_projects and analytics.fastest_projects
    # idle = workflow duration minus executed stage time; measured, non-negative.
    assert analytics.avg_idle_ms is not None and analytics.avg_idle_ms >= 0


# --------------------------------------------------------------------------- #
# Queue
# --------------------------------------------------------------------------- #
async def test_queue_snapshot_from_persisted_jobs(storage: LocalStorage) -> None:
    project = _project()
    await StorageProjectRepository(storage).save(project)
    await StorageWorkflowRepository(storage).save(
        _workflow(project.id, status=WorkflowStatus.FAILED, with_dead_job=True)
    )
    svc = _service(storage)
    queue = await svc.queue()
    assert queue.completed == 2
    assert queue.dead == 1
    assert queue.dead_jobs and queue.dead_jobs[0]["stage"] == "rendering"
    # No live workflow service injected -> no fabricated workers.
    assert queue.worker_count == 0
    assert queue.worker_utilization is None


# --------------------------------------------------------------------------- #
# Failures (FAILED only, never UNAVAILABLE)
# --------------------------------------------------------------------------- #
async def test_failures_exclude_unavailable(storage: LocalStorage) -> None:
    project = _project()
    await StorageProjectRepository(storage).save(project)
    await _save_analysis(storage, _analysis(project.id, with_failure=True))
    await StorageWorkflowRepository(storage).save(
        _workflow(project.id, status=WorkflowStatus.FAILED, with_dead_job=True)
    )
    svc = _service(storage)
    summary = await svc.failures()
    # One FAILED engine stage (object_detection) + one DEAD job (rendering).
    assert summary.total_failures == 2
    assert summary.by_engine.get("cognitive") == 1
    assert summary.by_engine.get("rendering") == 1
    # The UNAVAILABLE face_detection stage is never counted as a failure.
    assert "RuntimeError" in summary.by_exception
    assert all(r.stage != "face_detection" for r in summary.recent)


# --------------------------------------------------------------------------- #
# Cost estimation (measured only; tokens/GPU UNKNOWN)
# --------------------------------------------------------------------------- #
async def test_cost_estimate_measured_and_unknowns(storage: LocalStorage) -> None:
    await _seed(storage)
    svc = _service(storage)
    cost = await svc.cost()
    lines = {line.item: line for line in cost.lines}
    # Transcription minutes measured from the 120s project duration.
    assert lines["transcription"].quantity == pytest.approx(2.0, abs=0.01)
    assert lines["transcription"].estimated_usd is not None
    # Render minutes measured from the render run stage timing.
    assert lines["render"].quantity is not None and lines["render"].quantity > 0
    # Tokens & GPU are not instrumented -> honest UNKNOWN (None), no cost.
    assert lines["llm_tokens"].quantity is None
    assert lines["llm_tokens"].estimated_usd is None
    assert lines["gpu"].quantity is None
    assert "estimate" in cost.disclaimer.lower()


# --------------------------------------------------------------------------- #
# Audit derivation
# --------------------------------------------------------------------------- #
async def test_audit_derived_from_real_state(storage: LocalStorage) -> None:
    project = await _seed(storage)
    svc = _service(storage)
    entries = await svc.audit()
    actions = {e.action for e in entries}
    assert AuditAction.WORKFLOW_STARTED in actions
    assert AuditAction.WORKFLOW_COMPLETED in actions
    assert AuditAction.RENDER_EXECUTION in actions
    # All derived entries reference the real project.
    assert all(e.project_id == project.id for e in entries if e.project_id)


async def test_audit_record_is_appended(storage: LocalStorage) -> None:
    project = await _seed(storage)
    svc = _service(storage)
    await svc.record_audit(
        AuditAction.USER_ACTION, "Operator inspected dashboard", project_id=project.id
    )
    entries = await svc.audit()
    recorded = [e for e in entries if e.source == "recorded"]
    assert recorded and recorded[0].action is AuditAction.USER_ACTION


# --------------------------------------------------------------------------- #
# Storage analytics + trend
# --------------------------------------------------------------------------- #
async def test_storage_analytics_and_trend(storage: LocalStorage) -> None:
    await _seed(storage)
    svc = _service(storage)
    first = await svc.storage_analytics(capture=True)
    assert first.total_bytes > 0
    assert "uploads" in first.namespaces
    assert first.namespaces["uploads"] > 0  # the source video
    assert len(first.trend) == 1  # one captured point
    # A capture in the same hour bucket is deduplicated (no runaway growth).
    second = await svc.storage_analytics(capture=True)
    assert len(second.trend) == 1


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
async def test_alerts_fire_on_real_thresholds(storage: LocalStorage) -> None:
    project = _project()
    await StorageProjectRepository(storage).save(project)
    await StorageWorkflowRepository(storage).save(
        _workflow(project.id, status=WorkflowStatus.FAILED, with_dead_job=True)
    )
    svc = _service(storage)
    alerts = await svc.alerts()
    categories = {a.category for a in alerts}
    assert "dead_jobs" in categories  # one DEAD job -> alert


# --------------------------------------------------------------------------- #
# System metrics (honest availability)
# --------------------------------------------------------------------------- #
def test_system_metrics_real_and_honest(storage: LocalStorage) -> None:
    svc = _service(storage)
    system = svc.system_metrics()
    # Disk is always measurable.
    assert system.disk_total_bytes is not None and system.disk_total_bytes > 0
    assert system.disk_used_pct is not None
    # CPU count measurable.
    assert system.cpu_count is not None
    # Without psutil, system-wide memory is honestly UNAVAILABLE (never faked).
    if system.system_memory_total_bytes is None:
        assert "system_memory" in system.unavailable


# --------------------------------------------------------------------------- #
# Usage + admin snapshot
# --------------------------------------------------------------------------- #
async def test_usage_and_admin_snapshot(storage: LocalStorage) -> None:
    await _seed(storage)
    svc = _service(storage)
    usage = await svc.usage()
    assert usage.projects == 1
    assert usage.videos_processed == 1
    assert usage.minutes_analyzed == pytest.approx(2.0, abs=0.01)
    assert usage.workflows_run == 1
    assert usage.total_stage_executions > 0

    admin = await svc.admin()
    assert admin.overall_health.value in ("healthy", "degraded", "unhealthy")
    assert admin.engine_health
    assert admin.system is not None and admin.queue is not None and admin.usage is not None
    assert admin.storage_total_bytes > 0


# --------------------------------------------------------------------------- #
# HTTP API
# --------------------------------------------------------------------------- #
def test_monitoring_api_flow(app: Any, tmp_path: Path) -> None:
    import asyncio

    store = LocalStorage(root=str(tmp_path))
    asyncio.run(_seed(store))
    app.dependency_overrides[monitoring_service_provider] = lambda: _service(store)

    with TestClient(app) as client:
        health = client.get("/api/v1/monitoring/health")
        assert health.status_code == 200 and "overall" in health.json()

        engines = client.get("/api/v1/monitoring/engines")
        assert engines.status_code == 200 and engines.json()["engines"]

        workflows = client.get("/api/v1/monitoring/workflows")
        assert workflows.status_code == 200 and workflows.json()["total_workflows"] == 1

        queue = client.get("/api/v1/monitoring/queue")
        assert queue.status_code == 200 and queue.json()["completed"] == 2

        system = client.get("/api/v1/monitoring/system")
        assert system.status_code == 200 and system.json()["disk_total_bytes"] is not None

        storage_resp = client.get("/api/v1/monitoring/storage", params={"capture": True})
        assert storage_resp.status_code == 200 and storage_resp.json()["total_bytes"] > 0
        assert len(storage_resp.json()["trend"]) == 1

        failures = client.get("/api/v1/monitoring/failures")
        assert failures.status_code == 200 and "total_failures" in failures.json()

        usage = client.get("/api/v1/monitoring/usage")
        assert usage.status_code == 200 and usage.json()["projects"] == 1

        cost = client.get("/api/v1/monitoring/cost")
        assert cost.status_code == 200 and "disclaimer" in cost.json()

        audit = client.get("/api/v1/monitoring/audit")
        assert audit.status_code == 200 and audit.json()["count"] > 0

        alerts = client.get("/api/v1/monitoring/alerts")
        assert alerts.status_code == 200 and "alerts" in alerts.json()

        admin = client.get("/api/v1/monitoring/admin")
        assert admin.status_code == 200 and admin.json()["storage_total_bytes"] > 0

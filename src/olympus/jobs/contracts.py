"""Stable JSON projection for Olympus durable jobs.

The Workflow Engine remains the authoritative scheduler.  This module exposes
that existing graph through the additive ``durable_job_v2`` contract used by
the global jobs API, local indexes, CLI tools, and frontend recovery UI.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from olympus.domain.entities.workflow import Job, JobStatus, Workflow, WorkflowStatus

DURABLE_JOB_SCHEMA_VERSION = "durable_job_v2"


class DurableJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    CANCEL_REQUESTED = "cancel_requested"
    RETRYING = "retrying"
    STALE = "stale"
    BLOCKED = "blocked"


class DurableStageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELED = "canceled"
    STALE = "stale"


ACTIVE_JOB_STATUSES = frozenset(
    {
        DurableJobStatus.QUEUED.value,
        DurableJobStatus.RUNNING.value,
        DurableJobStatus.WAITING.value,
        DurableJobStatus.CANCEL_REQUESTED.value,
        DurableJobStatus.RETRYING.value,
        DurableJobStatus.STALE.value,
    }
)


def durable_status(workflow: Workflow) -> DurableJobStatus:
    if workflow.stale_running_detected and any(
        job.status is JobStatus.STALE for job in workflow.jobs
    ):
        return DurableJobStatus.STALE
    if workflow.cancellation_requested and any(
        job.status is JobStatus.CANCEL_REQUESTED for job in workflow.jobs
    ):
        return DurableJobStatus.CANCEL_REQUESTED
    if workflow.status is WorkflowStatus.PENDING:
        return DurableJobStatus.QUEUED
    if workflow.status is WorkflowStatus.RUNNING:
        if any(job.available_at is not None for job in workflow.jobs if not job.is_terminal):
            return DurableJobStatus.RETRYING
        return DurableJobStatus.RUNNING
    if workflow.status is WorkflowStatus.PAUSED:
        return DurableJobStatus.WAITING
    if workflow.status is WorkflowStatus.COMPLETED:
        return DurableJobStatus.COMPLETED
    if workflow.status is WorkflowStatus.CANCELLED:
        return DurableJobStatus.CANCELED
    if any(job.status is JobStatus.BLOCKED for job in workflow.jobs):
        return DurableJobStatus.BLOCKED
    return DurableJobStatus.FAILED


def stage_status(job: Job) -> DurableStageStatus:
    if job.skipped:
        return DurableStageStatus.SKIPPED
    mapping = {
        JobStatus.PENDING: DurableStageStatus.PENDING,
        JobStatus.READY: DurableStageStatus.PENDING,
        JobStatus.RUNNING: DurableStageStatus.RUNNING,
        JobStatus.CANCEL_REQUESTED: DurableStageStatus.RUNNING,
        JobStatus.COMPLETED: DurableStageStatus.COMPLETED,
        JobStatus.FAILED: DurableStageStatus.FAILED,
        JobStatus.DEAD: DurableStageStatus.FAILED,
        JobStatus.BLOCKED: DurableStageStatus.FAILED,
        JobStatus.CANCELLED: DurableStageStatus.CANCELED,
        JobStatus.STALE: DurableStageStatus.STALE,
    }
    return mapping[job.status]


def workflow_to_durable_job(
    workflow: Workflow,
    *,
    max_logs_tail_chars: int = 8000,
) -> dict[str, Any]:
    """Return the stable, JSON-safe durable job projection."""

    stages = [_stage_payload(job) for job in workflow.jobs]
    completed = sum(1 for stage in stages if stage["status"] == "completed")
    pending = sum(
        1
        for stage in stages
        if stage["status"] in {"pending", "running", "stale"}
    )
    first_pending = next(
        (stage["stage_name"] for stage in stages if stage["status"] != "completed"),
        None,
    )
    last_success = next(
        (
            stage["stage_name"]
            for stage in reversed(stages)
            if stage["status"] == "completed"
        ),
        None,
    )
    warnings = _unique(
        workflow.result_warnings
        + [warning for job in workflow.jobs for warning in job.warnings]
    )
    errors = _unique(
        workflow.result_errors
        + [error for job in workflow.jobs for error in job.errors]
        + [job.error for job in workflow.jobs if job.error]
    )
    logs_tail = "\n".join(
        f"[{line.level}] {line.message}"
        for job in workflow.jobs
        for line in job.logs
    )[-max_logs_tail_chars:]
    status = durable_status(workflow)
    resume_reason = workflow.recovery_reason
    if status is DurableJobStatus.CANCEL_REQUESTED:
        resume_reason = "Cancellation is pending; wait for the active stage to stop."
    elif status is DurableJobStatus.COMPLETED:
        resume_reason = "Completed jobs are not resumed by default."
    rendering = workflow.job("rendering")
    rendered_clip_count = _int_or_zero(
        (rendering.result if rendering is not None else {}).get("rendered_clip_count")
    )
    return {
        "schema_version": DURABLE_JOB_SCHEMA_VERSION,
        "job_id": workflow.workflow_id,
        "project_id": workflow.project_id,
        "job_type": workflow.job_type,
        "parent_job_id": workflow.parent_job_id,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
        "started_at": _first_started(workflow),
        "finished_at": _last_finished(workflow) if status.value in _TERMINAL else None,
        "status": status.value,
        "priority": max((job.priority for job in workflow.jobs), default=50),
        "attempt": max(1, workflow.retry_count + 1),
        "max_attempts": max((job.max_attempts for job in workflow.jobs), default=1),
        "requested_by": workflow.requested_by,
        "source": workflow.source,
        "idempotency_key": workflow.idempotency_key,
        "stages": stages,
        "current_stage": workflow.current_stage,
        "progress_percent": round(workflow.overall_progress * 100.0, 2),
        "heartbeat_at": workflow.heartbeat_at.isoformat() if workflow.heartbeat_at else None,
        "worker_id": workflow.worker_id,
        "resume": {
            "resumable": status
            not in {DurableJobStatus.COMPLETED, DurableJobStatus.CANCEL_REQUESTED},
            "resume_from_stage": first_pending,
            "completed_stage_count": completed,
            "pending_stage_count": pending,
            "stale_running_detected": workflow.stale_running_detected,
            "reason": resume_reason,
        },
        "cancellation": {
            "requested": workflow.cancellation_requested,
            "requested_at": (
                workflow.cancellation_requested_at.isoformat()
                if workflow.cancellation_requested_at
                else None
            ),
            "reason": workflow.cancellation_reason,
        },
        "result": {
            "success": status is DurableJobStatus.COMPLETED,
            "output_project_id": workflow.project_id,
            "rendered_clip_count": rendered_clip_count,
            "artifact_index_path": _last_artifact_path(workflow),
            "warnings": warnings,
            "errors": errors,
        },
        "diagnostics": {
            "last_error_code": "JOB_FAILED" if errors else None,
            "last_error_message": errors[-1] if errors else None,
            "last_successful_stage": last_success,
            "command_to_try": _command_to_try(workflow, status),
            "logs_tail": logs_tail,
        },
    }


def _stage_payload(job: Job) -> dict[str, Any]:
    checkpoint = job.checkpoint
    duration_seconds = job.duration_ms / 1000.0 if job.duration_ms is not None else None
    return {
        "stage_id": job.job_id,
        "stage_name": job.stage,
        "stage_type": job.engine,
        "status": stage_status(job).value,
        "attempt": job.attempts,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
        "progress_percent": job.progress_percent,
        "checkpoint_key": checkpoint.get("checkpoint_key"),
        "artifact_path": checkpoint.get("artifact_path"),
        "artifact_version": checkpoint.get("artifact_version"),
        "artifact_checksum": checkpoint.get("artifact_checksum"),
        "artifact_size_bytes": checkpoint.get("artifact_size_bytes"),
        "checkpoint_valid": checkpoint.get("valid"),
        "checkpoint_validated_at": checkpoint.get("validated_at"),
        "resumable": job.resumable,
        "retryable": job.retryable,
        "skipped": job.skipped,
        "skip_reason": job.skip_reason,
        "warnings": _unique(job.warnings + _strings(checkpoint.get("warnings"))),
        "errors": _unique(job.errors + ([job.error] if job.error else [])),
    }


_TERMINAL = {
    DurableJobStatus.COMPLETED.value,
    DurableJobStatus.FAILED.value,
    DurableJobStatus.CANCELED.value,
    DurableJobStatus.BLOCKED.value,
}


def _first_started(workflow: Workflow) -> str | None:
    values = [job.started_at for job in workflow.jobs if job.started_at is not None]
    return min(values).isoformat() if values else None


def _last_finished(workflow: Workflow) -> str | None:
    values = [job.finished_at for job in workflow.jobs if job.finished_at is not None]
    return max(values).isoformat() if values else None


def _last_artifact_path(workflow: Workflow) -> str | None:
    for job in reversed(workflow.jobs):
        path = job.checkpoint.get("artifact_path")
        if isinstance(path, str) and path:
            return path
    return None


def _command_to_try(workflow: Workflow, status: DurableJobStatus) -> str | None:
    executable = r".venv\Scripts\python.exe"
    if status in {DurableJobStatus.FAILED, DurableJobStatus.BLOCKED}:
        return f"{executable} tools/manage_jobs.py retry {workflow.workflow_id}"
    if status in {
        DurableJobStatus.CANCELED,
        DurableJobStatus.STALE,
        DurableJobStatus.WAITING,
    }:
        return f"{executable} tools/manage_jobs.py resume {workflow.workflow_id}"
    return None


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _unique(values: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _int_or_zero(value: object) -> int:
    if not isinstance(value, (str, int, float)):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0

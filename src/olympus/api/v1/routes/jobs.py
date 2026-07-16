"""Global durable job inspection and recovery controls."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from olympus.api.dependencies import WorkflowServiceDep
from olympus.api.v1.schemas.jobs import (
    DurableJobEventsResponse,
    DurableJobListResponse,
    DurableJobLogsResponse,
    DurableJobResponse,
)
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/jobs", tags=["jobs"])
project_router = APIRouter(prefix="/projects/{project_id}/jobs", tags=["jobs"])


@router.get("", response_model=DurableJobListResponse)
async def list_jobs(
    workflow: WorkflowServiceDep,
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> DurableJobListResponse:
    jobs = await workflow.list_jobs(project_id=project_id, status=status_filter)
    return DurableJobListResponse(jobs=[DurableJobResponse(**job) for job in jobs])


@project_router.get("", response_model=DurableJobListResponse)
async def list_project_jobs(
    project_id: str,
    workflow: WorkflowServiceDep,
) -> DurableJobListResponse:
    jobs = await workflow.list_jobs(project_id=project_id)
    return DurableJobListResponse(jobs=[DurableJobResponse(**job) for job in jobs])


@router.get("/{job_id}", response_model=DurableJobResponse)
async def get_job(job_id: str, workflow: WorkflowServiceDep) -> DurableJobResponse:
    job = await workflow.get_durable_job(job_id)
    if job is None:
        raise NotFoundError("Durable job not found.", details={"job_id": job_id})
    return DurableJobResponse(**job)


@router.post(
    "/{job_id}/cancel",
    response_model=DurableJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_job(job_id: str, workflow: WorkflowServiceDep) -> DurableJobResponse:
    return DurableJobResponse(**await workflow.cancel_by_job_id(job_id))


@router.post(
    "/{job_id}/retry",
    response_model=DurableJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_job(job_id: str, workflow: WorkflowServiceDep) -> DurableJobResponse:
    return DurableJobResponse(**await workflow.retry_by_job_id(job_id))


@router.post(
    "/{job_id}/resume",
    response_model=DurableJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_job(job_id: str, workflow: WorkflowServiceDep) -> DurableJobResponse:
    return DurableJobResponse(**await workflow.resume_by_job_id(job_id))


@router.get("/{job_id}/events", response_model=DurableJobEventsResponse)
async def get_job_events(
    job_id: str,
    workflow: WorkflowServiceDep,
) -> DurableJobEventsResponse:
    events = await workflow.durable_events(job_id)
    if events is None:
        raise NotFoundError("Durable job not found.", details={"job_id": job_id})
    return DurableJobEventsResponse(job_id=job_id, events=events)


@router.get("/{job_id}/logs", response_model=DurableJobLogsResponse)
async def get_job_logs(
    job_id: str,
    workflow: WorkflowServiceDep,
) -> DurableJobLogsResponse:
    logs = await workflow.durable_logs(job_id)
    if logs is None:
        raise NotFoundError("Durable job not found.", details={"job_id": job_id})
    return DurableJobLogsResponse(job_id=job_id, logs=logs)

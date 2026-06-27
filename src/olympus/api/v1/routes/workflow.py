"""Workflow Orchestration endpoints.

The operator surface for Olympus's central nervous system: start / pause /
resume / cancel a project's workflow, inspect its live status and execution
history, drill into any job's status and logs, retry a job or the whole
workflow, and observe the worker pool and scheduler. Everything reflects real
orchestration state - job statuses are genuine engine outcomes and progress is
derived from completed work, never fabricated.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from olympus.api.dependencies import ProjectServiceDep, WorkflowServiceDep
from olympus.api.v1.schemas.workflow import (
    HistoryResponse,
    JobLogsResponse,
    JobResponse,
    SchedulerResponse,
    WorkersResponse,
    WorkflowResponse,
)
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/workflow", tags=["workflow"])
ops_router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.get("", response_model=WorkflowResponse)
async def get_workflow(
    project_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> WorkflowResponse:
    """Return the project's current workflow state (404 if not started)."""

    await projects.get(project_id)
    wf = await workflow.get(project_id)
    if wf is None:
        raise NotFoundError(
            "No workflow exists for this project yet.", details={"id": project_id}
        )
    return WorkflowResponse.from_entity(wf)


@router.post("/start", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_workflow(
    project_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> WorkflowResponse:
    """Start (or resume) the full project workflow across every engine."""

    project = await projects.get(project_id)
    wf = await workflow.start(project)
    return WorkflowResponse.from_entity(wf)


@router.post("/pause", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def pause_workflow(
    project_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> WorkflowResponse:
    """Pause the workflow (running jobs finish; no new jobs are claimed)."""

    await projects.get(project_id)
    return WorkflowResponse.from_entity(await workflow.pause(project_id))


@router.post("/resume", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def resume_workflow(
    project_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> WorkflowResponse:
    """Resume a paused workflow."""

    await projects.get(project_id)
    return WorkflowResponse.from_entity(await workflow.resume(project_id))


@router.post("/cancel", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def cancel_workflow(
    project_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> WorkflowResponse:
    """Cancel the workflow (non-terminal jobs are cancelled and stay cancelled)."""

    await projects.get(project_id)
    return WorkflowResponse.from_entity(await workflow.cancel(project_id))


@router.post("/retry", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_workflow(
    project_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> WorkflowResponse:
    """Retry every failed/dead/blocked job in the workflow."""

    await projects.get(project_id)
    return WorkflowResponse.from_entity(await workflow.retry_workflow(project_id))


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    project_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> HistoryResponse:
    """Return the workflow's execution history (event stream)."""

    await projects.get(project_id)
    history = await workflow.history(project_id)
    if history is None:
        raise NotFoundError("No workflow for this project yet.", details={"id": project_id})
    return HistoryResponse.from_events(project_id, history)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    project_id: str, job_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> JobResponse:
    """Return a single job's full state."""

    await projects.get(project_id)
    job = await workflow.get_job(project_id, job_id)
    if job is None:
        raise NotFoundError(
            "Job not found.", details={"id": project_id, "job_id": job_id}
        )
    return JobResponse.from_entity(project_id, job)


@router.get("/jobs/{job_id}/logs", response_model=JobLogsResponse)
async def get_job_logs(
    project_id: str, job_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> JobLogsResponse:
    """Return a single job's structured logs."""

    await projects.get(project_id)
    logs = await workflow.job_logs(project_id, job_id)
    if logs is None:
        raise NotFoundError(
            "Job not found.", details={"id": project_id, "job_id": job_id}
        )
    return JobLogsResponse(project_id=project_id, job_id=job_id, logs=logs)


@router.post("/jobs/{job_id}/retry", response_model=WorkflowResponse)
async def retry_job(
    project_id: str, job_id: str, projects: ProjectServiceDep, workflow: WorkflowServiceDep
) -> WorkflowResponse:
    """Retry a single failed/dead/blocked job."""

    await projects.get(project_id)
    return WorkflowResponse.from_entity(await workflow.retry_job(project_id, job_id))


@ops_router.get("/workers", response_model=WorkersResponse)
async def get_workers(workflow: WorkflowServiceDep) -> WorkersResponse:
    """Return the worker pool's registration and health."""

    return WorkersResponse(workers=await workflow.workers())


@ops_router.get("/scheduler", response_model=SchedulerResponse)
async def get_scheduler(workflow: WorkflowServiceDep) -> SchedulerResponse:
    """Return a snapshot of the queue/scheduler state."""

    return SchedulerResponse(**await workflow.scheduler_status())

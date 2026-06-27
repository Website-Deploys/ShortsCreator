"""Schemas for the workflow (Orchestration) API.

The workflow's state is a rich graph (jobs, history, execution DAG); these
responses expose it as-is. Every value is real: job statuses reflect genuine
engine outcomes, progress is derived from completed jobs, and the
``estimated_remaining_seconds`` is clearly a nominal estimate (never presented as
measured). No field fabricates work.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from olympus.domain.entities.workflow import Job, Workflow, WorkflowEvent


class WorkflowResponse(BaseModel):
    """A project's complete workflow state (status + jobs + history + graph)."""

    workflow_id: str
    project_id: str
    status: str
    created_at: str
    updated_at: str
    current_stage: str | None
    overall_progress: float
    completed_stages: list[str]
    failed_stages: list[str]
    pending_stages: list[str]
    estimated_remaining_seconds: float
    retry_count: int
    total_retries: int
    jobs: list[dict[str, Any]]
    history: list[dict[str, Any]]
    execution_graph: dict[str, Any]

    @classmethod
    def from_entity(cls, workflow: Workflow) -> WorkflowResponse:
        return cls(**workflow.to_dict())


class JobResponse(BaseModel):
    """A single job's full state."""

    project_id: str
    job: dict[str, Any]

    @classmethod
    def from_entity(cls, project_id: str, job: Job) -> JobResponse:
        return cls(project_id=project_id, job=job.to_dict())


class JobLogsResponse(BaseModel):
    """A single job's structured logs."""

    project_id: str
    job_id: str
    logs: list[dict[str, Any]]


class HistoryResponse(BaseModel):
    """A workflow's execution history (event stream)."""

    project_id: str
    history: list[dict[str, Any]]

    @classmethod
    def from_events(cls, project_id: str, events: list[WorkflowEvent]) -> HistoryResponse:
        return cls(project_id=project_id, history=[e.to_dict() for e in events])


class WorkersResponse(BaseModel):
    """The worker pool's registration and health."""

    workers: list[dict[str, Any]]


class SchedulerResponse(BaseModel):
    """A snapshot of the queue/scheduler state."""

    queue: dict[str, Any]
    pool_running: bool
    worker_count: int

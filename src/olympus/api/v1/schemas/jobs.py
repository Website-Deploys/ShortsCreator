"""API schemas for the additive durable-job projection."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DurableJobResponse(BaseModel):
    schema_version: str
    job_id: str
    project_id: str
    job_type: str
    parent_job_id: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    status: str
    priority: int
    attempt: int
    max_attempts: int
    requested_by: str
    source: str
    idempotency_key: str | None = None
    stages: list[dict[str, Any]]
    current_stage: str | None = None
    progress_percent: float
    heartbeat_at: str | None = None
    worker_id: str | None = None
    resume: dict[str, Any]
    cancellation: dict[str, Any]
    result: dict[str, Any]
    diagnostics: dict[str, Any]


class DurableJobListResponse(BaseModel):
    jobs: list[DurableJobResponse]


class DurableJobEventsResponse(BaseModel):
    job_id: str
    events: list[dict[str, Any]]


class DurableJobLogsResponse(BaseModel):
    job_id: str
    logs: list[dict[str, Any]]

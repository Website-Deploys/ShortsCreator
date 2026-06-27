"""Schemas for the Production Monitoring & Analytics API.

The monitoring views are rich, measured aggregates; these responses expose the
entities' ``to_dict`` payloads. Nested structures are loosely typed (they pass
through intact) and any unmeasurable value is ``null`` (UNKNOWN), never
fabricated.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    overall: str
    engines: list[dict[str, Any]]
    system: dict[str, Any]
    queue: dict[str, Any]


class EnginesResponse(BaseModel):
    engines: list[dict[str, Any]]


class WorkflowAnalyticsResponse(BaseModel):
    total_workflows: int
    completed: int
    failed: int
    running: int
    avg_duration_ms: float | None
    avg_idle_ms: float | None
    critical_path: list[dict[str, Any]]
    engine_bottlenecks: list[dict[str, Any]]
    slowest_projects: list[dict[str, Any]]
    fastest_projects: list[dict[str, Any]]


class QueueResponse(BaseModel):
    queued: int
    running: int
    delayed: int
    completed: int
    failed: int
    dead: int
    blocked: int
    cancelled: int
    active_workflows: int
    worker_count: int
    busy_workers: int
    idle_workers: int
    offline_workers: int
    pool_running: bool
    worker_utilization: float | None
    stuck_jobs: list[dict[str, Any]]
    dead_jobs: list[dict[str, Any]]
    avg_queue_latency_ms: float | None
    workers: list[dict[str, Any]]


class SystemResponse(BaseModel):
    cpu_count: int | None
    load_avg_1m: float | None
    load_avg_5m: float | None
    load_avg_15m: float | None
    process_cpu_seconds: float | None
    process_max_rss_bytes: int | None
    system_memory_total_bytes: int | None
    system_memory_available_bytes: int | None
    disk_total_bytes: int | None
    disk_used_bytes: int | None
    disk_free_bytes: int | None
    disk_used_pct: float | None
    source: str
    unavailable: list[str]


class StorageAnalyticsResponse(BaseModel):
    total_bytes: int
    namespaces: dict[str, int]
    trend: list[dict[str, Any]]


class FailuresResponse(BaseModel):
    total_failures: int
    by_engine: dict[str, int]
    by_exception: dict[str, int]
    by_project: dict[str, int]
    recent: list[dict[str, Any]]


class UsageResponse(BaseModel):
    projects: int
    videos_processed: int
    minutes_analyzed: float
    clips: int
    renders: int
    exports: int
    workflows_run: int
    total_stage_executions: int
    busiest_engine: str | None


class CostResponse(BaseModel):
    lines: list[dict[str, Any]]
    total_usd: float
    disclaimer: str


class AuditResponse(BaseModel):
    count: int
    entries: list[dict[str, Any]]


class AlertsResponse(BaseModel):
    count: int
    alerts: list[dict[str, Any]]


class AdminResponse(BaseModel):
    overall_health: str
    engine_health: list[dict[str, Any]]
    system: dict[str, Any] | None
    queue: dict[str, Any] | None
    usage: dict[str, Any] | None
    storage_total_bytes: int
    alerts: list[dict[str, Any]]
    recent_failures: list[dict[str, Any]]
    recent_audit: list[dict[str, Any]]

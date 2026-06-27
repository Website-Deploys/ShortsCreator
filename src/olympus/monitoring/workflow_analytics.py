"""Workflow analytics, computed from real persisted workflows (pure)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from olympus.domain.entities.monitoring import WorkflowAnalytics
from olympus.domain.entities.workflow import Workflow, WorkflowStatus


def _duration_ms(workflow: Workflow) -> float | None:
    if workflow.status in (WorkflowStatus.RUNNING, WorkflowStatus.PENDING, WorkflowStatus.PAUSED):
        return None
    return (workflow.updated_at - workflow.created_at).total_seconds() * 1000.0


def build_workflow_analytics(workflows: list[Workflow], *, top_n: int = 5) -> WorkflowAnalytics:
    """Aggregate measured analytics across all project workflows."""

    analytics = WorkflowAnalytics(total_workflows=len(workflows))
    durations: list[float] = []
    idles: list[float] = []
    stage_total_ms: dict[str, float] = defaultdict(float)
    stage_count: dict[str, int] = defaultdict(int)
    project_durations: list[dict[str, Any]] = []

    for wf in workflows:
        if wf.status is WorkflowStatus.COMPLETED:
            analytics.completed += 1
        elif wf.status is WorkflowStatus.FAILED:
            analytics.failed += 1
        elif wf.status is WorkflowStatus.RUNNING:
            analytics.running += 1

        duration = _duration_ms(wf)
        executed = 0.0
        for job in wf.jobs:
            if job.duration_ms is not None:
                stage_total_ms[job.stage] += job.duration_ms
                stage_count[job.stage] += 1
                executed += job.duration_ms
        if duration is not None:
            durations.append(duration)
            project_durations.append(
                {
                    "project_id": wf.project_id,
                    "duration_ms": round(duration, 2),
                    "status": wf.status.value,
                }
            )
            idle = max(0.0, duration - executed)
            idles.append(idle)

    if durations:
        analytics.avg_duration_ms = round(sum(durations) / len(durations), 2)
    if idles:
        analytics.avg_idle_ms = round(sum(idles) / len(idles), 2)

    # Critical path = stages by total measured time (the work that dominates).
    crit = sorted(stage_total_ms.items(), key=lambda kv: kv[1], reverse=True)
    analytics.critical_path = [
        {
            "stage": stage,
            "total_ms": round(total, 2),
            "executions": stage_count[stage],
            "avg_ms": round(total / stage_count[stage], 2) if stage_count[stage] else None,
        }
        for stage, total in crit[:top_n]
    ]
    # Engine bottlenecks = stages by average measured time.
    bottlenecks = sorted(
        (
            (stage, total / stage_count[stage])
            for stage, total in stage_total_ms.items()
            if stage_count[stage]
        ),
        key=lambda kv: kv[1],
        reverse=True,
    )
    analytics.engine_bottlenecks = [
        {"stage": stage, "avg_ms": round(avg, 2)} for stage, avg in bottlenecks[:top_n]
    ]

    project_durations.sort(key=lambda p: p["duration_ms"], reverse=True)
    analytics.slowest_projects = project_durations[:top_n]
    analytics.fastest_projects = (
        list(reversed(project_durations[-top_n:])) if project_durations else []
    )
    return analytics

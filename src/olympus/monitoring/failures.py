"""Failure analytics, aggregated from real FAILED stages and jobs (pure).

Never fabricates a cause: it reports the error string the engine actually
recorded (and the exception type parsed from its prefix when present). Stages
that are ``UNAVAILABLE`` are *not* failures - they are an honest "not run", so
they are excluded here.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from olympus.domain.entities.monitoring import FailureRecord, FailureSummary


def _exception_type(error: str | None) -> str:
    if not error:
        return "unknown"
    head = error.split(":", 1)[0].strip()
    return head[:60] if head else "unknown"


def build_failure_summary(
    *,
    engine_analyses: list[tuple[str, str, Any]],
    workflow_jobs: list[Any],
    recent_limit: int = 25,
) -> FailureSummary:
    """Aggregate failures from engine stages + workflow jobs.

    Args:
        engine_analyses: tuples of (engine, project_id, analysis-like) to scan
            for ``FAILED`` stages.
        workflow_jobs: workflow Job objects to scan for ``FAILED``/``DEAD``.
    """

    summary = FailureSummary()
    by_engine: dict[str, int] = defaultdict(int)
    by_exception: dict[str, int] = defaultdict(int)
    by_project: dict[str, int] = defaultdict(int)
    records: list[FailureRecord] = []

    for engine, project_id, analysis in engine_analyses:
        for stage in getattr(analysis, "stages", []):
            if getattr(stage.status, "value", str(stage.status)) != "failed":
                continue
            error = getattr(stage, "error", None) or getattr(stage, "reason", None)
            records.append(
                FailureRecord(
                    engine=engine,
                    stage=stage.stage,
                    project_id=project_id,
                    ts=stage.completed_at,
                    error=error,
                    attempts=int(stage.attempts),
                )
            )
            by_engine[engine] += 1
            by_exception[_exception_type(error)] += 1
            by_project[project_id] += 1

    for job in workflow_jobs:
        status = getattr(job.status, "value", str(job.status))
        if status not in ("failed", "dead"):
            continue
        records.append(
            FailureRecord(
                engine=job.engine,
                stage=job.stage,
                project_id=job.project_id,
                ts=job.finished_at,
                error=job.error,
                attempts=int(job.attempts),
            )
        )
        by_engine[job.engine] += 1
        by_exception[_exception_type(job.error)] += 1
        by_project[job.project_id] += 1

    records.sort(key=lambda r: (r.ts is not None, r.ts), reverse=True)
    summary.total_failures = len(records)
    summary.by_engine = dict(by_engine)
    summary.by_exception = dict(by_exception)
    summary.by_project = dict(by_project)
    summary.recent = records[:recent_limit]
    return summary

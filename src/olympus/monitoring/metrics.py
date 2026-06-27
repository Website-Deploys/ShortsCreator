"""Engine performance metrics, computed from real persisted execution state.

Every engine persists a uniform stage record (``status``, ``attempts``,
``started_at``, ``completed_at``, ``data``). These pure functions aggregate those
records (plus the workflow's per-engine jobs, when present) into measured engine
metrics. Nothing is fabricated: a value that cannot be computed from the
persisted state is ``None`` (UNKNOWN).
"""

from __future__ import annotations

from typing import Any, Protocol

from olympus.domain.entities.monitoring import EngineMetrics

_TERMINAL_OK = "completed"


class _StageLike(Protocol):
    status: Any
    attempts: int
    started_at: Any
    completed_at: Any
    data: dict[str, Any]


class _AnalysisLike(Protocol):
    stages: list[_StageLike]


def _status(value: Any) -> str:
    return getattr(value, "value", str(value))


def stage_duration_ms(stage: _StageLike) -> float | None:
    """Measured wall-clock duration of one stage, or ``None`` if not timed."""

    if stage.started_at is None or stage.completed_at is None:
        return None
    return (stage.completed_at - stage.started_at).total_seconds() * 1000.0


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile of measured values, or ``None`` if empty."""

    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round((pct / 100.0) * len(ordered) + 0.5) - 1))
    return round(ordered[k], 2)


def collect_confidences(
    value: Any, *, depth: int = 0, _out: list[float] | None = None
) -> list[float]:
    """Collect every numeric ``confidence`` (0-1) the engines recorded in ``data``.

    A depth-limited walk over the stage's data: these are *measured* confidence
    values the engines wrote, not invented ones. Returns an empty list when none
    were recorded (the engine simply did not report confidence).
    """

    out = _out if _out is not None else []
    if depth > 4:
        return out
    if isinstance(value, dict):
        for key, sub in value.items():
            if key == "confidence" and isinstance(sub, int | float) and 0.0 <= sub <= 1.0:
                out.append(float(sub))
            else:
                collect_confidences(sub, depth=depth + 1, _out=out)
    elif isinstance(value, list):
        for item in value:
            collect_confidences(item, depth=depth + 1, _out=out)
    return out


def build_engine_metrics(
    engine: str,
    analyses: list[_AnalysisLike],
    *,
    jobs: list[Any] | None = None,
    concurrent: int = 0,
) -> EngineMetrics:
    """Aggregate measured metrics for one engine across all its analyses."""

    metrics = EngineMetrics(engine=engine, runs=len(analyses), concurrent_executions=concurrent)
    durations: list[float] = []
    confidences: list[float] = []
    earliest: Any = None
    latest: Any = None

    for analysis in analyses:
        for stage in analysis.stages:
            status = _status(stage.status)
            if status == "pending":
                continue
            metrics.stage_executions += 1
            if status == "completed":
                metrics.completed += 1
            elif status == "failed":
                metrics.failed += 1
            elif status == "unavailable":
                metrics.unavailable += 1
            elif status == "cancelled":
                metrics.cancelled += 1
            metrics.retries += max(0, int(stage.attempts) - 1)
            dur = stage_duration_ms(stage)
            if dur is not None:
                durations.append(dur)
                metrics.total_execution_ms += dur
            if stage.started_at is not None:
                earliest = stage.started_at if earliest is None else min(earliest, stage.started_at)
            if stage.completed_at is not None:
                latest = stage.completed_at if latest is None else max(latest, stage.completed_at)
            confidences.extend(collect_confidences(stage.data))

    if durations:
        metrics.avg_execution_ms = round(sum(durations) / len(durations), 2)
        metrics.p95_execution_ms = percentile(durations, 95)
    if confidences:
        metrics.avg_confidence = round(sum(confidences) / len(confidences), 4)
    if earliest is not None and latest is not None and latest > earliest:
        hours = (latest - earliest).total_seconds() / 3600.0
        if hours > 0:
            metrics.throughput_per_hour = round(metrics.completed / hours, 3)

    # Queue wait (time from job creation to start), measured from workflow jobs.
    if jobs:
        waits = [
            (j.started_at - j.created_at).total_seconds() * 1000.0
            for j in jobs
            if getattr(j, "started_at", None) is not None
            and getattr(j, "created_at", None) is not None
        ]
        if waits:
            avg_wait = round(sum(waits) / len(waits), 2)
            metrics.avg_wait_ms = avg_wait
            metrics.avg_queue_delay_ms = avg_wait  # same measured queue wait

    return metrics

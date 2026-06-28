"""Alert generation from measured state (informational only; no notifications).

Each alert is derived from a real measurement crossing a configurable threshold,
and carries the evidence it was derived from. Alerts never fire on fabricated or
unavailable data - a metric that is UNKNOWN simply produces no alert.
"""

from __future__ import annotations

from typing import Any

from olympus.domain.entities.monitoring import (
    Alert,
    AlertSeverity,
    EngineMetrics,
    FailureSummary,
    QueueSnapshot,
    StorageAnalytics,
    SystemMetrics,
)
from olympus.utils import new_id

# Configurable thresholds.
STORAGE_WARN_BYTES = 5 * 1024**3  # 5 GB
DISK_WARN_PCT = 0.85
DISK_CRITICAL_PCT = 0.95
REPEATED_FAILURE_THRESHOLD = 3
HIGH_RETRY_RATE = 0.5
LOW_CONFIDENCE = 0.3


def _alert(severity: AlertSeverity, category: str, message: str, evidence: dict[str, Any]) -> Alert:
    return Alert(
        id=new_id("alert"), severity=severity, category=category, message=message, evidence=evidence
    )


def generate_alerts(
    *,
    engine_metrics: list[EngineMetrics],
    queue: QueueSnapshot,
    storage: StorageAnalytics,
    system: SystemMetrics,
    failures: FailureSummary,
) -> list[Alert]:
    """Generate informational alerts from measured thresholds."""

    alerts: list[Alert] = []

    # Failed workflows / dead jobs.
    if queue.dead > 0:
        alerts.append(
            _alert(
                AlertSeverity.WARNING,
                "dead_jobs",
                f"{queue.dead} job(s) are dead (retries exhausted).",
                {"dead": queue.dead},
            )
        )
    if queue.failed > 0:
        alerts.append(
            _alert(
                AlertSeverity.INFO,
                "failed_jobs",
                f"{queue.failed} job(s) are currently failed.",
                {"failed": queue.failed},
            )
        )

    # Stuck workers / jobs.
    if queue.stuck_jobs:
        alerts.append(
            _alert(
                AlertSeverity.WARNING,
                "stuck_jobs",
                f"{len(queue.stuck_jobs)} job(s) appear stuck (running with a stale worker).",
                {"count": len(queue.stuck_jobs)},
            )
        )

    # Large storage usage.
    if storage.total_bytes >= STORAGE_WARN_BYTES:
        alerts.append(
            _alert(
                AlertSeverity.WARNING,
                "storage",
                f"Storage usage is {round(storage.total_bytes / 1024**3, 2)} GB.",
                {"total_bytes": storage.total_bytes},
            )
        )

    # Disk nearly full.
    used_pct = system.disk_used_pct
    if used_pct is not None:
        if used_pct >= DISK_CRITICAL_PCT:
            alerts.append(
                _alert(
                    AlertSeverity.CRITICAL,
                    "disk",
                    f"Disk is {round(used_pct * 100)}% full.",
                    {"disk_used_pct": used_pct},
                )
            )
        elif used_pct >= DISK_WARN_PCT:
            alerts.append(
                _alert(
                    AlertSeverity.WARNING,
                    "disk",
                    f"Disk is {round(used_pct * 100)}% full.",
                    {"disk_used_pct": used_pct},
                )
            )

    # Repeated failures by engine.
    for engine, count in failures.by_engine.items():
        if count >= REPEATED_FAILURE_THRESHOLD:
            alerts.append(
                _alert(
                    AlertSeverity.WARNING,
                    "repeated_failures",
                    f"Engine '{engine}' has {count} failures.",
                    {"engine": engine, "count": count},
                )
            )

    # High retry rate / low confidence per engine (only when measurable).
    for m in engine_metrics:
        if m.stage_executions > 0 and m.retries / m.stage_executions >= HIGH_RETRY_RATE:
            alerts.append(
                _alert(
                    AlertSeverity.WARNING,
                    "retry_rate",
                    f"Engine '{m.engine}' has a high retry rate.",
                    {"engine": m.engine, "retries": m.retries, "executions": m.stage_executions},
                )
            )
        if m.avg_confidence is not None and m.avg_confidence < LOW_CONFIDENCE:
            alerts.append(
                _alert(
                    AlertSeverity.INFO,
                    "low_confidence",
                    f"Engine '{m.engine}' average confidence is low ({m.avg_confidence}).",
                    {"engine": m.engine, "avg_confidence": m.avg_confidence},
                )
            )

    return alerts

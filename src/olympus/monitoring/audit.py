"""Audit log derivation from real persisted execution state (pure).

The audit feed is reconstructed from immutable records the platform already
persisted - workflow execution histories, the library activity log, and the
render/optimization execution records. This is honest by construction: it
reports actions that genuinely occurred. The monitoring service merges these
derived entries with any explicitly-recorded audit entries.
"""

from __future__ import annotations

from typing import Any

from olympus.domain.entities.monitoring import AuditAction, AuditEntry

_WORKFLOW_EVENT_MAP = {
    "workflow_started": AuditAction.WORKFLOW_STARTED,
    "workflow_completed": AuditAction.WORKFLOW_COMPLETED,
    "workflow_failed": AuditAction.WORKFLOW_FAILED,
    "workflow_cancelled": AuditAction.WORKFLOW_CANCELLED,
    "stage_finished": AuditAction.STAGE_FINISHED,
    "job_retrying": AuditAction.JOB_RETRIED,
}

_ACTIVITY_MAP = {
    "project_archived": AuditAction.PROJECT_ARCHIVED,
    "project_restored": AuditAction.PROJECT_RESTORED,
    "cleanup_performed": AuditAction.CLEANUP,
    "version_captured": AuditAction.VERSION_CAPTURED,
}


def derive_audit_entries(
    *,
    workflows: list[Any],
    activity_events: list[Any],
    render_runs: list[tuple[str, Any]],
    optimizations: list[tuple[str, Any]],
) -> list[AuditEntry]:
    """Reconstruct audit entries from real persisted state."""

    entries: list[AuditEntry] = []

    for wf in workflows:
        for ev in getattr(wf, "history", []):
            action = _WORKFLOW_EVENT_MAP.get(getattr(ev.type, "value", str(ev.type)))
            if action is None:
                continue
            entries.append(
                AuditEntry(
                    id=f"{wf.project_id}:{action.value}:{ev.ts.isoformat()}",
                    ts=ev.ts,
                    action=action,
                    message=ev.message,
                    project_id=wf.project_id,
                    source="derived",
                    detail={"stage": ev.stage} if ev.stage else {},
                )
            )

    for ev in activity_events:
        action = _ACTIVITY_MAP.get(getattr(ev.type, "value", str(ev.type)))
        if action is None:
            continue
        entries.append(
            AuditEntry(
                id=ev.id,
                ts=ev.ts,
                action=action,
                message=ev.message,
                project_id=ev.project_id,
                source="derived",
                detail=ev.detail,
            )
        )

    for project_id, run in render_runs:
        if run is None:
            continue
        entries.append(
            AuditEntry(
                id=f"{project_id}:render:{run.updated_at.isoformat()}",
                ts=run.updated_at,
                action=AuditAction.RENDER_EXECUTION,
                message=f"Render run {run.status.value}",
                project_id=project_id,
                source="derived",
                detail={"status": run.status.value},
            )
        )

    for project_id, opt in optimizations:
        if opt is None:
            continue
        entries.append(
            AuditEntry(
                id=f"{project_id}:optimization:{opt.updated_at.isoformat()}",
                ts=opt.updated_at,
                action=AuditAction.OPTIMIZATION_EXECUTION,
                message=f"Optimization {opt.status.value}",
                project_id=project_id,
                source="derived",
                detail={"status": opt.status.value},
            )
        )

    return entries

"""Global dashboard statistics aggregation (pure)."""

from __future__ import annotations

from olympus.domain.entities.library import ClipRecord, DashboardStats, ExportRecord


def compute_dashboard(
    *,
    total_projects: int,
    videos_processed: int,
    minutes_analyzed: float,
    clips: list[ClipRecord],
    exports: list[ExportRecord],
    rendered_clip_count: int,
    storage_bytes: int,
    archived_projects: int,
) -> DashboardStats:
    """Assemble global statistics from already-aggregated records (honest)."""

    scores = [c.viral_score for c in clips if c.viral_score is not None]
    average = round(sum(scores) / len(scores), 3) if scores else None
    available_exports = [e for e in exports if e.download_status == "available"]
    return DashboardStats(
        total_projects=total_projects,
        videos_processed=videos_processed,
        minutes_analyzed=minutes_analyzed,
        clips_generated=len(clips),
        renders_completed=rendered_clip_count,
        exports=len(available_exports),
        average_viral_score=average,
        storage_bytes=storage_bytes,
        archived_projects=archived_projects,
    )

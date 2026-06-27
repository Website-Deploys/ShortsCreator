"""Global search across projects, clips, videos, and exports.

A pure, deterministic substring/keyword matcher over the records the library has
already aggregated. It searches names, titles, platforms, resolutions, tags, and
ids - real metadata only. Ranking is simple and explainable (exact-ish matches
and name matches rank above incidental metadata matches).
"""

from __future__ import annotations

from olympus.domain.entities.library import (
    AssetKind,
    AssetRecord,
    ClipRecord,
    ExportRecord,
    SearchHit,
)
from olympus.domain.entities.project import Project


def _matches(query: str, *fields: object) -> int:
    """Return a match score for ``query`` against the given fields (0 = no match)."""

    q = query.strip().lower()
    if not q:
        return 0
    score = 0
    for field in fields:
        if field is None:
            continue
        text = str(field).lower()
        if not text:
            continue
        if text == q:
            score += 100
        elif text.startswith(q):
            score += 50
        elif q in text:
            score += 20
    return score


def search(
    query: str,
    *,
    projects: list[Project],
    clips: list[ClipRecord],
    exports: list[ExportRecord],
    assets: list[AssetRecord],
    limit: int = 50,
) -> list[SearchHit]:
    """Return ranked search hits across every record type."""

    scored: list[tuple[int, SearchHit]] = []

    for project in projects:
        s = _matches(query, project.name, project.source_filename, project.id, project.status.value)
        if s:
            scored.append(
                (
                    s,
                    SearchHit(
                        kind="project",
                        id=project.id,
                        project_id=project.id,
                        title=project.name,
                        subtitle=project.source_filename,
                        detail={"status": project.status.value},
                    ),
                )
            )

    for clip in clips:
        s = _matches(query, clip.title, clip.clip_id, clip.platform, *clip.tags)
        if s:
            scored.append(
                (
                    s,
                    SearchHit(
                        kind="clip",
                        id=clip.clip_id,
                        project_id=clip.project_id,
                        title=clip.title,
                        subtitle=f"{clip.project_name} · {clip.status}",
                        detail={"viral_score": clip.viral_score, "platform": clip.platform},
                    ),
                )
            )

    for export in exports:
        s = _matches(query, export.clip_id, export.platform, export.resolution, export.codec)
        if s:
            scored.append(
                (
                    s,
                    SearchHit(
                        kind="export",
                        id=export.id,
                        project_id=export.project_id,
                        title=f"{export.clip_id} export",
                        subtitle=f"{export.project_name} · {export.resolution or '—'}",
                        detail={
                            "platform": export.platform,
                            "download_status": export.download_status,
                        },
                    ),
                )
            )

    for asset in assets:
        if asset.kind is not AssetKind.SOURCE_VIDEO:
            continue
        s = _matches(query, asset.name, *asset.tags)
        if s:
            scored.append(
                (
                    s,
                    SearchHit(
                        kind="video",
                        id=asset.id,
                        project_id=asset.project_id,
                        title=asset.name,
                        subtitle=asset.project_name,
                        detail={"size_bytes": asset.size_bytes},
                    ),
                )
            )

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [hit for _, hit in scored[:limit]]

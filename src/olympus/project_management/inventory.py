"""Inventory builders - turn real engine outputs into library records.

Pure, deterministic functions that read the *already-loaded* outputs of the
engines (the editing timelines, the render manifest, the optimization packages,
the render run) and produce the library's asset / clip / export records. They
never modify any engine data and never invent values: anything an engine did not
actually produce is left ``None`` (UNKNOWN).

The functions take a synchronous ``size_of`` callable (key -> bytes | None) so
they stay pure and unit-testable; the service supplies it from the storage port.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from olympus.domain.entities.analysis import Analysis
from olympus.domain.entities.editing import EditingAnalysis
from olympus.domain.entities.library import (
    AssetKind,
    AssetRecord,
    ClipRecord,
    ExportRecord,
    ProjectLibraryMeta,
)
from olympus.domain.entities.optimization import OptimizationAnalysis
from olympus.domain.entities.project import Project
from olympus.domain.entities.render_pipeline import RenderRun
from olympus.domain.entities.rendering import RenderManifest

SizeOf = Callable[[str], "int | None"]


# --------------------------------------------------------------------------- #
# Extractors (defensive reads of engine output shapes)
# --------------------------------------------------------------------------- #
def timelines(editing: EditingAnalysis | None) -> list[dict[str, Any]]:
    if editing is None:
        return []
    stage = editing.stage("timeline_validation")
    if stage is None or stage.status.value != "completed":
        return []
    tl = stage.data.get("timelines")
    return tl if isinstance(tl, list) else []


def optimization_platform(optimization: OptimizationAnalysis | None) -> str | None:
    if optimization is None:
        return None
    stage = optimization.stage("platform_optimization")
    if stage is None or stage.status.value != "completed":
        return None
    order = stage.data.get("platform_order")
    return order[0] if isinstance(order, list) and order else None


def render_time_ms(render_run: RenderRun | None) -> float | None:
    if render_run is None:
        return None
    stage = render_run.stage("full_resolution_render")
    if stage is None or stage.started_at is None or stage.completed_at is None:
        return None
    return (stage.completed_at - stage.started_at).total_seconds() * 1000.0


def _meta(timeline: dict[str, Any]) -> dict[str, Any]:
    m = timeline.get("metadata")
    return m if isinstance(m, dict) else {}


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


# --------------------------------------------------------------------------- #
# Clip Library
# --------------------------------------------------------------------------- #
def build_clips(
    project: Project,
    *,
    editing: EditingAnalysis | None,
    render_manifest: RenderManifest | None,
    optimization: OptimizationAnalysis | None,
    meta: ProjectLibraryMeta,
) -> list[ClipRecord]:
    """Every clip Olympus produced for a project, with its real per-clip facts."""

    platform = optimization_platform(optimization)
    rendered = {r.clip_id: r for r in (render_manifest.renders if render_manifest else [])}
    clips: list[ClipRecord] = []
    for tl in timelines(editing):
        clip_id = str(tl.get("clip_id"))
        m = _meta(tl)
        render = rendered.get(clip_id)
        asset_meta = meta.asset_meta(clip_id)
        title = str(m.get("title") or clip_id)
        clips.append(
            ClipRecord(
                clip_id=clip_id,
                project_id=project.id,
                project_name=project.name,
                title=title,
                duration=_num(tl.get("duration")),
                viral_score=_num(m.get("quality_score")),
                platform=platform,
                status="rendered" if render is not None else "planned",
                thumbnail_key=project.thumbnail_key,
                render_version=render.timeline_version if render else None,
                created_at=editing.updated_at if editing else project.created_at,
                tags=list(asset_meta.get("tags", [])),
                favorite=bool(asset_meta.get("favorite", False)),
            )
        )
    return clips


# --------------------------------------------------------------------------- #
# Export Library
# --------------------------------------------------------------------------- #
def build_exports(
    project: Project,
    *,
    render_manifest: RenderManifest | None,
    render_run: RenderRun | None,
    optimization: OptimizationAnalysis | None,
    size_of: SizeOf,
) -> list[ExportRecord]:
    """Every rendered export, with the renderer's real measured media facts."""

    if render_manifest is None:
        return []
    platform = optimization_platform(optimization)
    rtime = render_time_ms(render_run)
    exports: list[ExportRecord] = []
    for r in render_manifest.renders:
        present = size_of(r.storage_key) is not None
        resolution = f"{r.width}x{r.height}" if r.width and r.height else None
        exports.append(
            ExportRecord(
                id=f"{project.id}:{r.clip_id}",
                project_id=project.id,
                project_name=project.name,
                clip_id=r.clip_id,
                platform=platform,
                resolution=resolution,
                codec=r.video_codec,
                bitrate_kbps=r.bitrate_kbps,
                file_size=r.size_bytes,
                render_time_ms=rtime,
                download_status="available" if present else "unavailable",
                storage_key=r.storage_key,
                checksum=r.checksum,
                created_at=render_manifest.updated_at,
            )
        )
    return exports


# --------------------------------------------------------------------------- #
# Asset Library (source video + clips + renders + exports + thumbnail)
# --------------------------------------------------------------------------- #
def build_assets(
    project: Project,
    *,
    editing: EditingAnalysis | None,
    render_manifest: RenderManifest | None,
    optimization: OptimizationAnalysis | None,
    render_run: RenderRun | None,
    meta: ProjectLibraryMeta,
    size_of: SizeOf,
) -> list[AssetRecord]:
    """Aggregate every managed asset for a project."""

    assets: list[AssetRecord] = []

    # Source video
    assets.append(
        AssetRecord(
            id=f"{project.id}:source",
            project_id=project.id,
            project_name=project.name,
            kind=AssetKind.SOURCE_VIDEO,
            name=project.source_filename,
            created_at=project.created_at,
            storage_key=project.storage_key,
            size_bytes=size_of(project.storage_key) if project.storage_key else project.size_bytes,
            content_type=project.content_type,
            tags=list(meta.tags),
            favorite=meta.favorite,
            archived=meta.archived,
            metadata={"duration_seconds": project.duration_seconds, "format": project.video_format},
        )
    )

    # Thumbnail
    if project.thumbnail_key:
        assets.append(
            AssetRecord(
                id=f"{project.id}:thumbnail",
                project_id=project.id,
                project_name=project.name,
                kind=AssetKind.THUMBNAIL,
                name="thumbnail.jpg",
                created_at=project.created_at,
                storage_key=project.thumbnail_key,
                size_bytes=size_of(project.thumbnail_key),
                content_type="image/jpeg",
                archived=meta.archived,
            )
        )

    # Clips (as assets)
    for clip in build_clips(
        project,
        editing=editing,
        render_manifest=render_manifest,
        optimization=optimization,
        meta=meta,
    ):
        assets.append(
            AssetRecord(
                id=f"{project.id}:clip:{clip.clip_id}",
                project_id=project.id,
                project_name=project.name,
                kind=AssetKind.CLIP,
                name=clip.title,
                created_at=clip.created_at,
                tags=clip.tags,
                favorite=clip.favorite,
                archived=meta.archived,
                metadata={
                    "clip_id": clip.clip_id,
                    "duration": clip.duration,
                    "viral_score": clip.viral_score,
                    "status": clip.status,
                },
            )
        )

    # Renders + exports
    if render_manifest is not None:
        for r in render_manifest.renders:
            assets.append(
                AssetRecord(
                    id=f"{project.id}:render:{r.clip_id}",
                    project_id=project.id,
                    project_name=project.name,
                    kind=AssetKind.RENDER,
                    name=f"{r.clip_id}.mp4",
                    created_at=render_manifest.updated_at,
                    storage_key=r.storage_key,
                    size_bytes=r.size_bytes,
                    content_type="video/mp4",
                    archived=meta.archived,
                    metadata={
                        "clip_id": r.clip_id,
                        "resolution": f"{r.width}x{r.height}" if r.width and r.height else None,
                        "checksum": r.checksum,
                        "render_version": r.timeline_version,
                    },
                )
            )

    for export in build_exports(
        project,
        render_manifest=render_manifest,
        render_run=render_run,
        optimization=optimization,
        size_of=size_of,
    ):
        assets.append(
            AssetRecord(
                id=f"{project.id}:export:{export.clip_id}",
                project_id=project.id,
                project_name=project.name,
                kind=AssetKind.EXPORT,
                name=f"{export.clip_id} ({export.platform or 'export'})",
                created_at=export.created_at,
                storage_key=export.storage_key,
                size_bytes=export.file_size,
                content_type="video/mp4",
                archived=meta.archived,
                metadata={
                    "clip_id": export.clip_id,
                    "platform": export.platform,
                    "resolution": export.resolution,
                    "download_status": export.download_status,
                },
            )
        )

    return assets


def has_analysis(analysis: Analysis | None) -> bool:
    """Whether a project has a (terminal) cognitive analysis on record."""

    return analysis is not None

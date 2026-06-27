"""Project Management & Asset Library endpoints.

The production management surface over everything Olympus has produced: the
dashboard, asset/clip/export libraries, global search, the activity feed, the
storage inspector, and per-project version history. Everything is read-only
except the explicitly-mutating endpoints (favorite, tag, archive/restore, and
the cleanup tools), exactly as the product requires. No endpoint modifies an
engine or its data, and every figure reflects real stored state.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from olympus.api.dependencies import LibraryServiceDep
from olympus.api.v1.schemas.library import (
    ActivityResponse,
    AssetsResponse,
    CapturedVersionsResponse,
    CleanupResponse,
    ClipsResponse,
    DashboardResponse,
    ExportsResponse,
    FavoriteRequest,
    MetaResponse,
    SearchResponse,
    StorageResponse,
    TagRequest,
    VersionEnginesResponse,
    VersionPayloadResponse,
    VersionsResponse,
)
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(library: LibraryServiceDep) -> DashboardResponse:
    """Return global statistics across everything Olympus has produced."""

    stats = await library.dashboard()
    return DashboardResponse(**stats.to_dict())


@router.get("/assets", response_model=AssetsResponse)
async def list_assets(
    library: LibraryServiceDep,
    kind: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    favorite: bool | None = Query(default=None),
    archived: bool | None = Query(default=None),
) -> AssetsResponse:
    """The Asset Library: source videos, clips, renders, exports (filterable)."""

    assets = await library.assets(
        kind=kind, project_id=project_id, query=q, tag=tag, favorite=favorite, archived=archived
    )
    return AssetsResponse(count=len(assets), assets=[a.to_dict() for a in assets])


@router.get("/clips", response_model=ClipsResponse)
async def list_clips(
    library: LibraryServiceDep,
    project_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    clip_status: str | None = Query(default=None, alias="status"),
    archived: bool | None = Query(default=None),
) -> ClipsResponse:
    """The Clip Library: every clip Olympus has ever produced."""

    clips = await library.clips(
        project_id=project_id, query=q, platform=platform, status=clip_status, archived=archived
    )
    return ClipsResponse(count=len(clips), clips=[c.to_dict() for c in clips])


@router.get("/exports", response_model=ExportsResponse)
async def list_exports(
    library: LibraryServiceDep,
    project_id: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    archived: bool | None = Query(default=None),
) -> ExportsResponse:
    """The Export Library: every rendered export with its real media facts."""

    exports = await library.exports(project_id=project_id, platform=platform, archived=archived)
    return ExportsResponse(count=len(exports), exports=[e.to_dict() for e in exports])


@router.get("/search", response_model=SearchResponse)
async def search(
    library: LibraryServiceDep,
    q: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> SearchResponse:
    """Global search across projects, clips, videos, and exports."""

    hits = await library.search(q, limit=limit)
    return SearchResponse(query=q, count=len(hits), hits=[h.to_dict() for h in hits])


@router.get("/activity", response_model=ActivityResponse)
async def get_activity(
    library: LibraryServiceDep,
    project_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> ActivityResponse:
    """The activity feed (real recorded + derived events), newest first."""

    events = await library.activity(project_id, limit=limit)
    return ActivityResponse(count=len(events), events=[e.to_dict() for e in events])


@router.get("/storage", response_model=StorageResponse)
async def get_storage(
    library: LibraryServiceDep, project_id: str | None = Query(default=None)
) -> StorageResponse:
    """The storage inspector: per-project consumption by namespace."""

    breakdowns = await library.storage(project_id)
    return StorageResponse(
        total_bytes=sum(b.total for b in breakdowns),
        breakdowns=[b.to_dict() for b in breakdowns],
    )


# -- Version history ----------------------------------------------------------
@router.get("/projects/{project_id}/versions", response_model=VersionEnginesResponse)
async def list_version_engines(
    project_id: str, library: LibraryServiceDep
) -> VersionEnginesResponse:
    """List the engines that have captured version history for a project."""

    engines = await library.list_version_engines(project_id)
    return VersionEnginesResponse(project_id=project_id, engines=engines)


@router.post(
    "/projects/{project_id}/versions/capture",
    response_model=CapturedVersionsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def capture_versions(project_id: str, library: LibraryServiceDep) -> CapturedVersionsResponse:
    """Capture a version snapshot of each engine's current output (deduplicated)."""

    captured = await library.capture_versions(project_id)
    return CapturedVersionsResponse(project_id=project_id, captured=[v.to_dict() for v in captured])


@router.get("/projects/{project_id}/versions/{engine}", response_model=VersionsResponse)
async def list_versions(
    project_id: str, engine: str, library: LibraryServiceDep
) -> VersionsResponse:
    """Browse the captured version history for one engine."""

    versions = await library.list_versions(project_id, engine)
    return VersionsResponse(
        project_id=project_id, engine=engine, versions=[v.to_dict() for v in versions]
    )


@router.get(
    "/projects/{project_id}/versions/{engine}/{version}", response_model=VersionPayloadResponse
)
async def get_version(
    project_id: str, engine: str, version: int, library: LibraryServiceDep
) -> VersionPayloadResponse:
    """Return the full captured payload for a specific version."""

    payload = await library.get_version(project_id, engine, version)
    if payload is None:
        raise NotFoundError(
            "Version not found.", details={"id": project_id, "engine": engine, "version": version}
        )
    return VersionPayloadResponse(
        project_id=project_id, engine=engine, version=version, payload=payload
    )


# -- Metadata mutations (favorites, tags, archive/restore) --------------------
@router.post("/projects/{project_id}/favorite", response_model=MetaResponse)
async def set_favorite(
    project_id: str, body: FavoriteRequest, library: LibraryServiceDep
) -> MetaResponse:
    """Mark/unmark a project as a favorite."""

    meta = await library.set_project_favorite(project_id, body.favorite)
    return MetaResponse(meta=meta.to_dict())


@router.post("/projects/{project_id}/tags", response_model=MetaResponse)
async def add_tag(project_id: str, body: TagRequest, library: LibraryServiceDep) -> MetaResponse:
    """Add a tag to a project."""

    meta = await library.add_project_tag(project_id, body.tag)
    return MetaResponse(meta=meta.to_dict())


@router.delete("/projects/{project_id}/tags/{tag}", response_model=MetaResponse)
async def remove_tag(project_id: str, tag: str, library: LibraryServiceDep) -> MetaResponse:
    """Remove a tag from a project."""

    meta = await library.remove_project_tag(project_id, tag)
    return MetaResponse(meta=meta.to_dict())


@router.post("/projects/{project_id}/archive", response_model=MetaResponse)
async def archive_project(project_id: str, library: LibraryServiceDep) -> MetaResponse:
    """Archive a project (hidden from default library views; data preserved)."""

    meta = await library.archive(project_id)
    return MetaResponse(meta=meta.to_dict())


@router.post("/projects/{project_id}/restore", response_model=MetaResponse)
async def restore_project(project_id: str, library: LibraryServiceDep) -> MetaResponse:
    """Restore an archived project."""

    meta = await library.restore(project_id)
    return MetaResponse(meta=meta.to_dict())


# -- Cleanup tools ------------------------------------------------------------
@router.post("/cleanup/temp-files", response_model=CleanupResponse)
async def cleanup_temp_files(
    library: LibraryServiceDep, project_id: str | None = Query(default=None)
) -> CleanupResponse:
    """Delete render working/temporary files (rendered outputs untouched)."""

    return CleanupResponse(result=(await library.cleanup_temp_files(project_id)).to_dict())


@router.post("/cleanup/failed-renders", response_model=CleanupResponse)
async def cleanup_failed_renders(
    library: LibraryServiceDep, project_id: str | None = Query(default=None)
) -> CleanupResponse:
    """Delete clip files from render runs whose status is FAILED."""

    return CleanupResponse(result=(await library.cleanup_failed_renders(project_id)).to_dict())


@router.post("/cleanup/unused-renders", response_model=CleanupResponse)
async def cleanup_unused_renders(
    library: LibraryServiceDep, project_id: str | None = Query(default=None)
) -> CleanupResponse:
    """Delete clip files no longer referenced by the current render manifest."""

    return CleanupResponse(result=(await library.cleanup_unused_renders(project_id)).to_dict())

"""Project endpoints.

Real, persistent project management built on the storage abstraction. Projects
survive refreshes and restarts. No endpoint fabricates processing results -
``/process`` honestly *queues* a project for the (not-yet-connected) editing
pipeline.

Media endpoints (``/source``, ``/thumbnail``) stream stored bytes directly from
the backend - no external services. Local-disk storage is served via the
framework's file response, which supports HTTP range requests (so the in-app
video player can seek). Cloud storage redirects to a presigned URL.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Response, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse

from olympus.api.dependencies import (
    AnalysisServiceDep,
    ProjectServiceDep,
    StorageDep,
    StoryServiceDep,
)
from olympus.api.v1.schemas.projects import (
    CreateProjectRequest,
    ProjectResponse,
    RenameProjectRequest,
)
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.services.projects import NewProjectInput

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: CreateProjectRequest,
    projects: ProjectServiceDep,
    analysis: AnalysisServiceDep,
) -> ProjectResponse:
    """Create a project from an uploaded video.

    Immediately kicks off the video understanding pipeline (the Cognitive Engine)
    in the background, so the project begins being *understood* the moment it is
    created. This sets the project's status to ``analyzing``; it never fabricates
    progress - stages report their honest state as the pipeline advances.
    """

    project = await projects.create(
        NewProjectInput(
            storage_key=payload.storage_key,
            source_filename=payload.source_filename,
            size_bytes=payload.size_bytes,
            video_format=payload.video_format,
            content_type=payload.content_type,
            duration_seconds=payload.duration_seconds,
            width=payload.width,
            height=payload.height,
            upload_duration_ms=payload.upload_duration_ms,
        )
    )
    # Begin understanding the video right away (background task).
    await analysis.start(project)
    refreshed = await projects.get(project.id)
    return ProjectResponse.from_entity(refreshed)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(projects: ProjectServiceDep) -> list[ProjectResponse]:
    """List all projects, newest first."""

    items = await projects.list()
    return [ProjectResponse.from_entity(p) for p in items]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, projects: ProjectServiceDep) -> ProjectResponse:
    """Fetch a single project (powers the project page; survives refresh)."""

    return ProjectResponse.from_entity(await projects.get(project_id))


@router.patch("/{project_id}", response_model=ProjectResponse)
async def rename_project(
    project_id: str, payload: RenameProjectRequest, projects: ProjectServiceDep
) -> ProjectResponse:
    """Rename a project."""

    return ProjectResponse.from_entity(await projects.rename(project_id, payload.name))


@router.post("/{project_id}/process", response_model=ProjectResponse)
async def process_project(project_id: str, projects: ProjectServiceDep) -> ProjectResponse:
    """Queue a project for the editing pipeline (honest: queues, does not fake work)."""

    return ProjectResponse.from_entity(await projects.queue(project_id))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    projects: ProjectServiceDep,
    analysis: AnalysisServiceDep,
    story: StoryServiceDep,
) -> Response:
    """Delete a project, its stored artifacts, its analysis, and its story."""

    await story.delete(project_id)
    await analysis.delete(project_id)
    await projects.delete(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/source")
async def get_project_source(
    project_id: str,
    projects: ProjectServiceDep,
    storage: StorageDep,
    download: bool = False,
) -> Response:
    """Stream the original uploaded video (supports range requests for seeking)."""

    project = await projects.get(project_id)
    media_type = project.content_type or f"video/{project.video_format}"
    path = storage.local_path(project.storage_key)
    if path is not None:
        # FileResponse handles HTTP Range automatically (seek/scrub support).
        return FileResponse(
            path,
            media_type=media_type,
            filename=project.source_filename if download else None,
        )
    url = await storage.generate_access_url(project.storage_key)
    return RedirectResponse(url)


@router.get("/{project_id}/thumbnail")
async def get_project_thumbnail(
    project_id: str, projects: ProjectServiceDep, storage: StorageDep
) -> Response:
    """Serve the project's thumbnail image (404 if none has been generated)."""

    project = await projects.get(project_id)
    if not project.thumbnail_key:
        raise NotFoundError("No thumbnail for this project.")
    path = storage.local_path(project.thumbnail_key)
    if path is not None:
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600"},
        )
    url = await storage.generate_access_url(project.thumbnail_key)
    return RedirectResponse(url)


@router.post("/{project_id}/thumbnail", response_model=ProjectResponse)
async def set_project_thumbnail(
    project_id: str, projects: ProjectServiceDep, file: UploadFile = File(...)
) -> ProjectResponse:
    """Store a thumbnail image (a real frame the client captured from the video)."""

    if not (file.content_type or "").startswith("image/"):
        raise ValidationError("Thumbnail must be an image.")
    data = await file.read()
    project = await projects.set_thumbnail(project_id, data, content_type=file.content_type)
    return ProjectResponse.from_entity(project)

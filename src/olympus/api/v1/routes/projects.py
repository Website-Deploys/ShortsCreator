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

from fastapi import APIRouter, BackgroundTasks, File, Response, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse

from olympus.api.dependencies import (
    AnalysisServiceDep,
    ClipPlannerServiceDep,
    EditingServiceDep,
    LibraryServiceDep,
    LinkIntakeDep,
    OptimizationServiceDep,
    ProjectServiceDep,
    RenderingServiceDep,
    SettingsDep,
    StorageDep,
    StoryServiceDep,
    ViralityServiceDep,
    WorkflowServiceDep,
)
from olympus.api.v1.schemas.projects import (
    CreateProjectFromLinkRequest,
    CreateProjectFromLinkResponse,
    CreateProjectRequest,
    LinkDownloadResponse,
    ProjectResponse,
    RenameProjectRequest,
)
from olympus.platform.config.settings import Environment
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.services.analysis import AnalysisService
from olympus.services.intake import (
    LinkDownloadRecord,
    LinkDownloadStatus,
    LinkIngestionMode,
    VideoLinkIntakeService,
)
from olympus.services.projects import NewProjectInput, ProjectService
from olympus.services.workflow import WorkflowService

router = APIRouter(prefix="/projects", tags=["projects"])
log = get_logger(__name__)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: CreateProjectRequest,
    projects: ProjectServiceDep,
    analysis: AnalysisServiceDep,
    workflow: WorkflowServiceDep,
    settings: SettingsDep,
) -> ProjectResponse:
    """Create a project from an uploaded video.

    Immediately kicks off the video understanding pipeline (the Cognitive Engine)
    in the background, so the project begins being *understood* the moment it is
    created. This sets the project's status to ``analyzing``; it never fabricates
    progress - stages report their honest state as the pipeline advances.
    """

    log.info(
        "project_creation_started",
        storage_key=payload.storage_key,
        source_filename=payload.source_filename,
    )
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
            desired_clip_count=payload.desired_clip_count,
            content_category=payload.content_category,
            editing_intensity=payload.editing_intensity,
            music_enabled=payload.music_enabled,
            sfx_enabled=payload.sfx_enabled,
            captions_enabled=payload.captions_enabled,
        )
    )
    log.info("project_created", project_id=project.id, storage_key=project.storage_key)
    # Begin understanding the video right away (background task).
    await analysis.start(project)
    if settings.durable_jobs.enabled and settings.environment is not Environment.TESTING:
        await workflow.start(
            project,
            source="manual_upload",
            idempotency_key=f"project_pipeline:{project.id}",
        )
    log.info("analysis_background_task_scheduled", project_id=project.id)
    refreshed = await projects.get(project.id)
    log.info("project_creation_response_ready", project_id=project.id)
    return ProjectResponse.from_entity(refreshed)


@router.post(
    "/from-link",
    response_model=CreateProjectFromLinkResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_project_from_link(
    payload: CreateProjectFromLinkRequest,
    background_tasks: BackgroundTasks,
    links: LinkIntakeDep,
    projects: ProjectServiceDep,
    analysis: AnalysisServiceDep,
    workflow: WorkflowServiceDep,
    settings: SettingsDep,
) -> CreateProjectFromLinkResponse:
    """Validate a permitted link and queue download/project creation."""

    log.info("link_project_creation_started", url=payload.url)
    record = await links.prepare(
        payload.url,
        permission_confirmed=payload.permission_confirmed,
        start_processing=payload.start_processing,
        mode=payload.mode,
        quality=payload.quality,
    )
    if record.status in {LinkDownloadStatus.FAILED, LinkDownloadStatus.UNAVAILABLE}:
        log.info(
            "link_project_creation_unavailable",
            url=payload.url,
            status=record.status.value,
            reason=record.reason,
        )
        return CreateProjectFromLinkResponse(
            download=_link_download_response(record),
            project=None,
        )

    if payload.mode != LinkIngestionMode.METADATA_ONLY.value:
        background_tasks.add_task(
            _complete_link_project,
            record.id,
            links,
            projects,
            analysis,
            workflow,
            settings.durable_jobs.enabled and settings.environment is not Environment.TESTING,
            payload,
        )
    log.info("link_project_creation_queued", ingestion_id=record.id, url=record.url)
    return CreateProjectFromLinkResponse(
        download=_link_download_response(record),
        project=None,
    )


@router.get(
    "/link-ingestions/{ingestion_id}",
    response_model=CreateProjectFromLinkResponse,
)
async def get_link_ingestion(
    ingestion_id: str,
    links: LinkIntakeDep,
    projects: ProjectServiceDep,
) -> CreateProjectFromLinkResponse:
    """Return persisted metadata, download progress, and the created project."""

    record = await links.get(ingestion_id)
    project_response = None
    if record.project_id:
        project_response = ProjectResponse.from_entity(await projects.get(record.project_id))
    return CreateProjectFromLinkResponse(
        download=_link_download_response(record),
        project=project_response,
    )


async def _complete_link_project(
    ingestion_id: str,
    links: VideoLinkIntakeService,
    projects: ProjectService,
    analysis: AnalysisService,
    workflow: WorkflowService,
    durable_jobs_enabled: bool,
    payload: CreateProjectFromLinkRequest,
) -> None:
    """Complete link ingestion after the HTTP response has been returned."""

    stage = "project_creation"
    try:
        record = await links.ingest_prepared(ingestion_id)
        if record.upload is None or record.status is not LinkDownloadStatus.DOWNLOADED:
            return
        if record.mode == LinkIngestionMode.DOWNLOAD_ONLY.value:
            return
        probe = record.media_probe or {}
        project = await projects.create(
            NewProjectInput(
                storage_key=record.upload.storage_key,
                source_filename=record.upload.filename,
                size_bytes=record.upload.size_bytes,
                video_format=record.upload.video_format,
                content_type=record.upload.content_type,
                duration_seconds=probe.get("container_duration"),
                width=probe.get("width"),
                height=probe.get("height"),
                source_type="link",
                source_url=record.url,
                link_ingestion_id=record.id,
                desired_clip_count=payload.desired_clip_count,
                content_category=payload.content_category,
                editing_intensity=payload.editing_intensity,
                music_enabled=payload.music_enabled,
                sfx_enabled=payload.sfx_enabled,
                captions_enabled=payload.captions_enabled,
            )
        )
        await links.attach_project(
            ingestion_id,
            project.id,
            processing_started=False,
        )
        if payload.start_processing:
            stage = "processing_started"
            await analysis.start(project)
            durable_workflow = (
                await workflow.start(
                    project,
                    source="link_ingestion",
                    idempotency_key=f"project_pipeline:{project.id}",
                )
                if durable_jobs_enabled
                else None
            )
            await links.attach_project(
                ingestion_id,
                project.id,
                processing_started=True,
                job_id=durable_workflow.workflow_id if durable_workflow is not None else None,
            )
        log.info("link_project_created", project_id=project.id, ingestion_id=ingestion_id)
    except Exception as exc:
        await links.fail_after_download(
            ingestion_id,
            exc,
            stage=stage,
            cleanup_upload=stage == "project_creation",
        )
        log.error(
            "link_project_background_failed",
            ingestion_id=ingestion_id,
            error=str(exc),
            exc_info=True,
        )


def _link_download_response(record: LinkDownloadRecord) -> LinkDownloadResponse:
    upload = record.upload
    return LinkDownloadResponse(
        ingestion_id=record.id,
        status=record.status.value,
        url=record.url,
        original_url=record.original_url,
        reason=record.reason,
        filename=upload.filename if upload else None,
        storage_key=upload.storage_key if upload else None,
        size_bytes=upload.size_bytes if upload else None,
        video_format=upload.video_format if upload else None,
        content_type=upload.content_type if upload else None,
        project_id=record.project_id,
        job_id=record.job_id,
        status_url=f"/api/v1/jobs/{record.job_id}" if record.job_id else None,
        resume_url=f"/api/v1/jobs/{record.job_id}/resume" if record.job_id else None,
        link_source=record.link_source,
        video_metadata=record.video_metadata,
        download_selection=record.download_selection,
        link_ingestion_status=record.link_ingestion_status,
        rights_confirmation=record.rights_confirmation,
        media_probe=record.media_probe,
        error=record.error,
        warnings=record.warnings,
    )


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
    virality: ViralityServiceDep,
    planning: ClipPlannerServiceDep,
    editing: EditingServiceDep,
    optimization: OptimizationServiceDep,
    rendering: RenderingServiceDep,
    workflow: WorkflowServiceDep,
    library: LibraryServiceDep,
) -> Response:
    """Delete a project, its stored artifacts, and all engine analyses."""

    # First, signal cancellation to every engine so an in-flight chain stops
    # propagating (an upstream engine completing must not re-trigger a
    # downstream one after we have begun deleting). Each delete() below then
    # waits for its own task to drain before removing artifacts.
    for service in (analysis, story, virality, planning, editing, optimization, rendering):
        await service.cancel(project_id)

    await library.delete_library_data(project_id)
    await workflow.delete(project_id)
    await optimization.delete(project_id)
    await rendering.delete(project_id)
    await editing.delete(project_id)
    await planning.delete(project_id)
    await virality.delete(project_id)
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

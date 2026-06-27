"""Dependency-injection providers for the API layer.

FastAPI's ``Depends`` system is our dependency-injection mechanism. These
provider functions construct (or look up) the dependencies routes need -
settings, database sessions, storage, AI providers, renderer - returning them
typed as their *contracts* so routes never import concrete adapters.

Adapters that are cheap and stateless are built per-request via the factories;
this keeps wiring explicit and testable (tests override these providers to
inject fakes). Heavier shared singletons (the DB engine) are managed in their
own modules and surfaced here.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from olympus.ai import build_transcription_provider
from olympus.data.database.session import get_session
from olympus.data.repositories import (
    StorageActivityRepository,
    StorageAnalysisRepository,
    StorageAuditRepository,
    StorageEditingRepository,
    StorageLibraryMetaRepository,
    StorageMetricsSnapshotRepository,
    StorageOptimizationRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageRenderManifestRepository,
    StorageRenderRunRepository,
    StorageStoryRepository,
    StorageVersionRepository,
    StorageViralityRepository,
    StorageWorkflowRepository,
)
from olympus.data.storage import build_storage
from olympus.domain.contracts import Renderer, StoragePort, TranscriptionProvider
from olympus.domain.contracts.rendering import ClipRenderer
from olympus.platform.config import Settings, get_settings
from olympus.rendering import build_clip_renderer, build_renderer
from olympus.services.analysis import AnalysisService
from olympus.services.editing import EditingService
from olympus.services.intake import IntakeService
from olympus.services.monitoring import MonitoringService
from olympus.services.optimization import OptimizationService
from olympus.services.planning import ClipPlannerService
from olympus.services.project_management import LibraryService
from olympus.services.projects import ProjectService
from olympus.services.rendering import RenderingService
from olympus.services.story import StoryService
from olympus.services.virality import ViralityService
from olympus.services.workflow import WorkflowService
from olympus.workflow import UploadRunner, build_service_runner


def settings_provider() -> Settings:
    """Provide the application settings."""

    return get_settings()


async def db_session_provider() -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session for the request."""

    async for session in get_session():
        yield session


def storage_provider() -> StoragePort:
    """Provide the configured storage adapter (typed as the contract)."""

    return build_storage()


def transcription_provider() -> TranscriptionProvider:
    """Provide the configured transcription provider (typed as the contract)."""

    return build_transcription_provider()


def renderer_provider() -> Renderer:
    """Provide the configured (legacy) renderer (typed as the contract)."""

    return build_renderer()


def clip_renderer_provider() -> ClipRenderer:
    """Provide the configured clip renderer for the Rendering Engine.

    The Rendering Engine depends only on the :class:`ClipRenderer` abstraction;
    this returns the FFmpeg-backed renderer today and can be swapped for a
    GPU/cloud/distributed backend without touching any pipeline stage. When the
    backend (e.g. FFmpeg) is absent, the renderer reports itself unavailable and
    the engine renders nothing rather than fabricating output.
    """

    return build_clip_renderer(get_settings().rendering.ffmpeg_binary)


def intake_provider() -> IntakeService:
    """Provide the video intake service, wired to the configured storage."""

    return IntakeService(build_storage())


def project_service_provider() -> ProjectService:
    """Provide the project service, wired to the configured storage."""

    storage = build_storage()
    return ProjectService(StorageProjectRepository(storage), storage)


def editing_service_provider() -> EditingService:
    """Provide the editing service (the Editing Engine's application boundary).

    Wired to the configured storage; reads the Cognitive, Story, Virality, and
    Clip Planner outputs as its only inputs. The in-flight run registry lives in
    the service module (process-wide), so per-request instances coordinate
    correctly. It renders nothing.
    """

    storage = build_storage()
    return EditingService(
        editing_repo=StorageEditingRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
    )


def optimization_service_provider() -> OptimizationService:
    """Provide the optimization service (the Optimization Engine's boundary).

    Wired to the configured storage; reads the Rendering Engine's render manifest
    plus the Cognitive, Story, Virality, Clip Planner, and Editing outputs as its
    only inputs. It is fully additive and never modifies any of them.

    Note on chaining: this engine intentionally does *not* auto-start after the
    Editing Engine, because the Rendering Engine must produce a real MP4 between
    them. It is started explicitly via the API, or - in a future deployment - by
    the Rendering Engine's own ``on_complete`` hook once that engine exists. The
    in-flight run registry lives in the service module (process-wide), so
    per-request instances coordinate correctly. It renders and encodes nothing.
    """

    storage = build_storage()
    return OptimizationService(
        optimization_repo=StorageOptimizationRepository(storage),
        render_repo=StorageRenderManifestRepository(storage),
        editing_repo=StorageEditingRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
    )


def rendering_service_provider() -> RenderingService:
    """Provide the rendering service (the Rendering Engine's application boundary).

    Wired to the configured storage and the replaceable clip renderer; reads the
    Editing Engine's timelines (plus the Cognitive/Story/Virality/Clip Planner
    outputs) as its only inputs, and the source media. It is the official producer
    of the render manifest the Optimization Engine consumes.

    Chaining: on a *successful* render (a manifest published with real rendered
    clips), its completion hook automatically starts the Optimization Engine -
    realising the Rendering -> Optimization chain. This is wiring only; neither
    engine is redesigned. When FFmpeg is unavailable the render stages report
    UNAVAILABLE honestly, no manifest is produced, and optimization is not
    triggered (there is nothing to optimize). Rendering itself is started
    explicitly (via the API), since it is the heavy execution step.
    """

    storage = build_storage()

    async def _start_optimization(project: object, _run: object) -> None:
        await optimization_service_provider().start(project)  # type: ignore[arg-type]

    return RenderingService(
        render_run_repo=StorageRenderRunRepository(storage),
        manifest_store=StorageRenderManifestRepository(storage),
        renderer=clip_renderer_provider(),
        editing_repo=StorageEditingRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
        on_complete=_start_optimization,
    )


def planning_service_provider() -> ClipPlannerService:
    """Provide the clip-planner service (the Clip Planner's application boundary).

    Wired to the configured storage; reads the Cognitive, Story, and Virality
    engines' outputs as its only inputs. Its completion hook automatically begins
    the Editing Engine once clip planning finishes, chaining the layers without
    coupling them. The in-flight run registry lives in the service module
    (process-wide), so per-request instances coordinate correctly.
    """

    storage = build_storage()

    async def _start_editing(project: object, _planning: object) -> None:
        await editing_service_provider().start(project)  # type: ignore[arg-type]

    return ClipPlannerService(
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
        on_complete=_start_editing,
    )


def virality_service_provider() -> ViralityService:
    """Provide the virality service (the Virality Engine's application boundary).

    Wired to the configured storage; reads the Cognitive Engine's and Story
    Engine's outputs as its only inputs. Its completion hook automatically begins
    Clip Planning once the Virality Engine finishes, chaining the layers without
    coupling them.
    """

    storage = build_storage()

    async def _start_planning(project: object, _virality: object) -> None:
        await planning_service_provider().start(project)  # type: ignore[arg-type]

    return ViralityService(
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
        on_complete=_start_planning,
    )


def story_service_provider() -> StoryService:
    """Provide the story service (the Story Engine's application boundary).

    Wired to the configured storage; reads the Cognitive Engine's output (the
    transcript) as its input. Its completion hook automatically begins Virality
    analysis once the Story Engine finishes, chaining the layers without coupling
    them. The in-flight run registry lives in the service module (process-wide),
    so per-request instances coordinate correctly.
    """

    storage = build_storage()

    async def _start_virality(project: object, _story: object) -> None:
        await virality_service_provider().start(project)  # type: ignore[arg-type]

    return StoryService(
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
        on_complete=_start_virality,
    )


def analysis_service_provider() -> AnalysisService:
    """Provide the analysis service (the Cognitive Engine's application boundary).

    Wired to the configured storage and transcription provider. Its completion
    hook automatically begins Story analysis once the Cognitive Engine finishes,
    chaining the two intelligence layers without coupling them.
    """

    storage = build_storage()

    async def _start_story(project: object, _analysis: object) -> None:
        # Build a fresh story service and kick off its background pipeline.
        await story_service_provider().start(project)  # type: ignore[arg-type]

    return AnalysisService(
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
        transcription_provider=build_transcription_provider(),
        on_complete=_start_story,
    )


# --------------------------------------------------------------------------- #
# Workflow Orchestration Engine
# --------------------------------------------------------------------------- #
# The Workflow Engine is a process-wide singleton: it owns the in-memory active-
# workflow cache, the job queue, the worker pool, and the event bus, which must
# be shared across all requests (unlike the per-request engine services). It is
# built lazily and reused.
_WORKFLOW_SERVICE: WorkflowService | None = None


def build_workflow_service() -> WorkflowService:
    """Construct the singleton workflow service, wiring runners to real engines.

    Each runner drives an existing engine's service to a genuine terminal state;
    the services are built once here (they coordinate via process-wide registries
    and shared storage, so a single instance is correct). This is pure wiring -
    no engine is modified, and the engines' own APIs and chaining keep working.
    """

    storage = build_storage()
    runners = {
        "upload": UploadRunner(storage),
        "cognitive": build_service_runner(
            "cognitive", analysis_service_provider(), getter="get_analysis"
        ),
        "story": build_service_runner("story", story_service_provider(), getter="get_story"),
        "virality": build_service_runner(
            "virality", virality_service_provider(), getter="get_virality"
        ),
        "planning": build_service_runner(
            "planning", planning_service_provider(), getter="get_planning"
        ),
        "editing": build_service_runner(
            "editing", editing_service_provider(), getter="get_editing"
        ),
        "rendering": build_service_runner(
            "rendering", rendering_service_provider(), getter="get_run"
        ),
        "optimization": build_service_runner(
            "optimization", optimization_service_provider(), getter="get_optimization"
        ),
    }
    return WorkflowService(
        repository=StorageWorkflowRepository(storage),
        project_repo=StorageProjectRepository(storage),
        runners=runners,
        concurrency=2,
    )


def workflow_service_provider() -> WorkflowService:
    """Provide the process-wide singleton workflow service."""

    global _WORKFLOW_SERVICE
    if _WORKFLOW_SERVICE is None:
        _WORKFLOW_SERVICE = build_workflow_service()
    return _WORKFLOW_SERVICE


def library_service_provider() -> LibraryService:
    """Provide the Project Management / Asset Library service.

    Composes the existing engine repositories (read-only) with the library's own
    additive repositories (versions, activity, metadata) under the ``library/``
    storage namespace. It never modifies any engine or its data.
    """

    storage = build_storage()
    return LibraryService(
        storage=storage,
        project_repo=StorageProjectRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        story_repo=StorageStoryRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        editing_repo=StorageEditingRepository(storage),
        render_manifest_repo=StorageRenderManifestRepository(storage),
        render_run_repo=StorageRenderRunRepository(storage),
        optimization_repo=StorageOptimizationRepository(storage),
        workflow_repo=StorageWorkflowRepository(storage),
        version_repo=StorageVersionRepository(storage),
        activity_repo=StorageActivityRepository(storage),
        meta_repo=StorageLibraryMetaRepository(storage),
    )


def monitoring_service_provider() -> MonitoringService:
    """Provide the Production Monitoring & Analytics service.

    Composes every engine repository (read-only), the workflow and activity
    repositories, and the monitoring-owned audit and metrics-snapshot
    repositories, plus the live workflow service singleton for worker/queue
    introspection. It is strictly observational: it never modifies any engine,
    the workflow, or their data, and never fabricates a metric.
    """

    storage = build_storage()
    return MonitoringService(
        storage=storage,
        project_repo=StorageProjectRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        story_repo=StorageStoryRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        editing_repo=StorageEditingRepository(storage),
        render_manifest_repo=StorageRenderManifestRepository(storage),
        render_run_repo=StorageRenderRunRepository(storage),
        optimization_repo=StorageOptimizationRepository(storage),
        workflow_repo=StorageWorkflowRepository(storage),
        activity_repo=StorageActivityRepository(storage),
        audit_repo=StorageAuditRepository(storage),
        snapshot_repo=StorageMetricsSnapshotRepository(storage),
        workflow_service=workflow_service_provider(),
    )


# Reusable typed aliases for clean route signatures.
SettingsDep = Annotated[Settings, Depends(settings_provider)]
DbSessionDep = Annotated[AsyncSession, Depends(db_session_provider)]
StorageDep = Annotated[StoragePort, Depends(storage_provider)]
TranscriptionDep = Annotated[TranscriptionProvider, Depends(transcription_provider)]
RendererDep = Annotated[Renderer, Depends(renderer_provider)]
ClipRendererDep = Annotated[ClipRenderer, Depends(clip_renderer_provider)]
IntakeDep = Annotated[IntakeService, Depends(intake_provider)]
ProjectServiceDep = Annotated[ProjectService, Depends(project_service_provider)]
AnalysisServiceDep = Annotated[AnalysisService, Depends(analysis_service_provider)]
StoryServiceDep = Annotated[StoryService, Depends(story_service_provider)]
ViralityServiceDep = Annotated[ViralityService, Depends(virality_service_provider)]
ClipPlannerServiceDep = Annotated[ClipPlannerService, Depends(planning_service_provider)]
EditingServiceDep = Annotated[EditingService, Depends(editing_service_provider)]
OptimizationServiceDep = Annotated[OptimizationService, Depends(optimization_service_provider)]
RenderingServiceDep = Annotated[RenderingService, Depends(rendering_service_provider)]
WorkflowServiceDep = Annotated[WorkflowService, Depends(workflow_service_provider)]
LibraryServiceDep = Annotated[LibraryService, Depends(library_service_provider)]
MonitoringServiceDep = Annotated[MonitoringService, Depends(monitoring_service_provider)]

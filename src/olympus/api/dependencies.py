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
    StorageAnalysisRepository,
    StorageProjectRepository,
    StorageStoryRepository,
)
from olympus.data.storage import build_storage
from olympus.domain.contracts import Renderer, StoragePort, TranscriptionProvider
from olympus.platform.config import Settings, get_settings
from olympus.rendering import build_renderer
from olympus.services.analysis import AnalysisService
from olympus.services.intake import IntakeService
from olympus.services.projects import ProjectService
from olympus.services.story import StoryService


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
    """Provide the configured renderer (typed as the contract)."""

    return build_renderer()


def intake_provider() -> IntakeService:
    """Provide the video intake service, wired to the configured storage."""

    return IntakeService(build_storage())


def project_service_provider() -> ProjectService:
    """Provide the project service, wired to the configured storage."""

    storage = build_storage()
    return ProjectService(StorageProjectRepository(storage), storage)


def story_service_provider() -> StoryService:
    """Provide the story service (the Story Engine's application boundary).

    Wired to the configured storage; reads the Cognitive Engine's output (the
    transcript) as its input. The in-flight run registry lives in the service
    module (process-wide), so per-request instances coordinate correctly.
    """

    storage = build_storage()
    return StoryService(
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
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


# Reusable typed aliases for clean route signatures.
SettingsDep = Annotated[Settings, Depends(settings_provider)]
DbSessionDep = Annotated[AsyncSession, Depends(db_session_provider)]
StorageDep = Annotated[StoragePort, Depends(storage_provider)]
TranscriptionDep = Annotated[TranscriptionProvider, Depends(transcription_provider)]
RendererDep = Annotated[Renderer, Depends(renderer_provider)]
IntakeDep = Annotated[IntakeService, Depends(intake_provider)]
ProjectServiceDep = Annotated[ProjectService, Depends(project_service_provider)]
AnalysisServiceDep = Annotated[AnalysisService, Depends(analysis_service_provider)]
StoryServiceDep = Annotated[StoryService, Depends(story_service_provider)]

"""Tests for project persistence, the project service, and the projects API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.dependencies import (
    analysis_service_provider,
    intake_provider,
    project_service_provider,
    storage_provider,
)
from olympus.data.repositories import StorageAnalysisRepository, StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.services.analysis import AnalysisService
from olympus.services.intake import IntakeService
from olympus.services.projects import NewProjectInput, ProjectService


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


@pytest.fixture
def service(storage: LocalStorage) -> ProjectService:
    return ProjectService(StorageProjectRepository(storage), storage)


async def _seed_upload(storage: LocalStorage, key: str = "uploads/u1/source.mp4") -> str:
    await storage.put(key, b"video-bytes", content_type="video/mp4")
    return key


def _new_input(key: str) -> NewProjectInput:
    return NewProjectInput(
        storage_key=key,
        source_filename="my video.mp4",
        size_bytes=11,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=42.5,
        width=1920,
        height=1080,
    )


async def test_create_and_get_project(service: ProjectService, storage: LocalStorage) -> None:
    key = await _seed_upload(storage)
    created = await service.create(_new_input(key))
    assert created.name == "my video"
    assert created.status.value == "uploaded"

    fetched = await service.get(created.id)
    assert fetched.id == created.id
    assert fetched.width == 1920


async def test_create_rejects_missing_upload(service: ProjectService) -> None:
    with pytest.raises(ValidationError):
        await service.create(_new_input("uploads/missing/source.mp4"))


async def test_persistence_survives_new_repository(storage: LocalStorage) -> None:
    """A project persists across repository instances (i.e. across restarts)."""

    key = await _seed_upload(storage)
    service_a = ProjectService(StorageProjectRepository(storage), storage)
    created = await service_a.create(_new_input(key))

    # A brand-new service/repo reading the same storage must find it.
    service_b = ProjectService(StorageProjectRepository(storage), storage)
    listed = await service_b.list()
    assert [p.id for p in listed] == [created.id]


async def test_queue_is_honest(service: ProjectService, storage: LocalStorage) -> None:
    key = await _seed_upload(storage)
    created = await service.create(_new_input(key))
    queued = await service.queue(created.id)
    # Honest: it becomes "queued", never fabricated as processing/complete.
    assert queued.status.value == "queued"


async def test_rename_project(service: ProjectService, storage: LocalStorage) -> None:
    key = await _seed_upload(storage)
    created = await service.create(_new_input(key))
    renamed = await service.rename(created.id, "  My Highlight Reel  ")
    assert renamed.name == "My Highlight Reel"
    with pytest.raises(ValidationError):
        await service.rename(created.id, "   ")


async def test_set_thumbnail(service: ProjectService, storage: LocalStorage) -> None:
    key = await _seed_upload(storage)
    created = await service.create(_new_input(key))
    assert created.thumbnail_key is None
    updated = await service.set_thumbnail(
        created.id, b"\xff\xd8jpegbytes", content_type="image/jpeg"
    )
    assert updated.thumbnail_key is not None
    assert await storage.exists(updated.thumbnail_key) is True


async def test_delete_removes_project_and_source(
    service: ProjectService, storage: LocalStorage
) -> None:
    key = await _seed_upload(storage)
    created = await service.create(_new_input(key))
    await service.delete(created.id)
    assert await storage.exists(key) is False
    with pytest.raises(NotFoundError):
        await service.get(created.id)


def test_projects_api_roundtrip(app: FastAPI, tmp_path: Path) -> None:
    """The HTTP API can create, list, fetch, and delete a project."""

    store = LocalStorage(root=str(tmp_path))
    app.dependency_overrides[project_service_provider] = lambda: ProjectService(
        StorageProjectRepository(store), store
    )
    app.dependency_overrides[intake_provider] = lambda: IntakeService(store)
    app.dependency_overrides[storage_provider] = lambda: store
    # Share the same storage so the auto-triggered analysis sees the project.
    app.dependency_overrides[analysis_service_provider] = lambda: AnalysisService(
        analysis_repo=StorageAnalysisRepository(store),
        project_repo=StorageProjectRepository(store),
        storage=store,
    )

    with TestClient(app) as client:
        up = client.post(
            "/api/v1/uploads",
            files={"file": ("clip.mp4", b"bytes-bytes", "video/mp4")},
        )
        assert up.status_code == 201
        upload = up.json()

        created = client.post(
            "/api/v1/projects",
            json={
                "storage_key": upload["storage_key"],
                "source_filename": upload["filename"],
                "size_bytes": upload["size_bytes"],
                "video_format": upload["video_format"],
                "duration_seconds": 12.0,
                "width": 1280,
                "height": 720,
            },
        )
        assert created.status_code == 201
        project = created.json()
        # Auto-trigger: the Cognitive Engine starts understanding immediately.
        assert project["status"] in ("analyzing", "analyzed")

        listed = client.get("/api/v1/projects")
        assert listed.status_code == 200
        assert any(p["id"] == project["id"] for p in listed.json())

        fetched = client.get(f"/api/v1/projects/{project['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["has_thumbnail"] is False

        # Serve the original video (range-capable endpoint).
        source = client.get(f"/api/v1/projects/{project['id']}/source")
        assert source.status_code == 200
        assert source.content == b"bytes-bytes"

        # Upload a thumbnail (a real captured frame) and serve it back.
        thumb_set = client.post(
            f"/api/v1/projects/{project['id']}/thumbnail",
            files={"file": ("thumb.jpg", b"\xff\xd8jpeg", "image/jpeg")},
        )
        assert thumb_set.status_code == 200
        assert thumb_set.json()["has_thumbnail"] is True
        thumb = client.get(f"/api/v1/projects/{project['id']}/thumbnail")
        assert thumb.status_code == 200

        # Rename.
        renamed = client.patch(
            f"/api/v1/projects/{project['id']}", json={"name": "Renamed"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Renamed"

        deleted = client.delete(f"/api/v1/projects/{project['id']}")
        assert deleted.status_code == 204

        missing = client.get(f"/api/v1/projects/{project['id']}")
        assert missing.status_code == 404



async def test_derived_name_is_bounded_for_hostile_filename(
    service: ProjectService, storage: LocalStorage
) -> None:
    """A multi-thousand-character filename must not yield an unbounded name.

    Regression: ``_derive_name`` previously returned the full filename stem with
    no length ceiling, while ``rename`` enforced a 200-char limit - so an
    accidental or hostile upload filename could produce an enormous project name
    that bloats API payloads/persisted state and breaks the UI. The derived name
    must honour the same ceiling as the rename path.
    """
    from olympus.services.projects.service import MAX_PROJECT_NAME_LENGTH

    key = await _seed_upload(storage)
    data = _new_input(key)
    data.source_filename = "A" * 4000 + ".mp4"

    created = await service.create(data)

    assert len(created.name) <= MAX_PROJECT_NAME_LENGTH
    assert created.name == "A" * MAX_PROJECT_NAME_LENGTH
    # And the bound is single-sourced with the rename guard.
    with pytest.raises(ValidationError):
        await service.rename(created.id, "B" * (MAX_PROJECT_NAME_LENGTH + 1))


async def test_derived_name_falls_back_when_stem_empty(
    service: ProjectService, storage: LocalStorage
) -> None:
    """A filename that is all extension/whitespace yields a safe, non-empty name."""
    key = await _seed_upload(storage)
    data = _new_input(key)
    data.source_filename = "   .mp4"

    created = await service.create(data)

    assert created.name.strip() != ""
    assert len(created.name) <= 200



async def test_delete_tolerates_corrupt_project_document(
    service: ProjectService, storage: LocalStorage
) -> None:
    """A corrupt project.json must still be deletable, not a permanent 5xx.

    Regression: ProjectService.delete() read the project via repo.get() before
    deleting, and repo.get() raises StorageError on an unparseable document - so
    a corrupt project could never be removed and its detail endpoint 5xx'd
    forever. Delete must purge the broken record regardless.
    """
    from olympus.platform.errors import StorageError

    key = "projects/proj_corrupt/project.json"
    await storage.put(key, b"{ this is not valid json", content_type="application/json")
    assert await storage.exists(key)

    # get() surfaces the corruption as a mapped StorageError ...
    with pytest.raises(StorageError):
        await service.get("proj_corrupt")

    # ... but delete() must succeed and remove the broken document.
    await service.delete("proj_corrupt")
    assert not await storage.exists(key)

    # idempotent: deleting again is a no-op, never raises.
    await service.delete("proj_corrupt")

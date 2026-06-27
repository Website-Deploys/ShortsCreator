"""Tests for the video intake service and the upload endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.dependencies import intake_provider
from olympus.data.storage.local import LocalStorage
from olympus.platform.errors import ValidationError
from olympus.services.intake import IntakeService


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


@pytest.fixture
def intake(tmp_path: Path) -> IntakeService:
    return IntakeService(LocalStorage(root=str(tmp_path)))


async def test_store_upload_happy_path(intake: IntakeService, tmp_path: Path) -> None:
    record = await intake.store_upload("clip.mp4", "video/mp4", _chunks(b"abc", b"defg"))
    assert record.size_bytes == 7
    assert record.video_format == "mp4"
    assert record.storage_key.endswith("source.mp4")
    # The bytes were really written to storage.
    assert (tmp_path / record.storage_key).read_bytes() == b"abcdefg"


async def test_store_upload_rejects_unsupported_format(intake: IntakeService) -> None:
    with pytest.raises(ValidationError):
        await intake.store_upload("notes.pdf", "application/pdf", _chunks(b"x"))


async def test_store_upload_rejects_empty_file(intake: IntakeService) -> None:
    with pytest.raises(ValidationError):
        await intake.store_upload("empty.mov", "video/quicktime", _chunks())


def test_upload_endpoint_stores_file(app: FastAPI, tmp_path: Path) -> None:
    """POST /uploads accepts a real multipart file and returns its record."""

    app.dependency_overrides[intake_provider] = lambda: IntakeService(
        LocalStorage(root=str(tmp_path))
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/uploads",
            files={"file": ("sample.mp4", b"\x00\x01\x02\x03video-bytes", "video/mp4")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "sample.mp4"
    assert body["video_format"] == "mp4"
    assert body["size_bytes"] == len(b"\x00\x01\x02\x03video-bytes")
    assert body["storage_key"].startswith("uploads/")


def test_upload_endpoint_rejects_bad_format(app: FastAPI, tmp_path: Path) -> None:
    """An unsupported format is rejected with a 422 and a clear code."""

    app.dependency_overrides[intake_provider] = lambda: IntakeService(
        LocalStorage(root=str(tmp_path))
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/uploads",
            files={"file": ("document.pdf", b"%PDF-1.4", "application/pdf")},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

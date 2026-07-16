"""Tests for the video intake service and the upload endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.dependencies import intake_provider
from olympus.data.storage.local import LocalStorage
from olympus.platform.config.settings import LinkIngestionSettings
from olympus.platform.errors import ValidationError
from olympus.services.intake import DownloadedFile, IntakeService, VideoLinkIntakeService


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


def _youtube_metadata(
    _url: str,
    *,
    availability: str = "public",
    is_live: bool = False,
) -> dict[str, object]:
    return {
        "id": "BaW_jenozKc",
        "title": "Owned test video",
        "uploader": "Olympus Test",
        "channel": "Olympus Test",
        "duration": 90.0,
        "webpage_url": "https://www.youtube.com/watch?v=BaW_jenozKc",
        "availability": availability,
        "is_live": is_live,
        "formats": [
            {
                "format_id": "4k",
                "ext": "webm",
                "width": 3840,
                "height": 2160,
                "fps": 30,
                "vcodec": "vp9",
                "acodec": "none",
                "filesize": 400_000_000,
            },
            {
                "format_id": "1080",
                "ext": "mp4",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "vcodec": "h264",
                "acodec": "none",
                "filesize": 100_000_000,
            },
            {
                "format_id": "audio",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "aac",
                "filesize": 10_000_000,
            },
        ],
    }


def _valid_probe(_path: Path) -> dict[str, object]:
    return {
        "passed": True,
        "has_video": True,
        "has_audio": True,
        "container_duration": 90.0,
        "width": 1920,
        "height": 1080,
        "video_codec": "h264",
        "audio_codec": "aac",
        "errors": [],
    }


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


async def test_link_intake_stores_downloaded_file(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))

    def _fake_downloader(_url: str, directory: Path) -> DownloadedFile:
        path = directory / "Allowed Clip.mp4"
        path.write_bytes(b"real-video-bytes")
        return DownloadedFile(path=path, filename=path.name, content_type="video/mp4")

    service = VideoLinkIntakeService(
        storage,
        downloader=_fake_downloader,
        metadata_extractor=_youtube_metadata,
        media_probe=_valid_probe,
    )
    record = await service.ingest(
        "https://youtu.be/BaW_jenozKc?si=tracking",
        permission_confirmed=True,
    )

    assert record.status.value == "downloaded"
    assert record.upload is not None
    assert record.upload.storage_key.startswith("uploads/")
    assert await storage.exists(record.upload.storage_key)
    assert record.url == "https://www.youtube.com/watch?v=BaW_jenozKc"
    assert record.video_metadata["title"] == "Owned test video"
    assert record.media_probe and record.media_probe["passed"] is True


async def test_link_intake_reports_downloader_unavailable(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))

    def _missing_downloader(_url: str, _directory: Path) -> DownloadedFile:
        raise ImportError("yt-dlp is not installed")

    service = VideoLinkIntakeService(
        storage,
        downloader=_missing_downloader,
        metadata_extractor=_youtube_metadata,
        media_probe=_valid_probe,
    )
    record = await service.ingest(
        "https://www.youtube.com/watch?v=BaW_jenozKc",
        permission_confirmed=True,
    )

    assert record.status.value == "unavailable"
    assert record.upload is None
    assert record.error and record.error["code"] == "DOWNLOADER_UNAVAILABLE"


async def test_link_intake_requires_permission(tmp_path: Path) -> None:
    service = VideoLinkIntakeService(LocalStorage(root=str(tmp_path)))
    with pytest.raises(ValidationError):
        await service.ingest(
            "https://www.youtube.com/watch?v=BaW_jenozKc",
            permission_confirmed=False,
        )


@pytest.mark.parametrize(
    ("url", "url_type"),
    [
        ("https://www.youtube.com/watch?v=BaW_jenozKc&feature=share", "watch"),
        ("https://youtu.be/BaW_jenozKc?t=12", "short_url"),
        ("https://youtube.com/shorts/BaW_jenozKc", "shorts"),
    ],
)
def test_link_validation_accepts_and_normalizes_youtube_urls(
    tmp_path: Path,
    url: str,
    url_type: str,
) -> None:
    service = VideoLinkIntakeService(LocalStorage(root=str(tmp_path)))
    source = service.validate_url(url, permission_confirmed=True)
    assert source["normalized_url"] == "https://www.youtube.com/watch?v=BaW_jenozKc"
    assert source["url_type"] == url_type


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/private/video.mp4",
        "http://localhost/video.mp4",
        "http://127.0.0.1/video.mp4",
        "http://192.168.1.2/video.mp4",
        "https://youtube.com.evil.example/watch?v=BaW_jenozKc",
        "https://example.com/video.mp4",
    ],
)
def test_link_validation_rejects_unsafe_or_unsupported_urls(tmp_path: Path, url: str) -> None:
    service = VideoLinkIntakeService(LocalStorage(root=str(tmp_path)))
    with pytest.raises(ValidationError):
        service.validate_url(url, permission_confirmed=True)


def test_link_validation_rejects_playlist_only_url(tmp_path: Path) -> None:
    service = VideoLinkIntakeService(LocalStorage(root=str(tmp_path)))
    with pytest.raises(ValidationError) as exc_info:
        service.validate_url(
            "https://www.youtube.com/playlist?list=PL123456789",
            permission_confirmed=True,
        )
    assert exc_info.value.code == "PLAYLIST_NOT_SUPPORTED"


async def test_link_metadata_rejects_private_video(tmp_path: Path) -> None:
    def private_metadata(url: str) -> dict[str, object]:
        return _youtube_metadata(url, availability="private")

    service = VideoLinkIntakeService(
        LocalStorage(root=str(tmp_path)),
        metadata_extractor=private_metadata,
    )
    record = await service.prepare(
        "https://www.youtube.com/watch?v=BaW_jenozKc",
        permission_confirmed=True,
    )
    assert record.status.value == "failed"
    assert record.error and record.error["code"] == "PRIVATE_VIDEO"


async def test_quality_selection_caps_height_and_persists_progress(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    service = VideoLinkIntakeService(
        storage,
        metadata_extractor=_youtube_metadata,
        settings=LinkIngestionSettings(max_height=1080),
    )
    record = await service.prepare(
        "https://www.youtube.com/watch?v=BaW_jenozKc",
        permission_confirmed=True,
    )
    assert record.download_selection["selected_format_id"] == "1080+audio"
    await service._persist_progress(
        record.id,
        {
            "status": "downloading",
            "downloaded_bytes": 25,
            "total_bytes": 100,
            "speed": 10,
            "eta": 7.5,
        },
    )
    refreshed = await service.get(record.id)
    assert refreshed.link_ingestion_status["progress_percent"] == 25.0


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

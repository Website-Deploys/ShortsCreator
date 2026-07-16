"""The video intake service.

Validates an incoming upload, streams it into storage (memory-bounded, so files
of any size are supported), and returns a record describing the stored object.

The service depends only on the :class:`StoragePort` contract, so it is storage
backend agnostic and trivially testable with the local backend.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from olympus.domain.contracts.storage import StoragePort
from olympus.platform.errors import ValidationError
from olympus.platform.logging import get_logger
from olympus.utils import new_id

log = get_logger(__name__)

# The video container formats accepted by the MVP. We intentionally do NOT cap
# file size - large uploads are first-class (the storage layer streams them).
ALLOWED_VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".avi", ".mkv", ".webm"}
)


@dataclass(slots=True)
class UploadRecord:
    """Describes a stored upload (returned to the client)."""

    id: str
    filename: str
    content_type: str | None
    size_bytes: int
    storage_key: str
    video_format: str


class IntakeService:
    """Validate and store uploaded videos."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    @staticmethod
    def _extension_of(filename: str) -> str:
        return PurePosixPath(filename).suffix.lower()

    def _validate(self, filename: str) -> str:
        if not filename or not filename.strip():
            raise ValidationError("A file with a name is required.")
        ext = self._extension_of(filename)
        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            raise ValidationError(
                "Unsupported video format.",
                details={
                    "filename": filename,
                    "supported": sorted(e.lstrip(".") for e in ALLOWED_VIDEO_EXTENSIONS),
                },
            )
        return ext

    async def store_upload(
        self,
        filename: str,
        content_type: str | None,
        chunks: AsyncIterator[bytes],
    ) -> UploadRecord:
        """Validate and stream-store an upload, returning its record.

        The storage key is derived from a fresh upload id and the validated
        extension (never from the raw filename), so untrusted client filenames
        can never influence the storage path.
        """

        ext = self._validate(filename)
        upload_id = new_id("upl")
        storage_key = f"uploads/{upload_id}/source{ext}"

        started = time.perf_counter()
        log.info(
            "upload_storage_write_started",
            upload_id=upload_id,
            filename=filename,
            storage_key=storage_key,
        )
        stored = await self._storage.put_stream(
            storage_key, chunks, content_type=content_type
        )
        log.info(
            "upload_storage_write_completed",
            upload_id=upload_id,
            storage_key=storage_key,
            size_bytes=stored.size_bytes,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

        if stored.size_bytes == 0:
            # Clean up and reject empty uploads (honest failure, no junk stored).
            await self._storage.delete(storage_key)
            raise ValidationError("The uploaded file was empty.")

        return UploadRecord(
            id=upload_id,
            filename=filename,
            content_type=content_type,
            size_bytes=stored.size_bytes,
            storage_key=storage_key,
            video_format=ext.lstrip("."),
        )

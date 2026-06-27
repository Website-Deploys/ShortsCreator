"""Video upload endpoint.

``POST /api/v1/uploads`` accepts a multipart video file, streams it into storage
without buffering the whole file in memory (so uploads of any size are
supported), validates the format, and returns a record describing the stored
object.

This is a real, working endpoint backed by the storage abstraction - not a mock.
The browser computes upload progress/speed/ETA from the request it sends; the
server's responsibility is to receive, validate, and durably store the bytes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, File, UploadFile, status

from olympus.api.dependencies import IntakeDep
from olympus.api.v1.schemas.uploads import UploadResponse
from olympus.platform.errors import ValidationError

router = APIRouter()

# Size of chunks read from the incoming file when streaming to storage.
_CHUNK_SIZE = 1024 * 1024  # 1 MiB


async def _iter_upload(upload: UploadFile, chunk_size: int = _CHUNK_SIZE) -> AsyncIterator[bytes]:
    """Yield the upload's bytes in chunks (Starlette spools large files to disk)."""

    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        yield chunk


@router.post(
    "/uploads",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a video",
)
async def create_upload(intake: IntakeDep, file: UploadFile = File(...)) -> UploadResponse:
    """Receive, validate, and store an uploaded video."""

    if not file.filename:
        raise ValidationError("A file is required.")

    record = await intake.store_upload(
        filename=file.filename,
        content_type=file.content_type,
        chunks=_iter_upload(file),
    )
    return UploadResponse(
        id=record.id,
        filename=record.filename,
        size_bytes=record.size_bytes,
        content_type=record.content_type,
        video_format=record.video_format,
        storage_key=record.storage_key,
    )

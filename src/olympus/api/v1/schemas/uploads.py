"""Schemas for the uploads API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """Returned after a video has been successfully received and stored."""

    id: str = Field(description="Unique id for the stored upload.")
    filename: str = Field(description="The original filename provided by the client.")
    size_bytes: int = Field(description="Authoritative size of the stored file, in bytes.")
    content_type: str | None = Field(default=None, description="Reported content type.")
    video_format: str = Field(description="Detected container format (e.g. 'mp4').")
    storage_key: str = Field(description="Internal storage key for the stored object.")

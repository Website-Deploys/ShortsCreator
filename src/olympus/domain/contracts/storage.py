"""Storage contract (port).

Defines the capability "durably store and retrieve large binary artifacts by
key" without binding to a backend. Implemented by the local-disk and
S3-compatible adapters in ``olympus.data.storage``.

Keys are opaque, hierarchical strings (e.g. ``"projects/{id}/source.mp4"``).
The contract intentionally exposes a minimal, backend-agnostic surface: put,
get, delete, exists, and a time-limited access URL. Higher-level concerns
(lifecycle, retention, per-project namespacing) are policy built on top of this
in later milestones.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(slots=True)
class StorageObject:
    """Metadata describing a stored object."""

    key: str
    size_bytes: int
    content_type: str | None = None


class StoragePort(abc.ABC):
    """Abstract storage backend.

    All methods raise :class:`olympus.platform.errors.StorageError` on backend
    failure so callers handle a single error type regardless of backend.
    """

    @abc.abstractmethod
    async def put(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> StorageObject:
        """Store ``data`` under ``key`` and return its metadata."""

    @abc.abstractmethod
    async def get(self, key: str) -> bytes:
        """Return the bytes stored under ``key`` (raises if missing)."""

    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        """Return whether an object exists at ``key``."""

    @abc.abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the object at ``key`` (idempotent: no error if absent)."""

    @abc.abstractmethod
    async def generate_access_url(self, key: str, *, expires_in: int = 3600) -> str:
        """Return a time-limited URL granting read access to ``key``.

        For cloud backends this is a presigned URL; for local development it is
        a URL served by the API. ``expires_in`` is in seconds.
        """

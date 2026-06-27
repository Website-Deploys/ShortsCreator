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
from collections.abc import AsyncIterator
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
    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
    ) -> StorageObject:
        """Stream ``chunks`` into storage under ``key`` and return its metadata.

        Streaming (rather than buffering the whole payload in memory via
        :meth:`put`) is what lets Olympus accept arbitrarily large video uploads
        without memory pressure. The returned :class:`StorageObject` reports the
        total number of bytes written.
        """

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
    async def list_keys(self, prefix: str) -> list[str]:
        """Return all object keys beginning with ``prefix``.

        Used by repositories that enumerate stored documents (e.g. listing a
        creator's projects). Returns an empty list if nothing matches.
        """

    @abc.abstractmethod
    async def generate_access_url(self, key: str, *, expires_in: int = 3600) -> str:
        """Return a time-limited URL granting read access to ``key``.

        For cloud backends this is a presigned URL; for local development it is
        a URL served by the API. ``expires_in`` is in seconds.
        """

    def local_path(self, key: str) -> str | None:
        """Return a local filesystem path for ``key`` if this backend is local-disk.

        Concrete (non-abstract) with a ``None`` default so cloud backends need no
        change. The local backend overrides it, enabling efficient range-based
        media streaming (video seeking) via the web framework's file responses.
        """

        return None

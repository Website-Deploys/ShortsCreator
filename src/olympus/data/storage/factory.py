"""Storage adapter factory.

Selects and constructs the configured storage backend, returning it typed as
the :class:`StoragePort` contract so callers never depend on the concrete
adapter. This is the composition point that makes the backend a one-line
configuration choice.
"""

from __future__ import annotations

from olympus.domain.contracts.storage import StoragePort
from olympus.platform.config import Settings, get_settings
from olympus.platform.config.settings import StorageBackend
from olympus.platform.errors import ConfigurationError


def build_storage(settings: Settings | None = None) -> StoragePort:
    """Construct the storage adapter selected by configuration."""

    settings = settings or get_settings()
    backend = settings.storage.backend

    if backend is StorageBackend.LOCAL:
        from olympus.data.storage.local import LocalStorage

        return LocalStorage(root=settings.storage.local_root)

    if backend is StorageBackend.S3:
        from olympus.data.storage.s3 import S3Storage

        return S3Storage(settings.storage)

    raise ConfigurationError(f"Unknown storage backend: {backend!r}")

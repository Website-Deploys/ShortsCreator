"""Local-filesystem storage adapter.

The default backend in development and tests: it requires no cloud credentials,
so the application starts and runs end-to-end out of the box. Objects are stored
as files under a configured root directory, with the object key mapped to a
relative path.

This adapter is fully functional (not a placeholder). Blocking file I/O is run
in a thread to keep the async event loop responsive.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from olympus.domain.contracts.storage import StorageObject, StoragePort
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


class LocalStorage(StoragePort):
    """Store objects as files beneath ``root``."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        log.info("local_storage_init", root=str(self._root))

    def _path_for(self, key: str) -> Path:
        # Prevent path traversal: the resolved path must stay within root.
        candidate = (self._root / key).resolve()
        if not str(candidate).startswith(str(self._root)):
            raise StorageError("Invalid storage key.", details={"key": key})
        return candidate

    async def put(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> StorageObject:
        def _write() -> int:
            path = self._path_for(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return len(data)

        try:
            size = await asyncio.to_thread(_write)
        except OSError as exc:
            raise StorageError("Failed to write object.", details={"key": key}) from exc
        return StorageObject(key=key, size_bytes=size, content_type=content_type)

    async def get(self, key: str) -> bytes:
        def _read() -> bytes:
            return self._path_for(key).read_bytes()

        try:
            return await asyncio.to_thread(_read)
        except FileNotFoundError as exc:
            raise StorageError("Object not found.", details={"key": key}) from exc
        except OSError as exc:
            raise StorageError("Failed to read object.", details={"key": key}) from exc

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path_for(key).exists)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            self._path_for(key).unlink(missing_ok=True)

        await asyncio.to_thread(_delete)

    async def generate_access_url(self, key: str, *, expires_in: int = 3600) -> str:
        # In local development there is no presigning; the API serves the file.
        # The expiry is advisory and enforced by the serving endpoint later.
        return f"/internal/storage/{key}"

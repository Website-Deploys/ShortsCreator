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
import os
import tempfile
from collections.abc import AsyncIterator
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
            # Atomic write: write to a temp file in the same directory, then
            # os.replace() it into place. This guarantees readers always see a
            # complete file, never a partially-written one - essential because
            # background tasks (e.g. analysis status updates) may rewrite a
            # document concurrently with a reader.
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            return len(data)

        try:
            size = await asyncio.to_thread(_write)
        except OSError as exc:
            raise StorageError("Failed to write object.", details={"key": key}) from exc
        return StorageObject(key=key, size_bytes=size, content_type=content_type)

    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
    ) -> StorageObject:
        path = self._path_for(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        size = 0
        try:
            handle = await asyncio.to_thread(open, path, "wb")
            try:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    await asyncio.to_thread(handle.write, chunk)
                    size += len(chunk)
            finally:
                await asyncio.to_thread(handle.close)
        except OSError as exc:
            # Clean up a partial file so we never leave corrupt artifacts.
            await asyncio.to_thread(path.unlink, True)
            raise StorageError("Failed to stream object.", details={"key": key}) from exc
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

    async def list_keys(self, prefix: str) -> list[str]:
        def _walk() -> list[str]:
            start = self._path_for(prefix) if prefix else self._root
            if not start.exists():
                return []
            keys: list[str] = []
            for path in start.rglob("*"):
                if path.is_file():
                    keys.append(path.relative_to(self._root).as_posix())
            return sorted(keys)

        return await asyncio.to_thread(_walk)

    async def generate_access_url(self, key: str, *, expires_in: int = 3600) -> str:
        # In local development there is no presigning; the API serves the file.
        # The expiry is advisory and enforced by the serving endpoint later.
        return f"/internal/storage/{key}"

    def local_path(self, key: str) -> str | None:
        """Return the on-disk path for ``key`` if it exists, else ``None``."""

        path = self._path_for(key)
        return str(path) if path.exists() else None

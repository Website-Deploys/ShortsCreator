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
import time
from collections.abc import AsyncIterator
from pathlib import Path

from olympus.domain.contracts.storage import StorageObject, StoragePort
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)

_WINDOWS_REPLACE_ATTEMPTS = 20
_WINDOWS_REPLACE_BACKOFF_SECONDS = 0.025
_WINDOWS_READ_RETRY_ENABLED = os.name == "nt"


class LocalStorage(StoragePort):
    """Store objects as files beneath ``root``."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        log.info("local_storage_init", root=str(self._root))

    def _path_for(self, key: str) -> Path:
        # Prevent path traversal: the resolved path must stay within root. A
        # string ``startswith`` check is unsafe (a sibling like ``<root>_evil``
        # shares the prefix), so we verify true path containment instead.
        candidate = (self._root / key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
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
                _replace_atomic(tmp, path)
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
        started = time.perf_counter()
        log.info("local_storage_stream_write_started", key=key)
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
        except BaseException:
            # Producer error, client disconnect, or cancellation mid-stream: never
            # leave an orphaned partial object behind. Re-raise the original
            # exception unchanged (preserving its type and traceback).
            await asyncio.to_thread(path.unlink, True)
            raise
        log.info(
            "local_storage_stream_write_completed",
            key=key,
            size_bytes=size,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return StorageObject(key=key, size_bytes=size, content_type=content_type)

    async def get(self, key: str) -> bytes:
        def _read() -> bytes:
            path = self._path_for(key)
            for attempt in range(_WINDOWS_REPLACE_ATTEMPTS):
                try:
                    return path.read_bytes()
                except PermissionError:
                    if (
                        not _WINDOWS_READ_RETRY_ENABLED
                        or attempt == _WINDOWS_REPLACE_ATTEMPTS - 1
                    ):
                        raise
                    time.sleep(_WINDOWS_REPLACE_BACKOFF_SECONDS * (attempt + 1))
            raise RuntimeError("unreachable")

        try:
            return await asyncio.to_thread(_read)
        except FileNotFoundError as exc:
            raise StorageError("Object not found.", details={"key": key}) from exc
        except OSError as exc:
            raise StorageError("Failed to read object.", details={"key": key}) from exc

    async def exists(self, key: str) -> bool:
        def _exists() -> bool:
            try:
                return self._path_for(key).exists()
            except (OSError, StorageError):
                # An invalid, oversized (ENAMETOOLONG), or otherwise un-stattable
                # key cannot name an existing object. exists() is a boolean query,
                # so answer it honestly (False) instead of raising - a hostile or
                # malformed key must never turn a presence check into a 5xx.
                return False

        return await asyncio.to_thread(_exists)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            path = self._path_for(key)
            path.unlink(missing_ok=True)
            # Prune now-empty parent directories up to (but not including) the
            # root, so deleting all of a project's objects does not leave
            # orphaned empty directories behind. Stops at the first non-empty
            # (or already-removed) directory.
            parent = path.parent
            while parent != self._root and parent.is_relative_to(self._root):
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent

        await asyncio.to_thread(_delete)

    async def list_keys(self, prefix: str) -> list[str]:
        def _walk() -> list[str]:
            try:
                start = self._path_for(prefix) if prefix else self._root
                if not start.exists():
                    return []
                keys: list[str] = []
                for path in start.rglob("*"):
                    if path.is_file():
                        keys.append(path.relative_to(self._root).as_posix())
                return sorted(keys)
            except (OSError, StorageError):
                # Invalid/oversized prefix lists nothing - never raise (a hostile
                # key must not turn a listing into a 5xx).
                return []

        return await asyncio.to_thread(_walk)

    async def generate_access_url(self, key: str, *, expires_in: int = 3600) -> str:
        # In local development there is no presigning; the API serves the file.
        # The expiry is advisory and enforced by the serving endpoint later.
        return f"/internal/storage/{key}"

    def local_path(self, key: str) -> str | None:
        """Return the on-disk path for ``key`` if it exists, else ``None``."""

        try:
            path = self._path_for(key)
            return str(path) if path.exists() else None
        except (OSError, StorageError):
            # Invalid or un-stattable key: no local path exists. Never raise here -
            # callers (e.g. file-serving routes) treat None as "not available" and
            # fall back, so a hostile key yields a clean 404, not a 5xx.
            return None


def _replace_atomic(source: str, destination: Path) -> None:
    """Atomically replace a file, tolerating transient Windows reader locks."""

    for attempt in range(_WINDOWS_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if os.name != "nt" or attempt == _WINDOWS_REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_WINDOWS_REPLACE_BACKOFF_SECONDS * (attempt + 1))

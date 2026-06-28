"""Storage size helpers for the Project Management layer.

Sizes are measured from the real filesystem when the backend is local-disk (the
default), via the storage port's ``local_path``. For backends that don't expose a
local path, size is reported as ``None`` (UNKNOWN) rather than reading whole
media files into memory or fabricating a number - honest by construction.
"""

from __future__ import annotations

import asyncio
import os

from olympus.domain.contracts.storage import StoragePort


def size_of(storage: StoragePort, key: str) -> int | None:
    """Return the byte size of one stored object, or ``None`` if undeterminable."""

    path = storage.local_path(key)
    if not path:
        return None
    try:
        return os.path.getsize(path)
    except OSError:
        return None


async def measure_prefix(
    storage: StoragePort, prefix: str, *, exclude: tuple[str, ...] = ()
) -> int:
    """Sum the byte sizes of all objects under ``prefix`` (excluding sub-prefixes).

    Keys whose path starts with any entry in ``exclude`` are skipped (used to keep
    nested namespaces - e.g. export packages within optimization - from being
    double-counted).

    The per-object ``stat`` loop is run on a worker thread so summing a large
    storage tree never blocks the event loop.
    """

    keys = await storage.list_keys(prefix)

    def _sum() -> int:
        total = 0
        for key in keys:
            if any(key.startswith(ex) for ex in exclude):
                continue
            size = size_of(storage, key)
            if size is not None:
                total += size
        return total

    return await asyncio.to_thread(_sum)

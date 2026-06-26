"""Tests for the local storage adapter (verifies the storage contract works)."""

from __future__ import annotations

from pathlib import Path

import pytest

from olympus.data.storage.local import LocalStorage
from olympus.platform.errors import StorageError


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


async def test_put_get_roundtrip(storage: LocalStorage) -> None:
    """An object can be written and read back identically."""

    meta = await storage.put("projects/p1/source.txt", b"hello", content_type="text/plain")
    assert meta.size_bytes == 5
    assert await storage.get("projects/p1/source.txt") == b"hello"


async def test_exists_and_delete(storage: LocalStorage) -> None:
    """Existence and idempotent deletion behave correctly."""

    await storage.put("a/b.bin", b"x")
    assert await storage.exists("a/b.bin") is True
    await storage.delete("a/b.bin")
    assert await storage.exists("a/b.bin") is False
    # Deleting a missing key is a no-op (idempotent).
    await storage.delete("a/b.bin")


async def test_get_missing_raises_storage_error(storage: LocalStorage) -> None:
    """Reading a missing key raises the single, normalised storage error."""

    with pytest.raises(StorageError):
        await storage.get("does/not/exist.bin")


async def test_path_traversal_is_blocked(storage: LocalStorage) -> None:
    """Keys cannot escape the storage root."""

    with pytest.raises(StorageError):
        await storage.get("../../etc/passwd")

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



async def test_sibling_prefix_key_is_blocked(tmp_path: Path) -> None:
    """A key resolving to a sibling dir that shares the root's name prefix is
    rejected. The old ``startswith`` check would have allowed e.g. ``<root>_evil``.
    """

    storage = LocalStorage(root=str(tmp_path / "store"))
    sibling_key = f"../{(tmp_path / 'store').name}_evil/secret.txt"
    with pytest.raises(StorageError):
        await storage.put(sibling_key, b"x")
    with pytest.raises(StorageError):
        await storage.get(sibling_key)


async def test_root_itself_is_allowed_and_nested_keys_resolve(tmp_path: Path) -> None:
    """A normal nested key resolves under the root and round-trips."""

    storage = LocalStorage(root=str(tmp_path))
    await storage.put("deep/nested/key.bin", b"ok")
    assert await storage.get("deep/nested/key.bin") == b"ok"



async def test_delete_prunes_empty_parent_dirs_but_preserves_siblings(tmp_path: Path) -> None:
    """Deleting all objects under a project prunes its now-empty directories,
    without removing sibling projects' directories or the root."""

    storage = LocalStorage(root=str(tmp_path))
    await storage.put("analysis/p1/stages/s1.json", b"{}")
    await storage.put("analysis/p1/index.json", b"{}")
    await storage.put("analysis/p2/index.json", b"{}")  # sibling project

    await storage.delete("analysis/p1/stages/s1.json")
    await storage.delete("analysis/p1/index.json")

    assert not (tmp_path / "analysis" / "p1").exists()  # pruned
    assert (tmp_path / "analysis" / "p2" / "index.json").exists()  # sibling kept
    assert tmp_path.exists()  # root never removed

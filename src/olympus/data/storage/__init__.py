"""Storage adapters implementing :class:`olympus.domain.contracts.StoragePort`."""

from olympus.data.storage.factory import build_storage
from olympus.data.storage.local import LocalStorage

__all__ = ["LocalStorage", "build_storage"]

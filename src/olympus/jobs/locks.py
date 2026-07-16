"""Filesystem leases used by the local durable Workflow Engine."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from olympus.utils import utc_now


@dataclass(frozen=True, slots=True)
class JobLease:
    key: str
    owner: str
    acquired_at: datetime
    heartbeat_at: datetime

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> JobLease:
        return cls(
            key=str(payload.get("key") or ""),
            owner=str(payload.get("owner") or ""),
            acquired_at=_datetime(payload.get("acquired_at")),
            heartbeat_at=_datetime(payload.get("heartbeat_at")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "owner": self.owner,
            "acquired_at": self.acquired_at.isoformat(),
            "heartbeat_at": self.heartbeat_at.isoformat(),
        }


class LocalJobLockManager:
    """Atomic lock-directory leases that work on local Windows filesystems."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def try_acquire(
        self,
        key: str,
        owner: str,
        *,
        stale_after_seconds: float,
    ) -> bool:
        lock_dir = self._lock_dir(key)
        now = utc_now()
        try:
            lock_dir.mkdir()
        except FileExistsError:
            lease = self.read(key)
            if lease is not None and lease.owner == owner:
                self.heartbeat(key, owner)
                return True
            if lease is None or self._is_stale(lease, now, stale_after_seconds):
                self.force_release(key)
                try:
                    lock_dir.mkdir()
                except FileExistsError:
                    return False
            else:
                return False
        lease = JobLease(key=key, owner=owner, acquired_at=now, heartbeat_at=now)
        _atomic_json(lock_dir / "owner.json", lease.to_dict())
        return True

    def heartbeat(self, key: str, owner: str) -> bool:
        lease = self.read(key)
        if lease is None or lease.owner != owner:
            return False
        updated = JobLease(
            key=lease.key,
            owner=lease.owner,
            acquired_at=lease.acquired_at,
            heartbeat_at=utc_now(),
        )
        _atomic_json(self._lock_dir(key) / "owner.json", updated.to_dict())
        return True

    def release(self, key: str, owner: str) -> bool:
        lease = self.read(key)
        if lease is None:
            return True
        if lease.owner != owner:
            return False
        self.force_release(key)
        return True

    def force_release(self, key: str) -> None:
        lock_dir = self._lock_dir(key)
        if not lock_dir.exists():
            return
        tombstone = lock_dir.with_name(f"{lock_dir.name}.stale-{os.getpid()}-{time.time_ns()}")
        try:
            os.replace(lock_dir, tombstone)
        except (FileNotFoundError, PermissionError):
            return
        shutil.rmtree(tombstone, ignore_errors=True)

    def read(self, key: str) -> JobLease | None:
        path = self._lock_dir(key) / "owner.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        return JobLease.from_dict(payload) if isinstance(payload, dict) else None

    def recover_stale(self, *, stale_after_seconds: float) -> list[str]:
        recovered: list[str] = []
        now = utc_now()
        for lock_dir in self.root.glob("*.lock"):
            try:
                payload = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
                lease = JobLease.from_dict(payload)
            except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
                lease = None
            if lease is None or self._is_stale(lease, now, stale_after_seconds):
                key = lease.key if lease is not None else lock_dir.name
                if lease is not None:
                    self.force_release(lease.key)
                else:
                    shutil.rmtree(lock_dir, ignore_errors=True)
                recovered.append(key)
        return recovered

    def _lock_dir(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.lock"

    @staticmethod
    def _is_stale(lease: JobLease, now: datetime, stale_after_seconds: float) -> bool:
        return now - lease.heartbeat_at > timedelta(seconds=max(0.0, stale_after_seconds))


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _datetime(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return utc_now()

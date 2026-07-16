"""Indexed local JSON mirror for durable Workflow Engine jobs."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from olympus.jobs.contracts import ACTIVE_JOB_STATUSES, DURABLE_JOB_SCHEMA_VERSION
from olympus.jobs.locks import LocalJobLockManager
from olympus.utils import utc_now

_INTERNAL_ACTIVE = {"pending", "ready", "running", "paused"}
_SECRET_TOKENS = ("password", "secret", "token", "cookie", "authorization", "api_key")


class DurableJobStoreError(RuntimeError):
    """A durable job file exists but cannot be read safely."""


class LocalDurableJobStore:
    """Atomic local job documents plus rebuildable queue/project indexes."""

    def __init__(self, root: str | Path, *, max_logs_tail_chars: int = 8000) -> None:
        self.root = Path(root).resolve()
        self.jobs_dir = self.root / "jobs"
        self.indexes_dir = self.root / "indexes"
        self.logs_dir = self.root / "logs"
        self.reports_dir = self.root / "reports"
        self.locks = LocalJobLockManager(self.root / "locks")
        self.max_logs_tail_chars = max(100, max_logs_tail_chars)
        self._mutex = threading.RLock()
        for directory in (
            self.jobs_dir,
            self.indexes_dir,
            self.logs_dir,
            self.reports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._ensure_indexes()

    def upsert(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._mutex:
            clean = self._normalize(payload)
            _atomic_json(self._job_path(clean["job_id"]), clean)
            self.rebuild_indexes()
            return clean

    def get(self, job_id: str) -> dict[str, Any] | None:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DurableJobStoreError(f"Stored durable job '{job_id}' is corrupt.") from exc
        if not isinstance(payload, dict):
            raise DurableJobStoreError(f"Stored durable job '{job_id}' is invalid.")
        return payload

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        corrupt: list[str] = []
        for path in sorted(self.jobs_dir.glob("job_*.json")):
            job_id = path.stem.removeprefix("job_")
            try:
                job = self.get(job_id)
            except DurableJobStoreError:
                corrupt.append(path.name)
                continue
            if job is not None:
                jobs.append(job)
        jobs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        if corrupt:
            _atomic_json(
                self.reports_dir / "corrupt_jobs.json",
                {"detected_at": utc_now().isoformat(), "files": corrupt},
            )
        return jobs

    def list_by_project(self, project_id: str) -> list[dict[str, Any]]:
        index = self._read_index("by_project.json", {})
        job_ids = index.get(project_id, []) if isinstance(index, dict) else []
        jobs: list[dict[str, Any]] = []
        for job_id in job_ids if isinstance(job_ids, list) else []:
            try:
                job = self.get(str(job_id))
            except DurableJobStoreError:
                continue
            if job is not None:
                jobs.append(job)
        return jobs

    def find_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        index = self._read_index("idempotency.json", {})
        job_id = index.get(idempotency_key) if isinstance(index, dict) else None
        return self.get(str(job_id)) if job_id else None

    def delete(self, job_id: str) -> None:
        with self._mutex:
            self._job_path(job_id).unlink(missing_ok=True)
            self.rebuild_indexes()

    def rebuild_indexes(self) -> dict[str, Any]:
        jobs = self.list_jobs()
        by_project: dict[str, list[str]] = {}
        idempotency: dict[str, str] = {}
        queued: list[dict[str, Any]] = []
        running: list[str] = []
        for job in jobs:
            job_id = str(job["job_id"])
            project_id = str(job.get("project_id") or "")
            if project_id:
                by_project.setdefault(project_id, []).append(job_id)
            key = job.get("idempotency_key")
            if isinstance(key, str) and key:
                idempotency[key] = job_id
            status = str(job.get("durable_status") or job.get("status") or "")
            if status in ACTIVE_JOB_STATUSES | _INTERNAL_ACTIVE:
                queued.append(
                    {
                        "job_id": job_id,
                        "priority": int(job.get("priority") or 50),
                        "created_at": job.get("created_at"),
                    }
                )
            if status == "running":
                running.append(job_id)
        queued.sort(key=lambda item: (-item["priority"], str(item["created_at"] or "")))
        indexes: dict[str, Any] = {
            "by_project": by_project,
            "idempotency": idempotency,
            "queue": [item["job_id"] for item in queued],
            "running": running,
        }
        _atomic_json(self.indexes_dir / "by_project.json", by_project)
        _atomic_json(self.indexes_dir / "idempotency.json", idempotency)
        _atomic_json(self.indexes_dir / "queue.json", indexes["queue"])
        _atomic_json(self.indexes_dir / "running.json", running)
        return indexes

    def cleanup(self, *, completed_after_days: int, failed_after_days: int) -> list[str]:
        now = utc_now()
        removed: list[str] = []
        for job in self.list_jobs():
            status = str(job.get("durable_status") or job.get("status") or "")
            if status not in {"completed", "canceled", "failed", "blocked"}:
                continue
            age_days = (
                completed_after_days
                if status in {"completed", "canceled"}
                else failed_after_days
            )
            updated = _parse_datetime(job.get("updated_at"))
            if updated is None or now - updated <= timedelta(days=max(0, age_days)):
                continue
            job_id = str(job["job_id"])
            self._job_path(job_id).unlink(missing_ok=True)
            removed.append(job_id)
        if removed:
            self.rebuild_indexes()
        return removed

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        clean = cast(dict[str, Any], _sanitize(payload))
        job_id = str(clean.get("job_id") or clean.get("workflow_id") or "").strip()
        if not job_id:
            raise ValueError("Durable job payload requires job_id or workflow_id.")
        clean["job_id"] = job_id
        clean.setdefault("schema_version", DURABLE_JOB_SCHEMA_VERSION)
        diagnostics = clean.get("diagnostics")
        if isinstance(diagnostics, dict) and isinstance(diagnostics.get("logs_tail"), str):
            diagnostics["logs_tail"] = diagnostics["logs_tail"][-self.max_logs_tail_chars :]
        return clean

    def _job_path(self, job_id: str) -> Path:
        safe = "".join(char for char in job_id if char.isalnum() or char in {"-", "_"})
        if not safe or safe != job_id:
            raise ValueError("Invalid durable job id.")
        return self.jobs_dir / f"job_{safe}.json"

    def _read_index(self, filename: str, fallback: Any) -> Any:
        try:
            return json.loads((self.indexes_dir / filename).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return fallback

    def _ensure_indexes(self) -> None:
        names = ("by_project.json", "idempotency.json", "queue.json", "running.json")
        if any(not (self.indexes_dir / name).exists() for name in names):
            self.rebuild_indexes()


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if not any(token in str(key).lower() for token in _SECRET_TOKENS)
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _atomic_json(path: Path, payload: Any) -> None:
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


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

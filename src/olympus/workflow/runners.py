"""Engine runners - the only bridge from orchestration to real engine work.

A runner drives one existing engine (through its unchanged service) to a genuine
terminal state and reports it. It never simulates work and never fabricates
progress: it calls the service's ``start`` (which is idempotent and resumable),
waits for the service to stop running, then reads the engine's *real* persisted
status and maps it to a job outcome.

Because ``start`` is idempotent, a runner coexists with the engines' own
completion chaining: if an engine already finished (because an upstream engine
chained into it), the runner simply observes the completed state without
re-running it. This makes the Workflow Engine the coordinator without bypassing
or duplicating any engine's work.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.workflow import EngineRunner, EngineRunResult
from olympus.domain.entities.project import Project
from olympus.domain.entities.workflow import Job
from olympus.platform.logging import get_logger

log = get_logger(__name__)

StartFn = Callable[[Project], Awaitable[object]]
IsRunningFn = Callable[[str], bool]
StatusFn = Callable[[str], Awaitable[str | None]]
CancelFn = Callable[[str], Awaitable[object]]

_TERMINAL = {"completed", "failed", "cancelled"}


class UploadRunner(EngineRunner):
    """Validates that the uploaded source asset really exists (no engine to run)."""

    engine = "upload"

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def run(self, project: Project, job: Job) -> EngineRunResult:
        job.log(f"verifying source asset {project.storage_key}")
        present = await self._storage.exists(project.storage_key)
        if not present:
            return EngineRunResult(
                status="failed",
                error="source asset is missing from storage",
                summary={"storage_key": project.storage_key, "present": False},
            )
        job.log("source asset present")
        return EngineRunResult(
            status="completed",
            summary={"storage_key": project.storage_key, "present": True},
        )


class ServiceEngineRunner(EngineRunner):
    """Drives an engine via its service: start -> await -> read real status."""

    def __init__(
        self,
        engine: str,
        *,
        start: StartFn,
        is_running: IsRunningFn,
        status: StatusFn,
        poll_interval: float = 0.05,
        timeout_seconds: float = 600.0,
        cancel: CancelFn | None = None,
    ) -> None:
        self.engine = engine
        self._start = start
        self._is_running = is_running
        self._status = status
        self._poll = poll_interval
        self._timeout = timeout_seconds
        self._cancel = cancel

    async def run(self, project: Project, job: Job) -> EngineRunResult:
        job.log(f"starting {self.engine} engine")
        await self._start(project)
        waited = 0.0
        # Give the background task a tick to register as running.
        await asyncio.sleep(0)
        while self._is_running(project.id):
            if job.cancellation_requested and self._cancel is not None:
                job.log("cooperative cancellation requested")
                await self._cancel(project.id)
            await asyncio.sleep(self._poll)
            waited += self._poll
            if waited >= self._timeout:
                return EngineRunResult(
                    status="failed",
                    error=f"{self.engine} did not finish within {self._timeout:.0f}s",
                )
        raw = await self._status(project.id)
        mapped = raw if raw in _TERMINAL else "failed"
        job.log(f"{self.engine} engine finished with status: {raw or 'no-record'}")
        error = None
        if mapped != "completed":
            error = (
                f"{self.engine} did not persist a terminal status"
                if raw not in _TERMINAL
                else f"{self.engine} status: {raw}"
            )
        return EngineRunResult(
            status=mapped,
            summary={"engine_status": raw},
            error=error,
        )


def _status_getter(get: Callable[[str], Awaitable[object]]) -> StatusFn:
    """Wrap an engine ``get_*`` accessor into a status-string function."""

    async def _status(project_id: str) -> str | None:
        entity = await get(project_id)
        if entity is None:
            return None
        status = getattr(entity, "status", None)
        return getattr(status, "value", None) if status is not None else None

    return _status


def build_service_runner(
    engine: str,
    service: object,
    *,
    getter: str,
    poll_interval: float = 0.05,
    timeout_seconds: float = 600.0,
) -> ServiceEngineRunner:
    """Build a :class:`ServiceEngineRunner` from an engine service + its getter.

    ``service`` must expose ``start(project)``, ``is_running(project_id)`` and the
    named ``getter(project_id)`` returning an entity with a ``.status`` enum.
    """

    cancel = getattr(service, "cancel", None)
    return ServiceEngineRunner(
        engine,
        start=lambda project: service.start(project),  # type: ignore[attr-defined]
        is_running=lambda pid: service.is_running(pid),  # type: ignore[attr-defined]
        status=_status_getter(getattr(service, getter)),
        poll_interval=poll_interval,
        timeout_seconds=timeout_seconds,
        cancel=cast(CancelFn, cancel) if callable(cancel) else None,
    )

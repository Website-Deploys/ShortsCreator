"""Shared, concurrency-safe coordination for engine background runs.

Every engine service (Cognitive, Story, Virality, Clip Planner, Editing,
Rendering, Optimization) tracks its in-flight per-project run in a process-wide
``_RUNS`` registry and starts work via ``start(project, restart=...)``. That
``start`` performs a check-then-act on the registry, which is a classic race if
left unserialized:

* Two concurrent ``start(restart=False)`` calls (duplicate API requests, a
  double-click, or a workflow runner racing an upstream engine's completion
  chain) can both observe "no run in flight" and each spawn a pipeline, running
  the same engine twice for one project - double storage writes, double
  downstream chaining, wasted compute.
* ``start(restart=True)`` (used by every ``.../run`` endpoint) can overwrite the
  registry entry while the previous run is still executing, orphaning a task
  that is no longer referenced - so ``cancel``/``delete`` can no longer stop it,
  and it can resurrect artifacts after a delete.

:func:`begin_or_reuse_run` centralizes the fix once: it serializes the whole
critical section per (engine, project) with :func:`engine_start_lock`, reuses an
existing run when one is genuinely in flight (``restart=False``), and on
``restart`` cancels *and drains* the prior run before registering and spawning
the replacement - so two pipelines never run concurrently for one project and a
run is never orphaned.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

from olympus.platform.logging import get_logger
from olympus.utils import engine_start_lock

log = get_logger(__name__)


class RunLike(Protocol):
    """Structural type for the per-service ``_Run`` dataclasses."""

    cancel_event: asyncio.Event
    task: asyncio.Task[None] | None


R = TypeVar("R", bound=RunLike)
E = TypeVar("E")

# Generous bound for a cooperatively-cancelled run to reach a cancel checkpoint
# (the pipelines check their cancel_event between stages). Mirrors the drain
# timeout used by the services' delete() paths.
_DRAIN_TIMEOUT_SECONDS = 10.0


async def begin_or_reuse_run(
    *,
    scope: str,
    project_id: str,
    runs: dict[str, R],
    make_run: Callable[[], R],
    loader: Callable[[], Awaitable[E | None]],
    spawn: Callable[[R], asyncio.Task[None]],
    restart: bool,
    drain_timeout: float = _DRAIN_TIMEOUT_SECONDS,
) -> tuple[E | None, R | None]:
    """Atomically decide whether to reuse an in-flight run or start a fresh one.

    Returns ``(existing_entity, None)`` when an in-flight run is reused (the
    caller should return ``existing_entity`` directly), or ``(None, run)`` when a
    new run was registered and its task spawned (the caller proceeds with its
    post-start bookkeeping). Exactly one element of the tuple is non-None.

    The entire decision-register-spawn sequence runs under the per-(scope,
    project) start lock, and ``spawn`` is invoked synchronously (no ``await``
    between registry insertion and task creation), so no concurrent ``start``
    can observe a half-initialized registry entry.
    """

    async with engine_start_lock(scope, project_id):
        existing = runs.get(project_id)
        in_flight = existing is not None and existing.task is not None and not existing.task.done()
        if in_flight and existing is not None:
            if not restart:
                loaded = await loader()
                if loaded is not None:
                    return loaded, None
                # No persisted entity yet despite an in-flight run: fall through
                # and let the existing run continue; do not spawn a duplicate.
                return None, existing
            # restart: cancel and drain the prior run before replacing it, so two
            # pipelines never execute concurrently and no task is orphaned.
            existing.cancel_event.set()
            if existing.task is not None:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(existing.task), timeout=drain_timeout
                    )
                except Exception as exc:
                    # TimeoutError or the prior run's own error: best-effort drain,
                    # restart proceeds. CancelledError (the caller being cancelled)
                    # is a BaseException and intentionally propagates.
                    log.warning(
                        "engine_restart_drain_incomplete",
                        scope=scope,
                        project_id=project_id,
                        error=str(exc),
                    )

        run = make_run()
        runs[project_id] = run
        run.task = spawn(run)  # synchronous: no await between register and spawn
        return None, run

"""Process-wide, per-key async locks.

A tiny utility for serializing concurrent read-modify-write operations on the
same logical record (e.g. a project document) within a single process. Without
this, two coroutines that each load-mutate-save the same record can clobber one
another (a lost update): the Cognitive Engine's background status updates and a
user's thumbnail/rename can race on the same project.

This is intentionally a single-process primitive (it matches the MVP's
single-process storage). When a distributed datastore with its own concurrency
control is introduced, these locks become unnecessary and can be removed without
touching call sites' logic.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

_project_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_start_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def project_write_lock(project_id: str) -> asyncio.Lock:
    """Return the shared write lock for a project id.

    Hold this lock around any load-mutate-save of a project document so that
    concurrent writers serialize and each observes the latest persisted state.
    """

    return _project_locks[project_id]


def engine_start_lock(scope: str, project_id: str) -> asyncio.Lock:
    """Return the per-(engine, project) lock that serializes ``start()``.

    An engine service's ``start()`` performs a check-then-act on its in-flight
    run registry (decide whether a run already exists, then register a new one
    and spawn its task). Without serialization, two concurrent ``start()`` calls
    for the same project can both pass the "no run yet" check and each spawn a
    pipeline (duplicate execution), and a ``restart`` can overwrite the registry
    without cancelling the prior run (orphaning an uncancellable task). Holding
    this lock around the whole critical section makes that sequence atomic.

    It is intentionally distinct from :func:`project_write_lock` so a service may
    update the project document (which takes the write lock) while holding the
    start lock, without deadlocking on a non-reentrant lock.
    """

    return _start_locks[f"{scope}:{project_id}"]

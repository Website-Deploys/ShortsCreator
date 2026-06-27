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


def project_write_lock(project_id: str) -> asyncio.Lock:
    """Return the shared write lock for a project id.

    Hold this lock around any load-mutate-save of a project document so that
    concurrent writers serialize and each observes the latest persisted state.
    """

    return _project_locks[project_id]

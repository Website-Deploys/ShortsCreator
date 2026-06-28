"""Task registry.

Business tasks (the pipeline stages: ingest, transcribe, analyze, select, plan,
caption, render, export) are added here in later milestones. The foundation
provides a single ``ping`` task so the queue path can be verified end-to-end
(enqueue -> worker -> result) before any business logic exists.
"""

from __future__ import annotations

from olympus.platform.logging import get_logger
from olympus.services.queue.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="olympus.ping")  # type: ignore[untyped-decorator]  # celery has no stubs
def ping() -> str:
    """A trivial health task used to verify the queue/worker path is wired up."""

    log.info("ping_task_executed")
    return "pong"

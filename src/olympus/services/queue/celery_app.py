"""Celery application configuration.

Defines the process-wide Celery app used to dispatch and execute background
work. Per the architecture, the pipeline is decomposed into typed queues by
work kind; the foundation declares the queue *names* and routing so workers can
subscribe to the right ones, even though the business tasks themselves are added
in later milestones.

Configuration is conservative and reliability-oriented:
- ``task_acks_late`` + ``task_reject_on_worker_lost``: a job is only acked after
  it completes, so a crashed worker's job is redelivered (safe because tasks are
  designed to be idempotent).
- ``worker_prefetch_multiplier = 1``: fair dispatch so one long render cannot
  hoard prefetched work.
- a hard ``task_time_limit``: prevents runaway jobs (the Producer's budget).

Importing this module does not connect to the broker; connection is lazy.
"""

from __future__ import annotations

from celery import Celery

from olympus.platform.config import get_settings
from olympus.platform.logging import configure_logging

# Logical queue names, one per kind of work (see the pipeline state machine).
QUEUE_DEFAULT = "default"
QUEUE_INGEST = "ingest"
QUEUE_TRANSCRIBE = "transcribe"
QUEUE_ANALYZE = "analyze"
QUEUE_RENDER = "render"


def _create_celery_app() -> Celery:
    settings = get_settings()
    configure_logging(settings)

    app = Celery("olympus")
    app.conf.update(
        broker_url=settings.queue.broker_url,
        result_backend=settings.queue.result_backend,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # Reliability settings.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_time_limit=settings.queue.task_time_limit,
        # Default queue; specific tasks route to typed queues via task options.
        task_default_queue=QUEUE_DEFAULT,
    )
    # Auto-discover task modules registered under this package in later
    # milestones (e.g. olympus.services.queue.tasks).
    app.autodiscover_tasks(packages=["olympus.services.queue"])
    return app


# The process-wide Celery application instance.
celery_app = _create_celery_app()

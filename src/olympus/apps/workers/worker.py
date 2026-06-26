"""Celery worker entry point.

Exposes the ``celery_app`` that the Celery CLI runs, e.g.::

    celery -A olympus.apps.workers.worker:celery_app worker --queues default,ingest

Importing this module registers the task modules (so the worker knows the tasks)
and re-exports the shared Celery application configured in the queue service.
"""

from __future__ import annotations

# Importing the tasks module registers tasks against the Celery app.
from olympus.services.queue import celery_app
from olympus.services.queue import tasks as _tasks  # noqa: F401  (registers tasks)

__all__ = ["celery_app"]

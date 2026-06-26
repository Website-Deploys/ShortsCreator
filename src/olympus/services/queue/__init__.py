"""Queue infrastructure (Celery)."""

from olympus.services.queue.celery_app import celery_app

__all__ = ["celery_app"]

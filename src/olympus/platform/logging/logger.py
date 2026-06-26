"""Structured logging setup built on ``structlog``.

Every log line is structured (key/value) and carries context, enabling the
per-job traceability the architecture requires (correlation ids flow through
the ``request_id`` / ``job_id`` keys). In development logs render as readable
console output; in production they render as JSON for ingestion by the
observability platform.

Usage::

    from olympus.platform.logging import get_logger

    log = get_logger(__name__)
    log.info("video_ingested", project_id=project_id, duration_s=duration)

Loggers are bound, structured, and cheap to create; obtain one per module.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from olympus.platform.config import Settings, get_settings

# Sentinel so we only configure the logging pipeline once per process.
_CONFIGURED = False


def configure_logging(settings: Settings | None = None) -> None:
    """Configure the global logging pipeline.

    Idempotent: safe to call multiple times (only the first call applies).
    Called once at application/worker startup.

    Args:
        settings: Optional settings override; defaults to the cached settings.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = settings or get_settings()
    level = logging.getLevelName(settings.log_level.upper())

    # Route the stdlib logging through structlog so third-party libraries
    # (uvicorn, sqlalchemy, celery) share the same structured output.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format.value == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound to ``name`` (typically ``__name__``)."""

    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """Bind key/value context to the current execution context.

    Bound values (e.g. ``request_id``) are automatically attached to every log
    line emitted within the same context, giving correlation for free.
    """

    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all context-local bound values (call at the end of a request)."""

    structlog.contextvars.clear_contextvars()

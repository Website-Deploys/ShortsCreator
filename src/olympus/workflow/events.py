"""In-process event bus for the Workflow Engine.

A minimal, real publish/subscribe bus: subscribers are async callables invoked
for every published event. Handler errors are isolated so one faulty subscriber
never breaks orchestration or another subscriber. This is the seam future
plugins (notifications, metrics exporters, webhooks) attach to; a distributed
bus can replace it behind :class:`EventBus` without changing callers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from olympus.domain.contracts.workflow import EventBus
from olympus.domain.entities.workflow import WorkflowEvent
from olympus.platform.logging import get_logger

log = get_logger(__name__)

Handler = Callable[[WorkflowEvent], Awaitable[None]]


class InMemoryEventBus(EventBus):
    """A simple async pub/sub bus with isolated handler execution."""

    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def publish(self, event: WorkflowEvent) -> None:
        for handler in list(self._handlers):
            try:
                await handler(event)
            except Exception as exc:  # one bad subscriber must not break the rest
                log.warning("event_handler_error", event=event.type.value, error=str(exc))

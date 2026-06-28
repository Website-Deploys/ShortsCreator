"""Tests for the Workflow Engine's in-process event bus.

The bus must isolate subscriber failures: one faulty handler can never break
``publish`` or prevent other handlers from running. (Regression: the error path
used to pass ``event=`` to structlog, which collided with the positional event
name and raised TypeError, defeating the isolation it was meant to provide.)
"""

from __future__ import annotations

from olympus.domain.entities.workflow import EventType, WorkflowEvent
from olympus.utils import utc_now
from olympus.workflow.events import InMemoryEventBus


def _event() -> WorkflowEvent:
    return WorkflowEvent(ts=utc_now(), type=EventType.JOB_FAILED, message="boom")


async def test_publish_isolates_a_failing_subscriber() -> None:
    bus = InMemoryEventBus()
    ran: list[str] = []

    async def bad(_event: WorkflowEvent) -> None:
        raise RuntimeError("subscriber blew up")

    async def good(event: WorkflowEvent) -> None:
        ran.append(event.message)

    bus.subscribe(bad)
    bus.subscribe(good)

    # Must not raise, and the healthy subscriber must still run.
    await bus.publish(_event())
    assert ran == ["boom"]


async def test_publish_with_no_subscribers_is_a_noop() -> None:
    bus = InMemoryEventBus()
    await bus.publish(_event())  # must not raise


async def test_publish_delivers_to_all_healthy_subscribers() -> None:
    bus = InMemoryEventBus()
    seen: list[int] = []

    for i in range(3):
        async def handler(_e: WorkflowEvent, n: int = i) -> None:
            seen.append(n)

        bus.subscribe(handler)

    await bus.publish(_event())
    assert sorted(seen) == [0, 1, 2]

"""Tests for :mod:`athanore.events.bus`.

Three properties matter here and each has a test that fails loudly when it
stops holding: a subscription receives exactly the names its patterns
select, a subscriber that stops draining loses events and is *told* so
rather than blocking anyone, and :meth:`EventBus.publish` never awaits.

The last one is the one worth reading. ``publish`` is called with the
store's writer lock just released and is a plain function, so the way to
prove it cannot suspend is to run a ticker task alongside it and assert
the ticker got no turn: any ``await`` inside the fan-out — including the
"obvious fix" of awaiting ``queue.put`` on a full queue — hands control to
the loop and the assertion fails.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from athanore.events.bus import DEFAULT_MAXSIZE, EventBus, Subscription
from athanore.events.model import Event
from athanore.events.names import EventName

CREATED = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def event(name: str | EventName, **data: object) -> Event:
    return Event(name=str(name), data=dict(data), created=CREATED)


def drain(subscription: Subscription) -> list[str]:
    """Every event waiting on ``subscription``, by name, oldest first."""
    names: list[str] = []
    while not subscription.queue.empty():
        names.append(subscription.queue.get_nowait().name)
    return names


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------


async def test_a_pattern_selects_one_segment() -> None:
    bus = EventBus()
    subscription = bus.subscribe(["run.*"])

    bus.publish(event(EventName.run_created))
    bus.publish(event(EventName.task_started))

    assert drain(subscription) == [EventName.run_created]


async def test_several_patterns_are_a_union() -> None:
    bus = EventBus()
    subscription = bus.subscribe(["run.*", "engine.*"])

    bus.publish(event(EventName.run_failed))
    bus.publish(event(EventName.task_done))
    bus.publish(event(EventName.engine_recovered))

    assert drain(subscription) == [EventName.run_failed, EventName.engine_recovered]


async def test_no_patterns_selects_everything() -> None:
    bus = EventBus()
    subscription = bus.subscribe()

    bus.publish(event(EventName.run_created))
    bus.publish(event(EventName.task_started))
    bus.publish(event("plugin.demo.pinged"))

    assert drain(subscription) == [
        EventName.run_created,
        EventName.task_started,
        "plugin.demo.pinged",
    ]


async def test_a_star_does_not_span_a_dot() -> None:
    """``names.matches`` is per segment, so ``plugin.*`` is not a prefix."""
    bus = EventBus()
    narrow = bus.subscribe(["plugin.*"])
    wide = bus.subscribe(["plugin.*.*"])

    bus.publish(event("plugin.demo.pinged"))

    assert drain(narrow) == []
    assert drain(wide) == ["plugin.demo.pinged"]


async def test_each_subscription_gets_its_own_copy_of_the_selection() -> None:
    bus = EventBus()
    first = bus.subscribe(["run.*"])
    second = bus.subscribe(["run.*"])
    published = event(EventName.run_created)

    bus.publish(published)

    assert first.queue.get_nowait() is published
    assert second.queue.get_nowait() is published


# --------------------------------------------------------------------------
# Overflow
# --------------------------------------------------------------------------


async def test_a_full_queue_sets_overflowed_and_drops_the_new_event() -> None:
    bus = EventBus()
    subscription = bus.subscribe(maxsize=1)

    bus.publish(event(EventName.run_created))
    assert subscription.overflowed is False

    bus.publish(event(EventName.run_started))

    assert subscription.overflowed is True
    assert subscription.queue.qsize() == 1
    # The oldest event survives; it is the new one that is dropped, so the
    # cursor a client already has stays usable up to the hole.
    assert drain(subscription) == [EventName.run_created]


async def test_overflow_is_per_subscription() -> None:
    bus = EventBus()
    stalled = bus.subscribe(maxsize=1)
    healthy = bus.subscribe(maxsize=10)

    bus.publish(event(EventName.run_created))
    bus.publish(event(EventName.run_started))

    assert stalled.overflowed is True
    assert healthy.overflowed is False
    assert drain(healthy) == [EventName.run_created, EventName.run_started]


async def test_overflowed_stays_set_once_the_queue_is_drained() -> None:
    """The flag is a hole in the stream, not a level: SSE must still resync."""
    bus = EventBus()
    subscription = bus.subscribe(maxsize=1)

    bus.publish(event(EventName.run_created))
    bus.publish(event(EventName.run_started))
    drain(subscription)
    bus.publish(event(EventName.run_completed))

    assert subscription.overflowed is True
    assert drain(subscription) == [EventName.run_completed]


async def test_publish_never_awaits_a_subscriber_that_never_drains() -> None:
    """The property the drop exists for: a stalled reader cannot stall a
    commit. A ``publish`` that blocked on a full queue would give the
    ticker a turn."""
    bus = EventBus()
    subscription = bus.subscribe(maxsize=1)
    bus.publish(event(EventName.run_created))
    assert subscription.queue.full()

    turns = 0

    async def ticker() -> None:
        nonlocal turns
        while True:
            turns += 1
            await asyncio.sleep(0)

    running = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    before = turns

    for _ in range(1000):
        bus.publish(event(EventName.run_started))

    assert turns == before
    assert subscription.overflowed is True
    assert subscription.queue.qsize() == 1

    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------


async def test_close_stops_delivery_and_detaches_the_subscription() -> None:
    bus = EventBus()
    subscription = bus.subscribe(["run.*"])
    assert bus.subscriptions == (subscription,)

    subscription.close()
    bus.publish(event(EventName.run_created))

    assert subscription.closed is True
    assert bus.subscriptions == ()
    assert drain(subscription) == []


async def test_close_is_idempotent() -> None:
    bus = EventBus()
    subscription = bus.subscribe()

    subscription.close()
    subscription.close()

    assert bus.subscriptions == ()


async def test_closing_one_subscription_leaves_the_others() -> None:
    bus = EventBus()
    closed = bus.subscribe()
    open_ = bus.subscribe()

    closed.close()
    bus.publish(event(EventName.run_created))

    assert drain(closed) == []
    assert drain(open_) == [EventName.run_created]


async def test_the_default_queue_depth_is_the_documented_one() -> None:
    bus = EventBus()

    assert bus.subscribe().queue.maxsize == DEFAULT_MAXSIZE


# --------------------------------------------------------------------------
# wait_for
# --------------------------------------------------------------------------


async def test_wait_for_returns_the_first_matching_event() -> None:
    bus = EventBus()
    waiter = asyncio.create_task(bus.wait_for("run.*", timeout=5))
    await _subscribed(bus)

    first = event(EventName.run_created)
    bus.publish(event(EventName.task_started))
    bus.publish(first)
    bus.publish(event(EventName.run_started))

    assert await waiter is first


async def test_wait_for_skips_events_the_predicate_rejects() -> None:
    bus = EventBus()
    waiter = asyncio.create_task(
        bus.wait_for("run.*", lambda e: e.run_id == "wanted", timeout=5)
    )
    await _subscribed(bus)

    wanted = Event(
        name=EventName.run_started, run_id="wanted", data={}, created=CREATED
    )
    bus.publish(
        Event(name=EventName.run_started, run_id="other", data={}, created=CREATED)
    )
    bus.publish(wanted)

    assert await waiter is wanted


async def test_wait_for_raises_timeout_error() -> None:
    bus = EventBus()

    with pytest.raises(TimeoutError):
        await bus.wait_for("run.*", timeout=0.01)


async def test_wait_for_closes_its_subscription_on_every_exit() -> None:
    bus = EventBus()

    with pytest.raises(TimeoutError):
        await bus.wait_for("run.*", timeout=0.01)
    assert bus.subscriptions == ()

    waiter = asyncio.create_task(bus.wait_for("run.*", timeout=5))
    await _subscribed(bus)
    bus.publish(event(EventName.run_created))
    await waiter
    assert bus.subscriptions == ()

    cancelled = asyncio.create_task(bus.wait_for("run.*"))
    await _subscribed(bus)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert bus.subscriptions == ()


async def _subscribed(bus: EventBus) -> None:
    """Give a just-created `wait_for` task the turn it subscribes in.

    `wait_for` subscribes before it awaits anything, so one turn of the
    loop is enough and the assertion says so rather than spinning.
    """
    await asyncio.sleep(0)
    assert bus.subscriptions, "wait_for should subscribe before its first await"

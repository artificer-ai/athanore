"""Tests for :mod:`athanore.store.uow`.

The outbox exists so that "committed" and "published" are the same moment,
and these tests are written to catch the three ways that can be wrong: an
event published for a transaction that rolled back, an event published
*before* its row is readable, and an event published while the writer lock
is still held. The second is why
:func:`test_a_subscriber_sees_the_event_only_after_the_commit` counts the
rows from *inside* the subscriber rather than after the block — a
notification that arrives ahead of its data is a race the SSE endpoint
would only hit under load.

The ``store`` fixture comes from ``tests/store/conftest.py``, so every
test here runs against SQLite and, with the ``pg`` profile up, against
PostgreSQL too. The SQLite database is a temporary **file**: ``:memory:``
gives SQLAlchemy a pool holding a single connection, and half of what is
asserted here is that :meth:`Store.read` takes a different one from the
writer's.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.events.bus import EventBus
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.store.tables import events
from athanore.store.uow import Store, now

CREATED = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def event(name: str | EventName, **data: object) -> Event:
    return Event(name=str(name), data=dict(data), created=CREATED)


async def stored(store: Store) -> list[tuple[int, str]]:
    """Every row of ``events`` as ``(id, name)``, read on its own connection."""
    async with store.read() as conn:
        result = await conn.execute(
            select(events.c.id, events.c.name).order_by(events.c.id)
        )
        return [(row.id, row.name) for row in result]


async def count(store: Store) -> int:
    """How many rows another connection can see committed right now."""
    async with store.read() as conn:
        result = await conn.execute(select(func.count()).select_from(events))
        return int(result.scalar_one())


# --------------------------------------------------------------------------
# now()
# --------------------------------------------------------------------------


def test_now_is_aware_and_utc() -> None:
    stamp = now()

    assert stamp.tzinfo is not None
    assert stamp.utcoffset() == UTC.utcoffset(None)


# --------------------------------------------------------------------------
# Commit
# --------------------------------------------------------------------------


async def test_the_outbox_is_inserted_and_stamped_on_commit(store: Store) -> None:
    first, second = event(EventName.run_created), event(EventName.run_started)

    async with store.uow() as uow:
        uow.emit(first)
        uow.emit(second)
        assert first.id is None

    assert first.id is not None
    assert second.id is not None
    assert first.id < second.id
    assert await stored(store) == [
        (first.id, EventName.run_created),
        (second.id, EventName.run_started),
    ]


async def test_the_whole_envelope_is_written(store: Store) -> None:
    emitted = Event(
        name=EventName.task_done,
        run_id="01JRUN",
        task_id=7,
        data={"node": "build", "attempt": 1},
        created=CREATED,
    )

    async with store.uow() as uow:
        uow.emit(emitted)

    async with store.read() as conn:
        row = (await conn.execute(select(events))).one()
    assert (row.run_id, row.task_id, row.name) == ("01JRUN", 7, EventName.task_done)
    assert row.data == {"node": "build", "attempt": 1}
    # SQLite's ``DATETIME`` drops the offset on the way in and hands back a
    # naive value where PostgreSQL round-trips the aware one; writing UTC —
    # which is all `now()` ever produces — is what makes the two agree on
    # the instant rather than on a local wall clock.
    assert row.created.replace(tzinfo=UTC) == CREATED


async def test_work_done_on_the_connection_is_committed(store: Store) -> None:
    async with store.uow() as uow:
        await uow.conn.execute(
            events.insert().values(
                run_id=None,
                task_id=None,
                name=EventName.engine_recovered,
                data={},
                created=CREATED,
            )
        )

    assert [name for _, name in await stored(store)] == [EventName.engine_recovered]


async def test_two_sequential_uows_produce_ascending_ids(store: Store) -> None:
    ids: list[int] = []
    for index in range(4):
        emitted = event(EventName.log_appended, index=index)
        async with store.uow() as uow:
            uow.emit(emitted)
        assert emitted.id is not None
        ids.append(emitted.id)

    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


async def test_events_are_published_in_id_order(store: Store, bus: EventBus) -> None:
    subscription = bus.subscribe()
    emitted = [event(EventName.log_appended, index=index) for index in range(5)]

    async with store.uow() as uow:
        for one in emitted:
            uow.emit(one)

    published = [subscription.queue.get_nowait() for _ in range(len(emitted))]
    assert published == emitted
    ids: list[int] = []
    for one in published:
        assert one.id is not None
        ids.append(one.id)
    assert ids == sorted(ids)


async def test_an_empty_outbox_commits_and_publishes_nothing(
    store: Store, bus: EventBus
) -> None:
    subscription = bus.subscribe()

    async with store.uow() as uow:
        await uow.conn.execute(select(func.count()).select_from(events))

    assert subscription.queue.empty()
    assert await count(store) == 0


# --------------------------------------------------------------------------
# Rollback
# --------------------------------------------------------------------------


async def test_a_failing_uow_stores_nothing_and_publishes_nothing(
    store: Store, bus: EventBus
) -> None:
    subscription = bus.subscribe()
    emitted = event(EventName.run_created)

    with pytest.raises(RuntimeError, match="boom"):
        async with store.uow() as uow:
            uow.emit(emitted)
            await uow.conn.execute(
                events.insert().values(
                    run_id=None,
                    task_id=None,
                    name=EventName.run_started,
                    data={},
                    created=CREATED,
                )
            )
            raise RuntimeError("boom")

    assert emitted.id is None
    assert subscription.queue.empty()
    assert await count(store) == 0


async def test_a_failed_insert_leaves_no_event_carrying_an_id(
    store: Store, bus: EventBus
) -> None:
    """A stamped id names a row; a failed flush must leave none behind.

    The second event's ``created`` is not a datetime, so the insert of the
    outbox raises. Neither event may come out of the block carrying an id:
    a cursor into a hole is worse than no cursor.
    """

    subscription = bus.subscribe()
    good = event(EventName.run_created)
    bad = event(EventName.run_started)
    bad.created = "not a datetime"  # type: ignore[assignment]

    with pytest.raises(StatementError):
        async with store.uow() as uow:
            uow.emit(good)
            uow.emit(bad)

    assert good.id is None
    assert bad.id is None
    assert subscription.queue.empty()
    assert await count(store) == 0


async def test_the_writer_lock_is_released_after_a_failure(store: Store) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with store.uow():
            raise RuntimeError("boom")

    async with asyncio.timeout(5):
        async with store.uow() as uow:
            uow.emit(event(EventName.run_created))

    assert await count(store) == 1


async def test_the_outbox_does_not_survive_into_the_next_uow(
    store: Store, bus: EventBus
) -> None:
    subscription = bus.subscribe()

    with pytest.raises(RuntimeError, match="boom"):
        async with store.uow() as uow:
            uow.emit(event(EventName.run_created))
            raise RuntimeError("boom")

    async with store.uow() as uow:
        uow.emit(event(EventName.run_started))

    assert subscription.queue.get_nowait().name == EventName.run_started
    assert subscription.queue.empty()
    assert [name for _, name in await stored(store)] == [EventName.run_started]


async def test_a_cancelled_uow_rolls_back(store: Store, bus: EventBus) -> None:
    """Cancellation is an exception on the way out like any other."""

    subscription = bus.subscribe()

    async def write() -> None:
        async with store.uow() as uow:
            uow.emit(event(EventName.run_created))
            await asyncio.Event().wait()

    task = asyncio.create_task(write())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert subscription.queue.empty()
    assert await count(store) == 0
    # ...and the writer is free again.
    async with asyncio.timeout(5):
        async with store.uow():
            pass


# --------------------------------------------------------------------------
# Commit, unlock, then publish
# --------------------------------------------------------------------------


async def test_a_subscriber_sees_the_event_only_after_the_commit(
    store: Store, bus: EventBus
) -> None:
    subscription = bus.subscribe()

    async def observe() -> int:
        """How many rows are readable at the moment the event arrives?"""
        await subscription.queue.get()
        return await count(store)

    watcher = asyncio.create_task(observe())
    await asyncio.sleep(0)

    async with store.uow() as uow:
        uow.emit(event(EventName.run_created))
        # Emitted, not published, and not yet visible to another connection.
        assert subscription.queue.empty()
        assert await count(store) == 0

    async with asyncio.timeout(5):
        assert await watcher == 1


async def test_the_writer_lock_is_free_before_anything_is_published(
    engine: AsyncEngine,
) -> None:
    """Publishing under the lock would let a subscriber deadlock the writer.

    ``publish`` is synchronous, so the only vantage point from which the
    order is observable is inside it — hence the private lock. The
    property is 07's: commit, release, *then* fan out.
    """

    held: list[bool] = []

    class Watcher:
        def publish(self, event: Any, /) -> None:
            held.append(store._writer_lock.locked())

    store = Store(engine, Watcher())

    async with store.uow() as uow:
        uow.emit(event(EventName.run_created))
        assert store._writer_lock.locked()

    assert held == [False]


# --------------------------------------------------------------------------
# Ephemeral
# --------------------------------------------------------------------------


async def test_publish_ephemeral_reaches_the_bus_and_never_the_table(
    store: Store, bus: EventBus
) -> None:
    subscription = bus.subscribe(["task.*"])
    emitted = Event(
        name=EventName.task_stream,
        run_id="01JRUN",
        task_id=7,
        data={"seq_from": 1, "seq_to": 4},
        created=CREATED,
    )

    await store.publish_ephemeral(emitted)

    assert subscription.queue.get_nowait() is emitted
    assert emitted.id is None
    assert await count(store) == 0


async def test_publish_ephemeral_takes_no_writer_lock(store: Store) -> None:
    """A flush must not queue behind a commit; it stores nothing."""

    async with asyncio.timeout(5):
        async with store.uow() as uow:
            uow.emit(event(EventName.run_created))
            await store.publish_ephemeral(event(EventName.task_stream))


# --------------------------------------------------------------------------
# Concurrency
# --------------------------------------------------------------------------


async def test_two_concurrent_uows_serialise(store: Store) -> None:
    order: list[str] = []

    async def write(tag: str) -> None:
        async with store.uow() as uow:
            order.append(f"{tag} in")
            await asyncio.sleep(0.01)
            uow.emit(event(EventName.log_appended, tag=tag))
            order.append(f"{tag} out")

    async with asyncio.timeout(10):
        await asyncio.gather(write("a"), write("b"))

    assert order in (
        ["a in", "a out", "b in", "b out"],
        ["b in", "b out", "a in", "a out"],
    )
    assert await count(store) == 2


async def test_read_does_not_queue_behind_the_writer(store: Store) -> None:
    async with asyncio.timeout(5):
        async with store.uow() as uow:
            uow.emit(event(EventName.run_created))
            assert await count(store) == 0


async def test_reads_are_pooled_and_concurrent(store: Store) -> None:
    async with asyncio.timeout(5):
        counts = await asyncio.gather(*(count(store) for _ in range(4)))

    assert counts == [0, 0, 0, 0]


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------


async def test_the_connection_is_unreachable_outside_the_block(store: Store) -> None:
    async with store.uow() as uow:
        assert uow.conn is not None

    with pytest.raises(RuntimeError, match="not open"):
        _ = uow.conn


async def test_emitting_outside_the_block_raises(store: Store) -> None:
    async with store.uow() as uow:
        pass

    with pytest.raises(RuntimeError, match="not open"):
        uow.emit(event(EventName.run_created))


# --------------------------------------------------------------------------
# The repositories (T014)
# --------------------------------------------------------------------------


async def test_the_repositories_share_the_transaction(store: Store) -> None:
    """One block, one transaction: everything in it commits together."""

    async with store.uow() as uow:
        run = await uow.runs.insert("demo", "a run")
        await uow.log.append(run.id, "build", "engine", "started")
        assert uow.runs.conn is uow.conn
        assert uow.log.conn is uow.conn

    async with store.reader() as reader:
        assert await reader.runs.get(run.id) is not None
        assert len(await reader.log.list(run.id)) == 1


async def test_a_rolled_back_block_writes_none_of_its_repositories(
    store: Store,
) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with store.uow() as uow:
            run = await uow.runs.insert("demo", "a run")
            await uow.log.append(run.id, "build", "engine", "started")
            raise RuntimeError("boom")

    async with store.reader() as reader:
        assert await reader.runs.list() == []


async def test_reaching_a_repository_outside_the_block_raises(
    store: Store,
) -> None:
    async with store.uow() as uow:
        pass

    for name in ("runs", "log", "events", "submissions", "stream"):
        with pytest.raises(RuntimeError, match="not open"):
            getattr(uow, name)


async def test_the_reader_commits_nothing(store: Store) -> None:
    """Read-only by construction: no transaction, so no write survives."""

    async with store.reader() as reader:
        await reader.runs.insert("demo", "never happened")

    async with store.reader() as reader:
        assert await reader.runs.list() == []


async def test_the_reader_takes_no_writer_lock(store: Store) -> None:
    async with asyncio.timeout(5):
        async with store.uow() as uow:
            uow.emit(event(EventName.run_created))
            async with store.reader() as reader:
                assert await reader.runs.list() == []

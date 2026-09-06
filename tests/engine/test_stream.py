"""Tests for :class:`athanore.engine.services.StreamService`.

07 §Transcript writes fixes three things and each has a test here.

**One insert per interval.** An agent turn produces chunks a token at a
time; a statement per chunk is a round trip per chunk, and on SQLite a
turn of the one writer per chunk. Twenty appends inside one interval must
be one multi-row insert and one announcement, not twenty of each.

**The event is ephemeral.** ``task.stream`` goes to the bus and never to
the ``events`` table (``EPHEMERAL`` in ``athanore.events.names``): at two
to three flushes a second per streaming task it would be most of the
table, and it carries nothing a late joiner cannot fetch from
``/api/tasks/{id}/stream``.

**A flush failure never reaches the body.** The transcript is diagnostic
and the work log carries the deliverables, so an agent turn is not failed
by its own logging; the buffer keeps the chunks and the next tick writes
them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from athanore.engine.services import StreamService
from athanore.events.bus import EventBus
from athanore.events.names import EventName
from athanore.store.repos.stream import StreamRepo
from athanore.store.rows import ChunkKind
from athanore.store.uow import Store

#: Short enough that a test waits milliseconds, long enough that twenty
#: appends and a fixture setup fit inside one of them.
INTERVAL = 0.2


async def make_task(store: Store) -> tuple[str, int]:
    async with store.uow() as uow:
        run = await uow.runs.insert("demo", "a run")
        task = await uow.tasks.enqueue(
            run.id, "build", None, priority=0, explicit=False
        )
    return run.id, task.id


def service(store: Store, run_id: str, task_id: int, interval: float) -> StreamService:
    return StreamService(store, run_id=run_id, task_id=task_id, flush_interval=interval)


@pytest.fixture
def batches(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The size of every batch :meth:`StreamRepo.append_batch` was given."""

    sizes: list[int] = []
    original = StreamRepo.append_batch

    async def spy(
        self: StreamRepo, task_id: int, chunks: Sequence[tuple[int, str, str]]
    ) -> int:
        sizes.append(len(chunks))
        return await original(self, task_id, chunks)

    monkeypatch.setattr(StreamRepo, "append_batch", spy)
    return sizes


async def test_a_burst_inside_one_interval_is_one_insert_and_one_event(
    store: Store, bus: EventBus, batches: list[int]
) -> None:
    run_id, task_id = await make_task(store)
    stream = service(store, run_id, task_id, INTERVAL)
    subscription = bus.subscribe(["task.stream"])

    for index in range(20):
        assert await stream.append(ChunkKind.text, f"chunk {index}") == index + 1

    assert batches == []  # nothing is written before the flusher ticks
    await asyncio.sleep(INTERVAL * 1.5)
    assert batches == [20]

    event = subscription.queue.get_nowait()
    assert subscription.queue.empty()
    assert event.name == EventName.task_stream
    assert event.task_id == task_id
    assert event.run_id == run_id
    assert event.data == {"seq_from": 1, "seq_to": 20}
    assert event.id is None  # never stored, so never a cursor

    async with store.reader() as reader:
        rows = await reader.stream.list_after(task_id)
    assert [row.seq for row in rows] == list(range(1, 21))
    assert rows[0].kind is ChunkKind.text
    assert rows[19].text == "chunk 19"

    subscription.close()
    await stream.close()


async def test_close_flushes_the_remainder(
    store: Store, bus: EventBus, batches: list[int]
) -> None:
    """The last chunks of a finished turn are the ones a reader wants."""

    run_id, task_id = await make_task(store)
    stream = service(store, run_id, task_id, INTERVAL)
    subscription = bus.subscribe(["task.stream"])

    await stream.append(ChunkKind.text, "a")
    await stream.append(ChunkKind.thought, "b")
    await stream.append(ChunkKind.notice, "c")
    await stream.close()

    assert batches == [3]
    assert stream.buffer == []
    event = subscription.queue.get_nowait()
    assert event.data == {"seq_from": 1, "seq_to": 3}

    async with store.reader() as reader:
        rows = await reader.stream.list_after(task_id)
    assert [(row.seq, row.kind, row.text) for row in rows] == [
        (1, ChunkKind.text, "a"),
        (2, ChunkKind.thought, "b"),
        (3, ChunkKind.notice, "c"),
    ]
    subscription.close()


async def test_close_is_idempotent_and_refuses_a_later_append(store: Store) -> None:
    run_id, task_id = await make_task(store)
    stream = service(store, run_id, task_id, INTERVAL)

    await stream.append(ChunkKind.text, "a")
    await stream.close()
    await stream.close()

    with pytest.raises(RuntimeError, match="closed"):
        await stream.append(ChunkKind.text, "b")


async def test_closing_a_stream_that_never_wrote_is_a_no_op(
    store: Store, batches: list[int]
) -> None:
    run_id, task_id = await make_task(store)

    await service(store, run_id, task_id, INTERVAL).close()

    assert batches == []


async def test_seq_continues_after_a_restart(
    store: Store, bus: EventBus, batches: list[int]
) -> None:
    """A re-executed attempt writes chunk n+1, not chunk 1 again (04)."""

    run_id, task_id = await make_task(store)

    first = service(store, run_id, task_id, INTERVAL)
    await first.append(ChunkKind.text, "before the crash")
    await first.append(ChunkKind.text, "still before it")
    await first.close()

    subscription = bus.subscribe(["task.stream"])
    second = service(store, run_id, task_id, INTERVAL)
    assert await second.append(ChunkKind.text, "after it") == 3
    await second.close()

    assert batches == [2, 1]
    assert subscription.queue.get_nowait().data == {"seq_from": 3, "seq_to": 3}
    async with store.reader() as reader:
        rows = await reader.stream.list_after(task_id)
        assert await reader.stream.last_seq(task_id) == 3
    assert [row.seq for row in rows] == [1, 2, 3]
    subscription.close()


async def test_the_ephemeral_event_is_never_stored(store: Store) -> None:
    run_id, task_id = await make_task(store)
    stream = service(store, run_id, task_id, INTERVAL)

    await stream.append(ChunkKind.text, "a")
    await stream.close()

    async with store.reader() as reader:
        stored = await reader.events.list_for_run(run_id)
    assert [row.name for row in stored] == []


async def test_a_failing_flush_is_retried_and_never_reaches_the_body(
    store: Store, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, task_id = await make_task(store)
    stream = service(store, run_id, task_id, INTERVAL)
    subscription = bus.subscribe(["task.stream"])

    original = StreamRepo.append_batch
    failures: list[int] = []

    async def fail_once(
        self: StreamRepo, task_id_: int, chunks: Sequence[tuple[int, str, str]]
    ) -> int:
        if not failures:
            failures.append(len(chunks))
            raise RuntimeError("the disk is having a moment")
        return await original(self, task_id_, chunks)

    monkeypatch.setattr(StreamRepo, "append_batch", fail_once)

    await stream.append(ChunkKind.text, "a")
    await stream.append(ChunkKind.text, "b")
    await asyncio.sleep(INTERVAL * 1.5)

    # The tick failed, the body is untouched, and the chunks are still held.
    assert failures == [2]
    assert len(stream.buffer) == 2
    assert subscription.queue.empty()
    assert await stream.append(ChunkKind.text, "c") == 3

    await asyncio.sleep(INTERVAL * 1.5)

    assert stream.buffer == []
    assert subscription.queue.get_nowait().data == {"seq_from": 1, "seq_to": 3}
    async with store.reader() as reader:
        rows = await reader.stream.list_after(task_id)
    assert [row.text for row in rows] == ["a", "b", "c"]

    subscription.close()
    await stream.close()


async def test_close_does_not_write_a_batch_twice(
    store: Store, bus: EventBus, batches: list[int]
) -> None:
    """`seq` is unique per task, so a re-flushed batch would raise.

    Closing while the flusher is mid-write is the window in which a
    cancellation could leave a committed batch still in the buffer;
    :meth:`StreamService.close` waits it out rather than cancelling into
    it.
    """

    run_id, task_id = await make_task(store)
    stream = service(store, run_id, task_id, 0.01)

    for index in range(50):
        await stream.append(ChunkKind.text, f"chunk {index}")
    await asyncio.sleep(0.02)
    await stream.close()

    assert sum(batches) == 50
    async with store.reader() as reader:
        rows = await reader.stream.list_after(task_id)
    assert [row.seq for row in rows] == list(range(1, 51))

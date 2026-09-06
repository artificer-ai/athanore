"""Tests for :mod:`athanore.store.retention`.

07 §Retention states two windows and one cascade, and each of the three
has a way of being wrong that a coarse assertion would miss, so the ages
here are exact rather than approximate — ``freezegun`` writes every row
at a stated instant and the pass is measured back from another (13
§Pyramid).

- A transcript ages from the attempt **finishing**. A prune that measured
  from the chunk instead would delete the transcript of a task that is
  still streaming, which is the one thing a reader is watching.
- Events age from the row, except ``run.*``. A prune that took the whole
  table would leave an old run in the list with no history behind it.
- Deleting a run takes all eight child tables with it — seven by the
  cascade of 07 §Schema and ``events`` by the sweep D83 called for.

The windows come from ``athanore.settings.Retention``, imported here on
purpose: ``store`` may not import ``settings`` (02 §Layering), so the
protocol :mod:`athanore.store.retention` declares is only known to match
the real settings model if a test hands it one.

Every test that opens a database runs on both backends; see
``tests/store/conftest.py``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time

from athanore.settings import Retention
from athanore.store import retention as retention_module
from athanore.store.retention import (
    PRUNE_INTERVAL,
    PruneCounts,
    prune_once,
    retention_loop,
)
from athanore.store.rows import (
    AnswerAuthor,
    ChunkKind,
    LogAuthor,
    RequestKind,
    RequestMode,
    RequestSource,
    TaskStatus,
)
from athanore.store.tables import (
    answers,
    events,
    join_arrivals,
    log_entries,
    requests,
    stream_chunks,
    submissions,
    tasks,
)
from athanore.store.uow import Store

#: The instant a pass is measured back from.
NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)

#: The eight tables a run's rows live in. ``events`` is the one with no
#: foreign key, and the one `RunRepo.delete` sweeps itself (D83).
CHILD_TABLES = (
    tasks,
    log_entries,
    submissions,
    stream_chunks,
    requests,
    answers,
    join_arrivals,
    events,
)


def ago(days: float) -> datetime:
    """The instant ``days`` before :data:`NOW`."""

    return NOW - timedelta(days=days)


class Emitted:
    """The shape the outbox needs of an event (see ``test_events_repo``).

    ``created`` is read from the clock rather than fixed, so an event
    emitted inside a ``freeze_time`` block is stamped with that instant —
    which is the age the prune measures.
    """

    def __init__(self, name: str, run_id: str | None = None) -> None:
        self.id: int | None = None
        self.run_id = run_id
        self.task_id: int | None = None
        self.name = name
        self.data: dict[str, Any] = {}
        self.created = datetime.now(UTC)


async def make_run(store: Store, title: str = "a run") -> str:
    async with store.uow() as uow:
        run = await uow.runs.insert("demo", title)
    return run.id


async def make_task(store: Store, run_id: str, node: str = "build") -> int:
    async with store.uow() as uow:
        task = await uow.tasks.enqueue(run_id, node, {"spec": 1}, 0, False)
    return task.id


async def write_chunks(store: Store, task_id: int, count: int = 3) -> None:
    async with store.uow() as uow:
        await uow.stream.append_batch(
            task_id,
            [(seq, ChunkKind.text.value, f"line {seq}") for seq in range(1, count + 1)],
        )


async def finish_task(store: Store, task_id: int, at: datetime) -> None:
    """End the attempt as of ``at``, which is what a chunk's age is from."""

    with freeze_time(at):
        async with store.uow() as uow:
            await uow.tasks.finish(task_id, TaskStatus.done.value, result={"ok": True})


async def write_event(store: Store, name: str, at: datetime, run_id: str) -> None:
    """Store one event stamped ``at``, through the outbox that writes them."""

    with freeze_time(at):
        async with store.uow() as uow:
            uow.emit(Emitted(name, run_id))


async def event_names(store: Store) -> list[str]:
    async with store.reader() as reader:
        return [row.name for row in await reader.events.list_after(after=0, limit=1000)]


async def chunk_count(store: Store, task_id: int) -> int:
    async with store.reader() as reader:
        return len(await reader.stream.list_after(task_id))


# --------------------------------------------------------------------------
# Stream chunks: the window runs from the attempt finishing
# --------------------------------------------------------------------------


async def test_prune_removes_the_chunks_of_a_task_finished_beyond_the_window(
    store: Store,
) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    await write_chunks(store, task_id)
    await finish_task(store, task_id, ago(15))

    await prune_once(store, Retention(), NOW)

    assert await chunk_count(store, task_id) == 0


async def test_prune_keeps_the_chunks_of_a_running_task_of_the_same_age(
    store: Store,
) -> None:
    """A long turn is never pruned out from under the reader watching it."""

    run_id = await make_run(store)
    running = await make_task(store, run_id, "long")
    finished = await make_task(store, run_id, "short")
    with freeze_time(ago(15)):
        await write_chunks(store, running)
        await write_chunks(store, finished)
    await finish_task(store, finished, ago(15))

    await prune_once(store, Retention(), NOW)

    assert await chunk_count(store, running) == 3
    assert await chunk_count(store, finished) == 0


async def test_prune_keeps_the_chunks_of_a_task_finished_inside_the_window(
    store: Store,
) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    await write_chunks(store, task_id)
    await finish_task(store, task_id, ago(13))

    await prune_once(store, Retention(), NOW)

    assert await chunk_count(store, task_id) == 3


# --------------------------------------------------------------------------
# Events: 30 days, except `run.*`
# --------------------------------------------------------------------------


async def test_prune_removes_old_events_but_keeps_run_lifecycle(
    store: Store,
) -> None:
    run_id = await make_run(store)
    await write_event(store, "run.created", ago(31), run_id)
    await write_event(store, "task.done", ago(31), run_id)
    await write_event(store, "task.started", ago(29), run_id)

    counts = await prune_once(store, Retention(), NOW)

    assert sorted(await event_names(store)) == ["run.created", "task.started"]
    assert counts.events == 1


async def test_prune_keeps_the_run_history_of_a_run_whose_noise_is_gone(
    store: Store,
) -> None:
    """A run older than the window is still readable: its own events stay."""

    run_id = await make_run(store)
    for name in ("run.created", "run.started", "run.completed"):
        await write_event(store, name, ago(400), run_id)
    await write_event(store, "task.done", ago(400), run_id)

    await prune_once(store, Retention(), NOW)

    async with store.reader() as reader:
        kept = await reader.events.list_for_run(run_id)
    assert [row.name for row in kept] == ["run.created", "run.started", "run.completed"]


# --------------------------------------------------------------------------
# The windows are settings, not constants
# --------------------------------------------------------------------------


async def test_prune_reads_both_windows_from_the_settings_it_is_given(
    store: Store,
) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    await write_chunks(store, task_id)
    await finish_task(store, task_id, ago(2))
    await write_event(store, "task.done", ago(2), run_id)

    counts = await prune_once(store, Retention(events_days=1, stream_days=1), NOW)

    assert counts == PruneCounts(stream_chunks=3, events=1)
    assert await chunk_count(store, task_id) == 0
    assert await event_names(store) == []


async def test_prune_removes_nothing_inside_a_wider_window(store: Store) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    await write_chunks(store, task_id)
    await finish_task(store, task_id, ago(200))
    await write_event(store, "task.done", ago(200), run_id)

    counts = await prune_once(store, Retention(events_days=365, stream_days=365), NOW)

    assert counts == PruneCounts(stream_chunks=0, events=0)
    assert await chunk_count(store, task_id) == 3


async def test_prune_of_an_empty_database_removes_nothing(store: Store) -> None:
    assert await prune_once(store, Retention(), NOW) == PruneCounts(0, 0)


async def test_prune_measures_from_the_clock_when_given_no_instant(
    store: Store,
) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    await write_chunks(store, task_id)
    await finish_task(store, task_id, ago(15))
    await write_event(store, "task.done", ago(31), run_id)

    with freeze_time(NOW):
        counts = await prune_once(store, Retention())

    assert counts == PruneCounts(stream_chunks=3, events=1)


# --------------------------------------------------------------------------
# Deleting a run: all eight child tables
# --------------------------------------------------------------------------


async def populate_every_child_table(store: Store, run_id: str) -> None:
    """One row per table of :data:`CHILD_TABLES`, all under ``run_id``."""

    async with store.uow() as uow:
        task = await uow.tasks.enqueue(run_id, "build", {"spec": 1}, 0, False)
        await uow.log.append(
            run_id, "build", LogAuthor.agent.value, "a line", task_id=task.id
        )
        await uow.submissions.insert(task.id, {"headline": "done"})
        await uow.stream.append_batch(task.id, [(1, ChunkKind.text.value, "hello")])
        request = await uow.requests.create(
            run_id,
            task.id,
            "proceed?",
            mode=RequestMode.options.value,
            source=RequestSource.node.value,
            kind=RequestKind.question.value,
            options=[{"id": "yes", "label": "Yes"}],
            ordinal=1,
        )
        await uow.requests.answer(request.id, AnswerAuthor.user.value, option_id="yes")
        await uow.conn.execute(
            join_arrivals.insert().values(
                run_id=run_id,
                join_node="collect",
                fanout_task=task.id,
                index=0,
                key=None,
                value={"ok": True},
                from_task=task.id,
                late=False,
                created=NOW,
            )
        )
        uow.emit(Emitted("task.done", run_id))


async def child_rows(store: Store, run_id: str) -> dict[str, int]:
    """How many rows each child table holds for ``run_id``."""

    counts: dict[str, int] = {}
    async with store.read() as conn:
        task_ids = [
            row.id
            for row in (
                await conn.execute(tasks.select().where(tasks.c.run_id == run_id))
            ).all()
        ]
        request_ids = [
            row.id
            for row in (
                await conn.execute(requests.select().where(requests.c.run_id == run_id))
            ).all()
        ]
        for table in CHILD_TABLES:
            if "run_id" in table.c:
                where = table.c.run_id == run_id
            elif "request_id" in table.c:
                where = table.c.request_id.in_(request_ids)
            else:
                where = table.c.task_id.in_(task_ids)
            rows = (await conn.execute(table.select().where(where))).all()
            counts[table.name] = len(rows)
    return counts


async def test_deleting_a_run_empties_all_eight_child_tables(store: Store) -> None:
    run_id = await make_run(store)
    other = await make_run(store, "kept")
    await populate_every_child_table(store, run_id)
    await populate_every_child_table(store, other)
    assert await child_rows(store, run_id) == {table.name: 1 for table in CHILD_TABLES}

    async with store.uow() as uow:
        assert await uow.runs.delete(run_id) is True

    assert await child_rows(store, run_id) == {table.name: 0 for table in CHILD_TABLES}
    assert await child_rows(store, other) == {table.name: 1 for table in CHILD_TABLES}


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


async def swept(store: Store, loop_task: asyncio.Task[None]) -> None:
    """Wait for the running loop to empty the events table.

    The loop runs concurrently and aiosqlite hands its work to a thread,
    so the assertion is "this became true", not "this was true after one
    turn of the event loop". A loop that died instead of pruning is
    re-raised here rather than showing up as a timeout.
    """

    for _ in range(500):
        await asyncio.sleep(0.01)
        if loop_task.done():
            loop_task.result()
            raise AssertionError("the retention loop ended on its own")
        if await event_names(store) == []:
            return
    raise AssertionError("the retention loop did not prune")


async def test_the_loop_prunes_before_it_first_sleeps(store: Store) -> None:
    """A process restarted more often than the interval still prunes."""

    run_id = await make_run(store)
    await write_event(store, "task.done", ago(400), run_id)

    task = asyncio.create_task(retention_loop(store, Retention(), PRUNE_INTERVAL))
    try:
        await swept(store, task)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_the_loop_prunes_again_after_each_interval(store: Store) -> None:
    run_id = await make_run(store)

    task = asyncio.create_task(retention_loop(store, Retention(), 0.02))
    try:
        for _ in range(3):
            await write_event(store, "task.done", ago(400), run_id)
            await swept(store, task)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_cancelling_the_loop_returns_promptly(store: Store) -> None:
    """Shutdown does not wait an hour for the sleep to come round."""

    task = asyncio.create_task(retention_loop(store, Retention(), PRUNE_INTERVAL))
    await asyncio.sleep(0.05)
    assert not task.done()

    started = time.monotonic()
    task.cancel()
    _done, pending = await asyncio.wait({task}, timeout=5)
    elapsed = time.monotonic() - started

    assert not pending
    assert task.cancelled()
    assert elapsed < 1.0


async def test_the_loop_lets_a_failing_pass_reach_its_supervisor(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A janitor that swallowed its failures would look alive while the
    database grew, so the exception ends the task rather than the pass."""

    async def boom(*_args: object, **_kwargs: object) -> PruneCounts:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(retention_module, "prune_once", boom)

    with pytest.raises(RuntimeError, match="the database went away"):
        await retention_loop(store, Retention(), PRUNE_INTERVAL)

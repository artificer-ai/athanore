"""Tests for :mod:`athanore.store.repos.stream`.

The transcript is written in bursts — 07 §Transcript writes puts two to
three flushes a second per streaming task — so the batch is the point:
50 chunks are **one** statement, asserted with a statement counter rather
than by reading the SQL. The rest is what a reader and a retention job
need: pagination by ``seq``, a ``last_seq`` a restarted flusher counts up
from, a unique ``(task_id, seq)`` that refuses a duplicated segment, and
a prune that measures age from the attempt *finishing*, so a long-running
task never has its transcript deleted out from under a reader.

Every test runs on both backends; see ``tests/store/conftest.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Insert, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.store.rows import ChunkKind
from athanore.store.tables import tasks
from athanore.store.uow import Store, now

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def _task_insert(
    run_id: str, node: str = "build", finished: datetime | None = None
) -> Insert:
    return (
        tasks.insert()
        .values(
            run_id=run_id,
            node=node,
            attempt=1,
            status="done" if finished else "in_progress",
            priority=0,
            created=NOW,
            finished=finished,
            terminal=False,
            branch=[],
        )
        .returning(tasks.c.id)
    )


async def make_task(
    store: Store, node: str = "build", finished: datetime | None = None
) -> int:
    async with store.uow() as uow:
        run = await uow.runs.insert("demo", "a run")
        result = await uow.conn.execute(_task_insert(run.id, node, finished))
        return int(result.scalar_one())


class Counter:
    """Counts the statements a block sends to the database."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine.sync_engine
        self.statements: list[str] = []

    def _record(
        self, conn: object, cursor: object, statement: str, *rest: object
    ) -> None:
        self.statements.append(statement)

    def __enter__(self) -> Counter:
        event.listen(self._engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._record)


# --------------------------------------------------------------------------
# append_batch
# --------------------------------------------------------------------------


async def test_a_batch_of_fifty_chunks_is_one_insert(
    store: Store, engine: AsyncEngine
) -> None:
    task_id = await make_task(store)
    chunks = [(seq, ChunkKind.text.value, f"chunk {seq}") for seq in range(1, 51)]

    async with store.uow() as uow:
        with Counter(engine) as counter:
            written = await uow.stream.append_batch(task_id, chunks)

    inserts = [
        statement
        for statement in counter.statements
        if statement.lstrip().upper().startswith("INSERT")
    ]
    assert written == 50
    assert len(inserts) == 1

    async with store.reader() as reader:
        stored = await reader.stream.list_after(task_id)
    assert len(stored) == 50
    assert [chunk.seq for chunk in stored] == list(range(1, 51))
    assert stored[0].text == "chunk 1"
    assert stored[0].kind is ChunkKind.text
    assert stored[0].created.tzinfo is not None


async def test_every_chunk_kind_round_trips(store: Store) -> None:
    task_id = await make_task(store)
    kinds = list(ChunkKind)

    async with store.uow() as uow:
        await uow.stream.append_batch(
            task_id,
            [(index, kind.value, kind.value) for index, kind in enumerate(kinds, 1)],
        )

    async with store.reader() as reader:
        stored = await reader.stream.list_after(task_id)
    assert [chunk.kind for chunk in stored] == kinds


async def test_an_empty_batch_writes_nothing(store: Store, engine: AsyncEngine) -> None:
    task_id = await make_task(store)

    async with store.uow() as uow:
        with Counter(engine) as counter:
            assert await uow.stream.append_batch(task_id, []) == 0

    assert counter.statements == []


async def test_a_repeated_seq_is_refused(store: Store) -> None:
    """`(task_id, seq)` is unique: a re-sent batch cannot duplicate the
    transcript, and the repository does not absorb the violation."""

    task_id = await make_task(store)
    async with store.uow() as uow:
        await uow.stream.append_batch(task_id, [(1, ChunkKind.text.value, "one")])

    with pytest.raises(IntegrityError):
        async with store.uow() as uow:
            await uow.stream.append_batch(task_id, [(1, ChunkKind.text.value, "again")])

    async with store.reader() as reader:
        stored = await reader.stream.list_after(task_id)
    assert [chunk.text for chunk in stored] == ["one"]


async def test_two_tasks_may_share_a_seq(store: Store) -> None:
    mine = await make_task(store, "build")
    theirs = await make_task(store, "review")

    async with store.uow() as uow:
        await uow.stream.append_batch(mine, [(1, ChunkKind.text.value, "mine")])
        await uow.stream.append_batch(theirs, [(1, ChunkKind.text.value, "theirs")])

    async with store.reader() as reader:
        assert len(await reader.stream.list_after(mine)) == 1
        assert len(await reader.stream.list_after(theirs)) == 1


async def test_a_burst_larger_than_one_statement_still_lands_whole(
    store: Store,
) -> None:
    """Above the per-statement ceiling the batch is split, never dropped."""

    from athanore.store.repos.stream import MAX_ROWS_PER_INSERT

    task_id = await make_task(store)
    total = MAX_ROWS_PER_INSERT + 7
    chunks = [(seq, ChunkKind.text.value, "x") for seq in range(1, total + 1)]

    async with store.uow() as uow:
        assert await uow.stream.append_batch(task_id, chunks) == total

    async with store.reader() as reader:
        assert await reader.stream.last_seq(task_id) == total


# --------------------------------------------------------------------------
# list_after
# --------------------------------------------------------------------------


async def test_list_after_pages_by_seq(store: Store) -> None:
    task_id = await make_task(store)
    async with store.uow() as uow:
        await uow.stream.append_batch(
            task_id,
            [(seq, ChunkKind.text.value, f"chunk {seq}") for seq in range(1, 11)],
        )

    async with store.reader() as reader:
        first = await reader.stream.list_after(task_id, after_seq=0, limit=4)
        second = await reader.stream.list_after(
            task_id, after_seq=first[-1].seq, limit=4
        )
        rest = await reader.stream.list_after(task_id, after_seq=second[-1].seq)

    assert [chunk.seq for chunk in first] == [1, 2, 3, 4]
    assert [chunk.seq for chunk in second] == [5, 6, 7, 8]
    assert [chunk.seq for chunk in rest] == [9, 10]


async def test_list_after_the_end_is_empty(store: Store) -> None:
    task_id = await make_task(store)
    async with store.uow() as uow:
        await uow.stream.append_batch(task_id, [(1, ChunkKind.text.value, "one")])

    async with store.reader() as reader:
        assert await reader.stream.list_after(task_id, after_seq=1) == []


async def test_list_after_is_scoped_to_the_task(store: Store) -> None:
    mine = await make_task(store, "build")
    theirs = await make_task(store, "review")
    async with store.uow() as uow:
        await uow.stream.append_batch(mine, [(1, ChunkKind.text.value, "mine")])
        await uow.stream.append_batch(theirs, [(1, ChunkKind.text.value, "theirs")])

    async with store.reader() as reader:
        assert [chunk.text for chunk in await reader.stream.list_after(mine)] == [
            "mine"
        ]


# --------------------------------------------------------------------------
# last_seq
# --------------------------------------------------------------------------


async def test_last_seq_is_zero_before_anything_is_written(
    store: Store,
) -> None:
    """A restarted flusher counts up from it, so the first chunk is 1."""

    task_id = await make_task(store)

    async with store.reader() as reader:
        assert await reader.stream.last_seq(task_id) == 0


async def test_last_seq_is_the_highest_written(store: Store) -> None:
    task_id = await make_task(store)
    async with store.uow() as uow:
        await uow.stream.append_batch(
            task_id, [(seq, ChunkKind.text.value, "x") for seq in (1, 2, 3)]
        )

    async with store.reader() as reader:
        assert await reader.stream.last_seq(task_id) == 3


# --------------------------------------------------------------------------
# prune_finished
# --------------------------------------------------------------------------


async def test_prune_finished_leaves_running_tasks_alone(store: Store) -> None:
    long_ago = NOW - timedelta(days=15)
    cutoff = NOW - timedelta(days=14)
    finished = await make_task(store, "old", finished=long_ago)
    running = await make_task(store, "live")
    recent = await make_task(store, "recent", finished=NOW)
    async with store.uow() as uow:
        for task_id in (finished, running, recent):
            await uow.stream.append_batch(task_id, [(1, ChunkKind.text.value, "chunk")])

    async with store.uow() as uow:
        removed = await uow.stream.prune_finished(cutoff)

    assert removed == 1
    async with store.reader() as reader:
        assert await reader.stream.list_after(finished) == []
        assert len(await reader.stream.list_after(running)) == 1
        assert len(await reader.stream.list_after(recent)) == 1


async def test_prune_finished_with_nothing_to_do_removes_nothing(
    store: Store,
) -> None:
    task_id = await make_task(store, finished=now())
    async with store.uow() as uow:
        await uow.stream.append_batch(task_id, [(1, ChunkKind.text.value, "chunk")])

    async with store.uow() as uow:
        assert await uow.stream.prune_finished(NOW - timedelta(days=14)) == 0


async def test_chunks_go_with_their_run(store: Store) -> None:
    """The cascade of 07, through ``tasks``."""

    async with store.uow() as uow:
        run = await uow.runs.insert("demo", "doomed")
        result = await uow.conn.execute(_task_insert(run.id))
        task_id = int(result.scalar_one())
        await uow.stream.append_batch(task_id, [(1, ChunkKind.text.value, "chunk")])

    async with store.uow() as uow:
        assert await uow.runs.delete(run.id) is True

    async with store.reader() as reader:
        assert await reader.stream.list_after(task_id) == []

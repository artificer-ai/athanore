"""Tests for :mod:`athanore.store.repos.log`.

The work log is append-only and read by cursor, so what is worth
asserting is the filter: ``exclude_kinds=("stats",)`` is what lets the
agent-facing view show a run's deliverables without a ``[stats]`` line per
attempt (08 §Agent-facing), and it must not take the *unkinded* entries
with it — ``kind NOT IN ('stats')`` is NULL for a NULL kind, and SQL
treats NULL as false, which would drop every plain note in the run.

Every test runs on both backends; see ``tests/store/conftest.py``.
"""

from __future__ import annotations

from sqlalchemy import Insert

from athanore.store.rows import LogAuthor, LogKind
from athanore.store.tables import tasks
from athanore.store.uow import Store, now


async def make_run(store: Store, title: str = "a run") -> str:
    async with store.uow() as uow:
        run = await uow.runs.insert("demo", title)
    return run.id


async def test_append_returns_the_entry_it_wrote(store: Store) -> None:
    run_id = await make_run(store)

    async with store.uow() as uow:
        entry = await uow.log.append(
            run_id,
            "build",
            LogAuthor.agent,
            "shipped the thing",
            task_id=None,
            kind=LogKind.deliverable,
        )

    assert entry.run_id == run_id
    assert entry.node == "build"
    assert entry.author is LogAuthor.agent
    assert entry.kind is LogKind.deliverable
    assert entry.text == "shipped the thing"
    assert entry.task_id is None
    assert entry.created.tzinfo is not None


async def test_an_entry_may_name_a_task_or_not(store: Store) -> None:
    """A note about the run has no attempt to point at."""

    run_id = await make_run(store)

    async with store.uow() as uow:
        result = await uow.conn.execute(_task_insert(run_id))
        task_id = int(result.scalar_one())
        attached = await uow.log.append(
            run_id, "build", LogAuthor.engine, "attempt 1 failed", task_id=task_id
        )
        loose = await uow.log.append(run_id, "user", LogAuthor.user, "a note")

    assert attached.task_id == task_id
    assert loose.task_id is None
    assert loose.kind is None


async def test_list_is_in_insertion_order(store: Store) -> None:
    run_id = await make_run(store)

    async with store.uow() as uow:
        for index in range(4):
            await uow.log.append(run_id, "build", LogAuthor.engine, f"line {index}")

    async with store.reader() as reader:
        entries = await reader.log.list(run_id)

    assert [entry.text for entry in entries] == [f"line {index}" for index in range(4)]
    assert [entry.id for entry in entries] == sorted(entry.id for entry in entries)


async def test_list_is_scoped_to_the_run(store: Store) -> None:
    mine = await make_run(store, "mine")
    theirs = await make_run(store, "theirs")

    async with store.uow() as uow:
        await uow.log.append(mine, "build", LogAuthor.engine, "mine")
        await uow.log.append(theirs, "build", LogAuthor.engine, "theirs")

    async with store.reader() as reader:
        assert [entry.text for entry in await reader.log.list(mine)] == ["mine"]


async def test_list_honours_the_cursor_and_the_limit(store: Store) -> None:
    run_id = await make_run(store)
    async with store.uow() as uow:
        written = [
            await uow.log.append(run_id, "build", LogAuthor.engine, f"line {index}")
            for index in range(5)
        ]

    async with store.reader() as reader:
        after_second = await reader.log.list(run_id, after=written[1].id)
        page = await reader.log.list(run_id, after=written[1].id, limit=2)

    assert [entry.text for entry in after_second] == [
        "line 2",
        "line 3",
        "line 4",
    ]
    assert [entry.text for entry in page] == ["line 2", "line 3"]


async def test_exclude_kinds_drops_stats_and_keeps_everything_else(
    store: Store,
) -> None:
    run_id = await make_run(store)

    async with store.uow() as uow:
        await uow.log.append(
            run_id,
            "build",
            LogAuthor.agent,
            "the deliverable",
            kind=LogKind.deliverable,
        )
        await uow.log.append(
            run_id,
            "build",
            LogAuthor.engine,
            "[stats] node=build …",
            kind=LogKind.stats,
        )
        await uow.log.append(
            run_id,
            "build",
            LogAuthor.engine,
            "attempt 1 failed",
            kind=LogKind.failure,
        )
        # No kind at all: the case a `NOT IN` would silently drop.
        await uow.log.append(run_id, "build", LogAuthor.user, "a plain note")

    async with store.reader() as reader:
        kept = await reader.log.list(run_id, exclude_kinds=(LogKind.stats,))
        everything = await reader.log.list(run_id)

    assert [entry.text for entry in kept] == [
        "the deliverable",
        "attempt 1 failed",
        "a plain note",
    ]
    assert len(everything) == 4


async def test_exclude_kinds_takes_several(store: Store) -> None:
    run_id = await make_run(store)

    async with store.uow() as uow:
        for kind in (LogKind.stats, LogKind.failure, LogKind.note):
            await uow.log.append(
                run_id, "build", LogAuthor.engine, str(kind), kind=kind
            )

    async with store.reader() as reader:
        kept = await reader.log.list(
            run_id, exclude_kinds=(LogKind.stats, LogKind.failure)
        )

    assert [entry.kind for entry in kept] == [LogKind.note]


async def test_list_of_a_run_with_no_entries_is_empty(store: Store) -> None:
    run_id = await make_run(store)

    async with store.reader() as reader:
        assert await reader.log.list(run_id) == []


def _task_insert(run_id: str) -> Insert:
    return (
        tasks.insert()
        .values(
            run_id=run_id,
            node="build",
            attempt=1,
            status="in_progress",
            priority=0,
            created=now(),
            terminal=False,
            branch=[],
        )
        .returning(tasks.c.id)
    )

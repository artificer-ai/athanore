"""Tests for :mod:`athanore.store.repos.submissions`.

A submission is a value an agent handed in, never a transition
(invariant 1 of 03), and the latest one wins for the body — an agent that
was asked to repair its output submits again. So the property that
matters is that :meth:`SubmissionRepo.latest` returns the newest row and
not the first, ordered by id rather than by a timestamp two submissions
of one repair turn can share.

Every test runs on SQLite; T014b parametrises the suite over
PostgreSQL too (``tests/store/conftest.py``).
"""

from __future__ import annotations

from sqlalchemy import Insert

from athanore.store.tables import tasks
from athanore.store.uow import Store, now


def _task_insert(run_id: str, node: str = "build") -> Insert:
    return (
        tasks.insert()
        .values(
            run_id=run_id,
            node=node,
            attempt=1,
            status="in_progress",
            priority=0,
            created=now(),
            terminal=False,
            branch=[],
        )
        .returning(tasks.c.id)
    )


async def make_task(store: Store, node: str = "build") -> int:
    async with store.uow() as uow:
        run = await uow.runs.insert("demo", "a run")
        result = await uow.conn.execute(_task_insert(run.id, node))
        return int(result.scalar_one())


async def test_insert_returns_the_row_it_wrote(store: Store) -> None:
    task_id = await make_task(store)

    async with store.uow() as uow:
        submission = await uow.submissions.insert(task_id, {"verdict": "ok"})

    assert submission.task_id == task_id
    assert submission.payload == {"verdict": "ok"}
    assert submission.created.tzinfo is not None


async def test_a_payload_may_be_any_json_value(store: Store) -> None:
    task_id = await make_task(store)

    async with store.uow() as uow:
        for payload in ({"a": 1}, [1, 2], "text", 7, True, None):
            written = await uow.submissions.insert(task_id, payload)
            assert written.payload == payload


async def test_latest_is_the_highest_id_not_the_first_inserted(
    store: Store,
) -> None:
    task_id = await make_task(store)

    async with store.uow() as uow:
        for index in range(3):
            await uow.submissions.insert(task_id, {"attempt": index})

    async with store.reader() as reader:
        latest = await reader.submissions.latest(task_id)

    assert latest is not None
    assert latest.payload == {"attempt": 2}


async def test_latest_of_a_task_that_submitted_nothing_is_none(
    store: Store,
) -> None:
    task_id = await make_task(store)

    async with store.reader() as reader:
        assert await reader.submissions.latest(task_id) is None


async def test_list_is_oldest_first_and_scoped_to_the_task(
    store: Store,
) -> None:
    mine = await make_task(store, "build")
    theirs = await make_task(store, "review")

    async with store.uow() as uow:
        await uow.submissions.insert(mine, {"n": 1})
        await uow.submissions.insert(theirs, {"n": 99})
        await uow.submissions.insert(mine, {"n": 2})

    async with store.reader() as reader:
        listed = await reader.submissions.list(mine)
        other = await reader.submissions.list(theirs)

    assert [row.payload for row in listed] == [{"n": 1}, {"n": 2}]
    assert [row.payload for row in other] == [{"n": 99}]


async def test_submissions_go_with_their_task(store: Store) -> None:
    """The cascade of 07: deleting the run takes the submissions."""

    async with store.uow() as uow:
        run = await uow.runs.insert("demo", "doomed")
        result = await uow.conn.execute(_task_insert(run.id))
        task_id = int(result.scalar_one())
        await uow.submissions.insert(task_id, {"n": 1})

    async with store.uow() as uow:
        assert await uow.runs.delete(run.id) is True

    async with store.reader() as reader:
        assert await reader.submissions.list(task_id) == []

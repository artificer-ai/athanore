"""Tests for :meth:`athanore.store.repos.tasks.TaskRepo.claim_ready`.

The ordering assertions are ported from v0's ``tests/test_priority.py``
(the API half of that file is T044a's): run list position dominates,
explicit priorities come first, then downstream-first (``-generation``),
then newest-first, and a retry carrying the failed attempt's ``created``
does not jump the queue it was already in. 04 §Dispatch order is the
specification; this module is what stops the SELECT drifting from it.

Three properties beyond the ordering matter as much:

- **A claim is a claim.** The ``UPDATE`` re-checks ``status = 'ready'``,
  so claiming twice returns the row once. On PostgreSQL the select also
  takes ``FOR UPDATE OF tasks SKIP LOCKED``, which is the only part of
  the store that needs a second connection to mean anything.
- **The token is returned, never stored** (D38, 12 §Task tokens): the row
  keeps a SHA-256, the clear text appears nowhere in it, and each claimed
  attempt gets its own.
- **A paused run never dispatches.** It is the one line that makes
  operator pause mean something, and it is one ``IN`` away from being
  lost.

Every test runs on both backends; see ``tests/store/conftest.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from athanore.store.repos.tasks import (
    CLAIMABLE_RUNS,
    ClaimedTask,
    claim_statement,
    token_hash,
)
from athanore.store.rows import RunStatus, TaskRow, TaskStatus
from athanore.store.tables import tasks
from athanore.store.uow import Store, now

T0 = datetime(2026, 9, 6, 9, 0, tzinfo=UTC)
POOL = ["demo"]


def at(seconds: int) -> datetime:
    """A ``created`` stamp, so the newest-first tiebreaker is not a race."""

    return T0 + timedelta(seconds=seconds)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def make_run(store: Store, workflow: str = "demo", title: str = "run") -> str:
    """A queued run, appended at the bottom of the list."""

    async with store.uow() as uow:
        run = await uow.runs.insert(workflow, title)
    return run.id


async def enqueue(
    store: Store,
    run_id: str,
    node: str = "build",
    priority: int = 0,
    explicit: bool = False,
    created: datetime | None = None,
    **extra: Any,
) -> int:
    async with store.uow() as uow:
        task = await uow.tasks.enqueue(
            run_id, node, None, priority, explicit, created=created, **extra
        )
    return task.id


async def claim(
    store: Store, limit: int, workflows: list[str] | None = None
) -> list[ClaimedTask]:
    pool = POOL if workflows is None else workflows
    async with store.uow() as uow:
        return await uow.tasks.claim_ready(limit, pool)


async def claimed_ids(store: Store, limit: int = 10) -> list[int]:
    return [entry.task.id for entry in await claim(store, limit)]


async def make_ready_again(store: Store, task_id: int) -> None:
    """Put a claimed task back, as a recovery or a ``set_status`` would."""

    async with store.uow() as uow:
        await uow.conn.execute(
            tasks.update()
            .where(tasks.c.id == task_id)
            .values(status=TaskStatus.ready.value, started=None, token_hash=None)
        )


async def raw(store: Store, task_id: int) -> Any:
    async with store.reader() as reader:
        result = await reader.conn.execute(select(tasks).where(tasks.c.id == task_id))
        return result.mappings().one()


# --------------------------------------------------------------------------
# The ordering (ported from v0's tests/test_priority.py)
# --------------------------------------------------------------------------


async def test_run_position_dominates_every_task_key(store: Store) -> None:
    """A new run's start node must not preempt a deeper node of an
    in-flight run — v0's ``test_in_flight_run_beats_new_submission``."""

    first = await make_run(store, title="first")
    second = await make_run(store, title="second")
    deep = await enqueue(store, first, "review", priority=-4, created=at(0))
    start = await enqueue(store, second, "start", priority=0, created=at(10))

    assert await claimed_ids(store) == [deep, start]


async def test_run_position_dominates_even_an_explicit_priority(
    store: Store,
) -> None:
    top = await make_run(store, title="top")
    bottom = await make_run(store, title="bottom")
    ordinary = await enqueue(store, top, "build", priority=0, created=at(0))
    hotfix = await enqueue(store, bottom, "git", priority=1, explicit=True)

    assert await claimed_ids(store) == [ordinary, hotfix]


async def test_reordering_the_run_reorders_the_claim(store: Store) -> None:
    """Dispatch reads ``runs.position`` through the join, so a reorder needs
    no snapshot on the task (D41)."""

    first = await make_run(store, title="first")
    second = await make_run(store, title="second")
    a = await enqueue(store, first, "a", created=at(0))
    b = await enqueue(store, second, "b", created=at(0))
    assert await claimed_ids(store) == [a, b]

    await make_ready_again(store, a)
    await make_ready_again(store, b)
    async with store.uow() as uow:
        await uow.runs.swap_position(first, 1)

    assert await claimed_ids(store) == [b, a]


async def test_the_full_order_inside_one_run(store: Store) -> None:
    """v0's ``test_claim_order``, at the repository level."""

    run_id = await make_run(store)
    # Enqueued in deliberately wrong order.
    shallow = await enqueue(store, run_id, "prompt", priority=0, created=at(0))
    deep = await enqueue(store, run_id, "review", priority=-4, created=at(1))
    hotfix = await enqueue(store, run_id, "git", priority=1, explicit=True)
    later_hotfix = await enqueue(store, run_id, "qa", priority=5, explicit=True)
    deep2 = await enqueue(store, run_id, "qa2", priority=-4, created=at(2))

    order = await claimed_ids(store)

    assert order == [hotfix, later_hotfix, deep2, deep, shallow]
    # Within the same generation, newest first (stack behaviour).
    assert order.index(deep2) < order.index(deep)


async def test_an_explicit_priority_beats_a_generation(store: Store) -> None:
    """``explicit DESC`` splits the rows before either ``CASE`` is read, so
    a hotfix at priority 5 still precedes a generation of -9."""

    run_id = await make_run(store)
    deepest = await enqueue(store, run_id, "deep", priority=-9, created=at(0))
    hotfix = await enqueue(store, run_id, "hotfix", priority=5, explicit=True)

    assert await claimed_ids(store) == [hotfix, deepest]


async def test_negative_generation_orders_downstream_first(store: Store) -> None:
    run_id = await make_run(store)
    start = await enqueue(store, run_id, "start", priority=0, created=at(0))
    middle = await enqueue(store, run_id, "middle", priority=-1, created=at(0))
    end = await enqueue(store, run_id, "end", priority=-4, created=at(0))

    assert await claimed_ids(store) == [end, middle, start]


async def test_equal_keys_take_the_newer_created_first(store: Store) -> None:
    run_id = await make_run(store)
    older = await enqueue(store, run_id, "a", priority=0, created=at(0))
    newer = await enqueue(store, run_id, "b", priority=0, created=at(30))

    assert await claimed_ids(store) == [newer, older]


async def test_a_retry_carrying_the_old_created_does_not_jump_the_queue(
    store: Store,
) -> None:
    """04 §Running an attempt: the retry keeps its predecessor's ``created``,
    so a flapping node cannot keep overtaking the work behind it."""

    run_id = await make_run(store)
    failed_at = at(0)
    queued_meanwhile = await enqueue(store, run_id, "sibling", created=at(5))
    retry = await enqueue(store, run_id, "flapper", attempt=2, created=failed_at)

    assert await claimed_ids(store) == [queued_meanwhile, retry]

    # The same retry with a fresh stamp would have overtaken it, which is
    # precisely what passing `created` prevents.
    await make_ready_again(store, retry)
    await make_ready_again(store, queued_meanwhile)
    async with store.uow() as uow:
        await uow.conn.execute(
            tasks.update().where(tasks.c.id == retry).values(created=at(10))
        )

    assert await claimed_ids(store) == [retry, queued_meanwhile]


# --------------------------------------------------------------------------
# What is claimable at all
# --------------------------------------------------------------------------


async def test_a_paused_run_is_never_claimed(store: Store) -> None:
    """The line that makes operator pause mean something (04 §Operator
    operations): in-flight attempts finish, nothing new starts."""

    paused = await make_run(store, title="paused")
    live = await make_run(store, title="live")
    parked = await enqueue(store, paused, "build")
    dispatchable = await enqueue(store, live, "build")
    async with store.uow() as uow:
        await uow.runs.set_status(paused, RunStatus.paused)

    assert await claimed_ids(store) == [dispatchable]

    async with store.uow() as uow:
        await uow.runs.set_status(paused, RunStatus.running)

    assert await claimed_ids(store) == [parked]


@pytest.mark.parametrize(
    "status",
    [RunStatus.completed, RunStatus.failed, RunStatus.cancelled],
)
async def test_a_terminal_run_is_never_claimed(store: Store, status: RunStatus) -> None:
    assert status.value not in CLAIMABLE_RUNS

    run_id = await make_run(store)
    await enqueue(store, run_id, "build")
    async with store.uow() as uow:
        await uow.runs.set_status(run_id, status)

    assert await claimed_ids(store) == []


async def test_only_ready_tasks_are_claimed(store: Store) -> None:
    run_id = await make_run(store)
    ready = await enqueue(store, run_id, "ready", created=at(0))
    for status in (
        TaskStatus.in_progress,
        TaskStatus.waiting,
        TaskStatus.done,
        TaskStatus.failed,
        TaskStatus.dead_letter,
        TaskStatus.cancelled,
    ):
        other = await enqueue(store, run_id, status.value, created=at(5))
        async with store.uow() as uow:
            await uow.tasks.set_status(other, status)

    assert await claimed_ids(store) == [ready]


async def test_only_the_pools_workflows_are_claimed(store: Store) -> None:
    mine = await make_run(store, workflow="demo")
    theirs = await make_run(store, workflow="other")
    ours = await enqueue(store, mine, "build")
    await enqueue(store, theirs, "build")

    assert await claimed_ids(store) == [ours]


async def test_an_empty_pool_and_a_full_pool_claim_nothing(store: Store) -> None:
    """A pool with no workflow registered, and one with no free slot."""

    run_id = await make_run(store)
    await enqueue(store, run_id, "build")

    assert await claim(store, 10, []) == []
    assert await claim(store, 0) == []
    assert await claim(store, -1) == []


# --------------------------------------------------------------------------
# The claim itself
# --------------------------------------------------------------------------


async def test_claiming_marks_the_row_in_progress_and_stamps_started(
    store: Store,
) -> None:
    run_id = await make_run(store)
    task_id = await enqueue(store, run_id, "build")
    before = now()

    entry = (await claim(store, 1))[0]

    assert entry.task.id == task_id
    assert entry.task.status is TaskStatus.in_progress
    assert entry.task.started is not None
    assert before <= entry.task.started <= now()
    async with store.reader() as reader:
        stored = await reader.tasks.get(task_id)
    assert stored is not None and stored.status is TaskStatus.in_progress


async def test_limit_is_respected_and_the_rest_stay_ready(store: Store) -> None:
    run_id = await make_run(store)
    ids = [
        await enqueue(store, run_id, f"n{i}", priority=-i, created=at(0))
        for i in range(4)
    ]

    first = await claimed_ids(store, limit=2)
    second = await claimed_ids(store, limit=2)

    # priority -3 .. 0, downstream first.
    assert first == [ids[3], ids[2]]
    assert second == [ids[1], ids[0]]


async def test_a_second_claim_returns_nothing(store: Store) -> None:
    run_id = await make_run(store)
    await enqueue(store, run_id, "build")

    assert len(await claim(store, 10)) == 1
    assert await claim(store, 10) == []


async def test_two_claimers_never_take_the_same_task(store: Store) -> None:
    """The ``AND status = 'ready'`` in the ``UPDATE`` is the claim.

    Two claims of one connection cannot interleave, so this asserts the
    predicate rather than a race: a row taken between the select and the
    update is dropped, not claimed twice.
    """

    run_id = await make_run(store)
    task_id = await enqueue(store, run_id, "build")

    async with store.uow() as uow:
        stolen = await uow.conn.execute(
            tasks.update()
            .where(tasks.c.id == task_id, tasks.c.status == TaskStatus.ready.value)
            .values(status=TaskStatus.in_progress.value)
        )
        assert stolen.rowcount == 1
        assert await uow.tasks.claim_ready(10, POOL) == []


# --------------------------------------------------------------------------
# Tokens (D38, 12 §Task tokens)
# --------------------------------------------------------------------------


async def test_each_claim_mints_its_own_token_and_stores_only_the_hash(
    store: Store,
) -> None:
    run_id = await make_run(store)
    for index in range(3):
        await enqueue(store, run_id, f"n{index}", created=at(index))

    claimed = await claim(store, 3)

    tokens = [entry.token for entry in claimed]
    assert len(set(tokens)) == 3
    for entry in claimed:
        row = dict(await raw(store, entry.task.id))
        assert row["token_hash"] == token_hash(entry.token)
        assert entry.task.token_hash == token_hash(entry.token)
        # The clear text is returned to the caller and nowhere else.
        assert entry.token not in str(row)
        assert entry.token not in str(entry.task)
        assert entry.token not in str(entry.task.model_dump())
        assert "token" not in entry.task.model_dump()


async def test_the_stored_hash_is_what_by_token_hash_answers_to(
    store: Store,
) -> None:
    run_id = await make_run(store)
    task_id = await enqueue(store, run_id, "build")

    entry = (await claim(store, 1))[0]

    async with store.reader() as reader:
        found = await reader.tasks.by_token_hash(token_hash(entry.token))
    assert found is not None and found.id == task_id


async def test_a_recovered_attempt_gets_a_different_token(store: Store) -> None:
    """A token captured from a dead attempt is dead with it (D38)."""

    run_id = await make_run(store)
    task_id = await enqueue(store, run_id, "build")
    first = (await claim(store, 1))[0]

    async with store.uow() as uow:
        await uow.tasks.reset_for_recovery()
    second = (await claim(store, 1))[0]

    assert second.task.id == task_id
    assert second.token != first.token
    async with store.reader() as reader:
        assert await reader.tasks.by_token_hash(token_hash(first.token)) is None
        assert await reader.tasks.by_token_hash(token_hash(second.token)) is not None


# --------------------------------------------------------------------------
# queued -> running
# --------------------------------------------------------------------------


async def test_a_queued_run_starts_once_however_many_tasks_are_claimed(
    store: Store,
) -> None:
    run_id = await make_run(store)
    for index in range(3):
        await enqueue(store, run_id, f"n{index}", created=at(index))

    claimed = await claim(store, 3)

    assert [entry.run_started for entry in claimed] == [True, False, False]
    async with store.reader() as reader:
        run = await reader.runs.get(run_id)
    assert run is not None and run.status is RunStatus.running


async def test_a_run_already_running_is_never_flagged_again(store: Store) -> None:
    run_id = await make_run(store)
    await enqueue(store, run_id, "older", created=at(0))
    newer_id = await enqueue(store, run_id, "newer", created=at(1))

    first = await claim(store, 1)
    async with store.uow() as uow:
        await uow.tasks.finish(first[0].task.id, TaskStatus.done)
    second = await claim(store, 1)

    assert [entry.run_started for entry in first] == [True]
    assert first[0].task.id == newer_id  # newest first, within equal keys
    assert [entry.run_started for entry in second] == [False]


async def test_each_run_in_one_claim_is_flagged_on_its_own_first_task(
    store: Store,
) -> None:
    first = await make_run(store, title="first")
    second = await make_run(store, title="second")
    for index in range(2):
        await enqueue(store, first, f"a{index}", created=at(index))
        await enqueue(store, second, f"b{index}", created=at(index))

    claimed = await claim(store, 4)

    assert [entry.run_started for entry in claimed] == [True, False, True, False]
    assert [entry.task.run_id for entry in claimed] == [first, first, second, second]


async def test_the_run_start_flag_follows_the_row_the_database_moved(
    store: Store,
) -> None:
    """A run someone else already started reports nothing, so ``run.started``
    is emitted once in the life of a run."""

    run_id = await make_run(store)
    await enqueue(store, run_id, "build")
    async with store.uow() as uow:
        await uow.runs.set_status(run_id, RunStatus.running)

    claimed = await claim(store, 1)

    assert [entry.run_started for entry in claimed] == [False]


# --------------------------------------------------------------------------
# The dialect switch
# --------------------------------------------------------------------------


DIALECTS = {"sqlite": sqlite.dialect(), "postgresql": postgresql.dialect()}


@pytest.mark.parametrize("name", sorted(DIALECTS))
def test_the_claim_query_compiles_for_both_backends(name: str) -> None:
    """The PostgreSQL spelling is checked on a machine with only SQLite.

    ``SKIP LOCKED`` is the one part of the claim a single-writer SQLite
    never exercises, so the gate at least compiles it (13 §Pyramid).
    """

    sql = str(claim_statement(name, 4, ["demo"]).compile(dialect=DIALECTS[name]))

    assert "FROM tasks JOIN runs ON runs.id = tasks.run_id" in sql
    assert "ORDER BY runs.position ASC, tasks.explicit DESC" in sql
    assert sql.count("CASE WHEN") == 2
    assert "tasks.created DESC, tasks.id DESC" in sql
    # The lock is on the tasks alone: locking the joined run would make two
    # claims of different tasks in one run exclude each other.
    assert ("FOR UPDATE OF tasks SKIP LOCKED" in sql) is (name == "postgresql")


def test_an_unknown_backend_is_refused_not_guessed() -> None:
    with pytest.raises(NotImplementedError, match="mysql"):
        claim_statement("mysql", 1, ["demo"])


def test_a_claimed_task_unpacks_as_the_tuple_it_is_specified_as() -> None:
    row = TaskRow(
        id=1,
        run_id="01JRUN",
        node="build",
        attempt=1,
        status=TaskStatus.in_progress,
        priority=0,
        created=T0,
    )

    task, token, run_started = ClaimedTask(row, "clear-text", True)

    assert (task, token, run_started) == (row, "clear-text", True)

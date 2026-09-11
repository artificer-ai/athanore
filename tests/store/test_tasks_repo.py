"""Tests for :mod:`athanore.store.repos.tasks`, except the claim.

A task row is one *attempt* (03 §Task), and four properties carry this
module. The first is that the engine owns the clock: ``enqueue`` stamps
``created`` only when the caller did not, because a retry carries the
failed attempt's value forward and the dispatch order's last tiebreaker
is ``created DESC``. The second is that ``finish`` is the only call that
ends an attempt — it writes ``finished`` and ``terminal``, and
``set_status`` deliberately writes neither. The third is that
``reset_for_recovery`` touches exactly the two statuses a crash can leave
behind and clears the token hash with them, so a token minted for a dead
attempt authenticates nothing. The fourth is that ``terminal_tasks``
orders by the branch index path, which is what makes a fan-out's output a
list nobody's timing decides.

The claim is :mod:`tests.store.test_claim`. Every test here runs on both
backends; see ``tests/store/conftest.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from athanore.store.repos.tasks import (
    INTERRUPTED,
    PENDING,
    branch_path,
    token_hash,
)
from athanore.store.rows import BranchFrame, TaskRow, TaskStatus
from athanore.store.tables import tasks
from athanore.store.uow import Store, now

OLD = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def make_run(store: Store, workflow: str = "demo") -> str:
    async with store.uow() as uow:
        run = await uow.runs.insert(workflow, "a run")
    return run.id


async def enqueue(
    store: Store,
    run_id: str,
    node: str = "build",
    payload: Any = None,
    priority: int = 0,
    explicit: bool = False,
    **extra: Any,
) -> TaskRow:
    async with store.uow() as uow:
        return await uow.tasks.enqueue(
            run_id, node, payload, priority, explicit, **extra
        )


async def force(store: Store, task_id: int, **values: Any) -> None:
    """Write columns the repository has no setter for (a claim's leavings)."""

    async with store.uow() as uow:
        await uow.conn.execute(
            tasks.update().where(tasks.c.id == task_id).values(**values)
        )


async def raw(store: Store, task_id: int) -> Any:
    async with store.reader() as reader:
        result = await reader.conn.execute(select(tasks).where(tasks.c.id == task_id))
        return result.mappings().one()


# --------------------------------------------------------------------------
# enqueue
# --------------------------------------------------------------------------


async def test_enqueue_defaults_a_ready_untouched_attempt(store: Store) -> None:
    run_id = await make_run(store)
    before = now()

    task = await enqueue(store, run_id, "build", {"spec": 1}, -3, False)

    assert task.run_id == run_id
    assert task.node == "build"
    assert task.status is TaskStatus.ready
    assert task.attempt == 1
    assert task.payload == {"spec": 1}
    assert task.priority == -3
    assert task.explicit is False
    assert task.result is None
    assert task.error is None
    assert task.stats is None
    assert task.lineage is None
    assert task.terminal is False
    assert task.branch == []
    assert task.started is None
    assert task.finished is None
    # No token until a claim mints one (D38).
    assert task.token_hash is None
    assert before <= task.created <= now()


async def test_a_retry_keeps_the_created_of_the_attempt_it_replaces(
    store: Store,
) -> None:
    """``created`` is a parameter because a retry must not jump the queue.

    04 §Running an attempt: the retry is a new row with the old
    ``created``, and ``created DESC`` is the dispatch order's last
    tiebreaker.
    """

    run_id = await make_run(store)
    first = await enqueue(store, run_id, "build")

    retry = await enqueue(
        store, run_id, "build", attempt=first.attempt + 1, created=first.created
    )

    assert retry.id != first.id
    assert retry.attempt == 2
    assert retry.created == first.created


async def test_enqueue_records_lineage_and_the_branch_stack(store: Store) -> None:
    run_id = await make_run(store)
    frames = [
        BranchFrame(fanout=7, index=1, count=3, key={"deliverable": "b"}),
        BranchFrame(fanout=11, index=0, count=2, key=None),
    ]

    task = await enqueue(
        store,
        run_id,
        "review",
        priority=4,
        explicit=True,
        lineage={"from": 7, "reason": "transition"},
        branch=frames,
    )

    assert task.explicit is True
    assert task.priority == 4
    assert task.lineage == {"from": 7, "reason": "transition"}
    assert task.branch == frames
    assert branch_path(task) == (1, 0)


async def test_enqueue_accepts_any_json_payload(store: Store) -> None:
    run_id = await make_run(store)

    for payload in ({"a": 1}, [1, 2], "text", 7, True, None):
        task = await enqueue(store, run_id, "build", payload)
        assert task.payload == payload


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


async def test_get_returns_the_attempt_and_none_for_an_unknown_id(
    store: Store,
) -> None:
    run_id = await make_run(store)
    task = await enqueue(store, run_id)

    async with store.reader() as reader:
        assert (await reader.tasks.get(task.id)) == task
        assert (await reader.tasks.get(task.id + 10_000)) is None


async def test_list_for_run_is_every_attempt_of_that_run_oldest_first(
    store: Store,
) -> None:
    run_id = await make_run(store)
    other = await make_run(store)
    first = await enqueue(store, run_id, "build")
    second = await enqueue(store, run_id, "review")
    elsewhere = await enqueue(store, other, "build")

    async with store.reader() as reader:
        listed = await reader.tasks.list_for_run(run_id)

    assert [row.id for row in listed] == [first.id, second.id]
    assert elsewhere.id not in {row.id for row in listed}


async def test_by_token_hash_finds_the_attempt_and_misses_without_raising(
    store: Store,
) -> None:
    """An unknown token is the ordinary case at the door of ``/api/agent/``."""

    run_id = await make_run(store)
    task = await enqueue(store, run_id)
    await force(
        store,
        task.id,
        status=TaskStatus.in_progress.value,
        token_hash=token_hash("a-token"),
    )

    async with store.reader() as reader:
        found = await reader.tasks.by_token_hash(token_hash("a-token"))
        missed = await reader.tasks.by_token_hash(token_hash("another-token"))

    assert found is not None and found.id == task.id
    assert missed is None


async def test_last_for_node_is_the_newest_attempt_at_that_node(
    store: Store,
) -> None:
    """What a rerun reads: the payload and branch stack the last one had."""

    run_id = await make_run(store)
    frames = [BranchFrame(fanout=3, index=1, count=2, key="b")]
    await enqueue(store, run_id, "build", {"take": 1})
    await enqueue(store, run_id, "review", {"other": True})
    latest = await enqueue(store, run_id, "build", {"take": 2}, branch=frames)

    async with store.reader() as reader:
        found = await reader.tasks.last_for_node(run_id, "build")
        absent = await reader.tasks.last_for_node(run_id, "never-ran")

    assert found is not None
    assert found.id == latest.id
    assert found.payload == {"take": 2}
    assert found.branch == frames
    assert absent is None


async def test_last_for_node_does_not_reach_into_another_run(store: Store) -> None:
    run_id = await make_run(store)
    other = await make_run(store)
    mine = await enqueue(store, run_id, "build")
    await enqueue(store, other, "build")

    async with store.reader() as reader:
        found = await reader.tasks.last_for_node(run_id, "build")

    assert found is not None and found.id == mine.id


# --------------------------------------------------------------------------
# finish, set_status, set_stats
# --------------------------------------------------------------------------


async def test_finish_stamps_finished_and_records_the_outcome(store: Store) -> None:
    run_id = await make_run(store)
    task = await enqueue(store, run_id)
    before = now()

    async with store.uow() as uow:
        done = await uow.tasks.finish(
            task.id, TaskStatus.done, result={"ok": True}, terminal=True
        )

    assert done is not None
    assert done.status is TaskStatus.done
    assert done.result == {"ok": True}
    assert done.terminal is True
    assert done.error is None
    assert done.finished is not None
    assert before <= done.finished <= now()


async def test_finish_records_a_failure_and_leaves_terminal_false(
    store: Store,
) -> None:
    run_id = await make_run(store)
    task = await enqueue(store, run_id)

    async with store.uow() as uow:
        failed = await uow.tasks.finish(
            task.id, TaskStatus.failed, error="RuntimeError('boom')"
        )

    assert failed is not None
    assert failed.status is TaskStatus.failed
    assert failed.error == "RuntimeError('boom')"
    assert failed.result is None
    assert failed.terminal is False
    assert failed.finished is not None


async def test_finish_returns_none_for_an_unknown_task(store: Store) -> None:
    async with store.uow() as uow:
        assert await uow.tasks.finish(4321, TaskStatus.done) is None


async def test_set_status_moves_the_attempt_and_writes_no_timestamp(
    store: Store,
) -> None:
    """An operator putting a task back to ``ready`` has not finished it."""

    run_id = await make_run(store)
    task = await enqueue(store, run_id)
    stamp = now()
    await force(store, task.id, status=TaskStatus.in_progress.value, started=stamp)

    async with store.uow() as uow:
        moved = await uow.tasks.set_status(task.id, TaskStatus.cancelled)
        missing = await uow.tasks.set_status(task.id + 10_000, TaskStatus.ready)

    assert moved is not None
    assert moved.status is TaskStatus.cancelled
    assert moved.finished is None
    assert moved.started is not None
    assert missing is None


async def test_set_stats_stores_this_attempts_entry(store: Store) -> None:
    run_id = await make_run(store)
    task = await enqueue(store, run_id)
    entry = {"model": "opus", "total_tokens": 1204, "cost": 0.0123}

    async with store.uow() as uow:
        with_stats = await uow.tasks.set_stats(task.id, entry)
    async with store.uow() as uow:
        cleared = await uow.tasks.set_stats(task.id, None)

    assert with_stats is not None and with_stats.stats == entry
    assert cleared is not None and cleared.stats is None


async def test_set_stats_returns_none_for_an_unknown_task(store: Store) -> None:
    async with store.uow() as uow:
        assert await uow.tasks.set_stats(4321, {"cost": 1.0}) is None


# --------------------------------------------------------------------------
# has_pending
# --------------------------------------------------------------------------


async def test_has_pending_is_true_for_each_outstanding_status(store: Store) -> None:
    assert PENDING == ("ready", "in_progress", "waiting")

    for status in PENDING:
        run_id = await make_run(store)
        task = await enqueue(store, run_id)
        await force(store, task.id, status=status)

        async with store.reader() as reader:
            assert await reader.tasks.has_pending(run_id) is True, status


async def test_has_pending_is_false_once_nothing_is_outstanding(
    store: Store,
) -> None:
    run_id = await make_run(store)
    first = await enqueue(store, run_id, "build")
    second = await enqueue(store, run_id, "review")

    async with store.uow() as uow:
        await uow.tasks.finish(first.id, TaskStatus.done)
    async with store.reader() as reader:
        assert await reader.tasks.has_pending(run_id) is True

    async with store.uow() as uow:
        await uow.tasks.finish(second.id, TaskStatus.dead_letter, error="gave up")
    async with store.reader() as reader:
        assert await reader.tasks.has_pending(run_id) is False


async def test_has_pending_ignores_other_runs(store: Store) -> None:
    run_id = await make_run(store)
    other = await make_run(store)
    await enqueue(store, other, "build")

    async with store.reader() as reader:
        assert await reader.tasks.has_pending(run_id) is False


# --------------------------------------------------------------------------
# terminal_tasks
# --------------------------------------------------------------------------


def frame(index: int, fanout: int = 1, count: int = 2) -> BranchFrame:
    return BranchFrame(fanout=fanout, index=index, count=count, key=f"k{index}")


async def terminal(
    store: Store, run_id: str, node: str, branch: list[BranchFrame], value: Any
) -> int:
    task = await enqueue(store, run_id, node, branch=branch)
    async with store.uow() as uow:
        await uow.tasks.finish(task.id, TaskStatus.done, result=value, terminal=True)
    return task.id


async def test_terminal_tasks_are_ordered_by_the_branch_index_path(
    store: Store,
) -> None:
    """04 §Routing edge cases: branch order is the frame indexes, outermost
    first — never the order the branches happened to finish in."""

    run_id = await make_run(store)
    # Deliberately created out of order, and nested branches interleaved
    # with their parents.
    deep_one = await terminal(
        store, run_id, "d1", [frame(0), frame(1, fanout=5)], "0.1"
    )
    outer_one = await terminal(store, run_id, "o1", [frame(1)], "1")
    top = await terminal(store, run_id, "top", [], "top")
    deep_zero = await terminal(
        store, run_id, "d0", [frame(0), frame(0, fanout=5)], "0.0"
    )
    outer_zero = await terminal(store, run_id, "o0", [frame(0)], "0")

    async with store.reader() as reader:
        ordered = await reader.tasks.terminal_tasks(run_id)

    assert [row.id for row in ordered] == [
        top,
        outer_zero,
        deep_zero,
        deep_one,
        outer_one,
    ]
    assert [row.result for row in ordered] == ["top", "0", "0.0", "0.1", "1"]


async def test_terminal_tasks_tie_break_on_id_within_one_branch(
    store: Store,
) -> None:
    run_id = await make_run(store)
    first = await terminal(store, run_id, "a", [frame(0)], "a")
    second = await terminal(store, run_id, "b", [frame(0)], "b")

    async with store.reader() as reader:
        ordered = await reader.tasks.terminal_tasks(run_id)

    assert [row.id for row in ordered] == [first, second]


async def test_terminal_tasks_excludes_non_terminal_attempts_and_other_runs(
    store: Store,
) -> None:
    run_id = await make_run(store)
    other = await make_run(store)
    kept = await terminal(store, run_id, "done", [], "value")
    plain = await enqueue(store, run_id, "still-ready")
    async with store.uow() as uow:
        await uow.tasks.finish(plain.id, TaskStatus.done, result="routed onward")
    await terminal(store, other, "elsewhere", [], "not mine")

    async with store.reader() as reader:
        ordered = await reader.tasks.terminal_tasks(run_id)

    assert [row.id for row in ordered] == [kept]


# --------------------------------------------------------------------------
# reset_for_recovery
# --------------------------------------------------------------------------


async def test_reset_for_recovery_touches_only_the_interrupted_statuses(
    store: Store,
) -> None:
    """04 §Recovery on startup, step 1.

    ``done``, ``failed``, ``dead_letter`` and ``cancelled`` are decisions
    somebody made; ``cancelled`` in particular is operator intent that a
    restart must not undo.
    """

    assert INTERRUPTED == ("in_progress", "waiting")

    run_id = await make_run(store)
    rows: dict[str, int] = {}
    for status in TaskStatus:
        task = await enqueue(store, run_id, status.value)
        await force(
            store,
            task.id,
            status=status.value,
            started=OLD,
            token_hash=token_hash(f"token-{status.value}"),
        )
        rows[status.value] = task.id

    async with store.uow() as uow:
        recovered = await uow.tasks.reset_for_recovery()

    assert recovered == sorted(rows[status] for status in INTERRUPTED)

    async with store.reader() as reader:
        after = {row.node: row for row in await reader.tasks.list_for_run(run_id)}

    for status in TaskStatus:
        row = after[status.value]
        if status.value in INTERRUPTED:
            assert row.status is TaskStatus.ready
            assert row.started is None
            assert row.token_hash is None
        else:
            assert row.status is status
            assert row.started == OLD
            assert row.token_hash == token_hash(f"token-{status.value}")


async def test_reset_for_recovery_clears_the_hash_of_a_dead_attempts_token(
    store: Store,
) -> None:
    """A token captured from an attempt that died authenticates nothing."""

    run_id = await make_run(store)
    task = await enqueue(store, run_id)
    await force(
        store,
        task.id,
        status=TaskStatus.waiting.value,
        started=OLD,
        token_hash=token_hash("captured"),
    )

    async with store.uow() as uow:
        await uow.tasks.reset_for_recovery()

    async with store.reader() as reader:
        assert await reader.tasks.by_token_hash(token_hash("captured")) is None
    assert (await raw(store, task.id))["token_hash"] is None


async def test_reset_for_recovery_leaves_the_excluded_rows_alone(
    store: Store,
) -> None:
    """``exclude`` is the runtime case: a row an attempt of this process holds.

    A recovery run for one workflow after start (22 §Add step 3) can
    find a row already claimed by a tick that ran between the bind and
    the sweep; resetting it would put two attempts on one task (D229).
    """

    run_id = await make_run(store)
    held = await enqueue(store, run_id, "held")
    orphan = await enqueue(store, run_id, "orphan")
    for task in (held, orphan):
        await force(
            store,
            task.id,
            status=TaskStatus.in_progress.value,
            started=OLD,
            token_hash=token_hash(f"token-{task.id}"),
        )

    async with store.uow() as uow:
        recovered = await uow.tasks.reset_for_recovery(["demo"], exclude=[held.id])

    assert recovered == [orphan.id]
    assert (await raw(store, held.id))["status"] == TaskStatus.in_progress.value
    assert (await raw(store, held.id))["token_hash"] == token_hash(f"token-{held.id}")
    assert (await raw(store, orphan.id))["status"] == TaskStatus.ready.value


async def test_reset_for_recovery_spans_every_run_and_reports_nothing_when_idle(
    store: Store,
) -> None:
    """Recovery is a startup sweep, not a per-run question."""

    first = await make_run(store)
    second = await make_run(store)
    here = await enqueue(store, first, "build")
    there = await enqueue(store, second, "build")
    await force(store, here.id, status=TaskStatus.in_progress.value)
    await force(store, there.id, status=TaskStatus.waiting.value)

    async with store.uow() as uow:
        recovered = await uow.tasks.reset_for_recovery()
    async with store.uow() as uow:
        again = await uow.tasks.reset_for_recovery()

    assert recovered == sorted([here.id, there.id])
    assert again == []


async def test_reset_for_recovery_leaves_created_alone(store: Store) -> None:
    """A recovered attempt keeps its place in the queue."""

    run_id = await make_run(store)
    task = await enqueue(store, run_id, created=now() - timedelta(hours=2))
    await force(store, task.id, status=TaskStatus.in_progress.value)

    async with store.uow() as uow:
        await uow.tasks.reset_for_recovery()

    async with store.reader() as reader:
        after = await reader.tasks.get(task.id)

    assert after is not None
    assert after.created == task.created

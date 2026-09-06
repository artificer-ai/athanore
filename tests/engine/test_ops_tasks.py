"""The destructive and re-dispatching operator verbs (T027b, 04 §Operator ops).

``cancel``, ``delete``, ``rerun``, ``retry``, ``move`` and
``set_status``, ported from v0's ``test_management.py`` to engine level;
the HTTP half lands in T044a.

Four things here are decisions rather than mechanics, and each has a test
that fails if it is reversed:

- **cancel kills the attempt after the transaction commits**, so the
  runner's cancellation arm never sees a row that is not yet
  ``cancelled``;
- **delete leaves nothing behind** — asserted per table, all nine of
  them, because a cascade that is missing one is invisible in a test that
  only looks at ``runs``;
- **``retry`` keeps ``created`` and ``move`` takes a fresh one.** A retry
  keeps its place in the queue; a move is new work and goes to the back.
  Both are asserted, together, because the asymmetry is the point;
- **a task cannot be moved into a join.** A join is dispatched by its
  arrivals, and a task moved into one would wait forever for branches
  that already arrived.
"""

from __future__ import annotations

import asyncio

import pytest

from athanore.engine import Engine
from athanore.engine.errors import Conflict, NotFound, UnknownNode
from athanore.engine.ops import (
    MANUAL_RETRY_REASON,
    MOVE_REASON,
    RERUN_REASON,
)
from athanore.engine.pools import Pool
from athanore.events.bus import EventBus
from athanore.events.names import EventName
from athanore.store.rows import EventRow, RunRow, RunStatus, TaskRow, TaskStatus
from athanore.store.tables import (
    answers,
    events,
    join_arrivals,
    log_entries,
    requests,
    runs,
    stream_chunks,
    submissions,
    tasks,
)
from athanore.store.uow import Store
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------


class Sleeper:
    """A one-node workflow whose body waits to be cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.runs = 0

    def workflow(self, name: str = "sleepy") -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True)
        async def only() -> str:
            self.runs += 1
            self.started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            return "landed"  # pragma: no cover - the sleep does not return

        return wf


class Flaky:
    """A one-node workflow that fails until it is told to stop failing."""

    def __init__(self) -> None:
        self.attempts = 0
        self.fail = True

    def workflow(self, name: str = "flaky") -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True, retries=1)
        async def only() -> str:
            self.attempts += 1
            if self.fail:
                raise RuntimeError("boom")
            return "landed"

        return wf


def branching(name: str = "branching") -> Workflow:
    """`a` routes to `b` or `c`; nothing runs unless a pool lets it."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def a(b, c):  # type: ignore[no-untyped-def]
        return b

    @wf.node()
    async def b() -> str:
        return "b"

    @wf.node()
    async def c() -> str:
        return "c"

    return wf


def fanning(name: str = "fanning") -> Workflow:
    """A fan-out of two closed by a join, so a join node exists to aim at."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def split(branch):  # type: ignore[no-untyped-def]
        return [branch(1), branch(2)]

    @wf.node()
    async def branch(gather, *, payload):  # type: ignore[no-untyped-def]
        return gather(payload * 10)

    @wf.node(join=True)
    async def gather(*, payload):  # type: ignore[no-untyped-def]
        return [item["value"] for item in payload]

    return wf


def parked(engines, workflow: Workflow, capacity: int = 0) -> Engine:
    """An engine with ``workflow`` registered on a pool of ``capacity``."""

    engine: Engine = engines()
    engine.register(workflow.finalize(), Pool("test", capacity))
    return engine


# --------------------------------------------------------------------------
# Reading the store back
# --------------------------------------------------------------------------


async def run_of(store: Store, run_id: str) -> RunRow | None:
    async with store.reader() as reader:
        return await reader.runs.get(run_id)


async def tasks_of(store: Store, run_id: str) -> list[TaskRow]:
    async with store.reader() as reader:
        return await reader.tasks.list_for_run(run_id)


async def task_of(store: Store, task_id: int) -> TaskRow:
    async with store.reader() as reader:
        row = await reader.tasks.get(task_id)
    assert row is not None
    return row


async def events_of(store: Store, run_id: str) -> list[EventRow]:
    async with store.reader() as reader:
        return await reader.events.list_for_run(run_id)


async def named(store: Store, run_id: str, name: EventName) -> list[EventRow]:
    return [row for row in await events_of(store, run_id) if row.name == name]


async def _run_is(store: Store, run_id: str, status: RunStatus) -> bool:
    row = await run_of(store, run_id)
    return row is not None and row.status is status


async def _task_is(store: Store, task_id: int, status: TaskStatus) -> bool:
    return (await task_of(store, task_id)).status is status


async def _at(store: Store, run_id: str, node: str) -> list[TaskRow]:
    return [task for task in await tasks_of(store, run_id) if task.node == node]


# --------------------------------------------------------------------------
# cancel
# --------------------------------------------------------------------------


async def test_cancel_kills_a_sleeping_body_and_marks_every_task(
    engines, store: Store, wait_for, wait_until
) -> None:
    """One attempt in flight, one queued behind it; both end `cancelled`."""

    sleeper = Sleeper()
    engine = parked(engines, sleeper.workflow(), capacity=1)
    running = await engine.ops.submit("sleepy", "first")
    await engine.start()
    await wait_for(sleeper.started)
    (live,) = await tasks_of(store, running.id)
    queued = await engine.ops.submit("sleepy", "second")

    cancelled = await engine.ops.cancel(running.id)

    assert cancelled == [live.id]
    await wait_for(sleeper.cancelled)
    assert await _task_is(store, live.id, TaskStatus.cancelled)
    assert await _run_is(store, running.id, RunStatus.cancelled)
    (event,) = await named(store, running.id, EventName.run_cancelled)
    assert event.data == {"cancelled_tasks": [live.id]}
    (marked,) = await named(store, running.id, EventName.task_cancelled)
    assert marked.data == {
        "node": "only",
        "from": TaskStatus.in_progress.value,
        "reason": "cancel",
    }
    # The slot came back, so the run queued behind it dispatches.
    await wait_until(lambda: _run_is(store, queued.id, RunStatus.running))


async def test_cancel_marks_ready_and_waiting_tasks_too(engines, store: Store) -> None:
    """Everything outstanding, not only what this process was running."""

    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    async with store.uow() as uow:
        parked_task = await uow.tasks.enqueue(run.id, "b", None, 0, False)
        await uow.tasks.set_status(parked_task.id, TaskStatus.waiting.value)
        done = await uow.tasks.enqueue(run.id, "c", None, 0, False)
        await uow.tasks.finish(done.id, TaskStatus.done.value)

    cancelled = await engine.ops.cancel(run.id)

    assert parked_task.id in cancelled
    assert done.id not in cancelled, "a finished task is history, not work"
    assert await _task_is(store, done.id, TaskStatus.done)


async def test_cancel_refuses_a_run_that_has_already_ended(
    engines, store: Store
) -> None:
    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    await engine.ops.cancel(run.id)

    with pytest.raises(Conflict, match="already ended"):
        await engine.ops.cancel(run.id)


async def test_cancel_of_an_unknown_run_is_not_found(engines) -> None:
    engine = parked(engines, branching())

    with pytest.raises(NotFound):
        await engine.ops.cancel("01JNOPE")


# --------------------------------------------------------------------------
# delete
# --------------------------------------------------------------------------


async def test_delete_leaves_no_row_in_any_of_the_nine_tables(
    engines, store: Store
) -> None:
    """Per table, not just `runs`: a cascade that misses one is invisible.

    A run is given a row in every table that hangs off it — the eight
    cascades of 07 §Schema notes plus ``events``, which has no foreign
    key and is swept by hand — and a second run keeps its own rows, so
    the assertion is a delete rather than an empty database.
    """

    engine = parked(engines, branching())
    doomed = await engine.ops.submit("branching", "doomed")
    keeper = await engine.ops.submit("branching", "keeper")
    (task,) = await tasks_of(store, doomed.id)
    async with store.uow() as uow:
        await uow.log.append(doomed.id, "a", "user", "a note")
        await uow.submissions.insert(task.id, {"value": 1})
        await uow.stream.append_batch(task.id, [(1, "text", "hello")])
        request = await uow.requests.create(
            doomed.id,
            task.id,
            "which one?",
            mode="text",
            source="node",
            kind="question",
        )
        await uow.requests.answer(request.id, "user", value="that one")
        await uow.joins.arrive(
            run_id=doomed.id,
            join_node="b",
            fanout_task=task.id,
            index=0,
            key=None,
            value=1,
            from_task=task.id,
            count=2,
        )

    #: One column per table that names the deleted run, directly or
    #: through the row above it. ``answers`` names only its request, so
    #: it is counted through the request that was deleted with it.
    owned = (
        (runs, runs.c.id, doomed.id),
        (tasks, tasks.c.run_id, doomed.id),
        (log_entries, log_entries.c.run_id, doomed.id),
        (events, events.c.run_id, doomed.id),
        (submissions, submissions.c.task_id, task.id),
        (stream_chunks, stream_chunks.c.task_id, task.id),
        (requests, requests.c.run_id, doomed.id),
        (answers, answers.c.request_id, request.id),
        (join_arrivals, join_arrivals.c.run_id, doomed.id),
    )
    for table, column, owner in owned:
        assert await _count(store, table, column, owner) > 0, (
            f"the fixture wrote no {table.name} row to delete"
        )

    await engine.ops.delete(doomed.id)

    for table, column, owner in owned:
        left = await _count(store, table, column, owner)
        if table is events:
            # `events` has no foreign key precisely so that this one can
            # be written after the sweep: `run.deleted` is the last event
            # of a run, and a cascade would refuse it (D83, 18 §Runs).
            assert [row.name for row in await events_of(store, doomed.id)] == [
                EventName.run_deleted
            ]
            continue
        assert left == 0, f"{table.name} still has rows of the deleted run"

    assert await run_of(store, keeper.id) is not None
    assert await tasks_of(store, keeper.id) != []
    assert await events_of(store, keeper.id) != []


async def _count(store: Store, table, column, owner) -> int:
    """How many rows of ``table`` belong to ``owner``."""

    async with store.read() as conn:
        result = await conn.execute(table.select().where(column == owner))
    return len(result.mappings().all())


async def test_delete_announces_the_run_it_removed(
    engines, store: Store, bus: EventBus
) -> None:
    """`run.deleted` is the last event of a run and reaches SSE live."""

    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    seen: list[str] = []
    subscription = bus.subscribe([EventName.run_deleted])

    await engine.ops.delete(run.id)

    while not subscription.queue.empty():
        seen.append(subscription.queue.get_nowait().name)
    subscription.close()
    assert seen == [EventName.run_deleted]
    assert [row.name for row in await events_of(store, run.id)] == [
        EventName.run_deleted
    ], "everything before it went with the run (D83)"


async def test_delete_kills_a_running_attempt(engines, store: Store, wait_for) -> None:
    """The attempt is cancelled against rows that still exist."""

    sleeper = Sleeper()
    engine = parked(engines, sleeper.workflow(), capacity=1)
    run = await engine.ops.submit("sleepy", "a title")
    await engine.start()
    await wait_for(sleeper.started)

    await engine.ops.delete(run.id)

    await wait_for(sleeper.cancelled)
    assert await run_of(store, run.id) is None


async def test_delete_of_an_unknown_run_is_not_found(engines) -> None:
    engine = parked(engines, branching())

    with pytest.raises(NotFound):
        await engine.ops.delete("01JNOPE")


# --------------------------------------------------------------------------
# rerun
# --------------------------------------------------------------------------


async def test_rerun_continues_the_attempt_count_with_the_last_payload(
    engines, store: Store, wait_until
) -> None:
    """The port of v0's `test_rerun_node`: the node runs a second time."""

    engine = parked(engines, branching(), capacity=1)
    await engine.start()
    run = await engine.ops.submit("branching", "a title")
    await wait_until(lambda: _run_is(store, run.id, RunStatus.completed))
    (first,) = await _at(store, run.id, "b")

    task = await engine.ops.rerun(run.id, "b")

    assert task.node == "b"
    assert task.attempt == first.attempt + 1
    assert task.payload == first.payload
    assert task.lineage == {"from": first.id, "reason": RERUN_REASON}
    await wait_until(lambda: _run_is(store, run.id, RunStatus.completed))
    assert len(await _at(store, run.id, "b")) == 2


async def test_rerun_re_opens_a_terminal_run(engines, store: Store) -> None:
    """03 §State machines: retry, rerun and move are the three edges back."""

    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    await engine.ops.cancel(run.id)

    await engine.ops.rerun(run.id, "a")

    assert await _run_is(store, run.id, RunStatus.running)
    row = await run_of(store, run.id)
    assert row is not None and row.finished is None
    (updated,) = await named(store, run.id, EventName.run_updated)
    assert updated.data == {"changed": {"status": "running"}}


async def test_rerun_of_a_node_that_never_ran_starts_it(engines, store: Store) -> None:
    """`node exists` is the precondition; a first attempt is a valid one."""

    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")

    task = await engine.ops.rerun(run.id, "c")

    assert (task.node, task.attempt, task.payload) == ("c", 1, None)
    assert task.lineage == {"reason": RERUN_REASON}


async def test_rerun_of_a_join_replays_its_stored_arrivals(
    engines, store: Store, wait_until
) -> None:
    """Including a branch that arrived after the join had already fired.

    T024b records a late arrival and enqueues no second join task, which
    leaves ``rerun`` as the operator's way of getting that branch into
    the join body — so the payload comes from the arrivals table, not
    from the payload the first join task was handed.
    """

    engine = parked(engines, fanning(), capacity=4)
    await engine.start()
    run = await engine.ops.submit("fanning", "a title")
    await wait_until(lambda: _run_is(store, run.id, RunStatus.completed))
    (first,) = await _at(store, run.id, "gather")
    (split,) = await _at(store, run.id, "split")
    async with store.uow() as uow:
        await uow.joins.arrive(
            run_id=run.id,
            join_node="gather",
            fanout_task=split.id,
            index=2,
            key=3,
            value=30,
            from_task=None,
            count=3,
        )

    task = await engine.ops.rerun(run.id, "gather")

    assert [item["value"] for item in task.payload] == [10, 20, 30]
    assert task.attempt == first.attempt + 1
    assert task.lineage is not None
    assert task.lineage["from"] == split.id, "a join names the fan-out it closes"
    await wait_until(lambda: _task_is(store, task.id, TaskStatus.done))
    assert (await task_of(store, task.id)).result == [10, 20, 30]


async def test_rerun_of_a_join_that_never_fired_is_refused(
    engines, store: Store
) -> None:
    """There are no arrivals to replay, and inventing an empty list lies."""

    engine = parked(engines, fanning())
    run = await engine.ops.submit("fanning", "a title")

    with pytest.raises(Conflict, match="has not fired"):
        await engine.ops.rerun(run.id, "gather")


async def test_rerun_refuses_a_node_the_workflow_does_not_have(engines) -> None:
    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")

    with pytest.raises(UnknownNode):
        await engine.ops.rerun(run.id, "nope")


# --------------------------------------------------------------------------
# retry
# --------------------------------------------------------------------------


async def test_retry_queues_another_attempt_and_keeps_created(
    engines, store: Store, wait_until
) -> None:
    """The port of v0's `test_retry_failed_task`, plus the `created` rule.

    ``created DESC`` is the dispatch order's last tiebreaker, so a retry
    that took a fresh timestamp would overtake everything enqueued while
    the attempt it replaces was running.
    """

    flaky = Flaky()
    engine = parked(engines, flaky.workflow(), capacity=1)
    await engine.start()
    run = await engine.ops.submit("flaky", "a title")
    await wait_until(lambda: _run_is(store, run.id, RunStatus.failed))
    dead = [task for task in await tasks_of(store, run.id) if task.terminal is False][
        -1
    ]
    assert dead.status is TaskStatus.dead_letter
    flaky.fail = False

    retry = await engine.ops.retry(dead.id)

    assert retry.attempt == dead.attempt + 1
    assert retry.created == dead.created, "a retry keeps its place in the queue"
    assert retry.payload == dead.payload
    assert retry.priority == dead.priority
    assert retry.lineage == {"from": dead.id, "reason": MANUAL_RETRY_REASON}
    await wait_until(lambda: _run_is(store, run.id, RunStatus.completed))
    assert flaky.attempts == 2, "one attempt that failed, and the retry"


async def test_retry_re_opens_a_terminal_run(engines, store: Store) -> None:
    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    (task,) = await tasks_of(store, run.id)
    await engine.ops.cancel(run.id)

    await engine.ops.retry(task.id)

    assert await _run_is(store, run.id, RunStatus.running)


async def test_retry_refuses_a_task_that_has_not_stopped(engines, store: Store) -> None:
    """Two attempts of one task is exactly what the claim makes impossible."""

    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    (task,) = await tasks_of(store, run.id)

    with pytest.raises(Conflict, match="has not stopped"):
        await engine.ops.retry(task.id)


async def test_retry_of_an_unknown_task_is_not_found(engines) -> None:
    engine = parked(engines, branching())

    with pytest.raises(NotFound):
        await engine.ops.retry(4321)


# --------------------------------------------------------------------------
# move
# --------------------------------------------------------------------------


async def test_move_cancels_the_task_and_queues_it_at_the_target(
    engines, store: Store
) -> None:
    """The port of v0's `test_move_task`, with the lineage v1 added."""

    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    (task,) = await tasks_of(store, run.id)

    moved = await engine.ops.move(task.id, "c")

    assert moved.node == "c"
    assert moved.status is TaskStatus.ready
    assert moved.payload == task.payload
    assert moved.attempt == 1
    assert moved.lineage == {"from": task.id, "reason": MOVE_REASON}
    assert await _task_is(store, task.id, TaskStatus.cancelled)
    (cancelled,) = await named(store, run.id, EventName.task_cancelled)
    assert cancelled.data["reason"] == MOVE_REASON
    (event,) = await named(store, run.id, EventName.task_moved)
    assert event.data == {"node": "a", "to": "c", "new_task_id": moved.id}


async def test_move_takes_a_fresh_created_where_retry_keeps_the_old_one(
    engines, store: Store
) -> None:
    """The asymmetry of 04, asserted as one comparison.

    A retry is the same work again and keeps its place in the queue; a
    move is new work at a different node and goes to the back.
    """

    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    (task,) = await tasks_of(store, run.id)
    await engine.ops.set_status(task.id, "dead_letter")

    retry = await engine.ops.retry(task.id)
    moved = await engine.ops.move(task.id, "c")

    assert retry.created == task.created
    assert moved.created > task.created


async def test_move_into_a_join_is_refused(engines, store: Store) -> None:
    """A join is dispatched by its arrivals, never by a task placed in it."""

    engine = parked(engines, fanning())
    run = await engine.ops.submit("fanning", "a title")
    (task,) = await tasks_of(store, run.id)

    with pytest.raises(Conflict, match="join"):
        await engine.ops.move(task.id, "gather")

    assert await _task_is(store, task.id, TaskStatus.ready), "nothing was written"
    assert await _at(store, run.id, "gather") == []


async def test_move_refuses_a_node_the_workflow_does_not_have(
    engines, store: Store
) -> None:
    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    (task,) = await tasks_of(store, run.id)

    with pytest.raises(UnknownNode):
        await engine.ops.move(task.id, "nope")


async def test_move_kills_the_attempt_it_cancels(
    engines, store: Store, wait_for, wait_until
) -> None:
    sleeper = Sleeper()
    engine: Engine = engines()
    engine.register(sleeper.workflow("two_step").finalize(), Pool("test", 1))
    run = await engine.ops.submit("two_step", "a title")
    await engine.start()
    await wait_for(sleeper.started)
    (task,) = await tasks_of(store, run.id)

    moved = await engine.ops.move(task.id, "only")

    await wait_for(sleeper.cancelled)
    assert await _task_is(store, task.id, TaskStatus.cancelled)
    await wait_until(lambda: _task_is(store, moved.id, TaskStatus.in_progress))


async def test_move_re_opens_a_terminal_run(engines, store: Store) -> None:
    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    (task,) = await tasks_of(store, run.id)
    await engine.ops.cancel(run.id)

    await engine.ops.move(task.id, "c")

    assert await _run_is(store, run.id, RunStatus.running)


# --------------------------------------------------------------------------
# set_status
# --------------------------------------------------------------------------


async def test_set_status_ready_re_dispatches(
    engines, store: Store, wait_until
) -> None:
    """A dead-lettered task put back to `ready` runs again."""

    flaky = Flaky()
    engine = parked(engines, flaky.workflow(), capacity=1)
    await engine.start()
    run = await engine.ops.submit("flaky", "a title")
    await wait_until(lambda: _run_is(store, run.id, RunStatus.failed))
    dead = (await tasks_of(store, run.id))[-1]
    flaky.fail = False

    await engine.ops.set_status(dead.id, "ready")

    await wait_until(lambda: _run_is(store, run.id, RunStatus.completed))
    assert await _task_is(store, dead.id, TaskStatus.done)
    (event,) = await named(store, run.id, EventName.task_status_set)
    assert event.data == {
        "node": "only",
        "from": TaskStatus.dead_letter.value,
        "to": TaskStatus.ready.value,
    }


async def test_set_status_cancelled_kills_the_attempt_and_says_why(
    engines, store: Store, wait_for
) -> None:
    """`task.cancelled reason=set_status` is 18's member for this path."""

    sleeper = Sleeper()
    engine = parked(engines, sleeper.workflow(), capacity=1)
    run = await engine.ops.submit("sleepy", "a title")
    await engine.start()
    await wait_for(sleeper.started)
    (task,) = await tasks_of(store, run.id)

    await engine.ops.set_status(task.id, "cancelled")

    await wait_for(sleeper.cancelled)
    assert await _task_is(store, task.id, TaskStatus.cancelled)
    (cancelled,) = await named(store, run.id, EventName.task_cancelled)
    assert cancelled.data == {
        "node": "only",
        "from": TaskStatus.in_progress.value,
        "reason": "set_status",
    }


async def test_set_status_dead_letter_files_the_task_as_failed(
    engines, store: Store
) -> None:
    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    (task,) = await tasks_of(store, run.id)

    row = await engine.ops.set_status(task.id, "dead_letter")

    assert row.status is TaskStatus.dead_letter
    assert await named(store, run.id, EventName.task_cancelled) == []


async def test_set_status_refuses_a_status_that_is_not_an_operators(
    engines, store: Store
) -> None:
    """`done`, `failed`, `in_progress` and `waiting` are the engine's own."""

    engine = parked(engines, branching())
    run = await engine.ops.submit("branching", "a title")
    (task,) = await tasks_of(store, run.id)

    with pytest.raises(ValueError):
        await engine.ops.set_status(task.id, "done")  # type: ignore[arg-type]


async def test_set_status_of_an_unknown_task_is_not_found(engines) -> None:
    engine = parked(engines, branching())

    with pytest.raises(NotFound):
        await engine.ops.set_status(4321, "ready")

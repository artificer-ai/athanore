"""The operator verbs that destroy nothing (T027a, 04 §Operator operations).

``submit``, ``edit``, ``reorder``, ``pause``, ``resume`` and
``append_log``, against a real engine — the wiring is the subject here,
so nothing is stubbed. The v0 assertions of ``test_edit_run.py``,
``test_pause.py`` and ``test_run_log.py`` are ported to this level; their
HTTP halves land in T044a.

The one that is easy to get wrong, and therefore the one this file
insists on: **pause stops the next claim, not the current body.** An
attempt in flight runs to its end and enqueues its successor; the
successor waits. Killing running work is ``cancel``, which is T027b's.
"""

from __future__ import annotations

import asyncio

import pytest

from athanore.engine import Engine
from athanore.engine.errors import Conflict, NotFound, UnknownWorkflow
from athanore.engine.ops import START_REASON, USER_NODE
from athanore.engine.pools import Pool
from athanore.events.names import EventName
from athanore.store.rows import (
    EventRow,
    LogAuthor,
    LogEntryRow,
    RunRow,
    RunStatus,
    TaskRow,
    TaskStatus,
)
from athanore.store.uow import Store
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------


class Pair:
    """A two-node workflow whose first node parks until it is let go.

    ``top`` announces that it started, waits on :attr:`go`, and routes to
    ``bottom``; ``bottom`` records that it ran. Between the two there is a
    moment where exactly one task is in flight and exactly one is about
    to be — which is the window every pause assertion needs.
    """

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.go = asyncio.Event()
        self.top_done = asyncio.Event()
        self.bottom_done = asyncio.Event()

    def workflow(self, name: str = "pair") -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True)
        async def top(bottom):  # type: ignore[no-untyped-def]
            self.started.set()
            await self.go.wait()
            self.top_done.set()
            return bottom

        @wf.node()
        async def bottom() -> str:
            self.bottom_done.set()
            return "landed"

        return wf


def trivial(name: str = "trivial") -> Workflow:
    """A one-node workflow that returns immediately."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def only() -> str:
        return "done"

    return wf


def parked(engines, workflow: Workflow, capacity: int = 0) -> Engine:
    """An engine with ``workflow`` registered on a pool of ``capacity``.

    ``capacity=0`` is the default because most of these assertions are
    about the queue rather than about running anything: a parked pool
    means a submitted run stays exactly as the operation left it.
    """

    engine: Engine = engines()
    engine.register(workflow.finalize(), Pool("test", capacity))
    return engine


# --------------------------------------------------------------------------
# Reading the store back
# --------------------------------------------------------------------------


async def run_of(store: Store, run_id: str) -> RunRow:
    async with store.reader() as reader:
        row = await reader.runs.get(run_id)
    assert row is not None
    return row


async def tasks_of(store: Store, run_id: str) -> list[TaskRow]:
    async with store.reader() as reader:
        return await reader.tasks.list_for_run(run_id)


async def events_of(store: Store, run_id: str) -> list[EventRow]:
    async with store.reader() as reader:
        return await reader.events.list_for_run(run_id)


async def named(store: Store, run_id: str, name: EventName) -> list[EventRow]:
    return [row for row in await events_of(store, run_id) if row.name == name]


async def log_of(store: Store, run_id: str) -> list[LogEntryRow]:
    async with store.reader() as reader:
        return await reader.log.list(run_id)


async def claimable(store: Store, workflows: list[str]) -> list[int]:
    """What the dispatch query would take right now, without running it.

    The claim is the only place ``paused`` is enforced, so this is how a
    pause assertion is made without a scheduler in the way. The rows it
    claims are rolled back, so the store is untouched.
    """

    ids: list[int] = []
    async with store.read() as conn:
        from athanore.store.repos.tasks import claim_statement

        result = await conn.execute(claim_statement(conn.dialect.name, 10, workflows))
        ids = [int(row.id) for row in result]
    return ids


# --------------------------------------------------------------------------
# submit
# --------------------------------------------------------------------------


async def test_submit_queues_a_run_and_its_start_task(engines, store: Store) -> None:
    """A run is `queued` until something claims it (03 §Run)."""

    engine = parked(engines, trivial())

    run = await engine.ops.submit("trivial", "a title", "a description")

    assert run.status is RunStatus.queued
    assert run.title == "a title"
    assert run.description == "a description"
    (task,) = await tasks_of(store, run.id)
    assert task.node == "only"
    assert task.status is TaskStatus.ready
    assert task.attempt == 1
    assert task.payload == {"title": "a title", "description": "a description"}
    assert task.lineage == {"reason": START_REASON}


async def test_submit_reads_the_graph_from_the_registry_at_each_call(
    engines, store: Store
) -> None:
    """The start node is the registered edition's, per call (T083).

    A live ``replace`` swaps ``engine.graphs[name]``; the operations
    never cache a graph, so the next ``submit`` queues the new start
    node with nothing else changing.
    """

    engine = parked(engines, trivial())
    before = await engine.ops.submit("trivial", "before")

    renamed = Workflow("trivial")

    @renamed.node(start=True)
    async def begin() -> str:
        return "done"

    engine.graphs["trivial"] = renamed.finalize()
    after = await engine.ops.submit("trivial", "after")

    (old,) = await tasks_of(store, before.id)
    (new,) = await tasks_of(store, after.id)
    assert (old.node, new.node) == ("only", "begin")


async def test_submit_announces_the_run_and_the_task(engines, store: Store) -> None:
    """One transaction, two events, in the order they happened (18)."""

    engine = parked(engines, trivial())

    run = await engine.ops.submit("trivial", "a title")

    assert [row.name for row in await events_of(store, run.id)] == [
        EventName.run_created,
        EventName.task_enqueued,
    ]
    created, enqueued = await events_of(store, run.id)
    assert created.data == {
        "workflow": "trivial",
        "title": "a title",
        "position": run.position,
    }
    assert enqueued.data["reason"] == START_REASON
    assert enqueued.data["payload_present"] is True
    assert enqueued.data["branch"] == []
    assert "from_task" not in enqueued.data, "a start task comes from nothing"


async def test_submit_refuses_a_workflow_that_is_not_registered(engines) -> None:
    """The name resolves to nothing, so there is no run to make."""

    engine = parked(engines, trivial())

    with pytest.raises(UnknownWorkflow, match="nowhere"):
        await engine.ops.submit("nowhere", "a title")


async def test_submit_refuses_an_empty_title(engines) -> None:
    """A run with no title is unfindable in every list that shows one."""

    engine = parked(engines, trivial())

    with pytest.raises(Conflict):
        await engine.ops.submit("trivial", "   ")


async def test_submit_wakes_the_scheduler(engines, store: Store, wait_until) -> None:
    """The run dispatches without waiting for a tick (04 §The loop)."""

    engine = parked(engines, trivial(), capacity=1)
    await engine.start()

    run = await engine.ops.submit("trivial", "a title")

    await wait_until(lambda: _run_is(store, run.id, RunStatus.completed))


# --------------------------------------------------------------------------
# edit
# --------------------------------------------------------------------------


async def test_edit_changes_one_field_and_leaves_the_other(
    engines, store: Store
) -> None:
    """A partial edit is partial: `None` means "leave it" (v0 test_edit_run)."""

    engine = parked(engines, trivial())
    run = await engine.ops.submit("trivial", "old", "old desc")

    await engine.ops.edit(run.id, title="new")
    assert (await run_of(store, run.id)).description == "old desc"

    await engine.ops.edit(run.id, description="new desc")
    row = await run_of(store, run.id)
    assert (row.title, row.description) == ("new", "new desc")


async def test_edit_announces_only_what_changed(engines, store: Store) -> None:
    """`run.updated` is a diff, and a diff of one field names one field."""

    engine = parked(engines, trivial())
    run = await engine.ops.submit("trivial", "old", "old desc")

    await engine.ops.edit(run.id, title="new", description="old desc")

    (updated,) = await named(store, run.id, EventName.run_updated)
    assert updated.data == {"changed": {"title": "new"}}


async def test_an_edit_that_changes_nothing_writes_nothing(
    engines, store: Store
) -> None:
    """Re-sending the values already stored is not a change to announce."""

    engine = parked(engines, trivial())
    run = await engine.ops.submit("trivial", "same", "same desc")
    before = await run_of(store, run.id)

    await engine.ops.edit(run.id, title="same", description="same desc")

    assert await named(store, run.id, EventName.run_updated) == []
    assert (await run_of(store, run.id)).updated == before.updated


async def test_edit_rejects_an_empty_title(engines, store: Store) -> None:
    """The one precondition 04 gives `edit`, whitespace included."""

    engine = parked(engines, trivial())
    run = await engine.ops.submit("trivial", "keep me")

    for bad in ("", "   "):
        with pytest.raises(Conflict):
            await engine.ops.edit(run.id, title=bad)

    assert (await run_of(store, run.id)).title == "keep me"
    assert await named(store, run.id, EventName.run_updated) == []


async def test_edit_of_an_unknown_run_is_not_found(engines) -> None:
    engine = parked(engines, trivial())

    with pytest.raises(NotFound):
        await engine.ops.edit("01JNOPE", title="x")


# --------------------------------------------------------------------------
# reorder
# --------------------------------------------------------------------------


async def test_reorder_swaps_with_the_neighbour_above(engines, store: Store) -> None:
    """`direction=-1` is one swap, not a renumbering (D57)."""

    engine = parked(engines, trivial())
    first = await engine.ops.submit("trivial", "first")
    second = await engine.ops.submit("trivial", "second")

    position = await engine.ops.reorder(second.id, direction=-1)

    assert position == first.position
    assert (await run_of(store, first.id)).position == second.position
    (event,) = await named(store, second.id, EventName.run_reordered)
    assert event.data == {"position": first.position, "previous": second.position}


async def test_reorder_at_the_end_is_a_no_op_that_reports_its_position(
    engines, store: Store
) -> None:
    """There is no neighbour, so nothing moves and nothing is announced."""

    engine = parked(engines, trivial())
    first = await engine.ops.submit("trivial", "first")
    await engine.ops.submit("trivial", "second")

    assert await engine.ops.reorder(first.id, direction=-1) == first.position
    assert await named(store, first.id, EventName.run_reordered) == []


async def test_reorder_to_an_index_clamps_to_the_list(engines, store: Store) -> None:
    """`index` is zero-based and clamped at both ends (D57)."""

    engine = parked(engines, trivial())
    first = await engine.ops.submit("trivial", "first")
    second = await engine.ops.submit("trivial", "second")
    third = await engine.ops.submit("trivial", "third")

    assert await engine.ops.reorder(third.id, index=0) == 1
    assert await _order(store) == [third.id, first.id, second.id]

    assert await engine.ops.reorder(third.id, index=99) == 3
    assert await _order(store) == [first.id, second.id, third.id]


async def test_reorder_takes_exactly_one_of_direction_and_index(engines) -> None:
    """Both or neither is a caller's bug, not a state conflict."""

    engine = parked(engines, trivial())
    run = await engine.ops.submit("trivial", "a title")

    with pytest.raises(ValueError, match="exactly one"):
        await engine.ops.reorder(run.id)
    with pytest.raises(ValueError, match="exactly one"):
        await engine.ops.reorder(run.id, direction=1, index=0)
    with pytest.raises(ValueError, match="-1 or 1"):
        await engine.ops.reorder(run.id, direction=2)


# --------------------------------------------------------------------------
# pause and resume
# --------------------------------------------------------------------------


async def test_pause_blocks_the_next_claim_while_the_body_finishes(
    engines, store: Store, wait_for, wait_until
) -> None:
    """The port of v0's `test_pause_blocks_dispatch`, at engine level.

    ``top`` is inside its body when the run is paused. It finishes,
    records ``done`` and enqueues ``bottom`` — and ``bottom`` sits there,
    because the claim excludes a paused run.
    """

    pair = Pair()
    engine = parked(engines, pair.workflow(), capacity=1)
    run = await engine.ops.submit("pair", "a title")
    await engine.start()
    await wait_for(pair.started)

    await engine.ops.pause(run.id)
    pair.go.set()
    await wait_for(pair.top_done)
    await wait_until(lambda: _has_node(store, run.id, "bottom"))

    top = await _task_at(store, run.id, "top")
    bottom = await _task_at(store, run.id, "bottom")
    assert top.status is TaskStatus.done, "the in-flight body ran to its end"
    assert await claimable(store, ["pair"]) == [], "a paused run is not claimed"
    await asyncio.sleep(0.1)
    assert (await _task_at(store, run.id, "bottom")).id == bottom.id
    assert (await _task_at(store, run.id, "bottom")).status is TaskStatus.ready
    assert not pair.bottom_done.is_set()

    await engine.ops.resume(run.id)

    await wait_for(pair.bottom_done)
    await wait_until(lambda: _run_is(store, run.id, RunStatus.completed))


async def test_pause_and_resume_announce_themselves(engines, store: Store) -> None:
    engine = parked(engines, trivial())
    run = await engine.ops.submit("trivial", "a title")

    paused = await engine.ops.pause(run.id)
    resumed = await engine.ops.resume(run.id)

    assert paused.status is RunStatus.paused
    assert resumed.status is RunStatus.running
    assert [row.name for row in await events_of(store, run.id)][-2:] == [
        EventName.run_paused,
        EventName.run_resumed,
    ]


async def test_pause_refuses_a_run_that_is_not_queued_or_running(
    engines, store: Store, wait_until
) -> None:
    """A completed run has no next claim to stop (v0's 409 cases)."""

    engine = parked(engines, trivial(), capacity=1)
    await engine.start()
    run = await engine.ops.submit("trivial", "a title")
    await wait_until(lambda: _run_is(store, run.id, RunStatus.completed))

    with pytest.raises(Conflict, match="completed"):
        await engine.ops.pause(run.id)


async def test_resume_refuses_a_run_that_is_not_paused(engines) -> None:
    engine = parked(engines, trivial())
    run = await engine.ops.submit("trivial", "a title")

    with pytest.raises(Conflict, match="queued"):
        await engine.ops.resume(run.id)


async def test_pause_and_resume_of_an_unknown_run_are_not_found(engines) -> None:
    engine = parked(engines, trivial())

    with pytest.raises(NotFound):
        await engine.ops.pause("01JNOPE")
    with pytest.raises(NotFound):
        await engine.ops.resume("01JNOPE")


# --------------------------------------------------------------------------
# append_log
# --------------------------------------------------------------------------


async def test_append_log_files_the_note_under_the_one_live_node(
    engines, store: Store, wait_for
) -> None:
    """The port of v0's `test_run_log_append_in_progress`."""

    pair = Pair()
    engine = parked(engines, pair.workflow(), capacity=1)
    run = await engine.ops.submit("pair", "a title")
    await engine.start()
    await wait_for(pair.started)

    entry = await engine.ops.append_log(run.id, "look at this")

    assert entry.node == "top"
    assert entry.author is LogAuthor.user
    assert entry.task_id is None, "an operator note is about the run (03 §LogEntry)"
    assert [row.text for row in await log_of(store, run.id)] == ["look at this"]
    pair.go.set()


async def test_append_log_files_it_under_user_when_nothing_is_live(
    engines, store: Store, wait_until
) -> None:
    """The port of v0's `test_run_log_no_task_node_is_user`."""

    engine = parked(engines, trivial(), capacity=1)
    await engine.start()
    run = await engine.ops.submit("trivial", "a title")
    await wait_until(lambda: _run_is(store, run.id, RunStatus.completed))

    entry = await engine.ops.append_log(run.id, "afterwards")

    assert entry.node == USER_NODE


async def test_append_log_announces_a_preview_and_not_the_text(
    engines, store: Store
) -> None:
    """18 §Rules: an event never carries the full log text."""

    engine = parked(engines, trivial())
    run = await engine.ops.submit("trivial", "a title")

    entry = await engine.ops.append_log(run.id, "x" * 500)

    (event,) = await named(store, run.id, EventName.log_appended)
    assert event.data == {
        "log_id": entry.id,
        "author": "user",
        "node": USER_NODE,
        "preview": "x" * 200,
    }


async def test_append_log_refuses_an_empty_entry(engines, store: Store) -> None:
    """v0 rejected empty and whitespace-only text; so does this."""

    engine = parked(engines, trivial())
    run = await engine.ops.submit("trivial", "a title")

    for bad in ("", "   ", "\n"):
        with pytest.raises(Conflict):
            await engine.ops.append_log(run.id, bad)

    assert await log_of(store, run.id) == []


async def test_append_log_of_an_unknown_run_is_not_found(engines) -> None:
    engine = parked(engines, trivial())

    with pytest.raises(NotFound):
        await engine.ops.append_log("01JNOPE", "hello")


# --------------------------------------------------------------------------
# Small readers
# --------------------------------------------------------------------------


async def _order(store: Store) -> list[str]:
    async with store.reader() as reader:
        return [row.id for row in await reader.runs.list()]


async def _task_at(store: Store, run_id: str, node: str) -> TaskRow:
    rows = [task for task in await tasks_of(store, run_id) if task.node == node]
    assert rows, f"no task at {node!r}"
    return rows[-1]


async def _has_node(store: Store, run_id: str, node: str) -> bool:
    return any(task.node == node for task in await tasks_of(store, run_id))


async def _run_is(store: Store, run_id: str, status: RunStatus) -> bool:
    return (await run_of(store, run_id)).status is status

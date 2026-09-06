"""The attempt lifecycle and the success path (T024, 04 §Running an attempt).

What is asserted here is the join between the three rules and the store:
a body returns, and the run's rows say the right thing afterwards. The
routing table itself is ``tests/engine/test_routing.py``'s — this file
never re-tests which transitions a value produces, only that the ones it
produced were written, with the payload, the branch, the priority and the
lineage the documents fix.

The two assertions that are not about rows are the important ones:

- ``current_task()`` works inside a body and raises after it. Every
  user-land helper — ``human_input``, an agent façade, a plugin action —
  finds its attempt that way, and one that leaked past the attempt would
  write into a task that had finished.
- the live context is unregistered in the ``finally`` **even when the
  body raises**. The registry is how the API reaches a running attempt
  (05, 08); an entry that outlived its attempt would answer for a task
  nothing is running.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from athanore.engine.context import current_task, maybe_current_task
from athanore.events.names import EventName
from athanore.store.rows import RunStatus, TaskStatus
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------


def linear() -> Workflow:
    """start → middle → end, each carrying its value forward."""

    wf = Workflow("linear")

    @wf.node(start=True)
    async def start(middle):
        return {"from": "start"}

    @wf.node()
    async def middle(end, *, deliverable):
        return {"seen": deliverable}

    @wf.node()
    async def end(*, deliverable):
        return {"finished": deliverable}

    return wf


def branching(route: Callable[[Any, Any], Any]) -> Workflow:
    """A start node with two successors, so routing has to be explicit.

    ``route`` is what the body does with the two refs it is given, which
    is the only thing that differs between the cases below.
    """

    wf = Workflow("branching")

    @wf.node(start=True)
    async def choose(left, right):
        return route(left, right)

    @wf.node()
    async def left(*, deliverable): ...

    @wf.node()
    async def right(*, deliverable): ...

    return wf


# --------------------------------------------------------------------------
# The success path
# --------------------------------------------------------------------------


async def test_a_plain_return_takes_the_single_edge_and_carries_the_payload(
    harness,
) -> None:
    harness.register(linear())
    run_id = await harness.submit("linear")

    claimed = await harness.attempt()

    start = await harness.task(claimed.task.id)
    assert start.status is TaskStatus.done
    assert start.result == {"from": "start"}
    assert start.terminal is False
    (middle,) = await harness.at(run_id, "middle")
    assert middle.status is TaskStatus.ready
    assert middle.payload == {"from": "start"}
    assert middle.attempt == 1
    assert middle.lineage == {"from": start.id, "reason": "transition"}
    assert middle.branch == []


async def test_a_bare_ref_transitions_without_a_payload(harness) -> None:
    harness.register(branching(lambda left, right: right))
    run_id = await harness.submit("branching")

    await harness.attempt()

    assert await harness.at(run_id, "left") == []
    (right,) = await harness.at(run_id, "right")
    assert right.payload is None
    assert right.status is TaskStatus.ready


async def test_a_called_ref_transitions_with_its_payload(harness) -> None:
    harness.register(branching(lambda left, right: left({"deliverable": "a"})))
    run_id = await harness.submit("branching")

    await harness.attempt()

    (left,) = await harness.at(run_id, "left")
    assert left.payload == {"deliverable": "a"}


async def test_a_list_of_two_refs_enqueues_both(harness) -> None:
    harness.register(branching(lambda left, right: [left("a"), right("b")]))
    run_id = await harness.submit("branching")

    claimed = await harness.attempt()

    (left,) = await harness.at(run_id, "left")
    (right,) = await harness.at(run_id, "right")
    assert (left.payload, right.payload) == ("a", "b")
    # A fan-out, so each child carries the frame naming its branch.
    assert [frame.model_dump() for frame in left.branch] == [
        {"fanout": claimed.task.id, "index": 0, "count": 2, "key": "a"}
    ]
    assert [frame.model_dump() for frame in right.branch] == [
        {"fanout": claimed.task.id, "index": 1, "count": 2, "key": "b"}
    ]


async def test_the_payload_slot_is_bound_even_when_the_payload_is_none(
    harness,
) -> None:
    seen: list[tuple[bool, object]] = []
    wf = Workflow("nullable")

    @wf.node(start=True)
    async def only(*, deliverable):
        seen.append((True, deliverable))
        return []

    harness.register(wf)
    await harness.submit("nullable", payload=None)

    await harness.attempt()

    assert seen == [(True, None)]


async def test_a_payload_a_node_cannot_take_is_dropped_but_recorded(harness) -> None:
    """04 §Routing edge cases: the timeline still shows what was passed."""

    wf = Workflow("slotless")

    @wf.node(start=True)
    async def only():
        return []

    harness.register(wf)
    run_id = await harness.submit("slotless", payload={"ignored": True})

    claimed = await harness.attempt()

    assert (await harness.task(claimed.task.id)).payload == {"ignored": True}
    assert (await harness.run(run_id)).status is RunStatus.completed


async def test_a_terminal_return_completes_the_run_and_stores_the_output(
    harness,
) -> None:
    harness.register(linear())
    run_id = await harness.submit("linear")

    await harness.drain()

    run = await harness.run(run_id)
    assert run.status is RunStatus.completed
    assert run.output == {"finished": {"seen": {"from": "start"}}}
    assert run.finished is not None
    (end,) = await harness.at(run_id, "end")
    assert end.terminal is True
    assert end.result == run.output


async def test_a_run_completes_only_when_its_last_branch_lands(harness) -> None:
    """A terminal branch with a sibling still pending ends itself, not the run."""

    harness.register(branching(lambda left, right: [left("a"), right("b")]))
    run_id = await harness.submit("branching")

    await harness.attempt()  # the fan-out
    await harness.attempt()  # one branch, terminal

    assert (await harness.run(run_id)).status is RunStatus.running

    await harness.drain()

    run = await harness.run(run_id)
    assert run.status is RunStatus.completed
    # Two branches terminated independently: the output is the list, in
    # branch order (04 §Routing edge cases, D58).
    assert run.output == [None, None]


async def test_an_explicit_node_priority_beats_the_generation_key(harness) -> None:
    wf = Workflow("priorities")

    @wf.node(start=True)
    async def open_(urgent, ordinary):
        return [urgent(1), ordinary(2)]

    @wf.node(priority=0)
    async def urgent(*, deliverable): ...

    @wf.node()
    async def ordinary(*, deliverable): ...

    harness.register(wf)
    run_id = await harness.submit("priorities")

    await harness.attempt()

    (urgent_task,) = await harness.at(run_id, "urgent")
    (ordinary_task,) = await harness.at(run_id, "ordinary")
    assert (urgent_task.priority, urgent_task.explicit) == (0, True)
    assert (ordinary_task.priority, ordinary_task.explicit) == (-1, False)


# --------------------------------------------------------------------------
# The context
# --------------------------------------------------------------------------


async def test_current_task_is_bound_inside_the_body_and_gone_after(harness) -> None:
    inside: list[tuple[str, int, str, int]] = []
    wf = Workflow("bound")

    @wf.node(start=True)
    async def only():
        ctx = current_task()
        inside.append((ctx.run_id, ctx.task_id, ctx.node, ctx.attempt))
        assert ctx.services is not None
        assert ctx.api_base == "http://127.0.0.1:4002"
        return []

    harness.register(wf)
    run_id = await harness.submit("bound")

    claimed = await harness.attempt()

    assert inside == [(run_id, claimed.task.id, "only", 1)]
    assert maybe_current_task() is None
    with pytest.raises(RuntimeError, match="no task context"):
        current_task()


async def test_the_context_carries_the_claimed_token_and_is_live_while_it_runs(
    harness,
) -> None:
    live: list[bool] = []
    tokens: list[str] = []
    wf = Workflow("registered")

    @wf.node(start=True)
    async def only():
        ctx = current_task()
        tokens.append(ctx.token)
        live.append(harness.engine.live.context_for(ctx.task_id) is ctx)
        return []

    harness.register(wf)
    await harness.submit("registered")

    claimed = await harness.attempt()

    assert tokens == [claimed.token]
    assert live == [True]
    assert len(harness.engine.live) == 0


async def test_the_context_is_unregistered_and_the_slot_returned_when_a_body_raises(
    harness,
) -> None:
    wf = Workflow("raising")

    @wf.node(start=True)
    async def only():
        raise RuntimeError("boom")

    harness.register(wf)
    await harness.submit("raising")

    claimed = await harness.attempt()

    assert len(harness.engine.live) == 0
    assert harness.engine.live.context_for(claimed.task.id) is None
    assert harness.pool.leased == 0
    assert harness.engine.notifications == 1


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


async def test_the_attempt_announces_itself_and_its_run(harness) -> None:
    harness.register(linear())
    run_id = await harness.submit("linear")

    claimed = await harness.attempt()

    names = await harness.event_names(run_id)
    assert names[0] == EventName.task_started
    assert EventName.run_started in names
    (started,) = await harness.events_named(run_id, EventName.run_started)
    assert started.data == {"task_id": claimed.task.id, "node": "start"}
    assert started.task_id is None

    (enqueued,) = await harness.events_named(run_id, EventName.task_enqueued)
    (middle,) = await harness.at(run_id, "middle")
    assert enqueued.task_id == middle.id
    assert enqueued.data == {
        "node": "middle",
        "attempt": 1,
        "reason": "transition",
        "from_task": claimed.task.id,
        "payload_present": True,
        "branch": [],
    }

    (done,) = await harness.events_named(run_id, EventName.task_done)
    assert done.data == {
        "node": "start",
        "attempt": 1,
        "transitions": ["middle"],
        "terminal": False,
    }


async def test_run_started_is_emitted_once_however_many_tasks_are_claimed(
    harness,
) -> None:
    harness.register(branching(lambda left, right: [left("a"), right("b")]))
    run_id = await harness.submit("branching")

    await harness.drain()

    assert len(await harness.events_named(run_id, EventName.run_started)) == 1


async def test_run_completed_carries_the_output_and_its_terminal_tasks(
    harness,
) -> None:
    harness.register(linear())
    run_id = await harness.submit("linear")

    await harness.drain()

    (end,) = await harness.at(run_id, "end")
    (completed,) = await harness.events_named(run_id, EventName.run_completed)
    assert completed.data == {
        "node": "end",
        "task_id": end.id,
        "output": {"finished": {"seen": {"from": "start"}}},
        "terminal_tasks": [end.id],
    }

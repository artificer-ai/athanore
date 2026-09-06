"""Fan-in: branch frames, arrivals, and the join that fires once (T024b).

04 §Fan-in adds one mechanism to the three rules — the branch stack. A
fan-out pushes a frame onto every child; a transition into a ``join=True``
node pops it, records an arrival against it, and enqueues the join only
when every branch of that frame has arrived. The tests here are about
that mechanism, in the two shapes that can break it:

- **order.** The join's payload is the branches in *fan-out* order, never
  arrival order, because a run whose output depended on which branch
  finished first would not be reproducible (D58).
- **nesting.** A branch that fans out again pushes a second frame, so the
  inner join must come back to the outer branch's level rather than to
  the top — which is what makes joins compose at all.
"""

from __future__ import annotations

import pytest

from athanore.events.names import EventName
from athanore.graph import GraphError
from athanore.store.rows import RunStatus, TaskStatus
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------


def fanned(width: int = 3) -> Workflow:
    """One fan-out of ``width`` branches, closed by a join."""

    wf = Workflow("fanned")

    @wf.node(start=True)
    async def product(build):
        return [build(f"d{index}") for index in range(width)]

    @wf.node()
    async def build(release, *, deliverable):
        return release({"built": deliverable})

    @wf.node(join=True)
    async def release(*, results):
        return {"released": [result["value"]["built"] for result in results]}

    return wf


def nested() -> Workflow:
    """A fan-out inside a fan-out, each closed by its own join."""

    wf = Workflow("nested")

    @wf.node(start=True)
    async def outer(middle):
        return [middle(index) for index in range(2)]

    @wf.node()
    async def middle(leaf, *, deliverable):
        return [leaf({"outer": deliverable, "inner": j}) for j in range(2)]

    @wf.node()
    async def leaf(inner_join, *, deliverable):
        return inner_join(deliverable)

    @wf.node(join=True)
    async def inner_join(outer_join, *, results):
        return outer_join([result["value"] for result in results])

    @wf.node(join=True)
    async def outer_join(*, results):
        return {"branches": [result["value"] for result in results]}

    return wf


# --------------------------------------------------------------------------
# Arrival and dispatch
# --------------------------------------------------------------------------


async def test_three_branches_reach_the_join_in_index_order(harness) -> None:
    harness.register(fanned())
    run_id = await harness.submit("fanned")

    await harness.drain()

    (join_task,) = await harness.at(run_id, "release")
    builds = await harness.at(run_id, "build")
    assert join_task.payload == [
        {
            "index": index,
            "key": f"d{index}",
            "value": {"built": f"d{index}"},
            "from_task": builds[index].id,
        }
        for index in range(3)
    ]
    assert join_task.branch == []
    assert join_task.attempt == 1
    assert (await harness.run(run_id)).status is RunStatus.completed
    assert (await harness.run(run_id)).output == {"released": ["d0", "d1", "d2"]}


async def test_the_join_task_is_enqueued_once_with_the_arriving_tasks(
    harness,
) -> None:
    harness.register(fanned())
    run_id = await harness.submit("fanned")

    await harness.drain()

    fanout = (await harness.at(run_id, "product"))[0]
    builds = await harness.at(run_id, "build")
    (join_task,) = await harness.at(run_id, "release")
    assert join_task.lineage == {
        "from": fanout.id,
        "reason": "join",
        "arrivals": [build.id for build in builds],
    }
    enqueued = [
        event
        for event in await harness.events_named(run_id, EventName.task_enqueued)
        if event.data["reason"] == "join"
    ]
    assert len(enqueued) == 1
    assert enqueued[0].task_id == join_task.id
    assert enqueued[0].data["from_task"] == fanout.id
    assert enqueued[0].data["arrivals"] == [build.id for build in builds]
    assert enqueued[0].data["payload_present"] is True
    assert enqueued[0].data["branch"] == []


async def test_every_branch_announces_its_arrival(harness) -> None:
    harness.register(fanned())
    run_id = await harness.submit("fanned")

    await harness.drain()

    fanout = (await harness.at(run_id, "product"))[0]
    arrived = await harness.events_named(run_id, EventName.join_arrived)
    assert len(arrived) == 3
    assert {event.data["index"] for event in arrived} == {0, 1, 2}
    assert [event.data["arrived"] for event in arrived] == [1, 2, 3]
    for event in arrived:
        assert event.data["join"] == "release"
        assert event.data["fanout_task"] == fanout.id
        assert event.data["count"] == 3
        assert event.data["late"] is False


async def test_the_arrivals_are_stored_with_their_branch_keys(harness) -> None:
    harness.register(fanned())
    run_id = await harness.submit("fanned")

    await harness.drain()

    fanout = (await harness.at(run_id, "product"))[0]
    arrivals = await harness.arrivals(run_id, "release", fanout.id)
    assert [(row.index, row.key, row.late) for row in arrivals] == [
        (0, "d0", False),
        (1, "d1", False),
        (2, "d2", False),
    ]


async def test_a_fan_out_of_one_fires_the_join_on_the_first_arrival(harness) -> None:
    """04 §Fan-in: a stage that usually splits still works on one branch."""

    harness.register(fanned(width=1))
    run_id = await harness.submit("fanned")

    await harness.drain()

    (build,) = await harness.at(run_id, "build")
    assert [frame.count for frame in build.branch] == [1]
    (join_task,) = await harness.at(run_id, "release")
    assert join_task.payload == [
        {
            "index": 0,
            "key": "d0",
            "value": {"built": "d0"},
            "from_task": build.id,
        }
    ]
    assert (await harness.run(run_id)).output == {"released": ["d0"]}


async def test_a_nested_fan_out_joins_back_to_its_own_level(harness) -> None:
    harness.register(nested())
    run_id = await harness.submit("nested")

    await harness.drain()

    outer = (await harness.at(run_id, "outer"))[0]
    middles = await harness.at(run_id, "middle")
    leaves = await harness.at(run_id, "leaf")
    inner_joins = await harness.at(run_id, "inner_join")
    (outer_join,) = await harness.at(run_id, "outer_join")

    # The two middles are the outer fan-out's branches, in index order.
    assert [(task.branch[0].fanout, task.branch[0].index) for task in middles] == [
        (outer.id, 0),
        (outer.id, 1),
    ]
    # Each leaf carries both frames, outermost first. Compared as a set:
    # the branches run concurrently, so the order of the *rows* is the
    # order they were enqueued in, which is a race and not a contract.
    assert {
        tuple((frame.fanout, frame.index, frame.count) for frame in leaf.branch)
        for leaf in leaves
    } == {
        ((outer.id, 0, 2), (middles[0].id, 0, 2)),
        ((outer.id, 0, 2), (middles[0].id, 1, 2)),
        ((outer.id, 1, 2), (middles[1].id, 0, 2)),
        ((outer.id, 1, 2), (middles[1].id, 1, 2)),
    }
    # An inner join comes back to its outer branch, not to the top.
    assert {
        tuple((frame.fanout, frame.index) for frame in task.branch)
        for task in inner_joins
    } == {((outer.id, 0),), ((outer.id, 1),)}
    assert outer_join.branch == []

    run = await harness.run(run_id)
    assert run.status is RunStatus.completed
    assert run.output == {
        "branches": [
            [{"outer": 0, "inner": 0}, {"outer": 0, "inner": 1}],
            [{"outer": 1, "inner": 0}, {"outer": 1, "inner": 1}],
        ]
    }


# --------------------------------------------------------------------------
# Graphs a join cannot be built from
# --------------------------------------------------------------------------


async def test_routing_into_a_join_with_no_frame_is_a_graph_error(harness) -> None:
    wf = Workflow("unframed")

    @wf.node(start=True)
    async def start(gather):
        return gather("x")

    @wf.node(join=True)
    async def gather(*, results): ...

    harness.register(wf)
    run_id = await harness.submit("unframed")

    await harness.attempt()

    (start_task,) = await harness.at(run_id, "start")
    assert start_task.status is TaskStatus.dead_letter
    assert "no fan-out frame" in (start_task.error or "")
    assert await harness.at(run_id, "gather") == []
    assert (await harness.run(run_id)).status is RunStatus.failed


def test_a_join_without_a_payload_slot_fails_finalize() -> None:
    """The general case is ``tests/graph/test_builder.py``'s; a join that
    cannot receive its branches is a typo, and it is caught at
    registration rather than on the first arrival."""

    wf = Workflow("slotless_join")

    @wf.node(start=True)
    async def start(gather):
        return [gather("x")]

    @wf.node(join=True)
    async def gather(): ...

    with pytest.raises(GraphError, match="payload"):
        wf.finalize()

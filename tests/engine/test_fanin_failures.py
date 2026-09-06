"""Fan-in when a branch does not arrive, and the output shape (T024c).

A join waits for every branch, so the interesting cases are the ones
where a branch does not come:

- it **dead-letters** — the run fails as usual, and retrying the branch
  later makes it arrive, fires the join and finishes the run. Fan-in
  composes with the existing re-open semantics; there is no new state.
- it **terminates instead of joining** — nothing is pending and the join
  is short, which 03 invariant 4 calls a deadlock rather than a
  completion: ``failed`` with ``join_incomplete``.
- it **arrives twice** — the second one is history (``late``) and does
  not fire a second join.
- it **was interrupted** — the arrivals are rows, so a restart loses
  nothing and the branch arrives after it.

The last two tests are about ``run.output``, and they are the reason the
whole mechanism is built the way it is: the output of a fan-out must
come out of its *shape*, never out of which branch happened to finish
first. The delays are shuffled to prove it.
"""

from __future__ import annotations

import asyncio

import pytest

from athanore.engine.errors import NonRetryable
from athanore.events.names import EventName
from athanore.store.rows import RunStatus, TaskStatus
from athanore.workflow import Workflow

# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------


def flaky(fail_once: set[str]) -> Workflow:
    """Three branches into a join; the named ones fail their first attempt."""

    wf = Workflow("flaky")

    @wf.node(start=True)
    async def product(build):
        return [build(f"d{index}") for index in range(3)]

    @wf.node()
    async def build(release, *, deliverable):
        if deliverable in fail_once:
            fail_once.discard(deliverable)
            raise NonRetryable(f"{deliverable} refused")
        return release({"built": deliverable})

    @wf.node(join=True)
    async def release(*, results):
        return {"released": [result["value"]["built"] for result in results]}

    return wf


def leaky() -> Workflow:
    """Three branches, one of which terminates instead of joining."""

    wf = Workflow("leaky")

    @wf.node(start=True)
    async def product(build):
        return [build(f"d{index}") for index in range(3)]

    @wf.node()
    async def build(release, *, deliverable):
        if deliverable == "d2":
            return []
        return release({"built": deliverable})

    @wf.node(join=True)
    async def release(*, results):
        return {"released": [result["value"]["built"] for result in results]}

    return wf


def timed_join(delays: tuple[float, ...]) -> Workflow:
    """A fan-out closed by a join, whose branches finish in ``delays`` order.

    The run's output is the join's one value, and it must not depend on
    which branch finished first (D58).
    """

    wf = Workflow("timed")

    @wf.node(start=True)
    async def product(build):
        return [build(f"d{index}") for index in range(len(delays))]

    @wf.node()
    async def build(release, *, deliverable):
        await asyncio.sleep(delays[int(deliverable[1:])])
        return release(deliverable)

    @wf.node(join=True)
    async def release(*, results):
        return [result["value"] for result in results]

    return wf


def timed_open(delays: tuple[float, ...]) -> Workflow:
    """The same fan-out with no join: every branch terminates on its own.

    The run's output is the list of their values, in branch order.
    """

    wf = Workflow("timed")

    @wf.node(start=True)
    async def product(build):
        return [build(f"d{index}") for index in range(len(delays))]

    @wf.node()
    async def build(*, deliverable):
        await asyncio.sleep(delays[int(deliverable[1:])])
        return deliverable

    return wf


# --------------------------------------------------------------------------
# A branch that dead-letters
# --------------------------------------------------------------------------


async def test_a_dead_lettered_branch_fails_the_run_and_a_retry_fires_the_join(
    harness,
) -> None:
    harness.register(flaky({"d1"}))
    run_id = await harness.submit("flaky")

    await harness.drain()

    run = await harness.run(run_id)
    assert run.status is RunStatus.failed
    assert await harness.at(run_id, "release") == []
    (refused,) = [
        task
        for task in await harness.at(run_id, "build")
        if task.status is TaskStatus.dead_letter
    ]
    fanout = (await harness.at(run_id, "product"))[0]
    assert len(await harness.arrivals(run_id, "release", fanout.id)) == 2

    # `ops.retry` is T027b's; this is what it does — same node, payload,
    # priority and branch, `attempt + 1`, and the run re-opened.
    async with harness.store.uow() as uow:
        await uow.tasks.enqueue(
            run_id,
            refused.node,
            refused.payload,
            refused.priority,
            refused.explicit,
            attempt=refused.attempt + 1,
            created=refused.created,
            lineage={"from": refused.id, "reason": "manual_retry"},
            branch=refused.branch,
        )
        await uow.runs.update(run_id, status=RunStatus.running.value, finished=None)

    await harness.drain()

    run = await harness.run(run_id)
    assert run.status is RunStatus.completed
    assert run.output == {"released": ["d0", "d1", "d2"]}
    assert len(await harness.at(run_id, "release")) == 1


# --------------------------------------------------------------------------
# A branch that never joins
# --------------------------------------------------------------------------


async def test_a_branch_that_terminates_instead_of_joining_fails_the_run(
    harness,
) -> None:
    harness.register(leaky())
    run_id = await harness.submit("leaky")

    await harness.drain()

    run = await harness.run(run_id)
    assert run.status is RunStatus.failed
    assert await harness.at(run_id, "release") == []
    (failed,) = await harness.events_named(run_id, EventName.run_failed)
    assert failed.data["code"] == "join_incomplete"
    assert failed.data["error"] == "join_incomplete: release has 2 of 3 arrivals"


# --------------------------------------------------------------------------
# A branch that arrives twice
# --------------------------------------------------------------------------


async def test_an_arrival_after_the_join_fired_is_late_and_fires_nothing(
    harness,
) -> None:
    harness.register(flaky(set()))
    run_id = await harness.submit("flaky")
    await harness.drain()
    assert (await harness.run(run_id)).status is RunStatus.completed

    first = (await harness.at(run_id, "build"))[0]
    async with harness.store.uow() as uow:
        await uow.tasks.enqueue(
            run_id,
            first.node,
            first.payload,
            first.priority,
            first.explicit,
            attempt=first.attempt + 1,
            created=first.created,
            lineage={"from": first.id, "reason": "manual_retry"},
            branch=first.branch,
        )
        await uow.runs.update(run_id, status=RunStatus.running.value, finished=None)

    await harness.drain()

    fanout = (await harness.at(run_id, "product"))[0]
    arrivals = await harness.arrivals(run_id, "release", fanout.id)
    assert [row.late for row in arrivals] == [True, False, False]
    assert len(await harness.at(run_id, "release")) == 1
    late = [
        event
        for event in await harness.events_named(run_id, EventName.join_arrived)
        if event.data["late"]
    ]
    assert len(late) == 1
    assert late[0].data["index"] == 0


# --------------------------------------------------------------------------
# A branch interrupted by a restart
# --------------------------------------------------------------------------


async def test_a_branch_interrupted_by_a_restart_arrives_after_recovery(
    harness,
) -> None:
    running = asyncio.Event()
    release_it = asyncio.Event()
    wf = Workflow("interrupted")

    @wf.node(start=True)
    async def product(build):
        return [build(f"d{index}") for index in range(3)]

    @wf.node()
    async def build(release, *, deliverable):
        if deliverable == "d2" and not release_it.is_set():
            running.set()
            await asyncio.sleep(30)
        return release({"built": deliverable})

    @wf.node(join=True)
    async def release(*, results):
        return {"released": [result["value"]["built"] for result in results]}

    harness.register(wf)
    run_id = await harness.submit("interrupted")

    await harness.attempt()  # the fan-out
    claimed = await harness.claim(3)
    attempts = [harness.spawn(one) for one in claimed]
    await asyncio.wait_for(running.wait(), timeout=2)
    stuck = [
        attempt
        for attempt, one in zip(attempts, claimed, strict=True)
        if one.task.payload == "d2"
    ]
    for attempt in stuck:
        attempt.cancel()
    await asyncio.gather(*attempts, return_exceptions=True)

    fanout = (await harness.at(run_id, "product"))[0]
    assert len(await harness.arrivals(run_id, "release", fanout.id)) == 2
    assert await harness.at(run_id, "release") == []

    # The restart: `recover()` is T027's, and this is the row half of it.
    release_it.set()
    async with harness.store.uow() as uow:
        recovered = await uow.tasks.reset_for_recovery()
    assert len(recovered) == 1

    await harness.drain()

    run = await harness.run(run_id)
    assert run.status is RunStatus.completed
    assert run.output == {"released": ["d0", "d1", "d2"]}


# --------------------------------------------------------------------------
# Output shape, whatever the timings
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "delays",
    [(0.0, 0.0, 0.0), (0.03, 0.0, 0.015), (0.0, 0.03, 0.0), (0.015, 0.03, 0.0)],
)
async def test_a_joined_fan_out_has_one_output_whatever_the_timings(
    harness, delays: tuple[float, ...]
) -> None:
    harness.register(timed_join(delays))
    run_id = await harness.submit("timed")

    await harness.drain()

    run = await harness.run(run_id)
    assert run.status is RunStatus.completed
    assert run.output == ["d0", "d1", "d2"]
    (join_task,) = await harness.at(run_id, "release")
    assert join_task.terminal is True


@pytest.mark.parametrize(
    "delays",
    [(0.0, 0.0, 0.0), (0.03, 0.0, 0.015), (0.0, 0.03, 0.0), (0.015, 0.03, 0.0)],
)
async def test_an_open_fan_out_outputs_its_branches_in_branch_order(
    harness, delays: tuple[float, ...]
) -> None:
    harness.register(timed_open(delays))
    run_id = await harness.submit("timed")

    await harness.drain()

    run = await harness.run(run_id)
    assert run.status is RunStatus.completed
    assert run.output == ["d0", "d1", "d2"]
    (completed,) = await harness.events_named(run_id, EventName.run_completed)
    builds = await harness.at(run_id, "build")
    assert completed.data["terminal_tasks"] == [task.id for task in builds]

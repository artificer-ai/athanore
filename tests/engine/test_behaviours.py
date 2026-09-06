"""What the engine does, end to end, through a real ``Engine`` (T028).

This is the top of the engine layer of 13 §Pyramid: no stub, no claim by
hand, no attempt run by the test. A workflow is registered, a run is
submitted through ``engine.ops``, and the dispatch loop is left to do the
rest; what is asserted is what the store and the event stream say
afterwards. The suites below it pin the pieces — the claim's ordering is
``tests/store``, the attempt is ``tests/engine/test_runner.py``, the loop
is ``test_scheduler.py``, the branch stack is ``test_fanin.py`` — and
this file is the one that says they compose.

The five MVP files it carries (`docs/porting-ledger.md`):

- ``test_deterministic.py`` — a node routes on plain Python, with no
  agent anywhere;
- ``test_fanout.py`` — a fan-out completes when the last branch lands,
  branches carry their payloads, and a retry's work log reaches the next
  attempt;
- ``test_priority.py`` — the dispatch order of 04, observed where an
  operator sees it: the order ``task.started`` was emitted in;
- ``test_worker_pools.py`` — dedicated, shared and zero-capacity pools,
  and the registrations the engine refuses;
- ``test_qa_gate.py`` — a review stage that sends work back, and a gate
  that fails twice and ends the run.

Three v1 differences from the MVP are asserted rather than inherited. A
run is ``queued`` until one of its tasks is claimed — v0 flipped it to
``running`` at submission, so "waiting for a slot" was not a state an
operator could see (03 §Run) — and a pool of capacity zero therefore
parks a run in ``queued`` rather than in ``running``. The other two are
registrations v0 refused and v1 allows: a second ``Pool`` object
redeclaring a registered name binds to the pool that is there rather than
raising, and the default pool's name is not reserved. Both are pinned
below and recorded in D112, so the difference is visible rather than
discovered.

Nothing here sleeps waiting for something to happen. A test waits on the
bus (``run_to_completion``), on an event a body set, or on a poll of the
store, each under the conftest's ``DEADLINE``; where a test has to show
that something did *not* happen, a second run on a live pool is the
clock, because it cannot finish without ticks that gave every pool its
turn.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from athanore.engine import DEFAULT_POOL, Engine
from athanore.engine.context import current_task
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
# Reading the store back
# --------------------------------------------------------------------------


async def run_row(store: Store, run_id: str) -> RunRow:
    async with store.reader() as reader:
        row = await reader.runs.get(run_id)
    assert row is not None
    return row


async def tasks_of(store: Store, run_id: str) -> list[TaskRow]:
    async with store.reader() as reader:
        return await reader.tasks.list_for_run(run_id)


async def at(store: Store, run_id: str, node: str) -> list[TaskRow]:
    """Every attempt at ``node``, oldest first."""

    return [task for task in await tasks_of(store, run_id) if task.node == node]


async def events_of(store: Store, run_id: str, name: EventName) -> list[EventRow]:
    async with store.reader() as reader:
        rows = await reader.events.list_for_run(run_id)
    return [row for row in rows if row.name == name]


async def started_nodes(store: Store, run_id: str) -> list[str]:
    """The nodes of one run, in the order attempts announced themselves.

    ``task.started`` is what the SPA's timeline draws and what an
    operator reads as "what ran, when" (03 §Event vocabulary), so it is
    where the dispatch order is asserted rather than in the claim.
    """

    return [
        str(row.data["node"])
        for row in await events_of(store, run_id, EventName.task_started)
    ]


async def started_everywhere(store: Store) -> list[tuple[str, str]]:
    """``(run_id, node)`` for every attempt of every run, in start order."""

    async with store.reader() as reader:
        rows = await reader.events.list_after(0, 10_000)
    return [
        (str(row.run_id), str(row.data["node"]))
        for row in rows
        if row.name == EventName.task_started
    ]


async def log_of(store: Store, run_id: str) -> list[LogEntryRow]:
    async with store.reader() as reader:
        return await reader.log.list(run_id)


async def log_texts(store: Store, run_id: str) -> list[str]:
    return [entry.text for entry in await log_of(store, run_id)]


async def note(text: str, *, author: LogAuthor = LogAuthor.agent) -> None:
    """Write one work-log line from inside a node body.

    The MVP's bodies wrote theirs through a ``MockAgent``; agents are
    Phase 2 and the log is not, so these bodies use the service the agent
    façade will use underneath (03 §LogEntry).
    """

    await current_task().services.log.append(text, author=author)


class Parked:
    """A body that says when it started and then waits to be let go.

    The lever every capacity assertion in this file pulls: while a
    ``Parked`` body is inside, its attempt is holding exactly one slot of
    its pool, and the test decides when that stops being true.
    """

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.runs = 0

    async def body(self) -> str:
        self.runs += 1
        self.started.set()
        await self.release.wait()
        return "let go"

    def workflow(self, name: str) -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True)
        async def only() -> str:
            return await self.body()

        return wf


def instant(name: str) -> Workflow:
    """A one-node workflow that completes as soon as it is dispatched.

    Used as a clock: a run of it cannot complete without a full tick of
    the loop, so "this other run is still queued afterwards" is a
    decision the loop made rather than one it never got to.
    """

    wf = Workflow(name)

    @wf.node(start=True)
    async def only() -> str:
        return "done"

    return wf


# --------------------------------------------------------------------------
# Deterministic nodes: routing on plain Python (`test_deterministic.py`)
# --------------------------------------------------------------------------


def routed() -> Workflow:
    """A router that reads its run and picks a branch. No agent anywhere."""

    wf = Workflow("routed")

    @wf.node(start=True)
    async def start(route):
        return route

    @wf.node()
    async def route(alpha, beta):
        run = await current_task().services.run.get()
        return alpha if "alpha" in run.title else beta

    @wf.node()
    async def alpha() -> str:
        return "alpha ran"

    @wf.node()
    async def beta() -> str:
        return "beta ran"

    return wf


async def test_a_deterministic_node_routes_without_an_agent(
    start_engine, run_to_completion, store: Store
) -> None:
    """Two runs of one workflow take opposite branches, on the title alone."""

    engine: Engine = await start_engine(routed())
    first = await engine.ops.submit("routed", "alpha task")
    second = await engine.ops.submit("routed", "beta task")

    alpha_run = await run_to_completion(first.id)
    beta_run = await run_to_completion(second.id)

    assert alpha_run.status is RunStatus.completed
    assert beta_run.status is RunStatus.completed
    assert await started_nodes(store, first.id) == ["start", "route", "alpha"]
    assert await started_nodes(store, second.id) == ["start", "route", "beta"]
    # The branch not taken has no task at all: a route is a decision, not
    # a filter applied afterwards.
    assert await at(store, first.id, "beta") == []
    assert await at(store, second.id, "alpha") == []
    assert alpha_run.output == "alpha ran"
    assert beta_run.output == "beta ran"


# --------------------------------------------------------------------------
# Fan-out (`test_fanout.py`)
# --------------------------------------------------------------------------


def fan() -> Workflow:
    """One stage splits into two branches that never come back together."""

    wf = Workflow("fan")

    @wf.node(start=True)
    async def intake(split):
        await note("intake read the task and comments")
        return split

    @wf.node()
    async def split(build):
        return [build("deliverable #1"), build("deliverable #2")]

    @wf.node()
    async def build(done, *, item):
        await note(f"handoff notes for {item}")
        return done(item)

    @wf.node()
    async def done(*, item):
        await note(f"shipped {item}")
        return item

    return wf


async def test_a_fan_out_completes_when_the_last_branch_lands(
    start_engine, run_to_completion, store: Store
) -> None:
    """Both branches run, and exactly one of them ends the run."""

    engine: Engine = await start_engine((fan(), Pool("wide", 4)))
    submitted = await engine.ops.submit("fan", "do two things", "a and b")

    run = await run_to_completion(submitted.id)

    assert run.status is RunStatus.completed
    tasks = await tasks_of(store, submitted.id)
    assert [task.status for task in tasks] == [TaskStatus.done] * 6
    assert [task.node for task in tasks].count("build") == 2
    assert [task.node for task in tasks].count("done") == 2

    # One completion, not one per branch, and it names both terminal
    # tasks: the run ended once, when nothing was left pending.
    (completed,) = await events_of(store, submitted.id, EventName.run_completed)
    terminals = {task.id: task for task in tasks if task.terminal}
    assert len(terminals) == 2
    assert set(completed.data["terminal_tasks"]) == set(terminals)
    # Listed in branch order, not in the order the branches landed —
    # which is why they are not in task-id order here: the second branch
    # is dispatched first (04 §Dispatch order, newest first).
    assert [
        terminals[task_id].branch[-1].index
        for task_id in completed.data["terminal_tasks"]
    ] == [0, 1]
    assert run.finished is not None


async def test_each_branch_carries_its_own_payload(
    start_engine, run_to_completion, store: Store
) -> None:
    """The fan-out's payloads reach the bodies, the rows and the output."""

    engine: Engine = await start_engine((fan(), Pool("wide", 4)))
    submitted = await engine.ops.submit("fan", "do two things", "a and b")

    run = await run_to_completion(submitted.id)

    assert [task.payload for task in await at(store, submitted.id, "build")] == [
        "deliverable #1",
        "deliverable #2",
    ]
    # Branch order, never arrival order: the output of a fan-out is
    # reproducible (D58).
    assert run.output == ["deliverable #1", "deliverable #2"]
    texts = await log_texts(store, submitted.id)
    assert "intake read the task and comments" in texts
    assert any("#1" in text for text in texts)
    assert any("#2" in text for text in texts)


def flaky() -> Workflow:
    """A node that fails once and succeeds on the attempt after it."""

    wf = Workflow("flaky")
    attempts = {"work": 0}

    @wf.node(start=True)
    async def begin(work):
        return work

    @wf.node()
    async def work(finish):
        attempts["work"] += 1
        if attempts["work"] == 1:
            raise RuntimeError("first attempt explodes")
        await note("second attempt")
        return finish

    @wf.node()
    async def finish() -> str:
        return "shipped"

    return wf


async def test_a_retry_leaves_the_failure_in_the_log_for_the_next_attempt(
    start_engine, run_to_completion, store: Store
) -> None:
    """The run's log is the history of the node, not of one attempt."""

    engine: Engine = await start_engine(flaky())
    submitted = await engine.ops.submit("flaky", "try again")

    run = await run_to_completion(submitted.id)

    assert run.status is RunStatus.completed
    attempts = await at(store, submitted.id, "work")
    assert [task.attempt for task in attempts] == [1, 2]
    assert [task.status for task in attempts] == [TaskStatus.failed, TaskStatus.done]
    texts = await log_texts(store, submitted.id)
    assert "attempt 1 failed: first attempt explodes" in texts
    assert "second attempt" in texts
    # The engine wrote the first line and the body wrote the second.
    authors = {entry.text: entry.author for entry in await log_of(store, submitted.id)}
    assert authors["attempt 1 failed: first attempt explodes"] is LogAuthor.engine
    assert authors["second attempt"] is LogAuthor.agent


# --------------------------------------------------------------------------
# Dispatch order (`test_priority.py`)
# --------------------------------------------------------------------------


def ordered() -> Workflow:
    """A fan-out whose two branches are of different depths."""

    wf = Workflow("ordered")

    @wf.node(start=True)
    async def start(wide, deep_one):
        return [wide(), deep_one()]

    @wf.node()
    async def wide() -> str:
        return "shallow"

    @wf.node()
    async def deep_one(deep_two):
        return deep_two

    @wf.node()
    async def deep_two() -> str:
        return "deep"

    return wf


def urgent() -> Workflow:
    """One node, declared at the front of its run's queue."""

    wf = Workflow("urgent")

    @wf.node(start=True, priority=-100)
    async def rush() -> str:
        return "rushed"

    return wf


async def test_downstream_work_dispatches_before_newer_shallow_work(
    start_engine, run_to_completion, store: Store
) -> None:
    """Deeper first, and newest first among equals (04 §Dispatch order).

    ``wide`` and ``deep_one`` are enqueued by one transaction at the same
    generation, so the newer of the two goes first; ``deep_two`` is a
    generation deeper than ``wide`` and goes ahead of it even though
    ``wide`` has been ready the whole time.
    """

    engine: Engine = await start_engine(ordered())
    submitted = await engine.ops.submit("ordered", "one run")

    run = await run_to_completion(submitted.id)

    assert run.status is RunStatus.completed
    assert await started_nodes(store, submitted.id) == [
        "start",
        "deep_one",
        "deep_two",
        "wide",
    ]


async def test_an_explicit_priority_beats_the_generations(
    start_engine, run_to_completion, store: Store
) -> None:
    """A node with ``priority`` jumps every generation-based task."""

    wf = Workflow("hotfixed")

    @wf.node(start=True)
    async def start(hotfix, chore):
        return [hotfix(), chore()]

    @wf.node(priority=0)
    async def hotfix() -> str:
        return "patched"

    @wf.node()
    async def chore() -> str:
        return "swept"

    engine: Engine = await start_engine(wf)
    submitted = await engine.ops.submit("hotfixed", "one run")

    run = await run_to_completion(submitted.id)

    assert run.status is RunStatus.completed
    # `hotfix` was enqueued first, so without the explicit flag the
    # newest-first tiebreak would have put `chore` in front of it.
    assert await started_nodes(store, submitted.id) == ["start", "hotfix", "chore"]


async def test_an_in_flight_run_beats_a_newer_submission(
    start_engine, run_to_completion, store: Store
) -> None:
    """Run position dominates everything inside a run (04 §Dispatch order).

    The MVP's reported bug: a new run's start node preempting the pending
    deeper nodes of a run already under way. Here the second run's start
    node carries an *explicit* priority — the strongest key inside a run
    — and still waits for the first run to finish, because the list
    position is read first.
    """

    engine: Engine = await start_engine(ordered(), urgent())
    first = await engine.ops.submit("ordered", "already going")
    second = await engine.ops.submit("urgent", "just arrived")

    assert (await run_row(store, first.id)).position < (
        await run_row(store, second.id)
    ).position

    await run_to_completion(first.id)
    await run_to_completion(second.id)

    assert await started_everywhere(store) == [
        (first.id, "start"),
        (first.id, "deep_one"),
        (first.id, "deep_two"),
        (first.id, "wide"),
        (second.id, "rush"),
    ]


# --------------------------------------------------------------------------
# Pools (`test_worker_pools.py`)
# --------------------------------------------------------------------------


async def test_a_dedicated_pool_is_not_blocked_by_the_default_one(
    start_engine, run_to_completion, wait_for, wait_until, store: Store
) -> None:
    """Strict reservation: a slow workflow cannot delay one with its own pool."""

    slow = Parked()
    fast = Parked()
    fast.release.set()
    engine: Engine = await start_engine(
        slow.workflow("slow"), (fast.workflow("fast"), Pool("fastlane", 1))
    )

    stuck = await engine.ops.submit("slow", "holds the default pool")
    await wait_for(slow.started)
    quick = await engine.ops.submit("fast", "has its own lane")

    assert (await run_to_completion(quick.id)).status is RunStatus.completed
    # The slow run is still inside its body, holding the one default slot.
    assert (await run_row(store, stuck.id)).status is RunStatus.running
    assert (await tasks_of(store, stuck.id))[0].status is TaskStatus.in_progress
    assert engine.snapshot()["default"]["in_flight"] == 1
    await wait_until(lambda: _idle(engine, "fastlane"))

    slow.release.set()
    assert (await run_to_completion(stuck.id)).status is RunStatus.completed


async def _idle(engine: Engine, pool: str) -> bool:
    """Whether ``pool`` has every slot back.

    A poll rather than a read straight after the run ended: the runner
    commits the run's completion and releases its lease afterwards, so
    the slot comes back a moment after the event that says the run is
    over.
    """

    return engine.snapshot()[pool]["in_flight"] == 0


async def test_a_shared_pool_serializes_two_workflows(
    start_engine, run_to_completion, wait_for, wait_until, store: Store
) -> None:
    """One capacity-1 pool, two workflows: one runs, the other waits ready."""

    first = Parked()
    second = Parked()
    shared = Pool("shared", 1)
    engine: Engine = await start_engine(
        (first.workflow("first"), shared), (second.workflow("second"), shared)
    )

    one = await engine.ops.submit("first", "a")
    two = await engine.ops.submit("second", "b")

    await wait_until(lambda: _in_progress(store, [one.id, two.id], 1))
    # Whichever took the slot, the other is queued and untouched. Which
    # one it was is read from the rows rather than from the bodies: the
    # claim flips the row, and the attempt it spawned enters the body a
    # moment later.
    holder, waiter = (one, two) if await _claimed(store, one.id) else (two, one)
    held, parked = (first, second) if holder is one else (second, first)
    await wait_for(held.started)
    assert not parked.started.is_set()
    assert (await run_row(store, waiter.id)).status is RunStatus.queued
    assert (await tasks_of(store, waiter.id))[0].status is TaskStatus.ready

    held.release.set()
    assert (await run_to_completion(holder.id)).status is RunStatus.completed
    # The slot came back and the waiter took it.
    await wait_until(lambda: _in_progress(store, [waiter.id], 1))
    parked.release.set()
    assert (await run_to_completion(waiter.id)).status is RunStatus.completed


async def _in_progress(store: Store, run_ids: Sequence[str], count: int) -> bool:
    """Whether exactly ``count`` tasks across ``run_ids`` are in progress."""

    running = 0
    for run_id in run_ids:
        running += sum(
            task.status is TaskStatus.in_progress
            for task in await tasks_of(store, run_id)
        )
    return running == count


async def _claimed(store: Store, run_id: str) -> bool:
    """Whether ``run_id`` is the one whose task took the slot."""

    return await _in_progress(store, [run_id], 1)


async def test_unpooled_workflows_share_the_default_pool(
    start_engine, run_to_completion, wait_until, store: Store
) -> None:
    """Workflows registered without a pool share the default one.

    ``settings.workers`` is 1 here, which is what makes the *sharing*
    visible: two unpooled workflows get one cap between them, not one
    each.
    """

    first = Parked()
    second = Parked()
    engine: Engine = await start_engine(
        first.workflow("first"), second.workflow("second")
    )
    assert engine.snapshot()["default"]["capacity"] == engine.settings.workers == 1

    one = await engine.ops.submit("first", "a")
    two = await engine.ops.submit("second", "b")
    await wait_until(lambda: _in_progress(store, [one.id, two.id], 1))

    first.release.set()
    second.release.set()
    assert (await run_to_completion(one.id)).status is RunStatus.completed
    assert (await run_to_completion(two.id)).status is RunStatus.completed
    assert first.runs == second.runs == 1


async def test_a_pool_of_capacity_zero_queues_without_dispatching(
    start_engine, run_to_completion, store: Store
) -> None:
    """``capacity=0`` parks a workflow: ``queued``, and never claimed.

    The live run is the clock — it cannot complete without a tick that
    gave every pool its turn — so the parked task being untouched
    afterwards is a decision the loop made.
    """

    never = Parked()
    engine: Engine = await start_engine(
        (never.workflow("parked"), Pool("lot", 0)),
        (instant("live"), Pool("live_lane", 1)),
    )

    stuck = await engine.ops.submit("parked", "never runs")
    clock = await engine.ops.submit("live", "the clock")
    assert (await run_to_completion(clock.id)).status is RunStatus.completed

    assert not never.started.is_set()
    assert (await tasks_of(store, stuck.id))[0].status is TaskStatus.ready
    # `queued`, not `running`: v0 flipped a run at submission, v1 flips
    # it at the first claim, and this run has never had one (03 §Run).
    assert (await run_row(store, stuck.id)).status is RunStatus.queued
    assert engine.snapshot()["lot"] == {"capacity": 0, "in_flight": 0}


# --------------------------------------------------------------------------
# What `register` refuses (`test_worker_pools.py`)
# --------------------------------------------------------------------------


def one_node(name: str) -> Workflow:
    """The smallest registrable workflow, for the registration errors."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def only() -> None: ...

    return wf


async def test_two_workflows_may_share_one_pool(engines) -> None:
    """A shared pool is not a feature: it is a pool two workflows named."""

    engine: Engine = engines()
    shared = Pool("shared", 2)
    engine.register(one_node("a").finalize(), shared)
    engine.register(one_node("b").finalize(), shared)

    assert engine.pools.workflows_of("shared") == ("a", "b")
    assert engine.snapshot()["shared"] == {"capacity": 2, "in_flight": 0}


async def test_a_pool_named_after_a_workflow_is_refused(engines) -> None:
    engine: Engine = engines()
    engine.register(one_node("a").finalize())

    with pytest.raises(ValueError, match="already the name of a workflow"):
        engine.register(one_node("z").finalize(), Pool("a", 1))


async def test_a_workflow_named_after_a_pool_is_refused(engines) -> None:
    engine: Engine = engines()
    engine.register(one_node("a").finalize(), Pool("shared", 2))

    with pytest.raises(ValueError, match="already the name of a pool"):
        engine.register(one_node("shared").finalize())


async def test_a_workflow_and_its_pool_may_not_share_a_name(engines) -> None:
    engine: Engine = engines()

    with pytest.raises(ValueError, match="already the name of a pool"):
        engine.register(one_node("dup").finalize(), Pool("dup", 1))


async def test_a_workflow_cannot_be_moved_to_another_pool(engines) -> None:
    """A task's pool comes from its run's workflow and never changes."""

    engine: Engine = engines()
    graph = one_node("a").finalize()
    engine.register(graph, Pool("first", 1))
    engine.register(graph, Pool("first", 1))  # the same pool again: a no-op

    with pytest.raises(ValueError, match="cannot be moved"):
        engine.register(graph, Pool("second", 1))


async def test_a_second_graph_under_one_workflow_name_is_refused(engines) -> None:
    """Rebinding the name would leave running attempts on the old graph."""

    engine: Engine = engines()
    engine.register(one_node("a").finalize())

    with pytest.raises(ValueError, match="already registered"):
        engine.register(one_node("a").finalize())


async def test_the_default_pool_name_is_not_reserved(engines) -> None:
    """v0 refused ``Pool("default", …)``; v1 lets a host size it (D112).

    Declaring it is how a host gives the default pool a capacity other
    than ``settings.workers``, and a workflow registered without a pool
    joins it rather than getting a cap of its own.
    """

    engine: Engine = engines()
    engine.register(one_node("a").finalize(), Pool(DEFAULT_POOL, 3))
    engine.register(one_node("b").finalize())

    assert engine.pools.workflows_of(DEFAULT_POOL) == ("a", "b")
    assert engine.snapshot()[DEFAULT_POOL]["capacity"] == 3


async def test_a_redeclared_pool_keeps_the_capacity_it_was_registered_with(
    engines,
) -> None:
    """Pools are joined by name, and the first declaration wins (D112).

    The MVP refused this outright ("two different pools with the same
    name"). v1's ``register`` adds a pool only when its name is new, so a
    second ``Pool`` object of that name binds the workflow to the pool
    that is already there — which is what makes registering the same
    shared pool twice a no-op, and what makes a *mismatched* redeclaration
    silent. Pinned here so the difference is visible rather than
    discovered.
    """

    engine: Engine = engines()
    engine.register(one_node("a").finalize(), Pool("shared", 2))
    engine.register(one_node("b").finalize(), Pool("shared", 4))

    assert engine.snapshot()["shared"]["capacity"] == 2


# --------------------------------------------------------------------------
# Review and gate loop-backs (`test_qa_gate.py`)
# --------------------------------------------------------------------------


def pipeline(name: str, verdicts: Sequence[str], gates: Sequence[bool]) -> Workflow:
    """``brief → engineering → qa → gate → git``, with scripted decisions.

    ``verdicts`` is what ``qa`` decides on each visit and ``gates`` what
    ``gate`` finds on each of its own; a gate visited past the end of
    ``gates`` raises, which is how the failing scenario terminates rather
    than looping for ever. ``retries=0`` on the gate is the MVP's
    server-wide ``max_retries=0``, narrowed to the node that needs it (04
    §Node options): the exception dead-letters on the spot.
    """

    wf = Workflow(name)
    remaining_verdicts = list(verdicts)
    remaining_gates = list(gates)

    @wf.node(start=True)
    async def brief(engineering):
        await note("brief: started")
        return engineering

    @wf.node()
    async def engineering(qa):
        await note("engineering: implemented")
        return qa

    @wf.node()
    async def qa(engineering, gate):
        verdict = remaining_verdicts.pop(0)
        await note(f"qa: {verdict}")
        return gate if verdict == "approve" else engineering

    @wf.node(retries=0)
    async def gate(engineering, git):
        if not remaining_gates:
            raise RuntimeError("gate failed after loop-back — terminating")
        passed = remaining_gates.pop(0)
        verdict = "PASS" if passed else "FAIL"
        await note(f"test gate: {verdict}", author=LogAuthor.engine)
        return git if passed else engineering

    @wf.node()
    async def git() -> str:
        await note("git: shipped")
        return "shipped"

    return wf


async def test_an_approved_review_goes_on_to_the_gate(
    start_engine, run_to_completion, store: Store
) -> None:
    """The linear path: nothing loops, and the run completes."""

    engine: Engine = await start_engine(
        pipeline("approve", verdicts=["approve"], gates=[True])
    )
    submitted = await engine.ops.submit("approve", "qa gate test", "test run")

    run = await run_to_completion(submitted.id)

    assert run.status is RunStatus.completed
    assert await started_nodes(store, submitted.id) == [
        "brief",
        "engineering",
        "qa",
        "gate",
        "git",
    ]
    assert "test gate: PASS" in await log_texts(store, submitted.id)


async def test_a_review_that_asks_for_changes_sends_the_work_back(
    start_engine, run_to_completion, store: Store
) -> None:
    """A loop-back is an ordinary transition: the node runs again."""

    engine: Engine = await start_engine(
        pipeline("loop", verdicts=["changes_requested", "approve"], gates=[True])
    )
    submitted = await engine.ops.submit("loop", "qa gate test", "test run")

    run = await run_to_completion(submitted.id)

    assert run.status is RunStatus.completed
    assert await started_nodes(store, submitted.id) == [
        "brief",
        "engineering",
        "qa",
        "engineering",
        "qa",
        "gate",
        "git",
    ]
    texts = await log_texts(store, submitted.id)
    assert texts.count("engineering: implemented") == 2
    assert texts.count("qa: changes_requested") == 1
    assert texts.count("qa: approve") == 1
    # A loop-back is a second *task*, not a second attempt of the first:
    # attempt numbers belong to retries (03 §Task).
    assert [task.attempt for task in await at(store, submitted.id, "engineering")] == [
        1,
        1,
    ]


async def test_a_gate_that_fails_twice_ends_the_run(
    start_engine, run_to_completion, store: Store
) -> None:
    """The loop-back terminates, and the run's verdict is the gate's."""

    engine: Engine = await start_engine(
        pipeline("gatefail", verdicts=["approve", "approve"], gates=[False])
    )
    submitted = await engine.ops.submit("gatefail", "qa gate test", "test run")

    run = await run_to_completion(submitted.id)

    assert run.status is RunStatus.failed
    assert await started_nodes(store, submitted.id) == [
        "brief",
        "engineering",
        "qa",
        "gate",
        "engineering",
        "qa",
        "gate",
    ]
    assert "test gate: FAIL" in await log_texts(store, submitted.id)
    # No retry: `retries=0` dead-letters the second gate on its first
    # attempt, and the dead-letter is what failed the run.
    (dead,) = await events_of(store, submitted.id, EventName.task_dead_lettered)
    assert dead.data["node"] == "gate"
    (failed,) = await events_of(store, submitted.id, EventName.run_failed)
    assert failed.data["task_id"] == dead.task_id
    # 18's absent-not-null rule: this failure has no code, so the field
    # is not on the wire at all.
    assert "code" not in failed.data
    assert "git" not in await started_nodes(store, submitted.id)


# --------------------------------------------------------------------------
# A loop-back's payload, carried or dropped
# --------------------------------------------------------------------------


def looping(name: str, *, carry: bool) -> tuple[Workflow, list[Any]]:
    """``build → check → build`` once, with or without a payload.

    ``seen`` collects what each visit to ``build`` was handed, which is
    the whole difference between ``return build`` and
    ``return build(feedback)`` (04 §Routing interpretation).
    """

    seen: list[Any] = []
    wf = Workflow(name)

    @wf.node(start=True)
    async def start(build):
        return build

    @wf.node()
    async def build(check, *, feedback=None):
        seen.append(feedback)
        return check

    @wf.node()
    async def check(build, done):
        if len(seen) > 1:
            return done
        return build("fix the tests") if carry else build

    @wf.node()
    async def done() -> str:
        return "landed"

    return wf, seen


async def test_a_loop_back_carries_the_payload_it_was_given(
    start_engine, run_to_completion, store: Store
) -> None:
    """``return build(feedback)`` hands the next visit what it was given.

    The value reaches the body, the row and the ``task.enqueued`` event's
    ``payload_present``, which is the only place the wire says a payload
    exists at all (18 §Rules).
    """

    wf, seen = looping("carried", carry=True)
    engine: Engine = await start_engine(wf)
    submitted = await engine.ops.submit("carried", "carry it")

    assert (await run_to_completion(submitted.id)).status is RunStatus.completed

    assert seen == [None, "fix the tests"]
    assert [task.payload for task in await at(store, submitted.id, "build")] == [
        None,
        "fix the tests",
    ]
    enqueued = [
        row.data
        for row in await events_of(store, submitted.id, EventName.task_enqueued)
        if row.data["node"] == "build"
    ]
    assert [data["payload_present"] for data in enqueued] == [False, True]


async def test_a_bare_loop_back_drops_the_payload(
    start_engine, run_to_completion, store: Store
) -> None:
    """``return build`` is a transition with no payload, not a repeat of one.

    The second visit is handed ``None`` rather than what the first was
    given: nothing carries a payload forward on its own, which is what
    makes a body's payload the decision of the node that routed to it.
    """

    wf, seen = looping("dropped", carry=False)
    engine: Engine = await start_engine(wf)
    submitted = await engine.ops.submit("dropped", "drop it")

    assert (await run_to_completion(submitted.id)).status is RunStatus.completed

    assert seen == [None, None]
    assert [task.payload for task in await at(store, submitted.id, "build")] == [
        None,
        None,
    ]
    enqueued = [
        row.data
        for row in await events_of(store, submitted.id, EventName.task_enqueued)
        if row.data["node"] == "build"
    ]
    assert [data["payload_present"] for data in enqueued] == [False, False]


# --------------------------------------------------------------------------
# `queued` is a state an operator can see
# --------------------------------------------------------------------------


async def test_a_run_is_queued_until_one_of_its_tasks_is_claimed(
    start_engine, run_to_completion, wait_for, store: Store
) -> None:
    """Waiting for a slot is a state, and ``run.started`` says when it ended.

    v0 flipped a run to ``running`` when it was submitted, so a run
    waiting behind another was indistinguishable from a run being worked
    on. v1 flips it in the claim's transaction, and emits ``run.started``
    from the attempt that did it (03 §Run, 04 §Dispatch order).
    """

    holder = Parked()
    engine: Engine = await start_engine(holder.workflow("one_at_a_time"))

    first = await engine.ops.submit("one_at_a_time", "holds the slot")
    await wait_for(holder.started)
    second = await engine.ops.submit("one_at_a_time", "waits for it")

    assert (await run_row(store, second.id)).status is RunStatus.queued
    assert await events_of(store, second.id, EventName.run_started) == []
    # The run that *is* being worked on says so, and said so once.
    assert (await run_row(store, first.id)).status is RunStatus.running
    (started,) = await events_of(store, first.id, EventName.run_started)
    assert started.data["node"] == "only"
    assert started.data["task_id"] == (await tasks_of(store, first.id))[0].id

    holder.release.set()
    assert (await run_to_completion(second.id)).status is RunStatus.completed
    (started,) = await events_of(store, second.id, EventName.run_started)
    assert started.data["task_id"] == (await tasks_of(store, second.id))[0].id


# --------------------------------------------------------------------------
# The `feature_build` shape: fan out per deliverable, join at the end
# --------------------------------------------------------------------------


def feature_build() -> Workflow:
    """04 §Fan-in's example, with the agents taken out.

    One branch per deliverable, a review inside a branch that sends that
    branch back a stage, and a join that runs once with every branch's
    value. The mechanism is T024b's; what this shape adds is that a
    loop-back *inside* a branch does not disturb the branch stack, so the
    join still fires exactly once and in fan-out order.
    """

    wf = Workflow("feature_build")
    reviewed: set[str] = set()

    @wf.node(start=True)
    async def prompt(product):
        return product

    @wf.node()
    async def product(architecture):
        return [architecture(name) for name in ("api", "cli", "docs")]

    @wf.node()
    async def architecture(engineering, *, deliverable):
        return engineering(deliverable)

    @wf.node()
    async def engineering(qa, *, deliverable):
        await note(f"engineering: {deliverable}")
        return qa(deliverable)

    @wf.node()
    async def qa(engineering, gate, *, deliverable):
        if deliverable == "cli" and deliverable not in reviewed:
            reviewed.add(deliverable)
            return engineering(deliverable)
        return gate(deliverable)

    @wf.node()
    async def gate(release, engineering, *, deliverable):
        return release({"deliverable": deliverable, "ok": True})

    @wf.node(join=True)
    async def release(*, results):
        return {"released": [row["value"]["deliverable"] for row in results]}

    return wf


async def test_a_feature_build_shaped_fan_out_is_closed_by_its_join(
    start_engine, run_to_completion, store: Store
) -> None:
    """Three branches, one of them looping, and one join that fires once."""

    engine: Engine = await start_engine((feature_build(), Pool("local", 4)))
    submitted = await engine.ops.submit("feature_build", "ship the feature")

    run = await run_to_completion(submitted.id)

    assert run.status is RunStatus.completed
    # Fan-out order, not arrival order, and not the order the loop-back
    # made them finish in.
    assert run.output == {"released": ["api", "cli", "docs"]}

    joins = await at(store, submitted.id, "release")
    assert len(joins) == 1
    assert [row["key"] for row in joins[0].payload] == ["api", "cli", "docs"]
    assert [row["index"] for row in joins[0].payload] == [0, 1, 2]
    assert joins[0].branch == []

    arrivals = await events_of(store, submitted.id, EventName.join_arrived)
    assert [event.data["arrived"] for event in arrivals] == [1, 2, 3]
    assert {event.data["count"] for event in arrivals} == {3}
    assert not any(event.data["late"] for event in arrivals)

    # The one branch that was sent back is the only node that ran twice,
    # and the run's single terminal task is the join.
    texts = await log_texts(store, submitted.id)
    assert sorted(texts) == [
        "engineering: api",
        "engineering: cli",
        "engineering: cli",
        "engineering: docs",
    ]
    tasks = await tasks_of(store, submitted.id)
    assert [task.id for task in tasks if task.terminal] == [joins[0].id]

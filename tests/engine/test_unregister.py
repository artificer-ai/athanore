"""Dropping a workflow from a running engine (T083, 22 §Remove).

``unregister`` is a shutdown for one name. Everything it does to an
attempt in flight is what ``stop()`` does — asyncio cancel, the agent
subprocess terminated then killed, the transcript flushed, the façade's
cancellation stats entry — and, like a shutdown, it **writes no task
status** (D52, D221): the rows stay ``in_progress`` / ``waiting``, the
run stays ``running``, and the next ``add`` of the name, or the next
process, recovers them. What it adds is the registry half: the name is
unbound from its pool so no claim selects its tasks again, the graph is
dropped, and the pool — the host's capacity — stays.

The one assertion that is about timing rather than end state is the
raced claim: an attempt spawned by the tick that was claiming when
``unregister`` was called is cancelled with the rest, because the call
runs between ticks (``Scheduler.quiescent``) and reads what is in
flight only once the claim has spawned.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from structlog.testing import capture_logs

from athanore.agents.acp import ACPAgent
from athanore.engine import Engine
from athanore.engine.context import current_task
from athanore.engine.pools import Pool
from athanore.events.names import EventName
from athanore.requests.human import human_input
from athanore.store.rows import EventRow, RunStatus, TaskRow, TaskStatus
from athanore.store.uow import Store
from athanore.testing import scenario
from athanore.workflow import Workflow

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 10.0


# --------------------------------------------------------------------------
# Bodies
# --------------------------------------------------------------------------


class Parked:
    """A body that announces itself and then waits to be cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False
        self.starts = 0

    def workflow(self, name: str) -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True)
        async def only() -> str:
            self.starts += 1
            self.started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return "landed"  # pragma: no cover - the point is that it never does

        return wf


class Spy(ACPAgent):
    """A façade that keeps its child, so the test can see it is gone.

    ``tests/agents/test_acp_outcomes.py``'s model: the subprocess is
    private to one ``run()``, and looking over the façade's shoulder as
    it spawns is the only honest way to assert "no zombie".
    """

    system_prompt = "You are a test agent."
    permission_policy = "auto_allow"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.process: asyncio.subprocess.Process | None = None

    async def _spawn(self, session: Any, settings: Any, ctx: Any) -> None:
        await super()._spawn(session, settings, ctx)
        self.process = session.process


def agent_workflow(name: str, agent: Spy) -> Workflow:
    """A one-node workflow whose body hands the turn to ``agent``.

    The body writes one transcript chunk first, so "the transcript is
    flushed" is a row the test can read back rather than an absence.
    """

    wf = Workflow(name)

    @wf.node(start=True)
    async def only() -> str:
        ctx = current_task()
        await ctx.services.stream.append("notice", "handing off to the agent")
        result = await agent.run("do the work")
        return str(result.status)  # pragma: no cover - the agent never finishes

    return wf


def asking_workflow(name: str) -> Workflow:
    """A one-node workflow that parks on a human question."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def only() -> str:
        return str(await human_input("Ship it?", options=["yes", "no"]))

    return wf


# --------------------------------------------------------------------------
# Reading the store back
# --------------------------------------------------------------------------


async def task_of(store: Store, run_id: str) -> TaskRow:
    async with store.reader() as reader:
        (task,) = await reader.tasks.list_for_run(run_id)
    return task


async def run_status(store: Store, run_id: str) -> RunStatus:
    async with store.reader() as reader:
        row = await reader.runs.get(run_id)
    assert row is not None
    return row.status


async def stats_lines(store: Store, run_id: str) -> list[str]:
    async with store.reader() as reader:
        entries = await reader.log.list(run_id)
    return [entry.text for entry in entries if entry.text.startswith("[stats]")]


async def transcript(store: Store, task_id: int) -> list[tuple[str, str]]:
    async with store.reader() as reader:
        chunks = await reader.stream.list_after(task_id)
    return [(str(chunk.kind), chunk.text) for chunk in chunks]


async def engine_events(store: Store, name: EventName) -> list[EventRow]:
    async with store.reader() as reader:
        rows = await reader.events.list_after(0, 1000)
    return [row for row in rows if row.name == name]


async def spawned(agent: Spy) -> asyncio.subprocess.Process:
    """Wait until ``agent`` has a child, and hand it over."""

    async with asyncio.timeout(DEADLINE):
        while agent.process is None:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)
    return agent.process


# --------------------------------------------------------------------------
# An agent mid-turn
# --------------------------------------------------------------------------


async def test_unregister_cancels_the_agent_mid_turn_and_writes_no_status(
    start_engine, store: Store
) -> None:
    """22 §Remove steps 1–2 on the attempt that costs the most to interrupt.

    The child is gone, the transcript is in the store, the stats entry
    is the façade's ordinary cancellation entry, and the rows are exactly
    as shutdown would leave them.
    """

    agent = Spy(command=scenario(sleep_s=30, submit={"verdict": "never"}))
    engine: Engine = await start_engine(
        (agent_workflow("agentic", agent), Pool("test", 1))
    )
    run = await engine.ops.submit("agentic", "a run")
    process = await spawned(agent)
    task = await task_of(store, run.id)
    assert engine.attempts_of("agentic") == [task.id]

    async with asyncio.timeout(DEADLINE):
        assert await engine.unregister("agentic") == [task.id]

    # Step 1: the attempt is cancelled the way a shutdown cancels it.
    assert process.returncode is not None, "no zombie"
    assert ("notice", "handing off to the agent") in await transcript(store, task.id)
    (entry,) = await stats_lines(store, run.id)
    assert "failed (shutdown)" in entry
    # ...and no status is written: the rows are recovery's.
    assert (await task_of(store, run.id)).status is TaskStatus.in_progress
    assert await run_status(store, run.id) is RunStatus.running
    assert await engine_events(store, EventName.engine_stopping) == []

    # Step 2: the graph is gone, the name is unbound, the pool stays.
    assert "agentic" not in engine.graphs
    assert engine.pools.workflows_of("test") == ()
    assert "test" in engine.pools
    assert engine.pools.get("test").leased == 0
    assert engine.scheduler.in_flight == ()
    assert engine.attempts_of("agentic") == []
    assert task.id not in engine.live


# --------------------------------------------------------------------------
# A body waiting on a human
# --------------------------------------------------------------------------


async def test_unregister_cancels_a_waiting_attempt_and_leaves_its_row_waiting(
    start_engine, store: Store, requests_service, wait_until
) -> None:
    """A parked attempt is in flight (22 §Remove step 1), and its row stays."""

    engine: Engine = await start_engine(
        (asking_workflow("asks"), Pool("test", 1)), requests=requests_service
    )
    run = await engine.ops.submit("asks", "a run")
    await wait_until(lambda: _status_is(store, run.id, TaskStatus.waiting))
    task = await task_of(store, run.id)

    async with asyncio.timeout(DEADLINE):
        assert await engine.unregister("asks") == [task.id]

    assert (await task_of(store, run.id)).status is TaskStatus.waiting
    assert await run_status(store, run.id) is RunStatus.running
    assert engine.scheduler.in_flight == ()
    assert engine.pools.get("test").leased == 0
    assert not engine.pools.get("test").readmit, "a cancelled park queues no re-admit"
    assert "asks" not in engine.graphs


# --------------------------------------------------------------------------
# What is never claimed again, and what keeps running
# --------------------------------------------------------------------------


async def test_a_ready_task_of_the_workflow_is_never_claimed_again(
    start_engine, store: Store, run_to_completion, wait_for
) -> None:
    """Step 2's consequence: the claim filters by the pool's bound names.

    A sibling on the same pool is the clock — it completes only through
    ticks that would have claimed the doomed row if anything could.
    """

    doomed, sibling = Parked(), Parked()

    def quick(name: str) -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True)
        async def only() -> str:
            sibling.started.set()
            return "landed"

        return wf

    engine: Engine = await start_engine(
        (doomed.workflow("doomed"), Pool("test", 2)),
        (quick("sibling"), Pool("test", 2)),
    )
    running = await engine.ops.submit("doomed", "running")
    await wait_for(doomed.started)

    async with asyncio.timeout(DEADLINE):
        assert await engine.unregister("doomed") == [
            (await task_of(store, running.id)).id
        ]
    assert doomed.cancelled

    # A row of the workflow made ready afterwards — by hand, since the
    # operator verbs refuse an unregistered workflow — sits untouched.
    async with store.uow() as uow:
        orphan = await uow.runs.insert("doomed", "orphan")
        orphan_task = await uow.tasks.enqueue(orphan.id, "only", None, 0, False)
    engine.notify()
    kept = await engine.ops.submit("sibling", "kept")
    assert (await run_to_completion(kept.id)).status is RunStatus.completed
    await asyncio.sleep(0.1)

    assert (await task_of(store, orphan.id)).status is TaskStatus.ready
    assert orphan_task.id not in engine.scheduler.in_flight
    assert doomed.starts == 1
    assert engine.pools.workflows_of("test") == ("sibling",)


# --------------------------------------------------------------------------
# The raced claim
# --------------------------------------------------------------------------


class GatedStore:
    """The store, with the next ``uow()`` after :meth:`arm` held at a gate.

    What holds the loop inside its claim, so ``unregister`` can be shown
    to wait for that claim and to cancel the attempt it spawns.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self._armed = False
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    def arm(self) -> None:
        self._armed = True

    def uow(self) -> Any:
        if not self._armed:
            return self._store.uow()
        self._armed = False

        @asynccontextmanager
        async def gated() -> AsyncGenerator[Any]:
            self.entered.set()
            await self.gate.wait()
            async with self._store.uow() as uow:
                yield uow

        return gated()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


async def test_an_attempt_spawned_by_the_racing_claim_is_cancelled_too(
    start_engine, store: Store, wait_for
) -> None:
    """The call runs between ticks, so the claim in flight is counted.

    The second attempt is cancelled inside its first await, before it
    has a context, a node or a slot of its own to speak of — and the
    runner's ``finally`` still returns the slot without raising past it.
    """

    parked = Parked()
    engine: Engine = await start_engine((parked.workflow("raced"), Pool("test", 2)))
    first = await engine.ops.submit("raced", "first")
    await wait_for(parked.started)

    gated = GatedStore(store)
    engine.store = gated  # type: ignore[assignment]
    second = await engine.ops.submit("raced", "second")
    # `submit` notified and returned without yielding, so the next unit
    # of work anything opens is the tick's claim.
    gated.arm()
    await wait_for(gated.entered)

    removing = asyncio.create_task(engine.unregister("raced"))
    await asyncio.sleep(0.05)
    assert not removing.done(), "unregister ran across a claim in flight"

    with capture_logs() as logged:
        gated.gate.set()
        async with asyncio.timeout(DEADLINE):
            task_ids = await removing

    first_task = await task_of(store, first.id)
    second_task = await task_of(store, second.id)
    assert task_ids == [first_task.id, second_task.id]
    assert second_task.status is TaskStatus.in_progress
    assert parked.starts == 1, "the raced attempt never reached its body"
    assert not any(
        entry["event"] == "attempt raised past the runner" for entry in logged
    )
    assert engine.scheduler.in_flight == ()
    assert engine.pools.get("test").leased == 0
    assert engine.live.all() == []


# --------------------------------------------------------------------------
# The attempt that holds no id
# --------------------------------------------------------------------------


class GatedReader:
    """The store, with the next ``reader()`` after :meth:`arm` held at a gate.

    What holds an attempt inside ``_load_run`` — its first await, a read —
    so the attempt spawned before it can be ended underneath it.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self._armed = False
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    def arm(self) -> None:
        self._armed = True

    def reader(self) -> Any:
        if not self._armed:
            return self._store.reader()
        self._armed = False

        @asynccontextmanager
        async def gated() -> AsyncGenerator[Any]:
            self.entered.set()
            await self.gate.wait()
            async with self._store.reader() as reader:
                yield reader

        return gated()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


async def test_unregister_cancels_the_younger_attempt_of_a_re_dispatched_row(
    start_engine, store: Store, wait_for, wait_until
) -> None:
    """The attempt ``cancel_attempts`` cannot see is cancelled too, promptly.

    ``set_status(task, ready)`` on a row in flight spawns a second attempt
    under the first; the first keeps the id (D107), and once it has ended
    the second is the row's only attempt — running its body, registered
    live, with no id-keyed entry anywhere. ``unregister`` cancels what is
    live, not what holds an id: it returns when that attempt has been
    cancelled rather than when its body would have finished, and the
    status the body would have written is never written.

    The state is built from ``set_status``'s two halves — the write, then
    the cancel — with the younger attempt's first read held between
    them, which is what a slow ``finally`` on the older attempt (an agent
    killed under the grace period) does unaided.
    """

    parked = Parked()
    engine: Engine = await start_engine((parked.workflow("twice"), Pool("test", 2)))
    run = await engine.ops.submit("twice", "a run")
    await wait_for(parked.started)
    task = await task_of(store, run.id)

    gated = GatedReader(store)
    engine.store = gated  # type: ignore[assignment]
    async with store.uow() as uow:
        await uow.tasks.set_status(task.id, TaskStatus.ready)
    # The next read anything opens is the younger attempt's `_load_run`:
    # the claim is a unit of work, and the older attempt is asleep.
    gated.arm()
    engine.notify()
    await wait_for(gated.entered)

    # The older attempt ends under it and is reaped: the id has no holder.
    assert engine.scheduler.cancel_attempts([task.id]) == [task.id]
    await wait_until(lambda: _reaped(engine, task.id))
    assert parked.cancelled

    # Nothing holds the id, so the younger passes the registry and runs.
    parked.started.clear()
    parked.cancelled = False
    gated.gate.set()
    await wait_for(parked.started)
    assert parked.starts == 2
    assert task.id in engine.live
    assert engine.scheduler.in_flight == ()
    assert engine.attempts_of("twice") == [task.id]

    with capture_logs() as logged:
        async with asyncio.timeout(DEADLINE):
            assert await engine.unregister("twice") == [task.id]

    assert parked.cancelled
    assert (await task_of(store, run.id)).status is TaskStatus.in_progress
    assert await run_status(store, run.id) is RunStatus.running
    assert not any(
        entry["event"] == "attempt raised past the runner" for entry in logged
    )
    assert "twice" not in engine.graphs
    assert engine.attempts_of("twice") == []
    assert engine.scheduler.in_flight == ()
    assert engine.pools.get("test").leased == 0
    assert engine.live.all() == []


async def _reaped(engine: Engine, task_id: int) -> bool:
    return task_id not in engine.scheduler.in_flight


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------


async def test_unregister_refuses_an_unknown_name(engines) -> None:
    engine: Engine = engines()
    engine.register(Parked().workflow("known").finalize(), Pool("test", 1))
    with pytest.raises(KeyError, match="'unknown' is not registered"):
        await engine.unregister("unknown")
    assert "known" in engine.graphs
    assert engine.pools.workflows_of("test") == ("known",)


async def test_unregister_on_a_never_started_engine_just_edits_the_registries(
    engines,
) -> None:
    engine: Engine = engines()
    engine.register(Parked().workflow("idle").finalize(), Pool("test", 1))

    assert await engine.unregister("idle") == []

    assert engine.graphs == {}
    assert engine.pools.workflows_of("test") == ()
    assert "test" in engine.pools


async def test_stop_after_an_unregister_is_quiet(
    start_engine, store: Store, wait_for
) -> None:
    """Nothing is in flight any more, so the shutdown announces nothing."""

    parked = Parked()
    engine: Engine = await start_engine((parked.workflow("gone"), Pool("test", 1)))
    await engine.ops.submit("gone", "a run")
    await wait_for(parked.started)

    async with asyncio.timeout(DEADLINE):
        assert len(await engine.unregister("gone")) == 1
        await engine.stop()

    assert await engine_events(store, EventName.engine_stopping) == []


async def _status_is(store: Store, run_id: str, status: TaskStatus) -> bool:
    return (await task_of(store, run_id)).status is status

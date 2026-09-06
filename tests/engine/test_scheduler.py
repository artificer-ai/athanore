"""The dispatch loop: capacity, order, waking and stopping (T025).

The scheduler decides nothing about *which* task runs — that is the
claim's ordering, and ``tests/store`` pins it — so what is asserted here
is the loop's own contract:

- a pool's capacity is a real cap, so ``workers=1`` means one body at a
  time and ``capacity=0`` means none, ever;
- the re-admit queue is served before the store is asked for new work,
  which is what keeps a half-finished body from starving (04 §Waiting);
- ``notify()`` wakes the loop, so dispatch is not paced by the tick. The
  timing assertion is deliberate: with a tick far longer than the bound
  it asserts, a broken ``notify`` makes this file slow rather than green;
- an exception in a tick is logged and the loop carries on;
- ``stop()`` cancels what is running, gets the slots back, and writes no
  task status (D52).

Nothing here sleeps for a real second. The waits are either an event a
body set or a poll of the store, both under an ``asyncio.timeout`` that
only expires when something is actually broken.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

import pytest
from structlog.testing import capture_logs

from athanore.engine.live import LiveRegistry
from athanore.engine.pools import Pool, PoolRegistry
from athanore.engine.scheduler import Scheduler
from athanore.events.names import EventName
from athanore.graph import Graph
from athanore.settings import AthanoreSettings
from athanore.store.rows import EventRow, RunRow, RunStatus, TaskRow, TaskStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow

#: Short enough that a test which waits for a tick is not waiting long,
#: long enough that a loop under load is not spinning. Every test that
#: depends on being woken rather than ticked overrides it.
TICK = 0.02

#: The fuse on every wait in this file. Reached only when the loop is
#: broken, so it is generous: a slow container must not make this flaky.
DEADLINE = 5.0


# --------------------------------------------------------------------------
# The engine the scheduler runs against
# --------------------------------------------------------------------------


class Fleet:
    """A stub engine with real pools, and the scheduler under test.

    The five members :func:`~athanore.engine.runner.run_attempt` reads,
    plus the ``pools`` the loop iterates —
    ``athanore.engine.scheduler.SchedulerEngine`` and nothing more. The
    real ``Engine`` is T027's; wiring one here would test the wiring
    instead of the loop. ``notify()`` is the engine's, and forwards to
    the scheduler exactly as T027's will.
    """

    def __init__(
        self,
        store: Store,
        settings: AthanoreSettings,
        pools: Mapping[str, int],
        *,
        tick: float,
    ) -> None:
        self.store = store
        self.settings = settings
        self.live = LiveRegistry()
        self.graphs: dict[str, Graph] = {}
        self.pools = PoolRegistry()
        for name, capacity in pools.items():
            self.pools.add(Pool(name, capacity=capacity))
        self.notifications = 0
        self.scheduler = Scheduler(self, tick=tick)

    def notify(self) -> None:
        self.notifications += 1
        self.scheduler.notify()

    # -- registration and submission ---------------------------------------

    def register(self, workflow: Workflow, pool: str = "test") -> Graph:
        """Finalize ``workflow`` and run it on ``pool`` (``server.register``)."""

        graph = workflow.finalize()
        self.graphs[graph.name] = graph
        self.pools.bind(graph.name, pool)
        return graph

    async def submit(
        self,
        workflow: str,
        payload: Any = None,
        title: str = "a run",
        *,
        wake: bool = True,
    ) -> str:
        """A queued run with its start task ready (``ops.submit``, T027a).

        ``wake=False`` skips the ``notify()`` a real submission makes, so
        a test can watch the tick find the work on its own.
        """

        graph = self.graphs[workflow]
        node = graph.start_node
        explicit = node.priority is not None
        priority = node.priority if node.priority is not None else -node.generation
        async with self.store.uow() as uow:
            run = await uow.runs.insert(workflow, title)
            await uow.tasks.enqueue(
                run.id, node.name, payload, priority, explicit, lineage=None
            )
        if wake:
            self.notify()
        return run.id

    # -- reading the store back --------------------------------------------

    async def run(self, run_id: str) -> RunRow:
        async with self.store.reader() as reader:
            row = await reader.runs.get(run_id)
        assert row is not None
        return row

    async def tasks(self, run_id: str) -> list[TaskRow]:
        async with self.store.reader() as reader:
            return await reader.tasks.list_for_run(run_id)

    async def only_task(self, run_id: str) -> TaskRow:
        (task,) = await self.tasks(run_id)
        return task

    async def is_completed(self, run_id: str) -> bool:
        return (await self.run(run_id)).status == RunStatus.completed

    async def events_named(self, run_id: str, name: str) -> list[EventRow]:
        async with self.store.reader() as reader:
            rows = await reader.events.list_for_run(run_id)
        return [row for row in rows if row.name == name]


@pytest.fixture
async def fleet(
    store: Store, settings: AthanoreSettings
) -> AsyncIterator[Callable[..., Fleet]]:
    """Make fleets, and stop every scheduler they started.

    The teardown is the point: a loop task left running would outlive
    its test and claim against the next one's database.
    """

    made: list[Fleet] = []

    def make(pools: Mapping[str, int] | None = None, *, tick: float = TICK) -> Fleet:
        one = Fleet(store, settings, pools or {"test": 1}, tick=tick)
        made.append(one)
        return one

    yield make
    for one in made:
        await one.scheduler.stop()


# --------------------------------------------------------------------------
# Workflows and waiting
# --------------------------------------------------------------------------


def single(name: str, body: Callable[[], Awaitable[Any]]) -> Workflow:
    """A one-node workflow whose only node awaits ``body()``."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def only() -> Any:
        return await body()

    return wf


async def wait_until(check: Callable[[], Awaitable[bool]]) -> None:
    """Poll ``check`` until it is true, or fail the test.

    A poll rather than an event, for the assertions that are about a row
    the runner writes after the body returned.
    """

    async with asyncio.timeout(DEADLINE):
        while True:
            if await check():
                return
            await asyncio.sleep(0.005)


async def idle(one: Fleet, pool: str = "test") -> bool:
    """Whether ``pool`` has every one of its slots back."""

    state = one.pools.get(pool)
    return state.free() == state.capacity


async def leased(one: Fleet, count: int, pool: str = "test") -> bool:
    """Whether ``pool`` has exactly ``count`` slots out."""

    return one.pools.get(pool).leased == count


async def wait_for(event: asyncio.Event) -> None:
    """Wait for ``event``, or fail the test."""

    async with asyncio.timeout(DEADLINE):
        await event.wait()


class Overlap:
    """How many bodies were inside at once, and how many ran at all."""

    def __init__(self, expected: int) -> None:
        self.inside = 0
        self.peak = 0
        self.finished = 0
        self.done = asyncio.Event()
        self._expected = expected

    async def body(self) -> str:
        self.inside += 1
        self.peak = max(self.peak, self.inside)
        # Long enough that a loop which ignored capacity would have
        # spawned the second attempt into this window many times over.
        await asyncio.sleep(0.01)
        self.inside -= 1
        self.finished += 1
        if self.finished >= self._expected:
            self.done.set()
        return "done"


# --------------------------------------------------------------------------
# Capacity
# --------------------------------------------------------------------------


async def test_one_worker_runs_two_ready_tasks_one_after_the_other(fleet) -> None:
    one = fleet({"test": 1})
    overlap = Overlap(expected=2)
    one.register(single("serial", overlap.body))
    first = await one.submit("serial")
    second = await one.submit("serial")

    await one.scheduler.start()
    await wait_for(overlap.done)

    assert overlap.peak == 1, "two bodies were inside a pool of capacity 1"
    await wait_until(lambda: one.is_completed(first))
    await wait_until(lambda: one.is_completed(second))
    # The claim flags the first task of a run it moved `queued → running`
    # and the attempt publishes it, so exactly one `run.started` reaches
    # the timeline however the two paths are read (D107).
    for run_id in (first, second):
        assert len(await one.events_named(run_id, EventName.run_started)) == 1


async def test_a_wider_pool_runs_both_at_once(fleet) -> None:
    """The counterpart: the cap is capacity, not the loop's shape."""

    one = fleet({"test": 2})
    overlap = Overlap(expected=2)
    one.register(single("parallel", overlap.body))
    await one.submit("parallel")
    await one.submit("parallel")

    await one.scheduler.start()
    await wait_for(overlap.done)

    assert overlap.peak == 2


async def test_a_pool_of_capacity_zero_never_claims(fleet) -> None:
    """`capacity=0` parks a workflow: queued, and never dispatched.

    The run on the live pool is the clock — it cannot complete without a
    tick that gave every pool its turn, so the parked task being
    untouched afterwards is a decision the loop made, not one it never
    got to.
    """

    one = fleet({"parked": 0, "test": 1, "idle": 4})
    ran = asyncio.Event()

    async def never() -> None:  # pragma: no cover - the point is that it does not
        raise AssertionError("a parked pool dispatched a task")

    async def clock() -> str:
        ran.set()
        return "tick"

    one.register(single("parked_wf", never), pool="parked")
    one.register(single("live_wf", clock), pool="test")
    slow = await one.submit("parked_wf")
    live = await one.submit("live_wf")

    await one.scheduler.start()
    await wait_for(ran)
    await wait_until(lambda: one.is_completed(live))

    assert (await one.only_task(slow)).status == TaskStatus.ready
    assert (await one.run(slow)).status == RunStatus.queued
    assert one.scheduler.in_flight == ()
    # The pool nothing is registered on never spent a slot on another
    # pool's work either (strict reservation).
    assert one.pools.get("idle").leased == 0


# --------------------------------------------------------------------------
# The re-admit queue
# --------------------------------------------------------------------------


async def test_readmits_are_served_before_the_store_is_asked_for_work(fleet) -> None:
    """A body that was answered goes ahead of every ready task (04 §Waiting)."""

    one = fleet({"test": 1})
    ran = asyncio.Event()

    async def body() -> str:
        ran.set()
        return "done"

    one.register(single("readmit", body))
    run_id = await one.submit("readmit")

    pool = one.pools.get("test")
    readmitted = pool.request_readmit(4242)

    await one.scheduler.start()
    lease = await asyncio.wait_for(readmitted, DEADLINE)

    # The queue took the pool's only slot, so the ready task stayed ready.
    assert lease.task_id == 4242
    assert pool.free() == 0
    assert not ran.is_set()
    assert (await one.only_task(run_id)).status == TaskStatus.ready

    # ...and it dispatches as soon as the waiter gives the slot back.
    lease.release()
    one.scheduler.notify()
    await wait_for(ran)
    await wait_until(lambda: one.is_completed(run_id))


# --------------------------------------------------------------------------
# Waking
# --------------------------------------------------------------------------


async def test_notify_wakes_the_loop_before_the_tick_elapses(fleet) -> None:
    """Dispatch is paced by `notify()`; the tick is only a safety net.

    The tick here is two seconds and the assertion is half of one, so a
    `notify()` that did not wake the loop fails this test slowly instead
    of passing it.
    """

    one = fleet({"test": 1}, tick=2.0)
    ran = asyncio.Event()

    async def body() -> str:
        ran.set()
        return "done"

    one.register(single("woken", body))
    await one.scheduler.start()
    # Let the first tick find an empty queue and settle into its wait.
    await asyncio.sleep(0.05)
    assert not ran.is_set()

    started = asyncio.get_running_loop().time()
    await one.submit("woken")  # submit notifies, as `ops.submit` does
    await wait_for(ran)

    assert asyncio.get_running_loop().time() - started < 0.5


async def test_the_tick_dispatches_without_a_notify(fleet) -> None:
    """A task made ready behind the engine's back still runs, one tick later."""

    one = fleet({"test": 1})
    ran = asyncio.Event()

    async def body() -> str:
        ran.set()
        return "done"

    one.register(single("ticked", body))
    await one.scheduler.start()
    await asyncio.sleep(0.05)

    run_id = await one.submit("ticked", wake=False)
    await wait_for(ran)
    await wait_until(lambda: one.is_completed(run_id))


# --------------------------------------------------------------------------
# Failure inside the loop
# --------------------------------------------------------------------------


class FlakyStore:
    """The store, with the first ``uow()`` of a claim raising.

    A claim that fails is the realistic tick failure — the writer is
    wedged, the disk is full — and the loop's contract is that it is
    logged and the next tick happens anyway.
    """

    def __init__(self, store: Store, failures: int) -> None:
        self._store = store
        self.failures = failures

    def uow(self) -> Any:
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("the writer is wedged")
        return self._store.uow()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


async def test_a_failing_tick_is_logged_and_the_loop_carries_on(fleet) -> None:
    one = fleet({"test": 1})
    ran = asyncio.Event()

    async def body() -> str:
        ran.set()
        return "done"

    one.register(single("flaky", body))
    run_id = await one.submit("flaky")
    flaky = FlakyStore(one.store, failures=1)
    one.store = flaky  # type: ignore[assignment]

    with capture_logs() as logged:
        await one.scheduler.start()
        await wait_for(ran)

    assert flaky.failures == 0
    assert any(entry["event"] == "pool dispatch failed" for entry in logged)
    await wait_until(lambda: one.is_completed(run_id))
    # The slots the failed claim had reserved went back to the pool, and
    # so did the one the attempt after it ran on.
    await wait_until(lambda: idle(one))


# --------------------------------------------------------------------------
# Cancelling and stopping
# --------------------------------------------------------------------------


class Parked:
    """A body that announces itself and then never returns."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False
        self.starts = 0

    async def body(self) -> None:
        self.starts += 1
        self.started.set()
        try:
            await asyncio.sleep(DEADLINE * 10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def test_stop_cancels_a_running_body_and_returns(fleet) -> None:
    one = fleet({"test": 1})
    parked = Parked()
    one.register(single("parked", parked.body))
    run_id = await one.submit("parked")

    await one.scheduler.start()
    await wait_for(parked.started)
    assert one.scheduler.in_flight == ((await one.only_task(run_id)).id,)

    async with asyncio.timeout(DEADLINE):
        await one.scheduler.stop()

    assert parked.cancelled
    assert one.scheduler.in_flight == ()
    assert not one.scheduler.running
    assert one.pools.get("test").free() == 1
    # A shutdown writes no task status: the row is recovery's (D52).
    assert (await one.only_task(run_id)).status == TaskStatus.in_progress


async def test_stop_is_idempotent_and_safe_before_a_start(fleet) -> None:
    one = fleet({"test": 1})
    await one.scheduler.stop()
    await one.scheduler.start()
    await one.scheduler.stop()
    await one.scheduler.stop()
    assert not one.scheduler.running


async def test_starting_twice_is_a_defect(fleet) -> None:
    one = fleet({"test": 1})
    await one.scheduler.start()
    with pytest.raises(RuntimeError, match="already running"):
        await one.scheduler.start()


async def test_cancel_attempts_ends_the_named_attempts_only(fleet) -> None:
    """The hook the operator operations end a live task through (T027b)."""

    one = fleet({"test": 2})
    first, second = Parked(), Parked()
    one.register(single("one_wf", first.body), pool="test")
    one.register(single("two_wf", second.body), pool="test")
    kept = await one.submit("one_wf")
    killed = await one.submit("two_wf")

    await one.scheduler.start()
    await wait_for(first.started)
    await wait_for(second.started)

    doomed = (await one.only_task(killed)).id
    assert one.scheduler.cancel_attempts([doomed, 9999]) == [doomed]

    await wait_until(lambda: _resolved(one, doomed))
    assert second.cancelled
    assert not first.cancelled
    assert one.scheduler.in_flight == ((await one.only_task(kept)).id,)
    # The cancelled attempt's slot comes back. Polled rather than read
    # once, unlike the stopped-scheduler case above: a live loop takes
    # the free slots *before* it asks the store for work and gives back
    # the ones it did not use (D107), so a single read of `free()` can
    # land inside a reservation that is about to be released — which is
    # a scheduler tick away, and was a flake under a slow interpreter.
    await wait_until(lambda: leased(one, 1))
    # Cancelling a task nothing is running is not an error, and the
    # attempt already reaped cannot be cancelled twice.
    assert one.scheduler.cancel_attempts([doomed]) == []


async def test_a_row_re_dispatched_under_a_live_attempt_leaks_no_slot(
    fleet,
) -> None:
    """A second attempt of one task is survivable, and costs no capacity.

    ``set_status(task, ready)`` on an ``in_progress`` row (04 §Operator
    operations, T027b) is the one way a task the loop is already running
    can be claimed again. Two attempts of one task is a defect, and the
    live registry refuses the younger one on the spot; what must not
    happen on top of it is the older attempt losing its slot and its
    cancellation, which under ``workers=1`` is the whole engine wedged.
    """

    one = fleet({"test": 2})
    parked = Parked()
    one.register(single("redispatched", parked.body))
    run_id = await one.submit("redispatched")

    await one.scheduler.start()
    await wait_for(parked.started)
    task_id = (await one.only_task(run_id)).id
    assert await leased(one, 1)

    async with one.store.uow() as uow:
        await uow.tasks.set_status(task_id, TaskStatus.ready)
    one.scheduler.notify()

    # The row goes back to `in_progress` when the loop claims it again...
    await wait_until(lambda: _status_is(one, run_id, TaskStatus.in_progress))
    # ...and the attempt it was claimed for refuses itself and gives its
    # slot straight back, without ever reaching the body.
    await wait_until(lambda: leased(one, 1))
    assert parked.starts == 1

    # The older attempt still owns the id, so it is still cancellable.
    assert one.scheduler.in_flight == (task_id,)
    assert one.scheduler.cancel_attempts([task_id]) == [task_id]
    await wait_until(lambda: idle(one))
    assert parked.cancelled


async def _status_is(one: Fleet, run_id: str, status: TaskStatus) -> bool:
    return (await one.only_task(run_id)).status == status


async def _resolved(one: Fleet, task_id: int) -> bool:
    return task_id not in one.scheduler.in_flight

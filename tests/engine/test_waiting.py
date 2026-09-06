"""Releasing the pool slot while a body waits on a human (T026, 04 §Waiting).

This is the mechanism that makes a one-worker install usable. The MVP
parked the body with its worker slot still held, so under ``workers=1``
one playtest question stalled the whole server; ``ctx.services.lease
.released()`` gives the slot back for the duration of the wait and takes
one again through the pool's re-admit queue afterwards.

Four things are asserted, and they are the four ways this can be wrong:

- the slot really is free while the body waits, so a second ready task
  runs inside the window;
- the waiter is re-admitted **ahead** of a ready task, because it is
  mid-execution and queued once already (04 §Waiting, D43);
- the node ``timeout`` is *paused*, not merely restored on the way out:
  a node capped at 0.25 s that waits 0.4 s neither dies inside the wait
  nor comes back with a fresh budget — it comes back with what was left;
- capacity accounting is exact. A resumed body holds a **different**
  lease from the one it was dispatched with, and the runner's ``finally``
  has to release that one: the scheduler's reap only knows the first, so
  a slot lost here is, under ``workers=1``, the engine wedged until a
  restart.

``human_input`` is T033's; the bodies here call the service directly,
which is also the layer the behaviour lives at.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

import pytest

from athanore.engine.context import TaskContext, current_task
from athanore.engine.live import LiveRegistry
from athanore.engine.pools import Lease, Pool, PoolRegistry, PoolState
from athanore.engine.scheduler import Scheduler
from athanore.engine.services import TaskServices
from athanore.events.names import EventName
from athanore.graph import Graph
from athanore.settings import AthanoreSettings
from athanore.store.rows import EventRow, RunStatus, TaskRow, TaskStatus
from athanore.store.uow import Store
from athanore.workflow import Workflow

#: Short enough not to pace a test, long enough not to spin. Every wake-up
#: that matters here comes from `notify()`.
TICK = 0.02

#: The fuse on every wait. Reached only when something is broken.
DEADLINE = 5.0

#: A node budget and a wait longer than it: the pause is what stops the
#: second from spending the first (04 §Timeouts).
BUDGET = 0.25
BURNED = 0.1
PARKED = 0.4

WORKFLOW = "demo"
FLUSH_INTERVAL = 0.05


# --------------------------------------------------------------------------
# The engine the scheduler runs against
# --------------------------------------------------------------------------


class Fleet:
    """A stub engine with real pools, and the scheduler under test.

    ``athanore.engine.scheduler.SchedulerEngine`` and nothing more, for
    the reason ``tests/engine/test_scheduler.py`` gives: the real
    ``Engine`` is T027's, and wiring one here would test the wiring
    instead of the waiting.
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
        # No request service: these tests drive `lease.released()` with a
        # request id directly rather than through the port (T032).
        self.requests = None
        self.scheduler = Scheduler(self, tick=tick)

    def notify(self) -> None:
        self.scheduler.notify()

    def register(self, workflow: Workflow, pool: str = "test") -> Graph:
        graph = workflow.finalize()
        self.graphs[graph.name] = graph
        self.pools.bind(graph.name, pool)
        return graph

    async def submit(self, workflow: str, title: str = "a run") -> str:
        """A queued run with its start task ready (``ops.submit``, T027a)."""

        graph = self.graphs[workflow]
        node = graph.start_node
        explicit = node.priority is not None
        priority = node.priority if node.priority is not None else -node.generation
        async with self.store.uow() as uow:
            run = await uow.runs.insert(workflow, title)
            await uow.tasks.enqueue(
                run.id, node.name, None, priority, explicit, lineage=None
            )
        self.notify()
        return run.id

    # -- reading the store back --------------------------------------------

    async def only_task(self, run_id: str) -> TaskRow:
        async with self.store.reader() as reader:
            (task,) = await reader.tasks.list_for_run(run_id)
        return task

    async def status(self, run_id: str) -> TaskStatus:
        return TaskStatus((await self.only_task(run_id)).status)

    async def is_completed(self, run_id: str) -> bool:
        async with self.store.reader() as reader:
            run = await reader.runs.get(run_id)
        assert run is not None
        return run.status == RunStatus.completed

    async def events_named(self, run_id: str, name: str) -> list[EventRow]:
        async with self.store.reader() as reader:
            rows = await reader.events.list_for_run(run_id)
        return [row for row in rows if row.name == name]

    def pool(self, name: str = "test") -> PoolState:
        return self.pools.get(name)


@pytest.fixture
async def fleet(
    store: Store, settings: AthanoreSettings
) -> AsyncIterator[Callable[..., Fleet]]:
    """Make fleets, and stop every scheduler they started.

    The teardown also asserts nothing: a slot leaked by a test is asserted
    by that test, because "which one leaked it" is the whole diagnosis.
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
# Bodies
# --------------------------------------------------------------------------


class Question:
    """One body's park: it waits inside ``released()`` until answered.

    ``request_id`` is what a real ``human_input`` would pass in from the
    request it opened (06); nothing here needs the request itself, and
    T033 is what puts the two together.
    """

    def __init__(self, request_id: int = 7) -> None:
        self.request_id = request_id
        self.parked = asyncio.Event()
        self.answered = asyncio.Event()
        self.resumed = asyncio.Event()
        #: The lease held before the park and the one held after it.
        self.leases: list[Lease | None] = []

    async def ask(self) -> str:
        ctx = current_task()
        self.leases.append(ctx.services.lease.held)
        async with ctx.services.lease.released(self.request_id):
            self.parked.set()
            await self.answered.wait()
        self.leases.append(ctx.services.lease.held)
        self.resumed.set()
        return "answered"

    def answer(self) -> None:
        self.answered.set()


def single(
    name: str, body: Callable[[], Awaitable[Any]], *, timeout: float | None = None
) -> Workflow:
    """A one-node workflow whose only node awaits ``body()``."""

    wf = Workflow(name)

    @wf.node(start=True, timeout=timeout, retries=0)
    async def only() -> Any:
        return await body()

    return wf


async def wait_for(event: asyncio.Event) -> None:
    """Wait for ``event``, or fail the test."""

    async with asyncio.timeout(DEADLINE):
        await event.wait()


async def wait_until(check: Callable[[], Awaitable[bool]]) -> None:
    """Poll ``check`` until it is true, or fail the test."""

    async with asyncio.timeout(DEADLINE):
        while True:
            if await check():
                return
            await asyncio.sleep(0.005)


def idle(one: Fleet, pool: str = "test") -> bool:
    """Whether ``pool`` has every one of its slots back."""

    state = one.pool(pool)
    return state.leased == 0 and state.free() == state.capacity


async def settled(one: Fleet, pool: str = "test") -> bool:
    """:func:`idle`, as something :func:`wait_until` can poll.

    A run reads `completed` inside the transaction that ended its last
    attempt, and the lease goes back in the ``finally`` after it, so the
    two are ordered but not simultaneous.
    """

    return idle(one, pool)


async def status_is(one: Fleet, run_id: str, *statuses: TaskStatus) -> bool:
    """Whether the run's one task is in any of ``statuses`` right now."""

    return await one.status(run_id) in statuses


async def queued(pool: PoolState, count: int = 1) -> bool:
    """Whether ``count`` waiters are in the pool's re-admit queue."""

    return len(pool.readmit) == count


# --------------------------------------------------------------------------
# The slot is really free
# --------------------------------------------------------------------------


async def test_a_waiting_body_lets_the_next_ready_task_have_the_slot(fleet) -> None:
    """`workers=1` and a parked body: the pool's one slot is free.

    The MVP's failure, inverted into an assertion — the second run must
    finish while the first is still inside `released()`.
    """

    one = fleet({"test": 1})
    question = Question()
    ran = asyncio.Event()

    async def quick() -> str:
        ran.set()
        return "done"

    one.register(single("asks", question.ask))
    one.register(single("quick", quick))
    asking = await one.submit("asks")
    quickly = await one.submit("quick")

    await one.scheduler.start()
    await wait_for(question.parked)

    # The waiter is `waiting` and holds nothing...
    await wait_until(lambda: status_is(one, asking, TaskStatus.waiting))
    first = question.leases[0]
    assert first is not None and first.released

    # ...so the task behind it runs and finishes, inside the window.
    await wait_for(ran)
    await wait_until(lambda: one.is_completed(quickly))
    assert not question.resumed.is_set()
    assert await one.status(asking) == TaskStatus.waiting

    question.answer()
    await wait_for(question.resumed)
    await wait_until(lambda: one.is_completed(asking))
    await wait_until(lambda: settled(one))


async def test_the_pair_of_events_and_the_two_statuses(fleet) -> None:
    """`task.waiting` on the way in, `task.resumed` on the way out (18)."""

    one = fleet({"test": 1})
    question = Question(request_id=42)
    one.register(single("asks", question.ask))
    run_id = await one.submit("asks")

    await one.scheduler.start()
    await wait_for(question.parked)
    await wait_until(lambda: status_is(one, run_id, TaskStatus.waiting))

    (waiting,) = await one.events_named(run_id, EventName.task_waiting)
    assert waiting.data == {"node": "only", "request_id": 42}
    assert not await one.events_named(run_id, EventName.task_resumed)

    question.answer()
    await wait_for(question.resumed)
    await wait_until(lambda: one.is_completed(run_id))

    task = await one.only_task(run_id)
    assert task.status == TaskStatus.done
    assert task.result == "answered"
    (resumed,) = await one.events_named(run_id, EventName.task_resumed)
    assert resumed.data["node"] == "only"
    assert resumed.data["request_id"] == 42
    # Real data only: the wait is measured, not estimated.
    assert resumed.data["waited_s"] > 0
    await wait_until(lambda: settled(one))


# --------------------------------------------------------------------------
# Order: a re-admit beats a ready task
# --------------------------------------------------------------------------


async def test_the_waiter_re_acquires_before_a_third_ready_task(fleet) -> None:
    """The freed slot goes to the answered body, not to the queue.

    The shape is the one that can tell them apart: the answer arrives
    while another task holds the pool's only slot, so both the waiter and
    a fresh `ready` task want it at the moment it comes back.
    """

    one = fleet({"test": 1})
    order: list[str] = []
    question = Question()
    holding = asyncio.Event()
    let_go = asyncio.Event()
    third_ran = asyncio.Event()

    async def asks() -> str:
        order.append("asks")
        answer = await question.ask()
        order.append("asks-resumed")
        return answer

    async def holds() -> str:
        order.append("holds")
        holding.set()
        await let_go.wait()
        return "done"

    async def third() -> str:
        order.append("third")
        third_ran.set()
        return "done"

    one.register(single("asks", asks))
    one.register(single("holds", holds))
    one.register(single("third", third))
    asking = await one.submit("asks")
    await one.scheduler.start()
    await wait_for(question.parked)

    # The second task takes the slot the waiter gave back.
    holds_run = await one.submit("holds")
    await wait_for(holding)

    # Now the answer arrives, and only then is a third task made ready:
    # the waiter is in the queue, the newcomer is in the store.
    question.answer()
    await wait_until(lambda: queued(one.pool()))
    third_run = await one.submit("third")
    await asyncio.sleep(TICK * 2)  # ...ticks with no free slot change nothing
    assert not third_ran.is_set()
    assert await one.status(asking) == TaskStatus.waiting

    let_go.set()
    await wait_for(question.resumed)
    assert not third_ran.is_set(), "a ready task overtook a body already running"

    await wait_until(lambda: one.is_completed(third_run))
    assert order == ["asks", "holds", "asks-resumed", "third"]
    assert await one.is_completed(asking)
    assert await one.is_completed(holds_run)
    await wait_until(lambda: settled(one))


# --------------------------------------------------------------------------
# The node timeout is paused
# --------------------------------------------------------------------------


async def test_a_wait_longer_than_the_node_timeout_does_not_fail_it(fleet) -> None:
    """`timeout=0.25` and a 0.4 s wait: the clock does not run while waiting.

    This is the reason the task exists. Without the pause the body is
    cancelled inside the wait; with a pause that forgets to re-arm, the
    attempt has no budget left to overrun.
    """

    one = fleet({"test": 1})
    remaining: list[float] = []

    async def slow() -> str:
        ctx = current_task()
        async with ctx.services.lease.released(1):
            await asyncio.sleep(PARKED)
        loop = asyncio.get_running_loop()
        scope = ctx._timeout  # pyright: ignore[reportPrivateUsage]
        assert scope is not None
        when = scope.when()
        assert when is not None, "the node timeout was left disarmed"
        remaining.append(when - loop.time())
        return "done"

    one.register(single("slow", slow, timeout=BUDGET))
    run_id = await one.submit("slow")

    await one.scheduler.start()
    await wait_until(lambda: one.is_completed(run_id))

    task = await one.only_task(run_id)
    assert task.status == TaskStatus.done
    assert task.result == "done"
    # Re-armed with what was left, so it is a budget and not a fresh one.
    assert 0 < remaining[0] <= BUDGET
    await wait_until(lambda: settled(one))


async def test_the_budget_that_comes_back_is_what_was_left_of_it(fleet) -> None:
    """The resumed body still dies of the time it spent *before* parking.

    `BURNED` of the node's `BUDGET` is spent before the wait, so the
    attempt has less than `BUDGET - BURNED` left when it resumes and an
    overrun of `BUDGET` fails it. A timeout re-armed at the full budget —
    or never re-armed — passes the test above and fails this one.
    """

    one = fleet({"test": 1})

    async def slow() -> str:
        ctx = current_task()
        await asyncio.sleep(BURNED)
        async with ctx.services.lease.released(1):
            await asyncio.sleep(PARKED)
        await asyncio.sleep(BUDGET)  # more than what is left
        return "done"  # pragma: no cover - the timeout fires first

    one.register(single("slow", slow, timeout=BUDGET))
    run_id = await one.submit("slow")

    await one.scheduler.start()
    await wait_until(
        lambda: status_is(one, run_id, TaskStatus.dead_letter, TaskStatus.done)
    )

    task = await one.only_task(run_id)
    assert task.status == TaskStatus.dead_letter, "the paused clock never restarted"
    assert task.error is not None and "TimeoutError" in task.error
    await wait_until(lambda: settled(one))


# --------------------------------------------------------------------------
# Capacity accounting
# --------------------------------------------------------------------------


async def test_the_lease_released_at_the_end_is_the_re_acquired_one(fleet) -> None:
    """A resumed body holds a different lease, and that is the one given back.

    The scheduler's reap only knows the lease it handed over, so if the
    runner's `finally` released that one instead, the pool would end the
    run a slot short with nothing left to give it back.
    """

    one = fleet({"test": 1})
    question = Question()
    one.register(single("asks", question.ask))
    run_id = await one.submit("asks")

    await one.scheduler.start()
    await wait_for(question.parked)
    # The first lease went back the moment the body parked.
    first = question.leases[0]
    assert first is not None and first.released

    question.answer()
    await wait_for(question.resumed)
    second = question.leases[1]
    assert second is not None
    assert second is not first, "the body resumed on the lease it had given back"
    assert not second.released
    assert second.pool_state is one.pool()

    await wait_until(lambda: one.is_completed(run_id))
    await wait_until(lambda: settled(one))
    assert second.released, "the runner released the lease it started with"


async def test_stopping_while_a_body_waits_leaks_no_slot(fleet) -> None:
    """A shutdown cancels the waiter: no re-admit, no status, no slot held.

    The row is left `waiting` on purpose — recovery turns it back into
    `ready` (04 §Recovery), and writing a status here is how a graceful
    restart loses work (D52).
    """

    one = fleet({"test": 1})
    question = Question()
    one.register(single("asks", question.ask))
    run_id = await one.submit("asks")

    await one.scheduler.start()
    await wait_for(question.parked)
    await one.scheduler.stop()

    assert not question.resumed.is_set()
    assert await one.status(run_id) == TaskStatus.waiting
    assert not await one.events_named(run_id, EventName.task_resumed)
    await wait_until(lambda: settled(one))
    assert not one.pool().readmit


# --------------------------------------------------------------------------
# The service on its own
# --------------------------------------------------------------------------


async def attached(store: Store, pool: PoolState, node: str = "ask") -> TaskContext:
    """A run, its task and a services bundle attached to a real lease.

    What the runner builds, minus the runner: these are the tests about
    `released()` itself rather than about an attempt.
    """

    async with store.uow() as uow:
        run = await uow.runs.insert(WORKFLOW, "a run")
        task = await uow.tasks.enqueue(run.id, node, None, priority=0, explicit=False)
    services = TaskServices(
        store,
        run_id=run.id,
        task_id=task.id,
        node=node,
        workflow=WORKFLOW,
        flush_interval=FLUSH_INTERVAL,
    )
    context = TaskContext(
        run_id=run.id,
        task_id=task.id,
        workflow=WORKFLOW,
        node=node,
        attempt=1,
        token=f"tok-{task.id}",
        api_base="http://127.0.0.1:4002",
        services=services,
    )
    lease = pool.try_acquire(task.id)
    assert lease is not None
    services.lease.attach(context, lease, lambda: None)
    return context


async def test_a_lease_handed_to_a_waiter_that_is_cancelled_goes_back(
    store: Store,
) -> None:
    """The one window where a slot could be lost silently.

    Between the scheduler handing a lease to the queue and the body
    resuming to take it, the attempt can be cancelled. The lease is spent
    and nothing but that future knows it exists, so the body gives it
    back on its way out.
    """

    pool = PoolState(Pool("test", capacity=1))
    ctx = await attached(store, pool)
    parked = asyncio.Event()
    answered = asyncio.Event()

    async def body() -> None:
        async with ctx.services.lease.released(1):
            parked.set()
            await answered.wait()

    attempt = asyncio.create_task(body())
    await wait_for(parked)
    assert pool.leased == 0

    answered.set()
    await wait_until(lambda: queued(pool))
    # The scheduler hands the lease over and the attempt is cancelled
    # before it is resumed to take it: no await in between.
    handed = pool.drain_readmits()
    attempt.cancel()
    await asyncio.gather(attempt, return_exceptions=True)

    assert len(handed) == 1
    assert handed[0].released
    assert pool.leased == 0, "the pool spent a slot on a waiter that never took it"


async def test_a_second_park_inside_the_first_is_refused(store: Store) -> None:
    """One park per body: the second would release a slot it does not hold."""

    pool = PoolState(Pool("test", capacity=1))
    ctx = await attached(store, pool)

    async with ctx.services.lease.released(1):
        assert ctx.services.lease.waiting
        with pytest.raises(RuntimeError, match="already waiting"):
            async with ctx.services.lease.released(2):  # pragma: no cover - it raises
                pass
        # The pool's slot is still the one the first park gave back.
        assert pool.leased == 0
        asyncio.get_running_loop().call_soon(lambda: pool.drain_readmits())

    assert not ctx.services.lease.waiting
    assert pool.leased == 1
    ctx.services.lease.release()
    assert pool.leased == 0


async def test_the_waiting_task_carries_the_request_it_parked_on(
    store: Store,
) -> None:
    """The status is durable before the slot is free, and names the request."""

    pool = PoolState(Pool("test", capacity=1))
    ctx = await attached(store, pool)

    async with ctx.services.lease.released(99):
        async with store.reader() as reader:
            row = await reader.tasks.get(ctx.task_id)
            events = await reader.events.list_for_run(ctx.run_id)
        assert row is not None and row.status == TaskStatus.waiting
        assert [event.name for event in events] == [EventName.task_waiting]
        assert events[0].data == {"node": "ask", "request_id": 99}
        asyncio.get_running_loop().call_soon(lambda: pool.drain_readmits())

    async with store.reader() as reader:
        row = await reader.tasks.get(ctx.task_id)
    assert row is not None and row.status == TaskStatus.in_progress
    ctx.services.lease.release()

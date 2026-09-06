"""A store, and the smallest engine an attempt can run against.

The engine's subject is behaviour over the store, not the store's SQL, so
this suite runs against SQLite only — the backend matrix belongs to
``tests/store`` (13 §Pyramid). A file rather than ``:memory:``, for the
reason ``tests/store/conftest.py`` gives: WAL and a real pool are what the
services meet in production, and an in-memory database has neither.

:class:`StubEngine` is the six members
:func:`~athanore.engine.runner.run_attempt` reads — ``store``,
``settings``, ``live``, ``graphs``, ``requests`` and ``notify()`` — and
nothing else, which is exactly what 17 §T024 asks for: a runner test built on the real
:class:`~athanore.engine.Engine` would be testing the wiring instead of
the attempt. :class:`Harness` adds the two halves of the scheduler this
suite cannot do without — submitting a run and claiming its ready tasks —
so that a test reads as "run this workflow, then look at what the store
says", which is the level the behaviour is specified at.

The ``engines`` fixture is the other half: the real engine, for the
suites whose subject *is* the wiring — recovery, shutdown and the
operator operations (T027). It is a factory rather than one engine
because those tests start a second engine against the same store, which
is what a restart is; every engine it hands out is stopped on the way
out, so no dispatch loop outlives its test.

``start_engine`` and ``run_to_completion`` are what the behaviour suite
(T028) adds on top: register some workflows on a started engine, submit,
and wait for the run to end on the bus. 17 §T028 puts them in
``tests/conftest.py``; they are here because ``engine`` at the root of
``tests/`` is shadowed in both ``tests/engine`` and ``tests/store``,
where it is the SQLAlchemy ``AsyncEngine`` these fixtures are built out
of — a root fixture of that name would be invisible to every test that
wanted it (D112).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.engine import Engine
from athanore.engine.live import LiveRegistry
from athanore.engine.pools import Lease, Pool, PoolState
from athanore.engine.runner import run_attempt
from athanore.engine.services import RequestBackend
from athanore.events.bus import EventBus
from athanore.events.names import EventName
from athanore.graph import Graph
from athanore.requests.service import RequestService
from athanore.settings import AthanoreSettings
from athanore.store.engine import make_engine
from athanore.store.repos.tasks import ClaimedTask
from athanore.store.rows import (
    ArrivalRow,
    EventRow,
    LogEntryRow,
    RunRow,
    RunStatus,
    TaskRow,
)
from athanore.store.tables import metadata
from athanore.store.uow import Store
from athanore.workflow import Workflow

#: Wide enough that a fan-out runs its branches together, which is what
#: the determinism assertions of T024c need.
CAPACITY = 8


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """An empty SQLite database for one test."""

    return f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}"


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema of :data:`athanore.store.tables.metadata`, created."""

    eng = make_engine(db_url)
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def store(engine: AsyncEngine, bus: EventBus) -> Store:
    return Store(engine, bus)


@pytest.fixture
def settings(tmp_path: Path, db_url: str) -> AthanoreSettings:
    """Settings pinned to this test's database and defaults.

    Constructed with every field the engine reads passed explicitly, so
    an ``ATHANORE_*`` variable in the shell that started the container
    cannot change what a test asserts. ``workers`` is one of them from
    T028: it sizes the default pool, and a behaviour test that asserts
    what one slot does would otherwise be at the mercy of the shell.
    """

    return AthanoreSettings(
        root_path=tmp_path,
        db_url=db_url,
        public_url="http://127.0.0.1:4002",
        workers=1,
        max_retries=3,
        stream_flush_interval=0.05,
    )


class StubEngine:
    """The engine as :func:`run_attempt` sees it (17 §T024).

    Satisfies ``athanore.engine.runner.RunnerEngine`` structurally.
    ``notifications`` counts the wake-ups the runner asked for, because
    "the scheduler was notified" is part of the attempt's contract and
    the only observable half of it here.

    ``requests`` is the one member a real host has to supply from outside
    the engine (02 §Layering, T032): ``None`` here means every attempt
    gets the port that raises, which is what the suites that never ask a
    human want.
    """

    def __init__(
        self,
        store: Store,
        settings: AthanoreSettings,
        requests: RequestBackend | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.live = LiveRegistry()
        self.graphs: dict[str, Graph] = {}
        self.notifications = 0
        self.requests = requests

    def notify(self) -> None:
        self.notifications += 1


class Harness:
    """A stub engine plus the two scheduler verbs a runner test needs."""

    def __init__(
        self,
        store: Store,
        settings: AthanoreSettings,
        requests: RequestBackend | None = None,
    ) -> None:
        self.store = store
        self.requests = requests
        self.engine = StubEngine(store, settings, requests)
        self.pool = PoolState(Pool("test", capacity=CAPACITY))

    # -- registration and submission ---------------------------------------

    def register(self, workflow: Workflow) -> Graph:
        """Finalize ``workflow`` and register it (``server.register``)."""

        graph = workflow.finalize()
        self.engine.graphs[graph.name] = graph
        return graph

    async def submit(
        self, workflow: str, payload: Any = None, title: str = "a run"
    ) -> str:
        """A queued run with its start task ready (``ops.submit``, T027a)."""

        graph = self.engine.graphs[workflow]
        node = graph.start_node
        explicit = node.priority is not None
        priority = node.priority if node.priority is not None else -node.generation
        async with self.store.uow() as uow:
            run = await uow.runs.insert(workflow, title)
            await uow.tasks.enqueue(
                run.id, node.name, payload, priority, explicit, lineage=None
            )
        return run.id

    # -- claiming and running ----------------------------------------------

    async def claim(self, limit: int = 1) -> list[ClaimedTask]:
        """Claim up to ``limit`` ready tasks, in dispatch order."""

        async with self.store.uow() as uow:
            return await uow.tasks.claim_ready(limit, sorted(self.engine.graphs))

    def acquire(self, task_id: int) -> Lease:
        """A pool slot for one attempt."""

        lease = self.pool.try_acquire(task_id)
        assert lease is not None, "the test pool ran out of slots"
        return lease

    def spawn(self, claimed: ClaimedTask) -> asyncio.Task[None]:
        """Start an attempt as its own asyncio task, as the scheduler does."""

        lease = self.acquire(claimed.task.id)
        return asyncio.create_task(run_attempt(self.engine, claimed, lease))

    async def attempt(self) -> ClaimedTask:
        """Claim one ready task and run it to the end of its attempt."""

        claimed = await self.claim()
        assert claimed, "nothing is ready to claim"
        await run_attempt(self.engine, claimed[0], self.acquire(claimed[0].task.id))
        return claimed[0]

    async def drain(self, rounds: int = 40) -> None:
        """Run every task the run produces, branches together.

        One round claims everything ready and runs those attempts
        concurrently, which is what makes a fan-out interleave; the loop
        ends when a round claims nothing. ``rounds`` is a fuse: a
        workflow that never settles fails the test rather than the
        session.
        """

        for _ in range(rounds):
            claimed = await self.claim(CAPACITY)
            if not claimed:
                return
            await asyncio.gather(*(self.spawn(one) for one in claimed))
        raise AssertionError(f"the run had not settled after {rounds} rounds")

    # -- reading the store back --------------------------------------------

    async def run(self, run_id: str) -> RunRow:
        async with self.store.reader() as reader:
            row = await reader.runs.get(run_id)
        assert row is not None
        return row

    async def tasks(self, run_id: str) -> list[TaskRow]:
        async with self.store.reader() as reader:
            return await reader.tasks.list_for_run(run_id)

    async def task(self, task_id: int) -> TaskRow:
        async with self.store.reader() as reader:
            row = await reader.tasks.get(task_id)
        assert row is not None
        return row

    async def at(self, run_id: str, node: str) -> list[TaskRow]:
        """Every attempt at ``node``, oldest first."""

        return [task for task in await self.tasks(run_id) if task.node == node]

    async def events(self, run_id: str) -> list[EventRow]:
        async with self.store.reader() as reader:
            return await reader.events.list_for_run(run_id)

    async def event_names(self, run_id: str) -> list[str]:
        return [event.name for event in await self.events(run_id)]

    async def events_named(self, run_id: str, name: str) -> list[EventRow]:
        return [event for event in await self.events(run_id) if event.name == name]

    async def log(self, run_id: str) -> list[LogEntryRow]:
        async with self.store.reader() as reader:
            return await reader.log.list(run_id)

    async def arrivals(
        self, run_id: str, join_node: str, fanout_task: int
    ) -> list[ArrivalRow]:
        async with self.store.reader() as reader:
            return await reader.joins.arrivals(run_id, join_node, fanout_task)

    async def enqueue(
        self,
        run_id: str,
        node: str,
        payload: Any = None,
        priority: int = 0,
        explicit: bool = False,
        attempt: int = 1,
        branch: Sequence[Any] = (),
        lineage: dict[str, Any] | None = None,
    ) -> TaskRow:
        """Put a task on the queue by hand (an operator op, T027b)."""

        async with self.store.uow() as uow:
            return await uow.tasks.enqueue(
                run_id,
                node,
                payload,
                priority,
                explicit,
                attempt=attempt,
                lineage=lineage,
                branch=branch,
            )


@pytest.fixture
def requests_service(store: Store, bus: EventBus) -> RequestService:
    """The one request service a host builds beside the engine (T031).

    In ``tests/engine`` because the engine cannot build one for itself:
    ``athanore.requests`` is its sibling and neither imports the other
    (02 §Layering), so a suite that drives an attempt which asks a human
    composes the pair the same way a host does.
    """

    return RequestService(store, bus)


@pytest.fixture
def harness(
    store: Store, settings: AthanoreSettings, requests_service: RequestService
) -> Harness:
    """A stub engine, a pool, a request service and the store, wired together."""

    return Harness(store, settings, requests_service)


@pytest.fixture
def unwired_harness(store: Store, settings: AthanoreSettings) -> Harness:
    """The same, on an engine composed without a request service (T032).

    What a host that never built one leaves a body with: a request port
    whose every method raises.
    """

    return Harness(store, settings)


#: A tick short enough that a test which waits for one is not waiting
#: long, and long enough that a loop under load is not spinning. Every
#: path that makes work ready calls ``notify()``, so this is the safety
#: net rather than the mechanism.
TICK = 0.02

#: The fuse on every wait in the engine-lifecycle suites. Reached only
#: when something is broken, so it is generous: a slow container must
#: not make these flaky.
DEADLINE = 5.0


@pytest.fixture
async def engines(
    store: Store, settings: AthanoreSettings, bus: EventBus
) -> AsyncIterator[Callable[..., Engine]]:
    """Make real engines against this test's store, and stop all of them.

    The teardown is the point: an engine left started keeps a dispatch
    loop claiming against the next test's database.
    """

    made: list[Engine] = []

    def make(*, tick: float = TICK, requests: RequestBackend | None = None) -> Engine:
        one = Engine(settings, store, bus, requests=requests, tick=tick)
        made.append(one)
        return one

    yield make
    for one in made:
        await one.stop()


#: A run has ended when its row says so. The bus carries the two events
#: that say it (``run.completed``, ``run.failed``); the row is what
#: :func:`_run_to_completion` returns, because an event carries a
#: preview of the outcome and the row carries the outcome.
_RUN_ENDED: Final = (RunStatus.completed, RunStatus.failed)


@pytest.fixture
def start_engine(
    engines: Callable[..., Engine],
) -> Callable[..., Awaitable[Engine]]:
    """Register workflows on a real engine and start it (17 §T028).

    ``await start_engine(wf)`` is ``server.register(wf); await
    engine.start()`` — the whole of what a behaviour test needs before it
    can submit a run. A workflow may name its pool by arriving as a
    ``(workflow, pool)`` pair; one that does not runs on the default
    pool, sized by ``settings.workers`` as it is in production.

    Built on :func:`engines`, so every engine it starts is stopped on the
    way out of the test whatever the test did to it.
    """

    async def start(
        *workflows: Workflow | tuple[Workflow, Pool],
        tick: float = TICK,
        requests: RequestBackend | None = None,
    ) -> Engine:
        engine = engines(tick=tick, requests=requests)
        for entry in workflows:
            workflow, pool = entry if isinstance(entry, tuple) else (entry, None)
            engine.register(workflow.finalize(), pool)
        await engine.start()
        return engine

    return start


@pytest.fixture
def run_to_completion(
    store: Store, bus: EventBus
) -> Callable[[str], Awaitable[RunRow]]:
    """Wait for ``run_id`` to end, and return the run row it ended as.

    The bus rather than a poll: a suite that drives whole runs waits far
    more often than it reads, and a poll interval is either a slow suite
    or a flaky one. ``run.completed`` and ``run.failed`` are the two
    events that end a run (03 invariant 4), and the subscription is taken
    **before** the first read of the row, so a run that finished between
    the submission and this call is seen in the store rather than waited
    for forever. Any run's ending wakes the wait and the row is re-read;
    the store is what answers, never the event.

    Raises :exc:`TimeoutError` under :data:`DEADLINE`, which is a
    deadlocked run rather than a slow one.
    """

    async def wait(run_id: str) -> RunRow:
        subscription = bus.subscribe(
            [EventName.run_completed.value, EventName.run_failed.value]
        )
        try:
            async with asyncio.timeout(DEADLINE):
                while True:
                    async with store.reader() as reader:
                        row = await reader.runs.get(run_id)
                    if row is not None and row.status in _RUN_ENDED:
                        return row
                    await subscription.queue.get()
        finally:
            subscription.close()

    return wait


async def _wait_until(check: Callable[[], Awaitable[bool]]) -> None:
    """Poll ``check`` until it is true, or fail the test.

    A poll rather than an event: what these suites wait for is a row the
    engine wrote, not a moment in a body.
    """

    async with asyncio.timeout(DEADLINE):
        while True:
            if await check():
                return
            await asyncio.sleep(0.005)


async def _wait_for(event: asyncio.Event) -> None:
    """Wait for ``event``, or fail the test."""

    async with asyncio.timeout(DEADLINE):
        await event.wait()


@pytest.fixture
def wait_until() -> Callable[[Callable[[], Awaitable[bool]]], Awaitable[None]]:
    """Poll a condition until it holds, under :data:`DEADLINE`.

    A fixture rather than an import: ``tests/engine`` is not a package,
    so a helper shared between its modules arrives through pytest or not
    at all.
    """

    return _wait_until


@pytest.fixture
def wait_for() -> Callable[[asyncio.Event], Awaitable[None]]:
    """Wait for an :class:`asyncio.Event`, under :data:`DEADLINE`."""

    return _wait_for

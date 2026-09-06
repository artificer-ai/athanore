"""A store, a request service, and the smallest engine a body can ask from.

``tests/requests/test_service.py`` and ``test_validators.py`` need none of
this: the service is an object over a store and the validators are pure
functions. ``human_input`` (T033) is the other kind of subject — it is the
seam between the request channel, the ``TaskContext`` a body runs under
and the pool slot that body holds — so its tests need an attempt to run
inside, and a pool with the one worker whose slot is the point.

:class:`Fleet` is that: ``athanore.engine.scheduler.SchedulerEngine`` and
nothing else, with the request service the composition root supplies
(``athanore.requests`` is the engine's sibling and neither imports the
other, 02 §Layering). It is used two ways, which is why it is here rather
than in either file:

- **started**, when the subject is what the scheduler does with a parked
  body — the slot it hands to the next task, and the queue it takes back
  from (``test_human_input.py``);
- **unstarted**, when the subject is a crash — claim a task, run its
  attempt as an asyncio task of the test's own, cancel it mid-wait, and
  run it again (``test_human_input_replay.py``). A scheduler running the
  attempt would own that task, and the test needs to be the one that
  kills it.

It is deliberately not ``tests/engine/conftest.py``'s ``Harness``: a
sibling suite's conftest is not importable (``tests`` is not a package),
and the two want different things anyway — the harness has no pools and
this has no fan-out helpers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from athanore.engine.live import LiveRegistry
from athanore.engine.pools import Lease, Pool, PoolRegistry, PoolState
from athanore.engine.runner import run_attempt
from athanore.engine.scheduler import Scheduler
from athanore.events.bus import EventBus
from athanore.graph import Graph
from athanore.requests.service import RequestService
from athanore.settings import AthanoreSettings
from athanore.store.engine import make_engine
from athanore.store.repos.tasks import ClaimedTask
from athanore.store.rows import EventRow, RequestRow, RunStatus, TaskRow, TaskStatus
from athanore.store.tables import metadata
from athanore.store.uow import Store
from athanore.workflow import Workflow

#: Short enough not to pace a test, long enough not to spin. Every
#: wake-up that matters comes from ``notify()``; this is the safety net.
TICK = 0.02

#: The fuse on every wait in this suite. Reached only when something is
#: broken, so it is generous: a slow container must not make these flaky.
DEADLINE = 5.0


@pytest.fixture
async def store(tmp_path: Path, bus: EventBus) -> AsyncIterator[Store]:
    """A store on an empty SQLite file, publishing to :func:`bus`.

    SQLite only: nothing here is a statement about a dialect, and the
    backend matrix belongs to the suite that owns the SQL.
    """

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield Store(engine, bus)
    finally:
        await engine.dispose()


@pytest.fixture
def bus() -> EventBus:
    """The one bus: the store publishes to it and the waiters read it."""

    return EventBus()


@pytest.fixture
def settings(tmp_path: Path) -> AthanoreSettings:
    """Settings with every field these tests read passed explicitly.

    ``workers=1`` is not a default here, it is the subject: the slot a
    waiting body gives back is the only one there is.
    """

    return AthanoreSettings(
        root_path=tmp_path,
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}",
        public_url="http://127.0.0.1:4002",
        workers=1,
        max_retries=3,
        stream_flush_interval=0.05,
    )


@pytest.fixture
def service(store: Store, bus: EventBus) -> RequestService:
    """The one request service a host builds beside its engine (T031)."""

    return RequestService(store, bus)


class Fleet:
    """A stub engine with real pools, a real scheduler and a real service."""

    def __init__(
        self,
        store: Store,
        settings: AthanoreSettings,
        requests: RequestService,
        pools: Mapping[str, int],
        *,
        tick: float,
    ) -> None:
        self.store = store
        self.settings = settings
        self.live = LiveRegistry()
        self.graphs: dict[str, Graph] = {}
        self.requests = requests
        self.pools = PoolRegistry()
        for name, capacity in pools.items():
            self.pools.add(Pool(name, capacity=capacity))
        self.scheduler = Scheduler(self, tick=tick)

    def notify(self) -> None:
        self.scheduler.notify()

    # -- registration and submission ---------------------------------------

    def register(self, workflow: Workflow, pool: str = "test") -> Graph:
        graph = workflow.finalize()
        self.graphs[graph.name] = graph
        self.pools.bind(graph.name, pool)
        return graph

    def register_body(
        self,
        name: str,
        body: Callable[[], Awaitable[Any]],
        *,
        pool: str = "test",
        timeout: float | None = None,
        retries: int = 0,
    ) -> Graph:
        """Register a one-node workflow whose only node awaits ``body()``.

        ``retries=0`` because a body that raises in these tests is a
        failure to read, not a failure to retry.
        """

        workflow = Workflow(name)

        @workflow.node(start=True, timeout=timeout, retries=retries)
        async def only() -> Any:
            return await body()

        return self.register(workflow, pool)

    async def submit(self, workflow: str, title: str = "a run") -> str:
        """A queued run with its start task ready (``ops.submit``, T027a)."""

        graph = self.graphs[workflow]
        node = graph.start_node
        explicit = node.priority is not None
        priority = node.priority if node.priority is not None else -node.generation
        async with self.store.uow() as uow:
            run = await uow.runs.insert(graph.name, title)
            await uow.tasks.enqueue(
                run.id, node.name, None, priority, explicit, lineage=None
            )
        self.notify()
        return run.id

    # -- running an attempt by hand ----------------------------------------

    async def claim(self, limit: int = 1) -> list[ClaimedTask]:
        """Claim up to ``limit`` ready tasks, in dispatch order."""

        async with self.store.uow() as uow:
            return await uow.tasks.claim_ready(limit, sorted(self.graphs))

    def acquire(self, task_id: int, pool: str = "test") -> Lease:
        lease = self.pools.get(pool).try_acquire(task_id)
        assert lease is not None, "the test pool ran out of slots"
        return lease

    def spawn(self, claimed: ClaimedTask) -> asyncio.Task[None]:
        """Start one attempt as its own asyncio task, as the scheduler does.

        The test owns the task, which is what lets it be cancelled where a
        crash would have ended it.
        """

        return asyncio.create_task(
            run_attempt(self, claimed, self.acquire(claimed.task.id))
        )

    async def recover(self) -> list[int]:
        """What startup recovery does to the rows a crash left behind."""

        async with self.store.uow() as uow:
            return await uow.tasks.reset_for_recovery()

    # -- reading the store back --------------------------------------------

    def pool(self, name: str = "test") -> PoolState:
        return self.pools.get(name)

    async def only_task(self, run_id: str) -> TaskRow:
        async with self.store.reader() as reader:
            (task,) = await reader.tasks.list_for_run(run_id)
        return task

    async def status(self, run_id: str) -> TaskStatus:
        return TaskStatus((await self.only_task(run_id)).status)

    async def task(self, task_id: int) -> TaskRow:
        async with self.store.reader() as reader:
            row = await reader.tasks.get(task_id)
        assert row is not None
        return row

    async def is_completed(self, run_id: str) -> bool:
        async with self.store.reader() as reader:
            run = await reader.runs.get(run_id)
        assert run is not None
        return run.status == RunStatus.completed

    async def events_named(self, run_id: str, name: str) -> list[EventRow]:
        async with self.store.reader() as reader:
            rows = await reader.events.list_for_run(run_id)
        return [row for row in rows if row.name == name]

    async def log_texts(self, run_id: str) -> list[str]:
        async with self.store.reader() as reader:
            return [entry.text for entry in await reader.log.list(run_id)]

    async def requests_of(self, run_id: str) -> list[RequestRow]:
        """Every request of ``run_id``, oldest first, as rows.

        Rows rather than views: ``ordinal`` is the column these tests are
        about and a view does not carry it.
        """

        async with self.store.reader() as reader:
            views = await reader.requests.list_views(run_id)
            rows = [await reader.requests.get(view.id) for view in views]
        return [row for row in rows if row is not None]

    # -- waiting for the body to get somewhere -----------------------------

    async def asked(self, run_id: str, count: int = 1) -> list[RequestRow]:
        """The run's requests, once ``count`` of them exist.

        The store rather than an event, for the reason
        ``run_to_completion`` gives in ``tests/engine``: what a test waits
        for here is a row the body wrote.
        """

        await _wait_until(lambda: self._has_requests(run_id, count))
        return await self.requests_of(run_id)

    async def only_asked(self, run_id: str) -> RequestRow:
        """The one request the run has opened, once it has opened it."""

        (row,) = await self.asked(run_id)
        return row

    async def finished(self, run_id: str) -> Any:
        """Wait for the run to complete, and hand back its node's result."""

        await _wait_until(lambda: self.is_completed(run_id))
        return (await self.only_task(run_id)).result

    async def parked(self, run_id: str) -> bool:
        """Whether the run's one task is ``waiting`` right now."""

        return await self.status(run_id) is TaskStatus.waiting

    async def idle(self, name: str = "test") -> bool:
        """Whether ``name`` has every one of its slots back."""

        state = self.pool(name)
        return state.leased == 0 and state.free() == state.capacity

    async def queued(self, count: int = 1, name: str = "test") -> bool:
        """Whether ``count`` waiters are in the pool's re-admit queue."""

        return len(self.pool(name).readmit) == count

    async def _has_requests(self, run_id: str, count: int) -> bool:
        return len(await self.requests_of(run_id)) >= count


@pytest.fixture
async def fleet(
    store: Store, settings: AthanoreSettings, service: RequestService
) -> AsyncIterator[Callable[..., Fleet]]:
    """Make fleets, and stop every scheduler they started."""

    made: list[Fleet] = []

    def make(pools: Mapping[str, int] | None = None, *, tick: float = TICK) -> Fleet:
        one = Fleet(store, settings, service, pools or {"test": 1}, tick=tick)
        made.append(one)
        return one

    yield make
    for one in made:
        await one.scheduler.stop()


async def _wait_for(event: asyncio.Event) -> None:
    """Wait for ``event``, or fail the test."""

    async with asyncio.timeout(DEADLINE):
        await event.wait()


async def _wait_until(check: Callable[[], Awaitable[bool]]) -> None:
    """Poll ``check`` until it is true, or fail the test.

    A poll rather than an event: what these tests wait for is a row the
    engine wrote, not a moment in a body.
    """

    async with asyncio.timeout(DEADLINE):
        while True:
            if await check():
                return
            await asyncio.sleep(0.005)


@pytest.fixture
def wait_until() -> Callable[[Callable[[], Awaitable[bool]]], Awaitable[None]]:
    """Poll a condition until it holds, under :data:`DEADLINE`.

    A fixture rather than an import: ``tests/requests`` is not a package,
    so a helper shared between its modules arrives through pytest or not
    at all (D112).
    """

    return _wait_until


@pytest.fixture
def wait_for() -> Callable[[asyncio.Event], Awaitable[None]]:
    """Wait for an :class:`asyncio.Event`, under :data:`DEADLINE`."""

    return _wait_for

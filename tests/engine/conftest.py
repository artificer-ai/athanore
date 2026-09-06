"""A store, and the smallest engine an attempt can run against.

The engine's subject is behaviour over the store, not the store's SQL, so
this suite runs against SQLite only — the backend matrix belongs to
``tests/store`` (13 §Pyramid). A file rather than ``:memory:``, for the
reason ``tests/store/conftest.py`` gives: WAL and a real pool are what the
services meet in production, and an in-memory database has neither.

:class:`StubEngine` is the five members
:func:`~athanore.engine.runner.run_attempt` reads — ``store``,
``settings``, ``live``, ``graphs`` and ``notify()`` — and nothing else,
which is exactly what 17 §T024 asks for: the real ``Engine`` is T027's,
and a runner test that needed it would be testing the wiring instead of
the attempt. :class:`Harness` adds the two halves of the scheduler this
suite cannot do without — submitting a run and claiming its ready tasks —
so that a test reads as "run this workflow, then look at what the store
says", which is the level the behaviour is specified at.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.engine.live import LiveRegistry
from athanore.engine.pools import Lease, Pool, PoolState
from athanore.engine.runner import run_attempt
from athanore.events.bus import EventBus
from athanore.graph import Graph
from athanore.settings import AthanoreSettings
from athanore.store.engine import make_engine
from athanore.store.repos.tasks import ClaimedTask
from athanore.store.rows import (
    ArrivalRow,
    EventRow,
    LogEntryRow,
    RunRow,
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

    Constructed with every field the runner reads passed explicitly, so
    an ``ATHANORE_*`` variable in the shell that started the container
    cannot change what a test asserts.
    """

    return AthanoreSettings(
        root_path=tmp_path,
        db_url=db_url,
        public_url="http://127.0.0.1:4002",
        max_retries=3,
        stream_flush_interval=0.05,
    )


class StubEngine:
    """The engine as :func:`run_attempt` sees it (17 §T024).

    Satisfies ``athanore.engine.runner.RunnerEngine`` structurally.
    ``notifications`` counts the wake-ups the runner asked for, because
    "the scheduler was notified" is part of the attempt's contract and
    the only observable half of it here.
    """

    def __init__(self, store: Store, settings: AthanoreSettings) -> None:
        self.store = store
        self.settings = settings
        self.live = LiveRegistry()
        self.graphs: dict[str, Graph] = {}
        self.notifications = 0

    def notify(self) -> None:
        self.notifications += 1


class Harness:
    """A stub engine plus the two scheduler verbs a runner test needs."""

    def __init__(self, store: Store, settings: AthanoreSettings) -> None:
        self.store = store
        self.engine = StubEngine(store, settings)
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
def harness(store: Store, settings: AthanoreSettings) -> Harness:
    """A stub engine, a pool and the store, wired together."""

    return Harness(store, settings)

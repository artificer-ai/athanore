"""A store, an engine, and an application with plugins mounted on it.

The same shape as `tests/api/conftest.py` — a real `create_app()` spoken
to over ASGI — with two differences that the subject needs. The engine is
registered on *and started*, because the ``on`` dispatch tests want a run
that really completes; and the application is built from validated
`PluginSpec`s, because that is what a host hands `create_app`.

`app_with` is the one fixture most suites use: it takes the workflows,
registers them, collects and validates their declarations, and returns a
client speaking to the application that resulted. Registration through
the real `collect` + `validate` pair is deliberate — a suite that built a
`PluginSpec` by hand would be testing a shape no host produces.

`live_app` is the other: a serving application with only the builtins
mounted, for the suite that adds and removes a workflow's surface while
it serves (22 §Live mounting).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from athanore.api.app import create_app
from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.events.bus import EventBus
from athanore.events.names import EventName
from athanore.plugins.builtin import with_builtins
from athanore.plugins.registry import PluginSpec, collect, validate
from athanore.settings import AthanoreSettings
from athanore.store.engine import make_engine
from athanore.store.rows import RunRow, RunStatus
from athanore.store.tables import metadata
from athanore.store.uow import Store
from athanore.workflow import Workflow

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 5.0

#: A tick short enough that a test does not wait on it.
TICK = 0.02


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """An empty SQLite database for one test."""

    return f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}"


@pytest.fixture
async def sa_engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema of `athanore.store.tables.metadata`, created."""

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
def store(sa_engine: AsyncEngine, bus: EventBus) -> Store:
    return Store(sa_engine, bus)


@pytest.fixture
def settings(tmp_path: Path, db_url: str) -> AthanoreSettings:
    """A plain loopback bind, pinned to this test's database."""

    return AthanoreSettings(
        root_path=tmp_path,
        db_url=db_url,
        public_url="http://127.0.0.1:4002",
        workers=2,
        stream_flush_interval=0.05,
    )


@pytest.fixture
def engine(settings: AthanoreSettings, store: Store, bus: EventBus) -> Engine:
    """An engine with nothing registered and no loop running."""

    return Engine(settings, store, bus, tick=TICK)


@pytest.fixture
async def app_with(
    settings: AthanoreSettings, engine: Engine, store: Store
) -> AsyncIterator[Callable[..., Awaitable[httpx.AsyncClient]]]:
    """Register workflows, mount their plugins, and drive the application.

    ``await app_with(wf, start=True)`` is `server.register(wf)` followed
    by `create_app(...)`: finalize, collect, validate, register on the
    engine, build the app. The lifespan is run — it is what starts the
    ``on`` dispatcher — and shut down on the way out, and the engine is
    stopped whatever the test did to it.
    """

    stack: list[Callable[[], Awaitable[None]]] = []

    async def make(
        *workflows: Workflow,
        start: bool = False,
        extra: Sequence[PluginSpec] = (),
    ) -> httpx.AsyncClient:
        specs: list[PluginSpec] = []
        for workflow in workflows:
            graph = workflow.finalize()
            spec = collect(workflow)
            validate(spec, graph)
            engine.register(graph, Pool("test", settings.workers))
            specs.append(spec)
        # Specs a test supplies directly: the builtin scope of 09 is not
        # a registered workflow, so it cannot arrive any other way.
        specs.extend(extra)
        app: FastAPI = create_app(
            settings=settings, engine=engine, store=store, plugins=specs
        )
        if start:
            await engine.start()
        stack.append(await _lifespan(app))
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )
        stack.append(client.aclose)
        return client

    try:
        yield make
    finally:
        for close in reversed(stack):
            await close()
        await engine.stop()


@pytest.fixture
async def live_app(
    settings: AthanoreSettings, engine: Engine, store: Store
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """A serving application with the builtins and nothing else mounted.

    What `Server.serve()` has just after boot on a server with no
    workflows: `create_app(..., plugins=with_builtins(()))`, the lifespan
    run (so the dispatcher's one subscription is taken), the engine
    started. A test then registers a workflow on the engine and adds its
    spec to ``app.state.plugins``, which is the order T085's `Server.add`
    does the two in.
    """

    app: FastAPI = create_app(
        settings=settings, engine=engine, store=store, plugins=with_builtins(())
    )
    await engine.start()
    shutdown = await _lifespan(app)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )
    try:
        yield app, client
    finally:
        await client.aclose()
        await shutdown()
        await engine.stop()


async def _lifespan(app: FastAPI) -> Callable[[], Awaitable[None]]:
    """Run ``app``'s lifespan in a task of its own, and return its shutdown.

    A task rather than a bare ``__aenter__`` / ``__aexit__`` pair around
    the test, because the MCP session manager the lifespan starts is an
    anyio task group: entering and leaving it from the two different
    tasks pytest runs a fixture's halves in is exactly the "exit cancel
    scope in a different task" it refuses. One task owns both ends.
    """

    ready: asyncio.Event = asyncio.Event()
    stop: asyncio.Event = asyncio.Event()

    async def serve() -> None:
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    task = asyncio.create_task(serve())
    waiting = asyncio.ensure_future(ready.wait())
    done, _ = await asyncio.wait(
        {task, waiting}, timeout=DEADLINE, return_when=asyncio.FIRST_COMPLETED
    )
    if task in done:  # the lifespan failed on the way up
        waiting.cancel()
        await task
    assert ready.is_set(), "the application's lifespan did not start"

    async def shutdown() -> None:
        stop.set()
        await task

    return shutdown


@pytest.fixture
def run_to_completion(
    store: Store, bus: EventBus
) -> Callable[[str], Awaitable[RunRow]]:
    """Wait for a run to end, and return the row it ended as.

    The bus rather than a poll, and subscribed *before* the first read,
    so a run that finished between the submission and this call is seen
    in the store rather than waited for forever.
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
                    if row is not None and row.status in (
                        RunStatus.completed,
                        RunStatus.failed,
                    ):
                        return row
                    await subscription.queue.get()
        finally:
            subscription.close()

    return wait


@pytest.fixture
def wait_until() -> Callable[[Callable[[], bool]], Awaitable[None]]:
    """Poll a plain condition until it holds, under `DEADLINE`."""

    async def wait(check: Callable[[], bool]) -> None:
        async with asyncio.timeout(DEADLINE):
            while True:
                if check():
                    return
                await asyncio.sleep(0.005)

    return wait
